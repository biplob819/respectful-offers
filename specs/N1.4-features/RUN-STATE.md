# N1.4 run state

**Now:** green

## History
- 2026-11-15 — features drafted while N1.2 was under verification.
- 2026-11-15 — converged; verifier round 1 confirmed FEA-02, 03, 04, 06 (1M members × 60 days builds in 6 s per cohort) and disproved FEA-01 (duplicate labels multiply rows) and FEA-07 (cross-cohort duplicates refused); also cache identity by size only, a non-deterministic tie-break, audit rows dropped, overloaded drop counts and loader messages. All fixed with tests (L-25). Also: `scripts/check_staged.py` added after a CI break (L-24).
- 2026-11-15 — verifier round 2 confirmed FEA-02..07 (1M-member tie test: 0 rows differ; same-size label swap refused) and disproved FEA-01 again (duplicate profile rows); found that the stage hash missed helpers in other modules, so stale artifacts were served. Fixed: the version guard now hashes every imported project module (N1.3 fix, L-26), FeaturesStage bumped to version 2, duplicate profiles and null flags refused, timed `as_of` refused. Ruled: no third round.
- 2026-11-15 — converged twice; rows flipped green.
