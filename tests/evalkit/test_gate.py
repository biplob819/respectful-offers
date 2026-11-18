"""E4.1: release gates in EvalKit's gates format (EVK-02, OWNER D-52)."""

import copy
import json
import subprocess
import sys

import pytest
import yaml

from harness_lib import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import gate

METRICS = ROOT / "results" / "kkbox" / "metrics.json"
GATE_JSON = ROOT / "results" / "kkbox" / "gate.json"
GATES = ROOT / "configs" / "gates.yaml"


@pytest.fixture
def doc() -> dict:
    return json.loads(METRICS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def config() -> dict:
    return yaml.safe_load(GATES.read_text(encoding="utf-8"))


def first(doc, name, **labels):
    return next(
        m
        for m in doc["metrics"]
        if m["name"] == name and all(m.get("labels", {}).get(k) == v for k, v in labels.items())
    )


def test_the_gates_file_holds_the_owners_severities(config):
    by = {}
    for g in config["gates"]:
        by.setdefault(g["metric"], []).append(g)
    assert by["violations"][0]["labels"] == {"respectful": True}
    assert by["violations"][0]["value"] == 0 and by["violations"][0]["op"] == "=="
    sev = {m: {g.get("severity", "fail") for g in gs} for m, gs in by.items()}
    assert sev["violations"] == {"fail"}
    assert sev["diff.incremental_retained_per_1000_ntd"] == {"fail"}
    assert sev["separated.incremental_retained_per_1000_ntd"] == {"fail"}
    assert sev["holdout_check"] == {"fail"}
    assert sev["group.offer_rate"] == {"warn"} and by["group.offer_rate"][0]["value"] == 0.10
    assert by["group.offer_rate"][0]["disparity"] == "age_band"
    assert sev["churn.auc"] == {"warn"} and by["churn.auc"][0]["value"] == 0.80
    assert sev["churn.ece"] == {"warn"} and by["churn.ece"][0]["value"] == 0.05
    assert sev["ope.covered"] == {"warn"}


def test_the_published_run_passes_with_the_disparity_warnings_listed(doc, config):
    code, rows = gate.evaluate(doc, config)
    assert code == 0
    warns = [r for r in rows if r["status"] == "warn"]
    assert {r["labels"]["policy"] for r in warns} == {"bandit", "rule_following_baseline"}
    assert all(r["metric"] == "group.offer_rate" for r in warns)
    claim = [r for r in rows if r["metric"] == "diff.incremental_retained_per_1000_ntd"]
    assert {r["labels"]["variant"] for r in claim} == {"conservative", "central", "optimistic"}
    viol = [r for r in rows if r["metric"] == "violations"]
    assert viol and all(r["labels"]["respectful"] is True for r in viol)


def test_a_respect_violation_fails_but_only_on_a_respectful_policy(doc, config):
    bad = copy.deepcopy(doc)
    first(bad, "violations", rule="R1", policy="bandit", variant="central")["value"] = 1
    code, rows = gate.evaluate(bad, config)
    assert code == 1
    failed = [r for r in rows if r["status"] == "fail"]
    assert [(r["metric"], r["labels"]["rule"], r["labels"]["policy"]) for r in failed] == [
        ("violations", "R1", "bandit")
    ]
    sq = copy.deepcopy(doc)
    first(sq, "violations", rule="R1", policy="status_quo", variant="central")["value"] += 1
    assert gate.evaluate(sq, config)[0] == 0


def test_a_claim_whose_lower_bound_drops_below_zero_fails(doc, config):
    bad = copy.deepcopy(doc)
    m = first(
        bad,
        "diff.incremental_retained_per_1000_ntd",
        a="bandit",
        b="rule_following_baseline",
        variant="conservative",
    )
    m["ci_low"] = -0.01
    code, rows = gate.evaluate(bad, config)
    assert code == 1
    assert any(r["status"] == "fail" and r["bound"] == "lower" for r in rows)


def test_a_warn_only_failure_exits_zero(doc, config):
    bad = copy.deepcopy(doc)
    first(bad, "churn.ece")["value"] = 0.2
    code, rows = gate.evaluate(bad, config)
    assert code == 0 and any(r["metric"] == "churn.ece" and r["status"] == "warn" for r in rows)


@pytest.mark.parametrize(
    ("gates", "needle"),
    [
        ([{"metric": "no_such_metric", "op": "==", "value": 0}], "matches no metric"),
        (
            [{"metric": "violations", "labels": {"policy": "nobody"}, "op": "==", "value": 0}],
            "matches no metric",
        ),
        ([{"metric": "violations", "op": "!=", "value": 0}], "unknown op"),
        ([{"metric": "churn.ece", "bound": "upper", "op": "<=", "value": 1}], "no interval"),
        (
            [
                {
                    "metric": "group.offer_rate",
                    "disparity": "age_band",
                    "bound": "upper",
                    "op": "<=",
                    "value": 1,
                }
            ],
            "group n",
        ),
        ([{"metric": "violations", "op": "==", "value": 0, "colour": "red"}], "unknown keys"),
        ([{"metric": "ope.covered", "op": ">=", "value": True}], "booleans"),
        ([{"metric": "violations", "op": "==", "value": 0, "severity": "info"}], "severity"),
        ([{"metric": "violations", "op": [">="], "value": 0}], "unknown op"),
        (
            [{"metric": "group.offer_rate", "disparity": ["age_band"], "op": "<=", "value": 1}],
            "disparity must",
        ),
        ([{"metric": "churn.ece", "op": "<=", "value": float("inf")}], "not finite"),
        ([{"metric": "churn.ece", "op": "<=", "value": float("nan")}], "not finite"),
    ],
)
def test_bad_gates_are_errors_never_passes(doc, gates, needle):
    with pytest.raises(gate.GateError, match=needle):
        gate.evaluate(doc, {"gates": gates})


def test_a_true_label_never_matches_the_integer_one(doc):
    assert not gate._matches({"labels": {"respectful": 1}}, {"respectful": True})
    assert gate._matches({"labels": {"respectful": True}}, {"respectful": True})


def _cli(*args, cwd=ROOT):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gate.py"), *map(str, args)],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def test_gate_json_is_written_on_every_exit_path(tmp_path, doc):
    out = tmp_path / "gate.json"
    ok = _cli(METRICS, "--out", out)
    assert ok.returncode == 0 and ok.stdout.startswith("simulated: true")
    assert json.loads(out.read_text(encoding="utf-8"))["simulated"] is True

    bad = copy.deepcopy(doc)
    first(bad, "violations", rule="R2", policy="bandit", variant="optimistic")["value"] = 3
    f = tmp_path / "bad.json"
    f.write_text(json.dumps(bad), encoding="utf-8")
    failed = _cli(f, "--out", out)
    assert failed.returncode == 1
    assert json.loads(out.read_text(encoding="utf-8"))["verdict"] == "fail"

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    err = _cli(broken, "--out", out)
    assert err.returncode == 2
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["verdict"] == "error" and written["exit"] == 2 and written["error"]

    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps({**doc, "extra": 1}), encoding="utf-8")
    err = _cli(invalid, "--out", out)
    assert err.returncode == 2 and json.loads(out.read_text(encoding="utf-8"))["simulated"] is True


