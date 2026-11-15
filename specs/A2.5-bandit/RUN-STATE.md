# A2.5 run state

**Now:** green

## History
- 2026-11-15 — bandit drafted while A2.1 was under verification.
- 2026-11-15 — after the A2.4 verifier (L-29): Monte Carlo normals keyed by period instead of a stateful RNG, so probabilities are deterministic and member-local; fallback uses the posterior mean. Converge run; verifier launched.
- 2026-11-15 — verifier round 1 (BND-03 and BND-06 disproved; BND-02 and BND-04 partly): exact choice probabilities replace Monte Carlo (D-35), floor applied last, frozen flag and settings travel with the posterior, posterior copied on load, context shape and order checked, R7 proxies refused, tests made non-vacuous (L-30). Converge 12/12; green.
- 2026-11-15 — verifier round 2: the round-1 fixes held; new gaps closed per D-37 and L-31 (validation on load, context names, NaN moments, R7 lists agree, outcome matching, bias bound).
