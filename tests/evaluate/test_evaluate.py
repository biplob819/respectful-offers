"""A2.7: evaluate and compare (EVL-01..09). One evaluation of a synthetic March cohort is run
once per module and shared; the golden tests rerun it to prove it is byte-identical."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from harness_lib import ROOT
from respectful_offers.churn.model import report, train
from respectful_offers.data.synthetic import SyntheticSpec, generate
from respectful_offers.evaluate.pipeline import (
    COMPARED,
    HEADLINE,
    METRICS,
    OPE_TARGETS,
    SWEPT,
    Evaluation,
    check_inputs,
    run_evaluation,
    split,
    write,
)
from respectful_offers.evaluate.stats import Resampler, holm, paired
from respectful_offers.features.build import build_audit_attributes, build_cohort
from respectful_offers.policy.cohort import build_cohort as build_policy_cohort
from respectful_offers.schemas import load_simulator_config
from respectful_offers.schemas.config import load_run_config
from respectful_offers.schemas.summary import RunSummary

POLICIES = ("no_offer", "status_quo", "rule_following_baseline", "bandit", "segment_oracle")
VARIANTS = ("conservative", "central", "optimistic")


@pytest.fixture(scope="module")
def inputs(tmp_path_factory):
    raw = tmp_path_factory.mktemp("raw")
    generate(raw, SyntheticSpec(n_members=8000, seed=11))
    feb, mar = build_cohort(raw, "feb").features, build_cohort(raw, "mar").features
    attrs = build_audit_attributes(raw, pd.Series(sorted(set(mar["msno"]))))
    model, _ = train(feb, seed=1)
    rep = report(model, feb, mar, seed=1)
    scores = pd.DataFrame({"msno": mar["msno"].astype(str), "churn_risk": model.risk(mar)})
    sim = load_simulator_config(ROOT / "configs" / "simulator.yaml")
    cfg = load_run_config(ROOT / "configs" / "run.yaml").model_copy(
        update={
            "bootstrap_blocks": 200,
            "bootstrap_resamples": 1000,
            "budget_sweep": (0.0, 3000.0, 12000.0),
        }
    )
    return scores, mar, attrs, rep, sim, cfg


def evaluate(inputs, **kw) -> Evaluation:
    scores, mar, attrs, rep, sim, cfg = inputs
    return run_evaluation(
        scores,
        mar,
        attrs,
        rep,
        sim,
        kw.get("cfg", cfg),
        run_id="golden",
        git_sha="0" * 7,
        config_hash="c",
        simulator_hash="s",
        prereg_status="exploratory",
    )


@pytest.fixture(scope="module")
def ev(inputs) -> Evaluation:
    return evaluate(inputs)


def rows(ev, **match):
    return [p for p in ev.summary.policies if all(getattr(p, k) == v for k, v in match.items())]


# -- EVL-01 rollouts --------------------------------------------------------------------------


def test_every_policy_runs_under_every_variant_on_the_same_members(ev):
    s = ev.summary
    assert s.variants == VARIANTS
    assert {(p.policy, p.variant) for p in s.policies} == {
        (a, v) for a in POLICIES for v in VARIANTS
    }
    assert len({p.n_members for p in s.policies}) == 1  # one evaluation cohort for all


def test_cohorts_are_disjoint_and_the_split_is_stable(inputs):
    scores, mar, _, _, sim, cfg = inputs
    c = build_policy_cohort(scores, mar, sim, "central", cfg.seed)
    a, b = split(c, cfg), split(c, cfg)
    seen: set[str] = set()
    for name in ("holdout", "train", "logging", "eval"):
        members = set(a[name].msno)
        assert members == set(b[name].msno) and not members & seen
        seen |= members
    assert seen == set(c.msno)


# -- EVL-02 metrics ----------------------------------------------------------------------------


def test_metrics_follow_their_definitions(ev):
    for v in VARIANTS:
        base = rows(ev, policy="no_offer", variant=v)[0]
        assert base.incremental_retained_per_1000.point == 0.0 and base.discount_cost_total == 0.0
        assert base.no_offer_share == 1.0 and base.cost_per_incremental_retained is None
        for p in rows(ev, variant=v):
            inc = p.retained_per_1000.point - base.retained_per_1000.point
            assert p.incremental_retained_per_1000.point == pytest.approx(inc, abs=1e-5)
            assert (p.exploration_rate is not None) == (p.policy == "bandit")
            assert 0.0 <= p.no_offer_share <= 1.0
            if p.cost_per_incremental_retained is not None:  # only when surely positive
                assert p.incremental_retained_per_1000.lo > 0
            elif p.incremental_retained_per_1000.lo > 0:
                pytest.fail(f"{p.policy}: a bounded ratio exists but was not reported")
            if p.cost_per_incremental_retained is not None:
                extra = p.incremental_retained_per_1000.point * p.n_members / 1000
                ratio = p.discount_cost_total / extra
                assert p.cost_per_incremental_retained.point == pytest.approx(ratio, rel=1e-3)
            for iv in (p.retained_per_1000, p.ltv_proxy_per_member, p.offers_per_member_month):
                assert iv.lo <= iv.point <= iv.hi
            realised = sum(x.realised_cost for x in p.spend)
            assert realised <= sum(x.face_value_committed for x in p.spend) + 1e-6


def test_the_oracle_has_the_highest_value_in_every_variant(ev):
    for v in VARIANTS:
        ltv = {p.policy: p.ltv_proxy_per_member.point for p in rows(ev, variant=v)}
        assert max(ltv, key=lambda k: ltv[k]) == "segment_oracle", ltv


# -- EVL-03 paired comparisons and Holm --------------------------------------------------------


def test_holm_by_hand():
    assert holm([0.01, 0.04, 0.03]) == [True, False, False]  # 0.01 ≤ .05/3; 0.03 > .05/2
    assert holm([0.01, 0.02, 0.04]) == [True, True, True]
    assert holm([0.2, 0.01]) == [False, True]


def test_paired_differences_use_shared_resamples():
    r = Resampler.create(50, 500, 1)
    rng = np.random.default_rng(0)
    block = r.block_of(np.arange(5000, dtype=np.uint64))
    _, a = r.sums(block, rng.normal(size=5000))
    iv, p = paired(1.0, a, 1.0, a)
    assert iv.point == iv.lo == iv.hi == 0.0 and p == 1.0


def test_comparisons_cover_every_pair_metric_and_variant(ev):
    c = ev.summary.comparisons
    pairs = len(COMPARED) * (len(COMPARED) - 1) // 2
    assert len(c) <= len(VARIANTS) * len(METRICS) * pairs
    for v in VARIANTS:
        for m in ("incremental_retained_per_1000", "ltv_proxy_per_member"):
            assert sum(x.variant == v and x.metric == m for x in c) == pairs
        # the pre-registered headline is tested wherever both policies spend
        head = [
            x
            for x in c
            if x.variant == v
            and x.metric == HEADLINE
            and {x.a, x.b} == {"bandit", "rule_following_baseline"}
        ]
        spend = {p.policy: p.discount_cost_total for p in rows(ev, variant=v)}
        assert len(head) == int(spend["bandit"] > 0 and spend["rule_following_baseline"] > 0)
    for x in c:
        if x.separated:
            assert not (x.diff.lo <= 0.0 <= x.diff.hi)


# -- EVL-04 OPE beside the oracle --------------------------------------------------------------


def test_ope_estimates_every_target_beside_the_exact_oracle(ev):
    o = ev.summary.ope
    keys = {(x.policy, x.variant, x.estimator) for x in o}
    assert keys == {
        (p, v, e) for p in OPE_TARGETS for v in VARIANTS for e in ("ips", "snips", "dr")
    }
    dr = [x for x in o if x.estimator == "dr"]
    assert sum(x.covered for x in dr) >= len(dr) - 2  # nominal 95%: allow a miss or two
    for x in o:
        assert x.covered == (x.value.lo <= x.oracle <= x.value.hi)
        assert x.effective_sample_size > 0


# -- EVL-05 audit ------------------------------------------------------------------------------


def test_respectful_policies_audit_clean_and_the_status_quo_is_reported(ev):
    assert ev.audit_clean
    for p in ev.summary.policies:
        total = sum(p.violations.values())
        assert (total == 0) if p.respectful else (total > 0)
        assert p.violations["R3"] == 0  # not even the status quo contacts the holdout
    kinds = {a["rollout"].split(":")[0] for a in ev.audit}
    assert kinds == {"evaluation", "holdout", "logging_pilot", "sweep"}  # every rollout audited
    for a in ev.audit:
        if a["respectful"]:
            assert sum(a["violations"].values()) == 0, a


def test_cli_exits_1_when_the_audit_fails(tmp_path, monkeypatch):
    """A real violation flows through: a broken respect filter lets respectful policies
    offer discounts to unnudged members at risk (R2), the independent auditor counts it, and
    the command exits 1."""
    from respectful_offers import cli
    from respectful_offers.policy import rollout as rollout_module

    monkeypatch.setattr(
        rollout_module, "allowed_actions", lambda **k: np.ones((len(k["churn_risk"]), 4), bool)
    )
    data = tmp_path / "data"
    assert cli.main(["data", "synthetic", "--data-dir", str(data), "--members", "3000"]) == 0
    code = cli.main(
        ["evaluate", "--data-dir", str(data), "--root", str(tmp_path), "--run-id", "a", "--json"]
    )
    assert code == cli.EXIT_AUDIT


# -- EVL-06 holdout ----------------------------------------------------------------------------


def test_holdout_matches_no_offer_and_is_never_contacted(ev, inputs):
    for v in VARIANTS:
        h = ev.summary.holdout_check[v]
        assert h.lo <= 0.0 <= h.hi
        held = [a for a in ev.audit if a["variant"] == v and a["rollout"] == "holdout"]
        assert len(held) == 1 and sum(held[0]["violations"].values()) == 0
    # a holdout member moved into the evaluation cohort is refused before any rollout
    scores, mar, _, _, sim, cfg = inputs
    from respectful_offers.evaluate.pipeline import check_split

    parts = split(build_policy_cohort(scores, mar, sim, "central", cfg.seed), cfg)
    leaked = dict(parts)
    hold = parts["holdout"]
    first = np.zeros(len(hold), bool)
    first[0] = True
    from respectful_offers.policy.cohort import Cohort

    fields = (
        "msno",
        "hashes",
        "churn_risk",
        "base",
        "price",
        "cells",
        "risk_band",
        "trend_band",
        "segment",
    )
    one = hold.subset(first)
    arrays = {f: np.concatenate([getattr(parts["eval"], f), getattr(one, f)]) for f in fields}
    merged = Cohort(
        **arrays, features=pd.concat([parts["eval"].features, one.features], ignore_index=True)
    )
    leaked["eval"] = merged
    with pytest.raises(ValueError, match="belong to another cohort"):
        check_split(leaked, cfg)


# -- EVL-07 budget frontier --------------------------------------------------------------------


def test_budget_sweep_covers_every_level_and_spends_within_it(ev, inputs):
    cfg = inputs[-1]
    f = ev.frontier["frontier"]
    assert {(x["variant"], x["policy"], x["budget_per_1000"]) for x in f} == {
        (v, p, b) for v in VARIANTS for p in SWEPT for b in cfg.budget_sweep
    }
    for x in f:
        # face value per period ≤ budget per member; realised over H periods ≤ face over H
        assert x["spend_per_member"] <= x["budget_per_1000"] / 1000 * cfg.horizon_periods + 1e-9
    zero = [x for x in f if x["budget_per_1000"] == 0.0]
    assert all(x["spend_per_member"] == 0.0 for x in zero)


# -- EVL-08 disparity --------------------------------------------------------------------------


def test_disparity_is_reported_by_policy_metric_and_attribute(ev):
    d = ev.summary.disparity
    want = {
        f"{p}.{m}.{a}"
        for p in ("rule_following_baseline", "bandit")
        for m in ("offer_rate", "retained_per_1000")
        for a in ("age_band", "gender")
    }
    assert set(d) == want
    for groups in d.values():
        for iv in groups.values():
            assert iv.lo <= iv.point <= iv.hi


def test_protected_attributes_are_never_decision_features(inputs):
    cfg = inputs[-1]
    assert not {"age_band", "gender", "bd", "city", "registered_via"} & set(cfg.decision_features)


# -- EVL-09 summary.json -----------------------------------------------------------------------


def test_disparity_suppression_cannot_be_undone_by_subtraction():
    from respectful_offers.evaluate.metrics import MemberOutcomes
    from respectful_offers.evaluate.pipeline import disparity

    n = 400
    from respectful_offers.policy.cohort import Cohort
    from respectful_offers.runtime.seeds import member_hashes

    msno = np.array([f"M{i:04d}" for i in range(n)], dtype=object)
    c = Cohort(
        msno,
        member_hashes([str(m) for m in msno]),
        np.full(n, 0.1),
        np.full(n, 0.9),
        np.full(n, 149.0),
        np.zeros(n, int),
        np.full(n, "low", object),
        np.full(n, "stable", object),
        np.zeros(n, int),
        pd.DataFrame({"msno": msno}),
    )
    gender = np.array(["female"] * 16 + ["male"] * 184 + ["unknown"] * 200, dtype=object)
    attrs = pd.DataFrame({"msno": msno, "gender": gender, "age_band": "25-34"})
    out = MemberOutcomes(
        np.ones(n), np.zeros(n), np.zeros(n), np.ones(n), np.full(n, 3.0), 1, 3 * n, 0
    )
    d = disparity(
        c, {"rule_following_baseline": out, "bandit": out}, attrs, Resampler.create(50, 200, 0)
    )
    groups = set(d["bandit.offer_rate.gender"])
    assert "female" not in groups and "male" not in groups  # the next-smallest is hidden too
    assert groups == {"unknown"}


def test_thin_data_gives_null_or_refuses_never_a_fake_interval():
    from respectful_offers.evaluate.stats import interval

    with pytest.raises(ValueError, match="undefined"):
        interval(1.0, np.array([1.0] * 95 + [np.nan] * 5))
    assert interval(1.0, np.array([1.0] * 995 + [np.nan] * 5)).point == 1.0


def test_summary_is_stamped_and_round_trips(ev, tmp_path):
    write(ev, tmp_path, stable=True)
    text = (tmp_path / "summary.json").read_text(encoding="utf-8")
    s = RunSummary.model_validate_json(text)
    assert s.simulated is True and s.prereg_status == "exploratory"
    assert (s.git_sha, s.config_hash, s.simulator_hash) == ("0" * 7, "c", "s")
    assert s.churn.auc.lo <= s.churn.auc.point <= s.churn.auc.hi


def test_misaligned_inputs_are_refused(inputs):
    scores, mar, attrs, *_ = inputs
    with pytest.raises(ValueError, match="different members"):
        check_inputs(scores.iloc[1:], mar, attrs)
    with pytest.raises(ValueError, match="more than once"):
        check_inputs(pd.concat([scores, scores.iloc[:1]]), mar, attrs)
    with pytest.raises(ValueError, match="no audit attributes"):
        check_inputs(scores, mar, attrs.iloc[1:])


@pytest.mark.golden
def test_the_evaluation_is_byte_identical_on_a_rerun(ev, inputs, tmp_path):
    write(ev, tmp_path / "a", stable=True)
    write(evaluate(inputs), tmp_path / "b", stable=True)
    for name in ("summary.json", "frontier.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


@pytest.mark.golden
def test_offers_evaluate_end_to_end_on_synthetic_data(tmp_path):
    from respectful_offers import cli

    data = tmp_path / "data"
    assert cli.main(["data", "synthetic", "--data-dir", str(data), "--members", "4000"]) == 0
    args = ["evaluate", "--data-dir", str(data), "--root", str(tmp_path), "--run-id", "g"]
    assert cli.main([*args, "--variant", "central"]) == 0
    run = tmp_path / "runs" / "g"
    s = RunSummary.model_validate_json((run / "summary.json").read_text(encoding="utf-8"))
    assert s.variants == ("central",) and s.prereg_status == "preregistered"
    from respectful_offers.sim.prereg import sha256

    assert s.git_sha == "unknown"  # the tmp project is not a git repository
    assert s.simulator_hash == sha256(ROOT / "configs" / "simulator.yaml")[:16]
    assert s.config_hash == sha256(ROOT / "configs" / "run.yaml")[:16]
    audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
    assert audit["clean"] is True and audit["rollouts"]
    lineage = json.loads((run / "run.json").read_text(encoding="utf-8"))
    assert [x["stage"] for x in lineage["stages"]][-3:] == ["features", "churn", "evaluate"]
    assert cli.main([*args, "--variant", "central"]) == 0  # second run: all cached
    lineage = json.loads((run / "run.json").read_text(encoding="utf-8"))
    assert all(x["cache_hit"] for x in lineage["stages"] if x["stage"] == "evaluate")
    assert cli.main([*args, "--variant", "nonesuch"]) == cli.EXIT_ERROR
    assert cli.main([*args, "--variant", "central", "--exploratory"]) == 0
    assert Path(run / "audit.json").is_file()


def test_json_is_printed_even_when_a_command_crashes(tmp_path, monkeypatch, capsys):
    from respectful_offers import cli
    from respectful_offers.evaluate import stage

    def boom(*a, **k):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(stage, "run_evaluation", boom)
    data = tmp_path / "data"
    assert cli.main(["data", "synthetic", "--data-dir", str(data), "--members", "3000"]) == 0
    capsys.readouterr()
    code = cli.main(["evaluate", "--data-dir", str(data), "--root", str(tmp_path), "--json"])
    out = capsys.readouterr().out.strip().splitlines()[-1]
    assert code == cli.EXIT_ERROR and json.loads(out) == {
        "ok": False,
        "error": "RuntimeError: synthetic failure",
    }
