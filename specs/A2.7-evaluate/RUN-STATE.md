# A2.7 run state

**Now:** green

## History
- 2026-11-15 — pipeline, metrics, stats, stage and `offers evaluate` built while A2.5 and A2.6 were under verification; smoke run on 8,000 synthetic members in 12 s, audit clean, oracle highest LTV in every variant.
- 2026-11-15 — verifier: EVL-01..04, 06..08 confirmed; EVL-05 (holdout leak audited clean) and EVL-09 (crash at 20,000 members on a per-period spend check) disproved. Fixed per D-38 and L-32; the 20,000-member repro now runs in 26 s, audit clean.
