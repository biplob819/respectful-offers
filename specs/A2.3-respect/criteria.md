# A2.3 acceptance criteria

**RSP-01 — allowed actions**
- For random member states (property test), the allowed set always holds `no_offer`, never holds a declined action, never holds a commercial action for an at-risk member without an earlier nudge, and holds only `no_offer` for holdout members; hand-checked cases cover each rule and the threshold boundary (risk equal to the threshold is at risk). Bad inputs (wrong shapes, non-bool flags, risk outside [0, 1], `no_offer` declined, threshold outside (0, 1)) raise.

**RSP-02 — one decision per member per period**
- The auditor counts every duplicate member-period decision as an R8 violation.

**RSP-03 — holdout assignment**
- `assign_cohorts` is stable across calls and order, puts each member in exactly one cohort, gives each cohort close to its bucket share, and refuses buckets that do not tile 0–100.

**RSP-04 — independent auditor**
- On hand-built logs, the auditor counts R1 (re-offer after decline, including a nudge), R2 (commercial before a nudge, at the threshold), R3 (an offer to a holdout member, a holdout member in another policy, a non-holdout member in the holdout policy), R7 and R8 exactly; clean logs count zero; histories come from the logs even when a state table would say otherwise; `audit.py` imports nothing from `respect.py`.

**RSP-05 — property and mutation tests**
- A mini rollout over random members, three periods and random responses, using the real filter, audits clean; the same rollout with each of three broken filters (one ignoring R1, one ignoring R2, one ignoring R3) is caught by the auditor on the matching rule.

**RSP-06 — R7 context check**
- `check_context_columns` refuses a protected attribute and any column outside the allow-list, and passes the allow-list or any subset of it (D-25); the auditor reports R7 per policy from the logged context columns and refuses to audit a policy whose context was not logged.

**All auditor inputs fail closed:** unknown actions or responses, orphan outcomes, non-integer periods, a NaN threshold, risks outside [0, 1], non-boolean holdout flags and an empty log raise; duplicate or conflicting outcomes count as R8 and any decline among them counts as a decline.
