"""Regression tests for the N1.1 verifier's round-2 findings."""

import copy
import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from respectful_offers.schemas import (
    FEATURES,
    MEMBER_STATES,
    ConfigError,
    ContractError,
    Decision,
    MemberFeatures,
    RunSummary,
    check_frame,
    load_run_config,
    load_simulator_config,
    load_summary,
    row_from_record,
)
from respectful_offers.schemas.config import protected_name
from tests.schemas.conftest import FIX
from tests.schemas.test_contracts import features_frame, state_frame


def test_arrow_backed_dates_and_action_lists_are_checked_not_crashed():
    pytest.importorskip("pyarrow")
    df = features_frame()
    df["as_of"] = pd.Series([dt.date(2017, 3, 1)] * 2, dtype="date32[pyarrow]")
    check_frame(df, FEATURES, "features")
    df["as_of"] = pd.Series(["2017-03-01"] * 2, dtype="string[pyarrow]")
    with pytest.raises(ContractError, match="as_of"):
        check_frame(df, FEATURES, "features")
    st = state_frame()
    import pyarrow as pa

    st["declined"] = pd.Series([["content_nudge"]], dtype=pd.ArrowDtype(pa.list_(pa.string())))
    check_frame(st, MEMBER_STATES, "rollout")


def test_rows_from_parquet_records_validate_with_the_strict_models():
    record = {
        "msno": "S1",
        "cohort": "mar",
        "as_of": pd.Timestamp("2017-03-01"),
        "tenure_days": np.int64(400),
        "auto_renew": np.bool_(True),
        "cancels_90d": np.int64(0),
        "listening_trend_30d": np.float64(-0.3),
        "price_30d": np.float64(149.0),
        "plan_days": np.int64(30),
        "churn_label": np.bool_(False),
    }
    assert row_from_record(MemberFeatures, record).as_of == dt.date(2017, 3, 1)
    d = row_from_record(
        Decision,
        {
            "run_id": "r",
            "variant": "central",
            "policy": "bandit",
            "msno": "S1",
            "period": np.int64(1),
            "allowed": np.array(["no_offer", "content_nudge"], dtype=object),
            "requested": "content_nudge",
            "chosen": "content_nudge",
            "propensity": np.float64(0.5),
            "budget_downgraded": np.bool_(False),
            "face_value": np.float64(0.0),
        },
    )
    assert d.allowed == ("no_offer", "content_nudge")
    with pytest.raises(ValidationError):
        row_from_record(MemberFeatures, {**record, "as_of": pd.Timestamp("2017-03-01 12:00")})


def test_summaries_load_from_files_in_json_mode():
    assert load_summary(FIX / "run_summary.json").simulated is True


def test_yaml_dates_name_their_key(tmp_path):
    text = (FIX / "run_config.yaml").read_text(encoding="utf-8")
    text = text.replace('holdout_salt: "respectful-offers-v1"', "holdout_salt: 2001-12-14")
    p = tmp_path / "c.yaml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match=r"holdout_salt: date is not plain YAML data"):
        load_run_config(p)


@pytest.mark.parametrize(
    "name", ["registered_via_code", "registeredVia", "userGender", "ageBand", "age_band2", "SEX"]
)
def test_multi_word_and_camel_case_protected_names_are_caught(name):
    assert protected_name(name)


@pytest.mark.parametrize("name", ["average_spend", "usage_minutes", "listening_trend_30d", "page"])
def test_words_that_merely_contain_a_protected_name_pass(name):
    assert not protected_name(name)


@pytest.fixture
def data():
    return json.loads((FIX / "run_summary.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda d: d["comparisons"].append(copy.deepcopy(d["comparisons"][0])), "one comparison"),
        (
            lambda d: d["comparisons"].append(
                {**copy.deepcopy(d["comparisons"][0]), "a": "status_quo", "b": "bandit"}
            ),
            "one comparison",
        ),
        (
            lambda d: d["policies"][2]["spend"].append(copy.deepcopy(d["policies"][2]["spend"][0])),
            "one spend row",
        ),
        (lambda d: d.update(simulated=1), "boolean true"),
        (lambda d: d["disparity"].update(age_band={}), "disparity"),
    ],
)
def test_round_two_summary_gaps(data, mutate, match):
    mutate(data)
    with pytest.raises(ValidationError, match=match):
        RunSummary.model_validate_json(json.dumps(data))


@pytest.mark.parametrize("name", ["", "central ", "Central"])
def test_variant_names_are_clean(tmp_path, name):
    sim = yaml.safe_load((FIX / "simulator.yaml").read_text(encoding="utf-8"))
    sim["variants"][name] = sim["variants"].pop("central")
    p = tmp_path / "s.yaml"
    p.write_text(yaml.safe_dump(sim), encoding="utf-8")
    with pytest.raises(ConfigError, match="variants"):
        load_simulator_config(p)
