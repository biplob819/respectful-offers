"""The churn stage (A2.1): train on February, calibrate on a February fold, report on March,
and score the March cohort. Outputs `scores_mar.parquet` (msno, churn_risk, raw_score),
`report.json` (a `ChurnReport`), `calibration.json` (the isotonic map) and `model_card.json`.

No fitted model object is stored: everything downstream needs only the March scores, and a
pickled model would be a code-execution risk for anyone who loads a shared store.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd

from respectful_offers.churn.model import (
    BASELINE_FEATURES,
    HGB_PARAMS,
    MODEL_FEATURES,
    calibration_fold,
    importances,
    report,
    train,
)
from respectful_offers.runtime.stage import RunContext, Stage
from respectful_offers.schemas.rows import PROTECTED_ATTRIBUTES
from respectful_offers.schemas.simulator import SimulatorConfig


class ChurnStage(Stage):
    name = "churn"
    code_version = "6"

    def run(self, inputs: Mapping[str, Path], out: Path, ctx: RunContext) -> None:
        feats = inputs["features"]
        feb = pd.read_parquet(feats / "features_feb.parquet")
        mar = pd.read_parquet(feats / "features_mar.parquet")
        stats = json.loads((feats / "stats.json").read_text(encoding="utf-8"))
        model, info = train(feb, seed=ctx.seed)
        rep = report(model, feb, mar, seed=ctx.seed)
        scores = pd.DataFrame(
            {
                "msno": mar["msno"].astype(str),
                "churn_risk": model.risk(mar),
                "raw_score": model.raw_scores(mar),
            }
        )
        scores.to_parquet(out / "scores_mar.parquet", index=False)
        (out / "report.json").write_text(rep.model_dump_json(indent=2) + "\n", encoding="utf-8")
        cal = {
            "x": [round(float(v), 9) for v in model.calibrator.X_thresholds_],
            "y": [round(float(v), 9) for v in model.calibrator.y_thresholds_],
        }
        (out / "calibration.json").write_text(json.dumps(cal) + "\n", encoding="utf-8")
        card = {
            "model": "scikit-learn HistGradientBoostingClassifier (D-29)",
            "params": HGB_PARAMS,
            "seed": ctx.seed,
            "features": list(MODEL_FEATURES),
            "baseline_features": list(BASELINE_FEATURES),
            "protected_attributes_used": sorted(set(MODEL_FEATURES) & PROTECTED_ATTRIBUTES),
            # on the February calibration fold: March labels only ever report
            "permutation_importance_auc_drop": importances(
                model, feb[calibration_fold(feb["msno"])], ctx.seed
            ),
            "train": info,
            "leakage_checks": {c: stats[c]["provenance"] for c in ("feb", "mar")},
            "early_renewal_rows_dropped": {
                c: stats[c].get("early_renewal_rows_dropped") for c in ("feb", "mar")
            },
        }
        (out / "model_card.json").write_text(
            json.dumps(card, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


def assign_bands(
    scores: pd.DataFrame, features: pd.DataFrame, sim: SimulatorConfig
) -> pd.DataFrame:
    """Risk band from calibrated risk and trend band from the listening trend, using the
    simulator's cut points (CHN-04). Every scored member must have features."""
    merged = scores.merge(
        features[["msno", "listening_trend_30d"]], on="msno", how="left", validate="one_to_one"
    )
    if merged["listening_trend_30d"].isna().any():
        raise ValueError("some scored members have no features")
    lo, hi = sim.risk_bands.cuts
    risk = merged["churn_risk"].to_numpy()
    merged["risk_band"] = np.where(risk < lo, "low", np.where(risk < hi, "medium", "high"))
    merged["trend_band"] = np.where(
        merged["listening_trend_30d"] < sim.trend_bands.cuts[0], "declining", "stable"
    )
    return merged.drop(columns="listening_trend_30d")
