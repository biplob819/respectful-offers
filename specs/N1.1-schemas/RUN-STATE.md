# N1.1 run state

**Now:** green

## History
- 2026-11-15 — started after W0.1 green; schemas, contracts, fixtures and 81 tests drafted during W0.1 verification.
- 2026-11-15 — converged; verifier round 1 disproved SCH-05 (date and action kinds, no table-level respect rules) and raised strictness, pickling, hash-seed, loader, summary and protected-name defects. All fixed with a test reproducing each input (L-16); three low items ruled in D-23.
- 2026-11-15 — verifier round 2 confirmed SCH-01..06; four remaining defects fixed with tests (arrow date and list columns, `row_from_record` and `load_summary` for strict models, YAML values that name their key, camelCase and two-word protected names) plus the low items (duplicate comparisons and spend periods, `simulated` must be boolean true, clean variant names, non-empty disparity groups).
- 2026-11-15 — converged twice; rows flipped green.
