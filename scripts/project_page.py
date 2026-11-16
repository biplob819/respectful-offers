#!/usr/bin/env python3
"""The project page and the video script (D3.3): a case study (`docs/site/case-study.html`,
published on GitHub Pages beside the report and the PR/FAQ) and a 90-second video script
(`docs/site/video-script.md`), every number templated from the published summary through
`scripts/prfaq.py`'s `facts()`, so the three documents can never disagree (PAG-01, PAG-02).

    uv run python scripts/project_page.py          # write both
    uv run python scripts/project_page.py --check  # exit 1 if either is stale
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import prfaq  # noqa: E402

OUT = ROOT / "docs" / "site"
SITE = "https://biplob819.github.io/respectful-offers/"
LINKS = {
    "Results report": SITE,
    "PR/FAQ (PDF)": SITE + "prfaq.pdf",
    "Live demo (passkey)": "https://respectful-offers.streamlit.app/",
    "Source code": "https://github.com/biplob819/respectful-offers",
    "Package": "https://pypi.org/project/respectful-offers/",
    "Decision review": "https://github.com/biplob819/respectful-offers/blob/main/results/kkbox/decision-review.md",
}
WORDS_PER_SECOND = 2.5  # a calm narration pace: 90 seconds is about 225 words


def case_study() -> list[tuple[str, list[str]]]:
    f = prfaq.facts()
    c = "central"
    claims = ", ".join(f"{v} {f[f'{v}.claim'][0]:+.2f}" for v in prfaq.VARIANTS)
    return [
        (
            "The problem",
            [
                "Subscription services fight churn with discounts, and the usual rule, "
                "discount everyone the model flags as at risk, pays members who would have "
                "stayed anyway and asks people again after they said no.",
            ],
        ),
        (
            "What I built",
            [
                "A retention policy with two respect rules written outside the learning: a "
                "declined offer stays declined, and members at risk see content before "
                "commerce. A calibrated churn model scores each member, a filter removes "
                "every forbidden action, and a Thompson sampling bandit chooses among a "
                "content nudge, a cheaper plan and a half-price month, within a budget. An "
                "independent auditor recomputes every rule from the decision log.",
            ],
        ),
        (
            "How it was evaluated",
            [
                f"On {f['members']:,} real members of the KKBox music service (churn model AUC "
                f"{f['auc']:.2f}). Their data holds no offers, so responses come from a "
                "simulator whose values were frozen before the real run, in three variants. "
                "Every policy ran on the same members with common random numbers; a "
                f"{f['holdout_share']:.0%} holdout and off-policy estimates checked against "
                "the simulator's exact answer guard the measurement.",
            ],
        ),
        (
            "Result (simulated)",
            [
                f"The bandit spent {f[f'{c}.bandit.cost']:.0f} NTD of discount per extra "
                f"member kept, against {f[f'{c}.rule_following_baseline.cost']:.0f} for the "
                f"rule-following baseline and {f[f'{c}.status_quo.cost']:.0f} for the status "
                f"quo, which broke the rules {f[f'{c}.status_quo.violations']:,} times. The "
                "pre-registered claim, more members kept per 1,000 NTD than the baseline, held "
                f"in every variant ({claims}). It keeps fewer extra members in absolute terms "
                f"({f[f'{c}.bandit.inc']:.1f} against "
                f"{f[f'{c}.rule_following_baseline.inc']:.1f} per 1,000): the trade is "
                "cheaper retention, not more of it.",
            ],
        ),
        (
            "What I would do next",
            [
                "Run a real A/B test with the same holdout: it is the only way to learn how "
                "members respond to offers, and the result here says the policy is worth that "
                "test, under its stated assumptions.",
            ],
        ),
    ]


def page() -> str:
    body = [
        "<h1>Respectful Offers</h1>",
        '<p class="sub">Case study · simulated offer responses on real KKBox members · '
        "data: WSDM Cup 2018 KKBox churn prediction challenge (Kaggle), used for "
        "non-commercial research and education</p>",
    ]
    for head, paras in case_study():
        body.append(f"<h2>{html.escape(head)}</h2>")
        body += [f"<p>{html.escape(p)}</p>" for p in paras]
    body.append("<h2>Links</h2><ul>")
    body += [f'<li><a href="{html.escape(u)}">{html.escape(k)}</a></li>' for k, u in LINKS.items()]
    body.append("</ul>")
    css = (
        ":root{--fg:#1d1d1f;--muted:#5f6368;--bg:#fff;--accent:#0b57d0}"
        "@media (prefers-color-scheme:dark){:root{--fg:#e8eaed;--muted:#a8adb4;--bg:#121316;"
        "--accent:#8ab4f8}}body{margin:0;background:var(--bg);color:var(--fg);"
        "font:16px/1.6 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif}"
        "main{max-width:44rem;margin:0 auto;padding:32px 16px 64px}h1{margin:0 0 4px}"
        "h2{font-size:1.2rem;margin:28px 0 6px}.sub{color:var(--muted);font-size:.9rem}"
        "a{color:var(--accent)}"
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Respectful Offers: case study</title><style>{css}</style></head><body><main>"
        + "".join(body)
        + "</main></body></html>\n"
    )


def script() -> str:
    f = prfaq.facts()
    c = "central"
    share = f[f"{c}.bandit.cost_total"] / f[f"{c}.rule_following_baseline.cost_total"]
    fewer = 1 - f[f"{c}.bandit.inc"] / f[f"{c}.rule_following_baseline.inc"]
    held = all(f[f"{v}.claim"][3] and f[f"{v}.claim"][0] > 0 for v in prfaq.VARIANTS)
    beats = [
        (
            "0:00",
            "Title card: Respectful Offers",
            "Most subscription services fight churn the same way: find the members likely to "
            "leave, and send them a discount, even after they said no.",
        ),
        (
            "0:10",
            "The two rules on screen",
            "I built a retention policy with two rules it cannot break. A declined offer stays "
            "declined. And members at risk see content before they see a discount.",
        ),
        (
            "0:22",
            "Diagram: churn model, filter, bandit, auditor",
            "A churn model scores each member, a filter removes every offer the rules forbid, "
            "and a bandit learns which of the rest works: a content nudge, a cheaper plan or a "
            "half-price month. An independent auditor rechecks every rule.",
        ),
        (
            "0:40",
            "Simulated label, real members",
            f"I tested it on {f['members']:,} real members of a music service. Their data has "
            "no offers in it, so how they respond comes from a simulator frozen before the "
            "real run.",
        ),
        (
            "0:55",
            "The headline chart",
            f"The result: {f[f'{c}.bandit.cost']:.0f} N T D of discount per extra member kept, "
            f"against {f[f'{c}.rule_following_baseline.cost']:.0f} for a simple rule-following "
            f"policy, and {f[f'{c}.status_quo.cost']:.0f} for discounting everyone at risk. "
            + (
                "It held under pessimistic and optimistic assumptions too."
                if held
                else "It did not hold under every set of assumptions."
            ),
        ),
        (
            "1:12",
            "The demo, sliders moving",
            f"It keeps {fewer:.0%} fewer extra members than the simple policy, on "
            f"{share:.0%} of its discount. Nobody hears the same offer after saying no.",
        ),
        (
            "1:22",
            "End card: links",
            "Next step: a real A/B test. The report, the code and the demo are linked below.",
        ),
    ]
    lines = [
        "# Respectful Offers: 90-second video script",
        "",
        "Every number is templated from `results/kkbox/summary.json`; every result on screen "
        "carries the label **Simulated**.",
        "",
        "| Time | On screen | Narration |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {t} | {s} | {n} |" for t, s, n in beats]
    words = sum(len(n.split()) for _, _, n in beats)
    lines += ["", f"Narration: {words} words, about {words / WORDS_PER_SECOND:.0f} seconds.", ""]
    return "\n".join(lines)


def narration_words(text: str) -> int:
    rows = [r for r in text.splitlines() if re.match(r"\| \d:\d\d \|", r)]
    return sum(len(r.rsplit("|", 2)[1].split()) for r in rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    files = {OUT / "case-study.html": page(), OUT / "video-script.md": script()}
    if args.check:
        stale = [p.name for p, t in files.items() if not p.is_file() or p.read_text("utf-8") != t]
        if stale:
            print(f"stale: {stale}; run scripts/project_page.py", file=sys.stderr)
            return 1
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for p, t in files.items():
        p.write_text(t, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
