# W0.1 run state

**Now:** green

## History
- 2026-11-15 — harness ported from EvalKit; graph and catalog generated from the Tech Spec.
- 2026-11-15 — converged twice; verifier round 1 disproved HAR-05 (gate wiring untested, identities unchecked) and HAR-07 (archives, compressed rows, URL ids, no publish scan). Fixed: allow-list data scan with publish scan, real-gate self-tests with identities, exact CI permission and step tests, whole-word criteria matching, Kaggle patterns (L-13, D-22). OWNER D-21 (open source) widened Python to 3.11–3.13 on three OSes.
- 2026-11-15 — verifier round 2 confirmed HAR-01..06 and disproved HAR-07 (pandas `\/`, percent and entity encodings, UTF-32, PDFs); two gate mutants survived. All fixed, each with a test reproducing the verifier's input (L-14). Raw-name false positives on `train.py` and Kaggle checksum false positives fixed; fallback walk skips caches; every workflow's write scopes are checked. Ruled: no third round, because every finding is pinned by a regression test.
- 2026-11-15 — converged twice; rows flipped green.
