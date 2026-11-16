# A2.8 acceptance criteria

**REA-01 — real run, pre-registered**
- `results/kkbox/summary.json` validates, says `data_source: kaggle`, `prereg_status: preregistered`, all three variants and every policy in each; its simulator hash is the committed `configs/simulator.yaml`'s and is registered in `docs/prereg.md` with scope `real`; its config hash is `configs/run.yaml`'s; its commit is a clean commit (no `-dirty`); the evaluation cohort is the configured `eval_sample`; the audit is clean and covers every policy and rollout.

**REA-02 — real decisions read end to end**
- `results/kkbox/decision-review.md` reports, per variant, a replay of the run equal to `summary.json` to the last digit, the sampled strata, what the traces showed for R1, R2, budget and eligibility, and every reason an offered member did not renew. The committed per-variant findings show no choice outside the allowed set for any policy and no period-1 commercial offer to an at-risk member for any respectful policy (the status quo's are counted), and hold no member ids. `OFFERS_REAL_DATA=1` recomputes the findings from the local run and they match.

**REA-03 — churn model and leakage on real cohorts**
- The committed churn report equals the one in `summary.json`; the model beats its two-feature baseline; every feature's latest source event is before its cohort's as-of date in both the features stats and the model card; no protected attribute is used; the model is trained on February and evaluated on March.

**REA-04 — published outputs pass the publish scan and respect D-46**
- Every file under `results/kkbox/` and `demo/cube.json` passes the data scan, holds no member id, and the report and the results README cite the challenge and say no member data is published.

**REA-05 — demo cube rebuilt from the real run**
- `demo/cube.json` loads, is built from `real-v2` (run id, simulator hash, data source `kaggle`, members equal to the evaluation cohort within rounding), and passes the agreement check (DMO-05) for every policy, metric and variant; every price level covers at least `K_LEVEL` members (D-49).
