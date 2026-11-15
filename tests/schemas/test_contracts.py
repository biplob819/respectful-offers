import datetime as dt

import pandas as pd
import pytest

from respectful_offers.schemas import (
    AUDIT_ATTRIBUTES,
    CONTRACTS,
    DECISIONS,
    FEATURES,
    MEMBER_STATES,
    OUTCOMES,
    AuditAttributes,
    ContractError,
    Decision,
    MemberFeatures,
    MemberState,
    Outcome,
    check_frame,
)

# Independent list taken from Tech Spec §3, so a drifting contract or model both fail (L-4).
SPEC_COLUMNS = {
    "features": [
        "msno",
        "cohort",
        "as_of",
        "tenure_days",
        "auto_renew",
        "cancels_90d",
        "listening_trend_30d",
        "price_30d",
        "plan_days",
        "churn_label",
    ],
    "audit_attributes": ["msno", "age_band", "gender"],
    "member_states": [
        "msno",
        "period",
        "active",
        "in_holdout",
        "churn_risk",
        "risk_band",
        "trend_band",
        "declined",
        "nudged",
        "price_30d",
        "plan_multiplier",
    ],
    "decisions": [
        "run_id",
        "variant",
        "policy",
        "msno",
        "period",
        "allowed",
        "requested",
        "chosen",
        "propensity",
        "budget_downgraded",
        "face_value",
    ],
    "outcomes": [
        "run_id",
        "variant",
        "policy",
        "msno",
        "period",
        "response",
        "renewed",
        "revenue",
        "discount_cost",
    ],
}
MODELS = {
    "features": MemberFeatures,
    "audit_attributes": AuditAttributes,
    "member_states": MemberState,
    "decisions": Decision,
    "outcomes": Outcome,
}


@pytest.mark.contract
@pytest.mark.parametrize("name", sorted(SPEC_COLUMNS))
def test_contract_columns_match_the_model_and_the_spec(name):
    assert list(CONTRACTS[name].names) == SPEC_COLUMNS[name]
    assert list(MODELS[name].model_fields) == SPEC_COLUMNS[name]


def features_frame():
    return pd.DataFrame(
        {
            "msno": ["S1", "S2"],
            "cohort": ["mar", "mar"],
            "as_of": [dt.date(2017, 3, 1)] * 2,
            "tenure_days": [10, 400],
            "auto_renew": [True, False],
            "cancels_90d": [0, 2],
            "listening_trend_30d": [-0.2, 0.1],
            "price_30d": [149.0, 99.0],
            "plan_days": [30, 30],
            "churn_label": [False, True],
        }
    )


def test_valid_frame_passes():
    check_frame(features_frame(), FEATURES, "features")


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda df: df.drop(columns=["price_30d"]), "missing column"),
        (lambda df: df.assign(gender=["f", "m"]), "unexpected column"),
        (lambda df: df.assign(tenure_days=["10", "400"]), "tenure_days has dtype"),
        (lambda df: df.assign(price_30d=[149.0, None]), "price_30d has 1 null"),
        (lambda df: df.assign(plan_days=[30, 0]), "plan_days has 0.0 below minimum"),
        (lambda df: df.assign(cohort=["mar", "apr"]), "cohort has values"),
        (lambda df: df.assign(auto_renew=[1, 0]), "auto_renew has dtype"),
        (lambda df: df.assign(listening_trend_30d=[float("inf"), 0.0]), "NaN or infinite"),
        (lambda df: df.assign(msno=["S1", 7]), "non-string"),
    ],
)
def test_contract_errors_name_stage_and_column(mutate, match):
    with pytest.raises(ContractError, match=match) as exc:
        check_frame(mutate(features_frame()), FEATURES, "features-stage")
    assert "features-stage" in str(exc.value)


def test_action_list_columns_are_checked():
    df = pd.DataFrame({c: [] for c in DECISIONS.names})
    check_frame(df, DECISIONS, "empty")
    row = {
        "run_id": "r",
        "variant": "central",
        "policy": "bandit",
        "msno": "S1",
        "period": 1,
        "allowed": [("no_offer", "teleport")],
        "requested": "no_offer",
        "chosen": "no_offer",
        "propensity": 1.0,
        "budget_downgraded": False,
        "face_value": 0.0,
    }
    with pytest.raises(ContractError, match="sequences of actions"):
        check_frame(pd.DataFrame(row), DECISIONS, "rollout")


