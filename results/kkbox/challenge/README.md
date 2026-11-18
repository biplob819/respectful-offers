# Challenges against the published run (E4.3 MON-02)

Each folder is one `offers challenge`: a retrained churn model and bandit against the champion
(`real-v2`), rolled out on the same 200,000 evaluation members in the champion's simulated
world under common random numbers (D-58). Outcomes are simulated; member features and churn
scores are real. Aggregates only: no member id or row.

- `challenge.metrics.json`: both arms (`arm: champion | challenger`) per variant, and the
  paired claim difference with Holm, in EvalKit's metrics-1 format.
- `challenge.json`: the decision, every reason, and the period's outcome checks (OWNER D-56).

| Challenge | Decision | Why |
|---|---|---|
| `real-v2-challenger-s20261122-e3` | NO-PROMOTION | the claim does not improve in the conservative (+0.16, interval −0.10 to +0.42) or central (−0.03, −0.25 to +0.19) variants; it does in the optimistic one (+0.63, +0.29 to +0.97). The rule needs every variant. |

Reproduce: `offers challenge --challenger-seed 20261122` (about 7 minutes on the real data).
