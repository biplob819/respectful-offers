"""E4.3 MON-01 on EvalKit 0.4: drift and calibration at the D-56 severities, and the ledgers."""

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from harness_lib import ROOT
from respectful_offers.churn.model import MODEL_FEATURES
from respectful_offers.metrics1 import validate_metrics1
from respectful_offers.monitor.ledger import EXPERIMENTS, RUNS, run_drift, summarise_drift

pytest.importorskip("evalkit.drift", reason="the `evalkit` extra is not installed")

MON = ROOT / "results" / "kkbox" / "monitor"
REF = MON / "reference-2017-02.metrics.json"
PERIOD = MON / "period-2017-03.metrics.json"
CONFIG = ROOT / "configs" / "drift.yaml"
EVALKIT = str(Path(sys.executable).parent / "evalkit")  # the extra's console script


@pytest.fixture(scope="module")
def fresh(tmp_path_factory):
    out = tmp_path_factory.mktemp("drift")
    return out, run_drift(REF, PERIOD, out, config=CONFIG)


def test_the_drift_config_is_the_owner_ruling():
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert cfg["severity"] == {"psi": "warn", "calibration": "warn", "bins": "warn"}  # D-56
    assert cfg["calibration"]["binning"] == "equal-width"  # EvalKit OWNER D-73
    assert (cfg["psi_warn"], cfg["psi_alarm"]) == (0.1, 0.25)


def same(a, b, where="$"):
    """Exactly equal, except floats, which agree to 1e-9 relative: EvalKit's bootstrap sums
    differ in the last digits across CPUs and platforms (CI: Linux, Windows, macOS)."""
    if isinstance(a, float) or isinstance(b, float):
        assert isinstance(a, int | float) and isinstance(b, int | float), where
        assert math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12), (where, a, b)
    elif isinstance(a, dict):
        assert isinstance(b, dict) and a.keys() == b.keys(), where
        for k in a:
            same(a[k], b[k], f"{where}.{k}")
    elif isinstance(a, list):
        assert isinstance(b, list) and len(a) == len(b), where
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            same(x, y, f"{where}[{i}]")
    else:
        assert a == b, (where, a, b)  # every level, status, count, hash and name exactly


@pytest.mark.parametrize("name", ["drift-ref.json", "drift.metrics.json"])
def test_the_committed_drift_inputs_reproduce_byte_for_byte(fresh, name):
    out, _ = fresh
    assert (out / name).read_bytes() == (MON / name).read_bytes()


def test_the_committed_drift_check_reproduces_on_any_platform(fresh):
    out, _ = fresh
    same(
        json.loads((out / "drift.json").read_text(encoding="utf-8")),
        json.loads((MON / "drift.json").read_text(encoding="utf-8")),
    )


def test_every_model_feature_gets_a_psi_and_the_bins_are_compared(fresh):
    _, got = fresh
    report = got["report"]
    assert {f["feature"] for f in report.features} == set(MODEL_FEATURES)
    assert report.calibration["bins_status"] == "compared"  # equal-width bins align
    assert all(f["severity"] == "warn" for f in report.features)


def test_drift_and_calibration_warn_and_never_block_a_period(fresh):
    _, got = fresh
    s = summarise_drift(got["report"])
    flagged = [r for r in s["rows"] if r["level"] in ("warn", "alarm")]
    assert flagged  # the March calibration did move (a real finding, reported)
    assert s["exit_code"] == 0  # every alarm is at warn severity


def test_the_same_alarms_at_fail_severity_would_block(tmp_path):
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    cfg["severity"] = {"psi": "fail", "calibration": "fail", "bins": "fail"}
    path = tmp_path / "drift.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    got = run_drift(REF, PERIOD, tmp_path / "out", config=path)
    assert got["report"].exit_code == 1  # the severity, not the data, makes D-56's choice


def test_the_emitted_drift_metrics_are_valid_real_aggregates():
    doc = json.loads((MON / "drift.metrics.json").read_text(encoding="utf-8"))
    validate_metrics1(doc)
    assert doc["simulated"] is False  # real member features, scores and labels
    names = {m["name"] for m in doc["metrics"]}
    assert {"drift.psi", "drift.brier_delta", "drift.ece_delta"} <= names


@pytest.mark.parametrize("ledger", [RUNS, EXPERIMENTS], ids=lambda p: p.name)
def test_each_committed_ledger_chain_verifies(ledger):
    out = subprocess.run(
        [EVALKIT, "history", "verify", str(ledger), "--chain-only"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert out.returncode == 0, out.stdout + out.stderr


def _lines(path):
    return [json.loads(x) for x in (ROOT / path).read_text(encoding="utf-8").splitlines() if x]


def test_the_run_history_holds_the_published_run_and_its_drift():
    runs = {e["run_id"] for e in _lines(RUNS) if e["kind"] == "run"}
    summary = json.loads((ROOT / "results" / "kkbox" / "summary.json").read_text("utf-8"))
    period = json.loads(PERIOD.read_text(encoding="utf-8"))
    assert {summary["run_id"], f"{period['run_id']}-drift"} <= runs


def test_every_committed_challenge_is_opened_before_and_closed_in_the_experiment_ledger():
    entries = _lines(EXPERIMENTS)
    for path in sorted((ROOT / "results" / "kkbox" / "challenge").glob("*/challenge.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        led = record["experiment_ledger"]
        assert led and led["ledger"] == EXPERIMENTS.as_posix()
        mine = [e for e in entries if e.get("id") == led["experiment"]]
        kinds = [e["kind"] for e in mine]
        assert kinds == ["experiment_opened", "experiment_closed"], kinds
        assert mine[0]["change"] == record["challenger"]
        assert mine[1]["verdict"] == led["verdict"]


@pytest.mark.parametrize("feature", MODEL_FEATURES)
def test_a_planted_shift_in_one_feature_alarms_that_feature_and_no_other(tmp_path, feature):
    doc = json.loads(PERIOD.read_text(encoding="utf-8"))
    rows = [
        m
        for m in doc["metrics"]
        if m["name"] == "drift.feature_share" and m["labels"]["feature"] == feature
    ]
    target = min(rows, key=lambda m: m["value"])  # 30 points of share into the rarest bin
    others = [m for m in rows if m is not target]
    total = sum(m["value"] for m in others)
    for m in others:
        m["value"] = round(m["value"] * (1 - 0.3 / total), 9)
    target["value"] = round(1 - sum(m["value"] for m in others), 9)
    path = tmp_path / "shifted.metrics.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    report = run_drift(REF, path, tmp_path / "out", config=CONFIG)["report"]
    levels = {f["feature"]: f["level"] for f in report.features}
    assert levels.pop(feature) == "alarm"
    assert set(levels.values()) == {"ok"}


def test_this_repo_has_no_psi_code_of_its_own():
    import ast

    for path in (ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {n.name.lower() for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert not {n for n in names if "psi" in n}, path  # OWNER D-50: EvalKit computes PSI
