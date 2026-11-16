#!/usr/bin/env python3
"""The PR/FAQ (P2.1): one page plus FAQ, every number templated from the published
`results/kkbox/summary.json` (PRF-02), written as Markdown and HTML and printed to PDF.

    uv run python scripts/prfaq.py           # write docs/site/prfaq.md and prfaq.html
    uv run python scripts/prfaq.py --pdf     # also print prfaq.pdf with a local Chrome
    uv run python scripts/prfaq.py --check   # exit 1 if any of them is stale

The PDF records the sha256 of the HTML it was printed from in `prfaq.pdf.sha256`, so a check
without Chrome still knows whether the PDF is current.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "results" / "kkbox" / "summary.json"
OUT = ROOT / "docs" / "site"
VARIANTS = ("conservative", "central", "optimistic")
CHROME = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "chromium",
    "chrome",
)


def facts() -> dict:
    """Every number the PR/FAQ states, from summary.json and nothing else."""
    from respectful_offers.schemas.summary import RunSummary

    s = RunSummary.model_validate_json(SUMMARY.read_text(encoding="utf-8"))

    def row(v: str, p: str):
        return next(x for x in s.policies if x.variant == v and x.policy == p)

    f: dict = {"members": row("central", "bandit").n_members, "run": s.run_id}
    for v in VARIANTS:
        for p in ("no_offer", "bandit", "rule_following_baseline", "status_quo"):
            r = row(v, p)
            f[f"{v}.{p}.inc"] = r.incremental_retained_per_1000.point
            f[f"{v}.{p}.cost_total"] = r.discount_cost_total
            f[f"{v}.{p}.violations"] = sum(r.violations.values())
            c = r.cost_per_incremental_retained
            f[f"{v}.{p}.cost"] = None if c is None else c.point
        comp = next(
            c
            for c in s.comparisons
            if c.variant == v
            and {c.a, c.b} == {"bandit", "rule_following_baseline"}
            and c.metric == "incremental_retained_per_1000_ntd"
        )
        sign = 1 if comp.a == "bandit" else -1
        lo, hi = sorted((sign * comp.diff.lo, sign * comp.diff.hi))
        f[f"{v}.claim"] = (sign * comp.diff.point, lo, hi, comp.separated)
        sq = next(
            c
            for c in s.comparisons
            if c.variant == v
            and {c.a, c.b} == {"status_quo", "rule_following_baseline"}
            and c.metric == "incremental_retained_per_1000"
        )
        sg = 1 if sq.a == "status_quo" else -1
        lo2, hi2 = sorted((sg * sq.diff.lo, sg * sq.diff.hi))
        f[f"{v}.sq_minus_base"] = (sg * sq.diff.point, lo2, hi2, sq.separated)
        h = s.holdout_check[v]
        f[f"{v}.holdout"] = (h.point, h.lo, h.hi)
    dr = [o for o in s.ope if o.estimator == "dr"]
    f["dr.covered"] = sum(o.covered for o in dr)
    f["dr.total"] = len(dr)
    from respectful_offers.schemas.config import load_run_config

    lo_b, hi_b = load_run_config(ROOT / "configs" / "run.yaml").cohort_buckets["holdout"]
    f["holdout_share"] = (hi_b - lo_b) / 100
    f["auc"] = s.churn.auc.point
    f["baseline_auc"] = s.churn.baseline_auc.point
    return f


def sections() -> list[tuple[str, list[str]]]:
    f = facts()
    c = "central"
    claims = ", ".join(
        f"{v} {f[f'{v}.claim'][0]:+.2f} ({f[f'{v}.claim'][1]:+.2f} to {f[f'{v}.claim'][2]:+.2f})"
        for v in VARIANTS
    )
    held = all(f[f"{v}.claim"][3] and f[f"{v}.claim"][0] > 0 for v in VARIANTS)
    hp, hl, hh = f[f"{c}.holdout"]
    sq_d, sq_lo, sq_hi, sq_sep = f[f"{c}.sq_minus_base"]
    share = f[f"{c}.bandit.cost_total"] / f[f"{c}.rule_following_baseline.cost_total"]
    keep = f[f"{c}.bandit.inc"] / f[f"{c}.rule_following_baseline.inc"]
    press = [
        "**Simulated results.** A retention policy that decides which subscriber gets a content "
        "nudge, a cheaper plan or a discount, and that never repeats an offer a member declined, "
        "spent "
        f"**{f[f'{c}.bandit.cost']:.0f} NTD** of discount per extra member kept, against "
        f"{f[f'{c}.rule_following_baseline.cost']:.0f} NTD for a rule-following baseline and "
        f"{f[f'{c}.status_quo.cost']:.0f} NTD for today's habit of discounting everyone at risk. "
        f"It was evaluated on {f['members']:,} real members of the KKBox music service, whose "
        "responses to offers came from a pre-registered simulator: KKBox's data holds no offers.",
        "Respectful Offers predicts each member's churn risk, removes every offer the two respect "
        "rules forbid (a declined offer stays declined; members at risk see content before "
        "commerce), and lets a Thompson sampling bandit choose among what is left, within a "
        "monthly discount budget. An independent auditor recomputed every rule from the decision "
        f"log: the respectful policies broke none, the status quo broke "
        f"{f[f'{c}.status_quo.violations']:,} (central variant).",
        "The pre-registered claim was that the bandit keeps more members per 1,000 NTD of "
        "discount than the rule-following baseline. "
        + (
            "It held in all three simulator variants, "
            if held
            else "It did not hold in every variant, "
        )
        + f"bandit minus baseline with 95% intervals: {claims} members per 1,000 NTD. "
        f"The bandit spent {share:.0%} of the baseline's discount for {keep:.0%} of its extra "
        f"members kept ({f[f'{c}.bandit.inc']:.1f} against "
        f"{f[f'{c}.rule_following_baseline.inc']:.1f} per 1,000), leaning on free nudges and the "
        "cheaper plan. Read every number as conditional on the simulator's assumptions.",
    ]
    faq = [
        "**Are these real results?** The members, their behaviour, their churn labels and the "
        f"churn model (AUC {f['auc']:.2f} against {f['baseline_auc']:.2f} for a two-feature "
        "baseline) are real. Every outcome that depends on an offer is **simulated**: the "
        "simulator's values were frozen by their sha256 before the real run, and every result is "
        "reported under a conservative, a central and an optimistic variant.",
        "**What would a real A/B test add?** The one thing a simulator cannot give: how real "
        "members respond to offers. A live test, randomised at the member level with the same "
        "holdout, would measure acceptance and the lift in renewal directly, check whether "
        "sleeping dogs exist at the assumed share, and catch effects the simulator leaves out "
        "(offer fatigue across months, word of mouth, a discount teaching members to wait for "
        "the next one). Until then, the conclusion is: under these assumptions, this policy is "
        "worth testing.",
        f"**Why a holdout?** A randomly chosen {f['holdout_share']:.0%} of members are never "
        "offered anything. Their retention, against the no-offer policy on the evaluation "
        "members, checks that the lift is not a measurement artefact: the difference was "
        f"{hp:+.1f} per 1,000 (95% interval {hl:+.1f} to {hh:+.1f}), "
        + ("consistent with none." if hl <= 0 <= hh else "NOT consistent with none."),
        "**Why a doubly robust estimator?** A live system would only have its own logged "
        "decisions. Doubly robust off-policy evaluation combines a model of the reward with "
        "importance weights, so it stays unbiased if either one is right. Here it was validated "
        "against the simulator's exact answer: its 95% interval covered the true value in "
        f"{f['dr.covered']} of {f['dr.total']} policy and variant cases.",
        "**Why do the rules sit outside the learning?** A bandit that learns its own respect "
        "would trade it away whenever pestering pays. The filter removes forbidden actions "
        "before the bandit chooses, so no reward can buy a violation, and the auditor checks "
        "the log independently of the code that made the decisions.",
        "**What does respect cost?** The status quo, which ignores both rules, kept "
        f"{f[f'{c}.status_quo.inc']:.1f} extra members per 1,000 against the rule-following "
        f"baseline's {f[f'{c}.rule_following_baseline.inc']:.1f} (difference "
        f"{sq_d:+.2f}, 95% interval {sq_lo:+.2f} to {sq_hi:+.2f}), and paid "
        f"{f[f'{c}.status_quo.cost']:.0f} NTD per extra member against "
        f"{f[f'{c}.rule_following_baseline.cost']:.0f} (central): "
        + (
            "a little more retention, at a higher price per member kept"
            if sq_sep and sq_d > 0
            else "no clearly better retention, at a higher price per member kept"
        )
        + " and with members asked again after saying no.",
    ]
    return [("Press release", press), ("FAQ", faq)]


TITLE = "Respectful Offers: keep subscribers without pestering them (simulated results)"
SUB = (
    "PR/FAQ · data: WSDM Cup 2018 KKBox churn prediction challenge (Kaggle), used for "
    "non-commercial research and education · offer responses simulated"
)


def markdown() -> str:
    parts = [f"# {TITLE}", "", f"*{SUB}*", ""]
    for head, paras in sections():
        parts += [f"## {head}", ""]
        for p in paras:
            parts += [p, ""]
    return "\n".join(parts)


def _inline(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(text, quote=False))


def page() -> str:
    body = [f"<h1>{html.escape(TITLE)}</h1>", f'<p class="sub">{html.escape(SUB)}</p>']
    for head, paras in sections():
        body.append(f"<h2>{html.escape(head)}</h2>")
        body += [f"<p>{_inline(p)}</p>" for p in paras]
    css = (
        "@page{size:A4;margin:14mm}body{font:9.6pt/1.42 system-ui,-apple-system,'Segoe UI',"
        "Roboto,sans-serif;color:#1d1d1f;max-width:46rem;margin:0 auto;padding:12px}"
        "h1{font-size:15pt;margin:0 0 2px}h2{font-size:11pt;margin:10px 0 4px}"
        "p{margin:0 0 6px}.sub{color:#5f6368;font-size:8.4pt}"
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Respectful Offers PR/FAQ</title><style>{css}</style></head><body>"
        + "".join(body)
        + "</body></html>\n"
    )


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def print_pdf(html_path: Path, pdf_path: Path) -> None:
    chrome = next((c for c in CHROME if Path(c).exists() or shutil.which(c)), None)
    if chrome is None:
        raise SystemExit("no Chrome or Chromium found to print the PDF")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [
                chrome,
                "--headless=new",
                "--disable-gpu",
                f"--user-data-dir={tmp}",
                "--no-pdf-header-footer",
                f"--print-to-pdf={pdf_path}",
                html_path.resolve().as_uri(),
            ],
            check=True,
            capture_output=True,
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    md, htm = markdown(), page()
    paths = {OUT / "prfaq.md": md, OUT / "prfaq.html": htm}
    if args.check:
        stale = [p.name for p, t in paths.items() if not p.is_file() or p.read_text("utf-8") != t]
        side = OUT / "prfaq.pdf.sha256"
        if not (OUT / "prfaq.pdf").is_file() or not side.is_file():
            stale.append("prfaq.pdf")
        elif side.read_text("utf-8").strip() != sha(htm):
            stale.append("prfaq.pdf (printed from an older prfaq.html)")
        if stale:
            print(f"stale: {stale}; run scripts/prfaq.py --pdf", file=sys.stderr)
            return 1
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for p, t in paths.items():
        p.write_text(t, encoding="utf-8", newline="\n")
    if args.pdf:
        print_pdf(OUT / "prfaq.html", OUT / "prfaq.pdf")
        (OUT / "prfaq.pdf.sha256").write_text(sha(htm) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
