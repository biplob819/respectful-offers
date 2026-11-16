"""A2.8: the real-data results run, as published (REA-01..REA-05).

The real files never reach CI; the run's published outputs are committed under
`results/kkbox/` and the demo cube as `demo/cube.json`, and these tests hold them to the code,
the configs and the pre-registration. `OFFERS_REAL_DATA=1` re-runs the decision review on the
local run and compares it with the committed findings.
"""

import json
import os
import re
import subprocess
import sys

import pytest

import data_scan
from harness_lib import ROOT
from respectful_offers.schemas.summary import RunSummary
from respectful_offers.sim.prereg import sha256

RES = ROOT / "results" / "kkbox"
CUBE = ROOT / "demo" / "cube.json"
VARIANTS = ("conservative", "central", "optimistic")
POLICIES = {"no_offer", "status_quo", "rule_following_baseline", "bandit", "segment_oracle"}
RESPECTFUL = ("bandit", "rule_following_baseline")
MEMBER_ID = re.compile(r"[A-Za-z0-9+/]{43}=")


def summary() -> RunSummary:
    return RunSummary.model_validate_json((RES / "summary.json").read_text(encoding="utf-8"))


def findings(variant: str) -> dict:
    path = RES / "decision_review" / f"findings_{variant}.json"
    return json.loads(path.read_text(encoding="utf-8"))


# --- REA-01 ---------------------------------------------------------------------------


def test_the_published_run_is_real_preregistered_and_complete():
    s = summary()
    assert s.data_source == "kaggle" and s.prereg_status == "preregistered" and s.simulated
    assert tuple(s.variants) == VARIANTS
    for v in VARIANTS:
        assert {p.policy for p in s.policies if p.variant == v} == POLICIES, v
    assert not s.git_sha.endswith("-dirty") and re.fullmatch(r"[0-9a-f]{12}", s.git_sha)


def test_the_run_used_the_committed_configs_and_the_real_registration():
    from respectful_offers.schemas.config import load_run_config

    s = summary()
    assert s.simulator_hash == sha256(ROOT / "configs" / "simulator.yaml")[:16]
    assert s.config_hash == sha256(ROOT / "configs" / "run.yaml")[:16]
    prereg = (ROOT / "docs" / "prereg.md").read_text(encoding="utf-8")
    full = sha256(ROOT / "configs" / "simulator.yaml")
    assert f"`{full}`" in prereg and re.search(r"\| Scope \| real", prereg)
    cfg = load_run_config(ROOT / "configs" / "run.yaml")
    assert {p.n_members for p in s.policies} == {cfg.eval_sample}
    run = json.loads((RES / "run.json").read_text(encoding="utf-8"))
    assert run["run_id"] == s.run_id and run["git_sha"] == s.git_sha


def test_the_audit_is_clean_and_covers_every_rollout():
    audit = json.loads((RES / "audit.json").read_text(encoding="utf-8"))
    assert audit["clean"] is True
    seen = {(r["variant"], r["policy"]) for r in audit["rollouts"]}
    assert {(v, p) for v in VARIANTS for p in POLICIES} <= seen
    for r in audit["rollouts"]:
        if r["respectful"]:
            assert sum(r["violations"].values()) == 0, r


# --- REA-02 ---------------------------------------------------------------------------


def test_the_review_replays_the_run_to_the_last_digit():
    s = summary()
    review = (RES / "decision-review.md").read_text(encoding="utf-8")
    for v in VARIANTS:
        f = findings(v)
        assert f["members"] == 200_000
        for policy, (replay, run) in f["replay_matches_run"].items():
            reported = next(p for p in s.policies if p.variant == v and p.policy == policy)
            assert replay == run == round(reported.retained_per_1000.point, 4), (v, policy)
            assert f"{replay:.3f}" in review, (v, policy)


def test_no_choice_leaves_the_allowed_set_and_r2_holds_for_respectful_policies():
    for v in VARIANTS:
        f = findings(v)
        for policy in (*RESPECTFUL, "status_quo"):
            assert f[policy]["choice_outside_allowed"] == 0, (v, policy)
        for policy in RESPECTFUL:
            assert f[policy]["commercial_to_at_risk_in_period1"] == 0, (v, policy)
            assert f[policy]["r1_shown_again_after_decline"] == 0, (v, policy)
            assert f[policy]["r2_commercial_at_risk_without_earlier_nudge"] == 0, (v, policy)
        assert f["status_quo"]["r2_commercial_at_risk_without_earlier_nudge"] > 0  # D-17


