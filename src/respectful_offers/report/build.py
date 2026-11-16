"""The static results report (Tech Spec B2.1, OWNER D-15).

`build_report(run_dir, simulator_yaml, out_dir)` reads `summary.json` and `frontier.json`
from a run folder and writes `index.html` (self-contained: inline CSS and SVG, no scripts,
no external requests) plus a `charts/` folder of Vega-Lite specs with their data inline.

Rules the HTML keeps, each checked by parsing the rendered page in the tests:
- every figure or table whose numbers depend on the simulator is a `<figure
  data-simulated="true">` or `<section data-simulated="true">` that shows the word
  "Simulated" in its own visible text (RPT-03);
- the simulator YAML is quoted byte for byte inside `<pre id="simulator-yaml">` (RPT-04);
- the pre-registration status is stamped in the header (RPT-06);
- series are distinguished by marker shape and direct labels, not colour alone, and every
  chart has a table with the same numbers (RPT-06).
"""

from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path
from typing import Any

from respectful_offers.report.svg import (
    POLICY_LABEL,
    VARIANT_STYLE,
    Point,
    dot_chart,
    line_chart,
    reliability_chart,
)
from respectful_offers.schemas.summary import Interval, PolicySummary, RunSummary

ORDER = ("no_offer", "status_quo", "rule_following_baseline", "bandit", "segment_oracle")
RULES = ("R1", "R2", "R3", "R7", "R8")
ESTIMATORS = {"ips": "IPS", "snips": "SNIPS", "dr": "Doubly robust"}
SIM = '<span class="sim">Simulated</span>'


class ReportError(ValueError):
    pass


def _iv(iv: Interval | None, digits: int = 1) -> str:
    if iv is None:
        return '<span class="na">n/a</span>'
    return f"{iv.point:,.{digits}f} <small>[{iv.lo:,.{digits}f}, {iv.hi:,.{digits}f}]</small>"


def _policy(name: str) -> str:
    return escape(POLICY_LABEL.get(name, name))


def slug(text: str) -> str:
    """A safe HTML id from any string (variant names come from the user's config)."""
    return re.sub(r"[^a-z0-9_-]+", "-", text.lower()).strip("-") or "x"


def _figure(fig_id: str, title: str, chart: str, caption: str, table: str, simulated: bool) -> str:
    sim_attr = ' data-simulated="true"' if simulated else ""
    badge = f" {SIM}" if simulated else ""
    return (
        f'<figure id="{slug(fig_id)}"{sim_attr}><figcaption><h3>{escape(title)}{badge}</h3>'
        f"<p>{caption}</p></figcaption>{chart}"
        f"<details><summary>The numbers behind this chart</summary>{table}</details></figure>"
    )


def _table(head: list[str], rows: list[list[str]], caption: str = "") -> str:
    cap = f"<caption>{caption}</caption>" if caption else ""
    th = "".join(f'<th scope="col">{h}</th>' for h in head)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="scroll"><table>{cap}<thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def _by(summary: RunSummary, variant: str) -> dict[str, PolicySummary]:
    return {p.policy: p for p in summary.policies if p.variant == variant}


# -- sections ---------------------------------------------------------------------------------


