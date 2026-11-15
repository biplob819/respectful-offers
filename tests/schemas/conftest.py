import datetime as dt

import pytest

from harness_lib import ROOT

FIX = ROOT / "tests" / "fixtures" / "v1"


@pytest.fixture
def decision_row():
    return {
        "run_id": "r1",
        "variant": "central",
        "policy": "bandit",
        "msno": "S000001",
        "period": 1,
        "allowed": ("no_offer", "content_nudge"),
        "requested": "content_nudge",
        "chosen": "content_nudge",
        "propensity": 0.6,
        "budget_downgraded": False,
        "face_value": 0.0,
    }


@pytest.fixture
def state_row():
    return {
        "msno": "S000001",
        "period": 2,
        "active": True,
        "in_holdout": False,
        "churn_risk": 0.62,
        "risk_band": "high",
        "trend_band": "declining",
        "declined": ("content_nudge",),
        "nudged": True,
        "price_30d": 149.0,
        "plan_multiplier": 1.0,
    }


@pytest.fixture
def features_row():
    return {
        "msno": "S000001",
        "cohort": "mar",
        "as_of": dt.date(2017, 3, 1),
        "tenure_days": 400,
        "auto_renew": True,
        "cancels_90d": 0,
        "listening_trend_30d": -0.3,
        "price_30d": 149.0,
        "plan_days": 30,
        "churn_label": False,
    }
