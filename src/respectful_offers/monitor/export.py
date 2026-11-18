"""Drift and calibration inputs for EvalKit's drift monitor (E4.3 MON-01, EvalKit LED-04).

The aggregates form of EvalKit's frozen drift reference (EvalKit docs/drift.md, "The frozen
reference"): a metrics-1 file per period holding

- `drift.feature_share` (rate) {feature, bin} with `n`: each model feature's share of members
  per bin, on bins fixed by the baseline cohort (deciles, repeated edges merged, open outer
  bins, no bin under `MIN_MEMBERS` members);
- `churn.brier` (with a bootstrap interval) and `churn.ece`;
- `churn.reliability.predicted` / `.observed` (rate) {bin} with `n`, on ten **equal-width**
  bins (EvalKit OWNER D-73), so bins align across periods. Empty bins are left out.

The baseline is the February cohort and its calibration fold; the period is March, scored out
of time. The isotonic calibrator was fitted on that fold, so the February calibration figures
are in-sample for the calibrator and flatter it: March calibration drift is measured against a
deliberately optimistic reference, and the report says so. Member features, scores and churn
labels are real KKBox data; nothing here is simulated. No member id leaves this module.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from respectful_offers.churn.model import MODEL_FEATURES, ece

MIN_MEMBERS = 30  # no bin with fewer members is published (Tech Spec §9, DATA_CARD)
N_DECILES = 10
N_CAL_BINS = 10
N_BOOT = 1_000
CI_BRIER = "member bootstrap percentile 95% (1,000 resamples)"


class MonitorError(ValueError):
    """The inputs cannot be exported without breaking a monitoring rule."""


def feature_bins(baseline: pd.DataFrame, features: tuple[str, ...] = MODEL_FEATURES) -> dict:
    """Inner bin edges per feature from the baseline's deciles; small bins merged."""
    out: dict[str, list[float]] = {}
    for f in features:
        x = baseline[f].to_numpy(dtype=float)
        if not np.isfinite(x).all():
            raise MonitorError(f"{f}: non-finite values in the baseline")
        qs = np.quantile(x, np.linspace(0, 1, N_DECILES + 1)[1:-1])
        edges = sorted({float(q) for q in qs})
        # bins are [e_i, e_{i+1}), open at both ends; drop edges until no bin is small
        while True:
            counts = _counts(x, edges)
            small = [i for i, c in enumerate(counts) if c < MIN_MEMBERS]
            if not small or not edges:
                break
            i = small[0]
            edges.pop(min(i, len(edges) - 1))  # merge the small bin into a neighbour
        out[f] = edges
    return out


def _counts(x: np.ndarray, edges: list[float]) -> list[int]:
    idx = np.searchsorted(np.asarray(edges), x, side="right")
    return np.bincount(idx, minlength=len(edges) + 1).tolist()


def _shares(df: pd.DataFrame, bins: dict[str, list[float]], where: str) -> list[dict[str, Any]]:
    rows = []
    n = len(df)
    for f, edges in bins.items():
        counts = _counts(df[f].to_numpy(dtype=float), edges)
        for b, c in enumerate(counts):
            if 0 < c < MIN_MEMBERS:
                raise MonitorError(
                    f"{where}: {f} bin {b} holds {c} members, under {MIN_MEMBERS}: not published"
                )
            rows.append(
                {
                    "name": "drift.feature_share",
                    "unit": "rate",
                    "value": round(c / n, 9),
                    "n": n,
                    "labels": {"feature": f, "bin": b},
                }
            )
    return rows


def _calibration(y: np.ndarray, p: np.ndarray, seed: int, where: str) -> list[dict[str, Any]]:
    brier = float(np.mean((p - y) ** 2))
    rng = np.random.default_rng(seed)
    draws = np.empty(N_BOOT)
    sq = (p - y) ** 2
    n = len(y)
    for i in range(N_BOOT):
        draws[i] = sq[rng.integers(0, n, n)].mean()
    lo, hi = (float(v) for v in np.percentile(draws, [2.5, 97.5]))
    rows: list[dict[str, Any]] = [
        {
            "name": "churn.brier",
            "unit": "ratio",
            "value": round(brier, 9),
            "n": n,
            "ci_low": round(lo, 9),  # never clamped to hold the point: a miss is an error
            "ci_high": round(hi, 9),
            "ci_method": CI_BRIER,
        },
        {"name": "churn.ece", "unit": "ratio", "value": round(ece(y, p), 9), "n": n},
    ]
    if not rows[0]["ci_low"] <= rows[0]["value"] <= rows[0]["ci_high"]:
        raise MonitorError(f"{where}: the Brier score lies outside its own interval")
    idx = np.clip(np.floor(p * N_CAL_BINS + 1e-12).astype(int), 0, N_CAL_BINS - 1)
    for b in range(N_CAL_BINS):
        m = idx == b
        k = int(m.sum())
        if k == 0:
            continue  # an empty bin is left out on every side
        if k < MIN_MEMBERS:
            raise MonitorError(f"{where}: reliability bin {b} holds {k} members: not published")
        lab = {"bin": b}
        rows.append(
            {
                "name": "churn.reliability.predicted",
                "unit": "rate",
                "value": round(float(p[m].mean()), 9),
                "n": k,
                "labels": lab,
            }
        )
        rows.append(
            {
                "name": "churn.reliability.observed",
                "unit": "rate",
                "value": round(float(y[m].mean()), 9),
                "n": k,
                "labels": dict(lab),
            }
        )
    return rows


def period_doc(
    *,
    run_id: str,
    created_at: str,
    provenance: dict[str, Any],
    members: pd.DataFrame,
    bins: dict[str, list[float]],
    y: np.ndarray,
    p: np.ndarray,
    seed: int,
) -> dict[str, Any]:
    """One period's metrics-1 drift input. `members` holds the model features only."""
    if len(y) != len(p) or not len(y):
        raise MonitorError(f"{run_id}: labels and scores must be non-empty and the same length")
    if not (np.isfinite(p).all() and ((p >= 0) & (p <= 1)).all()):
        raise MonitorError(f"{run_id}: scores must be probabilities")
    metrics = _shares(members, bins, run_id) + _calibration(y.astype(float), p, seed, run_id)
    for m in metrics:
        if isinstance(m["value"], float) and not math.isfinite(m["value"]):
            raise MonitorError(f"{run_id}: {m['name']} is not finite")
    return {
        "schema_version": "metrics-1",
        "project": "respectful-offers",
        "run_id": run_id,
        "created_at": created_at,
        "simulated": False,  # real member features, scores and churn labels
        "provenance": provenance,
        "metrics": metrics,
    }


def bins_doc(bins: dict[str, list[float]], baseline: str) -> dict[str, Any]:
    """The bin edges behind every `drift.feature_share` row, published beside them."""
    return {
        "schema_version": "drift-bins-1",
        "baseline": baseline,
        "rule": (
            f"deciles of the baseline cohort, repeated edges merged, bins [e_i, e_i+1) open at "
            f"both ends, no bin under {MIN_MEMBERS} members; bin k lies above edge k-1"
        ),
        "features": {f: edges for f, edges in bins.items()},
        "calibration_bins": f"{N_CAL_BINS} equal-width bins of predicted risk, [k/10, (k+1)/10)",
    }
