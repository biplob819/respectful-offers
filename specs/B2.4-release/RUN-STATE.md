# B2.4 run state

**Now:** green

## History
- 2026-11-17 — history audit clean (498 blobs, 0 hits); version 0.1.0; project URLs and classifiers; README links made absolute so the PyPI page works; guides corrected (sure things, the cube's price levels); how-it-was-built note.
- 2026-11-17 — verifier round 1 (pre-release): the wheel installs and runs `offers doctor` and `offers report --example` from an empty folder; nothing private in the wheel or sdist; README renders for PyPI. Blocker: private vulnerability reporting was off while SECURITY.md points to it: turned on (verified `enabled: true`). Nit fixed: CI and release check out the full history so the history audit is not limited to the tip.
- 2026-11-17 — OSS-03 reproduction: a clean clone at 57f7d2c (uv sync --locked) plus the raw files, run with an empty cache (`offers run --all`, 860 s, audit clean), reproduced `results/kkbox/summary.json` in every field but the commit, run id and timestamps. The clone was stamped `-dirty` only because this check wrote its own log files (run.json, run.err) into it before the run; `git status` listed nothing else.
- 2026-11-17 — CI green on 57f7d2c (9 jobs); tagged `v0.1.0` there. Release run 43972264285: build (tests, scans, full-history audit), publish by trusted publishing, smoke on ubuntu, macos and windows: all success. `respectful-offers` 0.1.0 is on PyPI (OSS-03, OSS-05, OSS-06).
- 2026-11-17 — converged twice; rows flipped green.
