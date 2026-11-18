"""E4.3 MON-02: champion against challenger under common random numbers, and the promotion rule."""

import pandas as pd
import pytest

from harness_lib import ROOT
from respectful_offers.churn.model import train
from respectful_offers.data.synthetic import SyntheticSpec, generate
from respectful_offers.evaluate.stats import holm
from respectful_offers.features.build import build_cohort
from respectful_offers.metrics1 import validate_metrics1
from respectful_offers.monitor import challenge as ch
from respectful_offers.monitor.challenge import (
    ChallengeError,
    Challenger,
    append_decision,
    challenge_doc,
    decide,
    decision_row,
    run_challenge,
)
from respectful_offers.schemas import load_simulator_config
from respectful_offers.schemas.config import load_run_config
from respectful_offers.schemas.summary import Interval

PROV = {"code_version": "abc", "snapshot": None, "config_hash": None, "evalkit": None}


@pytest.fixture(scope="module")
def inputs(tmp_path_factory):
    raw = tmp_path_factory.mktemp("raw")
    generate(raw, SyntheticSpec(n_members=6000, seed=12))
    feb, mar = build_cohort(raw, "feb").features, build_cohort(raw, "mar").features
    champ, _ = train(feb, seed=1)
    chall, _ = train(feb, seed=2)
    msno = mar["msno"].astype(str)
    scores = {
        "champion": pd.DataFrame({"msno": msno, "churn_risk": champ.risk(mar)}),
        "challenger": pd.DataFrame({"msno": msno, "churn_risk": chall.risk(mar)}),
    }
    sim = load_simulator_config(ROOT / "configs" / "simulator.yaml")
    cfg = load_run_config(ROOT / "configs" / "run.yaml").model_copy(
        update={"bootstrap_blocks": 200, "bootstrap_resamples": 1000}
    )
    return scores, mar, sim, cfg


SEVEN = Challenger(seed=7)


def _run(inputs, challenger_scores=None, challenger=SEVEN, alarms=(), **kw):
    scores, mar, sim, cfg = inputs
    return run_challenge(
        scores["champion"],
        scores["challenger"] if challenger_scores is None else challenger_scores,
        mar,
        sim,
        kw.get("cfg", cfg),
        challenger,
        run_id="t",
        champion_simulator_hash=kw.get("champ_hash", "s"),
        simulator_hash=kw.get("hash", "s"),
        fail_alarms=list(alarms),
    )


@pytest.fixture(scope="module")
def result(inputs):
    return _run(inputs)


@pytest.fixture(scope="module")
def twin(inputs):
    """A challenger identical to the champion: same scores, same seed, same epochs."""
    scores, _, _, cfg = inputs
    return _run(inputs, scores["champion"], Challenger(seed=cfg.seed))


def test_an_identical_challenger_meets_exactly_the_same_luck(twin):
    # common random numbers: the same model in both arms gives the same members the same fate
    for v in twin["compared"]:
        a, b = (v["arms"][arm]["summary"] for arm in ("challenger", "champion"))
        assert a.model_dump() == b.model_dump()
        assert v["diff"].point == v["diff"].lo == v["diff"].hi == 0.0
    assert twin["decision"] == "NO-PROMOTION"  # no improvement: never promoted


def test_both_arms_are_rolled_out_on_the_same_members_in_every_variant(result, inputs):
    *_, cfg = inputs
    assert [v["variant"] for v in result["compared"]] == list(cfg.variants)
    for v in result["compared"]:
        n = {v["arms"][a]["summary"].n_members for a in ch.ARMS}
        assert n == {v["n_members"]}


def test_the_challenge_exports_valid_metrics1_with_the_paired_claim(result):
    doc = challenge_doc(result, run_id="t", created_at="2026-11-18T00:00:00Z", provenance=PROV)
    validate_metrics1(doc)
    assert doc["simulated"] is True
    diffs = [m for m in doc["metrics"] if m["name"] == "diff.incremental_retained_per_1000_ntd"]
    assert {m["labels"]["variant"] for m in diffs} == {v["variant"] for v in result["compared"]}
    assert all(m["labels"]["a"] == "challenger" and m["labels"]["b"] == "champion" for m in diffs)
    promoted = next(m for m in doc["metrics"] if m["name"] == "promoted")
    assert promoted["value"] is (result["decision"] == "PROMOTION")


