# P2.1 acceptance criteria

**PRF-01 — one page, Markdown to PDF**
- `docs/site/prfaq.md`, `prfaq.html` and a one-page `prfaq.pdf` exist, with a press release and an FAQ; the PDF's recorded source hash matches the current HTML.

**PRF-02 — numbers templated, drift fails**
- `scripts/prfaq.py --check` regenerates the Markdown and HTML from `summary.json` and fails on any difference; changing a number in the summary changes the text; every number stated is the summary's.

**PRF-03 — FAQ topics**
- The FAQ answers what a real A/B test would add, why a holdout, why doubly robust, and why the rules sit outside learning.

**PRF-04 — simulated, per variant, conditional**
- The title and the opening say simulated; the claim is stated for each variant with its interval; conclusions are stated as conditional on the simulator; the challenge is cited (OWNER D-46).
