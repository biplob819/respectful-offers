# N1.3 — Stage runner and artifact store

**Wave 1. Depends on:** N1.1. **Unblocks:** N1.4, A2.2.

## Goal
Every pipeline step runs as a stage whose output is a content-addressed artifact, so a rerun resumes, an unchanged stage is never recomputed, lineage is recorded, and every random draw is reproducible and identical across policies for the same member (CRN, D-1, D-10).

## Outputs (`respectful_offers.runtime`)
- `stage.py`: `Stage` (name, `code_version`, `params()`, `cache_key`, `run`), `RunContext` (root, run id, config hash, seed, git SHA, simulator hash, store, lineage), `run_stage`, `import_artifact`, `canonical_json`, `git_sha`.
- `store.py`: `Store` with atomic, first-writer-wins `put`, `get`, `stored_hash`; `content_hash` over file names and bytes.
- `seeds.py`: `stage_seed`, `member_hashes`, `member_uniforms` (counter-based splitmix64 keyed by root seed, member hash, period, stream and draw), `bucket` (salted sha256 mod 100).
- `versions.py` and `versions.json`: behaviour hash per stage (MRO sources, class constants, declared `extra_sources`); a change without a `code_version` bump fails.
- Run folder: `runs/<run_id>/run.json` (lineage) and `run.log` (JSON lines).

## Rules
- Cache key = sha256 of canonical JSON of stage name, code version, input content hashes, params, config hash and seed. NaN, infinity and sets are refused in a key.
- A failed stage leaves no artifact and logs its error; a rerun retries it.
- `member_uniforms` for a member never depends on which other members are in the call or their order.

## Out of scope
- Concrete stages (from N1.4 on). Parallel execution: stages are cheap enough to run in order.
