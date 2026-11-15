#!/usr/bin/env python3
"""Regenerate the bundled example run used by `offers report --example` (CLI-03).

Runs the full pipeline on synthetic members (never real data) with the configs in configs/,
a fixed seed and a fixed clock, and writes summary.json and frontier.json into
src/respectful_offers/examples/. Aggregates only: no member appears in either file.

    uv run python scripts/make_example.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMBERS = 8_000


def main() -> int:
    import pandas as pd

    from respectful_offers.churn.model import report, train
    from respectful_offers.data.synthetic import SyntheticSpec, generate
    from respectful_offers.evaluate.pipeline import run_evaluation, write
    from respectful_offers.features.build import build_audit_attributes, build_cohort
    from respectful_offers.schemas import load_simulator_config
    from respectful_offers.schemas.config import load_run_config
    from respectful_offers.sim.prereg import sha256

    work = Path(tempfile.mkdtemp(prefix="offers-example-"))
    try:
        raw = work / "raw"
        raw.mkdir()
        generate(raw, SyntheticSpec(n_members=MEMBERS, seed=20261121))
        feb, mar = build_cohort(raw, "feb").features, build_cohort(raw, "mar").features
        attrs = build_audit_attributes(raw, pd.Series(sorted(set(mar["msno"]))))
        model, _ = train(feb, seed=1)
        rep = report(model, feb, mar, seed=1)
        scores = pd.DataFrame({"msno": mar["msno"].astype(str), "churn_risk": model.risk(mar)})
        sim_path, cfg_path = ROOT / "configs" / "simulator.yaml", ROOT / "configs" / "run.yaml"
        ev = run_evaluation(
            scores,
            mar,
            attrs,
            rep,
            load_simulator_config(sim_path),
            load_run_config(cfg_path),
            run_id="example",
            git_sha="example",
            config_hash=sha256(cfg_path)[:16],
            simulator_hash=sha256(sim_path)[:16],
            prereg_status="preregistered",
        )
        out = ROOT / "src" / "respectful_offers" / "examples"
        write(ev, out, stable=True)
        audit = {"clean": ev.audit_clean, "rollouts": list(ev.audit)}
        (out / "audit.json").write_text(
            json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(
            f"wrote {out}/summary.json, frontier.json, audit.json (audit clean: {ev.audit_clean})"
        )
        return 0 if ev.audit_clean else 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
