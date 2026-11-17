#!/usr/bin/env python3
"""The data-flow and architecture diagrams (`docs/img/dataflow.svg`, `docs/img/architecture.svg`).

Hand-placed boxes, every label real SVG text, a white background so they read anywhere
(the portfolio page embeds them). Generated so they stay byte-stable and reviewable:

    uv run python scripts/diagrams.py          # write both
    uv run python scripts/diagrams.py --check  # exit 1 if either is stale
"""

from __future__ import annotations

import argparse
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "img"

INK, MUTED, LINE = "#1d1d1f", "#5f6368", "#80868b"
FILLS = {
    "data": ("#e8f0fe", "#1a73e8"),
    "model": ("#e6f4ea", "#188038"),
    "policy": ("#fef7e0", "#b06000"),
    "check": ("#fce8e6", "#c5221f"),
    "out": ("#f3e8fd", "#8430ce"),
    "plain": ("#f8f9fa", "#80868b"),
}
FONT = "system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


class Svg:
    def __init__(self, w: int, h: int, title: str, desc: str) -> None:
        self.w, self.h = w, h
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" '
            f'height="{h}" role="img" aria-labelledby="t d" font-family="{FONT}">',
            f'<title id="t">{escape(title)}</title><desc id="d">{escape(desc)}</desc>',
            '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            f'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" '
            f'fill="{LINE}"/></marker></defs>',
            f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
        ]

    def text(
        self,
        x: float,
        y: float,
        s: str,
        size: int = 13,
        weight: int = 400,
        color: str = INK,
        anchor: str = "middle",
    ) -> None:
        self.parts.append(
            f'<text x="{x:g}" y="{y:g}" font-size="{size}" font-weight="{weight}" fill="{color}" '
            f'text-anchor="{anchor}">{escape(s)}</text>'
        )

    def box(
        self, x: float, y: float, w: float, h: float, lines: list[str], kind: str = "plain"
    ) -> tuple[float, float, float, float]:
        fill, stroke = FILLS[kind]
        self.parts.append(
            f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="8" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.5"/>'
        )
        top = y + h / 2 - (len(lines) - 1) * 8 + 5
        for i, s in enumerate(lines):
            self.text(
                x + w / 2,
                top + i * 16,
                s,
                13 if i == 0 else 11,
                600 if i == 0 else 400,
                INK if i == 0 else MUTED,
            )
        return (x, y, w, h)

    def arrow(
        self, x1: float, y1: float, x2: float, y2: float, label: str = "", dashed: bool = False
    ) -> None:
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        self.parts.append(
            f'<path d="M{x1:g},{y1:g} L{x2:g},{y2:g}" stroke="{LINE}" stroke-width="1.5" '
            f'fill="none" marker-end="url(#a)"{dash}/>'
        )
        if label:
            self.text((x1 + x2) / 2 + 6, (y1 + y2) / 2 - 4, label, 10, 400, MUTED, "start")

    def band(self, x: float, y: float, w: float, h: float, label: str) -> None:
        self.parts.append(
            f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="10" fill="none" '
            f'stroke="#dadce0" stroke-width="1" stroke-dasharray="4 4"/>'
        )
        self.text(x + 12, y + 18, label, 11, 600, MUTED, "start")

    def legend(self, y: float, items: list[tuple[str, str]]) -> None:
        x = 24.0
        for kind, label in items:
            fill, stroke = FILLS[kind]
            self.parts.append(
                f'<rect x="{x:g}" y="{y - 10:g}" width="14" height="14" rx="3" fill="{fill}" '
                f'stroke="{stroke}"/>'
            )
            self.text(x + 20, y + 1, label, 11, 400, MUTED, "start")
            x += 30 + 6.2 * len(label)

    def render(self) -> str:
        return "\n".join([*self.parts, "</svg>"]) + "\n"


def bottom(b):
    return b[0] + b[2] / 2, b[1] + b[3]


def top(b):
    return b[0] + b[2] / 2, b[1]


