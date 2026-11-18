"""E4.2: this repo against EvalKit's public API (EVK-03, EVK-04).

These are the tests EvalKit's canary runs against every EvalKit release candidate (its
registry row `tests=auto` collects every test file here that imports `evalkit`). Offline: no
network, no keys. They import only names in EvalKit's public contract.
"""

import ast
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from harness_lib import ROOT

pytestmark = pytest.mark.contract

if os.environ.get("CI"):
    import evalkit  # noqa: F401  # CI installs every extra: a missing EvalKit is a failure
evalkit_gates = pytest.importorskip("evalkit.gates", reason="the `evalkit` extra is not installed")
evalkit_metrics = pytest.importorskip("evalkit.metrics")

sys.path.insert(0, str(ROOT / "scripts"))
import gate  # noqa: E402  # the E4.1 local gate, kept as a test oracle
from respectful_offers.metrics1 import MetricsError, validate_metrics1  # noqa: E402
from tests.evalkit import test_gate as local_gate_tests  # noqa: E402
from tests.evalkit import test_metrics1 as local_metrics_tests  # noqa: E402

METRICS = ROOT / "results" / "kkbox" / "metrics.json"
GATES = ROOT / "configs" / "gates.yaml"

# EvalKit 0.3 public names this repo may use (EvalKit scripts/check_public_api.py, PUBLIC)
PUBLIC = {
    "evalkit": {"__version__"},
    "evalkit.metrics": {
        "Metric",
        "MetricsError",
        "MetricsSummary",
        "Provenance",
        "load_metrics",
        "parse_metrics",
        "safe_text",
        "SCHEMA",
    },
    "evalkit.gates": {
        "EXIT_FAIL",
        "EXIT_INPUT",
        "EXIT_PASS",
        "GateReport",
        "GateRow",
        "disparity_gap",
        "evaluate",
        "load_gates",
        "parse_gates",
        "render_text",
        "run_gate",
    },
}

# Where the two validators disagree, by decision (D-53), reported to EvalKit (D-61 rule 3)
KNOWN_DISAGREEMENTS = {"member-id-shaped"}


def _doc() -> dict:
    return json.loads(METRICS.read_text(encoding="utf-8"))


def _ek_rows(report) -> list[tuple]:
    out = []
    for r in report.rows:
        d = r.as_dict()
        # EvalKit shows a disparity row as {attr: "max - min"}; the local gate as {disparity: attr}
        labels = {
            ("disparity" if v == "max - min" else k): (k if v == "max - min" else v)
            for k, v in d["labels"].items()
        }
        out.append(
            (
                d["metric"],
                tuple(sorted(labels.items())),
                d["bound"],
                d["op"],
                d["result"],
            )
        )
    return sorted(out)


def _local_rows(rows: list[dict]) -> list[tuple]:
    out = []
    for r in rows:
        # EvalKit shows label values as text: booleans as true/false, integers as digits
        labels = {
            k: (str(v).lower() if isinstance(v, bool) else str(v)) for k, v in r["labels"].items()
        }
        out.append(
            (
                r["metric"],
                tuple(sorted(labels.items())),
                r["bound"],
                r["op"],
                r["status"],
            )
        )
    return sorted(out)


def _both(tmp_path: Path, doc: dict, config: dict | None = None):
    m = tmp_path / "metrics.json"
    m.write_text(json.dumps(doc), encoding="utf-8")
    g = GATES
    if config is not None:
        g = tmp_path / "gates.yaml"
        g.write_text(yaml.safe_dump(config), encoding="utf-8")
    ek = evalkit_gates.run_gate(m, g)
    local = gate.run(m, g)
    return ek, local


def test_evalkit_loads_the_committed_metrics_and_sees_a_simulation():
    s = evalkit_metrics.load_metrics(METRICS)
    assert s.simulated is True and s.project == "respectful-offers"
    assert len(s.metrics) == len(_doc()["metrics"])


def test_evalkit_gate_passes_the_committed_run_with_both_disparity_warnings():
    report = evalkit_gates.run_gate(METRICS, GATES)
    assert report.exit_code == evalkit_gates.EXIT_PASS and report.simulated is True
    warns = [r for r in report.rows if r.result == "warn"]
    assert sorted(r.labels["policy"] for r in warns) == ["bandit", "rule_following_baseline"]
    assert all(r.metric == "group.offer_rate" for r in warns)
    assert not [r for r in report.rows if r.result == "fail"]


def test_evalkit_gate_and_the_local_gate_agree_row_by_row(tmp_path):
    ek, local = _both(tmp_path, _doc())
    assert ek.exit_code == local["exit"] == 0
    assert _ek_rows(ek) == _local_rows(local["rows"])


def _planted_metric_changes():
    def r1_bandit(d):
        local_gate_tests.first(d, "violations", rule="R1", policy="bandit", variant="central")[
            "value"
        ] = 1

    def r1_status_quo(d):
        local_gate_tests.first(d, "violations", rule="R1", policy="status_quo", variant="central")[
            "value"
        ] += 1

    def claim_below_zero(d):
        local_gate_tests.first(
            d,
            "diff.incremental_retained_per_1000_ntd",
            a="bandit",
            b="rule_following_baseline",
            variant="conservative",
        )["ci_low"] = -0.01

    def ece_warn(d):
        local_gate_tests.first(d, "churn.ece")["value"] = 0.2

    def true_label_is_not_one(d):  # a respectful flag written as 1 matches no gate: exit 2
        for m in d["metrics"]:
            if m["name"] == "violations" and m["labels"]["respectful"] is True:
                m["labels"]["respectful"] = 1

    return [
        (r1_bandit, 1),
        (r1_status_quo, 0),
        (claim_below_zero, 1),
        (ece_warn, 0),
        (true_label_is_not_one, 2),
    ]


