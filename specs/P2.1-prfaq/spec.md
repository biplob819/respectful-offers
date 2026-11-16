# P2.1 PR/FAQ

A one-page press release and FAQ, working backwards from the result, with every number templated from the published `results/kkbox/summary.json` (and the run config for the holdout share) by `scripts/prfaq.py`, written as Markdown and HTML under `docs/site/` (published on GitHub Pages) and printed to a one-page PDF with a local Chrome. The PDF records the hash of the HTML it was printed from, so CI knows it is current without Chrome.
