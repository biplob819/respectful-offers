# Results on real KKBox members

The pre-registered run `real-v2` of Respectful Offers on the March 2017 cohort of the [WSDM Cup 2018 KKBox churn prediction challenge](https://www.kaggle.com/competitions/kkbox-churn-prediction-challenge), used under its rules for non-commercial research and education (OWNER D-46). Members, features, churn labels and churn risk are real; **every outcome that depends on an offer is simulated** by the pre-registered simulator (`configs/simulator.yaml`, sha256 `6ae08959…` in `docs/prereg.md`). Aggregates only: no member data is in this folder.

| File | What it is |
| --- | --- |
| [`report/index.html`](report/index.html) | The results report (published on GitHub Pages with the README, node B2.3) |
| [`summary.json`](summary.json) | Every metric with its 95% interval, per policy and variant |
| [`frontier.json`](frontier.json) | Budget sweep, learning curves and the frozen bandit posteriors |
| [`audit.json`](audit.json) | The independent auditor's counts for every rollout (clean) |
| [`run.json`](run.json) | Lineage: commit, config and simulator hashes, stage keys |
| [`churn/`](churn/) | Churn model card (leakage checks, permutation importance), report and calibration |
| [`features_stats.json`](features_stats.json) | Cohort sizes, churn rates, feature means and each feature's latest source date |
| [`decision-review.md`](decision-review.md) | Real decisions read end to end before any number was published (L-11) |
| [`decision_review/`](decision_review/) | The review's aggregate checks, per variant |

Reproduce: accept the competition rules on Kaggle, then `offers data download`, `offers run --all --run-id real-v2`, and `python scripts/review_decisions.py --run runs/real-v2`. The demo's cube (`demo/cube.json`) is built from this run with `offers demo-cube --run-id real-v2`.

**Provenance.** `real-v2` ran at clean commit `2faad55`; its features and churn stages came from the stage cache written by `real-v1` (same code, uncommitted changes outside those stages). Rebuilt from the raw files with an empty cache on 2026-11-17, the features (`features_feb`, `features_mar`), audit attributes and churn scores were byte-identical to the cached ones, under the same stage keys.
