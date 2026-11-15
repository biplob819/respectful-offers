# W0.1 acceptance criteria

One block per capability. Each criterion is checked by a named test.

**HAR-01 — uv project and package skeleton**
- `uv run offers --version` prints `offers 0.0.1`; `pyproject.toml` names `respectful-offers`, requires Python ≥3.11 (OWNER D-21), MIT licence, the `offers` console script.
- `.gitattributes` forces LF; `.pre-commit-config.yaml` runs ruff and both scans.

**HAR-02 — CI**
- `ci.yml` runs on push and pull request with ruff, pyright, pytest, both scans, eligibility and `uv build`, on ubuntu, macOS and Windows with Python 3.11, 3.12 and 3.13 (OWNER D-21), and declares least-privilege `permissions`.

**HAR-03 — graph eligibility**
- Fails on a cycle, an unknown dependency, an unparseable `depends_on`, a catalog row naming an unknown node, and a node building or starting ahead of a non-green dependency. Passes on the live graph. `--self-test` passes.

**HAR-04 — node start**
- Refuses when the node is unknown, has no rows, a dependency is not green, a spec file is missing, or `criteria.md` misses a capability. Writes `.base` only with `--mark-building`. `--self-test` passes.

**HAR-05 — node converge**
- Runs the 12 gates of Tech Spec §11.6 in order (gate 8 `respect-ope`, gate 9 including the data scan), reports every one, exits 1 on any FAIL, logs under `.harness/<node>/`. `--self-test` shows every gate failing on planted input, golden SKIP with no tests, and the respect proof dimension required.

**HAR-06 — records**
- `graph.md` parses to 20 nodes with no cycle; `catalog.tsv` to 116 rows, each naming a node; every node has rows; the catalog round-trips byte for byte.
- `decisions.md` holds D-1 to D-21 including OWNER D-1, D-15, D-17, D-18, D-19, D-21; `lessons.md` and `changelog.md` exist; `status.py` prints the graph table and a node table.
- `.gitignore` keeps `Portfolio notes.md`, `data/`, `.offers/`, `runs/` and `.env` out of git.

**HAR-07 — secret, raw-data and publish scans**
- The secret scan detects Anthropic, OpenAI, AWS, GitHub, PyPI and Kaggle keys and private keys, and honours its allow marker.
- The data scan refuses KKBox raw file names, member-level file types, files over 5 MB and KKBox-shaped member ids, while letting synthetic ids and hex hashes through. The live repo is clean on both.
