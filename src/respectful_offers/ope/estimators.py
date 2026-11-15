"""Off-policy estimators for period 1 (Tech Spec §7.2, D-1, A2.6).

Logs come from the logging pilot: uniform choice over each member's allowed actions, with the
exact propensity μ(a|x) = 1/|allowed|. For a target policy with probabilities π(a|x):

    IPS    V̂ = (1/n) Σ wᵢ rᵢ,                 wᵢ = π(aᵢ|xᵢ) / μ(aᵢ|xᵢ)
    SNIPS  V̂ = Σ wᵢ rᵢ / Σ wᵢ
    DR     V̂ = (1/n) Σ [Σₐ π(a|xᵢ) q̂(xᵢ, a) + wᵢ (rᵢ − q̂(xᵢ, aᵢ))]

with q̂ a per-action gradient-boosted regressor (D-29), cross-fitted over two hash folds so a
member's own reward never predicts itself. Intervals: a block bootstrap over member-hash
blocks (D-16), recomputing each estimate from per-block sums.

Why period 1 only: at period 1 no member has a history, so every policy's allowed set is the
logger's and the logger covers every action a target can take. From period 2 the target's
own past choices change its allowed sets, which logged data cannot follow (C3); the scope
guard refuses any other period.

Targets are passed as probability arrays; `ope.data.target_probabilities` is the period-1
guard for them. What is estimated is each target's own choice distribution before the
budget (D-33): the pacer is a cohort-level constraint that couples members, not a
per-member policy, so a single-step estimator cannot follow it. The rollouts, not OPE,
carry budgeted results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from respectful_offers.schemas.summary import Interval
from respectful_offers.threads import small_fit_threads

Estimator = Literal["ips", "snips", "dr"]
REWARD_MODEL_PARAMS: dict[str, Any] = {
    "max_iter": 100,
    "learning_rate": 0.1,
    "max_leaf_nodes": 15,
    "min_samples_leaf": 20,
    "early_stopping": False,
}


MIN_BLOCKS = 20  # populated hash blocks below this give intervals too narrow to trust
MAX_NAN_SHARE = 0.01  # SNIPS resamples with Σw = 0 are undefined; more than this, refuse


class SupportError(ValueError):
    """The target puts probability where the logger never acts."""


@dataclass(frozen=True)
class Logs:
    """Period-1 logs from the logging pilot, aligned arrays."""

    x: np.ndarray  # [n, d] reward-model features
    allowed: np.ndarray  # [n, 4] bool
    action: np.ndarray  # [n] action index
    propensity: np.ndarray  # [n] μ(a|x)
    reward: np.ndarray  # [n] net revenue
    hashes: np.ndarray  # [n] uint64 member hashes (folds and blocks)
    period: int = 1

    def __post_init__(self) -> None:
        n = len(self.action)
        if self.period != 1:
            raise ValueError("off-policy estimates are defined for period 1 only (C3)")
        if n == 0:
            raise ValueError("the logs are empty")
        shapes_ok = (
            self.allowed.shape == (n, 4)
            and self.allowed.dtype == bool
            and self.x.ndim == 2
            and self.x.shape[0] == n
            and self.reward.shape == (n,)
            and self.propensity.shape == (n,)
            and self.hashes.shape == (n,)
        )
        if not shapes_ok:
            raise ValueError("log arrays are misaligned")
        if self.hashes.dtype != np.uint64 or len(np.unique(self.hashes)) != n:
            raise ValueError("member hashes must be distinct uint64 values")
        if (
            not np.issubdtype(self.action.dtype, np.integer)
            or not ((self.action >= 0) & (self.action < 4)).all()
        ):
            raise ValueError("logged actions must be action indices 0..3")
        if not self.allowed[np.arange(n), self.action].all():
            raise ValueError("a logged action was not allowed")
        uniform = 1.0 / self.allowed.sum(axis=1)
        if not np.allclose(self.propensity, uniform, rtol=0.0, atol=1e-12):
            raise ValueError("logging propensities must be exactly 1/|allowed| (the uniform pilot)")
        if not (np.isfinite(self.reward).all() and np.isfinite(self.x).all()):
            raise ValueError("rewards and reward-model features must be finite")


def check_support(logs: Logs, target: np.ndarray) -> None:
    if target.shape != logs.allowed.shape:
        raise ValueError("target probabilities must be [n, 4]")
    if not np.isfinite(target).all() or (target < 0).any():
        raise ValueError("target probabilities must be distributions")
    if not np.allclose(target.sum(axis=1), 1.0, rtol=0.0, atol=1e-9):
        raise ValueError("target probabilities must be distributions")
    outside = target[~logs.allowed]
    if (outside > 0).any():
        raise SupportError(
            f"target puts mass {float(outside.sum()):.4g} outside the logger's support"
        )


def fit_reward_model(logs: Logs, seed: int, folds: int = 2) -> np.ndarray:
    """Cross-fitted q̂(x, a) for every member and action, [n, 4]."""
    with small_fit_threads(len(logs.action)):
        return _fit_reward_model(logs, seed, folds)


def _fit_reward_model(logs: Logs, seed: int, folds: int) -> np.ndarray:
    n = len(logs.action)
    fold = (logs.hashes % np.uint64(folds)).astype(int)
    if len(np.unique(fold)) != folds:
        raise ValueError(f"cross-fitting needs members in all {folds} hash folds")
    q = np.zeros((n, 4))
    for f in range(folds):
        train, test = fold != f, fold == f
        for a in range(4):
            m = train & (logs.action == a)
            if m.sum() < 20:  # too little data: fall back to the action's mean (or overall)
                fallback = logs.reward[m].mean() if m.any() else logs.reward[train].mean()
                q[test, a] = fallback
                continue
            model = HistGradientBoostingRegressor(random_state=seed, **REWARD_MODEL_PARAMS)
            model.fit(logs.x[m], logs.reward[m])
            q[test, a] = model.predict(logs.x[test])
    return q


def _terms(logs: Logs, target: np.ndarray, q: np.ndarray | None) -> dict[str, np.ndarray]:
    n = len(logs.action)
    w = target[np.arange(n), logs.action] / logs.propensity
    terms = {"w": w, "wr": w * logs.reward}
    if q is not None:
        terms["dr"] = (target * q).sum(axis=1) + w * (logs.reward - q[np.arange(n), logs.action])
    return terms


def _value(estimator: Estimator, sums: dict[str, np.ndarray], n: np.ndarray) -> np.ndarray:
    if estimator == "ips":
        return sums["wr"] / n
    if estimator == "snips":
        return sums["wr"] / np.where(sums["w"] > 0, sums["w"], np.nan)
    return sums["dr"] / n


def estimate(
    logs: Logs,
    target: np.ndarray,
    estimator: Estimator,
    *,
    q: np.ndarray | None = None,
    blocks: int = 1_000,
    resamples: int = 10_000,
    seed: int = 0,
) -> tuple[Interval, float]:
    """(value with a block-bootstrap 95% interval, effective sample size)."""
    check_support(logs, target)
    if estimator == "dr" and q is None:
        raise ValueError("the DR estimate needs reward-model predictions q")
    if estimator == "dr" and (
        q is None or q.shape != logs.allowed.shape or not np.isfinite(q).all()
    ):
        raise ValueError("reward-model predictions q must be finite and [n, 4]")
    terms = _terms(logs, target, q if estimator == "dr" else None)
    if terms["w"].sum() <= 0:
        raise SupportError("the target gives zero probability to every logged action")
    n = len(logs.action)
    block = (logs.hashes % np.uint64(blocks)).astype(int)
    populated = len(np.unique(block))
    if populated < MIN_BLOCKS:
        raise ValueError(
            f"only {populated} bootstrap blocks hold members; at least {MIN_BLOCKS} are needed "
            "for an honest interval"
        )
    per_block = {k: np.bincount(block, weights=v, minlength=blocks) for k, v in terms.items()}
    counts = np.bincount(block, minlength=blocks).astype(float)
    point = float(
        _value(estimator, {k: v.sum(keepdims=True) for k, v in per_block.items()}, np.array([n]))[0]
    )
    rng = np.random.default_rng(seed)
    draws = np.empty(resamples)
    chunk = max(1, 4_000_000 // blocks)
    for lo in range(0, resamples, chunk):
        hi = min(lo + chunk, resamples)
        idx = rng.integers(0, blocks, (hi - lo, blocks))
        sums = {k: v[idx].sum(axis=1) for k, v in per_block.items()}
        draws[lo:hi] = _value(estimator, sums, counts[idx].sum(axis=1))
    nan_share = float(np.isnan(draws).mean())
    if nan_share > MAX_NAN_SHARE:
        raise ValueError(
            f"{nan_share:.0%} of bootstrap resamples have no weighted rows: too few logged "
            "actions the target would take for an interval"
        )
    lo_, hi_ = np.nanpercentile(draws, [2.5, 97.5])
    w = terms["w"]
    ess = float(w.sum() ** 2 / (w**2).sum()) if (w**2).sum() > 0 else 0.0
    return Interval(point=round(point, 6), lo=round(float(lo_), 6), hi=round(float(hi_), 6)), ess


def oracle_value(target: np.ndarray, expected: np.ndarray) -> float:
    """Exact period-1 value of a target policy on these members: mean over members of
    Σₐ π(a|x) E[r|x, a]. Pass `expected_reward_by_segment` (each member's own, fixed hidden
    segment), not the cell-mix average, or targets that read the segment are mis-scored (D-36)."""
    return float((target * expected).sum(axis=1).mean())
