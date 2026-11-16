"""The demo's cohort cube (Tech Spec §8, D-12, DMO-01): aggregates only, never member rows.

Cells are risk decile × trend band × auto-renew × tenure band × price band over the
evaluation cohort. Each cell keeps its member count, the means of the decision features and
its price levels: real prices are a few discrete plan prices (0, 99, 149, 180 NTD...), and a
mean price changes which offers a member can get and what the bandit picks (D-49, found by the
real-data agreement check). Every published price level covers at least `K_LEVEL` members.
A cell under `MIN_CELL` members is merged by coarsening, one dimension at a time (price band,
then tenure band, then auto-renew, then risk deciles into pairs, fives and all), anything
still too small joins a single remainder cell, and a remainder still too small joins the
largest cell. No member id, row or hash is written.

The cube also carries what the demo needs to run offline: the simulator file's text, the
frozen bandit posterior per variant, the reference settings and the full run's intervals (for
the agreement check, DMO-05).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

CUBE_VERSION = "2"
MIN_CELL = 20
K_LEVEL = 5  # members behind every published price level (disclosure control, D-49)
DIMS = ("risk_decile", "trend_band", "auto_renew", "tenure_band", "price_band")
MEANS = (
    "churn_risk",
    "tenure_days",
    "cancels_90d",
    "listening_trend_30d",
    "price_30d",
    "auto_renew",
)
ANY = "any"
SPREAD = ("churn_risk", "tenure_days", "cancels_90d", "listening_trend_30d")


def bands(df: pd.DataFrame, trend_cut: float) -> pd.DataFrame:
    """The cube's dimensions for each member (kept in memory only)."""
    ranks = df["churn_risk"].rank(method="first")
    out = pd.DataFrame(index=df.index)
    out["risk_decile"] = (np.ceil(ranks / len(df) * 10).clip(1, 10) - 1).astype(int).astype(str)
    out["trend_band"] = np.where(df["listening_trend_30d"] < trend_cut, "declining", "stable")
    out["auto_renew"] = np.where(df["auto_renew"].astype(bool), "yes", "no")
    out["tenure_band"] = pd.cut(
        df["tenure_days"], [-1, 179, 729, np.inf], labels=["<6m", "6-24m", ">24m"]
    ).astype(str)
    out["price_band"] = pd.cut(
        df["price_30d"], [-1, 99, 149, np.inf], labels=["<=99", "100-149", ">149"]
    ).astype(str)
    return out


def _coarser_risk(value: Any, step: int) -> str:
    value = str(value)
    if value == ANY or step >= 10:
        return ANY
    lo = int(value.split("-")[0]) // step * step
    return f"{lo}-{lo + step - 1}"


def merge_small(keys: pd.DataFrame, min_cell: int = MIN_CELL) -> pd.DataFrame:
    """Coarsen the keys of members in small cells until every cell holds min_cell or more."""
    if len(keys) < min_cell:
        raise ValueError(f"the cohort is too small for a cube: fewer than {min_cell} members")
    keys = keys.copy()

    def small() -> pd.Series:
        size = keys.groupby(list(DIMS), sort=False)["risk_decile"].transform("size")
        return size < min_cell

    for dim in ("price_band", "tenure_band", "auto_renew"):
        m = small()
        keys.loc[m, dim] = ANY
    for step in (2, 5, 10):
        m = small()
        keys.loc[m, "risk_decile"] = keys.loc[m, "risk_decile"].map(
            lambda v, s=step: _coarser_risk(v, s)
        )
    m = small()
    if m.any():  # whatever is left becomes one remainder cell
        for dim in DIMS:
            keys.loc[m, dim] = ANY
    m = small()
    if m.any():  # a remainder still too small joins the largest cell; where their labels
        # differ the merged cell says "any", so no member is mislabelled
        largest = keys[~m].groupby(list(DIMS), sort=True).size().idxmax()
        assert isinstance(largest, tuple)
        target = pd.Series(True, index=keys.index)
        for dim, value in zip(DIMS, largest, strict=True):
            target &= keys[dim] == value
        both = m | target
        for dim, value in zip(DIMS, largest, strict=True):
            keys.loc[both, dim] = ANY if (keys.loc[m, dim] != value).any() else value
    return keys


