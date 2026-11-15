# N1.4 acceptance criteria

**FEA-01 — DuckDB ingestion**
- Both cohorts build from the raw CSVs through DuckDB with an explicit schema, without loading a log or transaction file into pandas; a label file listing a member twice is refused; every label-file member with usable history appears exactly once; members with no history and members whose rows were all excluded are dropped and counted separately; the latest-transaction choice is deterministic under any row order; the stage refuses raw files whose sha256 differs from the verified manifest.

**FEA-02 — feature builder**
- On a hand-built raw fixture, every feature equals a hand-computed value: tenure (and the first-transaction fallback), auto-renew and price per 30 days from the latest transaction (ties broken as specified), cancellations inside the 90-day window but not outside it, the listening trend (including the clip and a zero prior), plan days.

**FEA-03 — as-of guard and leakage test**
- Recorded provenance is strictly before `as_of`; adding, removing or changing any event on or after `as_of` (transactions or logs) leaves every feature unchanged; an early renewal booked before `as_of` is excluded and counted; a planted feature built without the cutoff is refused by `check_provenance`.

**FEA-04 — cohorts and labels**
- February features carry `train.csv` labels and March features carry `train_v2.csv` labels; a member only in `train_v2.csv` appears only in the March cohort.

**FEA-05 — allow-list and audit table**
- The features table holds exactly the `FEATURES` columns (no age, gender, city or channel); the audit table holds age band and gender for exactly the same members (`unknown` when the profile row is missing or the age impossible); no protected attribute can be named as a decision feature.

**FEA-06 — one command**
- `offers features` rebuilds both cohorts from raw files, writes stats (members, drops, churn rate, provenance), reuses the cached artifact on a second run, and exits 3 when no verified data exists.

**FEA-07 — your own data**
- `offers features --from-table` accepts a valid CSV or Parquet table (Parquet 0.0/1.0 booleans included; a member may appear once in each cohort) and refuses, naming the file, row and column: a bad boolean, a bad date, a negative tenure, a member twice in one cohort; and refuses missing or unexpected columns by name.
