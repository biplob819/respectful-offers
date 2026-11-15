# B2.1 — Results report

**Wave 2. Depends on:** A2.7. **Unblocks:** B2.2, B2.3, P2.1.

## Goal
A static, self-contained HTML report of one run that a reader can trust at a glance: every simulated number is labelled as simulated, the simulator is quoted in full, the pre-registration status is stamped, and the respect audit sits beside the results (Tech Spec B2.1, OWNER D-15, NFR1, NFR2).

## Outputs (`respectful_offers.report`)
- `svg.py`: inline-SVG line, dot-and-whisker and reliability charts; series differ by colour, marker shape and direct label (Okabe–Ito colours, themed by CSS variables).
- `build.py`: `render(summary, frontier, yaml, sha)` → HTML; `build_report(run_dir, simulator_yaml, out_dir)` → `index.html` + `charts/*.vl.json` (Vega-Lite with inline data).
- `cli.py`: `offers report [--root] [--run-id] [--simulator] [--model-card] [--out] [--json]`.

## Rules
- No scripts, no external requests: inline CSS and SVG only.
- Every simulator-dependent figure or section carries `data-simulated="true"` and shows "Simulated" in its own visible text; only the churn model (real labels) does not.
- The simulator file is quoted byte for byte and must be the one the run used (its sha256 matches the summary's simulator hash).
- Every chart has a table with the same numbers; light and dark themes; keyboard-reachable YAML block.

## Out of scope
- `offers report --example` and the bundled synthetic run (B2.2); hosting on GitHub Pages (B2.3).
