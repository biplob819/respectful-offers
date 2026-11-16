# B2.4 acceptance criteria

**OSS-01** — `scripts/history_audit.py` scans every blob on every ref under its committed path with the secret and data scans and reports zero hits; it catches a leak committed and later deleted.
**OSS-02** — The decision log, data card, how-it-was-built note, PRD, lessons and changelog are in the repo and linked from the README.
**OSS-03** — One version (0.1.0) in pyproject, the package and the lock; the `v0.1.0` tag's CI is green; a clean clone at the tag plus the raw files reproduces `results/kkbox/summary.json` in every number (recorded in the run state).
**OSS-04** — Every published artifact (results, site, demo cube, README) passes the data scan, cites the challenge and holds no row files.
**OSS-05** — Distribution `respectful-offers`, CLI `offers`, import `respectful_offers`, MIT, Python ≥3.11, project URLs; the release workflow publishes only on a `v*` tag, by trusted publishing (no stored token), after tests and scans.
**OSS-06** — After publishing, the release workflow installs the published version with `uvx` on Linux, macOS and Windows and runs `offers doctor` and `offers report --example`.
**OSS-07** — Guides: quickstart (five minutes), your own data, writing a simulator, the respect rules, reproducing the results.
**OSS-08** — CONTRIBUTING (with semantic versioning), SECURITY (private reporting, no email), CODE_OF_CONDUCT, LICENSE, issue and PR templates.
**OSS-09** — The privacy statement says no telemetry and names the one network call; no network client is imported outside the download module; the demo turns off usage statistics.
