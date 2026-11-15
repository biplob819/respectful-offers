# B2.2 run state

**Now:** green

## History
- 2026-11-15 — modules built during B2.1 verification; CLI wired after B2.1 was committed; your-own-table flow run end to end in a fresh `offers init` project.
- 2026-11-15 — verifier: CLI-01, 02, 05, 06 confirmed (with gaps); CLI-03 (example overwrote user files via a marked folder and symlinks) and CLI-04 (no JSON on usage errors; warm cache hid a missing raw file) disproved; prereg bypasses through `simulate` and a stale source marker. Fixed per D-41 and L-34.