def _headline(s: RunSummary, variant: str) -> str:
    rows = _by(s, variant)
    b, base = rows.get("bandit"), rows.get("rule_following_baseline")
    if b is None or base is None:
        return ""
    comp = next(
        (
            c
            for c in s.comparisons
            if c.variant == variant
            and {c.a, c.b} == {"bandit", "rule_following_baseline"}
            and c.metric == "incremental_retained_per_1000_ntd"
        ),
        None,
    )
    if b.discount_cost_total == 0 or base.discount_cost_total == 0:
        reason = "one of them spent nothing, so members per discount dollar is undefined"
    else:
        reason = "this summary has no comparison on that metric"
    verdict = (
        "The pre-registered claim, that the bandit keeps more members per discount dollar than "
        f"the rule-following baseline, cannot be tested here: {reason}."
    )
    if comp is not None:
        sign = 1 if comp.a == "bandit" else -1
        diff = sign * comp.diff.point
        lo, hi = sorted((sign * comp.diff.lo, sign * comp.diff.hi))
        result = (
            "the bandit keeps more members per discount dollar"
            if comp.separated and diff > 0
            else "the rule-following baseline keeps more members per discount dollar"
            if comp.separated
            else "a tie: the claim is not supported in this variant"
        )
        verdict = (
            f"Pre-registered claim, extra members kept per 1,000 NTD of discount, bandit minus "
            f"rule-following baseline: <strong>{diff:+.2f}</strong> (95% interval {lo:+.2f} to "
            f"{hi:+.2f}; Holm-adjusted p = {comp.p_value:.4f}), so <strong>{result}</strong>. "
            "Other variants are in the comparisons table."
        )
    return (
        f'<section id="headline" data-simulated="true"><h2>Headline, {escape(variant)} variant {SIM}</h2>'
        f"<p>Retained per 1,000 members after {len(b.spend)} months: bandit "
        f"<strong>{b.retained_per_1000.point:,.1f}</strong>, rule-following baseline "
        f"<strong>{base.retained_per_1000.point:,.1f}</strong>, with discount spend of "
        f"{b.discount_cost_total:,.0f} and {base.discount_cost_total:,.0f} NTD. {verdict}</p></section>"
    )


def _policy_table(s: RunSummary, variant: str) -> str:
    head = [
        "Policy",
        "Retained / 1,000",
        "Incremental / 1,000",
        "Retained / 1,000 at risk",
        "90-day value / member (NTD)",
        "Discount cost (NTD)",
        "Cost per extra member kept",
        "Offers / member-month",
        "No-offer share",
        "Exploration",
        "Violations",
    ]
    rows = []
    for name in ORDER:
        p = _by(s, variant).get(name)
        if p is None:
            continue
        v = sum(p.violations.values())
        rows.append(
            [
                _policy(name),
                _iv(p.retained_per_1000),
                _iv(p.incremental_retained_per_1000),
                _iv(p.retained_per_1000_at_risk),
                _iv(p.ltv_proxy_per_member, 2),
                f"{p.discount_cost_total:,.0f}",
                _iv(p.cost_per_incremental_retained, 0),
                _iv(p.offers_per_member_month, 3),
                f"{p.no_offer_share:.1%}",
                "n/a" if p.exploration_rate is None else f"{p.exploration_rate:.1%}",
                f'<span class="{"bad" if v else "ok"}">{v:,}{" ✗" if v else " ✓"}</span>',
            ]
        )
    return (
        f'<section id="{slug("policies-" + variant)}" data-simulated="true">'
        f"<h3>Every policy, {escape(variant)} variant {SIM}</h3>"
        f"{_table(head, rows, 'Point estimates with 95% block-bootstrap intervals in brackets.')}</section>"
    )


def _frontier(frontier: dict[str, Any], variant: str) -> str:
    series: dict[str, list[Point]] = {}
    for r in frontier["frontier"]:
        if r["variant"] != variant:
            continue
        series.setdefault(r["policy"], []).append(
            Point(
                r["spend_per_member"],
                r["retained_per_1000"],
                r.get("retained_lo"),
                r.get("retained_hi"),
            )
        )
    if not series:
        return ""
    chart = line_chart(
        series,
        "Discount spend per member over the horizon (NTD)",
        "Retained per 1,000",
        f"Retained against spend, {variant}",
        "One line per policy across the budget sweep.",
    )
    rows = [
        [
            _policy(r["policy"]),
            f"{r['budget_per_1000']:,.0f}",
            f"{r['spend_per_member']:.3f}",
            f"{r['retained_per_1000']:.1f}",
            f"{r['incremental_per_1000']:.1f}",
        ]
        for r in frontier["frontier"]
        if r["variant"] == variant
    ]
    table = _table(
        [
            "Policy",
            "Budget / 1,000 / month",
            "Spend / member",
            "Retained / 1,000",
            "Incremental / 1,000",
        ],
        rows,
    )
    return _figure(
        f"frontier-{variant}",
        f"Retained against spend, {variant} variant",
        chart,
        "Each point is one budget level; further up and to the left is better.",
        table,
        True,
    )


