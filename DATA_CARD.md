# Data card

What data Respectful Offers uses, what it does with it, and what it publishes. Sections marked *pending N1.5* are filled in when the real KKBox files are downloaded and verified with the owner's credentials (L-6: say what is true now).

## Source

The [WSDM Cup 2018 KKBox churn prediction challenge](https://www.kaggle.com/competitions/kkbox-churn-prediction-challenge) on Kaggle. KKBox is a Taiwanese music-streaming service. Member ids (`msno`) arrive already hashed by KKBox.

| File | Holds | Used for |
| --- | --- | --- |
| `members_v3.csv` | City, age (`bd`), gender, registration channel and date | Tenure only; age and gender go to the audit table, never into features (R7) |
| `transactions.csv`, `transactions_v2.csv` | Payments, plan days, list price, amount paid, auto-renew, expiry, cancellations | Auto-renew, cancellations, price, plan days, tenure |
| `user_logs.csv`, `user_logs_v2.csv` | Daily listening counts and seconds | 30-day listening trend |
| `train.csv`, `train_v2.csv` | `is_churn` for memberships expiring in February and March 2017 | Churn labels |

**Label.** As defined by the competition: a member churns if there is no new valid subscription within 30 days of the membership expiring.

**Date ranges.** *Pending N1.5.* The spec assumes `transactions.csv` and `user_logs.csv` run to the end of February 2017 and the `_v2` files cover March 2017. `offers data verify` records the real minimum and maximum of every date column in `data/manifest.json`, and node N1.4 enforces the as-of rule whatever they turn out to be.

## How it is used

- **As-of rule.** Features for a cohort use only events strictly before the first day of its label month (2017-02-01 for February, 2017-03-01 for March). A leakage test enforces it (N1.4).
- **Cohorts.** The March cohort is split by a salted hash of the member id: 10% holdout, 30% bandit training, 20% logging pilot, 40% evaluation (D-8).
- **Offer responses are simulated.** The data holds no offers. Every outcome that depends on an offer comes from the pre-registered simulator and is labelled "simulated" (NFR1).

## What is never committed or published

- Raw files and any member-level table (features, scores, decisions, outcomes) live under `data/`, `.offers/` and `runs/`, which git ignores. The data scan in CI refuses KKBox file names, data-file types, archives and anything that looks like a KKBox member id.
- Published outputs (report, `summary.json`, PR/FAQ, demo cube) hold aggregates only, and pass the publish scan.

## Licence

*Pending N1.5.* The owner reads the competition rules and records a ruling (`OWNER D-n`) before anything derived from KKBox data is published. If the rules forbid publishing derived aggregates, the project switches to an openly licensed churn dataset, recorded as a decision.

## Synthetic fixture

`offers data synthetic` writes seeded data in the KKBox file layout (`respectful_offers.data.synthetic`): the same files, columns, YYYYMMDD dates and label definition, with member ids like `S000042`. Its manifest says `"source": "synthetic"`, and it refuses to write over a folder holding real data. Its semantics are simpler than the real data's, although it includes the awkward cases: older 7-, 31- and 90-day plans, discounts and free months, same-day duplicates, cancellations, churners who return after 30 days, members only in the March cohort, members missing from `members_v3.csv`, impossible ages and negative listening seconds. Tests, the golden run and `offers report --example` use it, so the whole pipeline runs without the real files. Its churn rate (about 6–7%) and drivers (auto-renew, listening trend, cancellations, tenure, price) are made up to resemble the real problem. No result computed on it says anything about KKBox members.
