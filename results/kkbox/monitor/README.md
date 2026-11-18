# Drift and calibration inputs (E4.3, aggregates only)

Inputs for EvalKit's drift monitor (`evalkit drift`, EvalKit LED-04, v0.4.0), written by
`offers monitor export` from the published run `real-v2`. Real KKBox member features, churn
scores and churn labels; nothing here is simulated, and no file holds a member id or row.

| File | What it holds |
|---|---|
| `reference-2017-02.metrics.json` | February: each model feature's share of members per bin (`drift.feature_share`), and the churn model's calibration on its February calibration fold (`churn.brier`, `churn.ece`, ten equal-width reliability bins) |
| `period-2017-03.metrics.json` | March, the same rows on the same bins: the first monitored period, scored out of time |
| `bins.json` | The bin edges behind every `drift.feature_share` row (February deciles, merged so no non-empty bin holds fewer than 30 members; a feature whose deciles are one value, `cancels_90d`, keeps a bin above it; empty bins are left out) |
| `drift-ref.json` | EvalKit's frozen reference (`drift-ref-1`) from the February file, with its own hash, written by `offers monitor drift` |
| `drift.json` | EvalKit's check of March against it (`drift-1`) at `configs/drift.yaml`: PSI per feature, Brier, ECE and per-bin calibration changes with 95% intervals |
| `drift.metrics.json` | The same figures as metrics-1, recorded in EvalKit's run history `docs/measurements/runs.jsonl` |

**Read the calibration change with care.** The isotonic calibrator was fitted on the February
fold, so February's calibration is in-sample for it and flatters the model. March is the honest
out-of-time figure; the February-to-March change overstates true calibration decay.

**The check (2026-11-18, EvalKit 0.4.0):** no feature drifted (every PSI below 0.01, `cancels_90d` 0.0001); calibration worsened out of time (Brier +0.015, ECE +0.024, both beyond EvalKit's tolerance; reliability bins 3 to 5 off by 0.12 to 0.20). Under OWNER D-56 every drift and calibration alarm warns: `offers monitor drift` exits 0 and a challenger is the response.

The rebuilt churn model is checked against the run's published March scores and must match
them exactly, so these figures describe the model the run published.
