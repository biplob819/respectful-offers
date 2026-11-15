# A2.6 acceptance criteria

**OPE-01 — IPS and SNIPS**
- IPS of the logging policy itself equals the mean logged reward exactly and its effective sample size equals n; SNIPS normalises by the summed weights.

**OPE-02 — doubly robust**
- With the true conditional expectation as q̂, the DR interval covers the oracle; the fitted reward model is cross-fitted (changing one fold's rewards changes predictions only for the other fold); DR without a reward model is refused.

**OPE-03 — intervals**
- Intervals come from a block bootstrap over member-hash blocks and cover the exact oracle (members' own segments) for no-offer, rule-following and segment-oracle targets on one pilot, with no slack; fewer than 20 populated blocks, more than 1% undefined SNIPS resamples, or a target with zero weight on every logged action are refused.

**OPE-04 — validation against the oracle**
- Over 200 replicate pilots of 4,000 members, for no offer, rule-following, the segment oracle and a peaked stochastic target, the 95% intervals of SNIPS and DR cover the exact oracle value between 90% and 99% of the time, with mean signed error below 1 NTD per member (D-36).

**OPE-05 — support and effective sample size**
- A target with mass outside the logger's allowed set is refused; non-distributions are refused; a peaked target has a smaller effective sample size than a uniform one.

**OPE-06 — period-1 scope**
- Logs for any period other than 1, and target probabilities from a view at another period, are refused; logs must come from one logging-pilot run of the named variant, with outcomes from the same run, the view's allowed sets, exact uniform propensities and aligned, distinct members.
