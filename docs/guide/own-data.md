# Using your own data

You need one table of members (CSV or Parquet), with one row per member and cohort:

| Column | Meaning |
| --- | --- |
| `msno` | your member id (any string) |
| `cohort` | `feb` (trains the churn model) or `mar` (the cohort the policies are evaluated on) |
| `as_of` | the cohort's date, `YYYY-MM-DD` |
| `tenure_days`, `cancels_90d` | whole numbers, 0 or more |
| `auto_renew`, `churn_label` | `true`/`false` (or 1/0) |
| `listening_trend_30d` | engagement trend, −1 or more |
| `price_30d` | the member's monthly price, 0 or more |
| `plan_days` | days in the plan, 1 or more |

Each cohort needs both churners and renewers. Age band and gender, if you have them, go in a
separate `audit.csv` (`msno,age_band,gender`): they are audited for disparity and **never**
used to decide.

```bash
offers init my-project && cd my-project      # templates and a README; never overwrites
offers features --from-table features.csv --audit-table audit.csv   # names any bad row and column
# edit simulator.yaml (see writing-a-simulator.md), then freeze it for real data:
offers prereg --scope real
offers run --all --from-table features.csv --audit-table audit.csv
```

The report lands in `report/index.html`, stamped with your data source. Nothing leaves your
machine.
