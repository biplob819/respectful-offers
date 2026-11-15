# A2.4 acceptance criteria

**POL-01 — policy interface**
- Every policy's probabilities are non-negative and sum to 1 per member; a respectful policy that puts mass on a forbidden action makes the rollout raise; `choose` samples in proportion to the probabilities.

**POL-02 — baselines**
- No-offer and holdout never offer anything; the status quo discounts every at-risk member every period, re-offering declined discounts (its R1 and R2 violations are counted by the auditor); the rule-following baseline nudges an at-risk member first, discounts only after a nudge, never re-offers a declined action, and audits clean.

**POL-03 — budget pacer**
- For random requests, priorities and budgets, committed face value never exceeds the budget; higher priority is admitted first with ties broken stably by member hash; downgrades go to a free action; a zero budget admits nothing costly; a negative or NaN budget or a non-finite priority raises.

**POL-04 — logging pilot**
- Chooses uniformly among allowed actions, logs propensity exactly 1/|allowed|, and is not budgeted.

**POL-05 — segment oracle**
- Picks the allowed action with the highest known-segment expected reward (ties to no offer); its exact period-1 expected value is at least that of every other respectful policy on the same cohort.

**POL-06 — rollout engine**
- One decision per active member per period; members who do not renew leave; declines and nudges carry into the next period's allowed sets; logs pass their column contracts; every respectful policy audits clean; the same seed gives identical logs; two policies that make the same choice for a member in period 1 see the same outcome for that member (common random numbers).
