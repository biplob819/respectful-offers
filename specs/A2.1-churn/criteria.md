# A2.1 acceptance criteria

**CHN-01 — model**
- Trains on February with exactly the six model features; the same seed gives byte-identical March scores and another seed may differ; a cohort with one class is refused.

**CHN-02 — calibration**
- The calibration fold is a stable ~20% of February members disjoint from the fitting rows; the calibrator is monotone, shrinks small blocks toward the base rate and maps strictly inside (0, 1); permuting March labels leaves every March score unchanged; on synthetic data calibration lowers ECE on March versus the uncalibrated scores, or keeps it within 0.01.

**CHN-03 — March report**
- AUC and Brier carry raw (never clamped) bootstrap percentile intervals, shared between model and baseline, that contain their point estimates on the fixture; ECE equals a hand-computed value on a small example; reliability bins cover every March member once; a March cohort with one class is refused.

**CHN-04 — scores and bands**
- Every March member gets a risk in [0, 1]; `assign_bands` applies the simulator's risk and trend cuts exactly at their boundaries (a risk equal to a cut falls in the upper band) and refuses scores without features.

**CHN-05 — model card**
- The card lists the model features (equal to the allow-list), no protected attribute, an importance per feature, the training rows, and the features stage's provenance and early-renewal counts; no pickle or model object is written.

**CHN-06 — baseline**
- The report includes a two-feature (tenure, auto-renew) logistic baseline AUC with its interval, computed on the same bootstrap resamples as the model.
