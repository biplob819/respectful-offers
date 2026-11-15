"""A cohort of members ready to roll out: features, calibrated risk, bands, hidden segments.

Built once per variant from the churn stage's March scores, the March features and the
simulator. The hidden segment is drawn from each member's own CRN stream, so it is the same
for every policy in a variant (D-1).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from respectful_offers.runtime.seeds import member_hashes
from respectful_offers.schemas.simulator import SimulatorConfig
from respectful_offers.sim.response import Tables, cell_index, draw_segments

RISK_BANDS = ("low", "medium", "high")


@dataclass(frozen=True)
class Cohort:
    msno: np.ndarray
    hashes: np.ndarray
    churn_risk: np.ndarray
    base: np.ndarray  # 1 − churn risk
    price: np.ndarray
    cells: np.ndarray
    risk_band: np.ndarray  # strings
    trend_band: np.ndarray
    segment: np.ndarray  # hidden: only the simulator and the segment oracle read it
    features: pd.DataFrame  # the March features rows, aligned with msno

    def __len__(self) -> int:
        return len(self.msno)

    def subset(self, mask: np.ndarray) -> Cohort:
        return Cohort(
            self.msno[mask],
            self.hashes[mask],
            self.churn_risk[mask],
            self.base[mask],
            self.price[mask],
            self.cells[mask],
            self.risk_band[mask],
            self.trend_band[mask],
            self.segment[mask],
            self.features[mask].reset_index(drop=True),
        )


def build_cohort(
    scores: pd.DataFrame, features: pd.DataFrame, sim: SimulatorConfig, variant: str, seed: int
) -> Cohort:
    df = scores.merge(features, on="msno", how="inner", validate="one_to_one")
    if len(df) != len(scores):
        raise ValueError("every scored member needs March features")
    df = df.sort_values("msno", kind="mergesort").reset_index(drop=True)
    risk = df["churn_risk"].to_numpy(dtype=float)
    if not (np.isfinite(risk).all() and (risk >= 0).all() and (risk <= 1).all()):
        raise ValueError("churn risks must be probabilities")
    lo, hi = sim.risk_bands.cuts
    risk_band = np.where(risk < lo, "low", np.where(risk < hi, "medium", "high"))
    trend = df["listening_trend_30d"].to_numpy(dtype=float)
    trend_band = np.where(trend < sim.trend_bands.cuts[0], "declining", "stable")
    cells = cell_index(risk_band, trend_band)
    hashes = member_hashes(df["msno"])
    t = Tables.from_config(sim, variant)
    return Cohort(
        msno=df["msno"].to_numpy(dtype=object),
        hashes=hashes,
        churn_risk=risk,
        base=1.0 - risk,
        price=df["price_30d"].to_numpy(dtype=float),
        cells=cells,
        risk_band=risk_band,
        trend_band=trend_band,
        segment=draw_segments(seed, hashes, cells, t),
        features=df[[c for c in features.columns]].reset_index(drop=True),
    )
