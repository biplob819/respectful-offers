"""Champion against challenger under common random numbers, and the promotion rule (E4.3 MON-02).

The challenger is a retrained churn model and a retrained bandit. Both policies are rolled
out on the champion's evaluation members, in the champion's simulated world: each member's
base retention and hidden segment come from the champion's scores, so the world does not
move when the challenger's model does. Only what a policy reads changes: the challenger's
decisions and respect rules see the challenger's churn risk. Decision and response draws
are keyed by member, period and variant, so both policies meet the same luck (D-1).

The comparison is this repo's own paired, member-level block bootstrap on the shared
resamples (D-16): challenger minus champion on extra members kept per 1,000 NTD, Holm across
the variants. The promotion rule (spec, stated before any challenger ran) promotes only if,
in every variant, the claim improves (lower bound > 0 and separated after Holm), neither
respectful policy breaks a rule, and no outcome check of the period fails (OWNER D-56).

The challenger trains on the training cohort and is judged on the evaluation cohort; the
salted-hash split keeps them apart (R3, D-8), so it is never tuned on what it is judged on.
A challenger can never change the pre-registered simulator (D-3).
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from respectful_offers.evaluate.metrics import member_outcomes, summarise
from respectful_offers.evaluate.pipeline import BANDIT_EPOCHS, HEADLINE, _audit, split
from respectful_offers.evaluate.stats import Resampler, holm, paired
from respectful_offers.metrics1 import CI_METHOD_PAIRED, _metric, validate_metrics1
from respectful_offers.policy.bandit import ThompsonBandit, train_bandit
from respectful_offers.policy.baselines import NoOffer
from respectful_offers.policy.cohort import Cohort, build_cohort
from respectful_offers.policy.rollout import rollout
from respectful_offers.schemas.config import RunConfig
from respectful_offers.schemas.simulator import SimulatorConfig

ARMS = ("champion", "challenger")


class ChallengeError(ValueError):
    """The challenge cannot be run without breaking a rule."""


@dataclass(frozen=True)
class Challenger:
    """How the challenger's bandit is retrained (its churn scores are passed in)."""

    seed: int
    epochs: int = BANDIT_EPOCHS


def with_risk(c: Cohort, risk: pd.Series) -> Cohort:
    """The same members in the same world, seen through another churn model."""
    got = risk.reindex(c.msno).to_numpy(dtype=float)
    if np.isnan(got).any():
        raise ChallengeError("the challenger's scores miss some of the champion's members")
    if not ((got >= 0) & (got <= 1)).all():
        raise ChallengeError("the challenger's churn risks must be probabilities")
    return dataclasses.replace(c, churn_risk=got)


def _train(c: Cohort, sim: SimulatorConfig, variant: str, cfg: RunConfig, seed: int, epochs: int):
    return train_bandit(
        c,
        sim,
        variant,
        decision_features=cfg.decision_features,
        risk_threshold=cfg.risk_threshold,
        budget_per_1000=cfg.budget_per_1000_per_period,
        periods=cfg.horizon_periods,
        epochs=epochs,
        prior_precision=cfg.ts_prior_precision,
        noise_variance=cfg.ts_noise_variance,
        integration_nodes=cfg.ts_integration_nodes,
        support_floor=cfg.ts_support_floor,
        seed=seed,
    )


