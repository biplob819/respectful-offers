# D3.1 — Demo engine

**Wave 3. Depends on:** A2.7, B2.2 (D-42). **Unblocks:** D3.2, A2.8 (which rebuilds the cube from real data).

## Goal
A fast, offline `simulate(budget, threshold, variant)` behind the public demo, built from an aggregates-only cohort cube so no member's data ever leaves the machine (Tech Spec §8, D-12, H9, H10, US7).

## Outputs (`respectful_offers.demo`)
- `cube.py`: `bands`, `merge_small` (cells of 20 or more), `build_cube`, `make_cube` (from a finished, audit-clean run: the evaluation cohort's aggregates, the frozen posteriors, the simulator text, the run's intervals for agreement).
- `engine.py`: `load_cube`, `sample` (20,000 synthetic members around each cell's mean and spread), `simulate`, `agreement`.
- `cli.py`: `offers demo-cube`.

## Rules
- The cube holds counts, means and spreads per cell of at least 20 members: no member id, row or hash.
- The threshold slider changes R2's allowed sets; the bandit stays the one trained at the reference threshold; at-risk denominators use the reference threshold.
- Every rollout is audited live; respectful policies must show zero violations.
- p95 latency under 2 s.

## Out of scope
- The Streamlit page (D3.2); the real-data cube (A2.8, REA-05).
