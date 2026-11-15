# Changelog

Format: `[TYPE] [NODE] — summary`, newest first.

- [CHANGE] [N1.1] — run config: `ts_integration_nodes` and `ts_support_floor` replace `ts_mc_draws` (D-35); disparity keys may be `policy.metric.attribute` (D-34); churn stage version 4 (its schemas changed).
- [FEAT] [A2.5] — Thompson sampling bandit: disjoint Bayesian linear posteriors on revenue ÷ price; exact choice probabilities by a one-dimensional integral with a support floor applied last (D-35); simulated training; a frozen posterior that carries its flag, settings and column order; learning curve against the respectful oracle; allow-listed context with R7 proxy checks.
- [FIX] [A2.4] — verifier round 1 (D-32, L-29): exact pacer, oracle falls back to its best free action, member-keyed choices, probabilities validated, status quo honours R3, clear errors on empty cohorts.
- [FEAT] [A2.4] — policies (no offer, holdout, status quo, rule-following baseline, logging pilot, segment oracle), face-value budget pacer, and the H-period rollout engine with CRN, plan-change eligibility and contract-checked logs.
- [FIX] [A2.1] — small model fits run on one thread (30x faster, same output); churn stage version 3.
- [FEAT] [A2.2] — response simulator: hidden segments behind real features, exposure and acceptance effects, CRN draws, exact period-1 oracle and segment-oracle values, direction rules, `offers prereg`; recommended values registered for synthetic runs only, awaiting the owner (D-3).
- [FEAT] [A2.1] — churn model: gradient-boosted classifier on February, isotonic calibration on a February fold, March report with bootstrap intervals, reliability bins and a two-feature baseline, calibrated March scores, model card; no pickles.
- [FIX] [N1.3] — the stale-cache guard hashes every project module a stage imports, transitively (L-26).
- [FEAT] [N1.4] — features as of each cohort's label month via DuckDB with an explicit schema; provenance-checked as-of guard, early renewals excluded (D-28), audit table kept apart, `offers features` and `--from-table` for your own data.
- [FEAT] [N1.2] — data contract: seeded synthetic data in the exact KKBox formats, `offers data download|verify|synthetic`, DuckDB-streamed manifest with checksums and date ranges, nested archive unpacking with traversal checks, data card.
- [FEAT] [A2.3] — respect filter (R1 with nudges, R2, R3), cohort assignment, R7 context check, and an independent auditor that rebuilds histories from the logs; mutation-tested against three broken filters.
- [FEAT] [N1.3] — stage runner: content-addressed store, cache keys, lineage, run log, counter-based CRN draws, cohort buckets, stale-cache version guard.
- [FIX] [W0.1] — data scan labels use forward slashes on Windows (L-15).
- [FEAT] [N1.1] — schemas and config: row contracts, simulator and run configs with file-and-key errors, summary schemas, column contracts, results format v1 fixtures.
- [FEAT] [W0.1] — repo and harness: EvalKit's lean Kova harness ported (12 gates, respect-ope gate, data scan), graph of 20 nodes and 116 capabilities generated from the Tech Spec, decisions D-1..D-21 (open source per OWNER D-21), carried lessons L-1..L-12.
- [DOCS] [—] — PRD and Tech Spec; PRD loophole review; owner rulings D-1, D-15, D-17, D-18.
