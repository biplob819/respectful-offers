"""Column contracts for DataFrames crossing a stage boundary (D-11).

A million pydantic objects would be slow, so whole tables are checked column by column:
dtype kind, nullability, range and allowed values. Errors name the stage, column and rule.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

import numpy as np
import pandas as pd

from respectful_offers.schemas.rows import ACTIONS, POLICY_NAMES

Kind = Literal["str", "int", "float", "bool", "date", "actions"]


class ContractError(ValueError):
    """A table broke its column contract. The message names the stage, column and rule."""


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    kind: Kind
    nullable: bool = False
    min: float | None = None
    max: float | None = None
    allowed: frozenset[str] | None = None


@dataclass(frozen=True)
class TableContract:
    name: str
    columns: tuple[ColumnSpec, ...] = field(default_factory=tuple)
    row_rules: tuple[Callable[[pd.DataFrame], str | None], ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)


def _kind_ok(series: pd.Series, kind: Kind) -> bool:
    if kind == "bool":
        return pd.api.types.is_bool_dtype(series)
    if kind == "int":
        return pd.api.types.is_integer_dtype(series) and not pd.api.types.is_bool_dtype(series)
    if kind == "float":
        return pd.api.types.is_float_dtype(series) or (
            pd.api.types.is_integer_dtype(series) and not pd.api.types.is_bool_dtype(series)
        )
    if kind == "date":
        # calendar dates only: naive datetime64 at midnight, or datetime.date (not datetime,
        # time, timedelta or tz-aware timestamps)
        if isinstance(series.dtype, pd.ArrowDtype):
            return str(series.dtype.pyarrow_dtype) in ("date32[day]", "date64[ms]")
        if pd.api.types.is_datetime64_any_dtype(series):
            if getattr(series.dt, "tz", None) is not None:
                return False
            return bool((series.dropna() == series.dropna().dt.normalize()).all())
        return all(type(v) is dt.date for v in series.dropna())
    if kind == "str":
        return pd.api.types.is_string_dtype(series) or pd.api.types.is_object_dtype(series)
    if kind == "actions":
        if isinstance(series.dtype, pd.ArrowDtype):
            return str(series.dtype.pyarrow_dtype).startswith(("list<", "large_list<"))
        return pd.api.types.is_object_dtype(series)
    return False  # pragma: no cover


def check_frame(df: pd.DataFrame, contract: TableContract, stage: str) -> None:
    where = f"{stage}: table {contract.name}"
    dupes = sorted({str(c) for c in df.columns[df.columns.duplicated()]})
    if dupes:
        raise ContractError(f"{where}: duplicated column(s) {dupes}")
    missing = [c for c in contract.names if c not in df.columns]
    extra = [c for c in df.columns if c not in contract.names]
    if missing:
        raise ContractError(f"{where}: missing column(s) {missing}")
    if extra:
        raise ContractError(f"{where}: unexpected column(s) {extra}")
    for spec in contract.columns:
        col = df[spec.name]
        nulls = col.isna()
        if nulls.any() and not spec.nullable:
            raise ContractError(f"{where}: column {spec.name} has {int(nulls.sum())} null(s)")
        values = col[~nulls]
        if len(values) and not _kind_ok(values, spec.kind):  # an empty column has no dtype to check
            raise ContractError(
                f"{where}: column {spec.name} has dtype {col.dtype}, not {spec.kind}"
            )
        if spec.kind == "str" and len(values) and not _all_strings(values):
            raise ContractError(f"{where}: column {spec.name} holds non-string values")
        if spec.kind in ("int", "float") and len(values):
            arr = values.to_numpy(dtype=float)
            if not np.isfinite(arr).all():
                raise ContractError(f"{where}: column {spec.name} has NaN or infinite values")
            if spec.min is not None and arr.min() < spec.min:
                raise ContractError(
                    f"{where}: column {spec.name} has {arr.min()} below minimum {spec.min}"
                )
            if spec.max is not None and arr.max() > spec.max:
                raise ContractError(
                    f"{where}: column {spec.name} has {arr.max()} above maximum {spec.max}"
                )
        if spec.allowed is not None and len(values):
            bad = sorted({str(v) for v in _unique(values)} - spec.allowed)
            if bad:
                raise ContractError(f"{where}: column {spec.name} has values {bad[:5]} not allowed")
        if spec.kind == "actions" and len(values):
            for v in _unique(values):
                ordered = isinstance(v, list | tuple | np.ndarray)
                if not ordered or any(not isinstance(a, str) or a not in ACTIONS for a in v):
                    raise ContractError(
                        f"{where}: column {spec.name} must hold sequences of actions, got {v!r}"
                    )
    for rule in contract.row_rules:
        problem = rule(df)
        if problem:
            raise ContractError(f"{where}: {problem}")


def _all_strings(values: pd.Series) -> bool:
    if pd.api.types.is_string_dtype(values.dtype) and not pd.api.types.is_object_dtype(
        values.dtype
    ):
        return True
    return pd.api.types.infer_dtype(values, skipna=True) in ("string", "empty")


def _key(v: Any) -> Any:
    """A hashable stand-in for a value; unhashable odd values (dicts, sets) stay unique."""
    if isinstance(v, list | np.ndarray):
        try:
            return (type(v).__name__, tuple(v))
        except TypeError:
            return ("id", id(v))
    try:
        hash(v)
    except TypeError:
        return ("id", id(v))
    return (type(v).__name__, v)


def _unique(values: pd.Series) -> list[Any]:
    """The distinct values, checked once each (a rollout's columns repeat a handful of values
    across hundreds of thousands of rows). Unhashable values are kept whole."""
    seen: dict[Any, Any] = {}
    for v in values.tolist():
        seen.setdefault(_key(v), v)
    return list(seen.values())


def _map_unique(series: pd.Series, f: Any) -> pd.Series:
    """`series.map(f)` evaluated once per distinct value."""
    cache: dict[Any, bool] = {}
    out = []
    for v in series.tolist():
        k = _key(v)
        if k not in cache:
            cache[k] = bool(f(v))
        out.append(cache[k])
    return pd.Series(out, index=series.index, dtype=bool)


def _c(name: str, kind: Kind, **kw: object) -> ColumnSpec:
    return ColumnSpec(name, kind, **kw)  # type: ignore[arg-type]


def _first_bad(mask: pd.Series, df: pd.DataFrame, what: str) -> str | None:
    if not mask.any():
        return None
    row = df.loc[mask].iloc[0]
    who = f"member {row['msno']}" if "msno" in df.columns else "a row"
    return f"{int(mask.sum())} row(s) {what} (first: {who})"


def _declined_rule(df: pd.DataFrame) -> str | None:
    def bad(v: Any) -> bool:
        seq = list(v)
        return (
            "no_offer" in seq or len(set(seq)) != len(seq) or seq != sorted(seq, key=ACTIONS.index)
        )

    return _first_bad(
        _map_unique(df["declined"], bad), df, "with declined not a sorted set of shown actions"
    )


def _decision_rules(df: pd.DataFrame) -> str | None:
    def allowed_bad(v: Any) -> bool:
        seq = list(v)
        return (
            not seq
            or "no_offer" not in seq
            or len(set(seq)) != len(seq)
            or seq != sorted(seq, key=ACTIONS.index)
        )

    checks = [
        (
            _map_unique(df["allowed"], allowed_bad),
            "with allowed not an ordered set holding no_offer",
        ),
        (
            pd.Series(
                [c not in a for c, a in zip(df["chosen"], df["allowed"], strict=True)],
                index=df.index,
                dtype=bool,
            ),
            "with chosen outside allowed",
        ),
        (
            pd.Series(
                [r not in a for r, a in zip(df["requested"], df["allowed"], strict=True)],
                index=df.index,
                dtype=bool,
            ),
            "with requested outside allowed",
        ),
        (
            df["budget_downgraded"] != (df["chosen"] != df["requested"]),
            "whose downgrade flag disagrees with the actions",
        ),
        (df["chosen"].eq("no_offer") & df["face_value"].ne(0), "with face value on no_offer"),
    ]
    for mask, what in checks:
        problem = _first_bad(mask, df, what)
        if problem:
            return problem
    return None


def _outcome_rule(df: pd.DataFrame) -> str | None:
    mask = ~df["renewed"].astype(bool) & (df["revenue"].ne(0) | df["discount_cost"].ne(0))
    return _first_bad(mask, df, "that did not renew but have revenue or cost")


_ACTION_SET = frozenset(ACTIONS)
_POLICY_SET = frozenset(POLICY_NAMES)
INF = math.inf

FEATURES = TableContract(
    "features",
    (
        _c("msno", "str"),
        _c("cohort", "str", allowed=frozenset({"feb", "mar"})),
        _c("as_of", "date"),
        _c("tenure_days", "int", min=0),
        _c("auto_renew", "bool"),
        _c("cancels_90d", "int", min=0),
        _c("listening_trend_30d", "float", min=-1.0),
        _c("price_30d", "float", min=0.0),
        _c("plan_days", "int", min=1),
        _c("churn_label", "bool"),
    ),
)
AUDIT_ATTRIBUTES = TableContract(
    "audit_attributes",
    (
        _c("msno", "str"),
        _c(
            "age_band",
            "str",
            allowed=frozenset({"<18", "18-24", "25-34", "35-44", "45+", "unknown"}),
        ),
        _c("gender", "str", allowed=frozenset({"female", "male", "unknown"})),
    ),
)
MEMBER_STATES = TableContract(
    "member_states",
    (
        _c("msno", "str"),
        _c("period", "int", min=1),
        _c("active", "bool"),
        _c("in_holdout", "bool"),
        _c("churn_risk", "float", min=0.0, max=1.0),
        _c("risk_band", "str", allowed=frozenset({"low", "medium", "high"})),
        _c("trend_band", "str", allowed=frozenset({"declining", "stable"})),
        _c("declined", "actions"),
        _c("nudged", "bool"),
        _c("price_30d", "float", min=0.0),
        _c("plan_multiplier", "float", min=1e-12, max=1.0),
    ),
    (_declined_rule,),
)
DECISIONS = TableContract(
    "decisions",
    (
        _c("run_id", "str"),
        _c("variant", "str"),
        _c("policy", "str", allowed=_POLICY_SET),
        _c("msno", "str"),
        _c("period", "int", min=1),
        _c("allowed", "actions"),
        _c("requested", "str", allowed=_ACTION_SET),
        _c("chosen", "str", allowed=_ACTION_SET),
        _c("propensity", "float", min=1e-12, max=1.0),
        _c("budget_downgraded", "bool"),
        _c("face_value", "float", min=0.0),
    ),
    (_decision_rules,),
)
OUTCOMES = TableContract(
    "outcomes",
    (
        _c("run_id", "str"),
        _c("variant", "str"),
        _c("policy", "str", allowed=_POLICY_SET),
        _c("msno", "str"),
        _c("period", "int", min=1),
        _c("response", "str", allowed=frozenset({"accepted", "declined", "not_shown"})),
        _c("renewed", "bool"),
        _c("revenue", "float", min=0.0),
        _c("discount_cost", "float", min=0.0),
    ),
    (_outcome_rule,),
)

CONTRACTS: Mapping[str, TableContract] = MappingProxyType(
    {c.name: c for c in (FEATURES, AUDIT_ATTRIBUTES, MEMBER_STATES, DECISIONS, OUTCOMES)}
)
