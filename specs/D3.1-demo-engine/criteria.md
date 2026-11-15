# D3.1 acceptance criteria

**DMO-01 — aggregates-only cube**
- No member id appears anywhere in the cube; every cell holds at least 20 members; counts (rounded to fives) and means and spreads (three significant figures) defeat differencing two cubes one member apart; small cells merge until none is small without mislabelling anyone, and a cohort under 20 is refused; a cube is built only from a pre-registered, audit-clean run with that run's simulator, config, data source and cohort; `offers demo-cube` writes it, never over a run's files or a foreign file, and exits 1 for an audit-failed run.

**DMO-02 — simulate**
- `simulate(budget, threshold, variant)` runs no offer, the rule-following baseline, the frozen bandit and the status quo on 20,000 synthetic members; it is deterministic; a zero budget means no discounts; the threshold slider changes allowed sets; the bandit is labelled with its training threshold; bad inputs, a variant the run never trained, and a tampered cube (unknown keys, small or fractional counts, inconsistent totals, out-of-range means, a protected decision feature, a missing posterior) are refused with clear errors.

**DMO-03 — latency**
- p95 latency over ten slider settings, the cold first call included, is under 2 s on a developer machine (3.5 s ceiling on shared CI runners); the target on the deployed page is measured in DEM-03 (D-43).

**DMO-04 — live auditor**
- Every respectful policy shows zero violations; the status quo's are shown.

**DMO-05 — agreement**
- At the reference settings, every policy's retained, paired incremental retained and offers per member-month lie within the full run's 95% intervals widened by two standard errors of the demo's own estimates, in every variant; a missing row fails; the check fails for a demo with the bandit and status quo swapped, the wrong variant's posterior, or no spreads.
