# D3.3 acceptance criteria

**PAG-01** — `docs/site/case-study.html` states the summary's numbers (members, cost per extra member kept, violations, AUC, the claim per variant), says simulated, cites the challenge, and `scripts/project_page.py --check` fails on drift; re-rendering from a summary with every field scaled changes every number except a short list of template constants.
**PAG-02** — `docs/site/video-script.md`: timed beats from 0:00, narration that fits in 90 seconds at 2.5 words per second, results labelled **Simulated**, numbers from the summary.
**PAG-03** — Every link on the case study points at a published place (a file built into the Pages site or committed in the repo); with `OFFERS_CHECK_LINKS=1` every link answers 200 live (PyPI through its JSON API).