def test_every_contract_is_registered():
    assert set(CONTRACTS) == set(SPEC_COLUMNS)
    assert {MEMBER_STATES.name, OUTCOMES.name, AUDIT_ATTRIBUTES.name} <= set(CONTRACTS)


@pytest.mark.parametrize(
    "bad",
    [
        [pd.Timedelta(1, "D")] * 2,
        [dt.date(2017, 3, 1), dt.time(1, 2)],
        [pd.Timestamp("2017-03-01 12:30")] * 2,
        [pd.Timestamp("2017-03-01", tz="UTC")] * 2,
        ["2017-03-01"] * 2,
    ],
)
def test_date_columns_hold_calendar_dates_only(bad):
    with pytest.raises(ContractError, match="as_of"):
        check_frame(features_frame().assign(as_of=bad), FEATURES, "features")


def test_naive_midnight_timestamps_are_dates():
    df = features_frame().assign(as_of=pd.to_datetime(["2017-03-01", "2017-03-01"]))
    check_frame(df, FEATURES, "features")


def state_frame(**over):
    row = {
        "msno": "S1",
        "period": 2,
        "active": True,
        "in_holdout": False,
        "churn_risk": 0.6,
        "risk_band": "high",
        "trend_band": "stable",
        "declined": [("content_nudge",)],
        "nudged": True,
        "price_30d": 149.0,
        "plan_multiplier": 1.0,
    }
    row.update(over)
    return pd.DataFrame({k: v if isinstance(v, list) else [v] for k, v in row.items()})


@pytest.mark.parametrize(
    "declined",
    [
        [("no_offer",)],
        [("plan_change", "content_nudge")],
        [("content_nudge", "content_nudge")],
        [{"content_nudge": 1}],
        [{"content_nudge"}],
    ],
)
def test_declined_column_enforces_the_respect_shape(declined):
    with pytest.raises(ContractError, match="declined"):
        check_frame(state_frame(declined=declined), MEMBER_STATES, "rollout")


def decision_frame(**over):
    row = {
        "run_id": "r",
        "variant": "central",
        "policy": "bandit",
        "msno": "S1",
        "period": 1,
        "allowed": [("no_offer", "content_nudge")],
        "requested": "content_nudge",
        "chosen": "content_nudge",
        "propensity": 0.5,
        "budget_downgraded": False,
        "face_value": 0.0,
    }
    row.update(over)
    return pd.DataFrame({k: v if isinstance(v, list) else [v] for k, v in row.items()})


@pytest.mark.respect
@pytest.mark.parametrize(
    ("over", "match"),
    [
        ({"allowed": [()]}, "allowed not an ordered set"),
        ({"allowed": [("content_nudge",)]}, "allowed not an ordered set"),
        ({"chosen": "discount_1m", "budget_downgraded": True}, "chosen outside allowed"),
        ({"requested": "plan_change", "budget_downgraded": True}, "requested outside allowed"),
        ({"budget_downgraded": True}, "downgrade flag"),
    ],
)
def test_decision_tables_enforce_the_respect_rules(over, match):
    check_frame(decision_frame(), DECISIONS, "rollout")
    with pytest.raises(ContractError, match=match):
        check_frame(decision_frame(**over), DECISIONS, "rollout")


def test_outcome_tables_refuse_revenue_without_renewal():
    df = pd.DataFrame(
        {
            "run_id": ["r"],
            "variant": ["central"],
            "policy": ["bandit"],
            "msno": ["S1"],
            "period": [1],
            "response": ["declined"],
            "renewed": [False],
            "revenue": [149.0],
            "discount_cost": [0.0],
        }
    )
    with pytest.raises(ContractError, match="did not renew"):
        check_frame(df, OUTCOMES, "rollout")


def test_duplicated_columns_and_frozen_registry():
    df = features_frame()
    df.insert(1, "msno", df["msno"], allow_duplicates=True)
    with pytest.raises(ContractError, match="duplicated column"):
        check_frame(df, FEATURES, "features")
    with pytest.raises(TypeError):
        CONTRACTS["x"] = FEATURES  # type: ignore[index]
