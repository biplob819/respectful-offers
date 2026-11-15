import json

import pytest
from pydantic import ValidationError

import respectful_offers.schemas as schemas
from respectful_offers.schemas import RunSummary, load_run_config, load_simulator_config
from tests.schemas.conftest import FIX

# Every schema named in Tech Spec §3, written out by hand (L-4: never loop over __all__).
SPEC_NAMES = [
    "Action",
    "ACTIONS",
    "Response",
    "PolicyName",
    "MemberFeatures",
    "AuditAttributes",
    "MemberState",
    "Decision",
    "Outcome",
    "Interval",
    "PeriodSpend",
    "PolicySummary",
    "OPEEstimate",
    "Comparison",
    "ChurnReport",
    "RunSummary",
    "RunConfig",
    "SimulatorConfig",
]


@pytest.mark.contract
def test_every_tech_spec_schema_is_exported():
    missing = [n for n in SPEC_NAMES if not hasattr(schemas, n) or n not in schemas.__all__]
    assert missing == []


def test_fixtures_round_trip_losslessly_and_stably():
    s = RunSummary.model_validate_json((FIX / "run_summary.json").read_text(encoding="utf-8"))
    once = s.model_dump_json()
    twice = RunSummary.model_validate_json(once).model_dump_json()
    assert once == twice and RunSummary.model_validate_json(once) == s
    for cfg in (
        load_run_config(FIX / "run_config.yaml"),
        load_simulator_config(FIX / "simulator.yaml"),
    ):
        dumped = cfg.model_dump_json()
        assert type(cfg).model_validate_json(dumped).model_dump_json() == dumped


def test_schema_version_is_required_and_major_checked():
    data = json.loads((FIX / "run_summary.json").read_text(encoding="utf-8"))
    for bad in ("2.0", "1", "v1.0"):
        with pytest.raises(ValidationError):
            RunSummary.model_validate_json(json.dumps({**data, "schema_version": bad}))
    data.pop("schema_version")
    with pytest.raises(ValidationError, match="schema_version"):
        RunSummary.model_validate_json(json.dumps(data))
    assert RunSummary.model_validate_json(json.dumps({**data, "schema_version": "1.3"}))
