"""D3.3: the case study page and the video script (PAG-01..PAG-03)."""

import html
import json
import os
import re
import subprocess
import sys
import urllib.request
from http.cookiejar import CookieJar

import pytest

from harness_lib import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import prfaq
import project_page

SITE = ROOT / "docs" / "site"


def test_both_files_are_current_with_the_published_summary():
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "project_page.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert out.returncode == 0, out.stderr


def test_the_case_study_states_the_summarys_numbers():
    f = prfaq.facts()
    page = (SITE / "case-study.html").read_text(encoding="utf-8")
    for n in (
        f"{f['members']:,}",
        f"{f['central.bandit.cost']:.0f} NTD",
        f"{f['central.status_quo.violations']:,}",
        f"AUC {f['auc']:.2f}",
    ):
        assert n in page, n
    for v in prfaq.VARIANTS:
        assert f"{v} {f[f'{v}.claim'][0]:+.2f}" in page
    assert "simulated" in page.lower() and "WSDM Cup 2018" in page


def test_no_number_is_written_into_either_template(tmp_path, monkeypatch):
    data = json.loads(prfaq.SUMMARY.read_text(encoding="utf-8"))

    def scale(x, path="", factor=0.93):
        if isinstance(x, bool):
            return x
        if isinstance(x, int):
            return x * 2
        if isinstance(x, float):
            return x * factor
        if isinstance(x, dict):
            own = 0.6 + (sum(map(ord, path)) % 35) / 100
            interval = {"point", "lo", "hi"} <= set(x)
            return {k: scale(v, f"{path}.{k}", factor if interval else own) for k, v in x.items()}
        if isinstance(x, list):
            return [scale(v, f"{path}[{i}]", factor) for i, v in enumerate(x)]
        return x

    keep = {"schema_version", "run_id", "git_sha", "config_hash", "simulator_hash"}
    fake = tmp_path / "summary.json"
    scaled = {k: (v if k in keep else scale(v, k)) for k, v in data.items()}
    fake.write_text(json.dumps(scaled), encoding="utf-8")
    pattern = r"[+-]?\d[\d,]*\.?\d*%?"

    def numbers() -> list[str]:
        text = project_page.page() + project_page.script()
        text = re.sub(r"\| \d:\d\d \|", "|", text)  # timestamps are the script's own
        text = re.sub(r"Narration: \d+ words, about \d+ seconds", "", text)
        text = html.unescape(re.sub(r"<style>.*?</style>|<[^>]+>", " ", text))  # prose only
        return re.findall(pattern, text)

    real = numbers()
    monkeypatch.setattr(prfaq, "SUMMARY", fake)
    other = numbers()
    assert len(real) == len(other)
    constants = {a for a, b in zip(real, other, strict=True) if a == b}
    # the challenge's year, a unit, the video's length, and the holdout share the config fixes
    assert constants <= {"2018", "1,000", "90", "10%"}, constants


def test_the_video_script_fits_ninety_seconds_and_labels_results_simulated():
    text = (SITE / "video-script.md").read_text(encoding="utf-8")
    words = project_page.narration_words(text)
    assert words / project_page.WORDS_PER_SECOND <= 90
    times = [int(m) * 60 + int(s) for m, s in re.findall(r"^\| (\d):(\d\d) \|", text, re.M)]
    assert times == sorted(times) and times[0] == 0 and times[-1] < 90
    rows = re.findall(r"^\| \d:\d\d \| [^|]+ \| ([^|]+) \|$", text, re.M)
    slots = [b - a for a, b in zip(times, [*times[1:], 90], strict=True)]
    for (narration, slot), start in zip(zip(rows, slots, strict=True), times, strict=True):
        spoken = len(narration.split()) / project_page.WORDS_PER_SECOND
        assert spoken <= slot, f"the beat at {start} s needs {spoken:.1f} s of its {slot} s"
    assert "**Simulated**" in text
    f = prfaq.facts()
    assert f"{f['central.bandit.cost']:.0f} N T D" in text and f"{f['members']:,}" in text


def test_every_link_points_at_a_published_place():
    page = (SITE / "case-study.html").read_text(encoding="utf-8")
    hrefs = re.findall(r'href="([^"]+)"', page)
    assert set(hrefs) == set(project_page.LINKS.values())
    site = "https://biplob819.github.io/respectful-offers/"
    for url in hrefs:
        if url.startswith(site):  # served from the Pages site: the file must be built into it
            rel = url[len(site) :] or "index.html"
            assert (SITE / rel).is_file() or (ROOT / "results/kkbox/report" / rel).is_file()
        elif "/blob/main/" in url:
            assert (ROOT / url.split("/blob/main/", 1)[1]).is_file(), url


@pytest.mark.skipif(os.environ.get("OFFERS_CHECK_LINKS") != "1", reason="set OFFERS_CHECK_LINKS=1")
@pytest.mark.parametrize("url", list(project_page.LINKS.values()))
def test_every_link_resolves_live(url):
    if url.startswith("https://pypi.org/project/"):  # the page answers 200 even when missing
        url = url.replace("/project/", "/pypi/").rstrip("/") + "/json"
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    req = urllib.request.Request(url, headers={"User-Agent": "respectful-offers-link-check"})
    fetch = opener.open  # an HTTP request, not a text file: no encoding applies
    with fetch(req, timeout=30) as r:
        assert r.status == 200, (url, r.status)
