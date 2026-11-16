# Privacy

- **No telemetry.** Respectful Offers sends nothing anywhere. The only network call it ever
  makes is the KKBox download you start yourself (`offers data download`).
- **Your data stays local.** Raw files, features, scores and run folders live in your project
  folder; `data/`, `.offers/` and `runs/` are git-ignored.
- **Credentials are never printed or stored** by the tool; `offers doctor` only says whether
  they are present.
- **What is safe to share:** the report and `summary.json` hold aggregates only. The demo cube
  holds counts, means and spreads for groups of at least 20 members, never a member's row.
