# A2.5 acceptance criteria

**BND-01 — model**
- After observing data, each action's posterior mean and precision equal the closed-form Bayesian ridge solution on that action's data; non-positive, non-finite or non-numeric hyperparameters, integration nodes outside 8..256 and support floors outside (0, 0.05] are refused; NaN features are refused.

**BND-02 — training and freezing**
- `train_bandit` trains for the given epochs and returns a frozen bandit whose posterior does not change during an evaluation rollout; the posterior round-trips through JSON exactly, carries its frozen flag and settings, and is copied (never shared) when loaded; the same seed gives identical posteriors.

**BND-03 — choice probabilities**
- Choice probabilities are exact integrals (D-35): for two allowed actions they match Φ((m₁ − m₂)/√(s₁² + s₂²)) within 1e-3, and for three or four actions with scales up to 150x apart they match adaptive quadrature within 2e-3; they are zero outside the allowed set, at least the support floor inside it (after normalising) and sum to 1; they depend only on the member; the logged propensity equals the probability of the requested action.

**BND-04 — R5, no offer when nothing beats it**
- When every offer's posterior is far below no offer, the bandit chooses no offer for nearly every member; on synthetic data a trained bandit's no-offer share is above 5% (far above what the floor alone gives) and its exploration rate is reported.

**BND-05 — learning curve**
- The curve holds one point before training and one per epoch; the trained greedy value exceeds the untrained one by more than 0.5 NTD per member and never exceeds the respectful segment oracle's exact period-1 value.

**BND-06 — allow-listed context**
- A protected, proxy (`city_id`, `userGender`) or non-allow-listed column in the context raises; a context of another shape or column order raises; the bandit's context columns are logged for the auditor's R7 check and audit clean.
