"""Block bootstrap, paired comparisons and Holm (Tech Spec §7.3, D-16).

Members are summed into hash blocks once; each resample draws blocks with replacement and
recomputes the statistic from block sums, so a 200,000-member cohort costs no more than its
block count. One seeded resample matrix serves every policy, metric and variant, which makes
comparisons paired. Block sums use numpy's pairwise summation; totals that reach an output
use `math.fsum` in the callers.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from respectful_offers.schemas.summary import Interval


@dataclass(frozen=True)
class Resampler:
    blocks: int
    index: np.ndarray  # [resamples, blocks] block ids drawn with replacement

    @classmethod
    def create(cls, blocks: int, resamples: int, seed: int) -> Resampler:
        if blocks < 2 or resamples < 10:
            raise ValueError("need at least 2 blocks and 10 resamples")
        rng = np.random.default_rng(seed)
        return cls(blocks, rng.integers(0, blocks, (resamples, blocks)))

    def block_of(self, hashes: np.ndarray) -> np.ndarray:
        return (hashes % np.uint64(self.blocks)).astype(np.int64)

    def sums(self, block: np.ndarray, values: np.ndarray) -> tuple[float, np.ndarray]:
        """(total, total per resample) of `values` grouped by block."""
        per = np.bincount(block, weights=values, minlength=self.blocks)
        return float(per.sum()), per[self.index].sum(axis=1)


MAX_UNDEFINED = 0.01  # more undefined resamples than this: too thin for an interval


def interval(point: float, draws: np.ndarray, digits: int = 6) -> Interval:
    finite = np.isfinite(draws)
    if not finite.any():
        raise ValueError("no finite bootstrap draws")
    if 1.0 - finite.mean() > MAX_UNDEFINED:
        raise ValueError(
            f"{1.0 - finite.mean():.1%} of bootstrap resamples are undefined (empty groups): "
            "too little data for an interval"
        )
    draws = draws[finite]
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return Interval(
        point=round(point, digits), lo=round(float(lo), digits), hi=round(float(hi), digits)
    )


def mean_interval(
    r: Resampler, block: np.ndarray, values: np.ndarray, scale: float = 1.0
) -> tuple[Interval, np.ndarray]:
    total, draws_total = r.sums(block, values)
    _, counts = r.sums(block, np.ones(len(values)))
    point = scale * total / len(values)
    draws = scale * draws_total / np.where(counts > 0, counts, np.nan)
    return interval(point, draws), draws


def ratio_interval(
    r: Resampler, block: np.ndarray, num: np.ndarray, den: np.ndarray
) -> tuple[float, np.ndarray]:
    n_total, n_draws = r.sums(block, num)
    d_total, d_draws = r.sums(block, den)
    point = n_total / d_total if d_total > 0 else float("nan")
    draws = n_draws / np.where(d_draws > 0, d_draws, np.nan)
    return point, draws


def paired(
    point_a: float, draws_a: np.ndarray, point_b: float, draws_b: np.ndarray
) -> tuple[Interval, float]:
    """Difference a − b on shared resamples, with a two-sided bootstrap p-value."""
    diff = draws_a - draws_b
    diff = diff[np.isfinite(diff)]
    centred = diff - diff.mean()
    observed = point_a - point_b
    p = float(min(1.0, max((np.abs(centred) >= abs(observed)).mean(), 1.0 / len(diff))))
    return interval(observed, diff), p


def holm(pvalues: list[float], alpha: float = 0.05) -> list[bool]:
    """Holm–Bonferroni: which hypotheses are rejected (gaps separated) at family-wise alpha."""
    order = np.argsort(pvalues, kind="mergesort")
    m = len(pvalues)
    rejected = [False] * m
    for rank, i in enumerate(order):
        if pvalues[i] <= alpha / (m - rank):
            rejected[i] = True
        else:
            break
    return rejected
