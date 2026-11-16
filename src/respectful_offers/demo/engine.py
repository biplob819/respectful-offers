"""`simulate(budget, threshold, variant)`: the live demo (Tech Spec §8, DMO-02..05).

It samples synthetic members from the cohort cube with a fixed seed (each member takes its
cell's means, so no real member is ever reproduced), then rolls out no offer, the
rule-following baseline, the frozen bandit and the status quo for the horizon under common
random numbers, and audits every log with the independent auditor. Moving the threshold
changes R2's allowed sets; the bandit stays the one trained at the reference threshold.
Denominators use the reference threshold, so the at-risk rate does not move with the slider.
"""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from respectful_offers.demo.cube import CUBE_VERSION, DIMS, MIN_CELL, SPREAD, integrity
from respectful_offers.policy.audit import audit
from respectful_offers.policy.bandit import Posterior, ThompsonBandit
from respectful_offers.policy.baselines import NoOffer, Policy, RuleFollowingBaseline, StatusQuo
from respectful_offers.policy.cohort import Cohort, build_cohort
from respectful_offers.policy.rollout import rollout
from respectful_offers.schemas.config import load_simulator_config
from respectful_offers.schemas.simulator import SimulatorConfig

DEMO_MEMBERS = 20_000
DEMO_NODES = 16  # integration nodes for the demo's bandit: worst error about 1e-3 (D-35)
DEMO_SEED = 20261121
POLICIES = ("no_offer", "rule_following_baseline", "bandit", "status_quo")


@dataclass(frozen=True)
class Cube:
    data: dict[str, Any]
    sim: SimulatorConfig
    digest: str = ""  # the cache key: the cube's content, never its id

    @property
    def reference(self) -> dict[str, Any]:
        return self.data["reference"]


DATA_SOURCES = {"kaggle", "local", "synthetic", "your_table"}
CUBE_KEYS = {
    "integrity",
    "cube_version",
    "simulated",
    "data_source",
    "members",
    "min_cell",
    "dims",
    "cells",
    "simulator_yaml",
    "posteriors",
    "reference",
    "agreement",
}
CELL_KEYS = {*DIMS, "count", "means", "sds", "price_levels"}
RANGES = {
    "churn_risk": (0.0, 1.0),
    "tenure_days": (0.0, 1e5),
    "cancels_90d": (0.0, 1e3),
    "listening_trend_30d": (-1.0, 1e3),
    "price_30d": (0.0, 1e5),
    "auto_renew": (0.0, 1.0),
}


