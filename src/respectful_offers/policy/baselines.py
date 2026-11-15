"""Policies other than the bandit (Tech Spec §6.3) and the shared policy interface.

Every policy turns a period's view of the active members into action probabilities over
`ACTIONS`. Respectful policies put zero probability outside the respect filter's allowed
set; the status quo is the one deliberate exception (OWNER D-17) and is audited and reported
with its violations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import numpy as np

from respectful_offers.schemas.rows import PolicyName
from respectful_offers.sim.response import (
    DISCOUNT,
    NO_OFFER,
    NUDGE,
    Tables,
    expected_reward_by_segment,
)


@dataclass(frozen=True)
class View:
    """What a policy may see in one period, for the active members only."""

    period: int
    periods_left: int
    allowed: np.ndarray  # [n, 4] bool, after the respect filter (all True for the status quo)
    churn_risk: np.ndarray
    price: np.ndarray
    nudged: np.ndarray
    declined: np.ndarray  # [n, 4]
    context: np.ndarray  # [n, d] allow-listed decision features (A2.5); may be empty
    risk_threshold: float
    free: np.ndarray  # [4] bool: actions with no face value (no_offer, and a free nudge)
    # hidden truth, read only by the segment oracle and never by a real policy
    base: np.ndarray
    segment: np.ndarray
    tables: Tables
    plan_multiplier: np.ndarray | None = None  # 1 = full plan; a plan change is offered once
    context_columns: tuple[str, ...] = ()  # names of `context`'s columns, in order


class Policy:
    name: ClassVar[PolicyName]
    respectful: ClassVar[bool] = True
    budgeted: ClassVar[bool] = True
    context_columns: tuple[str, ...] = ()

    def probabilities(self, view: View) -> np.ndarray:
        raise NotImplementedError

    def priority(self, view: View, requested: np.ndarray) -> np.ndarray:
        return view.churn_risk

    def choose(self, probs: np.ndarray, u: np.ndarray) -> np.ndarray:
        """Inverse-CDF draw with one uniform per member (keyed by the member's hash, so a
        member's draw never depends on who else is in the cohort). An action with zero
        probability is never drawn."""
        check_distributions(probs)
        c = np.cumsum(probs, axis=1)
        c /= c[:, -1:]
        return np.minimum((u[:, None] >= c).sum(axis=1), probs.shape[1] - 1)

    def preference(self, view: View, probs: np.ndarray) -> np.ndarray:
        """How much this policy prefers each action, [n, 4]: used to pick the downgrade target
        when the budget refuses a costly request. By default, its own probabilities."""
        return probs

    def fallback(self, view: View, probs: np.ndarray) -> np.ndarray:
        """The best free allowed action by this policy's own preference (no_offer if none)."""
        pref = np.asarray(self.preference(view, probs), dtype=float)
        ok = view.allowed & view.free[None, :]
        ok[:, NO_OFFER] = True  # always allowed and always free
        masked = np.where(ok, pref, -np.inf)
        best = masked.argmax(axis=1)  # ties go to the lowest index: no_offer first
        return np.where(np.isfinite(masked[np.arange(len(best)), best]), best, NO_OFFER)


def check_distributions(probs: np.ndarray) -> None:
    if probs.ndim != 2 or probs.shape[1] != 4:
        raise ValueError("action probabilities must be [n, 4]")
    if not np.isfinite(probs).all() or (probs < 0).any():
        raise ValueError("action probabilities must be finite and non-negative")
    if not np.allclose(probs.sum(axis=1), 1.0, rtol=0.0, atol=1e-9):
        raise ValueError("action probabilities must sum to 1 for every member")


def one_hot(index: np.ndarray, k: int = 4) -> np.ndarray:
    out = np.zeros((len(index), k))
    out[np.arange(len(index)), index] = 1.0
    return out


class NoOffer(Policy):
    name = "no_offer"
    budgeted = False

    def probabilities(self, view: View) -> np.ndarray:
        return one_hot(np.zeros(len(view.allowed), dtype=int))


class Holdout(NoOffer):
    name = "holdout"


class StatusQuo(Policy):
    """'Discount everyone at risk', every period, ignoring R1 and R2 (OWNER D-17). It still
    never contacts the holdout (R3): `view.allowed` holds only R3 for this policy."""

    name = "status_quo"
    respectful = False

    def probabilities(self, view: View) -> np.ndarray:
        at_risk = view.churn_risk >= view.risk_threshold
        return one_hot(np.where(at_risk & view.allowed[:, DISCOUNT], DISCOUNT, NO_OFFER))


class RuleFollowingBaseline(Policy):
    """The same intent through the respect filter: nudge first, then discount, never re-offer."""

    name = "rule_following_baseline"

    def probabilities(self, view: View) -> np.ndarray:
        at_risk = view.churn_risk >= view.risk_threshold
        pick = np.where(
            at_risk & view.allowed[:, DISCOUNT],
            DISCOUNT,
            np.where(at_risk & view.allowed[:, NUDGE], NUDGE, NO_OFFER),
        )
        return one_hot(pick)

    def preference(self, view: View, probs: np.ndarray) -> np.ndarray:
        # nudge first, then discount: a refused discount falls back to a free nudge if allowed
        at_risk = (view.churn_risk >= view.risk_threshold)[:, None]
        rank = np.array([0.0, 1.0, 2.0, 0.0])[None, :]
        return np.where(at_risk, rank, probs)


class LoggingPolicy(Policy):
    """Uniform over the allowed actions: the randomised pilot whose logs feed OPE."""

    name = "logging"
    budgeted = False

    def probabilities(self, view: View) -> np.ndarray:
        a = view.allowed.astype(float)
        return a / a.sum(axis=1, keepdims=True)


class SegmentOracle(Policy):
    """Knows each member's true segment: the upper bound no real system can reach (§5.4)."""

    name = "segment_oracle"

    def _values(self, view: View) -> np.ndarray:
        v = expected_reward_by_segment(
            view.base, view.segment, view.price, view.tables, view.plan_multiplier
        )
        return np.where(view.allowed, v, -np.inf)

    def probabilities(self, view: View) -> np.ndarray:
        v = self._values(view)
        return one_hot(v.argmax(axis=1))  # ties go to the lowest index: no_offer first

    def preference(self, view: View, probs: np.ndarray) -> np.ndarray:
        return self._values(view)

    def priority(self, view: View, requested: np.ndarray) -> np.ndarray:
        v = self._values(view)
        best_free = np.where(view.free[None, :] & view.allowed, v, -np.inf).max(axis=1)
        gain = v[np.arange(len(requested)), requested] - best_free
        return np.where(np.isfinite(gain), gain, 0.0)
