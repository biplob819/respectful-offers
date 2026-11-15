# A2.5 — Thompson sampling bandit

**Wave 2. Depends on:** A2.4. **Unblocks:** A2.7.

## Goal
A contextual bandit that learns, in simulation, which allowed action earns the most net revenue for which member, including when to make no offer, with an exact, logged choice distribution so off-policy estimators can evaluate it (Tech Spec §6.4, D-6, FR5, R5, R6, R7).

## Outputs (`respectful_offers.policy.bandit`)
- `static_context(features, churn_risk, decision_features)`: the member-level context from allow-listed features only.
- `Posterior` (JSON round-trip), `ThompsonBandit` (a `Policy`): disjoint Bayesian linear models on revenue as a share of price; exact choice probabilities (a one-dimensional integral per action, D-35); a support floor applied after normalising; posterior-mean priority for the budget; `observe` (learning) and `freeze`; exploration rate.
- `train_bandit(...)`: epochs of simulated rollouts on the training cohort, learning curve of the greedy policy's exact period-1 value, then frozen.

## Rules
- Context columns are a subset of the allow-list; dynamic flags (nudged, declined) are added per period.
- Probabilities are zero outside the allowed set and at least 1/(2·draws) inside it.
- A frozen bandit never changes its posterior.

## Out of scope
- Evaluation and comparison (A2.7).
