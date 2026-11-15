"""The respect filter (Tech Spec §6.1): which actions a member may be offered, before any policy.

Vectorised over members. Columns of every mask follow `ACTIONS`:
    0 no_offer, 1 content_nudge, 2 discount_1m, 3 plan_change.

Rules applied in `allowed_actions`:
  R3  holdout members get only no_offer;
  R1  an action shown and declined before is never offered again, nudges included (OWNER D-18);
  R2  a member at or above the risk threshold with no earlier nudge gets only no_offer or a nudge;
  always: no_offer is allowed, so the set is never empty.
R8 (one decision per member per period) holds by construction in the rollout engine; R7 is
`check_context_columns`. The auditor (`audit.py`) re-derives all of this independently.
"""

from __future__ import annotations

import numbers
from collections.abc import Iterable, Sequence

import numpy as np

from respectful_offers.runtime.seeds import bucket
from respectful_offers.schemas.config import protected_name
from respectful_offers.schemas.rows import ACTIONS, PROTECTED_ATTRIBUTES

NO_OFFER, NUDGE, DISCOUNT, PLAN = range(4)
COMMERCIAL = (DISCOUNT, PLAN)


def declined_mask(declined: Sequence[Iterable[str]]) -> np.ndarray:
    """bool [n, 4] from per-member sequences of declined action names."""
    mask = np.zeros((len(declined), len(ACTIONS)), dtype=bool)
    index = {a: i for i, a in enumerate(ACTIONS)}
    for row, actions in enumerate(declined):
        for a in actions:
            if a not in index:
                raise ValueError(f"unknown action {a!r}")
            if a == "no_offer":
                raise ValueError("no_offer cannot be declined")
            mask[row, index[a]] = True
    return mask


def allowed_actions(
    *,
    in_holdout: np.ndarray,
    churn_risk: np.ndarray,
    nudged: np.ndarray,
    declined: np.ndarray,
    risk_threshold: float | np.floating,
) -> np.ndarray:
    n = len(churn_risk)
    for name, arr in (("in_holdout", in_holdout), ("nudged", nudged)):
        if arr.shape != (n,) or arr.dtype != bool:
            raise ValueError(f"{name} must be a bool array of length {n}")
    if declined.shape != (n, len(ACTIONS)) or declined.dtype != bool:
        raise ValueError(f"declined must be a bool array of shape ({n}, {len(ACTIONS)})")
    if declined[:, NO_OFFER].any():
        raise ValueError("no_offer cannot be declined")
    risk = np.asarray(churn_risk)
    if risk.ndim != 1 or not np.issubdtype(risk.dtype, np.floating):
        raise ValueError("churn_risk must be a 1-D float array")
    if not np.isfinite(risk).all() or (risk < 0).any() or (risk > 1).any():
        raise ValueError("churn_risk must be finite probabilities")
    if isinstance(risk_threshold, bool) or not isinstance(risk_threshold, numbers.Real):
        raise ValueError("risk_threshold must be a number")
    if not 0.0 < risk_threshold < 1.0:
        raise ValueError("risk_threshold must lie inside (0, 1)")

    allowed = np.ones((n, len(ACTIONS)), dtype=bool)
    allowed &= ~declined  # R1
    at_risk_unnudged = (risk >= risk_threshold) & ~nudged
    for a in COMMERCIAL:  # R2
        allowed[:, a] &= ~at_risk_unnudged
    allowed[in_holdout, 1:] = False  # R3
    allowed[:, NO_OFFER] = True
    return allowed


def assign_cohorts(
    msnos: Sequence[str], salt: str, buckets: dict[str, tuple[int, int]]
) -> np.ndarray:
    """Cohort name per member from salted hash buckets (D-8, RSP-03)."""
    spans = sorted((lo, hi, name) for name, (lo, hi) in buckets.items())
    edge = 0
    for lo, hi, _ in spans:
        if lo != edge or hi <= lo:
            raise ValueError("cohort buckets must tile 0..100")
        edge = hi
    if edge != 100:
        raise ValueError("cohort buckets must end at 100")
    b = bucket(salt, msnos)
    out = np.empty(len(b), dtype=object)
    for lo, hi, name in spans:
        out[(b >= lo) & (b < hi)] = name
    return out


def check_context_columns(columns: Sequence[str], allow_list: Sequence[str]) -> None:
    """R7: a policy's context uses exactly the allow-listed features, never a protected one."""
    bad = sorted(c for c in columns if c in PROTECTED_ATTRIBUTES or protected_name(c))
    if bad:
        raise ValueError(f"R7: protected or proxy attributes in a policy context: {bad}")
    extra = sorted(set(columns) - set(allow_list))
    if extra:
        raise ValueError(f"R7: context columns outside the allow-list: {extra}")
