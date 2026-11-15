# A2.7 acceptance criteria

**EVL-01 — rollouts**
- Every policy (no offer, status quo, rule-following baseline, bandit, segment oracle) runs under every variant on one evaluation cohort; the holdout policy runs on the holdout cohort; cohorts are disjoint, cover the March cohort, and are stable.

**EVL-02 — metrics**
- Incremental retained equals retained minus no offer's; cost per incremental retained is present exactly when the incremental interval lies above zero and equals discount cost over the extra members, with resamples that keep nobody extra counted as unbounded; at-risk retention is null below 30 at-risk members; realised cost never exceeds face value over the horizon; exploration rate only for the bandit; intervals contain their points; the segment oracle has the highest LTV in every variant.

**EVL-03 — paired comparisons and Holm**
- Holm matches hand computation; a difference of identical draws is 0 with p = 1; comparisons cover every pair, metric and variant, including the pre-registered headline (members kept per 1,000 NTD) wherever both policies spend, and a separated pair's interval excludes 0.

**EVL-04 — OPE beside the oracle**
- IPS, SNIPS and DR rows for no offer, rule-following, segment oracle and bandit in every variant, each with the exact oracle and a `covered` flag that agrees with its interval; DR covers nearly every row.

**EVL-05 — audit**
- Every rollout (evaluation, holdout, logging pilot, every sweep level) is audited with holdout flags re-derived from the salted hash and all counts written to `audit.json`; every respectful policy and the holdout audit clean and the status quo's violations are reported; a real violation (a broken filter) makes the CLI exit 1.

**EVL-06 — holdout**
- The holdout-minus-no-offer retention interval contains 0 in every variant; the holdout is never offered anything; a split that puts a holdout member in another cohort is refused.

**EVL-07 — budget frontier**
- The sweep covers every budget level, swept policy and variant; spend per member never exceeds the budget over the horizon; at budget 0 nothing is spent, and members paying 0 are never offered a commercial action.

**EVL-08 — disparity**
- Offer rate and retained per 1,000 by age band and gender for each respectful offer-making policy, keyed `policy.metric.attribute`; groups under 30 members are suppressed, with complementary suppression so no hidden group can be recovered from the totals; protected attributes are never decision features.

**EVL-09 — summary.json**
- The summary round-trips through its schema, and `offers evaluate` itself stamps it simulated with prereg status, commit (in the cache key, `-dirty` for an uncommitted tree) and file hashes; it does not crash at 20,000 members; `--json` output stays JSON on a crash; misaligned inputs (members missing, duplicated or without audit rows) are refused; a rerun is byte-identical; `offers evaluate` runs end to end from synthetic data and reuses its cache.
