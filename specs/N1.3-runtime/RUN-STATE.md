# N1.3 run state

**Now:** green

## History
- 2026-11-15 — runtime drafted while N1.1 was under verification.
- 2026-11-15 — converged; verifier round 1 confirmed RUN-02, 03, 04, 06 (CRN draws identical on Python 3.11–3.13, uniformity checks pass on 500k members) and disproved RUN-01 (mixed key types) and RUN-05 (non-deterministic behaviour hash, late mixins, module constants, downgrades). All fixed with tests, plus read-only artifacts with input re-hashing, simulator hash and instance params in keys, lineage for failures and imports, race-free run.json, safe import names, streamed hashing, logged key errors, integer periods (L-18, D-26).
- 2026-11-15 — verifier round 2 confirmed RUN-01..04 and 06, disproved RUN-05 again (ABC and Generic bases, imported constants, re-added stages) and found a failing stage could still poison its input. All fixed with tests (L-19); Windows drive names and float root seeds refused. Ruled: no third round, every finding is pinned by a regression test.
- 2026-11-15 — converged twice; rows flipped green.
- 2026-11-15 — fix from the N1.4 verifier: `behaviour_hash` now includes the full source of every project module a stage imports, transitively, excluding the runtime package (L-26).
