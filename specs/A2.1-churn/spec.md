# A2.1 — Churn model and calibration

**Wave 2. Depends on:** N1.4. **Unblocks:** A2.2.

## Goal
A calibrated churn risk for every March member, from a model trained only on February and calibrated on a held-out February fold, with an honest March report and a model card (FR2, D-9, D-29, H11).

## Outputs (`respectful_offers.churn`)
- `model.py`: `train(feb, seed)` (gradient-boosted classifier on the allow-listed model features; isotonic calibration on a salted-hash 20% February fold), `report(model, feb, mar, seed)` → `ChurnReport` (AUC and Brier with bootstrap 95% intervals, ECE, quantile reliability bins, two-feature logistic baseline AUC), `importances`.
- `stage.py`: `ChurnStage` (input: features artifact) writing `scores_mar.parquet`, `report.json`, `calibration.json`, `model_card.json`; `assign_bands(scores, features, simulator_config)`.

## Rules
- March labels are used only to report, never to fit or calibrate.
- No fitted model object is stored (no pickles in the store).
- Model features: tenure, auto-renew, cancellations, listening trend, price per 30 days, plan days. No protected attribute.
- Deterministic for a seed: identical scores byte for byte.

## Out of scope
- Simulator semantics (A2.2) beyond assigning bands from its cut points.
