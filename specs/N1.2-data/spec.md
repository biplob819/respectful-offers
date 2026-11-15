# N1.2 — Data contract, synthetic fixture and download tooling

**Wave 1. Depends on:** N1.1. **Unblocks:** N1.4, N1.5.

## Goal
The pipeline can be built and tested end to end without the real KKBox files, and the real files can be fetched, unpacked and verified with one command the moment the owner provides a Kaggle token (D-24). Raw and member-level data can never reach the public repo.

## Outputs (`respectful_offers.data`)
- `kkbox.py`: competition slug, rules URL, each file's exact columns and date columns.
- `synthetic.py`: `generate(out_dir, SyntheticSpec)` writing all seven KKBox files with the competition's columns, YYYYMMDD dates and label definition, seeded, ids `S000001…`.
- `verify.py`: `verify(raw_dir, manifest)` → `data/manifest.json` (sha256, bytes, rows, columns, date ranges), streaming with DuckDB; `DataError` naming the fixing command.
- `download.py`: `download(data_dir, client)` with the `KaggleClient` protocol, the real `KaggleApiClient` (optional `[data]` extra), credential detection that never prints secrets, nested zip/7z unpacking with path-traversal checks, then `verify`.
- CLI: `offers data download | verify | synthetic` with exit code 3 for missing data and `--json`.
- `DATA_CARD.md`, honest about what is pending N1.5.

## Out of scope
- The real download and the licence ruling (N1.5). Feature building (N1.4).
