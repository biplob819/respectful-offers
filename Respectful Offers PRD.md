# Respectful Offers PRD

Nov 14, 2026 · @Biplob Chakraborty

A subscription offer policy that predicts churn risk, chooses offers with a contextual bandit and obeys two respect rules: a declined offer stays declined, and at-risk members see content before commerce. It is evaluated offline against a long-term holdout.

## Overview and deliverables

The policy aims to keep more members for less discount spend by knowing when to make no offer at all, and it proves that against a holdout instead of a short-term click rate.

**Problem.** Subscription services often send discounts to everyone who looks likely to leave. That trains members to wait for a deal, costs margin and annoys loyal members with repeated offers.

**Goals.**

1. A churn-propensity model on real subscription behaviour from the KKBox data.
2. A Thompson sampling bandit choosing among four actions: no offer, content nudge, one-month discount, plan change.
3. Two respect rules enforced outside the learning loop.
4. Offline evaluation against a 10% no-offer holdout and a "discount everyone at risk" baseline, under three simulator assumptions.
5. A PR/FAQ and a simulator screen a reviewer can play with.

**Non-goals.** Sending real offers; a content recommender (the content nudge is a placeholder action); production serving.

**Deliverables.**

| Deliverable | What it is | Where it lives |
| --- | --- | --- |
| GitHub repo `respectful-offers` | Features, churn model, simulator, respect filter, bandit, off-policy evaluation, tests | GitHub, public |
| Results report | Retained members, discount cost, LTV proxy, offer fatigue, under three assumptions | Cloudflare Pages |
| PR/FAQ | A short working-backwards document | PDF, linked from the project page |
| Demo page | A policy simulator in the shared `portfolio-demos` app | Streamlit Community Cloud |
| Project page and video | Case study in the shared template; a 90-second video explaining the two rules and the result | Portfolio site |
| Supporting artifacts | One-page PRD, decision log, data card, "how I built it" note | Repo and project page |

## Personas, user stories and flows

Three personas drive eight stories; the six marked Must make up the first release.

**Personas.**

- **Subscription growth PM (primary).** Owns retention offers and their discount budget; judged on retained members and margin.
- **Member at risk of churning.** Would stay for the right content; resents being chased with discounts.
- **Time-poor reviewer.** A product or ML leader who gives the project five minutes and looks for ML product judgement at scale: offers, experimentation, long-term holdouts.

**User stories.**

| ID | As a | I want to | So that | Acceptance criteria | Priority |
| --- | --- | --- | --- | --- | --- |
| US1 | Growth PM | see retained members per 1,000 at-risk under each policy | I pick the policy that keeps the most members | Bandit, baseline and holdout compared on the same members | Must |
| US2 | Growth PM | see discount cost per retained member | I protect margin | Cost per retained member per policy | Must |
| US3 | Member | never be offered something I already declined | I am not pestered | Zero violations of rule R1 in evaluation | Must |
| US4 | Member at risk | be shown something to watch before being offered a deal | I am treated as a viewer, not a target | Zero violations of rule R2 in evaluation | Must |
| US5 | Growth PM | see how results change if offer responses differ from my assumptions | I trust the conclusion | Results under conservative, central and optimistic simulators | Must |
| US6 | Reviewer | read a short PR/FAQ | I see working-backwards thinking | One page plus FAQ | Must |
| US7 | Growth PM | adjust the discount budget and risk threshold in a demo | I see the trade-off myself | The simulator screen recomputes in under 2 seconds | Should |
| US8 | Growth PM | see confidence intervals on every estimate | I do not over-read noise | Intervals on every off-policy estimate | Should |

**Flow A. Evaluate policies (US1 to US5).**

1. `offers features` builds member features from transactions and listening logs.
2. `offers churn` trains and calibrates the churn model.
3. `offers simulate --variant central` generates logged data from a simple logging policy.
4. `offers evaluate` estimates each policy's value with inverse propensity scoring and doubly robust estimators, applying the respect filter first.
5. Steps 3 and 4 repeat for the conservative and optimistic variants; `offers report` builds the comparison.

**Flow B. Play with the simulator (US7).**

