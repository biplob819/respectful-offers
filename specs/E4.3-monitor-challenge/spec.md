# E4.3 Monitoring and improvement on EvalKit B5.7

**Wave 4. Depends on:** E4.2. **Built on EvalKit v0.4.0 (tagged 2026-11-18, D-59)**, which ships the monitoring and improvement ledger (B5.7: LED-01 run history, LED-02 trend and alarm bands, LED-03 experiment ledger with a freeze guard, LED-04 drift and calibration monitor, LED-05 PSI drift defaults). Run-vs-run compare (B5.6: RVR-01..RVR-03) ships earlier, in v0.3.0. Decisions: OWNER D-50, D-51; EvalKit D-62, D-63, D-65.

**Interface status.** Written on 2026-11-17 before EvalKit froze B5.7; built against EvalKit 0.4.0's public `evalkit.drift` and `evalkit.ledger` (D-59).

**Honest limit.** Member features, churn scores and calibration are real KKBox data. Offer responses still come from the pre-registered simulator. Monitoring therefore shows how the loop works and catches drift in the real inputs. It does not measure how real members respond to offers, and every monitored outcome carries `simulated: true`.

## Goal
Run the policy period after period the way a live deployment would. Each period the monitor checks whether the inputs drifted, the churn model's calibration held, the rules held and the cost per extra member kept moved. Each time a challenger (a retrained churn model and bandit) earns promotion, it is promoted only by a pre-stated rule, with a record.

## Interface

### `offers monitor` (MON-01)
`offers monitor export [--run-id real-v2] [--out-dir results/kkbox/monitor]` writes the drift and calibration inputs; `offers monitor drift [--reference <metrics-1>] [--period-drift <metrics-1>] [--drift-config configs/drift.yaml] [--ledger docs/measurements/runs.jsonl]` has EvalKit freeze the reference, check the period (writes `drift-ref.json`, `drift.json`, `drift.metrics.json`) and record it in the run history; `offers monitor check --period <metrics-1> [--baseline <metrics-1>] [--out alarms.json]` runs the outcome checks at the OWNER D-56 severities (0 pass, 1 fail, 2 bad input). Cost and disparity need a baseline period and are reported as not checked without one, never as passed.
- Periods come from the real data: the KKBox files cover several label months, so February serves as the baseline and March as the first monitored period. With more months, each later month becomes another period. A period run is the existing pipeline with a later `as_of` and the frozen champion (no retraining).
- **This repo provides, aggregates only:**
  - each period's `metrics.json` (`metrics-1`, from E4.1);
  - per-feature binned distributions for drift: `drift.feature_share` (rate) {feature, bin}, with fixed bin edges stored with the baseline. Bins with fewer than 30 members merge into their neighbour, so no small group shows.
  - calibration per period: `churn.brier`, `churn.ece`, reliability bins;
  - respect violations, cost per extra member kept, and age-band disparity.
- **EvalKit computes:** PSI per feature and Brier/ECE/reliability deltas against alarm bands (LED-04, LED-05), the run history and trend (LED-01, LED-02), and the alarms. This repo adds no PSI code of its own (OWNER D-50: EvalKit owns the eval machinery).
- Exit codes follow EvalKit's gate scheme: 0 no fail alarm, 1 a fail alarm, 2 bad input. Alarm severities are set by the owner before the node starts (one ask sitting), in the way OWNER D-52 set gate severities.

### `offers challenge` (MON-02)
`offers challenge --challenger-seed <n> [--challenger-epochs <e>] [--run-id real-v2] [--baseline <metrics-1>] [--out-dir results/kkbox/challenge] [--record docs/decisions.md] [--ledger docs/measurements/experiments.jsonl] [--ledger-baseline results/kkbox/metrics.json] [--no-record] [--json]` (recording is on by default; an outcome check that could not run withholds promotion, D-59)
- The champion is the published run, rebuilt from its seed and checked to reproduce its March scores exactly. The challenger is a churn model and a bandit retrained with the challenger's seed (and epochs), on February data and the training cohort only (D-58).
- Both are rolled out on the champion's evaluation members **in the champion's simulated world**: base retention and hidden segments come from the champion's scores, so the world does not move when the model does; only what each policy reads differs. Decision and response draws are keyed by member, period and variant (common random numbers). The champion arm therefore reproduces the published bandit figure for figure.
- It exports `challenge.metrics.json` (`metrics-1`: both arms labelled `arm`, and `diff/separated/p_value.incremental_retained_per_1000_ntd` {a: challenger, b: champion, variant}, this repo's paired block-bootstrap intervals with Holm across the variants, D-16) and `challenge.json` (decision, reasons, the outcome checks of the period).
- Refused (exit 2): a changed simulator (D-3), a changed run config, a challenger identical to the champion, a champion that no longer reproduces its scores, challenger scores missing members.
- `evalkit compare` (RVR-01, RVR-02) reports the change on every metric. Its case-level resampling needs per-case data this repo never publishes (RVR-03's optional sidecar would be member-level). So this repo's own paired, member-level comparison stays the promotion test, and `evalkit compare` reports the deltas.
- **Promotion rule, stated before any challenger runs:** promote only if, in every variant:
  1. the claim metric improves (lower bound > 0, separated after Holm);
  2. the respectful policies have zero violations;
  3. no fail alarm fires from MON-01.
- **Record:** every challenge, promoted or not, is written to EvalKit's experiment ledger (LED-03: opened before either arm is rolled out, closed with EvalKit's compare of the per-arm files `champion.metrics.json` and `challenger.metrics.json`; the held-out `look` is not used, D-59) and to `docs/decisions.md` as a PROMOTION or NO-PROMOTION row with run ids and hashes. A challenger can never change the pre-registered simulator: a changed simulator needs a new pre-registration and a rerun of every variant (D-3).

## Out of scope
- Real offer responses, which need a real A/B test (PR/FAQ).
- Any change inside `~/EvalKit` (D-61 rule 4). Gaps found in B5.6 or B5.7 are reported to EvalKit's build with this repo's failing case (D-61 rule 3).