def build_cube(
    scores: pd.DataFrame,
    features: pd.DataFrame,
    trend_cut: float,
    *,
    simulator_yaml: str,
    posteriors: dict[str, Any],
    reference: dict[str, Any],
    agreement: dict[str, Any],
    data_source: str,
) -> dict[str, Any]:
    df = scores.merge(features, on="msno", how="inner", validate="one_to_one")
    if len(df) != len(scores):
        raise ValueError("every scored member needs features")
    if not np.isfinite(df[list(MEANS)].astype(float).to_numpy()).all():
        raise ValueError("cube inputs must be finite (no NaN)")
    keys = merge_small(bands(df, trend_cut))
    df = pd.concat([keys, df[list(MEANS)].astype(float).add_prefix("m_")], axis=1)
    grouped = df.groupby(list(DIMS), sort=True)
    cells = []
    for key, g in grouped:
        cell: dict[str, Any] = dict(zip(DIMS, key, strict=True))
        # Disclosure control (D-43): counts rounded to fives (never below the minimum), means and
        # spreads to three significant figures, so two cubes from cohorts that differ by one
        # member cannot be differenced back to that member's values.
        cell["count"] = max(MIN_CELL, int(5 * round(len(g) / 5)))
        cell["means"] = {c: _sig3(float(g[f"m_{c}"].mean())) for c in MEANS}
        cell["sds"] = {c: _sig3(float(g[f"m_{c}"].std(ddof=0))) for c in SPREAD}
        cell["price_levels"] = price_levels(g["m_price_30d"].to_numpy())
        cells.append(cell)
    if min(c["count"] for c in cells) < MIN_CELL:  # belt and braces: never a small cell
        raise ValueError("a cube cell holds fewer than the minimum members")
    return {
        "cube_version": CUBE_VERSION,
        "simulated": True,
        "data_source": data_source,
        "members": int(sum(c["count"] for c in cells)),
        "min_cell": MIN_CELL,
        "dims": list(DIMS),
        "cells": cells,
        "simulator_yaml": simulator_yaml,
        "posteriors": posteriors,
        "reference": reference,
        "agreement": agreement,
    }


def price_level_counts(prices: np.ndarray, k: int = K_LEVEL) -> tuple[np.ndarray, np.ndarray]:
    """Whole-NTD price levels held by `k` or more members, and how many members each level
    stands for once members at rarer prices join the nearest kept level. Empty when no price
    is that common."""
    whole = np.round(np.asarray(prices, dtype=float))
    values, counts = np.unique(whole, return_counts=True)
    kept = values[counts >= k]
    if not len(kept):
        return kept, counts[:0]
    nearest = kept[np.abs(whole[:, None] - kept[None, :]).argmin(axis=1)]
    return np.unique(nearest, return_counts=True)


def price_levels(prices: np.ndarray, k: int = K_LEVEL) -> list[list[float]]:
    """A cell's prices as [[price, share], ...]: whole NTD, each level held by `k` or more
    members (members at rarer prices join the nearest kept level), shares to two decimals.
    With no level that common, the cell's mean price is the only level."""
    levels, n = price_level_counts(prices, k)
    if not len(levels):
        return [[_sig3(float(np.mean(prices))), 1.0]]
    shares = np.round(n / n.sum(), 2)
    keep = shares > 0  # a level under half a percent joins the most common one
    levels, shares = levels[keep], shares[keep]
    shares[np.argmax(shares)] += round(1.0 - float(shares.sum()), 2)  # sum exactly to one
    return [[float(v), round(float(s), 2)] for v, s in zip(levels, shares, strict=True)]


def _sig3(x: float) -> float:
    return float(f"{x:.3g}")