1. The reviewer opens the demo, which loads the central-variant results.
2. They move the discount budget and risk threshold sliders, or switch simulator variant.
3. Charts update for retained members, discount cost and offer fatigue, with the respect-rule violation count fixed at zero.

## Requirements

Ten functional requirements and five non-functional bars; the bar that matters most is labelling every simulated number as simulated.

**Functional.**

| ID | Requirement | Stories |
| --- | --- | --- |
| FR1 | Member features from the KKBox files: tenure, auto-renew, recent cancellations, 30-day listening trend | US1 |
| FR2 | A gradient-boosted churn model on the competition's labels, with AUC and a calibration plot on a held-out month | US1 |
| FR3 | A response simulator in one YAML file: renewal probability and discount cost per action and risk band, in three variants | US5 |
| FR4 | A respect filter applied before every decision (rules R1 and R2) | US3, US4 |
| FR5 | A Thompson sampling bandit over the allowed actions, using the churn model's features | US1, US2 |
| FR6 | Logged data from a simple logging policy, with propensities recorded | US1 |
| FR7 | Inverse propensity scoring and doubly robust estimates, with confidence intervals | US1, US8 |
| FR8 | Comparison of bandit, baseline and holdout on every success metric, per variant | US1, US2, US5 |
| FR9 | A short PR/FAQ | US6 |
| FR10 | A simulator screen with budget and threshold sliders | US7 |

**Non-functional.**

| ID | Area | Bar |
| --- | --- | --- |
| NFR1 | Honesty | Every number that depends on the simulator is labelled "simulated"; the write-up quotes the simulator YAML in full |
| NFR2 | Safety | Zero respect-rule violations across all runs |
| NFR3 | Cost | No API cost; runs on a laptop in minutes |
| NFR4 | Reproducibility | Seeds fixed; one command rebuilds features from raw files |
| NFR5 | Licensing | KKBox competition rules read before publishing anything derived; raw data never committed |

## Behavioral spec

The policy is a decision system rather than a chatbot, so its spec defines which actions it may take for whom; each rule is checked on every evaluation run.

| ID | Rule | Type | Check |
| --- | --- | --- | --- |
| R1 | Never offer an action a member has declined before | Never | Violation count, must be zero |
| R2 | For members above the risk threshold, allow only no offer or the content nudge until a nudge has been tried | Must | Violation count, must be zero |
| R3 | Keep a 10% holdout that never receives offers | Must | Holdout size and leakage check |
| R4 | Stay within the discount budget per period | Must | Spend against budget per run |
| R5 | Choose "no offer" when the expected value of every offer is below it | Must | Share of no-offer decisions reported |
| R6 | Explore new actions within the allowed set | May | Exploration rate reported |
| R7 | Use age or gender as a decision feature | Never | Feature list check |
| R8 | Show more than one offer per member per month | Never | Offer fatigue metric |

**Good decision.** A member with high risk and no nudge history receives a content nudge, not a discount (R2).

**Bad decision.** The same member receives a second one-month discount after declining the first (breaks R1).

## Trust architecture

Members are protected by rules the learning loop cannot override, and the business is protected by a holdout and honest uncertainty.

| Layer | What it does | Risk it handles | Evidence |
| --- | --- | --- | --- |
| Respect filter | Removes forbidden actions before the bandit chooses | Pestering members; training them to wait for discounts | Zero violations in every run |
| Long-term holdout | 10% of members never get offers | Mistaking short-term lift for real retention | Holdout comparison in the report |
| Budget cap | Stops discounts at the period budget | Margin loss | Spend against budget |
| Fairness constraint | Age and gender excluded from decision features | Discriminatory targeting | Feature list in the repo |
| Calibrated risk | Churn scores checked for calibration before use | Acting on mis-scaled risk | Calibration plot |
| Uncertainty shown | Confidence intervals and three simulator variants | Over-reading a single number | Report shows all three |
| Transparency | Simulator assumptions published in full | Hidden assumptions driving results | YAML quoted in the write-up |

Offer responses are simulated, because the data holds no offers; the PR/FAQ says what a real A/B test would add.

## Wireframe: policy simulator

