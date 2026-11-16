#!/usr/bin/env python3
"""The README's headline (REL-01): one chart and three sentences, built from the published
`results/kkbox/summary.json` so they can never drift from it (a test regenerates both).

    uv run python scripts/readme_assets.py          # rewrite docs/img/headline.svg and the
                                                    # README block between the headline markers
    uv run python scripts/readme_assets.py --check  # exit 1 if either is stale
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "results" / "kkbox" / "summary.json"
SVG = ROOT / "docs" / "img" / "headline.svg"
README = ROOT / "README.md"
START, END = "<!-- headline:start -->", "<!-- headline:end -->"
POLICIES = ("bandit", "rule_following_baseline", "status_quo")
VARIANTS = ("conservative", "central", "optimistic")
STYLE = (
    "<style>:root{--fg:#1d1d1f;--muted:#5f6368;--line:#d9dce1;--c-grey:#6b7280;"
    "--c-orange:#d55e00;--c-blue:#0072b2;--c-green:#009e73;--c-purple:#7a4fa3}"
    "@media (prefers-color-scheme:dark){:root{--fg:#e8eaed;--muted:#a8adb4;--line:#3a3d42;"
    "--c-orange:#f08a4b;--c-blue:#56b4e9;--c-green:#3fcf9f}}"
    ".chart text{fill:var(--fg);font:12px system-ui,sans-serif}.chart .tick{fill:var(--muted)}"
    ".chart .grid{stroke:var(--line);stroke-width:1}.chart .label{font-weight:600}</style>"
)


def _summary():
    from respectful_offers.schemas.summary import RunSummary

    return RunSummary.model_validate_json(SUMMARY.read_text(encoding="utf-8"))


def _row(s, variant: str, policy: str):
    return next(p for p in s.policies if p.variant == variant and p.policy == policy)


def _comparison(s, variant: str):
    return next(
        c
        for c in s.comparisons
        if c.variant == variant
        and {c.a, c.b} == {"bandit", "rule_following_baseline"}
        and c.metric == "incremental_retained_per_1000_ntd"
    )


def chart_svg() -> str:
    from respectful_offers.report.svg import POLICY_LABEL, Point, dot_chart

    s = _summary()
    rows = []
    for v in VARIANTS:
        for name in POLICIES:
            c = _row(s, v, name).cost_per_incremental_retained
            assert c is not None
            rows.append((f"{v}: {POLICY_LABEL[name]}", name, Point(c.point, 0, c.lo, c.hi)))
    body = dot_chart(
        rows,
        "Discount spent per extra member kept, NTD (95% interval); lower is better",
        "Discount cost per extra member kept, by simulator variant (simulated)",
        "Real KKBox members, simulated offer responses. For each of three pre-registered "
        "simulator variants, the discount each policy spends per extra member kept against "
        "no offer, with 95% bootstrap intervals.",
    )
    body = body.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
    return body.replace('class="chart">', f'class="chart">{STYLE}', 1) + "\n"


def headline() -> str:
    s = _summary()
    b, base, _ = (_row(s, "central", p) for p in POLICIES)
    cost = {}
    for p in POLICIES:
        c = _row(s, "central", p).cost_per_incremental_retained
        assert c is not None, f"{p} spent nothing"
        cost[p] = c
    diffs = {}
    for v in VARIANTS:
        c = _comparison(s, v)
        sign = 1 if c.a == "bandit" else -1
        assert c.separated and sign * c.diff.point > 0, f"the claim does not hold in {v}"
        diffs[v] = sign * c.diff.point
    n = b.n_members
    return "\n".join(
        [
            START,
            "![Discount spent per extra member kept, by policy and simulator variant: the "
            "bandit spends the least in every variant](docs/img/headline.svg)",
            "",
            f"On {n:,} real KKBox members with **simulated** offer responses, the respectful "
            f"bandit spent **{cost['bandit'].point:.0f} NTD** of discount per extra member kept, "
            f"against {cost['rule_following_baseline'].point:.0f} NTD for the rule-following "
            f"baseline and {cost['status_quo'].point:.0f} NTD for the status quo, which breaks "
            "both respect rules (central variant). "
            "That was the pre-registered claim, more members kept per 1,000 NTD of discount than "
            "the baseline, and it holds in all three simulator variants (central "
            f"{diffs['central']:+.2f}, conservative {diffs['conservative']:+.2f}, optimistic "
            f"{diffs['optimistic']:+.2f} members per 1,000 NTD; Holm-adjusted). "
            "In absolute terms the bandit keeps fewer extra members than the baseline "
            f"({b.incremental_retained_per_1000.point:.1f} against "
            f"{base.incremental_retained_per_1000.point:.1f} per 1,000, central): it leans on "
            "free content nudges and a cheaper plan instead of half-price months.",
            "",
            "> **Simulated.** KKBox's data holds no offers. Members, features, churn labels and "
            "churn risk are real; how a member responds to an offer comes from a pre-registered "
            "simulator (`configs/simulator.yaml`), and every result is reported under all three "
            "of its variants. Read the conclusions as conditional on those assumptions.",
            "",
            "```bash",
            "pip install respectful-offers",
            "offers report --example        # a full report from synthetic members, in seconds",
            "offers data download && offers run --all   # the published run (Kaggle token needed)",
            "```",
            "",
            "Data: [WSDM Cup 2018, KKBox's churn prediction challenge]"
            "(https://www.kaggle.com/competitions/kkbox-churn-prediction-challenge) on Kaggle, "
            "used under its rules for non-commercial research and education. No member data is "
            "in this repository.",
            END,
        ]
    )


def readme_with(text: str, block: str) -> str:
    if START not in text or END not in text:
        raise SystemExit(f"README.md needs the markers {START} and {END}")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    return head + block + tail


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    svg, readme = chart_svg(), readme_with(README.read_text(encoding="utf-8"), headline())
    if args.check:
        stale = [
            str(p.relative_to(ROOT))
            for p, want in ((SVG, svg), (README, readme))
            if not p.is_file() or p.read_text(encoding="utf-8") != want
        ]
        if stale:
            print(f"stale: {stale}; run scripts/readme_assets.py", file=sys.stderr)
            return 1
        return 0
    SVG.parent.mkdir(parents=True, exist_ok=True)
    SVG.write_text(svg, encoding="utf-8", newline="\n")
    README.write_text(readme, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
