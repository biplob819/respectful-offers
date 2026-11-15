"""`offers evaluate`: every policy, every variant, on the same members (Tech Spec §7, A2.7).

For each simulator variant:
  1. build the March cohort (risk, bands, hidden segments) and split it by salted hash into
     holdout, bandit training, logging pilot and evaluation cohorts (D-8);
  2. train the Thompson sampling bandit on the training cohort, then freeze it;
  3. roll out no offer, the status quo, the rule-following baseline, the bandit and the
     segment oracle for H periods on the evaluation cohort (CRN), and the holdout policy on
     the holdout cohort;
  4. audit every log independently; summarise each policy against no offer, paired;
  5. run the logging pilot (period 1) and estimate every respectful policy with IPS, SNIPS
     and DR beside the exact oracle;
  6. repeat the main rollouts at every budget in the sweep for the frontier.
Then compare policies (paired, Holm per metric and variant) and write `summary.json`.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from respectful_offers.evaluate.metrics import Draws, member_outcomes, summarise
from respectful_offers.evaluate.stats import Resampler, holm, interval, mean_interval, paired
from respectful_offers.ope.data import logs_from_pilot, period1_view, target_probabilities
from respectful_offers.ope.estimators import estimate, fit_reward_model, oracle_value
from respectful_offers.policy.audit import audit
from respectful_offers.policy.bandit import train_bandit
from respectful_offers.policy.baselines import (
    Holdout,
    LoggingPolicy,
    NoOffer,
    Policy,
    RuleFollowingBaseline,
    SegmentOracle,
    StatusQuo,
)
from respectful_offers.policy.cohort import Cohort, build_cohort
from respectful_offers.policy.respect import assign_cohorts
from respectful_offers.policy.rollout import RolloutResult, rollout
from respectful_offers.runtime.seeds import member_uniforms
from respectful_offers.schemas.config import RunConfig
from respectful_offers.schemas.simulator import SimulatorConfig
from respectful_offers.schemas.summary import (
    ChurnReport,
    Comparison,
    OPEEstimate,
    PolicySummary,
    RunSummary,
)
from respectful_offers.sim.response import Tables, expected_reward_by_segment

BANDIT_EPOCHS = 3
COMPARED = ("bandit", "rule_following_baseline", "status_quo")
HEADLINE = "incremental_retained_per_1000_ntd"  # extra members kept per 1,000 NTD (D-38)
METRICS = ("incremental_retained_per_1000", "ltv_proxy_per_member", HEADLINE)
SWEPT = ("bandit", "rule_following_baseline", "status_quo")
OPE_TARGETS = ("no_offer", "rule_following_baseline", "segment_oracle", "bandit")


@dataclass(frozen=True)
class Evaluation:
    summary: RunSummary
    frontier: dict[str, Any]
    audit_clean: bool
    audit: tuple[dict[str, Any], ...] = ()  # every audited rollout with its counts


def split(cohort: Cohort, cfg: RunConfig) -> dict[str, Cohort]:
    names = assign_cohorts(list(cohort.msno), cfg.holdout_salt, dict(cfg.cohort_buckets))
    parts = {n: cohort.subset(names == n) for n in ("holdout", "train", "logging", "eval")}
    ev = parts["eval"]
    if cfg.eval_sample is not None and len(ev) > cfg.eval_sample:
        # keyed by member: a member is sampled or not whatever else is in the cohort (L-29)
        key = member_uniforms(cfg.seed, ev.hashes, 0, "eval-sample")[:, 0]
        keep = np.zeros(len(ev), bool)
        keep[np.argsort(key, kind="stable")[: cfg.eval_sample]] = True
        parts["eval"] = ev.subset(keep)
    for n, c in parts.items():
        if len(c) == 0:
            raise ValueError(f"the {n} cohort is empty; the March cohort is too small")
    check_split(parts, cfg)
    return parts


def holdout_flags(cohort: Cohort, cfg: RunConfig) -> np.ndarray:
    """Re-derived from the salted hash for exactly these members, never taken from the split."""
    names = assign_cohorts(list(cohort.msno), cfg.holdout_salt, dict(cfg.cohort_buckets))
    return names == "holdout"


def check_split(parts: dict[str, Cohort], cfg: RunConfig) -> None:
    """Every member sits in the cohort its hash names, so no holdout member can be rolled out
    by an evaluation policy (R3)."""
    for name, c in parts.items():
        names = assign_cohorts(list(c.msno), cfg.holdout_salt, dict(cfg.cohort_buckets))
        wrong = int((names != name).sum())
        if wrong:
            raise ValueError(f"{wrong} members in the {name} cohort belong to another cohort (R3)")


def _audit(res, cohort: Cohort, policy: Policy, cfg: RunConfig) -> dict[str, int]:
    rep = audit(
        res.decisions,
        res.outcomes,
        churn_risk=pd.Series(cohort.churn_risk, index=cohort.msno),
        holdout=pd.Series(holdout_flags(cohort, cfg), index=cohort.msno, dtype=bool),
        risk_threshold=cfg.risk_threshold,
        context_columns={policy.name: tuple(policy.context_columns)},
        allow_list=cfg.decision_features,
    )
    return rep.violations(policy.name, res.decisions["variant"].iloc[0])


def evaluate_variant(
    scores: pd.DataFrame,
    features: pd.DataFrame,
    audit_attrs: pd.DataFrame,
    sim: SimulatorConfig,
    variant: str,
    cfg: RunConfig,
    r: Resampler,
    run_id: str,
) -> dict[str, Any]:
    cohort = build_cohort(scores, features, sim, variant, cfg.seed)
    parts = split(cohort, cfg)
    ev, H = parts["eval"], cfg.horizon_periods

    def roll(
        policy: Policy,
        c: Cohort,
        budget: float,
        ctx: np.ndarray | None = None,
        in_holdout: np.ndarray | None = None,
    ) -> RolloutResult:
        return rollout(
            policy,
            c,
            sim,
            variant,
            periods=H,
            risk_threshold=cfg.risk_threshold,
            budget_per_1000=budget,
            seed=cfg.seed,
            run_id=run_id,
            context=ctx,
            context_columns=cols if ctx is not None else (),
            in_holdout=holdout_flags(c, cfg) if in_holdout is None else in_holdout,
        )

    bandit = train_bandit(
        parts["train"],
        sim,
        variant,
        decision_features=cfg.decision_features,
        risk_threshold=cfg.risk_threshold,
        budget_per_1000=cfg.budget_per_1000_per_period,
        periods=H,
        epochs=BANDIT_EPOCHS,
        prior_precision=cfg.ts_prior_precision,
        noise_variance=cfg.ts_noise_variance,
        integration_nodes=cfg.ts_integration_nodes,
        support_floor=cfg.ts_support_floor,
        seed=cfg.seed,
    )
    ctx_ev = bandit.context_for(ev.features, ev.churn_risk)
    cols = tuple(bandit.posterior.columns)
    policies: list[tuple[Policy, np.ndarray | None]] = [
        (NoOffer(), None),
        (StatusQuo(), None),
        (RuleFollowingBaseline(), None),
        (bandit, ctx_ev),
        (SegmentOracle(), None),
    ]

    def run(policy: Policy, ctx: np.ndarray | None, budget: float) -> RolloutResult:
        return roll(policy, ev, budget, ctx)

    results = {p.name: run(p, c, cfg.budget_per_1000_per_period) for p, c in policies}
    outs = {name: member_outcomes(ev, res, H) for name, res in results.items()}
    at_risk = ev.churn_risk >= cfg.risk_threshold
    summaries: dict[str, PolicySummary] = {}
    draws: dict[str, Draws] = {}
    violations: dict[str, dict[str, int]] = {}
    audits: list[dict[str, Any]] = []

    def note(policy: Policy, rollout_kind: str, counts: dict[str, int]) -> None:
        audits.append(
            {
                "variant": variant,
                "policy": policy.name,
                "rollout": rollout_kind,
                "respectful": policy.respectful,
                "violations": counts,
            }
        )

    for policy, _ in policies:
        violations[policy.name] = _audit(results[policy.name], ev, policy, cfg)
        note(policy, "evaluation", violations[policy.name])
        summaries[policy.name], draws[policy.name] = summarise(
            policy.name,
            variant,
            policy.respectful,
            ev,
            outs[policy.name],
            outs["no_offer"],
            at_risk,
            results[policy.name].spend,
            violations[policy.name],
            bandit.summary()["exploration_rate"] if policy is bandit else None,
            r,
        )
    bandit.reset_counts()  # later rollouts (sweep) never reach the reported exploration rate

    # holdout: never offered anything; its retention should match no offer on the eval cohort
    hold = parts["holdout"]
    hold_res = roll(Holdout(), hold, 0.0)
    hold_viol = _audit(hold_res, hold, Holdout(), cfg)
    note(Holdout(), "holdout", hold_viol)
    hold_out = member_outcomes(hold, hold_res, H)
    _, h_draws = r.sums(r.block_of(hold.hashes), hold_out.retained)
    _, h_counts = r.sums(r.block_of(hold.hashes), np.ones(len(hold)))
    _, e_draws = r.sums(r.block_of(ev.hashes), outs["no_offer"].retained)
    _, e_counts = r.sums(r.block_of(ev.hashes), np.ones(len(ev)))
    diff_point = 1000.0 * (hold_out.retained.mean() - outs["no_offer"].retained.mean())
    h_rate = h_draws / np.where(h_counts > 0, h_counts, np.nan)  # empty resamples are dropped
    e_rate = e_draws / np.where(e_counts > 0, e_counts, np.nan)
    diff_draws = 1000.0 * (h_rate - e_rate)
    holdout_check = interval(diff_point, diff_draws)

    # off-policy estimates at period 1, beside the exact oracle
    lg = parts["logging"]
    ctx_lg = bandit.context_for(lg.features, lg.churn_risk)  # the posterior's column order
    view = period1_view(
        lg, sim, variant, cfg.risk_threshold, ctx_lg, periods=H, context_columns=cols
    )
    pilot = rollout(
        LoggingPolicy(),
        lg,
        sim=sim,
        variant=variant,
        periods=1,
        risk_threshold=cfg.risk_threshold,
        budget_per_1000=0.0,
        seed=cfg.seed,
        run_id=run_id,
        in_holdout=holdout_flags(lg, cfg),
    )
    note(LoggingPolicy(), "logging_pilot", _audit(pilot, lg, LoggingPolicy(), cfg))
    logs = logs_from_pilot(lg, pilot, ctx_lg, view, variant)
    q = fit_reward_model(logs, seed=cfg.seed)
    truth = expected_reward_by_segment(
        lg.base, lg.segment, lg.price, Tables.from_config(sim, variant)
    )
    targets = {
        "no_offer": NoOffer(),
        "rule_following_baseline": RuleFollowingBaseline(),
        "segment_oracle": SegmentOracle(),
        "bandit": bandit,
    }
    ope: list[OPEEstimate] = []
    for name in OPE_TARGETS:
        target = target_probabilities(targets[name], view)
        exact = oracle_value(target, truth)
        for est in ("ips", "snips", "dr"):
            iv, ess = estimate(
                logs,
                target,
                est,
                q=q if est == "dr" else None,
                blocks=cfg.bootstrap_blocks,
                resamples=cfg.bootstrap_resamples,
                seed=cfg.seed,
            )
            ope.append(
                OPEEstimate(
                    policy=name,
                    variant=variant,
                    estimator=est,
                    value=iv,  # type: ignore[arg-type]
                    oracle=round(exact, 6),
                    covered=iv.lo <= round(exact, 6) <= iv.hi,
                    effective_sample_size=round(ess, 3),
                )
            )

    # comparisons: paired on shared resamples, Holm per metric
    comparisons: list[Comparison] = []
    for metric in METRICS:
        pairs = [(a, b) for i, a in enumerate(COMPARED) for b in COMPARED[i + 1 :]]
        rows = []
        for a, b in pairs:
            got = [_metric(summaries[x], draws[x], metric) for x in (a, b)]
            if got[0] is None or got[1] is None:
                continue  # a policy that spends nothing has no members-per-NTD ratio
            (pa, da), (pb, db) = got[0], got[1]
            iv, p = paired(pa, da, pb, db)
            rows.append((a, b, iv, p))
        if not rows:
            continue
        sep = holm([row[3] for row in rows])
        for (a, b, iv, p), s in zip(rows, sep, strict=True):
            separated = bool(s) and not (iv.lo <= 0 <= iv.hi)
            comparisons.append(
                Comparison(
                    variant=variant,
                    metric=metric,
                    a=a,
                    b=b,
                    diff=iv,  # type: ignore[arg-type]
                    p_value=round(p, 6),
                    separated=separated,
                )
            )

    # budget frontier, with block-bootstrap intervals on the shared resamples
    frontier = []
    ev_block = r.block_of(ev.hashes)
    for budget in cfg.budget_sweep:
        for p, c in policies:
            if p.name not in SWEPT:
                continue
            res = run(p, c, budget)
            counts = _audit(res, ev, p, cfg)
            note(p, f"sweep:{budget:g}", counts)
            o = member_outcomes(ev, res, H)
            kept, _ = mean_interval(r, ev_block, o.retained, scale=1000.0)
            inc, _ = mean_interval(
                r, ev_block, o.retained - outs["no_offer"].retained, scale=1000.0
            )
            frontier.append(
                {
                    "variant": variant,
                    "policy": p.name,
                    "budget_per_1000": budget,
                    "retained_per_1000": round(1000 * o.retained.mean(), 4),
                    "incremental_per_1000": round(
                        1000 * (o.retained - outs["no_offer"].retained).mean(), 4
                    ),
                    "spend_per_member": round(math.fsum(o.cost) / len(ev), 4),
                    "retained_lo": round(kept.lo, 4),
                    "retained_hi": round(kept.hi, 4),
                    "incremental_lo": round(inc.lo, 4),
                    "incremental_hi": round(inc.hi, 4),
                }
            )

    return {
        "summaries": list(summaries.values()),
        "ope": ope,
        "comparisons": comparisons,
        "holdout_check": holdout_check,
        "holdout_violations": hold_viol,
        "frontier": frontier,
        "learning_curve": bandit.posterior.learning_curve,
        "posterior": bandit.posterior.to_json(),
        "outs": outs,
        "eval": ev,
        "audit": audits,
        "clean": all(sum(a["violations"].values()) == 0 for a in audits if a["respectful"]),
    }


def _metric(summary: PolicySummary, d: Draws, metric: str) -> tuple[float, np.ndarray] | None:
    if metric == "incremental_retained_per_1000":
        return summary.incremental_retained_per_1000.point, d.incremental
    if metric == "ltv_proxy_per_member":
        return summary.ltv_proxy_per_member.point, d.ltv
    if d.per_ntd_point is None or d.per_ntd is None:
        return None
    return d.per_ntd_point, d.per_ntd


DISPARITY_POLICIES = ("rule_following_baseline", "bandit")
DISPARITY_ATTRIBUTES = ("age_band", "gender")
MIN_GROUP = 30  # smaller groups are suppressed: too noisy to read and too close to identifying


def disparity(
    ev: Cohort, outs: dict[str, Any], audit_attrs: pd.DataFrame, r: Resampler
) -> dict[str, dict[str, Any]]:
    """Offer rate (shown offers per member-month) and retained per 1,000 by age band and
    gender, for each respectful policy that makes offers. Keys are `policy.metric.attribute`
    (D-34). Audit only: these attributes are never decision inputs (R7)."""
    attrs = audit_attrs.set_index("msno").reindex(ev.msno)
    block = r.block_of(ev.hashes)
    result: dict[str, dict[str, Any]] = {}
    for policy in DISPARITY_POLICIES:
        out = outs[policy]
        for attr in DISPARITY_ATTRIBUTES:
            col = attrs[attr].astype(object).where(attrs[attr].notna(), "unknown").to_numpy()
            rate: dict[str, Any] = {}
            kept: dict[str, Any] = {}
            sizes = {g: int((col == g).sum()) for g in sorted(set(col))}
            hidden = {g for g, n in sizes.items() if n < MIN_GROUP}
            if len(hidden) == 1 and len(sizes) > 1:
                # complementary suppression: with one group hidden, the totals would give it
                # away by subtraction, so the next-smallest group is hidden too (D-38)
                hidden.add(min((g for g in sizes if g not in hidden), key=lambda g: (sizes[g], g)))
            for g in sizes:
                m = (col == g).astype(float)
                if g in hidden:
                    continue
                n_tot, n_draws = r.sums(block, out.offers * m)
                d_tot, d_draws = r.sums(block, out.months * m)
                rate[g] = interval(n_tot / d_tot, n_draws / np.where(d_draws > 0, d_draws, np.nan))
                k_tot, k_draws = r.sums(block, out.retained * m)
                c_tot, c_draws = r.sums(block, m)
                kept[g] = interval(
                    1000.0 * k_tot / c_tot,
                    1000.0 * k_draws / np.where(c_draws > 0, c_draws, np.nan),
                )
            if rate:
                result[f"{policy}.offer_rate.{attr}"] = rate
                result[f"{policy}.retained_per_1000.{attr}"] = kept
    return result


def check_inputs(scores: pd.DataFrame, features: pd.DataFrame, audit_attrs: pd.DataFrame) -> None:
    """The three tables must describe the same March members, once each (EVL-09)."""
    for name, df in (("scores", scores), ("features", features), ("audit attributes", audit_attrs)):
        if df["msno"].duplicated().any():
            raise ValueError(f"the {name} table lists a member more than once")
    s, f, a = set(scores["msno"]), set(features["msno"]), set(audit_attrs["msno"])
    if s != f:
        raise ValueError(
            f"churn scores and March features describe different members ({len(s - f)} scored "
            f"without features, {len(f - s)} with features but no score): rebuild the churn stage"
        )
    if not f <= a:
        raise ValueError(f"{len(f - a)} March members have no audit attributes row")
    if "cohort" in features.columns and set(features["cohort"]) != {"mar"}:
        raise ValueError("evaluation runs on the March cohort only")


def run_evaluation(
    scores: pd.DataFrame,
    features: pd.DataFrame,
    audit_attrs: pd.DataFrame,
    churn: ChurnReport,
    sim: SimulatorConfig,
    cfg: RunConfig,
    *,
    run_id: str,
    git_sha: str,
    config_hash: str,
    simulator_hash: str,
    prereg_status: str,
    data_source: str = "synthetic",
) -> Evaluation:
    started = dt.datetime.now(dt.UTC)
    check_inputs(scores, features, audit_attrs)
    r = Resampler.create(cfg.bootstrap_blocks, cfg.bootstrap_resamples, cfg.seed)
    policies, ope, comps, frontier, curves = [], [], [], [], {}
    holdout: dict[str, Any] = {}
    audit_rows: list[dict[str, Any]] = []
    clean = True
    central: dict[str, Any] | None = None
    for variant in cfg.variants:
        res = evaluate_variant(scores, features, audit_attrs, sim, variant, cfg, r, run_id)
        policies += res["summaries"]
        ope += res["ope"]
        comps += res["comparisons"]
        frontier += res["frontier"]
        holdout[variant] = res["holdout_check"]
        curves[variant] = {
            "learning_curve": res["learning_curve"],
            "posterior": json.loads(res["posterior"]),
        }
        clean &= res["clean"]
        audit_rows += res["audit"]
        if variant == "central" or central is None:
            central = res
    assert central is not None
    summary = RunSummary(
        schema_version="1.0",
        run_id=run_id,
        git_sha=git_sha,
        config_hash=config_hash,
        simulator_hash=simulator_hash,
        prereg_status=prereg_status,  # type: ignore[arg-type]
        data_source=data_source,  # type: ignore[arg-type]
        simulated=True,
        variants=cfg.variants,
        policies=tuple(policies),
        ope=tuple(ope),
        comparisons=tuple(comps),
        churn=churn,
        holdout_check=holdout,
        disparity=disparity(central["eval"], central["outs"], audit_attrs, r),
        started_at=started,
        finished_at=dt.datetime.now(dt.UTC),
    )
    return Evaluation(summary, {"frontier": frontier, "bandit": curves}, clean, tuple(audit_rows))


def write(evaluation: Evaluation, out: Path, *, stable: bool = False) -> None:
    """Write summary.json and frontier.json. `stable` blanks the clock fields for golden runs."""
    out.mkdir(parents=True, exist_ok=True)
    data = json.loads(evaluation.summary.model_dump_json())
    if stable:
        data["started_at"] = "2026-11-21T00:00:00Z"
        data["finished_at"] = "2026-11-21T00:00:00Z"
    (out / "summary.json").write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / "frontier.json").write_text(
        json.dumps(evaluation.frontier, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
