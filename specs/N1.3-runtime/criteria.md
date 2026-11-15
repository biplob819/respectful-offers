# N1.3 acceptance criteria

**RUN-01 — stage contract and cache key**
- The key is stable under dict key order and across processes; it changes when any of stage name, code version, an input's content, params (instance attributes by default), config hash, simulator hash or seed changes; NaN, infinity, sets and non-string mapping keys are refused; a stage without name or version cannot run.

**RUN-02 — content-addressed store**
- `put` publishes atomically and read-only: a write that raises leaves no artifact; a second `put` of an existing key returns the first artifact untouched (first writer wins), including under concurrent writers; malformed keys are refused; `content_hash` changes with any file name or byte; a stage that modifies an input artifact fails and stores nothing.

**RUN-03 — lineage**
- `run.json` lists every stage run (failed ones with their error) and every imported source, with key, sorted parent keys, cache hit, start time and seconds, plus git SHA, config hash, simulator hash and seed; concurrent writers of one run never collide; imported file names cannot escape the artifact.

**RUN-04 — seed tree and CRN streams**
- `stage_seed` is stable (pinned values) and differs by stage; `member_uniforms` gives each member identical draws whatever the cohort, order or batch, different draws per period and stream, values in [0, 1) that pass a uniformity check; `bucket` is stable and spreads members roughly evenly.

**RUN-05 — resume and version check**
- Rerunning a run reuses every finished stage without executing it; a changed input reruns only the affected stage and those after it; the behaviour hash is identical across processes; the version check flags a behaviour change without a `code_version` increase (class source anywhere in the MRO, class or module constants, `extra_sources` helpers), refuses non-integer versions and downgrades, and `--update` refuses to accept any of these.

**RUN-06 — run log and folder**
- `run.log` has one JSON line per stage run (stage, key, cache hit, seconds, error); a failed stage logs its error and leaves nothing in the store.
