# A2.6 — Off-policy estimators

**Wave 2. Depends on:** A2.4. **Unblocks:** A2.7.

## Goal
Show what off-policy evaluation would say about each policy from logged data, and prove the estimators work by scoring them against the simulator's exact oracle where the truth is known (Tech Spec §7.2, D-1, C1, C3, FR7, US8).

## Outputs (`respectful_offers.ope`)
- `estimators.py`: `Logs` (period-1 logging-pilot data, validated), `check_support`, `fit_reward_model` (per-action gradient boosting, cross-fitted over two hash folds, one thread for small fits), `estimate(logs, target, "ips" | "snips" | "dr", ...)` → block-bootstrap 95% interval and effective sample size, `oracle_value`.
- `data.py`: `period1_view`, `logs_from_pilot`, `target_probabilities`.

## Rules
- Period 1 only; the estimators refuse anything else (C3).
- Logging propensities are exact (1/|allowed|); a target with mass outside the logger's support is refused.
- Intervals are raw percentiles of a block bootstrap over member-hash blocks.

## Out of scope
- Running OPE for every policy and variant and reporting it beside the oracle (A2.7).
