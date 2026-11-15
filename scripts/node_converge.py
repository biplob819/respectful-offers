#!/usr/bin/env python3
"""Run every gate for a build node and report all of them, even after a failure.

Usage:
    python scripts/node_converge.py W0.1          # run all 12 gates
    python scripts/node_converge.py --self-test   # prove every gate can fail

Exit 0 only when no gate FAILs. SKIP means the gate had nothing to check yet
(for example no golden tests exist before node A2.7); SKIP never hides a failure.

Gates:
   1 claims-work     at least one capability row of the node is building or green
   2 eligibility     graph has no cycles and nothing builds ahead of its dependencies
   3 proofs          every row has a proof for all five dimensions, and each proof resolves
   4 ruff            uv run ruff check .
   5 pyright         uv run pyright
   6 pytest          unit, property and contract tests
   7 golden          pytest -m golden
   8 respect-ope     pytest -m "respect or ope" (independent auditor, OPE validation)
   9 safety          pytest -m safety, plus the secret, raw-data and publish scans
  10 build           uv build, install the wheel in a clean venv, run the smoke commands
  11 changed-tests   if source changed since node start, tests changed too
  12 records         changelog entry, criteria cover every row, RUN-STATE.md exists
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import data_scan
import secret_scan
from harness_lib import (
    PROOF_DIMENSIONS,
    ROOT,
    SPECS_DIR,
    Cap,
    HarnessError,
    Node,
    eligibility_problems,
    load_catalog,
    load_graph,
    parse_catalog,
    parse_graph,
    spec_dir,
)

# Commands run inside the clean venv by gate 10. Node B2.2 adds `doctor` and `report --example`.
SMOKE_COMMANDS: list[list[str]] = [["offers", "--version"]]
PYTEST_UNIT_MARKERS = "not golden and not respect and not ope and not safety"
NA_MIN_REASON = 10
NA_FORBIDDEN = {"logical"}  # every capability needs at least a real unit test


@dataclass
class Result:
    status: str  # PASS | FAIL | SKIP
    detail: str


@dataclass
class Ctx:
    node: str
    root: Path
    nodes: dict[str, Node]
    caps: list[Cap]
    specs: Path


def _run(cmd: list[str], cwd: Path, timeout: int = 900) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        return 127, str(exc)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    return p.returncode, (p.stdout + p.stderr).strip()


def _tail(text: str, n: int = 12) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-n:])


# ---------- gates ----------


def gate_claims_work(ctx: Ctx) -> Result:
    rows = [c for c in ctx.caps if c.node == ctx.node]
    active = [c for c in rows if c.status in ("building", "green")]
    if not rows:
        return Result("FAIL", f"{ctx.node} has no catalog rows")
    if not active:
        return Result(
            "FAIL", f"no row of {ctx.node} is building or green (run node_start --mark-building)"
        )
    return Result("PASS", f"{len(active)}/{len(rows)} rows active")


def gate_eligibility(ctx: Ctx) -> Result:
    problems = eligibility_problems(ctx.nodes, ctx.caps)
    return Result("FAIL", "; ".join(problems)) if problems else Result("PASS", "eligible")


PROOF_RE = re.compile(r'^(?P<path>[^›"]+)›"(?P<test>[^"]+)"$')


def _test_functions(path: Path) -> dict[str, bool]:
    """Map each real test function name to whether it is skipped.

    Only `def test_*` at module level or inside a `Test*` class count, so names that
    appear in comments, strings or as prefixes of other names do not.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: dict[str, bool] = {}

    def record(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if fn.name.startswith("test"):
            found[fn.name] = any("skip" in ast.unparse(d) for d in fn.decorator_list)

    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            record(node)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    record(item)
    return found


def proof_problems(cap: Cap, root: Path) -> list[str]:
    if not cap.proof:
        return [f"{cap.cap_id}: no proof"]
    entries: dict[str, str] = {}
    for part in cap.proof.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            return [f"{cap.cap_id}: malformed proof entry {part!r}"]
        key, value = (s.strip() for s in part.split("=", 1))
        if key in entries:
            return [f"{cap.cap_id}: duplicate proof key {key!r}"]
        entries[key] = value
    problems: list[str] = []
    tests_root = (root / "tests").resolve()
    for dim in PROOF_DIMENSIONS:
        value = entries.get(dim)
        if value is None:
            problems.append(f"{cap.cap_id}: missing {dim} proof")
            continue
        if value.startswith("n/a:"):
            if dim in NA_FORBIDDEN:
                problems.append(f"{cap.cap_id}: {dim} proof cannot be n/a")
            elif len(value[4:].strip()) < NA_MIN_REASON:
                problems.append(f"{cap.cap_id}: {dim} n/a needs a reason of {NA_MIN_REASON}+ chars")
            continue
        m = PROOF_RE.match(value)
        if not m:
            problems.append(f'{cap.cap_id}: {dim} proof must be path›"test" or n/a:<reason>')
            continue
        rel, test = m["path"].strip(), m["test"].strip()
        path = (root / rel).resolve()
        if not path.is_relative_to(tests_root) or path.suffix != ".py":
            problems.append(f"{cap.cap_id}: {dim} proof file {rel} must be a .py file under tests/")
            continue
        if not path.is_file():
            problems.append(f"{cap.cap_id}: {dim} proof file {rel} not found")
            continue
        try:
            tests = _test_functions(path)
        except SyntaxError as exc:
            problems.append(f"{cap.cap_id}: {dim} proof file {rel} does not parse: {exc.msg}")
            continue
        if test not in tests:
            problems.append(f"{cap.cap_id}: {dim} test {test!r} is not a test function in {rel}")
        elif tests[test]:
            problems.append(f"{cap.cap_id}: {dim} test {test!r} is skipped")
    extra = set(entries) - set(PROOF_DIMENSIONS)
    if extra:
        problems.append(f"{cap.cap_id}: unknown proof keys {sorted(extra)}")
    return problems


def gate_proofs(ctx: Ctx) -> Result:
    rows = [c for c in ctx.caps if c.node == ctx.node]
    problems = [p for c in rows for p in proof_problems(c, ctx.root)]
    if problems:
        shown = "; ".join(problems[:6]) + (
            f"; … {len(problems) - 6} more" if len(problems) > 6 else ""
        )
        return Result("FAIL", shown)
    return Result("PASS", f"{len(rows)} rows × {len(PROOF_DIMENSIONS)} dimensions resolve")


def _tool_gate(cmd: list[str], root: Path, label: str) -> Result:
    code, out = _run(cmd, root)
    if code == 0:
        return Result("PASS", label)
    return Result("FAIL", _tail(out))


def gate_ruff(ctx: Ctx) -> Result:
    return _tool_gate([sys.executable, "-m", "ruff", "check", "."], ctx.root, "ruff clean")


def gate_pyright(ctx: Ctx) -> Result:
    return _tool_gate([sys.executable, "-m", "pyright"], ctx.root, "pyright clean")


def _pytest(root: Path, marker: str, label: str) -> Result:
    code, out = _run([sys.executable, "-m", "pytest", "-q", "-m", marker], root)
    if code == 0:
        last = out.splitlines()[-1] if out else ""
        return Result("PASS", f"{label}: {last}")
    if code == 5:
        return Result("SKIP", f"no {label} tests collected yet")
    return Result("FAIL", _tail(out))


def gate_pytest(ctx: Ctx) -> Result:
    return _pytest(ctx.root, PYTEST_UNIT_MARKERS, "unit")


def gate_golden(ctx: Ctx) -> Result:
    return _pytest(ctx.root, "golden", "golden")


def gate_respect_ope(ctx: Ctx) -> Result:
    return _pytest(ctx.root, "respect or ope", "respect-ope")


def gate_safety(ctx: Ctx) -> Result:
    files = secret_scan.candidate_files(ctx.root)
    hits = secret_scan.scan(files)
    data_hits = data_scan.scan(files, ctx.root)
    tests = _pytest(ctx.root, "safety", "safety")
    if hits:
        return Result("FAIL", "secret scan: " + "; ".join(hits[:5]))
    if data_hits:
        return Result("FAIL", "data scan: " + "; ".join(data_hits[:5]))
    site = ctx.root / "site"
    publish_hits = data_scan.scan_publish(site) if site.is_dir() else []
    if publish_hits:
        return Result("FAIL", "publish scan: " + "; ".join(publish_hits[:5]))
    if tests.status == "FAIL":
        return tests
    return Result("PASS", f"secret and data scans clean; {tests.detail}")


def _venv_bin(venv: Path, exe: str) -> Path:
    sub = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return venv / sub / f"{exe}{suffix}"


def gate_build(ctx: Ctx, smoke: list[list[str]] | None = None) -> Result:
    smoke = SMOKE_COMMANDS if smoke is None else smoke
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "dist"
        code, log = _run(["uv", "build", "--wheel", "--out-dir", str(out)], ctx.root)
        if code != 0:
            return Result("FAIL", "uv build: " + _tail(log))
        wheels = sorted(out.glob("*.whl"))
        if not wheels:
            return Result("FAIL", "uv build produced no wheel")
        venv = Path(tmp) / "venv"
        code, log = _run(["uv", "venv", "-q", str(venv)], ctx.root)
        if code != 0:
            return Result("FAIL", "uv venv: " + _tail(log))
        py = _venv_bin(venv, "python")
        code, log = _run(
            ["uv", "pip", "install", "-q", "--python", str(py), str(wheels[0])], ctx.root
        )
        if code != 0:
            return Result("FAIL", "install wheel: " + _tail(log))
        for cmd in smoke:
            exe = _venv_bin(venv, cmd[0])
            code, log = _run([str(exe), *cmd[1:]], Path(tmp))
            if code != 0:
                return Result("FAIL", f"{' '.join(cmd)}: {_tail(log)}")
        return Result(
            "PASS", f"{wheels[0].name} installs; smoke: {', '.join(' '.join(c) for c in smoke)}"
        )


def changed_files(root: Path, base: str) -> list[str] | None:
    """Files changed since base: committed, staged, unstaged and untracked.

    Returns None when git is unusable.
    """
    code, _ = _run(["git", "rev-parse", "--git-dir"], root)
    if code != 0:
        return None
    files: set[str] = set()
    code, _ = _run(["git", "rev-parse", "HEAD"], root)
    if code == 0 and base not in ("", "none"):
        code, out = _run(["git", "diff", "--name-only", base], root)
        if code != 0:
            raise HarnessError(f"git diff against base {base!r} failed: {_tail(out, 2)}")
        files.update(out.splitlines())
    else:
        code, out = _run(["git", "ls-files"], root)
        files.update(out.splitlines())
    code, out = _run(["git", "ls-files", "--others", "--exclude-standard"], root)
    files.update(out.splitlines())
    return sorted(f for f in files if f)


def changed_tests_problem(files: list[str]) -> str | None:
    src = [
        f for f in files if f.startswith("src/") or (f.startswith("scripts/") and f.endswith(".py"))
    ]
    tests = [f for f in files if f.startswith("tests/") and not f.endswith("__init__.py")]
    if src and not tests:
        return f"{len(src)} source files changed but no tests changed (e.g. {src[0]})"
    return None


def gate_changed_tests(ctx: Ctx) -> Result:
    d = spec_dir(ctx.node, ctx.specs)
    base_file = d / ".base" if d else None
    base = (
        base_file.read_text(encoding="utf-8").strip()
        if base_file and base_file.is_file()
        else "none"
    )
    try:
        files = changed_files(ctx.root, base)
    except HarnessError as exc:
        return Result("FAIL", str(exc))
    if files is None:
        return Result("SKIP", "not a git repository")
    problem = changed_tests_problem(files)
    if problem:
        return Result("FAIL", problem)
    return Result(
        "PASS", f"{len(files)} files changed since {base[:10]}; tests changed with source"
    )


def records_problems(node: str, caps: list[Cap], root: Path, specs: Path) -> list[str]:
    problems: list[str] = []
    changelog = root / "changelog.md"
    if not changelog.is_file() or f"[{node}]" not in changelog.read_text(encoding="utf-8"):
        problems.append(f"changelog.md has no [{node}] entry")
    d = spec_dir(node, specs)
    if d is None:
        return [*problems, f"no spec folder for {node}"]
    criteria = d / "criteria.md"
    text = criteria.read_text(encoding="utf-8") if criteria.is_file() else ""
    missing = [
        c.cap_id
        for c in caps
        if c.node == node and not re.search(rf"(?<![\w-]){re.escape(c.cap_id)}(?![\w-])", text)
    ]
    if missing:
        problems.append(f"criteria.md misses {', '.join(missing)}")
    if not (d / "RUN-STATE.md").is_file():
        problems.append("RUN-STATE.md missing")
        return problems
    # docs fresh: the node's run state was updated during this node (since its .base)
    base_file = d / ".base"
    if base_file.is_file():
        base = base_file.read_text(encoding="utf-8").strip()
        try:
            files = changed_files(root, base)
        except HarnessError as exc:
            return [*problems, f"docs fresh: {exc}"]
        rel = (d / "RUN-STATE.md").relative_to(root).as_posix()
        if files is not None and rel not in files:
            problems.append(f"docs fresh: {rel} not updated since node start ({base[:10]})")
    return problems


def gate_records(ctx: Ctx) -> Result:
    problems = records_problems(ctx.node, ctx.caps, ctx.root, ctx.specs)
    return Result("FAIL", "; ".join(problems)) if problems else Result("PASS", "records complete")


GATES: list[tuple[str, Callable[[Ctx], Result]]] = [
    ("claims-work", gate_claims_work),
    ("eligibility", gate_eligibility),
    ("proofs", gate_proofs),
    ("ruff", gate_ruff),
    ("pyright", gate_pyright),
    ("pytest", gate_pytest),
    ("golden", gate_golden),
    ("respect-ope", gate_respect_ope),
    ("safety", gate_safety),
    ("build", gate_build),
    ("changed-tests", gate_changed_tests),
    ("records", gate_records),
]


# ---------- self-test: every gate must be shown to fail on bad input ----------


def self_test() -> int:
    """Feed each gate a planted defect and require FAIL that names the defect."""
    failures = 0

    def check(name: str, ok: bool) -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"  [{'ok' if ok else 'WRONG'}] {name}")

    graph = parse_graph("| **W0.1** | Harness | — |\n| **N1.1** | Schemas | W0.1 |\n")
    hdr = "cap_id\tnode\tstatus\tproof\tnote\n"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        specs = root / "specs"
        (specs / "W0.1-harness").mkdir(parents=True)

        def ctx(cat: str, node: str = "W0.1", at: Path = root) -> Ctx:
            return Ctx(node, at, graph, parse_catalog(hdr + cat), specs)

        # 1 claims-work
        r = gate_claims_work(ctx("H-1\tW0.1\tspec\t\t\n"))
        check(
            "1 claims-work fails naming the node",
            r.status == "FAIL" and "no row of W0.1" in r.detail,
        )
        r = gate_claims_work(ctx("H-1\tW0.1\tbuilding\t\t\n"))
        check("1 claims-work passes when building", r.status == "PASS")

        # 2 eligibility
        r = gate_eligibility(ctx("H-1\tW0.1\tbuilding\t\t\nS-1\tN1.1\tbuilding\t\t\n", "N1.1"))
        check("2 eligibility fails when building ahead", r.status == "FAIL" and "W0.1" in r.detail)

        # 3 proofs
        tests_dir = root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_x.py").write_text(
            "import pytest\n\n"
            "# test_in_comment\n"
            "NAME = 'test_in_string'\n\n"
            "def test_real():\n    pass\n\n"
            "def test_realistic():\n    pass\n\n"
            "@pytest.mark.skip\ndef test_skipped():\n    pass\n",
            encoding="utf-8",
        )
        (root / "outside.py").write_text("def test_real():\n    pass\n", encoding="utf-8")
        ok = "; ".join(
            [f'{d}=tests/test_x.py›"test_real"' for d in PROOF_DIMENSIONS[:3]]
            + ["repro=n/a:no state to reproduce here", "respect=n/a:no member decisions involved"]
        )
        r = gate_proofs(ctx(f"H-1\tW0.1\tgreen\t{ok}\t\n"))
        check("3 proofs pass on resolvable proof", r.status == "PASS")
        bad = {
            "empty proof": "",
            "missing dimension": 'logical=tests/test_x.py›"test_real"',
            "unknown test": ok.replace('"test_real"', '"test_ghost"', 1),
            "name only in a comment": ok.replace('"test_real"', '"test_in_comment"', 1),
            "name only in a string": ok.replace('"test_real"', '"test_in_string"', 1),
            "prefix of another test": ok.replace('"test_real"', '"test_rea"', 1),
            "skipped test": ok.replace('"test_real"', '"test_skipped"', 1),
            "path outside tests/": ok.replace("tests/test_x.py", "outside.py", 1),
            "path escaping repo": ok.replace("tests/test_x.py", "tests/../../x.py", 1),
            "short n/a reason": ok.replace("n/a:no state to reproduce here", "n/a:x"),
            "logical n/a": ok.replace(
                'logical=tests/test_x.py›"test_real"', "logical=n/a:nothing to unit test here"
            ),
            "duplicate key": ok + '; logical=tests/test_x.py›"test_real"',
        }
        for label, proof in bad.items():
            r = gate_proofs(ctx(f"H-1\tW0.1\tgreen\t{proof}\t\n"))
            check(f"3 proofs fail on {label}", r.status == "FAIL" and r.detail.startswith("H-1:"))
        r = gate_proofs(ctx(f"H-1\tW0.1\tgreen\t{ok.rsplit(';', 1)[0]}\t\n"))
        check("3 proofs fail when only respect is missing", "missing respect proof" in r.detail)

        # 4 ruff — must name the planted rule, so a missing tool cannot pass for a caught defect
        lint = root / "lint"
        lint.mkdir()
        (lint / "bad.py").write_text("import os\n", encoding="utf-8")
        r = gate_ruff(ctx("H-1\tW0.1\tbuilding\t\t\n", at=lint))
        check("4 ruff fails naming F401", r.status == "FAIL" and "F401" in r.detail)

        # 5 pyright
        types = root / "types"
        types.mkdir()
        (types / "bad.py").write_text('x: int = "a"\n', encoding="utf-8")
        (types / "pyrightconfig.json").write_text("{}", encoding="utf-8")
        r = gate_pyright(ctx("H-1\tW0.1\tbuilding\t\t\n", at=types))
        check("5 pyright fails naming bad.py", r.status == "FAIL" and "bad.py" in r.detail)

        # 6-9 pytest-backed gates, each on its own failing fixture
        pt = root / "pt"
        pt.mkdir()
        (pt / "test_fail.py").write_text(
            "import pytest\n\n"
            "def test_unit_fails():\n    assert False\n\n"
            "@pytest.mark.golden\ndef test_golden_fails():\n    assert False\n\n"
            "@pytest.mark.respect\ndef test_respect_fails():\n    assert False\n\n"
            "@pytest.mark.safety\ndef test_safety_fails():\n    assert False\n",
            encoding="utf-8",
        )
        on_pt = ctx("H-1\tW0.1\tbuilding\t\t\n", at=pt)
        r = gate_pytest(on_pt)
        check(
            "6 pytest fails naming the failing test",
            r.status == "FAIL" and "test_unit_fails" in r.detail,
        )
        r = gate_golden(on_pt)
        check(
            "7 golden fails naming the failing test",
            r.status == "FAIL" and "test_golden_fails" in r.detail,
        )
        r = gate_respect_ope(on_pt)
        check(
            "8 respect-ope fails naming the failing respect test",
            r.status == "FAIL" and "test_respect_fails" in r.detail,
        )
        ope = root / "ope"
        ope.mkdir()
        (ope / "test_ope.py").write_text(
            "import pytest\n\n@pytest.mark.ope\ndef test_ope_fails():\n    assert False\n",
            encoding="utf-8",
        )
        r = gate_respect_ope(ctx("H-1\tW0.1\tbuilding\t\t\n", at=ope))
        check(
            "8 respect-ope fails naming a failing ope-only test",
            r.status == "FAIL" and "test_ope_fails" in r.detail,
        )
        r = gate_safety(ctx("H-1\tW0.1\tbuilding\t\t\n", at=pt))
        check(
            "9 safety fails on a failing safety test",
            r.status == "FAIL" and "test_safety_fails" in r.detail,
        )
        empty = root / "empty"
        empty.mkdir()
        (empty / "test_none.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
        check(
            "7 golden reports SKIP, not PASS, with no golden tests",
            gate_golden(ctx("H-1\tW0.1\tbuilding\t\t\n", at=empty)).status == "SKIP",
        )
        leak = root / "leak"
        leak.mkdir()
        (leak / "k.py").write_text('K = "sk-ant-' + "Q" * 30 + '"\n', encoding="utf-8")
        r = gate_safety(ctx("H-1\tW0.1\tbuilding\t\t\n", at=leak))
        check("9 safety fails on a leaked key", r.status == "FAIL" and "anthropic key" in r.detail)
        rows = root / "rows"
        rows.mkdir()
        (rows / "m.csv").write_text("msno\n" + "A" * 43 + "=\n", encoding="utf-8")
        r = gate_safety(ctx("H-1\tW0.1\tbuilding\t\t\n", at=rows))
        check("9 safety fails on a member id", r.status == "FAIL" and "member id" in r.detail)
        # publish scan: an ignored site/ file is invisible to the repo scan, so only gate 9's
        # publish-scan wiring can catch it
        pub = root / "pub"
        (pub / "site").mkdir(parents=True)
        _run(["git", "init", "-q"], pub)
        (pub / ".gitignore").write_text("site/\n", encoding="utf-8")
        (pub / "site" / "cube.json").write_text('["' + "Aa0+" * 10 + 'xy/="]', encoding="utf-8")
        r = gate_safety(ctx("H-1\tW0.1\tbuilding\t\t\n", at=pub))
        check(
            "9 safety fails on a member id in an ignored site/ file (publish scan)",
            r.status == "FAIL" and r.detail.startswith("publish scan"),
        )

        # 10 build
        broken = root / "broken"
        broken.mkdir()
        (broken / "pyproject.toml").write_text("[project\nname=", encoding="utf-8")
        r = gate_build(Ctx("W0.1", broken, graph, [], specs), smoke=[])
        check("10 build fails on a broken project", r.status == "FAIL" and "uv build" in r.detail)

        # 11 changed-tests
        check(
            "11 fails when only source changed",
            changed_tests_problem(["src/respectful_offers/x.py"]) is not None,
        )
        check(
            "11 an __init__.py does not count as a test change",
            changed_tests_problem(["src/respectful_offers/x.py", "tests/__init__.py"]) is not None,
        )
        check(
            "11 passes when tests changed",
            changed_tests_problem(["src/respectful_offers/x.py", "tests/test_x.py"]) is None,
        )
        repo = root / "repo"
        repo.mkdir()
        for c in (
            ["git", "init", "-q"],
            [
                "git",
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "a",
            ],
        ):
            _run(c, repo)
        try:
            changed_files(repo, "deadbeef")
            check("11 an unknown base commit fails", False)
        except HarnessError:
            check("11 an unknown base commit fails", True)
        _, head = _run(["git", "rev-parse", "HEAD"], repo)
        rspecs = repo / "specs" / "W0.1-harness"
        rspecs.mkdir(parents=True)
        (rspecs / ".base").write_text(head.strip() + "\n", encoding="utf-8")
        (repo / "src").mkdir()
        (repo / "src" / "only_source.py").write_text("X = 1\n", encoding="utf-8")
        r = gate_changed_tests(Ctx("W0.1", repo, graph, [], repo / "specs"))
        check(
            "11 changed-tests gate fails naming the untested source file",
            r.status == "FAIL" and "only_source.py" in r.detail,
        )
        (rspecs / "criteria.md").write_text("H-1\n", encoding="utf-8")
        (repo / "changelog.md").write_text("[W0.1]\n", encoding="utf-8")
        _run(["git", "add", "-A"], repo)
        _run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "b"], repo)
        (rspecs / "RUN-STATE.md").write_text("ok\n", encoding="utf-8")
        _run(["git", "add", "-A"], repo)
        _run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c"], repo)
        _, newhead = _run(["git", "rev-parse", "HEAD"], repo)
        (rspecs / ".base").write_text(newhead.strip() + "\n", encoding="utf-8")
        cat1 = parse_catalog(hdr + "H-1\tW0.1\tgreen\t\t\n")
        problems = records_problems("W0.1", cat1, repo, repo / "specs")
        check(
            "12 records fails when RUN-STATE.md is stale since node start",
            any("docs fresh" in p for p in problems),
        )

        # 12 records
        cat = parse_catalog(hdr + "H-1\tW0.1\tgreen\t\t\n")
        check(
            "12 records fails naming the missing changelog entry",
            "changelog.md has no [W0.1] entry" in records_problems("W0.1", cat, root, specs),
        )
        (specs / "W0.1-harness" / "criteria.md").write_text("H-10\n", encoding="utf-8")
        (root / "changelog.md").write_text("[FEAT] [W0.1] — harness\n", encoding="utf-8")
        (specs / "W0.1-harness" / "RUN-STATE.md").write_text("ok\n", encoding="utf-8")
        check(
            "12 criteria naming H-10 does not cover H-1",
            "criteria.md misses H-1" in records_problems("W0.1", cat, root, specs),
        )
        (root / "changelog.md").write_text("[FEAT] [W0.1] — harness\n", encoding="utf-8")
        (specs / "W0.1-harness" / "criteria.md").write_text("H-1\n", encoding="utf-8")
        (specs / "W0.1-harness" / "RUN-STATE.md").write_text("ok\n", encoding="utf-8")
        check("12 records passes when complete", records_problems("W0.1", cat, root, specs) == [])
        r = gate_records(Ctx("W0.1", root, graph, cat, specs))
        check("12 records gate passes on complete records", r.status == "PASS")
        (root / "changelog.md").write_text("nothing here\n", encoding="utf-8")
        r = gate_records(Ctx("W0.1", root, graph, cat, specs))
        check(
            "12 records gate fails naming the changelog",
            r.status == "FAIL" and "changelog.md has no [W0.1] entry" in r.detail,
        )
    print("self-test", "PASSED" if failures == 0 else f"FAILED ({failures})")
    return 0 if failures == 0 else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("node", nargs="?")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--no-log", action="store_true", help="do not write a log under .harness/")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.node:
        ap.error("node is required")
    try:
        ctx = Ctx(args.node, ROOT, load_graph(), load_catalog(), SPECS_DIR)
    except (HarnessError, OSError) as exc:
        print(f"node-converge: cannot read inputs: {exc}")
        return 1
    if args.node not in ctx.nodes:
        print(f"node-converge: unknown node {args.node}")
        return 1
    lines = [f"node-converge {args.node} — {dt.datetime.now().isoformat(timespec='seconds')}"]
    failed = 0
    for i, (name, fn) in enumerate(GATES, start=1):
        try:
            r = fn(ctx)
        except Exception as exc:  # a crashing gate is a failing gate
            r = Result("FAIL", f"gate crashed: {exc!r}")
        failed += r.status == "FAIL"
        first, *rest = r.detail.splitlines() or [""]
        lines.append(f"{i:>2} {name:<14} {r.status:<4}  {first}")
        lines.extend(f"{'':>22}{ln}" for ln in rest)
    lines.append(
        f"RESULT: {'FAIL' if failed else 'PASS'} "
        f"({failed} failing gate{'s' if failed != 1 else ''})"
    )
    report = "\n".join(lines)
    print(report)
    if args.no_log:
        return 1 if failed else 0
    log_dir = ROOT / ".harness" / args.node
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    (log_dir / f"converge-{stamp}.txt").write_text(report + "\n", encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
