# N1.4 — Features

**Wave 1. Depends on:** N1.2, N1.3. **Unblocks:** A2.1.

## Goal
Member features for the February and March cohorts, computed strictly from events before each cohort's label month, with leakage measured rather than assumed (C4, D-9, D-28), and the same feature table accepted from anyone's own subscription data (OWNER D-21, D-27).

## Outputs (`respectful_offers.features`)
- `build.py`: `build_cohort(raw, cohort)` → features, provenance (latest source event per feature), members dropped for having no history, early-renewal rows dropped; `check_provenance`; `build_audit_attributes` (age band, gender, never joined into features); `summary_stats`.
- `stage.py`: `FeaturesStage` (input: the verified manifest; checks raw sizes against it) writing `features_feb.parquet`, `features_mar.parquet`, `audit_attributes.parquet`, `stats.json`; `load_features_table` for user tables.
- CLI: `offers features [--data-dir] [--from-table PATH] [--json]`.

## Rules
- Every source event used is strictly before `as_of` (2017-02-01, 2017-03-01). Transactions booked before `as_of` but expiring after the label month are early renewals: excluded and counted.
- Latest transaction = latest `transaction_date`, then latest expiry, then non-cancel first, among rows with a positive plan length.
- Listening trend uses song counts (the five `num_*` columns), never `total_secs` (which holds impossible values in the real data).
- Tenure falls back to the first transaction when a member has no `members_v3.csv` row.
- Age and gender never enter the features table.

## Out of scope
- The churn model (A2.1). Decision features for the bandit (A2.5) are chosen from this table by `RunConfig.decision_features`.