def integrity(cube: dict[str, Any]) -> str:
    """sha256 of everything but the digest itself: catches edits made after `demo-cube`."""
    body = {k: v for k, v in cube.items() if k != "integrity"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def dumps(cube: dict[str, Any]) -> str:
    cube = {**cube, "integrity": integrity(cube)}
    return json.dumps(cube, indent=1, sort_keys=True) + "\n"


def make_cube(
    scores: pd.DataFrame,
    features: pd.DataFrame,
    run_dir: Any,
    simulator_path: Any,
    cfg: Any,
    sim: Any,
    *,
    config_path: Any = None,
    data_source: str | None = None,
) -> dict[str, Any]:
    """The cube from a finished run: the evaluation cohort's aggregates, the run's frozen
    posteriors, and its intervals at the reference settings for the agreement check."""
    from pathlib import Path

    from respectful_offers.evaluate.pipeline import split
    from respectful_offers.policy.cohort import build_cohort
    from respectful_offers.schemas.summary import RunSummary
    from respectful_offers.sim.prereg import sha256

    run_dir = Path(run_dir)
    summary = RunSummary.model_validate_json((run_dir / "summary.json").read_text("utf-8"))
    if summary.prereg_status != "preregistered":
        raise ValueError("the run is exploratory: a demo is built only from a pre-registered run")
    if sha256(Path(simulator_path))[:16] != summary.simulator_hash:
        raise ValueError(f"{simulator_path} is not the simulator the run used")
    if config_path is not None and sha256(Path(config_path))[:16] != summary.config_hash:
        raise ValueError(f"{config_path} is not the run config the run used")
    if data_source is not None and data_source != summary.data_source:
        raise ValueError(f"the data is {data_source}, but the run used {summary.data_source}")
    frontier = json.loads((run_dir / "frontier.json").read_text("utf-8"))
    if not summary.simulator_hash or not (run_dir / "audit.json").is_file():
        raise ValueError(f"{run_dir} is not a finished `offers evaluate` run")
    if json.loads((run_dir / "audit.json").read_text("utf-8")).get("clean") is not True:
        raise ValueError("the run's audit failed: no demo is built from it")
    ev = split(build_cohort(scores, features, sim, summary.variants[0], cfg.seed), cfg)["eval"]
    if len(ev) != summary.policies[0].n_members:
        raise ValueError(
            f"these members give an evaluation cohort of {len(ev):,}, but the run evaluated "
            f"{summary.policies[0].n_members:,}: use the run's own data"
        )
    keep = scores["msno"].isin(set(ev.msno))
    agreement: dict[str, dict[str, Any]] = {p.variant: {} for p in summary.policies}
    for p in summary.policies:
        agreement[p.variant][p.policy] = {
            name: json.loads(getattr(p, name).model_dump_json())
            for name in (
                "retained_per_1000",
                "incremental_retained_per_1000",
                "offers_per_member_month",
            )
        }
    reference = {
        "risk_threshold": cfg.risk_threshold,
        "budget_per_1000": cfg.budget_per_1000_per_period,
        "horizon_periods": cfg.horizon_periods,
        "decision_features": list(cfg.decision_features),
        "variants": list(summary.variants),
        "run_id": summary.run_id,
        "simulator_hash": summary.simulator_hash,
        "prereg_status": summary.prereg_status,
        # holdout facts from the run, so the page never asserts what it cannot show
        "holdout_share": (cfg.cohort_buckets["holdout"][1] - cfg.cohort_buckets["holdout"][0])
        / 100,
        "holdout_check": {
            v: json.loads(iv.model_dump_json()) for v, iv in summary.holdout_check.items()
        },
    }
    return build_cube(
        scores[keep],
        features[features["msno"].isin(set(ev.msno))],
        sim.trend_bands.cuts[0],
        simulator_yaml=Path(simulator_path).read_bytes().decode("utf-8"),
        posteriors={v: frontier["bandit"][v]["posterior"] for v in summary.variants},
        reference=reference,
        agreement=agreement,
        data_source=summary.data_source,
    )
