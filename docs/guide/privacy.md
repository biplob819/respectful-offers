# Privacy

- **No telemetry.** Respectful Offers sends nothing anywhere. The only network call it ever
  makes is the KKBox download you start yourself (`offers data download`).
- **Your data stays local.** Raw files, features, scores and run folders live in your project
  folder; `data/`, `.offers/` and `runs/` are git-ignored.
- **Credentials are never printed or stored** by the tool; `offers doctor` only says whether
  they are present.
- **What is safe to share:** the report and `summary.json` hold aggregates only. The demo cube
  holds counts (rounded to fives), means and spreads for groups of at least 20 members, and
  price levels that each stand for at least five members, never a member's row.
- **The hosted demo** turns off Streamlit's usage statistics and makes no calls of its own;
  only a hash of each passkey is stored, in the app's secrets.