def test_holm_is_applied_across_the_variants(result):
    ps = [v["p_value"] for v in result["compared"]]
    got = [row["separated"] for row in result["variants"]]
    expected = [
        bool(s) and not (v["diff"].lo <= 0 <= v["diff"].hi)
        for v, s in zip(result["compared"], holm(ps), strict=True)
    ]
    assert got == expected


def test_a_changed_simulator_is_refused(inputs):
    with pytest.raises(ChallengeError, match="pre-registration"):
        _run(inputs, hash="other")
    with pytest.raises(ChallengeError, match="simulator changed"):
        _run(inputs, champ_hash=None, hash=None)


def test_a_challenger_missing_members_is_refused(inputs):
    scores, *_ = inputs
    with pytest.raises(ChallengeError, match="miss"):
        _run(inputs, scores["challenger"].iloc[100:])


def test_a_planted_violation_always_blocks_promotion(inputs, monkeypatch):
    real = ch._audit
    calls = []

    def planted(res, cohort, policy, cfg):
        counts = dict(real(res, cohort, policy, cfg))
        calls.append(policy)
        if len(calls) % 2 == 0:  # each variant audits the champion, then the challenger
            counts["R2"] = counts.get("R2", 0) + 1  # the challenger offers to a low-risk member
        return counts

    monkeypatch.setattr(ch, "_audit", planted)
    cfg = inputs[-1]
    got = _run(inputs, cfg=cfg.model_copy(update={"variants": ("central",)}))
    assert got["decision"] == "NO-PROMOTION"
    assert any("challenger broke a respect rule" in r for r in got["reasons"])


# the rule itself, on planted comparisons


def _variant(name, lo, hi, p, champ=0, chall=0):
    point = (lo + hi) / 2
    return {
        "variant": name,
        "diff": Interval(point=point, lo=lo, hi=hi),
        "p_value": p,
        "arms": {
            "champion": {"violations": {"R1": champ}},
            "challenger": {"violations": {"R1": chall}},
        },
    }


GOOD = [_variant(v, 0.5, 2.0, 0.001) for v in ("conservative", "central", "optimistic")]
HOLM_SPLIT = [GOOD[0], _variant("central", 0.1, 2.0, 0.03), _variant("optimistic", 0.1, 2.0, 0.03)]


def test_a_challenger_better_in_every_variant_with_no_violation_or_alarm_is_promoted():
    assert decide(GOOD, [])["decision"] == "PROMOTION"


@pytest.mark.parametrize(
    "variants, alarms, why",
    [
        ([*GOOD[:2], _variant("optimistic", -0.1, 2.0, 0.2)], [], "does not improve"),
        (HOLM_SPLIT, [], "does not improve"),  # each 0.03 passes alone, not under Holm
        ([*GOOD[:2], _variant("optimistic", 0.5, 2.0, 0.001, chall=1)], [], "challenger broke"),
        ([*GOOD[:2], _variant("optimistic", 0.5, 2.0, 0.001, champ=1)], [], "champion broke"),
        (GOOD, [{"check": "claim", "message": "central: claim lost"}], "fail alarm (claim)"),
        ([], [], "no variant"),
    ],
)
def test_a_challenger_failing_any_condition_is_not_promoted(variants, alarms, why):
    got = decide(variants, alarms)
    assert got["decision"] == "NO-PROMOTION"
    assert any(why in r for r in got["reasons"]), got["reasons"]


def test_holm_can_withhold_a_variant_a_lone_test_would_pass():
    # 0.03 passes alone at 0.05; under Holm the second-smallest of three must be <= 0.025
    got = decide(HOLM_SPLIT, [])
    assert [r["separated"] for r in got["variants"]] == [True, False, False]


