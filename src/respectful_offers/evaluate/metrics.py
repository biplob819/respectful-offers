"""Per-member outcomes from a rollout, and the policy summary built from them (Tech Spec §7.4).

Every metric's denominator is fixed by the cohort, never by the policy or the demo slider:
retained and LTV per evaluation member; "at risk" uses the reference threshold in the run
config. Incremental figures are paired member by member against no offer on the same
members under common random numbers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from respectful_offers.evaluate.stats import Resampler, interval, mean_interval, ratio_interval
from respectful_offers.policy.cohort import Cohort
from respectful_offers.policy.rollout import RolloutResult
from respectful_offers.schemas.summary import Interval, PeriodSpend, PolicySummary


@dataclass(frozen=True)
class MemberOutcomes:
    """Aligned with the cohort's members."""

    retained: np.ndarray  # active after every period of the horizon
    revenue: np.ndarray
    cost: np.ndarray
    offers: np.ndarray  # shown actions
    months: np.ndarray  # member-months with a decision
    max_offers_in_a_month: int
    decisions: int
    no_offer_decisions: int


def member_outcomes(cohort: Cohort, res: RolloutResult, periods: int) -> MemberOutcomes:
    o = res.outcomes
    d = res.decisions
    idx = pd.Index(cohort.msno)
    renew_all = o.groupby("msno")["renewed"].agg(["all", "size"])
    retained = (renew_all["all"] & (renew_all["size"] == periods)).reindex(idx, fill_value=False)
    revenue = o.groupby("msno")["revenue"].sum().reindex(idx, fill_value=0.0)
    cost = o.groupby("msno")["discount_cost"].sum().reindex(idx, fill_value=0.0)
    shown = d["chosen"].ne("no_offer")
    offers = shown.groupby(d["msno"]).sum().reindex(idx, fill_value=0)
    months = d.groupby("msno").size().reindex(idx, fill_value=0)
    per_month = shown.groupby([d["msno"], d["period"]]).sum()
    return MemberOutcomes(
        retained=retained.to_numpy(dtype=float),
        revenue=revenue.to_numpy(dtype=float),
        cost=cost.to_numpy(dtype=float),
        offers=offers.to_numpy(dtype=float),
        months=months.to_numpy(dtype=float),
        max_offers_in_a_month=int(per_month.max()) if len(per_month) else 0,
        decisions=len(d),
        no_offer_decisions=int((~shown).sum()),
    )


MIN_AT_RISK = 30  # fewer at-risk members than this: the at-risk rate is reported as null


@dataclass(frozen=True)
class Draws:
    """Bootstrap draws kept for paired comparisons."""

    incremental: np.ndarray
    ltv: np.ndarray
    # the pre-registered headline: extra members kept per 1,000 NTD of discount (D-38);
    # None when the policy spends nothing (the ratio is undefined)
    per_ntd_point: float | None
    per_ntd: np.ndarray | None


def summarise(
    policy: str,
    variant: str,
    respectful: bool,
    cohort: Cohort,
    out: MemberOutcomes,
    base: MemberOutcomes,
    at_risk: np.ndarray,
    spend: list[dict[str, float]],
    violations: dict[str, int],
    exploration: float | None,
    r: Resampler,
) -> tuple[PolicySummary, Draws]:
    block = r.block_of(cohort.hashes)
    retained, _ = mean_interval(r, block, out.retained, scale=1000.0)
    inc_values = out.retained - base.retained
    incremental, inc_draws = mean_interval(r, block, inc_values, scale=1000.0)
    at_risk_iv: Interval | None = None
    if at_risk.sum() >= MIN_AT_RISK:
        risk_point, risk_draws = ratio_interval(
            r, block, out.retained * at_risk, at_risk.astype(float)
        )
        at_risk_iv = interval(1000.0 * risk_point, 1000.0 * risk_draws)
    ltv, ltv_draws = mean_interval(r, block, out.revenue)
    cost_total = math.fsum(out.cost)
    c_total, c_draws = r.sums(block, out.cost)
    _, i_draws = r.sums(block, inc_values)
    cost_ratio: Interval | None = None
    if incremental.lo > 0:
        # NTD of discount per extra member retained. A resample with no extra members has an
        # unbounded ratio: it counts as +inf, never dropped, so the upper bound stays honest.
        point = c_total / math.fsum(inc_values)
        draws = np.where(i_draws > 0, c_draws / np.where(i_draws > 0, i_draws, 1.0), np.inf)
        lo, hi = np.percentile(draws, [2.5, 97.5])
        if np.isfinite(hi):
            cost_ratio = Interval(
                point=round(point, 4), lo=round(float(lo), 4), hi=round(float(hi), 4)
            )
    per_ntd_point: float | None = None
    per_ntd: np.ndarray | None = None
    if cost_total > 0:
        per_ntd_point = 1000.0 * math.fsum(inc_values) / cost_total
        per_ntd = 1000.0 * i_draws / np.where(c_draws > 0, c_draws, np.nan)
    fatigue_point, fatigue_draws = ratio_interval(r, block, out.offers, out.months)
    summary = PolicySummary(
        policy=policy,  # type: ignore[arg-type]
        variant=variant,
        respectful=respectful,
        n_members=len(cohort),
        retained_per_1000=retained,
        incremental_retained_per_1000=incremental,
        retained_per_1000_at_risk=at_risk_iv,
        ltv_proxy_per_member=ltv,
        discount_cost_total=round(cost_total, 4),
        cost_per_incremental_retained=cost_ratio,
        offers_per_member_month=interval(fatigue_point, fatigue_draws),
        max_offers_in_a_month=out.max_offers_in_a_month,
        no_offer_share=round(out.no_offer_decisions / out.decisions, 6) if out.decisions else 1.0,
        exploration_rate=None if exploration is None else round(exploration, 6),
        spend=tuple(
            PeriodSpend(
                period=int(s["period"]),
                budget=round(s["budget"], 4),
                face_value_committed=round(s["face_value_committed"], 4),
                realised_cost=round(s["realised_cost"], 4),
            )
            for s in spend
        ),
        violations=violations,
    )
    return summary, Draws(inc_draws, ltv_draws, per_ntd_point, per_ntd)
