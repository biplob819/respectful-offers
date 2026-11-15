"""Churn model, calibration and report (Tech Spec §1 D-9, A2.1).

- Train a gradient-boosted classifier (scikit-learn `HistGradientBoostingClassifier`, D-29)
  on the February cohort's training fold.
- Calibrate with isotonic regression on a separate February fold (never on March, H11).
- Report on the March cohort: AUC and Brier with bootstrap 95% intervals, expected
  calibration error, reliability bins, and a two-feature logistic baseline for context.
- Score the March cohort with calibrated churn risk.

Model features are a fixed allow-list taken from the features table; protected attributes
never reach this module (the features table does not hold them).
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

from respectful_offers.schemas.rows import PROTECTED_ATTRIBUTES
from respectful_offers.schemas.summary import ChurnReport, Interval
from respectful_offers.threads import small_fit_threads

MODEL_FEATURES: tuple[str, ...] = (
    "tenure_days",
    "auto_renew",
    "cancels_90d",
    "listening_trend_30d",
    "price_30d",
    "plan_days",
)
BASELINE_FEATURES: tuple[str, ...] = ("tenure_days", "auto_renew")
CALIBRATION_SHARE = 0.2
SHRINKAGE = 20  # members of prior weight pulling each isotonic block toward the base rate
RISK_FLOOR = 1e-3  # calibrated risk stays inside [0.001, 0.999]
N_BINS = 10
N_BOOT = 1_000
HGB_PARAMS: dict[str, Any] = {
    "learning_rate": 0.08,
    "max_iter": 150,
    "max_leaf_nodes": 31,
    "min_samples_leaf": 50,
    "l2_regularization": 1.0,
    "early_stopping": False,  # no hidden validation split: deterministic and reproducible
}

assert not set(MODEL_FEATURES) & PROTECTED_ATTRIBUTES


def calibration_fold(msno: pd.Series, salt: str = "churn-calibration") -> np.ndarray:
    """True for the ~20% of February members held out for calibration (salted hash)."""
    h = np.array(
        [
            int.from_bytes(hashlib.sha256((salt + str(m)).encode("utf-8")).digest()[:8], "big")
            for m in msno
        ],
        dtype=object,
    )
    return np.array([v % 100 < int(CALIBRATION_SHARE * 100) for v in h], dtype=bool)


def _x(df: pd.DataFrame, cols: tuple[str, ...]) -> np.ndarray:
    return df[list(cols)].astype(float).to_numpy()


@dataclass
class ChurnModel:
    model: HistGradientBoostingClassifier
    calibrator: IsotonicRegression
    features: tuple[str, ...]

    def raw_scores(self, df: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(_x(df, self.features))[:, 1]

    def risk(self, df: pd.DataFrame) -> np.ndarray:
        r = np.asarray(self.calibrator.predict(self.raw_scores(df)), dtype=float)
        return np.clip(r, RISK_FLOOR, 1 - RISK_FLOOR)


def train(feb: pd.DataFrame, seed: int) -> tuple[ChurnModel, dict[str, Any]]:
    if feb["churn_label"].nunique() < 2:
        raise ValueError("the February cohort needs both churners and non-churners")
    cal = calibration_fold(feb["msno"])
    fit, hold = feb[~cal], feb[cal]
    if hold["churn_label"].nunique() < 2 or fit["churn_label"].nunique() < 2:
        raise ValueError("both February folds need churners and non-churners")
    model = HistGradientBoostingClassifier(random_state=seed, **HGB_PARAMS)
    with small_fit_threads(len(fit)):
        model.fit(_x(fit, MODEL_FEATURES), fit["churn_label"].astype(int).to_numpy())
    raw = model.predict_proba(_x(hold, MODEL_FEATURES))[:, 1]
    y = hold["churn_label"].astype(int).to_numpy()
    iso = shrunk_isotonic(raw, y)
    info = {
        "train_rows": len(fit),
        "calibration_rows": len(hold),
        "params": HGB_PARAMS,
        "seed": seed,
        "calibration": {
            "shrinkage_members": SHRINKAGE,
            "risk_bounds": [RISK_FLOOR, 1 - RISK_FLOOR],
        },
    }
    return ChurnModel(model, iso, MODEL_FEATURES), info


def shrunk_isotonic(raw: np.ndarray, y: np.ndarray) -> IsotonicRegression:
    """Isotonic calibration whose blocks are shrunk toward the base rate (A2.1 verifier).

    A plain isotonic fit gave a block of 81 members with no churners a risk of exactly 0, and
    a block of 2 members a risk of 0.5; risk 0 makes a member's simulated base renewal 1, so
    no policy can ever affect them. Each block's rate becomes (churners + k·p̄) / (n + k), with
    p̄ the fold's churn rate and k = SHRINKAGE members of prior weight, monotonicity is
    re-imposed, and the result is bounded inside (0, 1)."""
    first = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(raw, y)
    block = first.predict(raw)
    base = float(y.mean())
    target = np.empty_like(block, dtype=float)
    for value in np.unique(block):
        m = block == value
        target[m] = (y[m].sum() + SHRINKAGE * base) / (m.sum() + SHRINKAGE)
    bounded = IsotonicRegression(y_min=RISK_FLOOR, y_max=1 - RISK_FLOOR, out_of_bounds="clip")
    return bounded.fit(raw, target)


def ece(y: np.ndarray, p: np.ndarray, bins: int = N_BINS) -> float:
    """Equal-width bins [k/bins, (k+1)/bins); p = 1 falls in the last bin."""
    idx = np.clip(np.floor(np.asarray(p) * bins + 1e-12).astype(int), 0, bins - 1)
    total = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            total += m.mean() * abs(float(y[m].mean()) - float(p[m].mean()))
    return float(total)


def reliability(y: np.ndarray, p: np.ndarray, bins: int = N_BINS) -> list[tuple[float, float, int]]:
    """Quantile bins: (mean predicted, observed rate, n), sorted by prediction."""
    order = np.argsort(p, kind="mergesort")
    out = []
    for chunk in np.array_split(order, bins):
        if len(chunk):
            out.append(
                (
                    round(float(p[chunk].mean()), 6),
                    round(float(y[chunk].mean()), 6),
                    len(chunk),
                )
            )
    return out


def _interval(values: np.ndarray, point: float) -> Interval:
    """Raw percentile interval; never clamped to contain the point (a clamp would hide a
    broken bootstrap)."""
    lo, hi = np.percentile(values, [2.5, 97.5])
    return Interval(point=round(point, 6), lo=round(float(lo), 6), hi=round(float(hi), 6))


def fast_auc(y: np.ndarray, s: np.ndarray) -> float:
    """ROC AUC by average ranks (Mann-Whitney U), exact under ties."""
    from scipy.stats import rankdata

    n1 = int(y.sum())
    n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return float("nan")
    ranks = rankdata(s)
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def bootstrap(y: np.ndarray, scores: dict[str, np.ndarray], seed: int, n_boot: int = N_BOOT):
    """Member-level bootstrap of AUC and Brier for each named score, on shared resamples."""
    rng = np.random.default_rng(seed)
    n = len(y)
    out: dict[str, dict[str, list[float]]] = {k: {"auc": [], "brier": []} for k in scores}
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        yy = y[idx]
        if yy.min() == yy.max():
            continue
        for k, s in scores.items():
            ss = s[idx]
            out[k]["auc"].append(fast_auc(yy, ss))
            out[k]["brier"].append(float(np.mean((np.clip(ss, 0, 1) - yy) ** 2)))
    return out


def report(model: ChurnModel, feb: pd.DataFrame, mar: pd.DataFrame, seed: int) -> ChurnReport:
    if mar["churn_label"].nunique() < 2:
        raise ValueError("the March cohort needs both churners and non-churners to report on")
    y = mar["churn_label"].astype(int).to_numpy()
    risk = model.risk(mar)
    base = LogisticRegression(max_iter=1000).fit(
        _x(feb, BASELINE_FEATURES), feb["churn_label"].astype(int)
    )
    base_p = base.predict_proba(_x(mar, BASELINE_FEATURES))[:, 1]
    boots = bootstrap(y, {"model": risk, "baseline": base_p}, seed)
    auc = roc_auc_score(y, risk)
    return ChurnReport(
        auc=_interval(np.array(boots["model"]["auc"]), auc),
        brier=_interval(np.array(boots["model"]["brier"]), brier_score_loss(y, risk)),
        ece=round(ece(y, risk), 6),
        reliability=tuple(reliability(y, risk)),
        baseline_auc=_interval(np.array(boots["baseline"]["auc"]), roc_auc_score(y, base_p)),
        features=model.features,
    )


def importances(model: ChurnModel, df: pd.DataFrame, seed: int) -> dict[str, float]:
    """Permutation importance (drop in AUC) on the given frame; the model card uses it."""
    from sklearn.inspection import permutation_importance

    r = permutation_importance(
        model.model, _x(df, model.features), df["churn_label"].astype(int).to_numpy(),
        scoring="roc_auc", n_repeats=5, random_state=seed,
    )  # fmt: skip
    return {
        f: round(float(v), 6) for f, v in zip(model.features, r["importances_mean"], strict=True)
    }


def finite(x: float) -> bool:
    return math.isfinite(x)
