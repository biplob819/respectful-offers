"""Summary schemas written to `summary.json` (Tech Spec §3). Every outcome figure is simulated."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from respectful_offers.schemas._base import (
    Fraction,
    FrozenMap,
    Model,
    Name,
    NonNegFloat,
    NonNegInt,
    PosInt,
    Timestamp,
    Versioned,
)
from respectful_offers.schemas.rows import PolicyName

Finite = float


class Interval(Model):
    point: float = Field(allow_inf_nan=False)
    lo: float = Field(allow_inf_nan=False)
    hi: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.lo > self.hi:
            raise ValueError(f"interval lo {self.lo} is above hi {self.hi}")
        return self


class PeriodSpend(Model):
    period: PosInt
    budget: NonNegFloat
    face_value_committed: NonNegFloat
    realised_cost: NonNegFloat

    @model_validator(mode="after")
    def _within_budget(self) -> Self:
        if self.face_value_committed > self.budget * (1 + 1e-12):
            raise ValueError("face value committed exceeds the period budget (R4)")
        if self.realised_cost > self.face_value_committed * (1 + 1e-12):
            raise ValueError("realised cost exceeds the face value committed")
        return self


class PolicySummary(Model):
    policy: PolicyName
    variant: Name
    respectful: bool
    n_members: PosInt
    retained_per_1000: Interval
    incremental_retained_per_1000: Interval
    retained_per_1000_at_risk: Interval
    ltv_proxy_per_member: Interval
    discount_cost_total: NonNegFloat
    cost_per_incremental_retained: Interval | None
    offers_per_member_month: Interval
    max_offers_in_a_month: NonNegInt
    no_offer_share: Fraction
    exploration_rate: Fraction | None
    spend: tuple[PeriodSpend, ...]
    violations: FrozenMap[NonNegInt]

    @model_validator(mode="after")
    def _ratio_defined_only_with_incremental_members(self) -> Self:
        positive = self.incremental_retained_per_1000.point > 0
        ratio = self.cost_per_incremental_retained
        if ratio is not None and ratio.lo < 0:
            raise ValueError("cost per incremental retained member cannot be negative")
        if positive != (ratio is not None):
            raise ValueError(
                "cost_per_incremental_retained must be present exactly when incremental "
                "retention is positive"
            )
        if set(self.violations) != {"R1", "R2", "R3", "R7", "R8"}:
            raise ValueError("violations must report exactly R1, R2, R3, R7 and R8")
        return self


class OPEEstimate(Model):
    policy: PolicyName
    variant: Name
    estimator: Literal["ips", "snips", "dr"]
    value: Interval
    oracle: float = Field(allow_inf_nan=False)
    covered: bool
    effective_sample_size: NonNegFloat

    @model_validator(mode="after")
    def _covered_matches(self) -> Self:
        if self.covered != (self.value.lo <= self.oracle <= self.value.hi):
            raise ValueError("covered must say whether the oracle lies inside the interval")
        return self


class Comparison(Model):
    variant: Name
    metric: Name
    a: PolicyName
    b: PolicyName
    diff: Interval
    p_value: Fraction
    separated: bool

    @model_validator(mode="after")
    def _sane(self) -> Self:
        if self.a == self.b:
            raise ValueError("a comparison needs two different policies")
        if self.separated and self.diff.lo <= 0 <= self.diff.hi:
            raise ValueError("a gap whose interval spans 0 cannot be separated")
        return self


DISPARITY_GROUPS = {
    "age_band": {"<18", "18-24", "25-34", "35-44", "45+", "unknown"},
    "gender": {"female", "male", "unknown"},
}


class ChurnReport(Model):
    auc: Interval
    brier: Interval
    ece: Fraction
    reliability: tuple[tuple[float, float, NonNegInt], ...]
    baseline_auc: Interval
    features: tuple[Name, ...]


class RunSummary(Versioned):
    """Load from files with `load_summary` (JSON mode), never `model_validate(json.load(f))`."""

    run_id: Name
    git_sha: Name
    config_hash: Name
    simulator_hash: Name
    prereg_status: Literal["preregistered", "exploratory"]
    simulated: Literal[True]

    @field_validator("simulated", mode="before")
    @classmethod
    def _really_true(cls, v: object) -> object:
        if v is not True:
            raise ValueError("simulated must be the boolean true")
        return v

    variants: tuple[Name, ...] = Field(min_length=1)
    policies: tuple[PolicySummary, ...]
    ope: tuple[OPEEstimate, ...]
    comparisons: tuple[Comparison, ...]
    churn: ChurnReport
    holdout_check: FrozenMap[Interval]
    disparity: FrozenMap[FrozenMap[Interval]]
    started_at: Timestamp
    finished_at: Timestamp | None

    @model_validator(mode="after")
    def _references_resolve(self) -> Self:
        pairs = [(c.variant, c.metric, frozenset((c.a, c.b))) for c in self.comparisons]
        if len(set(pairs)) != len(pairs):
            raise ValueError("one comparison per variant × metric × pair of policies")
        for p in self.policies:
            periods = [s.period for s in p.spend]
            if len(set(periods)) != len(periods):
                raise ValueError(f"{p.policy}/{p.variant}: one spend row per period")
        if len(set(self.variants)) != len(self.variants):
            raise ValueError("variants must not repeat")
        ope_keys = [(o.policy, o.variant, o.estimator) for o in self.ope]
        if len(set(ope_keys)) != len(ope_keys):
            raise ValueError("one OPE row per policy × variant × estimator")
        for attr, groups in self.disparity.items():
            allowed = DISPARITY_GROUPS.get(attr)
            if allowed is None or not groups or not set(groups) <= allowed:
                raise ValueError(
                    f"disparity may only report {sorted(DISPARITY_GROUPS)} groups, got {attr}"
                )
        keys = [(p.policy, p.variant) for p in self.policies]
        if len(set(keys)) != len(keys):
            raise ValueError("one PolicySummary per policy × variant")
        known = set(keys)
        variants = set(self.variants)
        for p in self.policies:
            if p.variant not in variants:
                raise ValueError(f"policy {p.policy} names unknown variant {p.variant}")
        for o in self.ope:
            if (o.policy, o.variant) not in known:
                raise ValueError(f"OPE row names {o.policy}/{o.variant}, not in policies")
        for c in self.comparisons:
            for name in (c.a, c.b):
                if (name, c.variant) not in known:
                    raise ValueError(f"comparison names {name}/{c.variant}, not in policies")
        if set(self.holdout_check) - variants:
            raise ValueError("holdout_check names a variant not in variants")
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("finished_at is before started_at")
        return self


def finite(x: float) -> bool:
    return math.isfinite(x)


__all__ = [
    "ChurnReport",
    "Comparison",
    "Finite",
    "Interval",
    "OPEEstimate",
    "PeriodSpend",
    "PolicySummary",
    "RunSummary",
    "load_summary",
]


def load_summary(path: Path) -> RunSummary:
    """Read a summary.json in JSON mode, where arrays fill tuples and ISO strings fill dates."""
    return RunSummary.model_validate_json(Path(path).read_text(encoding="utf-8"))
