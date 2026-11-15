"""Disjoint Bayesian linear Thompson sampling (Tech Spec §6.4, D-6, A2.5).

For each action a there is a Gaussian posterior N(μₐ, Σₐ) over weights θₐ, with the reward
modelled as y = xᵀθₐ + ε, ε ~ N(0, σ²), where y is the period's net revenue as a share of the
member's price (so every action's value is on the same 0..1 scale and price never decides
the argmax on its own). Prior: θₐ ~ N(0, I/λ).

Choosing: draw θₐ for every allowed action and take the highest xᵀθₐ; `no_offer` wins when
every offer's sampled value is below it (R5). Because the posteriors are independent, each
member's sampled scores are independent normals Sₐ ~ N(mₐ = xᵀμₐ, sₐ² = xᵀΣₐx), so the
probability of each action winning, the policy's exact choice distribution, is a
one-dimensional integral:

    P(a wins) = ∫ Π_{b≠a} Φ((t − m_b)/s_b) dΦ((t − mₐ)/sₐ)

computed per member by a Stieltjes trapezoid rule on a grid built from every allowed action's
own nodes mₐ + sₐ·g (`ts_integration_nodes` per action), so each normal's steep part is
resolved at its own scale; worst error about 6e-4 at 32 nodes against adaptive quadrature
(D-35). No Monte Carlo: a member's probabilities depend only on the posterior and its own
context and allowed set. They are mixed with a uniform floor over the allowed actions
(`ts_support_floor`, so every allowed action keeps at least that probability, BND-03), then
the action is sampled from them. Those probabilities are the logged propensities and the
target probabilities for OPE.

Training happens in simulation on the training cohort (posteriors update after each period);
the posterior is then frozen for evaluation (BND-02).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, ClassVar

import numpy as np
import pandas as pd
from scipy.special import ndtr

from respectful_offers.policy.baselines import Policy, View
from respectful_offers.policy.respect import check_context_columns

DYNAMIC = ("nudged", "declined")  # state flags the bandit sees, built each period
MIN_NODES, MAX_NODES = 8, 256  # integration nodes per action (memory and time stay bounded)
MAX_FLOOR = 0.05  # four allowed actions at most: the mixture keeps 1 − 4·floor of the posterior
# risk_band is skipped: churn_risk already carries it, and the bands are the simulator's


def static_context(
    features: pd.DataFrame, churn_risk: np.ndarray, columns: tuple[str, ...]
) -> tuple[np.ndarray, list[str]]:
    """The member-level part of the context, from allow-listed decision features only."""
    df = features.copy()
    df["churn_risk"] = churn_risk
    cols: list[str] = []
    blocks = []
    for c in columns:
        if c in DYNAMIC:
            continue
        if c == "risk_band":
            continue  # captured by churn_risk; bands are the simulator's, not the policy's
        if c not in df.columns:
            raise KeyError(f"decision feature {c!r} is not in the features table")
        blocks.append(df[c].astype(float).to_numpy())
        cols.append(c)
    x = np.column_stack(blocks) if blocks else np.zeros((len(df), 0))
    if not np.isfinite(x).all():
        raise ValueError("decision features must be finite (no NaN or infinity)")
    return x, cols


@dataclass
class Posterior:
    columns: list[str]
    mean: np.ndarray  # feature means for standardising static columns
    scale: np.ndarray
    mu: np.ndarray  # [4, d]
    precision: np.ndarray  # [4, d, d]
    b: np.ndarray  # [4, d]
    noise_variance: float
    trained_periods: int = 0
    learning_curve: list[dict[str, float]] = field(default_factory=list)
    frozen: bool = False
    integration_nodes: int = 32
    support_floor: float = 0.001

    @property
    def dim(self) -> int:
        return self.mu.shape[1]

    def cov(self) -> np.ndarray:
        return np.linalg.inv(self.precision)

    def to_json(self) -> str:
        return json.dumps(
            {
                "columns": self.columns,
                "mean": self.mean.tolist(),
                "scale": self.scale.tolist(),
                "mu": self.mu.tolist(),
                "precision": self.precision.tolist(),
                "b": self.b.tolist(),
                "noise_variance": self.noise_variance,
                "trained_periods": self.trained_periods,
                "learning_curve": self.learning_curve,
                "frozen": self.frozen,
                "integration_nodes": self.integration_nodes,
                "support_floor": self.support_floor,
            },
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, text: str) -> Posterior:
        d = json.loads(text)
        return cls(
            d["columns"],
            np.array(d["mean"]),
            np.array(d["scale"]),
            np.array(d["mu"]),
            np.array(d["precision"]),
            np.array(d["b"]),
            float(d["noise_variance"]),
            int(d["trained_periods"]),
            list(d["learning_curve"]),
            bool(d["frozen"]),
            int(d["integration_nodes"]),
            float(d["support_floor"]),
        )

    def copy(self) -> Posterior:
        return Posterior.from_json(self.to_json())


class ThompsonBandit(Policy):
    name = "bandit"
    respectful: ClassVar[bool] = True

    def __init__(
        self,
        static: np.ndarray,
        columns: list[str],
        decision_features: tuple[str, ...],
        *,
        prior_precision: float,
        noise_variance: float,
        integration_nodes: int = 32,
        support_floor: float = 0.001,
        posterior: Posterior | None = None,
    ) -> None:
        check_context_columns(
            [*columns, *(c for c in DYNAMIC if c in decision_features)], decision_features
        )
        for name, v in (("prior precision", prior_precision), ("noise variance", noise_variance)):
            if (
                isinstance(v, bool)
                or not isinstance(v, int | float)
                or not (math.isfinite(v) and v > 0)
            ):
                raise ValueError(f"{name} must be a positive finite number")
        if isinstance(integration_nodes, bool) or not isinstance(integration_nodes, int):
            raise ValueError("integration_nodes must be an integer")
        if not MIN_NODES <= integration_nodes <= MAX_NODES:
            raise ValueError(f"integration_nodes must lie in [{MIN_NODES}, {MAX_NODES}]")
        if not (isinstance(support_floor, float) and 0.0 < support_floor <= MAX_FLOOR):
            raise ValueError(f"support_floor must lie in (0, {MAX_FLOOR}]")
        self._use_dynamic = tuple(c for c in DYNAMIC if c in decision_features)
        self.context_columns = (*columns, *self._use_dynamic)
        d = static.shape[1] + 1 + (1 if "nudged" in self._use_dynamic else 0)
        d += 3 if "declined" in self._use_dynamic else 0
        if posterior is None:
            if static.ndim != 2 or static.shape[1] != len(columns):
                raise ValueError("the static context must have one column per named column")
            mean = static.mean(axis=0) if static.size else np.zeros(len(columns))
            scale = static.std(axis=0) if static.size else np.zeros(len(columns))
            scale = np.where(scale > 0, scale, 1.0)
            posterior = Posterior(
                list(columns),
                mean,
                scale,
                np.zeros((4, d)),
                np.tile(np.eye(d) * prior_precision, (4, 1, 1)),
                np.zeros((4, d)),
                noise_variance,
                integration_nodes=integration_nodes,
                support_floor=support_floor,
            )
        else:
            # a copy: two bandits never share (and silently rewrite) one posterior
            posterior = posterior.copy()
            if list(posterior.columns) != list(columns):
                raise ValueError(
                    f"the posterior was trained on columns {posterior.columns}, not {list(columns)}"
                )
            if posterior.dim != d or len(posterior.mean) != len(columns):
                raise ValueError("the posterior's dimension does not match the context")
        self.posterior = posterior
        self._cov = posterior.cov()
        self._explored = 0
        self._decisions = 0

    @property
    def learning(self) -> bool:
        return not self.posterior.frozen

    # -- context ---------------------------------------------------------------------------
    def context_for(self, features: pd.DataFrame, churn_risk: np.ndarray) -> np.ndarray:
        """The static context in the posterior's own column order: the only safe way to build
        an evaluation context for a trained bandit."""
        x, cols = static_context(features, churn_risk, tuple(self.posterior.columns))
        if cols != list(self.posterior.columns):
            raise ValueError(f"context columns {cols} differ from {self.posterior.columns}")
        return x

    def features(self, view: View) -> np.ndarray:
        p = self.posterior
        n = len(view.allowed)
        ctx = view.context
        if ctx.ndim != 2 or ctx.shape != (n, len(p.columns)):
            raise ValueError(
                f"the context must be [{n}, {len(p.columns)}] for columns {p.columns}, "
                f"got {list(ctx.shape)}"
            )
        if not np.isfinite(ctx).all():
            raise ValueError("the context must be finite")
        z = (ctx - p.mean) / p.scale if ctx.size else np.zeros((n, 0))
        parts = [np.ones((n, 1)), z]
        if "nudged" in self._use_dynamic:
            parts.append(view.nudged.astype(float)[:, None])
        if "declined" in self._use_dynamic:
            parts.append(view.declined[:, 1:].astype(float))
        return np.hstack(parts)

    # -- policy ----------------------------------------------------------------------------
    def _moments(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        mean = x @ self.posterior.mu.T  # [n, 4]
        var = np.einsum("nd,ade,ne->na", x, self._cov, x)
        return mean, np.sqrt(np.maximum(var, 1e-12))

    def probabilities(self, view: View) -> np.ndarray:
        mean, sd = self._moments(self.features(view))
        p = self.posterior
        probs = win_probabilities(mean, sd, view.allowed, p.integration_nodes)
        # floor after normalising, as a mixture with uniform-over-allowed, so the floor holds
        k = view.allowed.sum(axis=1, keepdims=True)
        f = p.support_floor
        probs = np.where(view.allowed, (1.0 - k * f) * probs + f, 0.0)
        self._greedy = np.where(view.allowed, mean, -np.inf).argmax(axis=1)
        return probs

    def choose(self, probs: np.ndarray, u: np.ndarray) -> np.ndarray:
        picks = super().choose(probs, u)
        self._explored += int((picks != self._greedy).sum())
        self._decisions += len(picks)
        return picks

    def reset_counts(self) -> None:
        self._explored = self._decisions = 0

    def preference(self, view: View, probs: np.ndarray) -> np.ndarray:
        mean, _ = self._moments(self.features(view))  # posterior mean, not the sampled draw
        return mean

    def priority(self, view: View, requested: np.ndarray) -> np.ndarray:
        mean, _ = self._moments(self.features(view))
        best_free = np.where(view.free[None, :] & view.allowed, mean, -np.inf).max(axis=1)
        gain = (mean[np.arange(len(requested)), requested] - best_free) * view.price
        return np.where(np.isfinite(gain), gain, 0.0)

    # -- learning --------------------------------------------------------------------------
    def observe(self, view: View, chosen: np.ndarray, revenue: np.ndarray) -> None:
        if self.posterior.frozen:
            return
        x = self.features(view)
        if not np.isfinite(revenue).all():
            raise ValueError("rewards must be finite")
        y = revenue / np.where(view.price > 0, view.price, 1.0)
        p = self.posterior
        for a in range(4):
            m = chosen == a
            if not m.any():
                continue
            xa = x[m]
            p.precision[a] += xa.T @ xa / p.noise_variance
            p.b[a] += xa.T @ y[m] / p.noise_variance
            p.mu[a] = np.linalg.solve(p.precision[a], p.b[a])
        p.trained_periods += 1
        self._cov = p.cov()

    def freeze(self) -> None:
        """Permanent: the flag travels with the posterior's JSON, and a frozen posterior never
        updates again (BND-02)."""
        self.posterior.frozen = True

    def summary(self) -> dict[str, Any]:
        """Exploration rate: share of decisions since the last reset whose drawn action differs
        from the posterior-mean best, pooled over periods (R6)."""
        return {
            "exploration_rate": self._explored / self._decisions if self._decisions else None,
            "trained_periods": self.posterior.trained_periods,
            "frozen": self.posterior.frozen,
        }


def win_probabilities(
    mean: np.ndarray, sd: np.ndarray, allowed: np.ndarray, nodes: int
) -> np.ndarray:
    """P(action a has the highest draw) for independent normals, per member, [n, 4] (D-35)."""
    n = len(mean)
    out = np.zeros((n, 4))
    if n == 0:
        return out
    g = np.sinh(np.linspace(-np.arcsinh(40.0), np.arcsinh(40.0), nodes)) * (9.0 / 40.0)
    chunk = max(1, 400_000 // (4 * nodes))
    for lo in range(0, n, chunk):
        hi = min(lo + chunk, n)
        m, s, al = mean[lo:hi], sd[lo:hi], allowed[lo:hi]
        pts = m[:, :, None] + s[:, :, None] * g[None, None, :]
        pts = np.where(al[:, :, None], pts, np.nan).reshape(hi - lo, -1)
        pts = np.sort(pts, axis=1)  # NaN (disallowed actions' nodes) sort last
        top = np.nanmax(pts, axis=1, keepdims=True)
        pts = np.where(np.isnan(pts), top, pts)
        edge = np.full((hi - lo, 1), np.inf)
        grid = np.concatenate([-edge, pts, edge], axis=1)  # [c, G]
        cdf = ndtr((grid[:, :, None] - m[:, None, :]) / s[:, None, :])  # [c, G, 4]
        cdf = np.where(al[:, None, :], cdf, 1.0)
        for a in range(4):
            others = np.prod(np.delete(cdf, a, axis=2), axis=2)
            d_cdf = np.diff(cdf[:, :, a], axis=1)
            out[lo:hi, a] = (d_cdf * 0.5 * (others[:, 1:] + others[:, :-1])).sum(axis=1)
    out = np.where(allowed, np.maximum(out, 0.0), 0.0)
    total = out.sum(axis=1, keepdims=True)
    # one allowed action, or rounding: fall back to uniform over the allowed set
    uniform = allowed / allowed.sum(axis=1, keepdims=True)
    return np.where(total > 0, out / np.where(total > 0, total, 1.0), uniform)


def greedy_value(
    bandit: ThompsonBandit, cohort: Any, sim: Any, variant: str, risk_threshold: float
) -> float:
    """Exact period-1 expected net revenue per member of acting greedily on the posterior mean,
    from a fresh state (no declines, no nudges): the learning curve's y-axis (BND-05)."""
    from respectful_offers.policy.respect import allowed_actions
    from respectful_offers.sim.response import Tables, expected_reward

    t = Tables.from_config(sim, variant)
    n = len(cohort)
    allowed = allowed_actions(
        in_holdout=np.zeros(n, bool),
        churn_risk=cohort.churn_risk,
        nudged=np.zeros(n, bool),
        declined=np.zeros((n, 4), bool),
        risk_threshold=risk_threshold,
    )
    ctx = bandit.context_for(cohort.features, cohort.churn_risk)
    view = View(
        1,
        1,
        allowed,
        cohort.churn_risk,
        cohort.price,
        np.zeros(n, bool),
        np.zeros((n, 4), bool),
        ctx,
        risk_threshold,
        np.array([True, True, False, False]),
        cohort.base,
        cohort.segment,
        t,
    )
    mean, _ = bandit._moments(bandit.features(view))
    pick = np.where(allowed, mean, -np.inf).argmax(axis=1)
    ev = expected_reward(cohort.base, cohort.cells, cohort.price, t)
    return float(ev[np.arange(n), pick].mean())


