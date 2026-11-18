"""E4.3 MON-01 export side: drift and calibration inputs for EvalKit's LED-04 monitor."""

import json
import math
import os
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from harness_lib import ROOT
from respectful_offers.churn.model import MODEL_FEATURES
from respectful_offers.metrics1 import validate_metrics1
from respectful_offers.monitor.export import (
    MIN_MEMBERS,
    MonitorError,
    feature_bins,
    period_doc,
)

MON = ROOT / "results" / "kkbox" / "monitor"
FILES = ("reference-2017-02.metrics.json", "period-2017-03.metrics.json")
PROV = {"code_version": "abc", "snapshot": None, "config_hash": None, "evalkit": None}


def _members(n: int, seed: int, shift: str | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(
        {
            "tenure_days": rng.integers(30, 3000, n).astype(float),
            "auto_renew": rng.integers(0, 2, n).astype(float),
            "cancels_90d": rng.choice([0, 0, 0, 1, 2], n).astype(float),
            "listening_trend_30d": rng.normal(0, 1, n),
            "price_30d": rng.choice([99, 129, 149, 180], n).astype(float),
            "plan_days": rng.choice([30, 30, 30, 90, 180], n).astype(float),
        }
    )
    if shift:
        df[shift] = df[shift] + 3 * df[shift].std()
    return df


def _doc(df: pd.DataFrame, bins, seed: int = 1) -> dict:
    rng = np.random.default_rng(seed)
    p = rng.uniform(0, 0.85, len(df))
    y = (rng.uniform(0, 1, len(df)) < p).astype(int)
    return period_doc(
        run_id="t",
        created_at="2026-11-18T00:00:00Z",
        provenance=PROV,
        members=df,
        bins=bins,
        y=y,
        p=p,
        seed=seed,
    )


def _shares(doc: dict) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for m in doc["metrics"]:
        if m["name"] == "drift.feature_share":
            out.setdefault(m["labels"]["feature"], []).append(m["value"])
    return out


def test_a_period_file_is_valid_metrics1_with_every_feature_and_calibration():
    base = _members(5_000, 1)
    doc = _doc(base, feature_bins(base))
    validate_metrics1(doc)
    shares = _shares(doc)
    assert set(shares) == set(MODEL_FEATURES)
    assert all(math.isclose(sum(v), 1.0, abs_tol=1e-6) for v in shares.values())
    names = {m["name"] for m in doc["metrics"]}
    assert {
        "churn.brier",
        "churn.ece",
        "churn.reliability.predicted",
        "churn.reliability.observed",
    } <= names
    brier = next(m for m in doc["metrics"] if m["name"] == "churn.brier")
    assert brier["ci_low"] <= brier["value"] <= brier["ci_high"] and brier["ci_method"]
    assert doc["simulated"] is False  # real features, scores and labels


def test_reliability_bins_are_equal_width_and_paired():
    base = _members(5_000, 2)
    doc = _doc(base, feature_bins(base))
    pred = {
        m["labels"]["bin"]: m for m in doc["metrics"] if m["name"] == "churn.reliability.predicted"
    }
    obs = {
        m["labels"]["bin"]: m for m in doc["metrics"] if m["name"] == "churn.reliability.observed"
    }
    assert set(pred) == set(obs) and set(pred) <= set(range(10))
    for b, m in pred.items():
        assert b / 10 <= m["value"] < (b + 1) / 10  # mean prediction inside its own bin
        assert m["n"] == obs[b]["n"] >= MIN_MEMBERS
    assert 9 not in pred  # scores stop at 0.85 here: an empty bin is left out, never shown as 0


def test_baseline_bins_never_hold_fewer_than_thirty_members():
    base = _members(400, 3)  # deciles of 40: merges are needed for the skewed features
    bins = feature_bins(base)
    for f, edges in bins.items():
        idx = np.searchsorted(np.asarray(edges), base[f].to_numpy(), side="right")
        counts = np.bincount(idx, minlength=len(edges) + 1)
        assert (counts >= MIN_MEMBERS).all(), (f, counts)


def test_a_period_bin_under_thirty_members_is_refused_not_published():
    base = _members(5_000, 4)
    bins = feature_bins(base)
    tiny = base.copy()
    tiny.loc[: MIN_MEMBERS - 2, "tenure_days"] = 1e9  # 29 members land beyond every edge
    tiny.loc[MIN_MEMBERS - 1 :, "tenure_days"] = base["tenure_days"].median()
    with pytest.raises(MonitorError, match="under 30"):
        _doc(tiny, bins)


def test_a_planted_shift_moves_only_that_features_shares():
    base = _members(20_000, 5)
    bins = feature_bins(base)
    ref, new = _shares(_doc(base, bins)), _shares(_doc(_members(20_000, 6, "price_30d"), bins))

    def psi(p, q):  # a test-side yardstick only: the monitor computes PSI in EvalKit
        p, q = np.maximum(np.asarray(p), 1e-4), np.maximum(np.asarray(q), 1e-4)
        return float(np.sum((q - p) * np.log(q / p)))

    moved = {f for f in MODEL_FEATURES if psi(ref[f], new[f]) > 0.25}
    assert moved == {"price_30d"}


def test_no_member_id_or_row_can_appear():
    base = _members(2_000, 7)
    base.insert(0, "msno", [f"id{i}" for i in range(len(base))])
    doc = _doc(base[list(MODEL_FEATURES)], feature_bins(base[list(MODEL_FEATURES)]))
    text = json.dumps(doc)
    assert "msno" not in text and "id1" not in text


def test_bad_scores_are_refused():
    base = _members(1_000, 8)
    bins = feature_bins(base)
    with pytest.raises(MonitorError, match="probabilities"):
        period_doc(
            run_id="t",
            created_at="2026-11-18T00:00:00Z",
            provenance=PROV,
            members=base,
            bins=bins,
            y=np.zeros(1_000),
            p=np.full(1_000, 1.5),
            seed=1,
        )


@pytest.mark.parametrize("name", FILES)
def test_the_committed_real_exports_are_valid_and_aggregates_only(name):
    doc = json.loads((MON / name).read_text(encoding="utf-8"))
    validate_metrics1(doc)
    assert doc["simulated"] is False and doc["project"] == "respectful-offers"
    for m in doc["metrics"]:
        assert "n" in m and m["n"] >= MIN_MEMBERS
    shares = _shares(doc)
    assert set(shares) == set(MODEL_FEATURES)
    assert all(math.isclose(sum(v), 1.0, abs_tol=1e-6) for v in shares.values())


def test_both_periods_share_the_published_bin_edges():
    bins = json.loads((MON / "bins.json").read_text(encoding="utf-8"))
    ref, new = (json.loads((MON / f).read_text(encoding="utf-8")) for f in FILES)
    for f, edges in bins["features"].items():
        n_bins = len(edges) + 1
        for doc in (ref, new):
            got = sorted(
                m["labels"]["bin"]
                for m in doc["metrics"]
                if m["name"] == "drift.feature_share" and m["labels"]["feature"] == f
            )
            assert got == list(range(n_bins)), f


@pytest.mark.skipif(
    os.environ.get("OFFERS_REAL_DATA") != "1",
    reason="needs the real KKBox files and the real-v2 run (OFFERS_REAL_DATA=1)",
)
def test_the_committed_exports_reproduce_from_the_real_run(tmp_path):
    out = subprocess.run(
        [
            sys.executable,
            "-m",
            "respectful_offers.cli",
            "monitor",
            "export",
            "--out-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert out.returncode == 0, out.stdout + out.stderr
    for name in (*FILES, "bins.json"):
        assert (tmp_path / name).read_text(encoding="utf-8") == (MON / name).read_text(
            encoding="utf-8"
        ), name