def challenge_variant(
    champion_scores: pd.DataFrame,
    challenger_scores: pd.DataFrame,
    features: pd.DataFrame,
    sim: SimulatorConfig,
    variant: str,
    cfg: RunConfig,
    challenger: Challenger,
    r: Resampler,
    run_id: str,
) -> dict[str, Any]:
    world = build_cohort(champion_scores, features, sim, variant, cfg.seed)
    parts = split(world, cfg)
    risk = challenger_scores.set_index("msno")["churn_risk"]
    seen = {
        "champion": {n: parts[n] for n in ("train", "eval")},
        "challenger": {n: with_risk(parts[n], risk) for n in ("train", "eval")},
    }
    bandits: dict[str, ThompsonBandit] = {
        "champion": _train(seen["champion"]["train"], sim, variant, cfg, cfg.seed, BANDIT_EPOCHS),
        "challenger": _train(
            seen["challenger"]["train"], sim, variant, cfg, challenger.seed, challenger.epochs
        ),
    }
    H = cfg.horizon_periods

    def roll(policy, c: Cohort, ctx=None, cols=()):
        return rollout(
            policy,
            c,
            sim,
            variant,
            periods=H,
            risk_threshold=cfg.risk_threshold,
            budget_per_1000=cfg.budget_per_1000_per_period,
            seed=cfg.seed,  # the champion's seed: common random numbers for both arms
            run_id=run_id,
            context=ctx,
            context_columns=cols,
        )

    ev = parts["eval"]
    base = member_outcomes(ev, roll(NoOffer(), ev), H)
    at_risk = ev.churn_risk >= cfg.risk_threshold
    out: dict[str, Any] = {"variant": variant, "n_members": len(ev), "arms": {}}
    for arm in ARMS:
        c, b = seen[arm]["eval"], bandits[arm]
        res = roll(b, c, b.context_for(c.features, c.churn_risk), tuple(b.posterior.columns))
        viol = _audit(res, c, b, cfg)
        o = member_outcomes(c, res, H)
        s, d = summarise(
            "bandit", variant, True, c, o, base, at_risk, res.spend, viol, None, r
        )  # same members, same no-offer arm: incremental figures are paired across arms
        out["arms"][arm] = {"summary": s, "draws": d, "violations": viol}
    a, b = out["arms"]["challenger"]["draws"], out["arms"]["champion"]["draws"]
    if a.per_ntd is None or b.per_ntd is None or a.per_ntd_point is None:
        out["diff"], out["p_value"] = None, 1.0  # an arm that spends nothing has no claim ratio
    else:
        assert b.per_ntd_point is not None
        out["diff"], out["p_value"] = paired(a.per_ntd_point, a.per_ntd, b.per_ntd_point, b.per_ntd)
    return out


def decide(variants: list[dict[str, Any]], fail_alarms: list[dict[str, Any]]) -> dict[str, Any]:
    """The promotion rule, as the spec states it. Every reason it is not met is listed."""
    sep = holm([v["p_value"] for v in variants]) if variants else []
    reasons: list[str] = []
    rows = []
    for v, s in zip(variants, sep, strict=True):
        diff = v["diff"]
        separated = bool(s) and diff is not None and not (diff.lo <= 0 <= diff.hi)
        improved = diff is not None and diff.lo > 0 and separated
        rows.append({"variant": v["variant"], "improved": improved, "separated": separated})
        if not improved:
            reasons.append(
                f"{v['variant']}: the claim does not improve"
                + ("" if diff is None else f" (challenger minus champion lower bound {diff.lo})")
            )
        for arm in ARMS:
            n = sum(v["arms"][arm]["violations"].values())
            if n:
                reasons.append(f"{v['variant']}: the {arm} broke a respect rule {n} times")
    if not variants:
        reasons.append("no variant was compared")
    for a in fail_alarms:
        reasons.append(f"fail alarm ({a['check']}): {a['message']}")
    return {
        "decision": "NO-PROMOTION" if reasons else "PROMOTION",
        "variants": rows,
        "reasons": reasons,
    }


