# Contributing

Thank you for helping. Respectful Offers is built node by node with a gated harness: every
change lands with tests that prove it, and a skeptical review tries to break it first.

## Set up

```bash
git clone https://github.com/biplob819/respectful-offers && cd respectful-offers
uv sync --all-extras
uv run pytest -q
```

Python 3.11 to 3.13 on Linux, macOS or Windows. No KKBox data is needed: the tests run on
synthetic members (`offers data synthetic`).

## Making a change

1. Open an issue first for anything larger than a typo, so we can agree on the approach.
2. Write the test that fails without your change, then the change.
3. Run the same checks CI runs: `uv run ruff check .`, `uv run ruff format --check .`,
   `uv run pyright`, `uv run pytest -q`.
4. Never commit raw data, member-level files or credentials. `scripts/secret_scan.py` and
   `scripts/data_scan.py` run in CI and will refuse them.
5. If your change alters a cached stage's behaviour, bump its `code_version` and run
   `uv run python -m respectful_offers.runtime.versions --update`.
6. If it changes a design decision, add a row to `docs/decisions.md` saying what and why.

## The rules the code must keep

The respect rules (R1–R8), the holdout, the "Simulated" labelling and the pre-registration
of the simulator are the point of the project. A change that weakens any of them needs a
decision row and a very good reason.

## Versioning

Semantic versioning: patch releases fix bugs, minor releases add features without breaking
the CLI, the configs or `summary.json`; a major release may break them, and says how to
migrate. `summary.json` carries its own `schema_version`.
