import copy
import json

import pytest
from pydantic import ValidationError

from respectful_offers.schemas import Interval, OPEEstimate, RunSummary
from tests.schemas.conftest import FIX


@pytest.fixture
def data():
    return json.loads((FIX / "run_summary.json").read_text(encoding="utf-8"))


def test_fixture_loads(data):
    s = RunSummary.model_validate_json(json.dumps(data))
    assert s.simulated is True and len(s.policies) == 3


def _bandit(d):
    return next(p for p in d["policies"] if p["policy"] == "bandit")


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda d: d.update(simulated=False), "simulated"),
        (lambda d: _bandit(d)["retained_per_1000"].update(lo=999.0), "lo"),
        (lambda d: _bandit(d).update(cost_per_incremental_retained=None), "exactly when"),
        (lambda d: d["policies"].append(copy.deepcopy(_bandit(d))), "one PolicySummary"),
        (lambda d: d["ope"][0].update(policy="segment_oracle"), "not in policies"),
        (lambda d: d["comparisons"][0].update(b="rule_following_baseline"), "not in policies"),
        (lambda d: d["holdout_check"].update(optimistic={"point": 0, "lo": 0, "hi": 0}), "variant"),
        (lambda d: _bandit(d)["violations"].pop("R8"), "R8"),
        (lambda d: d.update(finished_at="2026-11-21T06:00:00Z"), "before"),
        (lambda d: d.update(started_at="2026-11-21T07:00:00"), "timezone"),
        (
            lambda d: _bandit(d)["spend"].append(
                {"period": 2, "budget": 1e6, "face_value_committed": 2e6, "realised_cost": 1.0}
            ),
            "R4",
        ),
        (lambda d: d["ope"].append(copy.deepcopy(d["ope"][0])), "one OPE row"),
        (lambda d: d.update(variants=["central", "central"]), "variants must not repeat"),
        (lambda d: d["comparisons"][0].update(b="bandit"), "two different"),
        (lambda d: d["comparisons"][0]["diff"].update(lo=-1.0), "spans 0"),
        (lambda d: _bandit(d)["cost_per_incremental_retained"].update(lo=-5.0), "negative"),
        (lambda d: d["disparity"].update(S0000001={}), "disparity"),
        (
            lambda d: d["disparity"].update(
                {"bandit.offer_rate.city": {"x": d["disparity"]["gender"]["male"]}}
            ),
            "disparity",
        ),
        (
            lambda d: d["disparity"].update({"rogue.offer_rate.gender": d["disparity"]["gender"]}),
            "disparity",
        ),
        (
            lambda d: d["disparity"].update({"bandit.revenue.gender": d["disparity"]["gender"]}),
            "disparity",
        ),
    ],
)
def test_inconsistent_summaries_are_refused(data, mutate, match):
    mutate(data)
    with pytest.raises(ValidationError, match=match):
        RunSummary.model_validate_json(json.dumps(data))


def test_cost_ratio_must_be_absent_without_incremental_members(data):
    nob = next(p for p in data["policies"] if p["policy"] == "no_offer")
    nob["cost_per_incremental_retained"] = {"point": 1.0, "lo": 1.0, "hi": 1.0}
    with pytest.raises(ValidationError, match="exactly when"):
        RunSummary.model_validate_json(json.dumps(data))


def test_ope_covered_must_agree_with_the_interval():
    base = {
        "policy": "bandit",
        "variant": "central",
        "estimator": "dr",
        "value": {"point": 1.0, "lo": 0.5, "hi": 1.5},
        "effective_sample_size": 10.0,
    }
    assert OPEEstimate(**base, oracle=1.2, covered=True).covered
    with pytest.raises(ValidationError, match="covered"):
        OPEEstimate(**base, oracle=2.0, covered=True)


def test_interval_order_and_finiteness():
    with pytest.raises(ValidationError):
        Interval(point=1.0, lo=2.0, hi=1.5)
    with pytest.raises(ValidationError):
        Interval(point=float("inf"), lo=0.0, hi=1.0)


def test_equal_summaries_dump_identical_bytes(data):
    a = RunSummary.model_validate_json(json.dumps(data))
    v = _bandit(data)["violations"]
    _bandit(data)["violations"] = dict(reversed(list(v.items())))
    b = RunSummary.model_validate_json(json.dumps(data))
    assert a == b and a.model_dump_json() == b.model_dump_json()


def test_summaries_pickle_and_deepcopy(data):
    import pickle

    s = RunSummary.model_validate_json(json.dumps(data))
    assert pickle.loads(pickle.dumps(s)) == s and copy.deepcopy(s) == s


def test_spend_is_bounded_over_the_horizon_not_per_period():
    """A plan change is charged in full when sent and paid in later periods (D-32, D-38)."""
    import json

    from harness_lib import ROOT
    from respectful_offers.schemas.summary import RunSummary

    d = json.loads(
        (ROOT / "tests" / "fixtures" / "v1" / "run_summary.json").read_text(encoding="utf-8")
    )
    b = next(p for p in d["policies"] if p["policy"] == "bandit")
    b["spend"] = [
        {"period": 1, "budget": 1e6, "face_value_committed": 900.0, "realised_cost": 100.0},
        {"period": 2, "budget": 1e6, "face_value_committed": 0.0, "realised_cost": 300.0},
    ]
    RunSummary.model_validate_json(json.dumps(d))  # 300 > 0 in period 2, fine over the horizon
    b["spend"][1]["realised_cost"] = 900.0
    with pytest.raises(ValidationError, match="over the horizon"):
        RunSummary.model_validate_json(json.dumps(d))
    b["spend"][1]["realised_cost"] = 1.0
    b["retained_per_1000_at_risk"] = None  # too few members at risk: null, never a fake interval
    RunSummary.model_validate_json(json.dumps(d))
