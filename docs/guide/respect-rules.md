# How the respect rules work

The rules sit **outside** learning: a filter removes forbidden actions before any policy
chooses, so the bandit and the baseline face exactly the same constraints. An independent
auditor then re-derives every rule from the logs. It is written separately from the filter, so
a bug in one cannot hide in the other.

| Rule | Meaning |
| --- | --- |
| R1 | An offer a member declined is never offered again, nudges included |
| R2 | A member at risk sees a content nudge before any discount or plan change |
| R3 | The holdout (10% of members) is never contacted |
| R4 | Discounts stop at the period budget, charged at face value when sent |
| R5 | No offer is always allowed, and chosen when nothing beats it |
| R6 | Exploration is measured and reported |
| R7 | Decisions use allow-listed features only: never age, gender, city or their proxies |
| R8 | One decision per member per month |

Every respectful policy must show zero violations, or `offers evaluate` exits 1 and the report
says the results must not be published. The status quo ("discount everyone at risk") breaks
R1 and R2 on purpose and is reported with its violations, as the honest comparison.
