# A2.3 run state

**Now:** green

## History
- 2026-11-15 — filter and auditor drafted while N1.1 was under verification.
- 2026-11-15 — converged; verifier round 1 confirmed RSP-01..05 (auditor matched a brute-force re-implementation on 300 random logs; 10M rows in 12 s) and narrowly disproved RSP-06 (R7 failed open). Fixed every fail-open path and strengthened the mutation test to 7 mutants on a risk grid × 6 seeds (L-17, D-25).
- 2026-11-15 — verifier round 2 confirmed RSP-01..06 (brute force: 0 mismatches over 300 logs; every round-1 fail-open case now raises); fixed the four remaining items with tests: actions and responses must agree, the filter's protected list matches the auditor's, boolean and absurd periods refused, numpy float thresholds accepted. Audit cost at 10M rows: 26 s, +5.5 GB (noted for A2.7: audit one variant at a time). Ruled: no third round.
- 2026-11-15 — converged twice; rows flipped green.