def train_bandit(
    cohort: Any,
    sim: Any,
    variant: str,
    *,
    decision_features: tuple[str, ...],
    risk_threshold: float,
    budget_per_1000: float,
    periods: int,
    epochs: int,
    prior_precision: float,
    noise_variance: float,
    integration_nodes: int = 32,
    support_floor: float = 0.001,
    seed: int,
) -> ThompsonBandit:
    """Simulated online training on the training cohort: `epochs` passes of an H-period rollout,
    updating after every period, then freeze. Records the learning curve (BND-02, BND-05)."""
    from respectful_offers.policy.rollout import rollout

    static, cols = static_context(cohort.features, cohort.churn_risk, decision_features)
    bandit = ThompsonBandit(
        static,
        cols,
        decision_features,
        prior_precision=prior_precision,
        noise_variance=noise_variance,
        integration_nodes=integration_nodes,
        support_floor=support_floor,
    )
    curve = [{"period": 0, "value": greedy_value(bandit, cohort, sim, variant, risk_threshold)}]
    for epoch in range(epochs):
        rollout(
            bandit,
            cohort,
            sim,
            variant,
            periods=periods,
            risk_threshold=risk_threshold,
            budget_per_1000=budget_per_1000,
            seed=seed + 1000 * (epoch + 1),
            run_id=f"train-{variant}-{epoch}",
            context=static,
        )
        curve.append(
            {
                "period": bandit.posterior.trained_periods,
                "value": greedy_value(bandit, cohort, sim, variant, risk_threshold),
            }
        )
    bandit.posterior.learning_curve = curve
    bandit.freeze()
    bandit.reset_counts()
    return bandit