def _variants(s: RunSummary) -> str:
    rows = []
    for name in ORDER:
        for v in s.variants:
            p = _by(s, v).get(name)
            if p is not None and name != "no_offer":
                iv = p.incremental_retained_per_1000
                rows.append(
                    (
                        f"{POLICY_LABEL.get(name, name)} · {v}",
                        name,
                        Point(iv.point, 0, iv.lo, iv.hi),
                    )
                )
    if not rows:
        return ""
    chart = dot_chart(
        rows,
        "Incremental retained per 1,000 against no offer",
        "Incremental retention by variant",
        "Dots with 95% intervals; the vertical line is zero.",
        reference=0.0,
    )
    table = _table(
        ["Policy · variant", "Incremental / 1,000"],
        [[escape(r[0]), f"{r[2].x:.1f} [{r[2].lo:.1f}, {r[2].hi:.1f}]"] for r in rows],
    )
    return _figure(
        "variants",
        f"The {NUMBERS.get(len(s.variants), str(len(s.variants)))} variants side by side"
        if len(s.variants) > 1
        else "Incremental retention",
        chart,
        "A scenario analysis, not an interval: the variants are never pooled.",
        table,
        True,
    )


def _comparisons(s: RunSummary) -> str:
    rows = []
    for c in s.comparisons:
        rows.append(
            [
                escape(c.variant),
                escape(c.metric.replace("_", " ")),
                f"{_policy(c.a)} − {_policy(c.b)}",
                _iv(c.diff, 2),
                f"{c.p_value:.4f}",
                "separated" if c.separated else "tie",
            ]
        )
    return (
        f'<section id="comparisons" data-simulated="true"><h3>Paired comparisons {SIM}</h3>'
        f"<p>Differences on shared bootstrap resamples; Holm correction at 5% per metric and variant. "
        f"A tie means the interval includes zero or Holm did not reject.</p>"
        f"{_table(['Variant', 'Metric', 'Difference', 'Estimate', 'p', 'Verdict'], rows)}</section>"
    )


def _ope(s: RunSummary) -> str:
    out = []
    for v in s.variants:
        rows, trows = [], []
        oracle = None
        for o in s.ope:
            if o.variant != v:
                continue
            rows.append(
                (
                    f"{POLICY_LABEL.get(o.policy, o.policy)} · {ESTIMATORS[o.estimator]}",
                    o.policy,
                    Point(o.value.point, 0, o.value.lo, o.value.hi, o.oracle),
                )
            )
            trows.append(
                [
                    _policy(o.policy),
                    ESTIMATORS[o.estimator],
                    _iv(o.value, 2),
                    f"{o.oracle:.2f}",
                    "yes ✓" if o.covered else '<span class="bad">no ✗</span>',
                    f"{o.effective_sample_size:,.0f}",
                ]
            )
            oracle = o.oracle if oracle is None else oracle
        if not rows:
            continue
        chart = dot_chart(
            rows,
            "Period-1 net revenue per member (NTD)",
            f"Off-policy estimates, {v}",
            "Estimates with 95% intervals; the black tick on each row is the exact oracle value.",
        )
        table = _table(
            ["Target", "Estimator", "Estimate", "Exact oracle", "Covered", "Effective sample"],
            trows,
        )
        out.append(
            _figure(
                f"ope-{v}",
                f"Off-policy estimates against the exact oracle, {v} variant",
                chart,
                "Estimated from the randomised logging pilot at period 1 and scored against the "
                "simulator's exact value, the black tick on each row. This validates the estimators; "
                "the rollouts are the headline.",
                table,
                True,
            )
        )
    return "".join(out)


def _learning(frontier: dict[str, Any]) -> str:
    series: dict[str, list[Point]] = {}
    for v, d in frontier.get("bandit", {}).items():
        series[v] = [Point(c["period"], c["value"]) for c in d.get("learning_curve", [])]
    if not series:
        return ""
    chart = line_chart(
        series,
        "Training periods",
        "Greedy period-1 value per member (NTD)",
        "Bandit learning curve",
        "One line per variant.",
        styles=VARIANT_STYLE,
        labels={v: v.capitalize() for v in series},
    )
    rows = [[escape(v), str(int(p.x)), f"{p.y:.3f}"] for v, ps in series.items() for p in ps]
    return _figure(
        "learning",
        "Bandit learning curve",
        chart,
        "Value of acting greedily on the posterior after each training epoch.",
        _table(["Variant", "Training periods", "Value"], rows),
        True,
    )