PLANTED = _planted_metric_changes()


@pytest.mark.parametrize(("change", "expected"), PLANTED, ids=[f.__name__ for f, _ in PLANTED])
def test_both_gates_agree_on_every_planted_metric_defect(tmp_path, change, expected):
    doc = _doc()
    change(doc)
    ek, local = _both(tmp_path, doc)
    assert ek.exit_code == local["exit"] == expected
    if expected != 2:  # on bad input EvalKit lists the rows it read before the error; we list none
        assert _ek_rows(ek) == _local_rows(local["rows"])


def test_both_gates_refuse_a_malformed_gates_file_and_a_duplicate_metric(tmp_path):
    ek, local = _both(
        tmp_path, _doc(), {"gates": [{"metric": "violations", "op": [">="], "value": 0}]}
    )
    assert ek.exit_code == local["exit"] == 2
    dup = _doc()
    dup["metrics"].append(copy.deepcopy(dup["metrics"][0]))
    ek, local = _both(tmp_path, dup)
    assert ek.exit_code == local["exit"] == 2


def _cases(test) -> list:
    """The parametrize cases of an E4.1 test, so both suites plant the same defects."""
    return list(test.pytestmark[0].args[1])


BAD_GATES = [g for g, _ in _cases(local_gate_tests.test_bad_gates_are_errors_never_passes)]


@pytest.mark.parametrize("gates", BAD_GATES, ids=[str(i) for i in range(len(BAD_GATES))])
def test_both_gates_refuse_every_planted_gate_defect_with_exit_2(tmp_path, gates):
    ek, local = _both(tmp_path, _doc(), {"gates": gates})
    assert ek.exit_code == evalkit_gates.EXIT_INPUT
    assert local["exit"] == 2


VALIDATOR_CASES = _cases(local_metrics_tests.test_the_validator_refuses_each_planted_defect)


@pytest.mark.parametrize(("doc", "needle"), VALIDATOR_CASES, ids=[n for _, n in VALIDATOR_CASES])
def test_both_validators_agree_on_every_planted_defect(doc, needle):
    try:
        validate_metrics1(copy.deepcopy(doc))
        ours = "accept"
    except MetricsError:
        ours = "refuse"
    try:
        evalkit_metrics.parse_metrics(json.dumps(doc))
        theirs = "accept"
    except (evalkit_metrics.MetricsError, ValueError):
        theirs = "refuse"
    if needle in KNOWN_DISAGREEMENTS:
        assert (ours, theirs) == ("refuse", "accept"), "D-53 changed: update the decision"
    else:
        assert ours == theirs == "refuse"


def test_both_validators_accept_the_committed_file():
    validate_metrics1(_doc())
    evalkit_metrics.parse_metrics(METRICS.read_text(encoding="utf-8"))


def _evalkit_imports() -> list[tuple[str, str, str]]:
    found = []
    for base in ("src", "scripts", "tests", "demo"):
        for path in (ROOT / base).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("evalkit"):
                    found += [
                        (str(path.relative_to(ROOT)), node.module or "", a.name) for a in node.names
                    ]
                elif isinstance(node, ast.Import):
                    found += [
                        (str(path.relative_to(ROOT)), a.name, "")
                        for a in node.names
                        if a.name.startswith("evalkit")
                    ]
    return found


def _evalkit_uses_in_this_file() -> list[tuple[str, str]]:
    """Modules reached with importorskip, and every attribute read through their aliases."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "importorskip"
        ):
            arg = node.value.args[0]
            assert isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            for target in node.targets:
                assert isinstance(target, ast.Name)
                aliases[target.id] = arg.value
    uses = [(m, "") for m in aliases.values()]
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in aliases
        ):
            uses.append((aliases[node.value.id], node.attr))
    return uses


def test_this_repo_imports_only_evalkits_public_api():
    uses = _evalkit_uses_in_this_file()
    assert {m for m, _ in uses} == {"evalkit.gates", "evalkit.metrics"}
    bad_use = [(m, n) for m, n in uses if m not in PUBLIC or (n and n not in PUBLIC[m])]
    assert not bad_use, bad_use
    bad = [
        (f, m, n) for f, m, n in _evalkit_imports() if m not in PUBLIC or (n and n not in PUBLIC[m])
    ]
    assert not bad, bad
    files = {f for f, _, _ in _evalkit_imports()}
    assert files == {"tests/evalkit/test_evalkit_contract.py"}  # never the runtime package


def test_the_package_runs_without_evalkit(tmp_path):
    """`offers metrics` must not need the optional extra: block the import and run it."""
    code = (
        "import sys; sys.modules['evalkit'] = None\n"
        "from respectful_offers.cli import main\n"
        f"raise SystemExit(main(['metrics', '--out', {str(tmp_path / 'm.json')!r}]))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    assert (tmp_path / "m.json").read_text(encoding="utf-8") == METRICS.read_text(encoding="utf-8")
