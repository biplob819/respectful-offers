# D3.2 run state

**Now:** green

## History
- 2026-11-15 — page and AppTest tests drafted during D3.1 verification; deploy bundle added; publishing is the owner's step after A2.8 (D-44).
- 2026-11-15 — verifier: DEM-01 rendered but not truthful (numbers under a 'must not be shown' banner, hard-coded holdout claim), DEM-02 passed but telemetry was on in deployment, DEM-03 failed (tampered cubes accepted, symlinks followed, uninstallable pin). Fixed per D-45 and L-36.
- 2026-11-17 — reopened for DEM-04 (OWNER D-48): the owner asked for passkey protection on the deployed page.
- 2026-11-17 — DEM-04 verifier round 1: two blockers (the committed deploy file was a stale bundle and would have opened with no passkey; the numbers are public elsewhere by design) and two should-fix (a top-level secret could clear the fail-closed env flag; the throttle could overshoot and be used to lock everyone out), plus six nits. All fixed with tests; the scope is written into OWNER D-48 (L-38). Ruled: no second round.
- 2026-11-17 — converged twice; DEM-04 green.
