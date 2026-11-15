# W0.1 — Repo and harness

**Wave 0. Depends on:** nothing. **Unblocks:** N1.1, and through it every other node.

## Goal
A repo that installs as `respectful-offers`, runs `offers --version`, and enforces the build process: no node starts before its dependencies are green, and no node turns green without proof that passes every gate.

## Inputs
- Respectful Offers Tech Spec §11 (build harness), §1 (decisions), §10 (testing).
- EvalKit harness: `~/EvalKit/scripts/` and `~/EvalKit/tests/harness/` (D-13, D-20).

## Outputs
- `pyproject.toml` (hatchling, src layout, Python ≥3.11 per OWNER D-21), `src/respectful_offers/` with `offers --version`, MIT licence, README stub, `.gitattributes` forcing LF.
- `.github/workflows/ci.yml`: lint, format, types, tests, scans, eligibility and build on push and PR, Python 3.11–3.13 on Linux, macOS and Windows.
- `docs/graph/graph.md` (20 nodes) and `docs/graph/catalog.tsv` (116 rows), generated from Tech Spec §11.2 and §11.4.
- `scripts/`: `harness_lib`, `verify_graph_eligibility`, `node_start`, `node_converge` (12 gates), `status`, `secret_scan`, `data_scan`, each gate script with `--self-test`.
- `docs/decisions.md` (D-1 to D-21), `docs/lessons.md` (L-1 to L-12 carried from EvalKit), `docs/prereg.md` stub, `changelog.md`.

## Out of scope
- Any pipeline code (starts at N1.1). The Typer CLI (B2.2).

## Constraints
- Harness scripts use only the standard library.
- No network calls except `uv build` / `uv pip` in gate 10.
