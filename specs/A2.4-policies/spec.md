# A2.4 — Policies, budget and rollout

**Wave 2. Depends on:** A2.2, A2.3. **Unblocks:** A2.5, A2.6.

## Goal
Every policy the evaluation compares, a budget pacer that can never overspend, a logging pilot with exact propensities, the segment-oracle ceiling, and the multi-period rollout engine that runs them all on the same members under common random numbers (Tech Spec §2.3, §6.3, D-1, D-7, OWNER D-17).

## Outputs (`respectful_offers.policy`)
- `cohort.py`: `Cohort`, `build_cohort(scores, features, simulator, variant, seed)` (risk and trend bands, hidden segments from CRN).
- `baselines.py`: `View`, `Policy` (probabilities, choose, priority, fallback), `NoOffer`, `Holdout`, `StatusQuo` (not respectful), `RuleFollowingBaseline`, `LoggingPolicy`, `SegmentOracle`.
- `budget.py`: `face_values`, `admit`.
- `rollout.py`: `rollout(policy, cohort, simulator, variant, ...)` → decisions, outcomes, states (contract-checked) and per-period spend.

## Rules
- Respectful policies put zero probability outside the allowed set (the engine refuses otherwise); the status quo sees every action.
- Face value is charged when an offer is sent; committed spend never exceeds the period budget; downgrades go to the policy's best free allowed action.
- One decision per active member per period; a member who does not renew leaves.
- Propensity logged is the policy's probability of the action it requested.

## Out of scope
- The bandit (A2.5), estimators (A2.6), metrics and comparison (A2.7).