def test_the_reviews_rule_counts_equal_the_auditors():
    audit = json.loads((RES / "audit.json").read_text(encoding="utf-8"))
    for v in VARIANTS:
        f = findings(v)
        for policy in (*RESPECTFUL, "status_quo"):
            row = next(
                r["violations"]
                for r in audit["rollouts"]
                if (r["variant"], r["policy"], r["rollout"]) == (v, policy, "evaluation")
            )
            assert f[policy]["r1_shown_again_after_decline"] == row["R1"], (v, policy)
            assert f[policy]["r2_commercial_at_risk_without_earlier_nudge"] == row["R2"]


def test_every_non_renewal_reason_is_named_in_the_review():
    review = (RES / "decision-review.md").read_text(encoding="utf-8")
    reasons = set()
    for v in VARIANTS:
        for policy in (*RESPECTFUL, "status_quo"):
            reasons |= set(findings(v)[policy]["not_renewed_after_offer_by_segment_and_response"])
    segments = {r.split("/")[0] for r in reasons}
    words = {"lost_cause": "Lost cause", "persuadable": "Persuadable"}
    words |= {"sleeping_dog": "Sleeping dog", "sure_thing": "Sure thing"}
    for seg in segments:
        assert words[seg] in review, seg
    for heading in ("Declined offers", "Accepted a content nudge", "Sleeping dogs"):
        assert heading in review


def test_the_review_and_its_findings_hold_no_member_ids():
    for path in [RES / "decision-review.md", *sorted((RES / "decision_review").iterdir())]:
        text = path.read_text(encoding="utf-8")
        assert not MEMBER_ID.search(text) and "msno" not in text, path


@pytest.mark.skipif(os.environ.get("OFFERS_REAL_DATA") != "1", reason="set OFFERS_REAL_DATA=1")
@pytest.mark.parametrize("variant", VARIANTS)
def test_the_review_reproduces_from_the_local_run(variant):
    run = ROOT / "runs" / summary().run_id
    script = str(ROOT / "scripts" / "review_decisions.py")
    out = subprocess.run(
        [sys.executable, script, "--run", str(run), "--variant", variant],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    )
    assert json.loads(out.stdout) == findings(variant)


# --- REA-03 ---------------------------------------------------------------------------


def test_the_churn_report_is_the_runs_and_beats_its_baseline():
    s = summary()
    report = json.loads((RES / "churn" / "report.json").read_text(encoding="utf-8"))
    assert report == json.loads(s.churn.model_dump_json())
    assert s.churn.auc.lo > s.churn.baseline_auc.hi  # clearly better than two features
    assert 0.6 < s.churn.auc.point < 0.95  # informative, and not suspiciously perfect


def test_no_feature_used_an_event_on_or_after_its_as_of_date():
    stats = json.loads((RES / "features_stats.json").read_text(encoding="utf-8"))
    card = json.loads((RES / "churn" / "model_card.json").read_text(encoding="utf-8"))
    for cohort, as_of in (("feb", 20170201), ("mar", 20170301)):
        assert stats[cohort]["as_of"] == f"{str(as_of)[:4]}-{str(as_of)[4:6]}-01"
        for source in (stats[cohort]["provenance"], card["leakage_checks"][cohort]):
            assert source and all(day < as_of for day in source.values()), (cohort, source)


def test_the_model_uses_no_protected_attribute_and_trains_on_february():
    card = json.loads((RES / "churn" / "model_card.json").read_text(encoding="utf-8"))
    stats = json.loads((RES / "features_stats.json").read_text(encoding="utf-8"))
    assert card["protected_attributes_used"] == []
    assert not {"bd", "gender", "age", "age_band", "city"} & set(card["features"])
    train = card["train"]
    feb = stats["feb"]["members"]
    assert train["train_rows"] + train["calibration_rows"] == feb  # all of February, no March
    assert summary().policies[0].n_members <= stats["mar"]["members"]


# --- REA-04 ---------------------------------------------------------------------------


