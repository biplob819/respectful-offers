"""The response simulator's configuration (Tech Spec §5.3), validated for structure only.

Whether effects run in their documented direction and whether the variants are ordered as
named is A2.2's job (SIM-06); this module only guarantees that every cell, segment and
action is present and that every number is a valid probability or effect.
"""

from __future__ import annotations

import itertools
import math
import re
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from respectful_offers.schemas._base import Fraction, FrozenMap, Model, Versioned

Segment = Literal["sure_thing", "persuadable", "lost_cause", "sleeping_dog"]
SEGMENTS: tuple[Segment, ...] = ("sure_thing", "persuadable", "lost_cause", "sleeping_dog")
RISK_BANDS = ("low", "medium", "high")
TREND_BANDS = ("stable", "declining")
CELLS: tuple[str, ...] = tuple(f"{r}.{t}" for r in RISK_BANDS for t in TREND_BANDS)
OFFER_ACTIONS = ("content_nudge", "discount_1m", "plan_change")
MIX_TOLERANCE = 1e-9

Effect = float


def _check_segments(where: str, row: dict[str, float], lo: float, hi: float) -> None:
    missing = [s for s in SEGMENTS if s not in row]
    extra = sorted(set(row) - set(SEGMENTS))
    if missing or extra:
        raise ValueError(f"{where}: missing segments {missing} / unknown segments {extra}")
    for seg, value in row.items():
        if not math.isfinite(value) or not lo <= value <= hi:
            raise ValueError(f"{where}.{seg}: {value} is outside [{lo}, {hi}]")


def _check_actions(where: str, table: dict[str, dict[str, float]], actions: tuple[str, ...]):
    missing = [a for a in actions if a not in table]
    extra = sorted(set(table) - set(actions))
    if missing or extra:
        raise ValueError(f"{where}: missing actions {missing} / unknown actions {extra}")


class Bands(Model):
    cuts: tuple[float, ...] = Field(min_length=1)

    @field_validator("cuts")
    @classmethod
    def _increasing(cls, v: tuple[float, ...]) -> tuple[float, ...]:
        if any(not math.isfinite(c) for c in v):
            raise ValueError("cuts must be finite")
        if any(b <= a for a, b in itertools.pairwise(v)):
            raise ValueError(f"cuts must be strictly increasing, got {v}")
        return v


class NudgeAction(Model):
    cost: float = Field(ge=0.0, allow_inf_nan=False)


class DiscountAction(Model):
    discount_fraction: float = Field(gt=0.0, le=1.0, allow_inf_nan=False)


class PlanChangeAction(Model):
    price_ratio: float = Field(gt=0.0, lt=1.0, allow_inf_nan=False)


class Actions(Model):
    content_nudge: NudgeAction
    discount_1m: DiscountAction
    plan_change: PlanChangeAction


class Variant(Model):
    segment_mix: FrozenMap[FrozenMap[float]]
    acceptance: FrozenMap[FrozenMap[float]]
    exposure_effect: FrozenMap[FrozenMap[float]]
    acceptance_effect: FrozenMap[FrozenMap[float]]

    @model_validator(mode="after")
    def _complete(self) -> Self:
        missing = [c for c in CELLS if c not in self.segment_mix]
        extra = sorted(set(self.segment_mix) - set(CELLS))
        if missing or extra:
            raise ValueError(f"segment_mix: missing cells {missing} / unknown cells {extra}")
        for cell, row in self.segment_mix.items():
            _check_segments(f"segment_mix.{cell}", row, 0.0, 1.0)
            total = math.fsum(row.values())
            if abs(total - 1.0) > MIX_TOLERANCE:
                raise ValueError(f"segment_mix.{cell}: sums to {total}, not 1")
        _check_actions("acceptance", self.acceptance, OFFER_ACTIONS)
        for action, row in self.acceptance.items():
            _check_segments(f"acceptance.{action}", row, 0.0, 1.0)
        _check_actions("exposure_effect", self.exposure_effect, OFFER_ACTIONS)
        for action, row in self.exposure_effect.items():
            _check_segments(f"exposure_effect.{action}", row, -1.0, 1.0)
        _check_actions("acceptance_effect", self.acceptance_effect, ("content_nudge",))
        for action, row in self.acceptance_effect.items():
            _check_segments(f"acceptance_effect.{action}", row, -1.0, 1.0)
        return self


class SimulatorConfig(Versioned):
    period_days: int = Field(default=30, ge=1, strict=True)
    horizon_periods: int = Field(ge=1, le=12, strict=True)
    currency: Literal["NTD"] = "NTD"
    risk_bands: Bands
    trend_bands: Bands
    segments: tuple[Segment, ...] = SEGMENTS
    actions: Actions
    allow_unconventional: bool = False
    variants: FrozenMap[Variant]

    @model_validator(mode="after")
    def _structure(self) -> Self:
        if self.segments != SEGMENTS:
            raise ValueError(f"segments must be exactly {list(SEGMENTS)}")
        if len(self.risk_bands.cuts) != 2 or not all(0 < c < 1 for c in self.risk_bands.cuts):
            raise ValueError("risk_bands.cuts must be two increasing probabilities inside (0, 1)")
        if len(self.trend_bands.cuts) != 1:
            raise ValueError("trend_bands.cuts must hold one cut (declining < cut <= stable)")
        if not self.variants:
            raise ValueError("variants: at least one variant is required")
        for name in self.variants:
            if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
                raise ValueError(
                    f"variants: name {name!r} must be lower-case letters, digits, - or _"
                )
        return self

    def risk_band(self, risk: float) -> str:
        lo, hi = self.risk_bands.cuts
        return "low" if risk < lo else "medium" if risk < hi else "high"

    def trend_band(self, trend: float) -> str:
        return "declining" if trend < self.trend_bands.cuts[0] else "stable"


__all__ = [
    "CELLS",
    "OFFER_ACTIONS",
    "SEGMENTS",
    "Actions",
    "Bands",
    "Effect",
    "Fraction",
    "Segment",
    "SimulatorConfig",
    "Variant",
]
