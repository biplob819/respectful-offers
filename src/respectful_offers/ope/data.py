"""Turning a logging pilot into period-1 logs, and asking a target policy what it would do."""

from __future__ import annotations

import numpy as np

from respectful_offers.ope.estimators import Logs
from respectful_offers.policy.baselines import Policy, View
from respectful_offers.policy.cohort import Cohort
from respectful_offers.policy.respect import allowed_actions
from respectful_offers.policy.rollout import RolloutResult, eligible
from respectful_offers.schemas.rows import ACTIONS
from respectful_offers.schemas.simulator import SimulatorConfig
from respectful_offers.sim.response import Tables

_INDEX = {a: i for i, a in enumerate(ACTIONS)}


def period1_view(
    cohort: Cohort,
    sim: SimulatorConfig,
    variant: str,
    risk_threshold: float,
    context: np.ndarray | None = None,
    periods: int = 3,
    context_columns: tuple[str, ...] = (),
) -> View:
    """Every member at period 1: no history, so allowed sets are the logger's (C3)."""
    n = len(cohort)
    allowed = allowed_actions(
        in_holdout=np.zeros(n, bool),
        churn_risk=cohort.churn_risk,
        nudged=np.zeros(n, bool),
        declined=np.zeros((n, 4), bool),
        risk_threshold=risk_threshold,
    )
    allowed = eligible(allowed, cohort.price, np.ones(n))  # the rollout's eligibility rules
    free = np.array([True, sim.actions.content_nudge.cost == 0, False, False])
    return View(
        1,
        periods,
        allowed,
        cohort.churn_risk,
        cohort.price,
        np.zeros(n, bool),
        np.zeros((n, 4), bool),
        np.zeros((n, 0)) if context is None else context,
        risk_threshold,
        free,
        cohort.base,
        cohort.segment,
        Tables.from_config(sim, variant),
        context_columns=tuple(context_columns),
    )


def logs_from_pilot(
    cohort: Cohort, pilot: RolloutResult, x: np.ndarray, view: View, variant: str
) -> Logs:
    """Period-1 rows of a logging-policy rollout as `Logs`, aligned with the cohort.

    The logs must describe exactly what the logger did: one row per cohort member, the allowed
    set the target will be asked about, the action the logger drew (never budget-downgraded),
    and the exact uniform propensity 1/|allowed|."""
    dec = pilot.decisions[pilot.decisions["period"] == 1]
    out = pilot.outcomes[pilot.outcomes["period"] == 1]
    if set(dec["policy"]) != {"logging"} or set(out["policy"]) != {"logging"}:
        raise ValueError("off-policy logs must come from the logging pilot")
    for col in ("run_id", "variant"):
        if dec[col].nunique() != 1 or set(out[col]) != set(dec[col]):
            raise ValueError(f"decisions and outcomes come from different runs ({col})")
    if dec["variant"].iloc[0] != variant:
        raise ValueError(f"the pilot ran under variant {dec['variant'].iloc[0]!r}, not {variant!r}")
    if x.shape[0] != len(cohort) or (view.context.size and not np.array_equal(x, view.context)):
        raise ValueError("reward-model features must be aligned with the cohort and the view")
    members = set(cohort.msno)
    if len(dec) != len(cohort) or set(dec["msno"]) != members or set(out["msno"]) != members:
        raise ValueError("the pilot's period-1 logs must hold every cohort member exactly once")
    d = dec.set_index("msno").loc[cohort.msno]
    o = out.set_index("msno").loc[cohort.msno]
    # each outcome must describe the logged action: shown actions get a response, no offer
    # never does (catches outcomes taken from another pilot that reused the run id)
    shown = (d["chosen"] != "no_offer").to_numpy()
    responded = (o["response"] != "not_shown").to_numpy()
    if (shown != responded).any():
        raise ValueError(
            f"{int((shown != responded).sum())} outcomes do not match their logged action: "
            "decisions and outcomes come from different runs"
        )
    logged = np.zeros((len(cohort), 4), bool)
    for row, acts in enumerate(d["allowed"]):
        logged[row, [_INDEX[a] for a in acts]] = True
    if not np.array_equal(logged, view.allowed):
        raise ValueError(
            "the pilot's allowed sets differ from the view's: targets would be "
            "asked about actions the logger could not take, or vice versa"
        )
    if (d["requested"] != d["chosen"]).any() or d["budget_downgraded"].any():
        raise ValueError("a logged action was changed after the logger drew it")
    if not np.allclose(
        d["propensity"].to_numpy(float), 1.0 / logged.sum(axis=1), rtol=0, atol=1e-12
    ):
        raise ValueError("logging propensities must be exactly 1/|allowed|")
    action = d["chosen"].map(_INDEX).to_numpy(dtype=int)
    return Logs(
        x=x,
        allowed=view.allowed,
        action=action,
        propensity=d["propensity"].to_numpy(float),
        reward=o["revenue"].to_numpy(float),
        hashes=cohort.hashes,
    )


def target_probabilities(policy: Policy, view: View) -> np.ndarray:
    if view.period != 1:
        raise ValueError("off-policy targets are evaluated at period 1 only (C3)")
    return policy.probabilities(view)
