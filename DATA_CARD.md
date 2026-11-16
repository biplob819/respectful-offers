# Data card

What data Respectful Offers uses, what it does with it, and what it publishes. The real files were downloaded with the owner's credentials and verified on 2026-11-17 (node N1.5); the full manifest, with every column, checksum and date range, is committed as [`docs/data/kkbox-manifest.json`](docs/data/kkbox-manifest.json). It holds file facts only, no member data.

## Source

The [WSDM Cup 2018 KKBox churn prediction challenge](https://www.kaggle.com/competitions/kkbox-churn-prediction-challenge) on Kaggle. KKBox is a Taiwanese music-streaming service. Member ids (`msno`) arrive already hashed by KKBox.

| File | Holds | Used for |
| --- | --- | --- |
| `members_v3.csv` | City, age (`bd`), gender, registration channel and date | Tenure only; age and gender go to the audit table, never into features (R7) |
| `transactions.csv`, `transactions_v2.csv` | Payments, plan days, list price, amount paid, auto-renew, expiry, cancellations | Auto-renew, cancellations, price, plan days, tenure |
| `user_logs.csv`, `user_logs_v2.csv` | Daily listening counts and seconds | 30-day listening trend |
| `train.csv`, `train_v2.csv` | `is_churn` for memberships expiring in February and March 2017 | Churn labels |

**Label.** As defined by the competition: a member churns if there is no new valid subscription within 30 days of the membership expiring.

**Real files, as verified** (`offers data verify`, 2026-11-17):

| File | Rows | Size | sha256 | Date ranges |
| --- | --- | --- | --- | --- |
| `members_v3.csv` | 6,769,473 | 427.9 MB | `5bacf7d28ee97b7f…` | `registration_init_time` 2004-03-26 to 2017-04-29 |
| `train.csv` | 992,931 | 46.7 MB | `14140a13139b9952…` | none |
| `train_v2.csv` | 970,960 | 45.6 MB | `1f7590a3467174f5…` | none |
| `transactions.csv` | 21,547,746 | 1,729.3 MB | `537c269140742fc7…` | `membership_expire_date` 1970-01-01 to 2017-03-31; `transaction_date` 2015-01-01 to 2017-02-28 |
| `transactions_v2.csv` | 1,431,009 | 115.4 MB | `1d3015e32ed1661e…` | `membership_expire_date` 2016-04-19 to 2036-10-15; `transaction_date` 2015-01-01 to 2017-03-31 |
| `user_logs.csv` | 392,106,543 | 30,514.1 MB | `32d83038c86f7974…` | `date` 2015-01-01 to 2017-02-28 |
| `user_logs_v2.csv` | 18,396,362 | 1,431.5 MB | `0188c4111de1c4fa…` | `date` 2017-03-01 to 2017-03-31 |

**What the real dates say.**

- `transactions.csv` and `user_logs.csv` end on 2017-02-28 and `user_logs_v2.csv` covers March 2017, as the spec assumed.
- `transactions_v2.csv` is **not** March-only: 361,187 of its rows were booked before March (back to 2015-01-01), and some memberships expire as late as 2036-10-15. No row appears in both transaction files, so reading both never counts a payment twice.
- `transactions.csv` holds `membership_expire_date` values as early as 1970-01-01 (placeholder dates) and 3,339 exact duplicate rows.
- None of this changes the method: every feature reads only events strictly before its cohort's as-of date, and the leakage check refuses any feature that did not (N1.4).

## How it is used

- **As-of rule.** Features for a cohort use only events strictly before the first day of its label month (2017-02-01 for February, 2017-03-01 for March). A leakage test enforces it (N1.4).
- **Cohorts.** The March cohort is split by a salted hash of the member id: 10% holdout, 30% bandit training, 20% logging pilot, 40% evaluation (D-8).
- **Offer responses are simulated.** The data holds no offers. Every outcome that depends on an offer comes from the pre-registered simulator and is labelled "simulated" (NFR1).

## What is never committed or published

- Raw files and any member-level table (features, scores, decisions, outcomes) live under `data/`, `.offers/` and `runs/`, which git ignores. The data scan in CI refuses KKBox file names, data-file types, archives and anything that looks like a KKBox member id.
- Published outputs (report, `summary.json`, PR/FAQ, demo cube) hold aggregates only, and pass the publish scan.

## Licence

The owner accepted the [competition rules](https://www.kaggle.com/competitions/kkbox-churn-prediction-challenge/rules) on Kaggle before downloading. The terms that govern this project, quoted from the rules (section 7, "Competition Data", and section 8, "Submission Code Requirements"):

> A. Data Access and Use. Unless otherwise restricted under the Competition Specific Rules above, after your acceptance of these Rules, you may access and use the Competition Data only for the purposes of the Competition, participation on Kaggle Website forums, academic research and education.

> B. Data Security. [...] You agree not to transmit, duplicate, publish, redistribute or otherwise provide or make available the Data to any party not participating in the Competition.

> B. Public Code Sharing. You are permitted to publicly share source or executable code developed in connection with or based upon the Competition Data, or otherwise relevant to the Competition, provided that such public sharing does not violate the intellectual property rights of any third party. By so sharing, you are deemed to have licensed the shared code under any of the eligible Open Source licenses listed below.

MIT, this project's licence, is one of those Open Source Initiative-approved licences. One more clause is worth knowing: the competition-specific "External Data Use" rule says it "supersedes General Rules Section 7.B". Its text is about using data other than the Competition Data, so it reads as a drafting slip for 7.C, and this project treats 7.B as binding.

**Ruling (OWNER D-46).** Respectful Offers is an educational, non-commercial research project. Raw KKBox data and member-level rows are never redistributed: not in git, not in releases, not in the demo. The code is published under MIT, as the code-sharing rule allows. Only aggregate results are published (the report, `summary.json`, the PR/FAQ) and the aggregates-only demo cube (every cell 20 or more members, counts rounded to fives, means to three significant figures), each citing the WSDM Cup 2018 KKBox challenge. Anyone who wants to reproduce the results downloads the data themselves after accepting the rules; `offers data download` does exactly that.

**This is the owner's reading, not an explicit permission.** The rules define neither "the Data" nor derived aggregates, and do not say whether a public, non-commercial portfolio project counts as "education". The riskiest output is the demo cube, because it is derived from member rows (though it holds none). If KKBox or Kaggle objects, the cube and the published results are withdrawn and the project falls back to synthetic members.

The facts under "What the real dates say" are checked by `tests/data/test_real_data.py` against the local files when `OFFERS_REAL_DATA=1`; CI checks the manifest facts on every push.

## Synthetic fixture

`offers data synthetic` writes seeded data in the KKBox file layout (`respectful_offers.data.synthetic`): the same files, columns, YYYYMMDD dates and label definition, with member ids like `S000042`. Its manifest says `"source": "synthetic"`, and it refuses to write over a folder holding real data. Its semantics are simpler than the real data's, although it includes the awkward cases: older 7-, 31- and 90-day plans, discounts and free months, same-day duplicates, cancellations, churners who return after 30 days, members only in the March cohort, members missing from `members_v3.csv`, impossible ages and negative listening seconds. Tests, the golden run and `offers report --example` use it, so the whole pipeline runs without the real files. Its churn rate (about 6–7%) and drivers (auto-renew, listening trend, cancellations, tenure, price) are made up to resemble the real problem. No result computed on it says anything about KKBox members.
