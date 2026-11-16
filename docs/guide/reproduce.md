# Reproducing the published results

The published results come from the KKBox churn competition data with the pre-registered
simulator in `configs/simulator.yaml` (its sha256 is in `docs/prereg.md`).

1. Accept the competition rules on Kaggle and create an API token
   (`~/.kaggle/kaggle.json`, or `KAGGLE_USERNAME` and `KAGGLE_KEY`).
2. From a clone of the repository:

```bash
uv sync --all-extras
uv run offers data download            # needs the token; checksums every file
uv run offers run --all                # refuses to run unless the simulator is registered for real data
```

`runs/latest/summary.json` should match the published one in every number; the stamps say
`preregistered`, the data source and the commit. The data itself is never redistributed here:
see `DATA_CARD.md`.
