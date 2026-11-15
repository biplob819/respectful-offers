"""The budget pacer (Tech Spec §6.3, D-7, R4).

Each period has a budget in NTD: `budget_per_1000_per_period × cohort size / 1000`. Offers are
charged at **face value when sent** (whatever the member does), so committed spend can never
exceed the budget (checked in exact arithmetic). The budget is fixed by the cohort's size at
the start, not by who is still active: members who churn free no budget for the rest (D-32).
    discount_1m   discount_fraction × price
    plan_change   (1 − price_ratio) × price × periods remaining (the worst case)
    content_nudge the nudge cost (0 by default)
After the policy chooses, costly requests are admitted in priority order (ties broken by the
member's hash, so the order is stable) while they fit; the rest are downgraded to the
policy's best free allowed action.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

import numpy as np

from respectful_offers.sim.response import DISCOUNT, NUDGE, PLAN, Tables


@dataclass(frozen=True)
class Admission:
    chosen: np.ndarray
    downgraded: np.ndarray
    face_value: np.ndarray  # of the chosen action
    committed: float
    budget: float


def face_values(price: np.ndarray, t: Tables, nudge_cost: float, periods_left: int) -> np.ndarray:
    """[n, 4] face value of each action for each member."""
    fv = np.zeros((len(price), 4))
    fv[:, NUDGE] = nudge_cost
    fv[:, DISCOUNT] = t.discount_fraction * price
    fv[:, PLAN] = (1.0 - t.price_ratio) * price * max(periods_left, 1)
    return fv


def admit(
    requested: np.ndarray,
    fallback: np.ndarray,
    priority: np.ndarray,
    tiebreak: np.ndarray,
    fv: np.ndarray,
    budget: float,
) -> Admission:
    """Admit costly requests by priority until the budget is spent; downgrade the rest to
    `fallback` (which must be free). `budget` may be 0 (no costly offers) but never negative."""
    if not np.isfinite(budget) or budget < 0:
        raise ValueError("the period budget must be finite and non-negative")
    if not np.isfinite(priority).all():
        raise ValueError("priorities must be finite")
    n = len(requested)
    idx = np.arange(n)
    cost = fv[idx, requested]
    if not (np.isfinite(cost).all() and (cost >= 0).all()):
        raise ValueError("face values must be finite and non-negative")
    if (fv[idx, fallback] > 0).any():
        raise ValueError("a fallback action must be free")
    costly = np.flatnonzero(cost > 0)
    order = costly[np.lexsort((tiebreak[costly], -priority[costly]))]
    # Greedy by priority, in exact arithmetic (floats are dyadic rationals, so Fraction sums
    # are exact): once one request does not fit, a later, cheaper one may still fit. The
    # committed total reported below is math.fsum of the admitted costs, the correctly rounded
    # exact sum, so it can never exceed the budget either (rounding is monotone).
    admitted = np.zeros(n, dtype=bool)
    if math.fsum(cost[order]) < budget or not len(order):
        admitted[order] = True
    else:
        remaining = Fraction(budget)
        for i in order:
            c = Fraction(float(cost[i]))
            if c <= remaining:
                admitted[i] = True
                remaining -= c
    chosen = requested.copy()
    down = (cost > 0) & ~admitted
    chosen[down] = fallback[down]
    face = fv[idx, chosen]
    return Admission(chosen, down, face, math.fsum(face), float(budget))
