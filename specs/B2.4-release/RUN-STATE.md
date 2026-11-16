# B2.4 run state

**Now:** building

## History
- 2026-11-17 — history audit clean (498 blobs, 0 hits); version 0.1.0; project URLs and classifiers; README links made absolute so the PyPI page works; guides corrected (sure things, the cube's price levels); how-it-was-built note.
- 2026-11-17 — verifier round 1 (pre-release): the wheel installs and runs `offers doctor` and `offers report --example` from an empty folder; nothing private in the wheel or sdist; README renders for PyPI. Blocker: private vulnerability reporting was off while SECURITY.md points to it: turned on (verified `enabled: true`). Nit fixed: CI and release check out the full history so the history audit is not limited to the tip.
