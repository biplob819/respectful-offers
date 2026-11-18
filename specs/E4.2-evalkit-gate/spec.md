# E4.2 Switch to `evalkit gate`

**Wave 4. Depends on:** E4.1. **Blocked on EvalKit v0.3.0 (EvalKit B5.4)**: `evalkit gate` (B5.3, GAT-01..GAT-10) ships in that release. Decisions: OWNER D-50, D-51, OWNER D-52; EvalKit D-61 (rules 1, 4), D-63, D-67.

## Goal
Gate releases with EvalKit's own `evalkit gate` on the committed `results/kkbox/metrics.json` and `configs/gates.yaml`, and give EvalKit's weekly canary real tests to run against this repo, so an EvalKit change that breaks this project fails EvalKit's build before it ships.

## Interface

### CI gates with `evalkit gate` (EVK-03)
- `evalkit-harness>=0.3.0,<0.4` is added as an optional extra (`[project.optional-dependencies] evalkit`) and to the dev group, never as a runtime requirement. `pip install respectful-offers` keeps working without EvalKit, and `offers metrics` imports nothing from it.
- CI runs `evalkit gate results/kkbox/metrics.json --config configs/gates.yaml --out ${{ runner.temp }}/gate.json` in place of `scripts/gate.py` (the step's exit code is the gate; the committed `results/kkbox/gate.json` stays the local oracle's output). Its verdict on the committed files must match the E4.1 one: exit 0, every fail gate holds, the two age-band disparity warnings listed, `simulated: true` shown.
- `scripts/gate.py` is kept only as a test oracle. A test runs both on the committed files and on each planted defect from `tests/evalkit/test_gate.py`, and requires the same exit code and the same pass/warn/fail status per gate row. Any disagreement is recorded as a decision and reported to EvalKit (D-61 rule 3), never patched silently on either side.
- The local validator (`validate_metrics1`) is checked against EvalKit's own metrics-1 loader on the committed file and on each planted defect: both accept, or both refuse.

### EvalKit canary coverage (EVK-04)
- New offline tests (`tests/evalkit/test_evalkit_contract.py`, marker `contract`, no network and no keys) import `evalkit`, load `results/kkbox/metrics.json` with EvalKit's public loader, and run EvalKit's gate API on `configs/gates.yaml`. They are skipped with a stated reason when the `evalkit` extra is not installed, and are never skipped in CI.
- These files are what EvalKit's canary runs (`tests=auto` collects every test file that imports `evalkit`). This repo imports only EvalKit's public API (`scripts/check_public_api.py` `PUBLIC` at the pinned version). A test parses this repo's sources with `ast` and fails on any `evalkit` import that is not public.
- EvalKit's registry row (`docs/downstream.tsv`: `respectful-offers`, `tests=none`) changes to `tests=auto` in EvalKit's own build (D-61 rule 4). This repo sends the request to the EvalKit build session with the pin, the install arguments (`--extra evalkit`) and the test file list. It never edits `~/EvalKit`.

## Out of scope
- Run-vs-run compare, monitoring and the improvement loop (E4.3).
- EvalKit's efficiency block (B5.3 §1b): not emitted. It measures model calls, and this project makes none (E4.1 spec).
