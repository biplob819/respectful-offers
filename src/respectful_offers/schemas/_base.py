"""Shared base model, strict field types and version helpers for every Respectful Offers schema.

Models are deeply immutable: list fields are tuples, dict fields become `FrozenDict`,
and free-form JSON values (`JsonValue`) are frozen recursively. That keeps an object's
JSON identical from the moment it is cached (N1.3) to the moment it is read back.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from typing import Annotated, Any, NoReturn, TypeVar

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

SCHEMA_VERSION = "1.0"
VERSION_PATTERN = r"^\d+\.\d+$"


class FrozenDict(dict):
    """A dict that refuses mutation and can be hashed."""

    def _blocked(self, *_: Any, **__: Any) -> NoReturn:
        raise TypeError("schema objects are immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _blocked  # type: ignore[assignment]
    __ior__ = _blocked  # type: ignore[assignment]

    def __hash__(self) -> int:  # type: ignore[override]
        return hash(frozenset(self.items()))

    # pickle, copy.deepcopy and model_copy(deep=True) rebuild a dict subclass through
    # __setitem__, which is blocked; rebuild from a plain dict instead.
    def __reduce__(self) -> tuple[Any, ...]:
        return (FrozenDict, (dict(self),))

    def __deepcopy__(self, memo: dict[int, Any]) -> FrozenDict:
        import copy

        return FrozenDict({copy.deepcopy(k, memo): copy.deepcopy(v, memo) for k, v in self.items()})

    def __copy__(self) -> FrozenDict:
        return self

    def __iter__(self) -> Iterator[Any]:
        return super().__iter__()


def deep_freeze(value: Any) -> Any:
    """Recursively turn lists into tuples and dicts into FrozenDicts; reject sets."""
    if isinstance(value, Mapping):
        return FrozenDict({k: deep_freeze(v) for k, v in value.items()})
    if isinstance(value, list | tuple):
        return tuple(deep_freeze(v) for v in value)
    if isinstance(value, set | frozenset):
        raise ValueError("sets are not JSON values; use a list")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("NaN and infinity are not allowed")
    return value


def _freeze_mapping(value: Mapping[Any, Any]) -> FrozenDict:
    # sorted keys: equal objects must dump identical JSON (content-addressed caching)
    return FrozenDict(sorted(value.items(), key=lambda kv: str(kv[0])))


# Strict scalar types: no bool-as-int, no "5"-as-5, no NaN or infinity.
NonNegInt = Annotated[int, Field(ge=0, strict=True)]
PosInt = Annotated[int, Field(ge=1, strict=True)]
StrictInt = Annotated[int, Field(strict=True)]
NonNegFloat = Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
Fraction = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
Name = Annotated[str, StringConstraints(min_length=1, pattern=r"^\S(.*\S)?$")]  # no edge spaces
Timestamp = AwareDatetime  # naive timestamps are ambiguous across machines

# Free-form JSON (tool arguments, gold rows): frozen recursively, sets rejected.
JsonValue = Annotated[Any, AfterValidator(deep_freeze)]


V = TypeVar("V")

# `dict[str, V]` that validates into a FrozenDict: FrozenMap[Interval], FrozenMap[bool], ...
FrozenMap = Annotated[dict[str, V], AfterValidator(_freeze_mapping)]


class Model(BaseModel):
    """Frozen, strict base: unknown fields are errors, objects are immutable, floats finite."""

    # strict: no "5000"-as-float, no bool-as-number, no set-as-tuple, no int-as-date (N1.1
    # verifier). Python callers pass real types; files are validated in JSON mode, where
    # arrays fill tuples and ISO strings fill dates.
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False, strict=True)


class Versioned(Model):
    """A top-level file record that carries the results-format version. It is required."""

    schema_version: Annotated[str, StringConstraints(pattern=VERSION_PATTERN)]

    @field_validator("schema_version")
    @classmethod
    def _same_major(cls, v: str) -> str:
        if v.split(".", 1)[0] != SCHEMA_VERSION.split(".", 1)[0]:
            raise ValueError(
                f"results format {v} is not compatible with this version of respectful-offers "
                f"(expects {SCHEMA_VERSION.split('.')[0]}.x)"
            )
        return v
