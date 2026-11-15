"""Row contracts for the tables the pipeline writes (Tech Spec §3).

Full tables are checked with column contracts (`contracts.py`); these models validate
fixtures, samples and single rows, and define what one row means.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Literal, Self, TypeVar

from pydantic import Field, field_validator, model_validator

from respectful_offers.schemas._base import Fraction, Model, Name, NonNegFloat, NonNegInt, PosInt

M = TypeVar("M", bound=Model)

PROTECTED_ATTRIBUTES: frozenset[str] = frozenset(
    {"age", "bd", "age_band", "gender", "sex", "city", "registered_via", "msno"}
)

Action = Literal["no_offer", "content_nudge", "discount_1m", "plan_change"]
ACTIONS: tuple[Action, ...] = ("no_offer", "content_nudge", "discount_1m", "plan_change")
SHOWN_ACTIONS: tuple[Action, ...] = ACTIONS[1:]
COMMERCIAL_ACTIONS: tuple[Action, ...] = ("discount_1m", "plan_change")
Response = Literal["accepted", "declined", "not_shown"]
PolicyName = Literal[
    "holdout",
    "no_offer",
    "status_quo",
    "rule_following_baseline",
    "bandit",
    "logging",
    "segment_oracle",
]
POLICY_NAMES: tuple[PolicyName, ...] = (
    "holdout",
    "no_offer",
    "status_quo",
    "rule_following_baseline",
    "bandit",
    "logging",
    "segment_oracle",
)
RiskBand = Literal["low", "medium", "high"]
TrendBand = Literal["declining", "stable"]
AgeBand = Literal["<18", "18-24", "25-34", "35-44", "45+", "unknown"]
Gender = Literal["female", "male", "unknown"]
Cohort = Literal["feb", "mar"]


def _sorted_unique_actions(v: tuple[Action, ...]) -> tuple[Action, ...]:
    if "no_offer" in v:
        raise ValueError("no_offer is never shown, so it cannot be declined")
    if len(set(v)) != len(v):
        raise ValueError("declined actions must not repeat")
    if list(v) != sorted(v, key=ACTIONS.index):
        raise ValueError("declined actions must be in ACTIONS order")
    return v


class MemberFeatures(Model):
    msno: Name
    cohort: Cohort
    as_of: dt.date
    tenure_days: NonNegInt
    auto_renew: bool
    cancels_90d: NonNegInt
    listening_trend_30d: float = Field(allow_inf_nan=False, ge=-1.0)
    price_30d: NonNegFloat
    plan_days: PosInt
    churn_label: bool


class AuditAttributes(Model):
    msno: Name
    age_band: AgeBand
    gender: Gender


class MemberState(Model):
    msno: Name
    period: PosInt
    active: bool
    in_holdout: bool
    churn_risk: Fraction
    risk_band: RiskBand
    trend_band: TrendBand
    declined: tuple[Action, ...] = ()
    nudged: bool
    price_30d: NonNegFloat
    plan_multiplier: float = Field(default=1.0, gt=0.0, le=1.0, allow_inf_nan=False)

    @field_validator("declined")
    @classmethod
    def _declined_ok(cls, v: tuple[Action, ...]) -> tuple[Action, ...]:
        return _sorted_unique_actions(v)


class Decision(Model):
    run_id: Name
    variant: Name
    policy: PolicyName
    msno: Name
    period: PosInt
    allowed: tuple[Action, ...] = Field(min_length=1)
    requested: Action
    chosen: Action
    propensity: float = Field(gt=0.0, le=1.0, allow_inf_nan=False)
    budget_downgraded: bool
    face_value: NonNegFloat

    @field_validator("allowed")
    @classmethod
    def _allowed_in_order(cls, v: tuple[Action, ...]) -> tuple[Action, ...]:
        if len(set(v)) != len(v) or list(v) != sorted(v, key=ACTIONS.index):
            raise ValueError("allowed must list distinct actions in ACTIONS order")
        if "no_offer" not in v:
            raise ValueError("no_offer is always allowed")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.requested not in self.allowed:
            raise ValueError(
                f"requested action {self.requested} is not in allowed {self.allowed}: a policy may "
                "only request what the respect filter allowed"
            )
        if self.chosen not in self.allowed:
            raise ValueError(f"chosen action {self.chosen} is not in allowed {self.allowed}")
        if self.budget_downgraded == (self.chosen == self.requested):
            raise ValueError("budget_downgraded must be true exactly when chosen != requested")
        if self.chosen == "no_offer" and self.face_value != 0:
            raise ValueError("no_offer has no face value")
        return self


class Outcome(Model):
    run_id: Name
    variant: Name
    policy: PolicyName
    msno: Name
    period: PosInt
    response: Response
    renewed: bool
    revenue: NonNegFloat
    discount_cost: NonNegFloat

    @model_validator(mode="after")
    def _non_renewal_earns_nothing(self) -> Self:
        if not self.renewed and (self.revenue != 0 or self.discount_cost != 0):
            raise ValueError("a member who did not renew has no revenue and no discount cost")
        return self


def plain(value: object) -> object:
    """A pandas or numpy value as the plain Python value a strict model expects."""
    import numpy as np
    import pandas as pd

    if isinstance(value, np.ndarray | list | tuple):
        return tuple(plain(v) for v in value)
    if isinstance(value, pd.Timestamp):
        return value.date() if value == value.normalize() and value.tz is None else value
    if isinstance(value, np.generic):
        return value.item()
    return value


def row_from_record(model: type[M], record: Mapping[str, object]) -> M:
    """Validate one table row (a dict, a DataFrame row or a Parquet record) with a strict
    row model: numpy scalars, arrays and midnight timestamps become plain values first."""
    return model.model_validate({k: plain(v) for k, v in record.items()})
