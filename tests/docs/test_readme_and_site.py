"""REL-01 (the README's opening) and REL-02 (the report on GitHub Pages)."""

import re
import subprocess
import sys

from harness_lib import ROOT

README = ROOT / "README.md"


def opening() -> str:
    text = README.read_text(encoding="utf-8")
    return text.split("<!-- headline:start -->", 1)[1].split("<!-- headline:end -->", 1)[0]


def test_the_readme_headline_and_chart_are_regenerated_from_the_published_summary():
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "readme_assets.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert out.returncode == 0, out.stderr  # any drift from results/kkbox/summary.json fails


def test_the_opening_is_one_chart_three_sentences_a_caveat_a_snippet_and_the_credit():
    block = opening()
    assert block.count("![") == 1 and "docs/img/headline.svg" in block
    prose = next(p for p in block.split("\n\n") if p.startswith("On "))
    assert len(re.findall(r"[.!?](?:\s|$)", prose)) == 3, prose
    assert "**simulated**" in prose and "> **Simulated.**" in block
    snippet = re.search(r"```bash\n(.*?)```", block, re.S)
    assert snippet and len(snippet.group(1).strip().splitlines()) == 3
    assert "kaggle.com/competitions/kkbox-churn-prediction-challenge" in block
    assert "No member data" in block


def test_the_readme_links_everything_that_matters():
    text = README.read_text(encoding="utf-8")
    for target in (
        "https://biplob819.github.io/respectful-offers/",
        "https://respectful-offers.streamlit.app/",
        "https://pypi.org/project/respectful-offers/",
        "results/kkbox/decision-review.md",
        "docs/guide/quickstart.md",
        "docs/guide/own-data.md",
        "docs/guide/reproduce.md",
        "DATA_CARD.md",
        "docs/decisions.md",
        "docs/prereg.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
    ):
        assert target in text, target
    for rel in re.findall(r"\]\(((?!https?://)[^)#]+)\)", text):
        assert (ROOT / rel.replace("%20", " ")).exists(), rel  # no dead relative link


def test_the_site_is_the_published_report_and_passes_the_publish_scan(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_site

    out = tmp_path / "_site"
    assert build_site.build(out) == []
    report = ROOT / "results" / "kkbox" / "report" / "index.html"
    assert (out / "index.html").read_bytes() == report.read_bytes()
    assert not any(p.suffix in {".csv", ".parquet", ".7z", ".zip"} for p in out.rglob("*"))
    import data_scan

    member = "Q" * 43 + "="  # the shape of a KKBox member id
    (out / "page.html").write_text(f"<p>{member}</p>", encoding="utf-8")
    assert data_scan.scan_publish(out)  # the scan the workflow relies on catches a leaked id
    (out / "page.html").unlink()
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "rows.csv").write_text("msno,is_churn\nabc,1\n", encoding="utf-8")
    monkeypatch.setattr(build_site, "SOURCES", (*build_site.SOURCES, extra))
    assert any("row-data" in p for p in build_site.build(out))  # and any table of rows


def test_the_pages_workflow_builds_through_the_scan_with_least_privilege():
    wf = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    assert "python scripts/build_site.py _site" in wf
    assert "actions/upload-pages-artifact" in wf and "actions/deploy-pages" in wf
    assert re.search(r"^permissions:\n  contents: read$", wf, re.M)
    assert "results/kkbox/report/**" in wf
