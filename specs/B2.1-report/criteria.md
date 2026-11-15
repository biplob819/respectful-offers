# B2.1 acceptance criteria

**RPT-01 — self-contained, all variants**
- The page has no scripts, iframes, images, stylesheets links or external URLs; each variant has its policy table, frontier and OPE figure; three Vega-Lite specs are written alongside.

**RPT-02 — charts**
- Frontier (with a block-bootstrap interval on every point), variant comparison, OPE against the oracle, learning curve, reliability plot, comparisons and headline are present; every chart has one SVG and one table; the frontier's numbers match `frontier.json`; row labels are never clipped.

**RPT-03 — "Simulated" labels**
- Every element marked `data-simulated="true"` shows "Simulated" in its visible text; every figure except the churn reliability plot is so marked; and no digit in visible text sits outside a marked element except in the churn card, the simulator file, the header and the footer.

**RPT-04 — YAML byte for byte**
- The `<pre id="simulator-yaml">` text, as a browser shows it, equals the simulator file, including a leading blank line, CRLF and lone CR; a file with a NUL or a different simulator file than the run used is refused; a missing run fails with exit 2.

**RPT-05 — audit, holdout, disparity, churn card**
- The audit panel reads `audit.json`: every audited rollout is listed and a failed audit is shown as failed with a do-not-publish banner; it shows each policy's violations per rule (the status quo's counts included), the holdout check per variant, the disparity table by age band and gender, and the churn model card (AUC, Brier, ECE, baseline).

**RPT-06 — accessibility, stamp, real output**
- `lang` is set; every SVG has `role="img"`, a title and a description; every policy has its own marker shape and series carry direct labels; the YAML block is focusable; the pre-registration stamp follows the summary (exploratory runs say they are never to be published) and no other text claims registration; the data source is stamped and the churn card is labelled by it (synthetic members are never called real); user strings never become markup (ids are slugs); the report is rendered from a real `offers evaluate` run in the tests and is deterministic.
