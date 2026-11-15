"""The H-period rollout engine (Tech Spec §2.3, POL-06).

For each period, for the members still active:
    allowed   = respect.allowed_actions(...)       (all actions for the status quo)
    probs     = policy.probabilities(view)
    requested = policy.choose(probs, u)       (one uniform per member, keyed by hash)
    chosen    = budget.admit(...)                  (budgeted policies only)
    outcome   = simulator.respond(...)             (common random numbers)
    state     = update(declined, nudged, plan multiplier, active)
and logs a decision, an outcome and the member's state at the start of the period. The logs
are checked against their column contracts before they are returned. R8 holds by
construction: one decision per active member per period.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from respectful_offers.policy.baselines import Policy, View, check_distributions
from respectful_offers.policy.budget import admit, face_values
from respectful_offers.policy.cohort import Cohort
from respectful_offers.policy.respect import allowed_actions
from respectful_offers.runtime.seeds import member_uniforms
from respectful_offers.schemas.contracts import DECISIONS, MEMBER_STATES, OUTCOMES, check_frame
from respectful_offers.schemas.rows import ACTIONS
from respectful_offers.schemas.simulator import SimulatorConfig
from respectful_offers.sim.response import NO_OFFER, NUDGE, PLAN, Tables, respond

_MASK_TUPLES = {m: tuple(a for i, a in enumerate(ACTIONS) if m >> i & 1) for m in range(16)}
_ACTION_NAMES = np.array(ACTIONS, dtype=object)


@dataclass(frozen=True)
class RolloutResult:
    decisions: pd.DataFrame
    outcomes: pd.DataFrame
    states: pd.DataFrame
    spend: list[dict[str, float]]


def _tuples(mask: np.ndarray) -> list[tuple[str, ...]]:
    codes = (mask * (1 << np.arange(mask.shape[1]))).sum(axis=1)
    return [_MASK_TUPLES[int(c)] for c in codes]


def rollout(
    policy: Policy,
    cohort: Cohort,
    sim: SimulatorConfig,
    variant: str,
    *,
    periods: int,
    risk_threshold: float,
    budget_per_1000: float,
    seed: int,
    run_id: str,
    in_holdout: np.ndarray | None = None,
    context: np.ndarray | None = None,
    context_columns: tuple[str, ...] = (),
) -> RolloutResult:
    n = len(cohort)
    if n == 0:
        raise ValueError("the cohort is empty: nothing to roll out")
    if periods < 1:
        raise ValueError("a rollout needs at least one period")
    t = Tables.from_config(sim, variant)
    hold = np.zeros(n, dtype=bool) if in_holdout is None else np.asarray(in_holdout, dtype=bool)
    ctx_all = np.zeros((n, 0)) if context is None else context
    active = np.ones(n, dtype=bool)
    declined = np.zeros((n, 4), dtype=bool)
    nudged = np.zeros(n, dtype=bool)
    mult = np.ones(n)
    nudge_cost = sim.actions.content_nudge.cost
    free = np.array([True, nudge_cost == 0, False, False])
    budget = budget_per_1000 * n / 1000.0
    d_parts, o_parts, s_parts, spend = [], [], [], []
    for period in range(1, periods + 1):
        idx = np.flatnonzero(active)
        if not len(idx):
            break
        s_parts.append(
            pd.DataFrame(
                {
                    "msno": cohort.msno[idx],
                    "period": period,
                    "active": True,
                    "in_holdout": hold[idx],
                    "churn_risk": cohort.churn_risk[idx],
                    "risk_band": cohort.risk_band[idx],
                    "trend_band": cohort.trend_band[idx],
                    "declined": _tuples(declined[idx]),
                    "nudged": nudged[idx],
                    "price_30d": cohort.price[idx],
                    "plan_multiplier": mult[idx],
                }
            )
        )
        if policy.respectful:
            allowed = allowed_actions(
                in_holdout=hold[idx],
                churn_risk=cohort.churn_risk[idx],
                nudged=nudged[idx],
                declined=declined[idx],
                risk_threshold=risk_threshold,
            )
        else:  # the status quo ignores R1 and R2 (OWNER D-17), never R3
            allowed = np.ones((len(idx), 4), dtype=bool)
            allowed[hold[idx], 1:] = False
        # eligibility, not respect: a plan change is offered once, from the full plan
        allowed[:, PLAN] &= mult[idx] >= 1.0
        view = View(
            period=period,
            periods_left=periods - period + 1,
            allowed=allowed,
            churn_risk=cohort.churn_risk[idx],
            price=cohort.price[idx],
            nudged=nudged[idx],
            declined=declined[idx],
            context=ctx_all[idx],
            risk_threshold=risk_threshold,
            free=free,
            base=cohort.base[idx],
            segment=cohort.segment[idx],
            tables=t,
            plan_multiplier=mult[idx],
            context_columns=tuple(context_columns),
        )
        probs = policy.probabilities(view)
        check_distributions(probs)
        if (probs[~allowed] > 0).any():
            raise RuntimeError(f"{policy.name} put probability on a forbidden action")
        u = member_uniforms(seed, cohort.hashes[idx], period, f"policy:{policy.name}:{variant}")
        requested = policy.choose(probs, u[:, 0])
        fv = face_values(cohort.price[idx], t, nudge_cost, periods - period + 1)
        if policy.budgeted:
            adm = admit(
                requested,
                policy.fallback(view, probs),
                policy.priority(view, requested),
                cohort.hashes[idx],
                fv,
                budget,
            )
            chosen, downgraded, face = adm.chosen, adm.downgraded, adm.face_value
        else:
            chosen, downgraded = requested, np.zeros(len(idx), dtype=bool)
            face = fv[np.arange(len(idx)), chosen]
        out = respond(
            seed=seed,
            hashes=cohort.hashes[idx],
            period=period,
            base=cohort.base[idx],
            segment=cohort.segment[idx],
            price=cohort.price[idx],
            plan_multiplier=mult[idx],
            chosen=chosen,
            t=t,
        )
        observe = getattr(policy, "observe", None)
        if observe is not None:  # learning policies (the bandit in training) see what happened
            observe(view, chosen, out.revenue)
        # propensity = π(requested | x): the probability of the action the policy drew, before
        # the budget (D-32). Always > 0, because a zero-probability action is never drawn.
        prop = probs[np.arange(len(idx)), requested]
        if not (prop > 0).all():
            raise RuntimeError(f"{policy.name} drew an action it gave zero probability")
        d_parts.append(
            pd.DataFrame(
                {
                    "run_id": run_id,
                    "variant": variant,
                    "policy": policy.name,
                    "msno": cohort.msno[idx],
                    "period": period,
                    "allowed": _tuples(allowed),
                    "requested": _ACTION_NAMES[requested],
                    "chosen": _ACTION_NAMES[chosen],
                    "propensity": np.minimum(prop, 1.0),
                    "budget_downgraded": downgraded,
                    "face_value": face,
                }
            )
        )
        o_parts.append(
            pd.DataFrame(
                {
                    "run_id": run_id,
                    "variant": variant,
                    "policy": policy.name,
                    "msno": cohort.msno[idx],
                    "period": period,
                    "response": out.response,
                    "renewed": out.renewed,
                    "revenue": out.revenue,
                    "discount_cost": out.discount_cost,
                }
            )
        )
        spend.append(
            {
                "period": period,
                "budget": budget if policy.budgeted else 0.0,
                "face_value_committed": math.fsum(face),
                "realised_cost": math.fsum(out.discount_cost),
            }
        )
        shown = chosen != NO_OFFER
        said_no = shown & (out.response == "declined")
        declined[idx[said_no], chosen[said_no]] = True
        nudged[idx[chosen == NUDGE]] = True
        mult[idx] = out.plan_multiplier
        active[idx[~out.renewed]] = False
    decisions = pd.concat(d_parts, ignore_index=True)
    outcomes = pd.concat(o_parts, ignore_index=True)
    states = pd.concat(s_parts, ignore_index=True)
    check_frame(decisions, DECISIONS, f"rollout[{policy.name}]")
    check_frame(outcomes, OUTCOMES, f"rollout[{policy.name}]")
    check_frame(states, MEMBER_STATES, f"rollout[{policy.name}]")
    return RolloutResult(decisions, outcomes, states, spend)
