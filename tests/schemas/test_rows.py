import pytest
from pydantic import ValidationError

from respectful_offers.schemas import (
    ACTIONS,
    AuditAttributes,
    Decision,
    MemberFeatures,
    MemberState,
    Outcome,
)


def test_valid_rows_load(decision_row, state_row, features_row):
    assert Decision(**decision_row).chosen == "content_nudge"
    assert MemberState(**state_row).declined == ("content_nudge",)
    assert MemberFeatures(**features_row).cohort == "mar"
    assert AuditAttributes(msno="S1", age_band="25-34", gender="unknown").gender == "unknown"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("requested", "free_lunch"),  # not an action
        ("propensity", 0.0),
        ("propensity", 1.2),
        ("propensity", float("nan")),
        ("allowed", ("content_nudge",)),  # no_offer always allowed
        ("allowed", ("content_nudge", "no_offer")),  # order
        ("allowed", ("no_offer", "no_offer")),
        ("budget_downgraded", True),  # downgrade that kept the action
        ("face_value", -1.0),
        ("surprise", 1),  # unknown field
    ],
)
def test_bad_decisions_are_refused(decision_row, field, value):
    with pytest.raises(ValidationError):
        Decision(**{**decision_row, field: value})


def test_a_downgrade_must_change_the_action_and_no_offer_has_no_face_value(decision_row):
    ok = {
        **decision_row,
        "allowed": ACTIONS,
        "requested": "discount_1m",
        "chosen": "no_offer",
        "budget_downgraded": True,
    }
    assert Decision(**ok).budget_downgraded
    with pytest.raises(ValidationError, match="face value"):
        Decision(**{**ok, "face_value": 74.5})


@pytest.mark.parametrize(
    "declined",
    [
        ("discount_1m", "content_nudge"),  # unsorted
        ("content_nudge", "content_nudge"),  # repeated
        ("no_offer",),  # never shown
    ],
)
def test_declined_is_a_sorted_set_of_shown_actions(state_row, declined):
    with pytest.raises(ValidationError):
        MemberState(**{**state_row, "declined": declined})


@pytest.mark.parametrize(
    ("field", "value"),
    [("churn_risk", 1.01), ("plan_multiplier", 0.0), ("plan_multiplier", 1.5), ("period", 0)],
)
def test_state_ranges(state_row, field, value):
    with pytest.raises(ValidationError):
        MemberState(**{**state_row, field: value})


def test_non_renewal_earns_nothing():
    base = {
        "run_id": "r",
        "variant": "central",
        "policy": "bandit",
        "msno": "S1",
        "period": 1,
        "response": "declined",
        "renewed": False,
        "revenue": 0.0,
        "discount_cost": 0.0,
    }
    assert Outcome(**base).revenue == 0
    with pytest.raises(ValidationError, match="did not renew"):
        Outcome(**{**base, "revenue": 149.0})
    with pytest.raises(ValidationError, match="did not renew"):
        Outcome(**{**base, "discount_cost": 10.0})


def test_rows_are_deeply_immutable_and_hashable(state_row, decision_row):
    s = MemberState(**state_row)
    d = Decision(**decision_row)
    with pytest.raises(ValidationError):
        s.nudged = False  # type: ignore[misc]
    assert isinstance(s.declined, tuple) and isinstance(d.allowed, tuple)
    assert hash(s) == hash(MemberState(**state_row))


def test_features_reject_bad_values(features_row):
    for field, value in [
        ("tenure_days", -1),
        ("plan_days", 0),
        ("listening_trend_30d", -1.5),
        ("price_30d", float("inf")),
        ("cohort", "apr"),
    ]:
        with pytest.raises(ValidationError):
            MemberFeatures(**{**features_row, field: value})


def test_chosen_outside_allowed_is_refused_on_its_own(decision_row):
    # requested is allowed and the downgrade flag is consistent, so only the chosen-in-allowed
    # rule can refuse this row (N1.1 verifier: the old case tripped two rules at once)
    row = {**decision_row, "chosen": "discount_1m", "budget_downgraded": True}
    with pytest.raises(ValidationError, match="chosen action discount_1m is not in allowed"):
        Decision(**row)


def test_a_request_the_filter_removed_cannot_hide_as_a_downgrade(decision_row):
    row = {**decision_row, "requested": "plan_change", "budget_downgraded": True}
    with pytest.raises(ValidationError, match="requested action plan_change"):
        Decision(**row)


@pytest.mark.parametrize(
    ("field", "value"),
    [("propensity", True), ("budget_downgraded", "no"), ("period", 1.0), ("allowed", {"no_offer"})],
)
def test_scalars_and_sequences_are_strict(decision_row, field, value):
    with pytest.raises(ValidationError):
        Decision(**{**decision_row, field: value})


def test_sets_are_refused_whatever_the_hash_seed(state_row):
    with pytest.raises(ValidationError):
        MemberState(**{**state_row, "declined": {"discount_1m", "content_nudge"}})


def test_dates_must_be_dates(features_row):
    import datetime as dt

    for bad in (0, "2017-03-01", dt.datetime(2017, 3, 1, 12)):
        with pytest.raises(ValidationError):
            MemberFeatures(**{**features_row, "as_of": bad})
