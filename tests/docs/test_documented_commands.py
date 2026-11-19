"""REL-03: every command the README and the guides document runs, in a scripted fixture
project. A documented `offers` command that no scenario here runs (and that is not on the
short, reasoned skip list) fails the first test, so the docs cannot drift from the CLI."""

import json
import re
import shlex

import pytest

from harness_lib import ROOT
from respectful_offers import cli

DOCS = [ROOT / "README.md", *sorted((ROOT / "docs" / "guide").glob("*.md"))]
SKIP = {
    "offers data download": "needs the owner's Kaggle token and network: tests/data covers it "
    "with a fake client, and results/kkbox is its output",
    "offers run --all": "on real KKBox data after a download: tests/results checks the "
    "published run it produced",
    "offers monitor export": "on real KKBox data after a download: tests/monitor/test_export.py "
    "checks the committed results/kkbox/monitor files it wrote",
    "offers challenge --challenger-seed 20261122 --baseline <a baseline period's metrics.json>": (
        "seven minutes on real KKBox data: tests/monitor checks the committed challenge, its "
        "decision row and its experiment-ledger entries"
    ),
}
QUICKSTART = (
    "offers doctor",
    "offers report --example",
    "offers data synthetic --members 20000",
    "offers run --all --exploratory",
)
OWN_DATA = (
    "offers init my-project",
    "offers features --from-table features.csv --audit-table audit.csv",
    "offers prereg --scope real",
    "offers run --all --from-table features.csv --audit-table audit.csv",
)

MONITOR = (
    "offers monitor drift --ledger docs/measurements/runs.jsonl",
    "offers monitor check --period results/kkbox/metrics.json",
)


SHELL_FENCE = re.compile(r"```(?:bash|sh|shell|console|zsh)\b[^\n]*\n(.*?)```", re.S)
PREFIX = re.compile(r"^(?:\$\s+|uv run\s+|uvx\s+(?:--from\s+\S+\s+)?)+")


def commands_in(text: str) -> set[str]:
    """Every `offers ...` command in the shell blocks of a Markdown text (bash, sh, shell,
    console or zsh fences; `$ ` prompts, `uv run` and `uvx` prefixes, `python -m
    respectful_offers`, chains with `&&`, `;` or `||` and backslash continuations included)."""
    found = set()
    for block in SHELL_FENCE.findall(text):
        block = block.replace("\\\n", " ")
        for line in block.splitlines():
            line = re.sub(r"\s+#.*$", "", line).strip()
            for part in re.split(r"&&|\|\||;", line):
                part = PREFIX.sub("", part.strip())
                part = re.sub(r"^python3? -m respectful_offers\b", "offers", part)
                if part.startswith("offers "):
                    found.add(" ".join(part.split()))
    return found


def documented() -> set[str]:
    return set().union(*(commands_in(d.read_text(encoding="utf-8")) for d in DOCS))


def test_no_offers_command_hides_in_an_unparsed_block():
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8")
        fences = re.findall(r"```([^\n]*)\n(.*?)```", text, re.S)
        for info, body in fences:
            if re.search(r"^\s*(?:\$\s*)?(?:uvx?\s+(?:run\s+)?)?offers\s", body, re.M):
                assert SHELL_FENCE.match(f"```{info}\n{body}```"), (doc.name, info)


def test_the_extractor_finds_commands_in_every_documented_form():
    text = (
        "```console\n$ offers doctor\n```\n```sh\nuvx --from respectful-offers offers report "
        "--example; python -m respectful_offers data synthetic \\\n  --members 20000\n```\n"
    )
    assert commands_in(text) == {
        "offers doctor",
        "offers report --example",
        "offers data synthetic --members 20000",
    }


def test_every_documented_command_is_run_here_or_skipped_for_a_reason():
    docs = documented()
    assert docs, "no documented commands found"
    covered = set(QUICKSTART) | set(OWN_DATA) | set(MONITOR) | set(SKIP)
    assert docs <= covered, f"documented but never run: {sorted(docs - covered)}"
    scenarios = set(QUICKSTART) | set(OWN_DATA) | set(MONITOR)
    assert scenarios <= docs, "a scenario runs a command no doc shows"


def run(command: str) -> int:
    return cli.main(shlex.split(command)[1:])


def test_the_quickstart_runs_as_written(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    for command in QUICKSTART:
        assert run(command) == 0, command
    capsys.readouterr()
    assert (tmp_path / "report-example" / "index.html").is_file()
    summary = json.loads((tmp_path / "runs" / "latest" / "summary.json").read_text("utf-8"))
    assert summary["data_source"] == "synthetic" and summary["prereg_status"] == "exploratory"
    assert (tmp_path / "report" / "index.html").is_file()


def test_using_your_own_data_runs_as_written(tmp_path, monkeypatch, capsys):
    from tests.cli.test_modules import table

    monkeypatch.chdir(tmp_path)
    assert run(OWN_DATA[0]) == 0
    project = tmp_path / "my-project"
    monkeypatch.chdir(project)  # `cd my-project`
    members = table(n=2000, seed=7)  # "replace them with your members"
    members.to_csv(project / "features.csv", index=False)
    ids = sorted(set(members.loc[members.cohort == "mar", "msno"]))
    bands = ["18-24", "25-34", "35-44", "unknown"]
    rows = [f"{m},{bands[i % 4]},{('female', 'male', 'unknown')[i % 3]}" for i, m in enumerate(ids)]
    (project / "audit.csv").write_text("msno,age_band,gender\n" + "\n".join(rows) + "\n", "utf-8")
    for command in OWN_DATA[1:]:
        assert run(command) == 0, command
    capsys.readouterr()
    summary = json.loads((project / "runs" / "latest" / "summary.json").read_text("utf-8"))
    assert summary["data_source"] == "your_table" and summary["prereg_status"] == "preregistered"
    assert (project / "report" / "index.html").is_file()


@pytest.mark.parametrize(
    "path",
    [
        "docs/img/headline.svg",
        "docs/img/report.png",
        "docs/img/demo.png",
        "docs/img/audit.png",
        "docs/img/frontier.png",
    ],
)
def test_every_image_the_readme_shows_exists(path):
    raw = "https://raw.githubusercontent.com/biplob819/respectful-offers/main/"
    assert f"]({raw}{path})" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert (ROOT / path).is_file() and (ROOT / path).stat().st_size > 1000


def test_the_monitoring_guide_runs_as_written(tmp_path, monkeypatch, capsys):
    """On a copy of the committed aggregates, so the real ledger is never appended to."""
    import shutil

    pytest.importorskip("evalkit.drift", reason="the `evalkit` extra is not installed")
    for rel in (
        "configs/drift.yaml",
        "results/kkbox/metrics.json",
        "results/kkbox/monitor/reference-2017-02.metrics.json",
        "results/kkbox/monitor/period-2017-03.metrics.json",
    ):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    monkeypatch.chdir(tmp_path)
    for command in MONITOR:
        assert run(command) == 0, command
    capsys.readouterr()
    assert (tmp_path / "docs" / "measurements" / "runs.jsonl").is_file()
    from tests.monitor.test_drift import same

    rel = "results/kkbox/monitor/drift.json"
    same(
        json.loads((tmp_path / rel).read_text(encoding="utf-8")),
        json.loads((ROOT / rel).read_text(encoding="utf-8")),
    )