NUMBERS = {2: "two", 3: "three", 4: "four", 5: "five"}
LABELS = {
    "kaggle": "real KKBox labels, not simulated",
    "local": "labels from the verified local files, not simulated",
    "your_table": "labels from your own table, not simulated",
    "synthetic": "synthetic members and labels, generated for testing: not simulated outcomes, and not real people",
}
CITATION = {  # OWNER D-46: every published output built from KKBox data cites the challenge
    "kaggle": (
        'Data: <a href="https://www.kaggle.com/competitions/kkbox-churn-prediction-challenge">'
        "WSDM Cup 2018, KKBox's churn prediction challenge</a> (Kaggle), used under its rules for "
        "non-commercial research and education. No member data is published: this page holds "
        "aggregates only."
    ),
}
SOURCE = {
    "kaggle": "Members: real, anonymised KKBox subscribers",
    "local": "Members: from verified local data files",
    "your_table": "Members: from your own features table",
    "synthetic": "Members: synthetic, generated for testing, not real people",
}


def _churn(s: RunSummary, model_card: dict[str, Any] | None) -> str:
    c = s.churn
    chart = reliability_chart(
        c.reliability, "Churn model reliability", "Bins of predicted risk against observed churn."
    )
    rows = [[f"{p:.3f}", f"{o:.3f}", f"{n:,}"] for p, o, n in c.reliability]
    fig = _figure(
        "reliability",
        f"Churn model reliability ({LABELS[s.data_source]})",
        chart,
        "Calibrated March risk against observed March churn; the diagonal is perfect calibration.",
        _table(["Predicted", "Observed", "Members"], rows),
        False,
    )
    card = _table(
        ["Measure", "Value"],
        [
            ["AUC", _iv(c.auc, 3)],
            ["Brier score", _iv(c.brier, 4)],
            ["Expected calibration error", f"{c.ece:.4f}"],
            ["Two-feature baseline AUC", _iv(c.baseline_auc, 3)],
            ["Features", escape(", ".join(c.features))],
        ],
    )
    extra = ""
    if model_card:
        extra = (
            f"<p>Model: {escape(str(model_card.get('model', '')))}; protected attributes used: "
            f"{escape(str(model_card.get('protected_attributes_used', [])))}.</p>"
        )
    return f'<section id="churn"><h2>Churn model card</h2>{card}{extra}{fig}</section>'


def _audit_rollouts(audit: dict[str, Any] | None) -> str:
    if audit is None:
        return (
            '<p class="bad">No audit.json was found beside this summary, so the audit of the '
            "holdout, the logging pilot and the budget sweep cannot be shown.</p>"
        )
    rows, failed = [], []
    for a in audit.get("rollouts", []):
        total = sum(a["violations"].values())
        if a["respectful"] and total:
            failed.append(a)
        rows.append(
            [
                _policy(a["policy"]),
                escape(a["variant"]),
                escape(a["rollout"]),
                "yes" if a["respectful"] else "no",
                *(f"{a['violations'].get(r, 0):,}" for r in RULES),
            ]
        )
    banner = (
        '<p class="ok">Every respectful rollout audited clean ✓</p>'
        if audit.get("clean") and not failed
        else f'<p class="bad">AUDIT FAILED ✗: {len(failed)} respectful rollout(s) broke a rule. '
        "These results must not be published.</p>"
    )
    table = _table(["Policy", "Variant", "Rollout", "Respectful", *RULES], rows)
    return (
        f"{banner}<details><summary>Every audited rollout ({len(rows)})</summary>{table}</details>"
    )


