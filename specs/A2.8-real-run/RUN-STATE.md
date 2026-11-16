# A2.8 run state

**Now:** green

## History
- 2026-11-17 — simulator confirmed (OWNER D-47) and pre-registered for real runs. First real run `real-v1` (16 min, audit clean) carried a `-dirty` commit, so `real-v2` was run from clean commit 2faad55: identical results.
- 2026-11-17 — decision review: replay equals the run in every variant; R1, R2, budget and eligibility read correct. The demo's agreement check failed on the bandit's offers per member-month: the cube gave members their cell's mean price. Cells now carry price levels (D-49); all 36 checks pass. The report now cites the challenge (OWNER D-46).
- 2026-11-17 — verifier round 1: no blocker; eight should-fix (a false README reference, the opt-in test covered one variant, the price-level tests could not fail, R1 and cross-period R2 were not counted, the demo did not cite the challenge, two stages reused from a dirty-tree run, a thin replay check, an unverifiable Pages claim) and four nits. All fixed: an independent R1/R2 recount equals the auditor's in every variant; features and scores rebuilt from raw with an empty cache are byte-identical; the committed cube rebuilds exactly and every price level stands for five or more members (opt-in tests). Ruled: no second round.
- 2026-11-17 — converged twice; rows flipped green.
