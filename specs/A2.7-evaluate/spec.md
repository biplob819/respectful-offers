# A2.7 — Evaluate and compare

**Wave 2. Depends on:** A2.5, A2.6. **Unblocks:** B2.1, B2.2, A2.8.

## Goal
One command, `offers evaluate`, that rolls out every policy under every simulator variant on the same evaluation members, audits every log, compares the policies with paired intervals, reports off-policy estimates beside the exact oracle, checks the holdout, sweeps the budget and audits disparity, then writes `summary.json` (Tech Spec §7, US1–US5, US8).

## Outputs (`respectful_offers.evaluate`)
- `stats.py`: `Resampler` (one seeded block-resample matrix shared by every policy, metric and variant), `interval`, `mean_interval`, `ratio_interval`, `paired` (difference and two-sided bootstrap p-value), `holm`.
- `metrics.py`: `member_outcomes`, `summarise` → `PolicySummary` and the draws kept for paired comparisons.
- `pipeline.py`: `split` (salted-hash cohorts, D-8; evaluation sample keyed by member), `evaluate_variant`, `disparity`, `check_inputs`, `run_evaluation`, `write`.
- `stage.py`: `EvaluateStage` (features + churn artifacts → `summary.json`, `frontier.json`, `audit.json`).
- `cli.py`: `offers evaluate [--variant all|name] [--exploratory] [--json]`; exit 1 if any respectful policy or the holdout has a violation.
- `configs/run.yaml`: the run configuration.

## Rules
- Denominators are fixed by the evaluation cohort and the reference threshold, never by a policy.
- Incremental figures are paired against no offer on the same members under CRN.
- The status quo is reported with its violations (OWNER D-17); every respectful policy must audit clean.
- OPE estimates are scored against the exact oracle on members' own segments (D-36), at period 1, before the budget (D-33).
- Disparity is audit only: age band and gender are never decision features (R7, D-34).
- `summary.json` is stamped `simulated: true` with `prereg_status`, the git commit, the config and simulator hashes.

## Out of scope
- The report (B2.1), the full CLI (`run --all`, `doctor`; B2.2), real KKBox data (A2.8).
