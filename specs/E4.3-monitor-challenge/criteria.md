# E4.3 acceptance criteria

**MON-01** — `offers monitor` on the February baseline and the March period writes both periods' `metrics-1` files with binned feature shares (fixed baseline edges, no bin under 30 members, no member ids) and calibration blocks. EvalKit's LED-04 computes PSI and calibration deltas from them, and this repo has no PSI code of its own. A planted shift in one feature's distribution raises that feature's drift alarm and no other. A planted respect violation raises a fail alarm and exits 1. Every monitored outcome shows `simulated: true`. Alarm severities match an owner ruling recorded before the node starts.
**MON-02** — `offers challenge` rolls out champion and challenger on the same period members under common random numbers and exports the paired claim comparison with Holm. `evalkit compare` reports the deltas on every metric. The promotion rule in the spec is applied as written:
- a challenger that improves the claim in every variant with zero violations and no fail alarm is promoted;
- one that fails any condition is not promoted;
- a planted violation always blocks promotion.

Every challenge is recorded in EvalKit's experiment ledger and as a PROMOTION or NO-PROMOTION row in `docs/decisions.md`. A challenger that changes the simulator hash is refused.
