import json

import numpy as np
import pandas as pd
import pytest

from respectful_offers.churn.model import (
    MODEL_FEATURES,
    calibration_fold,
    ece,
    reliability,
    report,
    train,
)
from respectful_offers.churn.stage import ChurnStage, assign_bands
from respectful_offers.data.synthetic import SyntheticSpec, generate
from respectful_offers.features.build import build_cohort
from respectful_offers.runtime import RunContext, import_artifact, run_stage
from respectful_offers.schemas import load_simulator_config
from respectful_offers.schemas.rows import PROTECTED_ATTRIBUTES
from tests.schemas.conftest import FIX


@pytest.fixture(scope="module")
def cohorts(tmp_path_factory):
    raw = tmp_path_factory.mktemp("raw")
    generate(raw, SyntheticSpec(n_members=4000, seed=11))
    return build_cohort(raw, "feb").features, build_cohort(raw, "mar").features


@pytest.fixture(scope="module")
def trained(cohorts):
    return train(cohorts[0], seed=1)[0]


def test_fast_auc_matches_scikit_learn_including_ties():
    from sklearn.metrics import roc_auc_score

    from respectful_offers.churn.model import fast_auc

    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 500)
    s = np.round(rng.uniform(size=500), 1)  # many ties
    assert fast_auc(y, s) == pytest.approx(roc_auc_score(y, s))


def test_model_uses_exactly_the_allow_list_and_is_deterministic(cohorts):
    feb, mar = cohorts
    m1, _ = train(feb, seed=1)
    m2, _ = train(feb, seed=1)
    assert m1.features == MODEL_FEATURES and not set(MODEL_FEATURES) & PROTECTED_ATTRIBUTES
    assert m1.risk(mar).tobytes() == m2.risk(mar).tobytes()


def test_one_class_cohorts_are_refused(cohorts, trained):
    feb, mar = cohorts
    with pytest.raises(ValueError, match="churners"):
        train(feb.assign(churn_label=False), seed=1)
    with pytest.raises(ValueError, match="March"):
        report(trained, feb, mar.assign(churn_label=False), seed=1)


def test_calibration_fold_is_stable_disjoint_and_about_a_fifth(cohorts):
    feb, _ = cohorts
    a, b = calibration_fold(feb["msno"]), calibration_fold(feb["msno"])
    assert (a == b).all() and 0.15 < a.mean() < 0.25
    _, info = train(feb, seed=1)
    assert info["train_rows"] + info["calibration_rows"] == len(feb)


def test_march_labels_never_touch_the_scores(cohorts, trained):
    _feb, mar = cohorts
    m = trained
    shuffled = mar.assign(
        churn_label=np.random.default_rng(0).permutation(mar["churn_label"].to_numpy())
    )
    assert m.risk(mar).tobytes() == m.risk(shuffled).tobytes()


def test_calibrator_is_monotone_and_bounded(cohorts, trained):
    _feb, mar = cohorts
    m = trained
    raw = np.linspace(0, 1, 101)
    cal = m.calibrator.predict(raw)
    assert (np.diff(cal) >= -1e-12).all() and cal.min() >= 0 and cal.max() <= 1
    y = mar["churn_label"].astype(int).to_numpy()
    assert ece(y, m.risk(mar)) <= ece(y, m.raw_scores(mar)) + 0.01


def test_report_intervals_contain_points_and_bins_cover_everyone(cohorts, trained):
    feb, mar = cohorts
    m = trained
    r = report(m, feb, mar, seed=1)
    for iv in (r.auc, r.brier, r.baseline_auc):
        assert iv.lo <= iv.point <= iv.hi
    assert sum(b[2] for b in r.reliability) == len(mar)
    assert r.auc.point > 0.6 and r.features == MODEL_FEATURES


def test_ece_and_reliability_on_a_hand_example():
    y = np.array([0, 0, 1, 1, 1, 0, 0, 0, 0, 1])
    p = np.array([0.05, 0.05, 0.95, 0.95, 0.55, 0.55, 0.15, 0.15, 0.15, 0.15])
    # bins of width 0.1: [0.0,0.1): mean 0.05 obs 0 (n 2); [0.1,0.2): 0.15 vs 0.25 (n 4);
    # [0.5,0.6): 0.55 vs 0.5 (n 2); [0.9,1.0]: 0.95 vs 1 (n 2)
    expected = 0.2 * 0.05 + 0.4 * 0.10 + 0.2 * 0.05 + 0.2 * 0.05
    assert ece(y, p) == pytest.approx(expected)
    bins = reliability(y, p, bins=5)
    assert [b[2] for b in bins] == [2, 2, 2, 2, 2]


def test_bands_respect_the_cut_points_exactly():
    sim = load_simulator_config(FIX / "simulator.yaml")  # cuts 0.2, 0.5; trend -0.25
    scores = pd.DataFrame({"msno": list("abcde"), "churn_risk": [0.19, 0.2, 0.49, 0.5, 0.9]})
    feats = pd.DataFrame(
        {"msno": list("abcde"), "listening_trend_30d": [-0.3, -0.25, 0.0, -0.26, 1.0]}
    )
    b = assign_bands(scores, feats, sim)
    assert b["risk_band"].tolist() == ["low", "medium", "medium", "high", "high"]
    assert b["trend_band"].tolist() == ["declining", "stable", "stable", "declining", "stable"]
    with pytest.raises(ValueError, match="no features"):
        assign_bands(scores, feats.iloc[:3], sim)