def _audit(s: RunSummary, audit: dict[str, Any] | None) -> str:
    rows = []
    for p in s.policies:
        cells = [
            f'<span class="{"bad" if p.violations.get(r, 0) else "ok"}">{p.violations.get(r, 0):,}</span>'
            for r in RULES
        ]
        rows.append(
            [
                _policy(p.policy),
                escape(p.variant),
                "yes" if p.respectful else "no (reported, OWNER D-17)",
                *cells,
            ]
        )
    hold = [
        [
            escape(v),
            _iv(iv, 1),
            "consistent ✓" if iv.lo <= 0 <= iv.hi else '<span class="bad">holdout differs ✗</span>',
        ]
        for v, iv in s.holdout_check.items()
    ]
    return (
        f'<section id="audit" data-simulated="true"><h2>Respect audit {SIM}</h2>'
        "<p>An independent auditor re-derives every rule from the logs. R1 never re-offer a declined "
        "action; R2 a nudge before any discount for members at risk; R3 never contact the holdout; "
        "R7 decisions use allow-listed features only; R8 one decision per member per month.</p>"
        f"{_audit_rollouts(audit)}"
        f"{_table(['Policy', 'Variant', 'Respectful', *RULES], rows)}"
        f"<h3>Holdout check {SIM}</h3><p>Holdout retention minus no-offer retention on the "
        f"evaluation members, per 1,000; the interval should contain zero.</p>"
        f"{_table(['Variant', 'Difference / 1,000', 'Verdict'], hold)}</section>"
    )


def _disparity(s: RunSummary, variant: str) -> str:
    if not s.disparity:
        return ""
    rows = []
    for key in sorted(s.disparity):
        parts = key.split(".")
        policy, metric, attr = parts if len(parts) == 3 else ("", "offer_rate", parts[0])
        for group, iv in sorted(s.disparity[key].items()):
            digits = 3 if metric == "offer_rate" else 1
            rows.append(
                [
                    _policy(policy) if policy else "",
                    escape(metric.replace("_", " ")),
                    escape(attr.replace("_", " ")),
                    escape(group),
                    _iv(iv, digits),
                ]
            )
    return (
        f'<section id="disparity" data-simulated="true"><h2>Disparity audit {SIM}</h2>'
        f"<p>{escape(variant.capitalize())} variant. Age band and gender are audited, never used to decide (R7). "
        "Groups under 30 members are not shown, nor is one more group when that would reveal them.</p>"
        f"{_table(['Policy', 'Measure', 'Attribute', 'Group', 'Estimate'], rows)}</section>"
    )


def _pre_text(text: str) -> str:
    """Escape for a <pre> so a browser shows exactly these characters: a newline right after
    the tag (browsers drop one there), and carriage returns as character references."""
    return "\n" + escape(text, quote=False).replace("\r", "&#13;")


def _yaml(simulator_yaml: str, sha: str) -> str:
    return (
        '<section id="simulator"><h2>The simulator, quoted in full</h2>'
        f"<p>Every simulated number above comes from this file (sha256 <code>{escape(sha)}</code>), "
        "all three variants, byte for byte.</p>"
        f'<pre id="simulator-yaml" tabindex="0">{_pre_text(simulator_yaml)}</pre></section>'
    )


CSS = """
:root{--bg:#fff;--fg:#1d1d1f;--muted:#5f6368;--line:#d9dce1;--panel:#f6f7f9;--accent:#0b57d0;
--bad:#b3261e;--ok:#146c2e;--c-grey:#6b7280;--c-orange:#d55e00;--c-blue:#0072b2;--c-green:#009e73;
--c-purple:#7a4fa3}
@media (prefers-color-scheme:dark){:root{--bg:#121316;--fg:#e8eaed;--muted:#a8adb4;--line:#3a3d42;
--panel:#1c1e22;--accent:#8ab4f8;--bad:#f2b8b5;--ok:#7dd99b;--c-grey:#9aa0a6;--c-orange:#f08a4b;
--c-blue:#56b4e9;--c-green:#3fcf9f;--c-purple:#c39be8}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1040px;margin:0 auto;padding:24px 16px 64px}
header{border-bottom:1px solid var(--line);padding-bottom:12px;margin-bottom:24px}
h1{font-size:1.8rem;margin:0 0 4px}h2{font-size:1.35rem;margin:40px 0 8px}h3{font-size:1.08rem;margin:24px 0 8px}
.stamp{display:inline-block;padding:2px 10px;border-radius:999px;border:1px solid var(--line);
background:var(--panel);font-size:.85rem;margin-right:6px}
.sim{display:inline-block;font-size:.75rem;font-weight:600;letter-spacing:.02em;padding:1px 8px;
border-radius:4px;border:1px dashed var(--muted);color:var(--muted);vertical-align:middle}
figure{margin:24px 0;padding:16px;border:1px solid var(--line);border-radius:10px;background:var(--panel)}
figcaption p{color:var(--muted);margin:0 0 8px}.chart{width:100%;height:auto;display:block}
.chart text{fill:var(--fg);font:12px system-ui,sans-serif}.chart .tick{fill:var(--muted)}
.chart .grid{stroke:var(--line);stroke-width:1}.chart .axis{stroke:var(--muted)}
.chart .ref{stroke:var(--muted);stroke-dasharray:4 4}.chart .oracle{stroke:var(--fg);stroke-width:2.5}.chart .label{font-weight:600}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:.9rem;margin:8px 0}
caption{text-align:left;color:var(--muted);padding:4px 0}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{font-weight:600}small{color:var(--muted)}.bad{color:var(--bad);font-weight:600}.ok{color:var(--ok)}
.na{color:var(--muted)}pre{background:var(--panel);border:1px solid var(--line);border-radius:8px;
padding:12px;overflow:auto;font-size:.82rem;max-height:520px}
details summary{cursor:pointer;color:var(--accent);margin-top:8px}
a{color:var(--accent)}:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
nav ul{display:flex;flex-wrap:wrap;gap:4px 16px;padding:0;list-style:none}
"""


