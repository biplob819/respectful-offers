# Respectful Offers build graph

Source of truth for build-node dependencies. Parsed by `scripts/harness_lib.py`.
A node may start only when every node in its `Depends on` cell is green (all its rows in `catalog.tsv` are green).
Edge rules: no cycles; a node inherits the constraints of what it depends on; `Verified by` must pass before a node flips green.
Generated from Respectful Offers Tech Spec §11.2 on 2026-11-15; edit here from now on and keep the Tech Spec in sync.


## Wave 0 — harness

| Node | Title | Depends on | Verified by | Deliverable | Stories |
| --- | --- | --- | --- | --- | --- |
| **W0.1** | Repo and harness | — | node_converge + verifier | Repo, uv project, CI, the ported harness scripts each with `--self-test`, decisions, lessons and changelog files | — |

## Wave 1 — data and core

| Node | Title | Depends on | Verified by | Deliverable | Stories |
| --- | --- | --- | --- | --- | --- |
| **N1.1** | Schemas and config | W0.1 | node_converge + verifier | `respectful_offers.schemas` (§3), `RunConfig` and simulator config loaders, column contracts, results format v1 fixtures | US1, US5 |
| **N1.2** | Data contract, synthetic fixture and download tooling | N1.1 | node_converge + verifier | `offers data download/verify` (tested against a fake Kaggle client), manifest format, synthetic KKBox-format fixture generator, raw-data gate, `DATA_CARD.md` | — |
| **N1.3** | Stage runner and artifact store | N1.1 | node_converge + verifier | Stage contract, content-addressed store, lineage, seed tree with CRN streams, version check | US1 |
| **N1.5** | KKBox acquisition and licence | N1.2 | node_converge + verifier | Real KKBox files downloaded with the owner's credentials and verified; licence ruling recorded | — |
| **N1.4** | Features | N1.2, N1.3 | node_converge + verifier | DuckDB ingestion, as-of feature builder, February and March cohorts, allow-list, audit table, `offers features` | US1 |

## Wave 2 — policy pipeline

| Node | Title | Depends on | Verified by | Deliverable | Stories |
| --- | --- | --- | --- | --- | --- |
| **A2.1** | Churn model and calibration | N1.4 | node_converge + verifier | Gradient-boosted churn model (D-29), isotonic calibration, March report, risk scores and bands, `offers churn` | US1 |
| **A2.2** | Response simulator | A2.1, N1.3 | node_converge + verifier | Segment response model, three variants set by the owner, CRN draws, oracle, `offers prereg` | US5 |
| **A2.3** | Respect filter and auditor | N1.1 | node_converge + verifier | `allowed_actions`, holdout assignment, independent auditor, property and mutation tests | US3, US4 |
| **A2.4** | Policies, budget and rollout | A2.2, A2.3 | node_converge + verifier | Policy protocol, baselines, pacer, logging pilot, segment oracle, vectorised rollout engine | US1, US2 |
| **A2.5** | Thompson sampling bandit | A2.4 | node_converge + verifier | Linear TS, simulated training, frozen posterior, Monte Carlo propensities, learning curve | US1, US2 |
| **A2.6** | Off-policy estimators | A2.4 | node_converge + verifier | IPS, SNIPS, DR with cross-fitted reward model, block bootstrap, validation against the oracle | US8 |
| **A2.7** | Evaluate and compare | A2.5, A2.6 | node_converge + verifier | `offers evaluate`: rollouts per variant, metrics, paired comparisons, OPE beside oracle, audit, holdout check, budget sweep, disparity, `summary.json` | US1–US5, US8 |
| **A2.8** | Real-data results run | A2.7, N1.5, D3.1 | node_converge + verifier | The pre-registered pipeline run on real KKBox data for all three variants, with real decisions read end to end; the demo cube rebuilt from the real run and its agreement re-checked (D-42) | US1–US5 |

## Wave 2 — report, PR/FAQ and release v0.1.0

| Node | Title | Depends on | Verified by | Deliverable | Stories |
| --- | --- | --- | --- | --- | --- |
| **B2.1** | Results report | A2.7 | node_converge + verifier | Static HTML report with "Simulated" labels, YAML quoted, audit and calibration panels | US1, US2, US5, US8 |
| **B2.2** | CLI | A2.7, B2.1 | node_converge + verifier | Typer CLI (§4), `doctor`, `report --example`, `run --all`, exit codes, `--json` | US1 |
| **B2.3** | Report deploy and README | B2.1, B2.2, A2.8 | node_converge + verifier | README headline chart, report published on GitHub Pages, docs commands tested | US1 |
| **P2.1** | PR/FAQ | A2.8, B2.1 | node_converge + verifier | One-page PR/FAQ, numbers templated from `summary.json`, PDF | US6 |
| **B2.4** | Open-source packaging and v0.1.0 | B2.3, P2.1 | node_converge + verifier | PyPI `respectful-offers`, Python × OS CI matrix, docs (quickstart, your own data, simulator config), community files, history audit, data card, tag v0.1.0 | US6 |

## Wave 3 — demo and project page

| Node | Title | Depends on | Verified by | Deliverable | Stories |
| --- | --- | --- | --- | --- | --- |
| **D3.1** | Demo engine | A2.7, B2.2 | node_converge + verifier | Aggregates-only cohort cube, `simulate()`, `offers demo-cube`, perf test, agreement with the full run (built on a synthetic run; A2.8 rebuilds the cube from real data, D-42) | US7 |
| **D3.2** | Demo page | D3.1, B2.2 | node_converge + verifier | Streamlit page in `portfolio-demos` matching the PRD wireframe, deployed | US7 |
| **D3.3** | Project page and video | B2.4, D3.2 | node_converge + verifier | Case study page and 90-second video script, numbers checked against `summary.json`, links resolve | — |