&#91;embedded content: wireframe · policy simulator screen\]

The screen lets a growth PM explore how budget and risk threshold change members retained and discount spent under each policy. The holdout card keeps the comparison honest, and the footer never lets anyone forget the outcomes are simulated.

## Data flow

&#91;embedded content: data flow · member data to offer decision to offline evaluation\]

The top row uses real member behaviour; everything from the simulator onward is simulated and labelled that way. The respect filter sits between risk scoring and every policy, so the baseline and bandit face the same constraints, and the holdout sees no offers at all.

## Technical architecture

&#91;embedded content: technical architecture · components and hosting\]

- **Package.** Python 3.12 with uv; pandas and DuckDB for features; LightGBM for the churn model with scikit-learn's calibration tools; NumPy for the Thompson sampling bandit; a small off-policy evaluation module for inverse propensity scoring and doubly robust estimates, with bootstrap intervals.
- **No model APIs.** This project is classical ML on purpose: it shows you choose the right tool, and it costs nothing to run.
- **Report and demo.** Static HTML on Cloudflare Pages; the simulator page in the shared Streamlit app reads cached member scores and the three simulator variants.

## Data model and interfaces

Four schemas and one simulator file define the whole experiment.

```python
class Member(BaseModel):
    msno: str                        # KKBox member ID
    tenure_days: int
    auto_renew: bool
    cancels_90d: int
    listening_trend_30d: float       # change in daily listening
    churn_risk: float                # calibrated probability
    declined_actions: set[str]
    nudged: bool
    in_holdout: bool

Action = Literal["no_offer", "content_nudge", "discount_1m", "plan_change"]

class Decision(BaseModel):
    msno: str
    period: int
    allowed: list[Action]            # after the respect filter
    chosen: Action
    propensity: float                # for off-policy evaluation
    policy: Literal["bandit", "discount_all_at_risk", "holdout"]

class Outcome(BaseModel):
    msno: str
    period: int
    renewed: bool                    # simulated
    discount_cost: float             # simulated
    revenue_90d: float               # LTV proxy, simulated
```

```yaml
# simulator.yaml (central variant, illustrative structure)
risk_bands: [low, medium, high]
renewal_probability:
  no_offer:      {low: ..., medium: ..., high: ...}
  content_nudge: {low: ..., medium: ..., high: ...}
  discount_1m:   {low: ..., medium: ..., high: ...}
  plan_change:   {low: ..., medium: ..., high: ...}
discount_cost:   {discount_1m: ..., plan_change: ...}
```

The values are left blank here on purpose: they are set during the build and pre-registered before the first evaluation, and the write-up quotes all three variants in full.

**CLI.** `offers features`, `offers churn`, `offers simulate --variant central`, `offers evaluate`, `offers report`.

**Demo functions.** `simulate(budget, threshold, variant)` recomputes the comparison from cached member scores in under 2 seconds. No model or API calls.

## Success metrics and risks

Success is a clear answer to "does respectful targeting keep more members per dollar?" under every simulator variant, with zero rule violations.

**Success metrics.**

| Metric | Definition | Target |
| --- | --- | --- |
| Retained members | Per 1,000 at-risk, against holdout and baseline | Reported per variant |
| Discount cost per retained member | Discount spend divided by members retained | Bandit below baseline under the central variant, or the write-up explains why not |
| 90-day LTV proxy | Expected revenue per member | Reported per variant |
| Offer fatigue | Offers per member per month | One or fewer |
| Respect-rule violations | R1 and R2 breaches | Zero |
| Churn model quality | AUC and calibration on a held-out month | Reported |

**Risks.**

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| The simulator drives the result | High | High | Three variants; assumptions published; conclusions stated as conditional |
| KKBox terms restrict derived data | Medium | Medium | Read the rules first; publish only aggregates; switch to an openly licensed churn dataset if needed |
| The download is large for a laptop | Medium | Low | Use the transactions and member files first; sample the user logs |

## Sources

Checked on 14 November 2026.

- [WSDM Cup 2018 KKBox churn, winning paper](https://www.arxiv.org/pdf/1802.03396.pdf)