def render(
    summary: RunSummary,
    frontier: dict[str, Any],
    simulator_yaml: str,
    simulator_sha: str,
    model_card: dict[str, Any] | None = None,
    audit: dict[str, Any] | None = None,
) -> str:
    if summary.simulated is not True:
        raise ReportError("only simulated summaries can be reported")
    lead = "central" if "central" in summary.variants else summary.variants[0]
    stamp = (
        "Pre-registered simulator"
        if summary.prereg_status == "preregistered"
        else "Exploratory run: not pre-registered, never to be published"
    )
    headline = _headline(summary, lead)
    disparity = _disparity(summary, lead)
    present = {"headline": bool(headline), "disparity": bool(disparity)}
    nav = "".join(
        f'<li><a href="#{a}">{t}</a></li>'
        for a, t in (
            ("headline", "Headline"),
            ("results", "Results"),
            ("ope", "Off-policy"),
            ("audit", "Audit"),
            ("disparity", "Disparity"),
            ("churn", "Churn model"),
            ("simulator", "Simulator"),
        )
        if present.get(a, True)
    )
    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Respectful Offers results</title>"
        f"<style>{CSS}</style></head><body><main>",
        "<header><h1>Respectful Offers: results</h1>"
        f'<p><span class="stamp" id="prereg-stamp">{escape(stamp)}</span>'
        f'<span class="stamp" id="sim-stamp">{SIM} outcomes from a simulator, not live members</span>'
        f'<span class="stamp" id="data-stamp">{escape(SOURCE[summary.data_source])}</span>'
        f'<span class="stamp">run {escape(summary.run_id)} · commit {escape(summary.git_sha[:12])}</span></p>'
        f'<nav aria-label="Sections"><ul>{nav}</ul></nav></header>',
        headline,
        '<section id="results"><h2>Results</h2>',
        *(_policy_table(summary, v) for v in summary.variants),
        *(_frontier(frontier, v) for v in summary.variants),
        _variants(summary),
        _comparisons(summary),
        _learning(frontier),
        "</section>",
        f'<section id="ope"><h2>Off-policy evaluation, validated {SIM}</h2>{_ope(summary)}</section>',
        _audit(summary, audit),
        disparity,
        _churn(summary, model_card),
        _yaml(simulator_yaml, simulator_sha),
        f"<footer><p>Schema {escape(summary.schema_version)} · config {escape(summary.config_hash)} · "
        f"simulator {escape(summary.simulator_hash)} · started {summary.started_at.isoformat()}</p>"
        + (
            f'<p id="citation">{CITATION[summary.data_source]}</p>'
            if summary.data_source in CITATION
            else ""
        )
        + "</footer>",
        "</main></body></html>\n",
    ]
    return "".join(parts)


