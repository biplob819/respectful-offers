# A2.3 — Respect filter and auditor

**Wave 2. Depends on:** N1.1. **Unblocks:** A2.4.

## Goal
The two respect rules, and the holdout and fairness rules around them, are enforced in front of every respectful policy, and independently audited from the logs, so zero violations is measured, not asserted (Tech Spec §6.1–6.2, D-4, OWNER D-18).

## Outputs (`respectful_offers.policy`)
- `respect.py`: `allowed_actions` (bool mask over `ACTIONS`), `declined_mask`, `assign_cohorts` (salted hash buckets, D-8), `check_context_columns` (R7).
- `audit.py`: `audit(decisions, outcomes, churn_risk=, holdout=, risk_threshold=, context_columns=, allow_list=)` → `AuditReport` with R1, R2, R3, R7, R8 counts and examples per policy × variant. It imports nothing from `respect.py`.

## Rules
- R3: holdout members get only `no_offer`. R1: every shown action declined earlier is removed, nudges included. R2: at or above the risk threshold with no earlier nudge, only `no_offer` or `content_nudge`. `no_offer` is always allowed.
- "Nudge tried" means a nudge was shown in an earlier period, whatever the response.
- The auditor rebuilds declines and nudges from the decision and outcome logs; risk and holdout come from the scoring and cohort stages, never from the rollout's own state.
- Policies that are not respectful (`status_quo`, `unfiltered_bandit`) are audited and reported, but do not fail the run.

## Out of scope
- Policies, the budget pacer and the rollout engine (A2.4).
