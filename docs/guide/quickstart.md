# Quickstart: a first result in five minutes

```bash
pip install respectful-offers          # or: uv tool install respectful-offers
offers doctor                          # checks Python, configs and data; prints no secrets
offers report --example                # renders the bundled example to report-example/index.html
```

Open `report-example/index.html`. It is a complete results report from synthetic members:
every policy under every simulator variant, the respect audit, the holdout check, off-policy
estimates beside the exact oracle, and the simulator quoted in full. Everything in it is
**simulated**, and the page says so on every figure.

To run the whole pipeline yourself on synthetic members:

```bash
offers data synthetic --members 20000  # generates KKBox-shaped files in data/
offers run --all --exploratory         # features, churn model, every policy, audit, report
```

`--exploratory` lets a run use a simulator you have not pre-registered; such runs are stamped
and never to be published. Next: [use your own data](own-data.md) or
[reproduce the published results](reproduce.md).
