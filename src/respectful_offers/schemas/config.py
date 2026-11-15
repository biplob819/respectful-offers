"""`RunConfig` and the YAML loaders (Tech Spec §3). Every load error names the file and key."""

from __future__ import annotations

import itertools
import json
import math
import re
from pathlib import Path
from typing import Any, Self, TypeVar

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from respectful_offers.schemas._base import FrozenMap, Model, Name, Versioned
from respectful_offers.schemas.rows import PROTECTED_ATTRIBUTES
from respectful_offers.schemas.simulator import SimulatorConfig

COHORTS = ("holdout", "train", "logging", "eval")


class ConfigError(ValueError):
    """A configuration file is missing, unreadable or invalid. The message names file and key."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys instead of keeping the last one."""


def _construct_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            hash(key)
        except TypeError:
            raise ConfigError(
                f"unhashable key {key!r} (line {key_node.start_mark.line + 1})"
            ) from None
        if not isinstance(key, str):
            raise ConfigError(f"key {key!r} must be a string (line {key_node.start_mark.line + 1})")
        if key in seen:
            raise ConfigError(f"duplicate key {key!r} (line {key_node.start_mark.line + 1})")
        seen.add(key)
    return loader.construct_mapping(node, deep=deep)


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,  # type: ignore[arg-type]
)


def load_yaml(path: Path) -> Any:
    path = Path(path)
    if path.is_dir():
        raise ConfigError(f"{path}: is a directory, not a YAML file")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read ({exc.strerror})") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{path}: not UTF-8 text") from exc
    try:
        return yaml.load(text, Loader=_UniqueKeyLoader)
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML ({exc})") from exc


M = TypeVar("M", bound=BaseModel)


def _validate(model: type[M], data: Any, path: Path) -> M:
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    bad = _first_non_json(data, "")
    if bad is not None:
        key, value = bad
        raise ConfigError(
            f"{path}: {key or '(top level)'}: {type(value).__name__} is not plain YAML data "
            "(quote dates and use text, numbers, booleans, lists and mappings only)"
        )
    text = json.dumps(data, allow_nan=True)
    try:
        return model.model_validate_json(text)
    except ValidationError as exc:
        parts = []
        for err in exc.errors():
            key = ".".join(str(p) for p in err["loc"]) or "(top level)"
            parts.append(f"{key}: {err['msg']}")
        raise ConfigError(f"{path}: " + "; ".join(parts)) from exc


class RunConfig(Versioned):
    seed: int = Field(ge=0, strict=True)
    holdout_salt: Name
    cohort_buckets: FrozenMap[tuple[int, int]]
    eval_sample: int | None = Field(default=200_000, ge=1)
    horizon_periods: int = Field(default=3, ge=1, le=12, strict=True)
    risk_threshold: float = Field(gt=0.0, lt=1.0, allow_inf_nan=False)
    budget_per_1000_per_period: float = Field(ge=0.0, allow_inf_nan=False)
    budget_sweep: tuple[float, ...] = ()
    variants: tuple[Name, ...] = Field(
        default=("conservative", "central", "optimistic"), min_length=1
    )
    decision_features: tuple[Name, ...] = Field(min_length=1)
    ts_prior_precision: float = Field(gt=0.0, allow_inf_nan=False)
    ts_noise_variance: float = Field(gt=0.0, allow_inf_nan=False)
    ts_integration_nodes: int = Field(default=32, ge=16, le=256, strict=True)
    ts_support_floor: float = Field(default=0.001, gt=0.0, le=0.05, allow_inf_nan=False)
    bootstrap_blocks: int = Field(default=1_000, ge=20, strict=True)  # OPE needs 20 (D-36)
    bootstrap_resamples: int = Field(default=10_000, ge=100, strict=True)

    @field_validator("budget_sweep")
    @classmethod
    def _sweep(cls, v: tuple[float, ...]) -> tuple[float, ...]:
        if any(not math.isfinite(b) or b < 0 for b in v):
            raise ValueError("budget levels must be finite and non-negative")
        if list(v) != sorted(set(v)):
            raise ValueError("budget levels must be distinct and increasing")
        return v

    @field_validator("decision_features")
    @classmethod
    def _no_protected(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        bad = sorted(f for f in v if protected_name(f))
        if bad:
            raise ValueError(f"protected or proxy attributes cannot be decision features: {bad}")
        if len(set(v)) != len(v):
            raise ValueError("decision features must not repeat")
        return v

    @field_validator("variants")
    @classmethod
    def _distinct_variants(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(v)) != len(v):
            raise ValueError("variants must not repeat")
        return v

    @model_validator(mode="after")
    def _buckets_partition(self) -> Self:
        names = set(self.cohort_buckets)
        if names != set(COHORTS):
            raise ValueError(
                f"cohort_buckets must name exactly {list(COHORTS)}, got {sorted(names)}"
            )
        spans = sorted(self.cohort_buckets.values())
        edge = 0
        for lo, hi in spans:
            if lo != edge or hi <= lo:
                raise ValueError(
                    f"cohort_buckets must tile 0..100 without gaps or overlaps, got {spans}"
                )
            edge = hi
        if edge != 100:
            raise ValueError(f"cohort_buckets must end at 100, got {edge}")
        return self


def _first_non_json(value: Any, key: str) -> tuple[str, Any] | None:
    if isinstance(value, dict):
        for k, v in value.items():
            found = _first_non_json(v, f"{key}.{k}" if key else str(k))
            if found:
                return found
        return None
    if isinstance(value, list):
        for i, v in enumerate(value):
            found = _first_non_json(v, f"{key}[{i}]")
            if found:
                return found
        return None
    if value is None or isinstance(value, str | int | float | bool):
        return None
    return key, value


# Protected or identifying attributes and their usual proxies, matched as whole words or
# adjacent word pairs (D-37). The auditor keeps its own copy of this list, written apart
# (audit.py); a test proves the two agree. "age" is protected as a word, so a tenure
# feature must be named `tenure_*`, not `account_age_*`.
_PROTECTED_WORDS = PROTECTED_ATTRIBUTES | {
    "msno",
    "sex",
    "gndr",
    "birth",
    "dob",
    "yob",
    "registered",
    "registration",
    "reg_via",
    "city",
    "region",
    "location",
    "zip",
    "postcode",
    "user_id",
}


def protected_name(name: str) -> bool:
    """True if a feature name is, or contains as a word, a protected or identifying attribute.

    Words come from snake_case, kebab-case and camelCase (`userGender`, `registeredVia`,
    `age_band2`, `Gender`), and adjacent pairs are joined to catch two-word attributes such
    as `registered_via_code`. `msno` is an identifier, never a feature.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    words = [w for w in re.split(r"[^a-z0-9]+|(?<=[a-z])(?=[0-9])", spaced.lower()) if w]
    pairs = {f"{a}_{b}" for a, b in itertools.pairwise(words)}
    return bool((set(words) | pairs | {name.lower()}) & _PROTECTED_WORDS)


def load_run_config(path: Path) -> RunConfig:
    return _validate(RunConfig, load_yaml(path), Path(path))


def load_simulator_config(path: Path) -> SimulatorConfig:
    return _validate(SimulatorConfig, load_yaml(path), Path(path))


__all__ = [
    "COHORTS",
    "ConfigError",
    "Model",
    "RunConfig",
    "load_run_config",
    "load_simulator_config",
    "load_yaml",
]