def check_cube(data: dict[str, Any]) -> None:
    """Refuse a cube that is not exactly what `offers demo-cube` writes (DMO-02): unknown keys
    (a member-rows block, say), cells below the code's minimum, inconsistent counts, values out
    of range, a widened allow-list, or a posterior missing for a variant."""
    from respectful_offers.schemas.config import protected_name

    if not isinstance(data, dict) or set(data) != CUBE_KEYS:
        raise ValueError("not a demo cube: unexpected or missing top-level keys")
    if (
        data["cube_version"] != CUBE_VERSION
        or data["simulated"] is not True
        or data["min_cell"] != MIN_CELL
    ):
        raise ValueError("not a demo cube of this version")
    total = 0
    for cell in data["cells"]:
        if set(cell) != CELL_KEYS:
            raise ValueError("a cube cell has unexpected keys")
        n = cell["count"]
        if isinstance(n, bool) or not isinstance(n, int) or n < MIN_CELL:
            raise ValueError(f"a cube cell holds fewer than the minimum {MIN_CELL} members")
        for name, (lo, hi) in RANGES.items():
            v = cell["means"].get(name)
            if not isinstance(v, int | float) or not (lo <= v <= hi) or not math.isfinite(v):
                raise ValueError(f"a cube cell's {name} mean is out of range")
        if any(
            not isinstance(v, int | float) or v < 0 or not math.isfinite(v)
            for v in cell["sds"].values()
        ):
            raise ValueError("a cube cell's spread is invalid")
        levels = cell["price_levels"]
        if (
            not isinstance(levels, list)
            or not levels
            or any(
                not isinstance(lv, list)
                or len(lv) != 2
                or any(isinstance(x, bool) or not isinstance(x, int | float) for x in lv)
                or not (0.0 <= lv[0] <= RANGES["price_30d"][1])
                or not (0.0 < lv[1] <= 1.0)
                for lv in levels
            )
            or abs(sum(lv[1] for lv in levels) - 1.0) > 0.011
            or len({lv[0] for lv in levels}) != len(levels)
        ):
            raise ValueError("a cube cell's price levels are invalid")
        total += n
    if total != data["members"]:
        raise ValueError("cube counts do not add up to its members")
    if data["integrity"] != integrity(data):
        raise ValueError("the cube was edited after `offers demo-cube` wrote it (integrity check)")
    if data["data_source"] not in DATA_SOURCES:
        raise ValueError(f"unknown data source {data['data_source']!r}")
    ref = data["reference"]
    yaml_sha = hashlib.sha256(data["simulator_yaml"].encode("utf-8")).hexdigest()
    if not yaml_sha.startswith(ref["simulator_hash"]):
        raise ValueError("the cube's simulator text is not the run's pre-registered simulator")
    if any(protected_name(c) for c in ref["decision_features"]):
        raise ValueError("the cube's decision features include a protected attribute")
    missing = sorted(set(ref["variants"]) - set(data["posteriors"]))
    if missing:
        raise ValueError(f"the cube has no bandit posterior for {missing}")


def load_cube(path: Path) -> Cube:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    check_cube(data)
    with tempfile.TemporaryDirectory() as tmp:  # validate the embedded simulator like a file
        sim_path = Path(tmp) / "simulator.yaml"
        sim_path.write_text(data["simulator_yaml"], encoding="utf-8", newline="")
        sim = load_simulator_config(sim_path)
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return Cube(data, sim, digest)


