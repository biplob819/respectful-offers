# Security

Please report a vulnerability privately through GitHub: **Security → Report a vulnerability**
on this repository (private vulnerability reporting). Do not open a public issue for it.

You can expect an acknowledgement within a week. Supported version: the latest release.

What counts: anything that could leak member data, credentials (for example the Kaggle token)
or files outside the project folder; code execution from a crafted config, table, cube or run
folder; or a way to make the auditor report zero violations for a policy that broke a rule.

Respectful Offers makes no network calls except the KKBox download you run yourself
(`offers data download`), and it never stores or prints your Kaggle credentials.
