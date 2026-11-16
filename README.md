# Respectful Offers

A subscription offer policy that predicts churn risk, chooses offers with a Thompson sampling bandit, and obeys two respect rules: a declined offer stays declined, and at-risk members see content before commerce. It is evaluated offline against a holdout, on real KKBox member behaviour with **simulated** offer responses.

**Status:** under construction, built node by node with a gated build harness. Run `python scripts/status.py` for live progress.

- Live demo: [respectful-offers.streamlit.app](https://respectful-offers.streamlit.app/), a policy simulator (every outcome simulated; synthetic members until the real-data run lands)
- Product: [Respectful Offers PRD](Respectful%20Offers%20PRD.md)
- How it is built: [Respectful Offers Tech Spec](Respectful%20Offers%20Tech%20Spec.md)

Licence: MIT. KKBox data is not included and is never committed; see the data card once node N1.2 lands.

## Glossary

- **Simulated.** KKBox's data holds no offers, so how a member responds to one comes from a stated, pre-registered simulator (`configs/simulator.yaml`). Members, features, churn labels and churn risk are real; every outcome that depends on an offer is simulated.
- **Response segments.** The simulator gives each member a hidden segment, as in uplift marketing. A *sure thing* is a member whose renewal an offer does not change: they still renew only at their own base rate (1 − churn risk), so "sure" does not mean "always renews", and a discount to them is wasted. A *persuadable* renews more when shown an offer; a *lost cause* leaves whatever you do; a *sleeping dog* is reminded to leave by an offer, even one they decline.
- **At risk.** Churn risk at or above the configured threshold (0.15).
- **R1, R2.** The respect rules: an action a member declined is not shown again (R1); members at risk see content before any commercial offer (R2).