def dataflow() -> str:
    s = Svg(
        1000,
        860,
        "Respectful Offers data flow",
        "From the raw KKBox files to features, a calibrated churn model, a cohort split, "
        "a respect filter in front of every policy, simulated rollouts under common random "
        "numbers, an independent audit and off-policy checks, aggregated into the report, "
        "PR/FAQ, demo cube and EvalKit release gates. Every outcome is simulated.",
    )
    s.text(500, 34, "Respectful Offers: data flow", 20, 700)
    s.text(
        500,
        56,
        "Real KKBox members, simulated offer responses (frozen before the real run)",
        12,
        400,
        MUTED,
    )
    s.box(40, 84, 190, 56, ["KKBox raw files", "members, transactions, logs"], "data")
    s.box(280, 84, 190, 56, ["Ingest (DuckDB)", "verified by sha256 manifest"], "data")
    s.box(520, 84, 190, 56, ["Features as of a date", "no future data (leak tests)"], "data")
    chu = s.box(760, 84, 200, 56, ["Churn model", "gradient boosting + isotonic"], "model")
    s.arrow(230, 112, 280, 112)
    s.arrow(470, 112, 520, 112)
    s.arrow(710, 112, 760, 112)
    sco = s.box(760, 180, 200, 56, ["Risk scores, March", "AUC 0.84 vs 0.72 baseline"], "model")
    s.arrow(*bottom(chu), *top(sco))
    spl = s.box(
        330,
        180,
        340,
        56,
        ["Cohort split (salted hash)", "holdout · train · logging · eval"],
        "data",
    )
    s.arrow(760, 208, 670, 208)
    s.box(40, 180, 240, 56, ["Response simulator", "3 variants, pre-registered sha256"], "policy")
    s.band(30, 262, 940, 210, "Policies: every respectful policy sits behind the respect filter")
    res = s.box(
        330,
        290,
        340,
        50,
        ["Respect filter (pure function)", "R1 a declined offer stays declined · R2 content first"],
        "check",
    )
    s.arrow(*bottom(spl), *top(res))
    pols = [
        ("Thompson sampling bandit", "trained on the train cohort"),
        ("Rule-following baseline", "same rules, no learning"),
        ("Status quo", "no filter: shown for contrast"),
        ("No offer / segment oracle", "floor and ceiling"),
    ]
    px = [44, 276, 508, 740]
    for x, (a, b) in zip(px, pols, strict=True):
        bx = s.box(x, 380, 216, 56, [a, b], "policy")
        if a != "Status quo":
            s.arrow(500, 340, *top(bx))
    s.arrow(160, 236, 160, 380, "responses")
    roll = s.box(
        40, 500, 300, 56, ["Rollouts, 3 periods", "every policy, common random numbers"], "policy"
    )
    logs = s.box(
        370,
        500,
        260,
        56,
        ["Logging rollout, period 1", "uniform over allowed, exact propensities"],
        "policy",
    )
    s.box(660, 500, 300, 56, ["Oracle", "exact period-1 value per policy"], "policy")
    for x in (190, 810):
        s.arrow(x, 436, x, 500)
    s.arrow(500, 340, 500, 500)  # through the gap: the filter's allowed set drives logging
    aud = s.box(
        40, 600, 300, 56, ["Independent auditor", "recomputes every rule from the log"], "check"
    )
    s.box(
        370,
        600,
        590,
        56,
        ["Off-policy estimates (IPS, SNIPS, DR)", "each interval checked against the oracle"],
        "check",
    )
    s.arrow(*bottom(roll), *top(aud))
    s.arrow(*bottom(logs), 500, 600)
    s.arrow(810, 556, 810, 600)
    s.box(
        190,
        690,
        620,
        50,
        [
            "Aggregate: block bootstrap, paired, Holm",
            "holdout check · budget sweep · disparity → summary.json",
        ],
        "data",
    )
    s.arrow(*bottom(aud), 300, 690)
    s.arrow(665, 656, 665, 690)
    outs = [
        ("Report", "GitHub Pages"),
        ("PR/FAQ", "one page, templated"),
        ("Demo cube", "aggregates only, passkey"),
        ("metrics-1 + gates", "EvalKit format, in CI"),
    ]
    for x, (a, b) in zip([40, 280, 520, 760], outs, strict=True):
        bx = s.box(x, 772, 200, 50, [a, b], "out")
        s.arrow(500, 740, *top(bx))
    s.legend(
        848,
        [
            ("data", "data and aggregation"),
            ("model", "churn model"),
            ("policy", "simulation and policies"),
            ("check", "rules and checks"),
            ("out", "outputs"),
        ],
    )
    return s.render()


