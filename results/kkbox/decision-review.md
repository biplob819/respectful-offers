# Real decisions, read end to end (REA-02)

Run `real-v2` (commit `2faad55e0a77`, simulator `6ae089599c41b741`, pre-registered), 200,000 evaluation members drawn from the 968,431-member March 2017 cohort of the [WSDM Cup 2018 KKBox churn prediction challenge](https://www.kaggle.com/competitions/kkbox-churn-prediction-challenge). Every outcome that depends on an offer is **simulated**; the members, their features and their churn risk are real.

Lesson L-11 says: before trusting a headline, read real decisions end to end and confirm every failure reason. This file is that reading. It holds aggregates only: the member-level traces stay on the machine that ran it (`runs/real-v2/decision_review/`, git-ignored), as the licence ruling requires (OWNER D-46).

## How

`scripts/review_decisions.py` rebuilds the run's evaluation cohort from its own stored features and scores, replays the no-offer, status-quo, rule-following and bandit rollouts for each variant with the run's frozen bandit posterior, and joins every decision to its outcome and to the member's hidden simulator segment. It first checks that the replay **is** the run (retained members, offers per member-month and discount spent, for every policy), then writes a stratified sample of 36 members per variant (at-risk and offered, offered and declined, sleeping dogs who were offered something, at-risk but not offered that month) for reading, and the aggregate checks in [`decision_review/`](decision_review/).

## The replay is the run

Retained members per 1,000, replay against `summary.json`, equal to the last digit in every variant:

| Variant | No offer | Status quo | Rule-following | Bandit |
| --- | --- | --- | --- | --- |
| conservative | 858.685 | 865.145 | 863.365 | 861.230 |
| central | 858.685 | 870.345 | 869.465 | 866.530 |
| optimistic | 858.685 | 875.025 | 876.290 | 873.130 |

## What the traces show

Read member by member, period by period (allowed set, requested action, chosen action, budget, response, renewal, revenue), every decision follows the rules it should:

- **R1, a declined action is not shown again** (declining includes ignoring, OWNER D-18). A member who declined a plan change in period 2 had it removed from the allowed set in period 3; a declined nudge never came back, while an accepted one could be shown again.
- **R2, content before commerce for members at risk.** At-risk members (churn risk at or above 0.15) were allowed only the content nudge in period 1.
- **Counted over every member and period**, independently of the auditor's code, the respectful policies break neither rule in any variant, and the status quo's violations equal the auditor's exactly (the violations it exists to show, OWNER D-17):

| Status quo | R1: shown again after a decline | R2: commercial offer to an at-risk member with no earlier nudge |
| --- | --- | --- |
| conservative | 7,361 | 24,799 |
| central | 6,540 | 24,950 |
| optimistic | 5,538 | 25,079 |

  Bandit and rule-following baseline: 0 and 0 in every variant.
- **No choice outside the allowed set**, for any policy in any variant (0 of about 1.7 million member-periods per policy).
- **Budget.** When the month's budget ran out, a requested discount became the next free action or no offer and was flagged. The status quo, which offers only discounts, hit the budget hardest (34,240 to 36,755 downgraded requests); the bandit hardly at all (0 to 1,160).
- **Eligibility.** The 0.47% of members paying 0 NTD were never offered a discount or a plan change: there is nothing to discount (D-38). An accepted half-price discount on a 149 NTD plan earned 74.50 NTD, as specified.

## Why members who were offered something still did not renew

Every non-renewal after an offer falls into a reason the simulator states. In the central variant, for the bandit:

| Hidden segment | Declined the offer | Accepted it |
| --- | --- | --- |
| Lost cause | 3,403 | 356 |
| Persuadable | 3,018 | 979 |
| Sleeping dog | 1,876 | 444 |
| Sure thing | 2,917 | 1,232 |

- **Declined offers** are the largest group: about half of persuadables and most lost causes decline (the acceptance table in the simulator).
- **Accepted a content nudge and still left**: accepting a nudge raises renewal by 12 points for a persuadable (central), it does not guarantee it. Accepting a *commercial* offer always means renewing on it, so no member who accepted a discount or a plan change is in the "accepted" column for those actions.
- **"Sure things" who did not renew.** In this simulator a sure thing is a member whose renewal an offer does not change; they still renew only at their own base rate, 1 − churn risk (D-2). The name follows the uplift-marketing convention but does not mean "always renews"; the README's glossary says so.
- **Sleeping dogs** lose renewal when shown an offer, even one they decline (the exposure effect).

## What the bandit actually does

The bandit's lower cost per retained member comes from *what* it offers, not from offering less:

| Central variant, share of member-periods | No offer | Nudge | Plan change | Discount |
| --- | --- | --- | --- | --- |
| Bandit | 84.7% | 13.5% | 1.4% | 0.4% |
| Rule-following baseline | 91.6% | 5.6% | – | 2.8% |
| Status quo | 95.6% | – | – | 4.4% |

It leans on the free content nudge and the cheaper plan, and rarely gives the half-price month, so it spends about a third of the baseline's discount for about three-quarters of its extra retained members. One cost of that choice, visible in the traces: the bandit shows something to more **sleeping dogs** (11,007 member-periods in the central variant against the baseline's 6,767), mostly nudges, whose harm in this simulator is small (−1 point, central). Under the conservative variant (weaker persuasion, more sleeping dogs, more harm from exposure) its lead on the pre-registered headline over the rule-following baseline narrows from 5.6 to 1.7, though it stays clear of zero (paired 95% bootstrap interval 1.3 to 2.2, and separated after the Holm correction the pre-registration names).

## Found while reading, and fixed before any number was published

- **The demo disagreed with the run** on the bandit's offers per member-month (0.144 against 0.152 to 0.154, central). Members rebuilt from the cube had their cell's *mean* price, while real prices are mostly a few plan prices (90.7% of members pay 0, 99, 149 or 180 NTD per 30 days); price decides eligibility and enters the bandit's context. Each cube cell now carries its price levels, each covering at least five members (D-49). All 36 agreement checks pass on the real run, and the agreement rule was not changed.
- **The report did not cite the challenge**, which OWNER D-46 requires of every published output: it now does, in its footer.

## Provenance

`real-v2` ran at clean commit `2faad55`. Its features and churn stages were reused from the stage cache, written by `real-v1`, which ran on the same code with uncommitted changes (the confirmed simulator's comment and the demo's passkey gate, neither of which the features or churn stages read). To close that gap, the features and churn scores were rebuilt from the raw files with an empty cache and compared byte for byte with the cached ones: see the README.
