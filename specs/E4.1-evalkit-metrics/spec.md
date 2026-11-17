# E4.1 EvalKit metrics export

**Wave 4. Depends on:** A2.8 (the published `summary.json`), B2.2 (the CLI contract). Decisions: OWNER D-50, D-51, OWNER D-52; EvalKit D-61 to D-63.

## Goal
Write the run's results in EvalKit's frozen metrics-summary format (`metrics-1`, EvalKit `specs/B5.3-gates/spec.md` §1–2 at commit 7986e5c), and gate releases on them with a gates file in EvalKit's format, so that switching to `evalkit gate` when EvalKit v0.3.0 ships is a one-line change in CI.

## Interface

### `offers metrics` (EVK-01)
`offers metrics [--summary results/kkbox/summary.json] [--out results/kkbox/metrics.json] [--json]`
- Reads `summary.json` through `load_summary`, writes `metrics-1` JSON (sorted keys, LF, trailing newline). The output is a pure function of the summary: `created_at` is the run's `finished_at` (else `started_at`), so the file is byte-stable.
- Top level: `schema_version: "metrics-1"`, `project: "respectful-offers"`, `run_id`, `created_at`, `simulated: true`, `provenance` {`code_version`: the run's git sha, `snapshot`: `"simulator:<simulator_hash>"`, `config_hash`, `evalkit`: null}.
- Metrics (labels in braces):
  - per policy row {policy, variant}: `retained_per_1000`, `incremental_retained_per_1000`, `retained_per_1000_at_risk` (when present), `offers_per_member_month` (ratio, interval); `ltv_proxy_per_member`, `cost_per_incremental_retained` (when present) (NTD, interval); `discount_cost_total` (NTD); `no_offer_share`, `exploration_rate` (when present) (rate, `n` = members); `max_offers_in_a_month` (count);
  - `violations` (count) {rule, policy, variant, respectful};
  - `spend.budget`, `spend.face_value_committed`, `spend.realised_cost` (NTD) {policy, variant, period};
  - comparisons {a, b, variant}: `diff.<metric>` (the comparison's own unit, interval), `separated.<metric>` (bool), `p_value.<metric>` (rate);
  - `ope.value` (NTD, interval), `ope.oracle` (NTD), `ope.covered` (bool), `ope.effective_sample_size` (ratio) {policy, variant, estimator};
  - `holdout_check` (ratio, interval) {variant};
  - `churn.auc`, `churn.baseline_auc`, `churn.brier` (ratio, interval), `churn.ece` (ratio), `churn.reliability.predicted` and `churn.reliability.observed` (rate, `n` = members in the bin) {bin};
  - `group.offer_rate` (rate), `group.retained_per_1000` (ratio), interval, {policy, variant: central, age_band | gender}.
- Units: `count`, `rate`, `bool`, `ratio` (per-1,000 figures, AUC, Brier, ECE, sizes) and `NTD`. Every interval carries `ci_method`: `"block-bootstrap percentile 95% (D-16)"`, or `"paired block-bootstrap percentile 95%; Holm per metric and variant (D-16)"` for comparisons. Intervals are copied exactly, never recomputed; a point outside its own interval is an error, never a silent fix.
- `validate_metrics1(doc)` applies every `metrics-1` rule: required and unknown top-level keys, provenance keys, metric name pattern, unit vocabulary and value domain (integers checked as parsed, never via float), `n`/`k`, both-or-neither interval with `ci_method`, `ci_low ≤ value ≤ ci_high`, flat scalar labels, unique (`name`, `labels`), and no member-shaped value anywhere (KKBox `msno` pattern or any key named like an id).

### Gates (EVK-02)
`configs/gates.yaml` in EvalKit's gates format (§2), severities per OWNER D-52. `scripts/gate.py <metrics.json> [--config configs/gates.yaml] [--json] [--out gate.json]` implements the subset this file uses: `labels` with `"*"`, `bound: point|lower|upper`, `op` `>=`/`<=`/`==`, `severity: fail|warn`, `disparity: <label>` on point values (the summary has no group `n`, so `bound: upper` on a disparity is an error). Exit codes: 0 every fail gate holds, 1 a fail gate fails, 2 bad input or a gate that matches nothing. Prints `simulated: true` first, then every gate row and the verdict; writes `gate.json` on every exit path. `results/kkbox/metrics.json` and `results/kkbox/gate.json` are committed; CI runs `offers metrics --check` style drift checks and the gate.

## Out of scope
- Importing `evalkit` (no release has `evalkit gate` yet); the registry row flips to `tests=auto` in the node that does.
- Run-vs-run compare (EvalKit B5.6) and monitoring (B5.7).

## EvalKit's efficiency block (B5.3 §1b, EvalKit D-67)
Not emitted. Every name in it measures model calls (tokens, cache hits, cost and latency per case, retries, errors, eval overhead and system cost), and this project makes none: the run is a deterministic simulation with no per-case cost or latency to report. The spec allows skipping what does not apply to a simulator. If a later node measures decision latency, it is emitted as `latency_p50`/`latency_p95`/`latency_p99` (ms).
