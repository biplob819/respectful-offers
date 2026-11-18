"""E4.3 MON-01 outcome checks at the OWNER D-56 severities, on metrics-1 documents."""

import copy
import json

import pytest

from harness_lib import ROOT
from respectful_offers.monitor.outcomes import outcome_alarms

REAL = json.loads((ROOT / "results" / "kkbox" / "metrics.json").read_text(encoding="utf-8"))


def _edit(doc, name, value=None, **labels):
    out = copy.deepcopy(doc)
    hit = 0
    for m in out["metrics"]:
        if m["name"] == name and all(m.get("labels", {}).get(k) == v for k, v in labels.items()):
            for k, v in (value or {}).items():
                m[k] = v
            hit += 1
    assert hit, (name, labels)
    return out


def _checks(result):
    return {a["check"] for a in result["alarms"]}


def test_the_committed_run_passes_every_outcome_check_against_itself():
    got = outcome_alarms(REAL, REAL)
    assert got["fail"] is False and got["alarms"] == [] and got["not_checked"] == []
    assert got["simulated"] is True


def test_without_a_baseline_cost_and_disparity_are_not_checked_never_passed():
    got = outcome_alarms(None, REAL)
    assert got["not_checked"] == ["cost", "disparity"] and got["fail"] is False


def test_a_planted_respect_violation_fails():
    bad = _edit(REAL, "violations", {"value": 1}, policy="bandit", variant="central", rule="R1")
    got = outcome_alarms(REAL, bad)
    assert got["fail"] and _checks(got) == {"respect"}


def test_the_status_quo_breaking_rules_is_not_a_respect_alarm():
    sq = _edit(REAL, "violations", {"value": 5}, policy="status_quo", rule="R1")
    assert outcome_alarms(REAL, sq)["fail"] is False


@pytest.mark.parametrize(
    "change",
    [{"ci_low": -0.01}],
)
def test_the_claim_lost_by_its_lower_bound_fails(change):
    lab = {"a": "bandit", "b": "rule_following_baseline", "variant": "conservative"}
    bad = _edit(REAL, "diff.incremental_retained_per_1000_ntd", change, **lab)
    got = outcome_alarms(REAL, bad)
    assert _checks(got) == {"claim"} and got["alarms"][0]["labels"]["variant"] == "conservative"


def test_the_claim_lost_by_holm_fails():
    lab = {"a": "bandit", "b": "rule_following_baseline", "variant": "optimistic"}
    bad = _edit(REAL, "separated.incremental_retained_per_1000_ntd", {"value": False}, **lab)
    assert _checks(outcome_alarms(REAL, bad)) == {"claim"}


def test_a_missing_claim_row_counts_as_lost():
    bad = copy.deepcopy(REAL)
    bad["metrics"] = [
        m
        for m in bad["metrics"]
        if not (
            m["name"] == "diff.incremental_retained_per_1000_ntd"
            and m["labels"]["variant"] == "central"
            and m["labels"]["a"] == "bandit"
            and m["labels"]["b"] == "rule_following_baseline"
        )
    ]
    assert _checks(outcome_alarms(REAL, bad)) == {"claim"}


def _cost(doc, policy="bandit", variant="central"):
    return next(
        m
        for m in doc["metrics"]
        if m["name"] == "cost_per_incremental_retained"
        and m["labels"] == {"policy": policy, "variant": variant}
    )


def test_cost_up_more_than_a_quarter_with_its_interval_clear_fails():
    b = _cost(REAL)["value"]
    bad = _edit(
        REAL,
        "cost_per_incremental_retained",
        {"value": 1.30 * b, "ci_low": 1.05 * b, "ci_high": 1.6 * b},
        policy="bandit",
        variant="central",
    )
    got = outcome_alarms(REAL, bad)
    assert _checks(got) == {"cost"}


@pytest.mark.parametrize(
    "rise, low",
    [
        (1.30, 0.95),  # up 30%, but the interval still reaches the baseline value
        (1.20, 1.10),  # clear of it, but up by only 20%
    ],
)
def test_cost_that_is_not_significantly_worse_passes(rise, low):
    b = _cost(REAL)["value"]
    ok = _edit(
        REAL,
        "cost_per_incremental_retained",
        {"value": rise * b, "ci_low": low * b, "ci_high": 1.6 * b},
        policy="bandit",
        variant="central",
    )
    assert "cost" not in _checks(outcome_alarms(REAL, ok))


def _gap_edit(doc, widen):
    out = copy.deepcopy(doc)
    rows = [
        m
        for m in out["metrics"]
        if m["name"] == "group.offer_rate"
        and m["labels"].get("policy") == "bandit"
        and "age_band" in m["labels"]
    ]
    top = max(rows, key=lambda m: m["value"])
    top["value"] += widen
    top["ci_high"] += widen
    return out


def test_an_age_band_gap_wider_by_more_than_005_fails():
    assert _checks(outcome_alarms(REAL, _gap_edit(REAL, 0.06))) == {"disparity"}


def test_an_age_band_gap_wider_by_less_passes():
    assert outcome_alarms(REAL, _gap_edit(REAL, 0.04))["fail"] is False


def _cli(*argv):
    from respectful_offers import cli

    return cli.main(["monitor", "check", *argv])


def test_monitor_check_exits_0_on_a_pass_1_on_a_fail_and_2_on_bad_input(tmp_path):
    good = ROOT / "results" / "kkbox" / "metrics.json"
    assert _cli("--period", str(good), "--baseline", str(good)) == 0
    bad = _edit(REAL, "violations", {"value": 2}, policy="bandit", variant="central", rule="R2")
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    out = tmp_path / "alarms.json"
    assert _cli("--period", str(path), "--out", str(out)) == 1
    assert json.loads(out.read_text(encoding="utf-8"))["alarms"][0]["check"] == "respect"
    broken = tmp_path / "broken.json"
    broken.write_text('{"schema_version": "metrics-1"}', encoding="utf-8")
    assert _cli("--period", str(broken)) == 2
    assert _cli("--period", str(tmp_path / "missing.json")) == 2


def test_a_file_with_no_outcomes_is_bad_input_never_a_pass(tmp_path):
    from respectful_offers.monitor.outcomes import OutcomeError

    drift_input = ROOT / "results" / "kkbox" / "monitor" / "reference-2017-02.metrics.json"
    doc = json.loads(drift_input.read_text(encoding="utf-8"))
    with pytest.raises(OutcomeError, match="no violations or claim rows"):
        outcome_alarms(None, doc)
    with pytest.raises(OutcomeError):
        outcome_alarms(doc, REAL)  # nor as a baseline
    assert _cli("--period", str(drift_input)) == 2
