# Changelog

Format: `[TYPE] [NODE] — summary`, newest first.

- [FEAT] [N1.2] — data contract: seeded synthetic data in the exact KKBox formats, `offers data download|verify|synthetic`, DuckDB-streamed manifest with checksums and date ranges, nested archive unpacking with traversal checks, data card.
- [FEAT] [A2.3] — respect filter (R1 with nudges, R2, R3), cohort assignment, R7 context check, and an independent auditor that rebuilds histories from the logs; mutation-tested against three broken filters.
- [FEAT] [N1.3] — stage runner: content-addressed store, cache keys, lineage, run log, counter-based CRN draws, cohort buckets, stale-cache version guard.
- [FIX] [W0.1] — data scan labels use forward slashes on Windows (L-15).
- [FEAT] [N1.1] — schemas and config: row contracts, simulator and run configs with file-and-key errors, summary schemas, column contracts, results format v1 fixtures.
- [FEAT] [W0.1] — repo and harness: EvalKit's lean Kova harness ported (12 gates, respect-ope gate, data scan), graph of 20 nodes and 116 capabilities generated from the Tech Spec, decisions D-1..D-21 (open source per OWNER D-21), carried lessons L-1..L-12.
- [DOCS] [—] — PRD and Tech Spec; PRD loophole review; owner rulings D-1, D-15, D-17, D-18.