def test_published_outputs_pass_the_publish_scan():
    files = [p for p in RES.rglob("*") if p.is_file()] + [CUBE]
    assert data_scan.scan(files) == []
    for p in files:
        assert not MEMBER_ID.search(p.read_text(encoding="utf-8")), p


def test_published_outputs_cite_the_challenge_and_say_no_member_data_is_published():
    page = (RES / "report" / "index.html").read_text(encoding="utf-8")
    readme = (RES / "README.md").read_text(encoding="utf-8")
    url = "kaggle.com/competitions/kkbox-churn-prediction-challenge"
    for text in (page, readme):
        assert url in text and "non-commercial research and education" in text
    assert "No member data is published" in page and "no member data" in readme.lower()


# --- REA-05 ---------------------------------------------------------------------------


def test_the_demo_cube_is_built_from_the_real_run():
    from respectful_offers.demo.engine import load_cube

    cube = load_cube(CUBE)
    s = summary()
    ref = cube.reference
    assert cube.data["data_source"] == "kaggle" and ref["run_id"] == s.run_id
    assert ref["simulator_hash"] == s.simulator_hash and ref["prereg_status"] == "preregistered"
    assert abs(cube.data["members"] - s.policies[0].n_members) <= 5 * len(cube.data["cells"])


def test_the_real_demo_agrees_with_the_full_run_everywhere():
    from respectful_offers.demo.engine import agreement, load_cube

    cube = load_cube(CUBE)
    for v in VARIANTS:
        rows = agreement(cube, v)
        assert len(rows) == 12 and all(r["agrees"] for r in rows), [
            (r["policy"], r["metric"]) for r in rows if not r["agrees"]
        ]


def test_the_real_cube_carries_real_plan_prices():
    cube = json.loads(CUBE.read_text(encoding="utf-8"))
    prices = {v for c in cube["cells"] for v, _ in c["price_levels"]}
    assert {99.0, 149.0} <= prices  # the common plans survive disclosure control
    assert sum(len(c["price_levels"]) > 1 for c in cube["cells"]) > len(cube["cells"]) // 3


@pytest.mark.skipif(os.environ.get("OFFERS_REAL_DATA") != "1", reason="set OFFERS_REAL_DATA=1")
def test_the_committed_cube_rebuilds_from_the_local_run_and_every_level_has_k_members():
    """Shares are rounded, so only the members themselves can prove each published price level
    stands for K_LEVEL or more of them."""
    import pandas as pd

    from respectful_offers.demo.cube import (
        K_LEVEL,
        bands,
        dumps,
        make_cube,
        merge_small,
        price_level_counts,
    )
    from respectful_offers.evaluate.pipeline import split
    from respectful_offers.policy.cohort import build_cohort
    from respectful_offers.schemas import load_simulator_config
    from respectful_offers.schemas.config import load_run_config

    s = summary()
    run = json.loads((RES / "run.json").read_text(encoding="utf-8"))
    store = {x["stage"]: x["key"] for x in run["stages"]}
    base = ROOT / ".offers" / "store"
    feats = pd.read_parquet(
        base / store["features"][:2] / store["features"] / "features_mar.parquet"
    )
    scores = pd.read_parquet(base / store["churn"][:2] / store["churn"] / "scores_mar.parquet")
    scores = scores[["msno", "churn_risk"]]
    cfg = load_run_config(ROOT / "configs" / "run.yaml")
    sim = load_simulator_config(ROOT / "configs" / "simulator.yaml")
    cube = make_cube(
        scores,
        feats,
        ROOT / "runs" / s.run_id,
        ROOT / "configs" / "simulator.yaml",
        cfg,
        sim,
        config_path=ROOT / "configs" / "run.yaml",
        data_source="kaggle",
    )
    assert dumps(cube) == CUBE.read_text(encoding="utf-8")
    ev = split(build_cohort(scores, feats, sim, s.variants[0], cfg.seed), cfg)["eval"]
    df = scores[scores.msno.isin(set(ev.msno))].merge(feats, on="msno")
    keys = merge_small(bands(df, sim.trend_bands.cuts[0]))
    for _, g in df.groupby([keys[c] for c in keys.columns]):
        _, counts = price_level_counts(g["price_30d"].to_numpy())
        assert (counts >= K_LEVEL).all()
