"""B2.4: the open-source release (OSS-01..OSS-09)."""

import re
import subprocess
import sys
import tomllib

import pytest

from harness_lib import ROOT

WF = ROOT / ".github" / "workflows" / "release.yml"


def pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


# --- OSS-01 history audit -------------------------------------------------------------


def test_the_whole_history_passes_the_secret_and_data_scans():
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "history_audit.py")],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert out.returncode == 0, out.stderr
    assert re.search(r"history audit: \d+ blobs on every ref, 0 hit", out.stdout)
    for wf in ("ci.yml", "release.yml"):  # a shallow checkout would audit only the tip
        text = (ROOT / ".github" / "workflows" / wf).read_text(encoding="utf-8")
        assert "fetch-depth: 0" in text, wf


def test_the_history_audit_catches_a_leak_committed_and_then_deleted(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import history_audit

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "test")
    (tmp_path / "train.csv").write_text("msno,is_churn\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("token KGAT_" + "a" * 30 + "\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "leak")
    git("rm", "-q", "train.csv", "notes.txt")
    git("commit", "-q", "-m", "remove")
    n, hits = history_audit.audit(tmp_path)
    assert n == 2 and len(hits) == 2
    assert any("KKBox raw file name" in h for h in hits)
    assert any("kaggle api token" in h for h in hits)


# --- OSS-02 records in the repo -------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "docs/decisions.md",
        "DATA_CARD.md",
        "docs/how-i-built-it.md",
        "Respectful Offers PRD.md",
        "docs/lessons.md",
        "changelog.md",
    ],
)
def test_the_records_are_in_the_repo_and_linked_from_the_readme(path):
    assert (ROOT / path).is_file()
    assert path.replace(" ", "%20") in (ROOT / "README.md").read_text(encoding="utf-8")


# --- OSS-03 versioned, tagged release -------------------------------------------------


def test_one_version_everywhere():
    from respectful_offers import __version__

    version = pyproject()["project"]["version"]
    assert version == __version__ == "0.1.0"
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert re.search(r'name = "respectful-offers"\nversion = "0\.1\.0"', lock)


# --- OSS-04 published artifacts and the licence ruling --------------------------------


def test_every_published_artifact_respects_the_licence_ruling():
    import data_scan

    published = [
        *(p for p in (ROOT / "results" / "kkbox").rglob("*") if p.is_file()),
        *(p for p in (ROOT / "docs" / "site").rglob("*") if p.is_file()),
        ROOT / "demo" / "cube.json",
        ROOT / "README.md",
    ]
    assert data_scan.scan(published) == []
    cite = "kaggle.com/competitions/kkbox-churn-prediction-challenge"
    for doc in ("results/kkbox/report/index.html", "results/kkbox/README.md", "README.md"):
        assert cite in (ROOT / doc).read_text(encoding="utf-8"), doc
    assert "WSDM Cup 2018" in (ROOT / "docs" / "site" / "prfaq.md").read_text(encoding="utf-8")
    assert not any(p.suffix in {".csv", ".parquet"} for p in published)


# --- OSS-05 names and trusted publishing ----------------------------------------------


def test_distribution_cli_and_import_names():
    p = pyproject()["project"]
    assert p["name"] == "respectful-offers"
    assert p["scripts"] == {"offers": "respectful_offers.cli:main"}
    assert (ROOT / "src" / "respectful_offers" / "__init__.py").is_file()
    assert p["license"] == "MIT" and p["requires-python"] == ">=3.11"
    assert {"Homepage", "Documentation", "Source", "Issues"} <= set(p["urls"])


def test_release_publishes_by_trusted_publishing_on_a_tag_only():
    wf = WF.read_text(encoding="utf-8")
    assert re.search(r"on:\n  push:\n    tags: \[\"v\*\"\]", wf)
    assert "pypa/gh-action-pypi-publish" in wf and "environment: pypi" in wf
    assert "password:" not in wf and "secrets." not in wf  # OIDC, no stored token
    assert "uv run pytest -q" in wf and "scripts/secret_scan.py" in wf


# --- OSS-06 smoke test after release --------------------------------------------------


def test_release_smoke_tests_the_published_package_on_every_os():
    wf = WF.read_text(encoding="utf-8")
    smoke = wf.split("  smoke:", 1)[1]
    assert "needs: publish" in smoke
    assert "os: [ubuntu-latest, macos-latest, windows-latest]" in smoke
    assert 'uvx --from "respectful-offers==${version}" offers doctor' in smoke
    assert "offers report --example" in smoke and "test -f example/index.html" in smoke


# --- OSS-07 docs ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "guide, must",
    [
        ("quickstart.md", "five minutes"),
        ("own-data.md", "--from-table"),
        ("writing-a-simulator.md", "offers prereg"),
        ("respect-rules.md", "R1"),
        ("reproduce.md", "offers data download"),
    ],
)
def test_the_guides_cover_what_users_need(guide, must):
    assert must in (ROOT / "docs" / "guide" / guide).read_text(encoding="utf-8")


# --- OSS-08 community files -----------------------------------------------------------


def test_community_files_and_versioning_policy():
    for f in ("CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md", "LICENSE"):
        assert (ROOT / f).is_file(), f
    assert "Semantic versioning" in (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    sec = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "Report a vulnerability" in sec and "@" not in sec  # private reporting, no email
    for f in ("ISSUE_TEMPLATE/bug.yml", "ISSUE_TEMPLATE/feature.yml", "PULL_REQUEST_TEMPLATE.md"):
        assert (ROOT / ".github" / f).is_file(), f


# --- OSS-09 privacy -------------------------------------------------------------------


def test_the_privacy_statement_matches_the_code():
    text = (ROOT / "docs" / "guide" / "privacy.md").read_text(encoding="utf-8")
    assert "No telemetry" in text and "offers data download" in text
    cfg = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert "gatherUsageStats = false" in cfg
    network = re.compile(
        r"^\s*(?:import|from)\s+(?:requests|httpx|urllib\.request|socket|aiohttp)\b"
    )
    for src in (ROOT / "src" / "respectful_offers").rglob("*.py"):
        if src.name == "download.py":
            continue  # the one place a network client may live (the KKBox download)
        for line in src.read_text(encoding="utf-8").splitlines():
            assert not network.match(line), (src, line)
