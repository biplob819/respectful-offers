#!/usr/bin/env python3
"""Read real decisions end to end (REA-02, L-11): replay a finished run's evaluation rollouts.

Rebuilds the run's evaluation cohort from its own stored features and scores, replays every
policy for one variant with the run's frozen bandit posterior, checks the replay reproduces the
run's numbers exactly, then:

  * writes a member-level trace of a stratified sample to <run>/decision_review/ (git-ignored,
    never published: it holds member ids), and
  * prints aggregate findings (no member ids) for the committed review.

    uv run python scripts/review_decisions.py --run runs/real-v2 [--variant central] [--n 40]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def stage_dir(run: dict, stage: str, root: Path) -> Path:
    key = next(s["key"] for s in run["stages"] if s["stage"] == stage)
    return root / ".offers" / "store" / key[:2] / key


def rule_counts(d: pd.DataFrame, threshold: float) -> dict[str, int]:
    """R1 and R2 recounted from responses, independently of the auditor's code.

    R1: an action shown to a member who declined that same action in an earlier period.
    R2: a commercial offer to an at-risk member who was not shown a content nudge in an
    earlier period (in any period, not just the first)."""
    d = d.sort_values(["msno", "period"])
    r1 = 0
    for action in ("content_nudge", "discount_1m", "plan_change"):
        declined = ((d.chosen == action) & (d.response == "declined")).astype(int)
        before = declined.groupby(d.msno).cumsum() - declined
        r1 += int(((before > 0) & (d.chosen == action)).sum())
    nudge = (d.chosen == "content_nudge").astype(int)
    nudged_before = (nudge.groupby(d.msno).cumsum() - nudge) > 0
    commercial = d.chosen.isin(["discount_1m", "plan_change"])
    r2 = int((commercial & (d.churn_risk >= threshold) & ~nudged_before).sum())
    return {"r1_shown_again_after_decline": r1, "r2_commercial_at_risk_without_earlier_nudge": r2}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--variant", default="central")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv)

    from respectful_offers.evaluate.metrics import member_outcomes
    from respectful_offers.evaluate.pipeline import holdout_flags, split
    from respectful_offers.policy.bandit import Posterior, ThompsonBandit
    from respectful_offers.policy.baselines import (
        NoOffer,
        RuleFollowingBaseline,
        StatusQuo,
    )
    from respectful_offers.policy.cohort import build_cohort
    from respectful_offers.policy.rollout import rollout
    from respectful_offers.schemas import load_simulator_config
    from respectful_offers.schemas.config import load_run_config
    from respectful_offers.schemas.summary import RunSummary

    root, run_dir, variant = Path(args.root), Path(args.run), args.variant
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    summary = RunSummary.model_validate_json((run_dir / "summary.json").read_text(encoding="utf-8"))
    frontier = json.loads((run_dir / "frontier.json").read_text(encoding="utf-8"))
    cfg = load_run_config(root / "configs" / "run.yaml")
    sim = load_simulator_config(root / "configs" / "simulator.yaml")
    feats = pd.read_parquet(stage_dir(run, "features", root) / "features_mar.parquet")
    scores = pd.read_parquet(stage_dir(run, "churn", root) / "scores_mar.parquet")
    scores = scores[["msno", "churn_risk"]]
    ev = split(build_cohort(scores, feats, sim, variant, cfg.seed), cfg)["eval"]
    post = Posterior.from_json(json.dumps(frontier["bandit"][variant]["posterior"]))
    bandit = ThompsonBandit(
        np.zeros((0, len(post.columns))), list(post.columns), cfg.decision_features, posterior=post
    )
    ctx = bandit.context_for(ev.features, ev.churn_risk)
    H = cfg.horizon_periods

    def roll(policy, c=None):
        return rollout(
            policy,
            ev,
            sim,
            variant,
            periods=H,
            risk_threshold=cfg.risk_threshold,
            budget_per_1000=cfg.budget_per_1000_per_period,
            seed=cfg.seed,
            run_id=summary.run_id,
            context=c,
            context_columns=tuple(post.columns) if c is not None else (),
            in_holdout=holdout_flags(ev, cfg),
        )

    res = {
        "no_offer": roll(NoOffer()),
        "status_quo": roll(StatusQuo()),
        "rule_following_baseline": roll(RuleFollowingBaseline()),
        "bandit": roll(bandit, ctx),
    }
    outs = {k: member_outcomes(ev, r, H) for k, r in res.items()}

    # 1. the replay is the run: same members, same retained counts
    reported = {p.policy: p for p in summary.policies if p.variant == variant}
    repro = {}
    for name, o in outs.items():
        got = 1000.0 * float(np.mean(o.retained))
        want = reported[name].retained_per_1000.point
        repro[name] = (round(got, 4), round(want, 4))
        assert abs(got - want) < 1e-6, f"{name}: replay {got} != run {want}"
        shown = float((res[name].decisions.chosen != "no_offer").mean())
        rep = reported[name]
        assert abs(shown - rep.offers_per_member_month.point) < 1e-3, f"{name}: offers"
        cost = float(res[name].outcomes.discount_cost.sum())
        assert abs(cost - rep.discount_cost_total) < 1e-3 * max(1.0, cost), f"{name}: cost"
    assert len(ev) == reported["bandit"].n_members

    # 2. join decisions, outcomes and the hidden segment for every member-period
    seg_names = np.array(sim.segments, dtype=object)
    member = pd.DataFrame(
        {
            "msno": ev.msno,
            "segment": seg_names[ev.segment],
            "churn_risk": ev.churn_risk,
            "risk_band": ev.risk_band,
            "trend_band": ev.trend_band,
            "price_30d": ev.price,
        }
    )
    findings: dict[str, object] = {"replay_matches_run": repro, "members": len(ev)}
    traces = []
    for name in ("bandit", "rule_following_baseline", "status_quo"):
        d = res[name].decisions.merge(
            res[name].outcomes, on=["run_id", "variant", "policy", "msno", "period"]
        )
        d = d.merge(member, on="msno", how="left", validate="many_to_one")
        d["chosen_in_allowed"] = [c in a for c, a in zip(d.chosen, d.allowed, strict=True)]
        offered = d[d.chosen != "no_offer"]
        f: dict[str, object] = {
            "member_periods": len(d),
            "choice_outside_allowed": int((~d.chosen_in_allowed).sum()),
            "chosen": dict(Counter(d.chosen)),
            "budget_downgraded": int(d.budget_downgraded.sum()),
            "response_by_chosen": {
                a: dict(Counter(g.response)) for a, g in offered.groupby("chosen")
            },
            "renewal_rate_by_segment_when_offered": {
                s: round(float(g.renewed.mean()), 4) for s, g in offered.groupby("segment")
            },
            "offers_to_sleeping_dogs": int((offered.segment == "sleeping_dog").sum()),
            "offers_to_sure_things": int((offered.segment == "sure_thing").sum()),
            "commercial_to_at_risk_in_period1": int(
                (
                    (d.period == 1)
                    & (d.churn_risk >= cfg.risk_threshold)
                    & d.chosen.isin(["discount_1m", "plan_change"])
                ).sum()
            ),
            **rule_counts(d, cfg.risk_threshold),
        }
        # why members who were offered something still did not renew
        lost = offered[~offered.renewed.astype(bool)]
        counts = lost.groupby(["segment", "response"]).size()
        f["not_renewed_after_offer_by_segment_and_response"] = {
            f"{s}/{r}": int(n)
            for (s, r), n in zip(counts.index.tolist(), counts.tolist(), strict=True)
        }
        findings[name] = f
        # stratified sample for reading: at-risk and offered, offered and declined, sleeping
        # dogs offered something, at-risk but not offered that month
        rng = np.random.default_rng(20261117)
        strata = {
            "at_risk_offered": offered[offered.churn_risk >= cfg.risk_threshold],
            "offered_and_declined": offered[offered.response == "declined"],
            "sleeping_dog_offered": offered[offered.segment == "sleeping_dog"],
            "at_risk_not_offered_that_month": d[
                (d.chosen == "no_offer") & (d.churn_risk >= cfg.risk_threshold)
            ],
        }
        per = max(1, args.n // (len(strata) * 3))
        for sname, g in strata.items():
            ids = g.msno.drop_duplicates()
            pick = ids.sample(min(per, len(ids)), random_state=int(rng.integers(1 << 31)))
            for m in pick:
                t = d[d.msno == m].sort_values("period")
                traces.append(t.assign(stratum=sname))
    out = run_dir / "decision_review"
    out.mkdir(exist_ok=True)
    trace = pd.concat(traces)
    cols = [
        "policy",
        "stratum",
        "msno",
        "period",
        "segment",
        "churn_risk",
        "risk_band",
        "trend_band",
        "price_30d",
        "allowed",
        "requested",
        "chosen",
        "budget_downgraded",
        "response",
        "renewed",
        "revenue",
    ]
    trace[cols].to_csv(out / f"trace_{variant}.csv", index=False)
    (out / f"findings_{variant}.json").write_text(
        json.dumps(findings, indent=1, default=str), encoding="utf-8"
    )
    print(json.dumps(findings, indent=1, default=str))
    print(
        f"\ntrace of {trace.msno.nunique()} members: {out / f'trace_{variant}.csv'}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
