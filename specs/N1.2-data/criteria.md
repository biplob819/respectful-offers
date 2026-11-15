# N1.2 acceptance criteria

**DAT-01 — download command**
- With a fake Kaggle client that serves a bundle zip of per-file archives, `download` unpacks the seven files in a staging folder, verifies them and installs them into `data/raw/` all or nothing (a failed download leaves nothing behind), never replaces real data, refuses duplicate copies of a file, and records `source: kaggle`. The real Kaggle client imports with the `[data]` extra, and its `exit()` calls become `DataError`s. With no credentials it raises `DataError` naming the environment variables and the rules URL, and the CLI exits 3. Archive members that escape the target folder are refused. Credentials never appear in any message. A 403 from Kaggle maps to "accept the rules".

**DAT-02 — verify command**
- `verify` records sha256, size, rows, exact header, min/max and unparseable count of every date column, and the data's source; a missing file, a wrong header or delimiter, a header with no rows, a ragged row, a corrupt manifest, or a file changed since the manifest each raise `DataError` naming the file and the fix, without echoing row contents.

**DAT-04 — raw data never committed**
- `.gitignore` covers `data/`, `.offers/` and `runs/`; the data scan refuses the generated synthetic files if they were ever staged; the package imports no network client outside `data/download.py` (NFR3).

**DAT-05 — synthetic fixture**
- Writes the seven files with the competition's exact columns and YYYYMMDD dates, including the awkward real-data cases (other plan lengths, discounts, duplicates, late returns, March-only members, members missing from `members_v3.csv`, outliers) and no renewal booked before a cohort's as-of date; `offers data synthetic` never overwrites unmarked data and records `source: synthetic`; is byte-identical for the same seed (under uv.lock) and different for another; `transactions.csv` and `user_logs.csv` end by 2017-02-28 and the `_v2` files lie in March 2017; labels follow the competition's definition (a non-churner has a renewal within 30 days of expiry, a churner has none); churn rates are between 3% and 12%; a two-feature model of the generated data separates churners (AUC above 0.7); no member id matches the KKBox id shape.

**DAT-06 — data card**
- `DATA_CARD.md` names every file used, the label definition, the as-of rule, what is never published and the synthetic fixture, and marks date ranges and the licence as pending N1.5 rather than stating them.