def vega_specs(summary: RunSummary, frontier: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Vega-Lite specs with inline data, alongside the HTML (OWNER D-15)."""
    base = "https://vega.github.io/schema/vega-lite/v5.json"
    specs: dict[str, dict[str, Any]] = {
        "frontier": {
            "$schema": base,
            "title": "Retained against spend (Simulated)",
            "data": {"values": frontier["frontier"]},
            "mark": {"type": "line", "point": True},
            "encoding": {
                "x": {"field": "spend_per_member", "type": "quantitative"},
                "y": {"field": "retained_per_1000", "type": "quantitative"},
                "color": {"field": "policy"},
                "shape": {"field": "policy"},
                "facet": {"field": "variant"},
            },
        },
        "ope": {
            "$schema": base,
            "title": "Off-policy estimates against the exact oracle (Simulated)",
            "data": {"values": [json.loads(o.model_dump_json()) for o in summary.ope]},
            "mark": "point",
            "encoding": {
                "x": {"field": "value.point", "type": "quantitative"},
                "y": {"field": "policy"},
                "shape": {"field": "estimator"},
                "color": {"field": "covered"},
            },
        },
        "policies": {
            "$schema": base,
            "title": "Incremental retained per 1,000 (Simulated)",
            "data": {"values": [json.loads(p.model_dump_json()) for p in summary.policies]},
            "mark": "point",
            "encoding": {
                "x": {"field": "incremental_retained_per_1000.point", "type": "quantitative"},
                "y": {"field": "policy"},
                "shape": {"field": "variant"},
            },
        },
    }
    return specs


def _load_json(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReportError(f"{path}: cannot read {what}: {exc}") from None


def build_report(
    run_dir: Path, simulator_yaml: Path, out_dir: Path, model_card: Path | None = None
) -> Path:
    from pydantic import ValidationError

    from respectful_offers.sim.prereg import sha256

    summary_path, frontier_path = run_dir / "summary.json", run_dir / "frontier.json"
    for p in (summary_path, frontier_path):
        if not p.is_file():
            raise ReportError(f"{p} is missing: run `offers evaluate` first")
    if not simulator_yaml.is_file():
        raise ReportError(
            f"no simulator file at {simulator_yaml}: pass --simulator with the file the run used"
        )
    out_dir = Path(out_dir)
    if out_dir.exists() and not out_dir.is_dir():
        raise ReportError(f"{out_dir} is a file: --out must be a folder")
    if out_dir.resolve() == run_dir.resolve() or run_dir.resolve() in out_dir.resolve().parents:
        raise ReportError(
            "--out must not be inside the run folder: a report never writes into a run"
        )
    try:
        summary = RunSummary.model_validate_json(summary_path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise ReportError(
            f"{summary_path} is not a valid summary ({exc.error_count()} problems; first: {exc.errors()[0]['msg']})"
        ) from None
    frontier = _load_json(frontier_path, "the frontier")
    if not isinstance(frontier, dict) or not isinstance(frontier.get("frontier"), list):
        raise ReportError(f"{frontier_path} has no 'frontier' list: rerun `offers evaluate`")
    audit_path = run_dir / "audit.json"
    audit = _load_json(audit_path, "the audit") if audit_path.is_file() else None
    if audit is not None and not isinstance(audit, dict):
        raise ReportError(f"{audit_path} is not an audit record")
    raw = simulator_yaml.read_bytes()
    if b"\x00" in raw:
        raise ReportError(f"{simulator_yaml} contains a NUL byte; it cannot be quoted faithfully")
    sha = sha256(simulator_yaml)
    if not sha.startswith(summary.simulator_hash):
        raise ReportError(
            f"{simulator_yaml} (sha256 {sha[:16]}) is not the simulator this run used "
            f"({summary.simulator_hash}); quote the file the run used"
        )
    card = None
    if model_card is not None:
        card = _load_json(model_card, "the model card")
        if not isinstance(card, dict):
            raise ReportError(f"{model_card} is not a model card (expected a JSON object)")
    out_dir.mkdir(parents=True, exist_ok=True)
    html = render(summary, frontier, raw.decode("utf-8"), sha, card, audit)
    (out_dir / "index.html").write_text(html, encoding="utf-8", newline="\n")
    charts = out_dir / "charts"
    charts.mkdir(exist_ok=True)
    for name, spec in vega_specs(summary, frontier).items():
        (charts / f"{name}.vl.json").write_text(
            json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
    return out_dir / "index.html"