def run_challenge(
    champion_scores: pd.DataFrame,
    challenger_scores: pd.DataFrame,
    features: pd.DataFrame,
    sim: SimulatorConfig,
    cfg: RunConfig,
    challenger: Challenger,
    *,
    run_id: str,
    champion_simulator_hash: str | None,
    simulator_hash: str | None,
    fail_alarms: list[dict[str, Any]],
) -> dict[str, Any]:
    if not champion_simulator_hash or champion_simulator_hash != simulator_hash:
        raise ChallengeError(
            f"the simulator changed (champion {champion_simulator_hash}, now {simulator_hash}): "
            "a changed simulator needs a new pre-registration and a rerun of every variant (D-3)"
        )
    r = Resampler.create(cfg.bootstrap_blocks, cfg.bootstrap_resamples, cfg.seed)
    variants = [
        challenge_variant(
            champion_scores, challenger_scores, features, sim, v, cfg, challenger, r, run_id
        )
        for v in cfg.variants
    ]
    result = decide(variants, fail_alarms)
    result["compared"] = variants
    return result


def challenge_doc(
    result: dict[str, Any], *, run_id: str, created_at: str, provenance: dict[str, Any]
) -> dict[str, Any]:
    """Both arms and the paired comparison as metrics-1, for `evalkit compare` and the ledger."""
    metrics: list[dict[str, Any]] = []
    sep = {row["variant"]: row["separated"] for row in result["variants"]}
    for v in result["compared"]:
        var = v["variant"]
        for arm in ARMS:
            s = v["arms"][arm]["summary"]
            lab = {"arm": arm, "variant": var}
            metrics.append(_metric("retained_per_1000", "ratio", None, lab, iv=s.retained_per_1000))
            metrics.append(
                _metric(
                    "incremental_retained_per_1000",
                    "ratio",
                    None,
                    lab,
                    iv=s.incremental_retained_per_1000,
                )
            )
            if s.cost_per_incremental_retained is not None:
                metrics.append(
                    _metric(
                        "cost_per_incremental_retained",
                        "NTD",
                        None,
                        lab,
                        iv=s.cost_per_incremental_retained,
                    )
                )
            metrics.append(_metric("discount_cost_total", "NTD", s.discount_cost_total, lab))
            for rule, count in sorted(s.violations.items()):
                metrics.append(
                    _metric("violations", "count", count, {**lab, "rule": rule, "respectful": True})
                )
        lab = {"a": "challenger", "b": "champion", "variant": var}
        if v["diff"] is not None:
            metrics.append(
                _metric(
                    f"diff.{HEADLINE}", "ratio", None, lab, iv=v["diff"], method=CI_METHOD_PAIRED
                )
            )
        metrics.append(_metric(f"separated.{HEADLINE}", "bool", sep[var], lab))
        metrics.append(_metric(f"p_value.{HEADLINE}", "rate", round(v["p_value"], 6), lab))
    metrics.append(_metric("promoted", "bool", result["decision"] == "PROMOTION"))
    doc = {
        "schema_version": "metrics-1",
        "project": "respectful-offers",
        "run_id": run_id,
        "created_at": created_at,
        "simulated": True,  # offer responses come from the pre-registered simulator
        "provenance": provenance,
        "metrics": metrics,
    }
    validate_metrics1(doc)
    return doc


ID_RE = re.compile(r"^\| (?:OWNER )?D-(\d+) \|", re.MULTILINE)


def decision_row(result: dict[str, Any], *, date: str, champion: str, challenger: str) -> str:
    """A PROMOTION or NO-PROMOTION row for docs/decisions.md."""
    why = "; ".join(result["reasons"]) or "every condition of the promotion rule holds"
    why = why.replace("|", "/")
    return (
        f"| {result['decision']} | {date} | **Challenge {challenger} against champion "
        f"{champion}** (E4.3 MON-02, simulated outcomes). Promotion rule: claim improves in "
        f"every variant after Holm, zero respect violations, no fail alarm | "
        f"{'Promote' if result['decision'] == 'NO-PROMOTION' else 'Keep the champion'} | {why} |"
    )


def append_decision(path: Path, row: str) -> None:
    text = path.read_text(encoding="utf-8")
    if row.split(" | ")[2] in text:
        raise ChallengeError("this challenge is already recorded")
    path.write_text(text.rstrip("\n") + "\n" + row + "\n", encoding="utf-8", newline="\n")