def architecture() -> str:
    s = Svg(
        1000,
        720,
        "Respectful Offers architecture",
        "Interfaces (CLI, report, demo, EvalKit gates) sit on the respectful_offers library: "
        "features, churn, simulator, policies with the respect filter, auditor, off-policy "
        "estimators, evaluation and report, over a cached stage runner and artifact store. "
        "A gated build harness and CI build and release it.",
    )
    s.text(500, 34, "Respectful Offers: architecture", 20, 700)
    s.text(
        500,
        56,
        "Python 3.11–3.13 package respectful-offers · no model calls · no telemetry",
        12,
        400,
        MUTED,
    )
    s.band(24, 74, 952, 104, "Interfaces")
    ifaces = [
        ("CLI: offers", "data · features · evaluate · run · metrics"),
        ("Static report", "inline SVG, GitHub Pages"),
        ("Streamlit demo", "cube only, passkey gate"),
        ("EvalKit gates", "metrics-1 · configs/gates.yaml"),
    ]
    for i, (a, b) in enumerate(ifaces):
        s.box(40 + i * 234, 100, 216, 60, [a, b], "out")
    s.band(24, 196, 952, 252, "Library: respectful_offers (every interface calls it)")
    mods = [
        [
            ("features", "as-of builder, allow-list", "data"),
            ("churn", "model, calibration, card", "model"),
            ("sim", "response model, variants", "policy"),
            ("policy.respect", "allowed actions (R1, R2)", "check"),
        ],
        [
            ("policy", "bandit, baselines, budget", "policy"),
            ("policy.audit", "independent recount", "check"),
            ("ope", "IPS, SNIPS, DR", "check"),
            ("evaluate", "rollouts, bootstrap, Holm", "data"),
        ],
        [
            ("report", "HTML + SVG charts", "out"),
            ("demo", "cube, engine, passkey", "out"),
            ("metrics1", "EvalKit export + validator", "out"),
            ("schemas", "frozen pydantic contracts", "plain"),
        ],
    ]
    for r, row in enumerate(mods):
        for i, (a, b, k) in enumerate(row):
            s.box(40 + i * 234, 222 + r * 72, 216, 58, [a, b], k)
    s.band(24, 466, 952, 96, "Runtime")
    rt = [
        ("Stage runner", "cache keys: code, inputs, config, seed"),
        ("Artifact store", ".offers/store, content-addressed"),
        ("Lineage", "runs/<id>/run.json"),
        ("Seeds", "per-member CRN streams"),
    ]
    for i, (a, b) in enumerate(rt):
        s.box(40 + i * 234, 490, 216, 56, [a, b], "data")
    s.band(24, 580, 952, 100, "Build and release")
    br = [
        ("Build harness", "node graph · 12 gates · verifier"),
        ("CI", "3 Pythons × 3 OS, scans, gates"),
        ("Release", "PyPI trusted publishing on tag"),
        ("Records", "decisions · lessons · changelog"),
    ]
    for i, (a, b) in enumerate(br):
        s.box(40 + i * 234, 604, 216, 56, [a, b], "plain")
    s.legend(
        706,
        [
            ("data", "data and runtime"),
            ("model", "model"),
            ("policy", "policies"),
            ("check", "rules and checks"),
            ("out", "outputs"),
            ("plain", "contracts, build"),
        ],
    )
    return s.render()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    files = {OUT / "dataflow.svg": dataflow(), OUT / "architecture.svg": architecture()}
    if args.check:
        stale = [
            p.name
            for p, t in files.items()
            if not p.is_file() or p.read_text(encoding="utf-8") != t
        ]
        if stale:
            print(f"stale: {stale}; run scripts/diagrams.py", file=sys.stderr)
            return 1
        return 0
    for p, t in files.items():
        p.write_text(t, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