def test_stage_writes_scores_report_and_card_without_pickles(tmp_path, cohorts):
    feb, mar = cohorts
    src = tmp_path / "feat"
    src.mkdir()
    feb.to_parquet(src / "features_feb.parquet", index=False)
    mar.to_parquet(src / "features_mar.parquet", index=False)
    stats = {
        c: {"provenance": {"auto_renew": 20170131}, "early_renewal_rows_dropped": 0}
        for c in ("feb", "mar")
    }
    (src / "stats.json").write_text(json.dumps(stats), encoding="utf-8")
    ctx = RunContext(tmp_path, "r", "cfg", seed=5)
    feats = import_artifact(ctx, "features", {p.name: p for p in src.iterdir()})
    ref = run_stage(ChurnStage(), {"features": feats}, ctx)
    names = {p.name for p in ref.path.iterdir()}
    assert {"scores_mar.parquet", "report.json", "calibration.json", "model_card.json"} <= names
    assert not any(n.endswith((".pkl", ".pickle", ".joblib")) for n in names)
    s = pd.read_parquet(ref.path / "scores_mar.parquet")
    assert len(s) == len(mar) and s["churn_risk"].between(0, 1).all()
    card = json.loads((ref.path / "model_card.json").read_text(encoding="utf-8"))
    assert card["features"] == list(MODEL_FEATURES) and card["protected_attributes_used"] == []
    assert set(card["permutation_importance_auc_drop"]) == set(MODEL_FEATURES)
    assert card["leakage_checks"]["feb"] == {"auto_renew": 20170131}


def test_calibrated_risk_is_strictly_inside_zero_and_one(cohorts, trained):
    _feb, mar = cohorts
    r = trained.risk(mar)
    assert r.min() > 0 and r.max() < 1
    assert (r > 0.001).mean() == 1.0  # the plain isotonic fit gave 13% of members exactly 0


def test_small_calibration_blocks_are_shrunk_toward_the_base_rate():
    from respectful_offers.churn.model import SHRINKAGE, shrunk_isotonic

    raw = np.r_[np.linspace(0, 0.5, 200), [0.9, 0.95]]
    y = np.r_[np.zeros(200, int), [1, 0]]  # a 2-member top block with one churner
    iso = shrunk_isotonic(raw, y)
    top = float(iso.predict([0.95])[0])
    base = y.mean()
    assert top == pytest.approx((1 + SHRINKAGE * base) / (2 + SHRINKAGE), rel=1e-6)
    assert iso.predict([0.0])[0] > 0


def test_intervals_are_raw_percentiles_never_clamped():
    from respectful_offers.churn.model import _interval

    iv = _interval(np.array([0.70, 0.71, 0.72]), point=0.9)
    assert iv.point == 0.9 and iv.hi < 0.9  # a point outside its interval shows, not hides


def test_model_and_baseline_share_bootstrap_resamples():
    from respectful_offers.churn.model import bootstrap

    rng = np.random.default_rng(1)
    y = rng.integers(0, 2, 300)
    s = rng.uniform(size=300)
    out = bootstrap(y, {"model": s, "baseline": s.copy()}, seed=4, n_boot=50)
    assert out["model"]["auc"] == out["baseline"]["auc"]


def test_ece_bins_are_left_closed():
    y = np.array([0, 1])
    p = np.array([0.3, 0.3])  # both in [0.3, 0.4)
    assert ece(y, p) == pytest.approx(abs(0.5 - 0.3))


def test_importances_never_read_march_labels(tmp_path, cohorts):
    feb, mar = cohorts

    def card_for(march):
        src = tmp_path / f"f{len(list(tmp_path.iterdir()))}"
        src.mkdir()
        feb.to_parquet(src / "features_feb.parquet", index=False)
        march.to_parquet(src / "features_mar.parquet", index=False)
        stats = {c: {"provenance": {}, "early_renewal_rows_dropped": 0} for c in ("feb", "mar")}
        (src / "stats.json").write_text(json.dumps(stats), encoding="utf-8")
        ctx = RunContext(tmp_path / f"root{src.name}", "r", "cfg", seed=5)
        feats = import_artifact(ctx, "features", {p.name: p for p in src.iterdir()})
        ref = run_stage(ChurnStage(), {"features": feats}, ctx)
        return json.loads((ref.path / "model_card.json").read_text(encoding="utf-8"))

    a = card_for(mar)
    shuffled = mar.assign(
        churn_label=np.random.default_rng(3).permutation(mar["churn_label"].to_numpy())
    )
    b = card_for(shuffled)
    assert a["permutation_importance_auc_drop"] == b["permutation_importance_auc_drop"]
    assert a["train"]["calibration"]["shrinkage_members"] == 20
