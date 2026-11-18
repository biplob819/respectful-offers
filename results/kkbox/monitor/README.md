# Drift and calibration inputs (E4.3, aggregates only)

Inputs for EvalKit's drift monitor (`evalkit drift`, EvalKit LED-04, v0.4.0), written by
`offers monitor export` from the published run `real-v2`. Real KKBox member features, churn
scores and churn labels; nothing here is simulated, and no file holds a member id or row.

| File | What it holds |
|---|---|
| `reference-2017-02.metrics.json` | February: each model feature's share of members per bin (`drift.feature_share`), and the churn model's calibration on its February calibration fold (`churn.brier`, `churn.ece`, ten equal-width reliability bins) |
| `period-2017-03.metrics.json` | March, the same rows on the same bins: the first monitored period, scored out of time |
| `bins.json` | The bin edges behind every `drift.feature_share` row (February deciles, merged so no bin holds fewer than 30 members) |

**Read the calibration change with care.** The isotonic calibrator was fitted on the February
fold, so February's calibration is in-sample for it and flatters the model. March is the honest
out-of-time figure; the February-to-March change overstates true calibration decay.

**First check (2026-11-18, EvalKit main 3882a09):** no feature drifted (every PSI below 0.01);
calibration worsened out of time (Brier +0.015, ECE +0.024, both outside EvalKit's tolerance).
Under OWNER D-56 calibration drift warns and never blocks a release.

The rebuilt churn model is checked against the run's published March scores and must match
them exactly, so these figures describe the model the run published.
