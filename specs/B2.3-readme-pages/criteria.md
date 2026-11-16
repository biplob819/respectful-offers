# B2.3 acceptance criteria

**REL-01 — README opening**
- Between the headline markers: exactly one chart (`docs/img/headline.svg`), a paragraph of three sentences that says **simulated**, a caveat block, a three-line bash snippet and the KKBox credit with "no member data"; `scripts/readme_assets.py --check` regenerates the block and the chart from `results/kkbox/summary.json` and fails on any drift; the README links the report, the demo, the decision review, the guides, the data card, the decision log, the pre-registration, PyPI and the community files, with no dead relative link; every screenshot it shows exists.

**REL-02 — report on GitHub Pages through the publish scan**
- `scripts/build_site.py` copies only the published report (and `docs/site/` pages, when that folder exists) into the site, refuses any row-data file and anything the publish scan rejects (a KKBox-shaped id is caught), and its index is the published report byte for byte; `.github/workflows/pages.yml` builds through it with read-only top-level permissions and deploys with `pages: write` and `id-token: write` only.

**REL-03 — documented commands run**
- Every `offers` command in a fenced bash block of the README or a guide is either run, as written, by the quickstart or the own-data scenario in a fresh fixture project, or on a two-item skip list with a reason (the Kaggle download and the real-data run, covered elsewhere); a scenario command no doc shows also fails.
