import re
from pathlib import Path

import pytest

import status
from harness_lib import ROOT

WORKFLOWS = ROOT / ".github" / "workflows"


def test_decisions_seeded_d1_to_d18():
    text = (ROOT / "docs" / "decisions.md").read_text(encoding="utf-8")
    ids = {int(n) for n in re.findall(r"^\| (?:OWNER )?D-(\d+) \|", text, re.M)}
    assert set(range(1, 25)) <= ids
    for owner in (1, 15, 17, 18, 19, 21):
        assert f"| OWNER D-{owner} |" in text


def test_lessons_and_changelog_exist():
    assert "L-1" in (ROOT / "docs" / "lessons.md").read_text(encoding="utf-8")
    assert "[W0.1]" in (ROOT / "changelog.md").read_text(encoding="utf-8")


def test_status_prints_graph_and_node(capsys):
    assert status.main([]) == 0
    out = capsys.readouterr().out
    assert "W0.1" in out and "D3.3" in out and "capabilities green" in out
    assert status.main(["W0.1"]) == 0
    assert "HAR-07" in capsys.readouterr().out
    assert status.main(["Z9.9"]) == 1


def _yaml_code(path: Path) -> str:
    """Workflow text with comment-only lines and trailing comments removed."""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        code = line.split(" #", 1)[0].rstrip()
        if code.strip() and not code.lstrip().startswith("#"):
            lines.append(code)
    return "\n".join(lines)


def test_ci_workflow_covers_gates_and_matrix():
    ci = _yaml_code(WORKFLOWS / "ci.yml")
    assert re.search(r"^on:\n  push:", ci, re.M)
    for step in (
        "ruff check",
        "ruff format --check",
        "pyright",
        "pytest",
        "uv build",
        "secret_scan.py",
        "data_scan.py",
        "verify_graph_eligibility.py",
    ):
        assert (
            f"run: uv run {step}" in ci
            or f"run: uv run python scripts/{step}" in ci
            or (step == "uv build" and "run: uv build" in ci)
        ), step
    assert "uv sync --locked" in ci
    for v in ('"3.11"', '"3.12"', '"3.13"'):
        assert v in ci
    for os_name in ("ubuntu-latest", "macos-latest", "windows-latest"):
        assert os_name in ci
    assert "pull_request" in ci


def test_portfolio_notes_stay_out_of_public_repo():
    assert "Portfolio notes.md" in Path(ROOT / ".gitignore").read_text(encoding="utf-8")


@pytest.mark.contract
def test_workflows_grant_least_privilege():
    ci = _yaml_code(WORKFLOWS / "ci.yml")
    assert re.search(r"^permissions:\n  contents: read$", ci, re.M)
    assert ": write" not in ci and "write-all" not in ci
    assert "secrets." not in ci
    # every workflow declares top-level permissions; write scopes only where named here
    may_write = {"release.yml": {"id-token"}, "pages.yml": {"pages", "id-token"}}
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        code = _yaml_code(wf)
        assert re.search(r"^permissions:", code, re.M), wf.name
        assert "write-all" not in code, wf.name
        writes = set(re.findall(r"^\s+([\w-]+): write$", code, re.M))
        assert writes <= may_write.get(wf.name, set()), (wf.name, writes)


def test_pre_commit_runs_ruff_and_both_scans():
    text = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    for hook in ("id: ruff", "id: ruff-format", "scripts/secret_scan.py", "scripts/data_scan.py"):
        assert hook in text


def test_gitignore_keeps_data_and_notes_out():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for entry in ("Portfolio notes.md", "data/", ".offers/", "runs/", ".env"):
        assert entry in text.splitlines()


def test_catalog_round_trip_is_byte_identical(tmp_path):
    from harness_lib import CATALOG_TSV, load_catalog, write_catalog

    out = tmp_path / "catalog.tsv"
    write_catalog(load_catalog(), out)
    assert out.read_bytes() == CATALOG_TSV.read_bytes()


def test_status_output_is_deterministic(capsys):
    status.main([])
    first = capsys.readouterr().out
    status.main([])
    assert capsys.readouterr().out == first


def test_gitattributes_force_lf():
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "* text=auto eol=lf" in text
