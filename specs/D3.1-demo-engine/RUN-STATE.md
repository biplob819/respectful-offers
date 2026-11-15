# D3.1 run state

**Now:** green

## History
- 2026-11-15 — drafted during B2.2 verification; contract checks and the auditor vectorised to bring simulate() from 5.5 s to about 1.1 s; graph rewired so the engine builds on a synthetic run (D-42).
- 2026-11-15 — verifier: DMO-03, 04 confirmed; DMO-01 (cube not bound to its run), DMO-02 (tampered cubes accepted, KeyError for untrained variants) disproved; DMO-05 confirmed but insensitive to six mutants; differencing revealed a member. Fixed per D-43 and L-35.
