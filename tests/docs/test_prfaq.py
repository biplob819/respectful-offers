"""P2.1: the PR/FAQ (PRF-01..PRF-04)."""

import json
import re
import subprocess
import sys

import pytest

from harness_lib import ROOT

SITE = ROOT / "docs" / "site"
sys.path.insert(0, str(ROOT / "scripts"))
import prfaq  # noqa: E402


def text() -> str:
    return (SITE / "prfaq.md").read_text(encoding="utf-8")


def test_a_one_page_pr_faq_in_markdown_html_and_pdf():
    for name in ("prfaq.md", "prfaq.html", "prfaq.pdf", "prfaq.pdf.sha256"):
        assert (SITE / name).is_file(), name
    pdf = (SITE / "prfaq.pdf").read_bytes()
    assert pdf.startswith(b"%PDF") and len(re.findall(rb"/Type\s*/Page[^s]", pdf)) == 1
    t = text()
    assert t.count("\n## ") == 2 and "## Press release" in t and "## FAQ" in t


def test_every_file_is_current_with_the_published_summary():
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "prfaq.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert out.returncode == 0, out.stderr  # md, html and the PDF's source hash


def test_a_changed_summary_changes_the_numbers(tmp_path, monkeypatch):
    data = json.loads(prfaq.SUMMARY.read_text(encoding="utf-8"))
    for p in data["policies"]:
        if p["variant"] == "central" and p["policy"] == "bandit":
            p["cost_per_incremental_retained"]["point"] = 123.0
    fake = tmp_path / "summary.json"
    fake.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(prfaq, "SUMMARY", fake)
    assert "**123 NTD**" in prfaq.markdown() and "**123 NTD**" not in text()


def test_every_number_in_the_text_comes_from_the_summary():
    f = prfaq.facts()
    t = text()
    assert f"**{f['central.bandit.cost']:.0f} NTD**" in t
    assert f"{f['members']:,} real members" in t
    for v in prfaq.VARIANTS:
        d, lo, hi, _ = f[f"{v}.claim"]
        assert f"{v} {d:+.2f} ({lo:+.2f} to {hi:+.2f})" in t
    assert f"{f['dr.covered']} of {f['dr.total']}" in t
    assert f"{f['central.status_quo.violations']:,}" in t
    numbers = set(re.findall(r"\d[\d,]*\.?\d*", t))
    assert "2018" in numbers  # the only number not from the summary or config is the year
    assert {"200,000", "97", "211", "289"} <= numbers


@pytest.mark.parametrize(
    "question",
    [
        "What would a real A/B test add?",
        "Why a holdout?",
        "Why a doubly robust estimator?",
        "Why do the rules sit outside the learning?",
    ],
)
def test_the_faq_answers_the_required_questions(question):
    assert f"**{question}**" in text()


def test_simulated_labels_and_conditional_conclusions():
    t = text()
    assert "(simulated results)" in t.splitlines()[0]
    press = t.split("## Press release", 1)[1].split("## FAQ", 1)[0].strip()
    assert press.startswith("**Simulated results.**")
    assert "conditional on the simulator's assumptions" in press
    for v in ("conservative", "central", "optimistic"):
        assert v in press  # a conclusion per variant
    assert "**simulated**" in t.split("## FAQ", 1)[1]
    assert "non-commercial research and education" in t  # OWNER D-46 citation


def test_no_number_is_written_into_the_template(tmp_path, monkeypatch):
    """Render once from the real summary and once from one with every number scaled: any
    number that stays the same is a constant of the template, and only a few are allowed."""
    data = json.loads(prfaq.SUMMARY.read_text(encoding="utf-8"))

    def scale(x, path="", factor=0.93):
        """Each field gets its own factor (an interval's point, lo and hi share one), so
        ratios between fields change too."""
        if isinstance(x, bool):
            return x
        if isinstance(x, int):
            return x * 2
        if isinstance(x, float):
            return x * factor
        if isinstance(x, dict):
            own = 0.6 + (sum(map(ord, path)) % 35) / 100  # in [0.6, 0.94]: bounds still hold
            interval = {"point", "lo", "hi"} <= set(x)
            return {k: scale(v, f"{path}.{k}", factor if interval else own) for k, v in x.items()}
        if isinstance(x, list):
            return [scale(v, f"{path}[{i}]", factor) for i, v in enumerate(x)]
        return x

    keep = {"schema_version", "run_id", "git_sha", "config_hash", "simulator_hash"}
    fake = tmp_path / "summary.json"
    scaled_data = {k: (v if k in keep else scale(v, k)) for k, v in data.items()}
    fake.write_text(json.dumps(scaled_data), encoding="utf-8")
    pattern = r"[+-]?\d[\d,]*\.?\d*%?"
    real = re.findall(pattern, prfaq.markdown())
    monkeypatch.setattr(prfaq, "SUMMARY", fake)
    scaled = re.findall(pattern, prfaq.markdown())
    assert len(real) == len(scaled)
    constants = {a for a, b in zip(real, scaled, strict=True) if a == b}
    # the year of the challenge, units ("per 1,000"), the confidence level, the share the
    # config fixes, the 12 estimator cases (a count of what was checked), and sha256
    assert constants <= {"2018", "1,000", "95%", "10%", "12", "256"}, constants
