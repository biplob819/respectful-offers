import numpy as np
import pandas as pd
import pytest

from harness_lib import ROOT
from respectful_offers.policy.cohort import build_cohort
from respectful_offers.schemas import load_simulator_config


@pytest.fixture(scope="session")
def sim():
    return load_simulator_config(ROOT / "configs" / "simulator.yaml")


@pytest.fixture(scope="session")
def cohort(sim):
    """A hand-built March cohort: 4,000 members with a spread of risks and trends."""
    rng = np.random.default_rng(4)
    n = 4000
    msno = [f"S{i:06d}" for i in range(n)]
    risk = np.clip(rng.beta(1.2, 12, n), 0.001, 0.95)
    feats = pd.DataFrame(
        {
            "msno": msno,
            "cohort": "mar",
            "as_of": pd.Timestamp("2017-03-01").date(),
            "tenure_days": rng.integers(30, 3000, n),
            "auto_renew": rng.uniform(size=n) < 0.85,
            "cancels_90d": rng.poisson(0.1, n),
            "listening_trend_30d": rng.normal(0, 0.3, n).clip(-1, 5),
            "price_30d": rng.choice([99.0, 129.0, 149.0], n),
            "plan_days": 30,
            "churn_label": False,
        }
    )
    scores = pd.DataFrame({"msno": msno, "churn_risk": risk})
    return build_cohort(scores, feats, sim, "central", seed=7)
