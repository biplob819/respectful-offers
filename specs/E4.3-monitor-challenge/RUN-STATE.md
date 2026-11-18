# E4.3 run state

**Now:** spec (blocked on EvalKit v0.4.0, B5.7)

## History
- 2026-11-17 — spec written ahead of EvalKit v0.4.0 (owner approved pre-speccing). B5.6 and B5.7 have capability rows in EvalKit's Tech Spec but no frozen spec yet, so this spec fixes only what this repo provides. `results/kkbox/features_stats.json` holds only per-feature means, so drift needs new binned distributions (MON-01).
- 2026-11-18 — owner ruling OWNER D-56 recorded; node started. Export side of MON-01 built on EvalKit's frozen LED-04 input shape: `offers monitor export` rebuilds the champion from the run's seed (checked to reproduce all 968,431 March scores exactly), writes February reference and March period metrics-1 files (feature shares on February decile bins, no bin under 30 members; Brier with a bootstrap interval, ECE, ten equal-width reliability bins) and `bins.json`. EvalKit main's `evalkit drift` reads them end to end: no feature drift (PSI < 0.01); calibration alarms (Brier +0.015, ECE +0.024), which warn under D-56. Waiting on EvalKit v0.4.0 for the ledger, `evalkit drift` in a release, and `offers challenge`.
