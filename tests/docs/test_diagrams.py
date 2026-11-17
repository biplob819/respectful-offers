"""The data-flow and architecture diagrams, embedded by the portfolio page."""

import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from harness_lib import ROOT

IMG = ROOT / "docs" / "img"
NS = "{http://www.w3.org/2000/svg}"


def test_both_diagrams_are_current():
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "diagrams.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert out.returncode == 0, out.stderr


@pytest.mark.parametrize("name", ["dataflow.svg", "architecture.svg"])
def test_labels_are_real_text_on_a_white_background(name):
    root = ET.parse(IMG / name).getroot()
    assert root.tag == f"{NS}svg" and root.find(f"{NS}title") is not None
    first_rect = root.find(f"{NS}rect")
    assert first_rect is not None and first_rect.get("fill") == "#ffffff"
    texts = [t.text for t in root.iter(f"{NS}text") if t.text]
    assert len(texts) > 30
    assert root.find(f".//{NS}image") is None  # no raster, every label is text