def sample(
    cube: Cube, n: int = DEMO_MEMBERS, seed: int = DEMO_SEED
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Synthetic members in proportion to the cells (largest remainder), each with its cell's
    means; auto-renew is drawn from the cell's share where the cell merged it, and the price
    from the cell's price levels (D-49)."""
    cells = cube.data["cells"]
    counts = np.array([c["count"] for c in cells], dtype=float)
    quota = counts / counts.sum() * n
    take = np.floor(quota).astype(int)
    take[np.argsort(-(quota - take), kind="stable")[: n - take.sum()]] += 1
    rng = np.random.default_rng(seed)
    idx = np.repeat(np.arange(len(cells)), take)
    means = pd.DataFrame([c["means"] for c in cells]).iloc[idx].reset_index(drop=True)
    sds = pd.DataFrame([c.get("sds", {}) for c in cells]).reindex(columns=list(SPREAD)).fillna(0.0)
    sds = sds.iloc[idx].reset_index(drop=True)
    msno = [f"demo-{i:06d}" for i in range(n)]
    auto = rng.uniform(size=n) < means["auto_renew"].to_numpy()

    def normal(col: str, lo: float) -> np.ndarray:
        m, s = means[col].to_numpy(), sds[col].to_numpy()
        return np.clip(m + s * rng.standard_normal(n), lo, np.inf)

    features = pd.DataFrame(
        {
            "msno": msno,
            "cohort": "mar",
            "tenure_days": normal("tenure_days", 0).round().astype(int),
            "auto_renew": auto,
            "cancels_90d": normal("cancels_90d", 0).round().astype(int),
            "listening_trend_30d": normal("listening_trend_30d", -1.0),
            "price_30d": _prices(rng, cells, idx),
            "plan_days": 30,
            "churn_label": False,
        }
    )
    risk = _beta_risk(rng, means["churn_risk"].to_numpy(), sds["churn_risk"].to_numpy())
    scores = pd.DataFrame({"msno": msno, "churn_risk": risk})
    return scores, features


def _prices(rng: np.random.Generator, cells: list[dict[str, Any]], idx: np.ndarray) -> np.ndarray:
    out = np.empty(len(idx))
    for c in np.unique(idx):
        at = np.flatnonzero(idx == c)
        levels = np.array(cells[c]["price_levels"], dtype=float)
        out[at] = rng.choice(levels[:, 0], size=len(at), p=levels[:, 1] / levels[:, 1].sum())
    return out


def _beta_risk(rng: np.random.Generator, m: np.ndarray, s: np.ndarray) -> np.ndarray:
    """A beta draw with the cell's mean and spread (the mean itself where the spread is 0 or
    too large for a beta)."""
    m = np.clip(m, 0.001, 0.999)
    var = np.square(s)
    ok = (var > 0) & (var < m * (1 - m))
    k = np.where(ok, m * (1 - m) / np.where(ok, var, 1.0) - 1, 1.0)
    draw = rng.beta(np.where(ok, m * k, 1.0), np.where(ok, (1 - m) * k, 1.0))
    return np.clip(np.where(ok, draw, m), 0.001, 0.999)


_CUBES: dict[str, Cube] = {}  # digest → cube, bounded with the caches below


def _remember(cube: Cube) -> str:
    if cube.digest not in _CUBES and len(_CUBES) >= 8:
        _CUBES.pop(next(iter(_CUBES)))
    _CUBES[cube.digest] = cube
    return cube.digest


@lru_cache(maxsize=8)
def _cohort(key: str, variant: str) -> Cohort:
    cube = _CUBES[key]
    scores, features = sample(cube)
    return build_cohort(scores, features, cube.sim, variant, DEMO_SEED)


@lru_cache(maxsize=8)
def _no_offer(key: str, variant: str, periods: int):
    cube = _CUBES[key]
    return rollout(
        NoOffer(),
        _cohort(key, variant),
        cube.sim,
        variant,
        periods=periods,
        risk_threshold=0.5,
        budget_per_1000=0.0,
        seed=DEMO_SEED,
        run_id="demo",
        check=False,
    )


def simulate(cube: Cube, budget: float, threshold: float, variant: str) -> dict[str, Any]:
    """Every figure the demo shows, for one setting of the sliders (all simulated)."""
    if variant not in cube.data["posteriors"]:
        raise ValueError(
            f"the cube has no variant {variant!r}: it holds {sorted(cube.data['posteriors'])}"
        )
    for v in (budget, threshold):
        if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
            raise ValueError("the budget and the threshold must be finite numbers")
    if not (0.0 < threshold < 1.0) or budget < 0:
        raise ValueError("the threshold must lie in (0, 1) and the budget must be non-negative")
    key = _remember(cube)
    cohort = _cohort(key, variant)
    ref = cube.reference
    raw = dict(cube.data["posteriors"][variant], integration_nodes=DEMO_NODES)
    posterior = Posterior.from_json(json.dumps(raw))
    bandit = ThompsonBandit(
        np.zeros((0, len(posterior.columns))),
        list(posterior.columns),
        tuple(ref["decision_features"]),
        posterior=posterior,
    )
    ctx = bandit.context_for(cohort.features, cohort.churn_risk)
    common = dict(
        sim=cube.sim,
        variant=variant,
        periods=int(ref["horizon_periods"]),
        risk_threshold=threshold,
        budget_per_1000=budget,
        seed=DEMO_SEED,
        run_id="demo",
    )
    runs: dict[str, Any] = {}
    policies: list[tuple[Policy, dict[str, Any]]] = [
        (NoOffer(), {}),
        (RuleFollowingBaseline(), {}),
        (bandit, {"context": ctx, "context_columns": tuple(posterior.columns)}),
        (StatusQuo(), {}),
    ]
    at_risk = cohort.churn_risk >= float(ref["risk_threshold"])  # reference denominator
    kept_by: dict[str, np.ndarray] = {}
    for policy, extra in policies:
        if policy.name == "no_offer":  # depends on neither slider: computed once per variant
            res = _no_offer(key, variant, int(ref["horizon_periods"]))
        else:
            res = rollout(policy, cohort, **common, **extra, check=False)  # type: ignore[arg-type]
        o = res.outcomes
        kept = o.groupby("msno")["renewed"].agg(["all", "size"])
        kept = (kept["all"] & (kept["size"] == common["periods"])).reindex(
            cohort.msno, fill_value=False
        )
        kept_by[policy.name] = kept.to_numpy(dtype=float)
        shown = res.decisions["chosen"].ne("no_offer")
        rep = audit(
            res.decisions,
            o,
            churn_risk=pd.Series(cohort.churn_risk, index=cohort.msno),
            holdout=pd.Series(False, index=cohort.msno),
            risk_threshold=threshold,
            context_columns={policy.name: tuple(policy.context_columns)},
            allow_list=tuple(ref["decision_features"]),
        )
        runs[policy.name] = {
            "retained_per_1000": round(1000 * float(kept.mean()), 2),
            "retained_per_1000_at_risk": round(1000 * float(kept.to_numpy()[at_risk].mean()), 2)
            if at_risk.sum() >= 30
            else None,
            "discount_per_member": round(math.fsum(o["discount_cost"]) / len(cohort), 4),
            "offers_per_member_month": round(float(shown.mean()), 4),
            "decisions": len(shown),
            "violations": rep.violations(policy.name, variant),
            "respectful": policy.respectful,
        }
    base = runs["no_offer"]["retained_per_1000"]
    n = len(cohort)
    for name, r in runs.items():
        r["incremental_per_1000"] = round(r["retained_per_1000"] - base, 2)
        diff = kept_by[name] - kept_by["no_offer"]  # paired on the same members (CRN)
        r["incremental_se"] = round(1000 * float(diff.std(ddof=1)) / math.sqrt(n), 4)
    return {
        "simulated": True,
        "variant": variant,
        "budget_per_1000": budget,
        "threshold": threshold,
        "bandit_trained_at": float(ref["risk_threshold"]),
        "members": len(cohort),
        "at_risk_now": int((cohort.churn_risk >= threshold).sum()),
        "policies": runs,
    }


def agreement(cube: Cube, variant: str = "central") -> list[dict[str, Any]]:
    """DMO-05: at the reference settings, does each policy agree with the full run on retained
    per 1,000, the paired incremental retained per 1,000 and offers per member-month? Each
    must lie within the run's 95% interval widened by two standard errors of the demo's own
    estimate (its members are a fresh synthetic sample, D-42, D-43). Every policy the run
    reported must be checked: a missing row is a failure."""
    ref = cube.reference
    out = simulate(cube, float(ref["budget_per_1000"]), float(ref["risk_threshold"]), variant)
    expected = cube.data["agreement"].get(variant, {})
    if set(expected) < set(out["policies"]):
        raise ValueError(f"the cube's agreement block lacks policies for {variant!r}")
    rows = []
    n = out["members"]
    for name, r in out["policies"].items():
        full = expected[name]
        p = r["retained_per_1000"] / 1000
        q = r["offers_per_member_month"]
        checks = {
            "retained_per_1000": (r["retained_per_1000"], 2 * 1000 * math.sqrt(p * (1 - p) / n)),
            "incremental_retained_per_1000": (r["incremental_per_1000"], 2 * r["incremental_se"]),
            "offers_per_member_month": (
                q,
                2 * math.sqrt(max(q * (1 - q), 1e-12) / max(r["decisions"], 1)),
            ),
        }
        for metric, (value, slack) in checks.items():
            iv = full[metric]
            lo, hi = iv["lo"] - slack, iv["hi"] + slack
            rows.append(
                {
                    "policy": name,
                    "metric": metric,
                    "demo": value,
                    "full": iv,
                    "lo": round(lo, 4),
                    "hi": round(hi, 4),
                    "agrees": lo <= value <= hi,
                }
            )
    return rows