def test_every_challenge_becomes_a_decision_row(tmp_path):
    path = tmp_path / "decisions.md"
    path.write_text(
        "| ID | Date | Decision | Alternatives | Why |\n|---|---|---|---|---|\n", encoding="utf-8"
    )
    for result, name in ((decide(GOOD, []), "c1"), (decide([], []), "c2")):
        append_decision(
            path, decision_row(result, date="2026-11-18", champion="r", challenger=name)
        )
    text = path.read_text(encoding="utf-8")
    assert "| PROMOTION | 2026-11-18 | **Challenge c1" in text
    assert "| NO-PROMOTION | 2026-11-18 | **Challenge c2" in text
    with pytest.raises(ChallengeError, match="already recorded"):
        append_decision(
            path, decision_row(decide(GOOD, []), date="2026-11-18", champion="r", challenger="c1")
        )


CHALLENGES = sorted((ROOT / "results" / "kkbox" / "challenge").glob("*/challenge.metrics.json"))


@pytest.mark.parametrize("path", CHALLENGES, ids=lambda p: p.parent.name)
def test_a_committed_challenge_is_valid_aggregates_and_reproduces_the_champion(path):
    import json

    doc = json.loads(path.read_text(encoding="utf-8"))
    validate_metrics1(doc)
    assert doc["simulated"] is True
    record = json.loads((path.parent / "challenge.json").read_text(encoding="utf-8"))
    summary = json.loads((ROOT / "results" / "kkbox" / "summary.json").read_text("utf-8"))
    assert summary["run_id"] == record["champion"]  # the published run is the champion
    # the champion arm is the published bandit, figure for figure (common random numbers)
    for p in (p for p in summary["policies"] if p["policy"] == "bandit"):
        for name in ("retained_per_1000", "incremental_retained_per_1000"):
            m = next(
                m
                for m in doc["metrics"]
                if m["name"] == name and m["labels"] == {"arm": "champion", "variant": p["variant"]}
            )
            iv = p[name]
            assert (m["value"], m["ci_low"], m["ci_high"]) == (iv["point"], iv["lo"], iv["hi"])
    promoted = next(m for m in doc["metrics"] if m["name"] == "promoted")["value"]
    assert promoted is (record["decision"] == "PROMOTION")
    decisions = (ROOT / "docs" / "decisions.md").read_text(encoding="utf-8")
    assert f"| {record['decision']} | " in decisions and record["challenger"] in decisions


def test_at_least_one_challenge_is_committed():
    assert CHALLENGES


def test_an_outcome_check_that_could_not_run_withholds_promotion():
    got = decide(GOOD, [], ["cost", "disparity"])
    assert got["decision"] == "NO-PROMOTION"
    assert any("not run (cost)" in r for r in got["reasons"])
    assert any("not run (disparity)" in r for r in got["reasons"])


def test_every_refusal_that_needs_no_rollout_happens_before_anything_is_opened(inputs):
    scores, *_ = inputs
    with pytest.raises(ChallengeError, match="simulator changed"):
        ch.precheck(
            scores["champion"],
            scores["challenger"],
            champion_simulator_hash="a",
            simulator_hash="b",
        )
    with pytest.raises(ChallengeError, match="miss"):
        ch.precheck(
            scores["champion"],
            scores["challenger"].iloc[100:],
            champion_simulator_hash="s",
            simulator_hash="s",
        )
    ch.precheck(
        scores["champion"], scores["challenger"], champion_simulator_hash="s", simulator_hash="s"
    )


def test_a_challenge_is_recorded_by_default():
    from respectful_offers.cli import build_parser

    args = build_parser().parse_args(["challenge", "--challenger-seed", "5"])
    assert args.record == "docs/decisions.md"
    assert args.ledger == "docs/measurements/experiments.jsonl"
    assert args.no_record is False


def test_a_recorded_challenge_is_found_before_it_reruns(tmp_path):
    path = tmp_path / "decisions.md"
    row = decision_row(
        decide([], []), date="2026-11-18", champion="r", challenger="r-challenger-s5-e3"
    )
    path.write_text(row + "\n", encoding="utf-8")
    assert ch.already_recorded(path, "r-challenger-s5-e3")
    assert not ch.already_recorded(path, "r-challenger-s6-e3")
