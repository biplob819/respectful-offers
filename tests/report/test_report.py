"""B2.1: the static report, rendered from a real `offers evaluate` run and checked by parsing
the HTML (RPT-01..06, EvalKit L-28, L-38)."""

import json
import re
from html import escape as html_escape
from html.parser import HTMLParser
from pathlib import Path

import pytest

from harness_lib import ROOT
from respectful_offers import cli
from respectful_offers.report.build import ReportError, build_report, render
from respectful_offers.schemas.summary import RunSummary

SIM_YAML = ROOT / "configs" / "simulator.yaml"
VARIANTS = ("conservative", "central", "optimistic")


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    root = tmp_path_factory.mktemp("proj")
    data = root / "data"
    assert cli.main(["data", "synthetic", "--data-dir", str(data), "--members", "4000"]) == 0
    assert (
        cli.main(["evaluate", "--data-dir", str(data), "--root", str(root), "--run-id", "r"]) == 0
    )
    out = root / "report"
    assert cli.main(["report", "--root", str(root), "--run-id", "r", "--out", str(out)]) == 0
    return root, out, (out / "index.html").read_text(encoding="utf-8")


class Tree(HTMLParser):
    """Collects elements with their attributes and the visible text inside each."""

    VOID = frozenset(
        {"meta", "br", "img", "input", "link", "hr", "path", "line", "circle", "rect", "polygon"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict] = []
        self.elements: list[dict] = []
        self.pre: dict[str, str] = {}
        self._in_hidden = 0

    def handle_starttag(self, tag, attrs):
        el = {"tag": tag, "attrs": dict(attrs), "text": []}
        self.elements.append(el)
        if tag in self.VOID:
            return
        if tag in ("title", "desc", "style"):
            self._in_hidden += 1
        self.stack.append(el)

    def handle_startendtag(self, tag, attrs):
        self.elements.append({"tag": tag, "attrs": dict(attrs), "text": []})

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        while self.stack:
            el = self.stack.pop()
            if el["tag"] in ("title", "desc", "style"):
                self._in_hidden -= 1
            if el["tag"] == "pre" and "id" in el["attrs"]:
                self.pre[el["attrs"]["id"]] = "".join(el["text"])
            if el["tag"] == tag:
                break

    def handle_data(self, data):
        if self._in_hidden:
            return
        for el in self.stack:
            el["text"].append(data)


def browser_pre(t: "Tree", ident: str) -> str:
    """What a browser shows for a <pre>: it drops one newline right after the opening tag."""
    text = t.pre[ident]
    return text[1:] if text.startswith("\n") else text


def parse(html: str) -> Tree:
    t = Tree()
    t.feed(html)
    return t


def by_id(t: Tree, ident: str) -> dict:
    found = [e for e in t.elements if e["attrs"].get("id") == ident]
    assert found, ident
    return found[0]


# -- RPT-01 self-contained, all variants -------------------------------------------------------


def test_report_is_self_contained_and_covers_every_variant(run):
    _, out, html = run
    t = parse(html)
    assert not [e for e in t.elements if e["tag"] in ("script", "iframe", "img", "link")]
    external = [
        v
        for e in t.elements
        for k, v in e["attrs"].items()
        if k in ("src", "href") and v and not v.startswith("#")
    ]
    assert external == []
    assert "@import" not in html and "url(" not in html
    for v in VARIANTS:
        by_id(t, f"policies-{v}")
        by_id(t, f"frontier-{v}")
        by_id(t, f"ope-{v}")
    assert sorted(p.name for p in (out / "charts").iterdir()) == [
        "frontier.vl.json",
        "ope.vl.json",
        "policies.vl.json",
    ]


# -- RPT-02 charts -------------------------------------------------------------------------------


def test_every_chart_is_present_with_its_numbers(run):
    _, _, html = run
    t = parse(html)
    for ident in ("variants", "learning", "reliability", "comparisons", "headline"):
        by_id(t, ident)
    figures = [e for e in t.elements if e["tag"] == "figure"]
    assert len(figures) >= 3 * 2 + 3
    assert html.count("<svg") == len(figures)
    for fig in re.findall(r"<figure.*?</figure>", html, flags=re.S):
        assert fig.count("<svg") == 1 and fig.count("<details>") == 1  # every chart has its table


def test_frontier_numbers_match_frontier_json(run):
    root, _, html = run
    frontier = json.loads((root / "runs" / "r" / "frontier.json").read_text(encoding="utf-8"))
    t = parse(html)
    fig = "".join(by_id(t, "frontier-central")["text"])
    for row in frontier["frontier"]:
        if row["variant"] == "central":
            assert f"{row['retained_per_1000']:.1f}" in fig


# -- RPT-03 "Simulated" on every simulator-dependent element ------------------------------------


def test_every_simulated_element_says_so_and_only_the_churn_model_is_not(run):
    _, _, html = run
    t = parse(html)
    flagged = [e for e in t.elements if e["attrs"].get("data-simulated") == "true"]
    assert len(flagged) >= 12
    for e in flagged:
        assert "Simulated" in "".join(e["text"]), e["attrs"]
    unflagged = [
        e for e in t.elements if e["tag"] == "figure" and e["attrs"].get("data-simulated") != "true"
    ]
    assert [e["attrs"]["id"] for e in unflagged] == ["reliability"]  # real labels, not simulated


# -- RPT-04 YAML byte for byte -----------------------------------------------------------------


def test_simulator_yaml_is_quoted_byte_for_byte(run):
    _, _, html = run
    assert browser_pre(parse(html), "simulator-yaml") == SIM_YAML.read_bytes().decode("utf-8")
    for v in VARIANTS:
        assert f"  {v}:" in parse(html).pre["simulator-yaml"]


@pytest.mark.parametrize(
    "text", ["\nleading: blank line\n", "a: 1\r\nb: 2\r\n", "lone\rcr\n", "x: '<b>&amp;'\n"]
)
def test_awkward_yaml_survives_the_browser(run, text):
    root, _, _ = run
    s = RunSummary.model_validate_json(
        (root / "runs" / "r" / "summary.json").read_text(encoding="utf-8")
    )
    frontier = json.loads((root / "runs" / "r" / "frontier.json").read_text(encoding="utf-8"))
    assert browser_pre(parse(render(s, frontier, text, "x")), "simulator-yaml") == text


def test_a_different_simulator_file_is_refused(run, tmp_path):
    root, _, _ = run
    other = tmp_path / "sim.yaml"
    other.write_text(SIM_YAML.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    with pytest.raises(ReportError, match="not the simulator this run used"):
        build_report(root / "runs" / "r", other, tmp_path / "out")
    assert (
        cli.main(
            ["report", "--root", str(root), "--run-id", "missing", "--out", str(tmp_path / "x")]
        )
        == cli.EXIT_ERROR
    )


# -- RPT-05 audit, holdout, disparity, churn card ------------------------------------------------


def test_audit_holdout_disparity_and_churn_card(run):
    root, _, html = run
    s = RunSummary.model_validate_json(
        (root / "runs" / "r" / "summary.json").read_text(encoding="utf-8")
    )
    t = parse(html)
    audit = "".join(by_id(t, "audit")["text"])
    for p in s.policies:
        if p.policy == "status_quo":
            assert f"{p.violations['R2']:,}" in audit
    assert "Holdout check" in audit and audit.count("consistent ✓") == len(s.variants)
    assert "Every respectful rollout audited clean ✓" in audit
    disparity = "".join(by_id(t, "disparity")["text"])
    assert "age band" in disparity and "gender" in disparity
    churn = "".join(by_id(t, "churn")["text"])
    assert f"{s.churn.auc.point:,.3f}" in churn and "Expected calibration error" in churn


# -- RPT-06 accessibility and the pre-registration stamp ----------------------------------------


def test_charts_never_rely_on_colour_alone(run):
    _, _, html = run
    t = parse(html)
    assert by_id(t, "simulator-yaml")["attrs"].get("tabindex") == "0"
    assert html.startswith('<!doctype html><html lang="en">')
    for svg in re.findall(r"<svg.*?</svg>", html, flags=re.S):
        assert 'role="img"' in svg and "<title>" in svg and "<desc>" in svg
    from respectful_offers.report.svg import POLICY_STYLE

    shapes = [shape for _, shape in POLICY_STYLE.values()]
    assert len(set(shapes)) == len(shapes)  # every policy has its own marker shape
    assert 'aria-labelledby="t d"' not in html  # no references to ids that do not exist
    found = re.search(r'<figure id="frontier-central".*?</svg>', html, flags=re.S)
    assert found is not None
    frontier = found.group(0)
    assert "<rect" in frontier and frontier.count("<polygon") >= 2  # square, triangle, diamond
    for label in ("Bandit", "Rule-following", "Status quo"):
        assert f">{label}</text>" in frontier  # and by direct label


def test_a_failed_audit_is_shown_as_failed(run, tmp_path):
    root, _, _ = run
    import shutil

    copy = tmp_path / "run"
    shutil.copytree(root / "runs" / "r", copy)
    audit = json.loads((copy / "audit.json").read_text(encoding="utf-8"))
    audit["clean"] = False
    audit["rollouts"][0] = {
        **audit["rollouts"][0],
        "respectful": True,
        "violations": {r: (5 if r == "R1" else 0) for r in ("R1", "R2", "R3", "R7", "R8")},
    }
    (copy / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    html = (build_report(copy, SIM_YAML, tmp_path / "out")).read_text(encoding="utf-8")
    assert "AUDIT FAILED ✗" in html and "must not be published" in html


def test_stamps_tell_the_truth_about_registration_and_data(run):
    _, _, html = run
    t = parse(html)
    assert "pre-registered" not in "".join(by_id(t, "sim-stamp")["text"])
    assert "synthetic" in "".join(by_id(t, "data-stamp")["text"])  # the fixture run is synthetic
    assert "not real people" in "".join(by_id(t, "reliability")["text"])
    # the quoted simulator says it is registered for real runs; the run's own words never do
    quoted = SIM_YAML.read_text(encoding="utf-8")
    outside = html
    for form in (quoted, html_escape(quoted), html_escape(quoted, quote=False)):
        outside = outside.replace(form, "")
    assert outside != html, "the simulator is quoted on the page"
    assert "real KKBox" not in outside


def test_user_strings_never_become_markup(run):
    root, _, _ = run
    evil = 'c"><script>x()</script>'
    text = (
        (root / "runs" / "r" / "summary.json")
        .read_text(encoding="utf-8")
        .replace('"central"', json.dumps(evil))
    )
    s = RunSummary.model_validate_json(text)
    frontier_text = (
        (root / "runs" / "r" / "frontier.json")
        .read_text(encoding="utf-8")
        .replace('"central"', json.dumps(evil))
    )
    page = render(s, json.loads(frontier_text), SIM_YAML.read_text(encoding="utf-8"), "x")
    assert "<script" not in page
    ids = [e["attrs"]["id"] for e in parse(page).elements if "id" in e["attrs"]]
    assert all(re.fullmatch(r"[a-z0-9_-]+", i) for i in ids), ids


def test_frontier_points_carry_their_intervals(run):
    root, _, html = run
    frontier = json.loads((root / "runs" / "r" / "frontier.json").read_text(encoding="utf-8"))
    rows = [r for r in frontier["frontier"] if r["variant"] == "central"]
    assert all(r["retained_lo"] <= r["retained_per_1000"] <= r["retained_hi"] for r in rows)
    found = re.search(r'<figure id="frontier-central".*?</svg>', html, flags=re.S)
    assert found is not None
    assert found.group(0).count('stroke-width="1.5"') == len(rows)  # one whisker per point


def test_simulated_numbers_never_appear_outside_a_simulated_element(run):
    """The other direction of RPT-03: a digit in visible text sits inside a flagged element,
    or in the parts that are not simulated (churn card, simulator file, header, footer)."""
    _, _, html = run

    class Walker(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.stack: list[tuple[str, dict]] = []
            self.bad: list[str] = []

        def handle_starttag(self, tag, attrs):
            if tag not in Tree.VOID:
                self.stack.append((tag, dict(attrs)))

        def handle_endtag(self, tag):
            if tag in Tree.VOID:
                return
            while self.stack and self.stack.pop()[0] != tag:
                pass

        def handle_data(self, data):
            if not re.search(r"\d", data):
                return
            tags = [t for t, _ in self.stack]
            if {"title", "desc", "style", "header", "footer", "nav"} & set(tags):
                return
            attrs = [a for _, a in self.stack]
            if any(a.get("data-simulated") == "true" for a in attrs):
                return
            if any(a.get("id") in ("churn", "simulator") for a in attrs):
                return
            self.bad.append(data.strip())

    w = Walker()
    w.feed(html)
    assert w.bad == []


def test_cli_refuses_unsafe_or_missing_paths(run, tmp_path):
    root, _, _ = run
    base = ["report", "--root", str(root), "--run-id", "r"]
    assert cli.main([*base, "--out", str(root / "runs" / "r" / "rep")]) == cli.EXIT_ERROR
    f = tmp_path / "file"
    f.write_text("x", encoding="utf-8")
    assert cli.main([*base, "--out", str(f)]) == cli.EXIT_ERROR
    with pytest.raises(ReportError, match="pass --simulator"):
        build_report(root / "runs" / "r", tmp_path / "nope.yaml", tmp_path / "o")


def test_the_prereg_stamp_follows_the_summary(run):
    root, _, html = run
    assert "Pre-registered simulator" in "".join(by_id(parse(html), "prereg-stamp")["text"])
    s = RunSummary.model_validate_json(
        (root / "runs" / "r" / "summary.json").read_text(encoding="utf-8")
    )
    frontier = json.loads((root / "runs" / "r" / "frontier.json").read_text(encoding="utf-8"))
    exploratory = s.model_copy(update={"prereg_status": "exploratory"})
    page = render(exploratory, frontier, SIM_YAML.read_text(encoding="utf-8"), "x")
    assert "never to be published" in "".join(by_id(parse(page), "prereg-stamp")["text"])


def test_report_is_deterministic(run, tmp_path):
    root, out, html = run
    build_report(root / "runs" / "r", SIM_YAML, tmp_path / "again")
    assert (tmp_path / "again" / "index.html").read_text(encoding="utf-8") == html
    assert (
        Path(out / "charts" / "ope.vl.json").read_bytes()
        == (tmp_path / "again" / "charts" / "ope.vl.json").read_bytes()
    )
