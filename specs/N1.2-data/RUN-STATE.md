# N1.2 run state

**Now:** green

## History
- 2026-11-15 — started after N1.1 green; scope narrowed by D-24 (real download and licence moved to N1.5).
- 2026-11-15 — converged; verifier round 1 disproved DAT-01 (real client unimportable without `six`; `exit()` on bad credentials) and found the synthetic command could overwrite a real download, plus verify, manifest, fixture-realism, early-renewal and download-robustness gaps. All fixed with tests (L-21, D-27, D-28).
- 2026-11-15 — verifier round 2 confirmed DAT-01, 02, 04, 05, 06 (labels rebuilt from transactions match for three seeds; every hostile archive refused; no secret leaks). Fixed the six remaining items with tests (L-22). Ruled: no third round.
- 2026-11-15 — converged twice; rows flipped green.
