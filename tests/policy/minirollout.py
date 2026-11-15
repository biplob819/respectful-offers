"""A tiny three-period rollout used to test the auditor against real and broken filters."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from respectful_offers.schemas.rows import ACTIONS

Filter = Callable[..., np.ndarray]


def run(
    filter_fn: Filter,
    n: int = 400,
    periods: int = 3,
    seed: int = 0,
    threshold: float = 0.5,
    policy: str = "bandit",
):
    rng = np.random.default_rng(seed)
    msno = np.array([f"S{i:05d}" for i in range(n)])
    # a 0.05 grid, so risks land exactly on the threshold and boundary mutants show
    risk = np.round(rng.uniform(0, 1, n) * 20) / 20
    holdout = rng.uniform(0, 1, n) < 0.1
    declined = np.zeros((n, 4), dtype=bool)
    nudged = np.zeros(n, dtype=bool)
    d_rows, o_rows = [], []
    for t in range(1, periods + 1):
        allowed = filter_fn(
            in_holdout=holdout,
            churn_risk=risk,
            nudged=nudged.copy(),
            declined=declined.copy(),
            risk_threshold=threshold,
        )
        # prefer commercial offers so any gap in the filter shows up
        weights = allowed * np.array([0.1, 1.0, 3.0, 3.0])
        probs = weights / weights.sum(axis=1, keepdims=True)
        chosen = np.array([rng.choice(4, p=p) for p in probs])
        accept = rng.uniform(0, 1, n) < 0.3
        for i in range(n):
            a = ACTIONS[chosen[i]]
            pol = "holdout" if holdout[i] else policy
            resp = "not_shown" if a == "no_offer" else ("accepted" if accept[i] else "declined")
            d_rows.append(
                {"policy": pol, "variant": "central", "msno": msno[i], "period": t, "chosen": a}
            )
            o_rows.append(
                {
                    "policy": pol,
                    "variant": "central",
                    "msno": msno[i],
                    "period": t,
                    "response": resp,
                }
            )
            if resp == "declined":
                declined[i, chosen[i]] = True
            if a == "content_nudge":
                nudged[i] = True
    return (
        pd.DataFrame(d_rows),
        pd.DataFrame(o_rows),
        pd.Series(risk, index=msno),
        pd.Series(holdout, index=msno),
    )
