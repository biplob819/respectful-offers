# Respectful Offers

A subscription offer policy that predicts churn risk, chooses offers with a Thompson sampling bandit, and obeys two respect rules: a declined offer stays declined, and at-risk members see content before commerce. It is evaluated offline against a holdout, on real KKBox member behaviour with **simulated** offer responses.

**Status:** under construction, built node by node with a gated build harness. Run `python scripts/status.py` for live progress.

- Product: [Respectful Offers PRD](Respectful%20Offers%20PRD.md)
- How it is built: [Respectful Offers Tech Spec](Respectful%20Offers%20Tech%20Spec.md)

Licence: MIT. KKBox data is not included and is never committed; see the data card once node N1.2 lands.
