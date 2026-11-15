# B2.2 — CLI

**Wave 2. Depends on:** A2.7, B2.1. **Unblocks:** B2.3, D3.2.

## Goal
One command line for the whole pipeline, usable from any folder after `pip install respectful-offers`, on the KKBox files or on the user's own features table (Tech Spec §4, OWNER D-21, NFR4).

## Outputs
- `cli.py`: `data`, `features`, `churn`, `prereg`, `simulate`, `evaluate`, `report` (with `--example`), `run --all`, `doctor`, `init`; `--json` on every command; exit codes 0 ok, 1 audit failed, 2 configuration or runtime error, 3 raw data missing; a top-level handler that keeps `--json` output JSON.
- `features/table.py`: `TableFeaturesStage` — the user's table (plus an optional audit table) as the features artifact, so churn and evaluate run unchanged.
- `doctor.py`, `scaffold.py`, `templates/` (byte-for-byte copies of `configs/`), `examples/` (the bundled synthetic run), `scripts/make_example.py`.

## Rules
- Default config paths resolve to `configs/…`, then the files `offers init` writes, then the bundled templates.
- `offers init` and `offers report --example` never overwrite a user's files or write into a run folder.
- `offers doctor` never prints a credential.
- Any data that is not synthetic (KKBox, verified local files, the user's table) needs a `real`-scope pre-registration, or `--exploratory`.

## Out of scope
- Hosting the report (B2.3); PyPI release (B2.4).