def test_the_committed_gate_json_is_current():
    out = _cli(METRICS, "--check", GATE_JSON)
    assert out.returncode == 0, out.stdout + out.stderr
    assert json.loads(GATE_JSON.read_text(encoding="utf-8"))["verdict"] == "pass"


def test_ci_runs_the_export_and_the_gate():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "offers metrics --check" in ci
    # E4.2: EvalKit's own gate runs in CI; scripts/gate.py stays as the test oracle
    assert "evalkit gate results/kkbox/metrics.json --config configs/gates.yaml" in ci


def test_a_malformed_gates_file_exits_2_with_gate_json(tmp_path):
    cfg = tmp_path / "gates.yaml"
    cfg.write_text('gates:\n  - {metric: violations, op: [">="], value: 0}\n', encoding="utf-8")
    out = tmp_path / "gate.json"
    res = _cli(METRICS, "--config", cfg, "--out", out)
    assert res.returncode == 2
    assert json.loads(out.read_text(encoding="utf-8"))["verdict"] == "error"


def test_every_variant_and_respectful_policy_is_gated_by_name(config):
    claim = [g for g in config["gates"] if g["metric"].endswith("_per_1000_ntd")]
    for name in ("diff.", "separated."):
        variants = {g["labels"]["variant"] for g in claim if g["metric"].startswith(name)}
        assert variants == {"conservative", "central", "optimistic"}
    disp = {g["labels"]["policy"] for g in config["gates"] if g.get("disparity")}
    assert disp == {"bandit", "rule_following_baseline"}
    assert all("*" not in g.get("labels", {}).values() for g in config["gates"])
