# A2.8 Real-data results run

Run the pre-registered pipeline on the real KKBox files (N1.5) for all three simulator variants from a clean commit; read real decisions end to end before any number is reported (L-11); re-run the churn report and the leakage checks on the real cohorts; publish only aggregates that pass the publish scan and respect OWNER D-46; rebuild the demo cube from the real run and re-check its agreement with the full run (D-42).

The real files never reach CI. The run's published outputs are committed under `results/kkbox/` and the demo cube as `demo/cube.json`; CI checks them against the code, the configs and the pre-registration. `OFFERS_REAL_DATA=1` re-runs the decision review against the local run.
