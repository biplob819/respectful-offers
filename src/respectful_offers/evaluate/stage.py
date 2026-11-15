"""The evaluate stage (A2.7): features + churn scores → `summary.json` and `frontier.json`.

Its identity is the two input artifacts, the full run and simulator configurations, the
pre-registration status and the run id (the summary names its run), plus the context's
config hash, simulator hash and seed. The summary records the git commit of the run that
produced it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from respectful_offers.evaluate.pipeline import run_evaluation, write
from respectful_offers.runtime.stage import RunContext, Stage
from respectful_offers.schemas.config import RunConfig
from respectful_offers.schemas.simulator import SimulatorConfig
from respectful_offers.schemas.summary import ChurnReport


class EvaluateStage(Stage):
    name = "evaluate"
    code_version = "4"

    def __init__(
        self,
        run_config: RunConfig,
        simulator: SimulatorConfig,
        prereg_status: str,
        run_id: str,
        git_sha: str = "unknown",
        stable_clock: bool = False,
        data_source: str = "synthetic",
    ) -> None:
        self.run_config = json.loads(run_config.model_dump_json())
        self.simulator = json.loads(simulator.model_dump_json())
        self.prereg_status = prereg_status
        self.run_id = run_id
        self.git_sha = git_sha  # in the cache key: a cached summary never carries a stale commit
        self.stable_clock = stable_clock
        self.data_source = data_source
        self._cfg = run_config
        self._sim = simulator

    def params(self) -> dict[str, Any]:
        return {k: v for k, v in sorted(vars(self).items()) if not k.startswith("_")}

    def run(self, inputs: Mapping[str, Path], out: Path, ctx: RunContext) -> None:
        feats, churn = inputs["features"], inputs["churn"]
        features = pd.read_parquet(feats / "features_mar.parquet")
        audit_attrs = pd.read_parquet(feats / "audit_attributes.parquet")
        scores = pd.read_parquet(churn / "scores_mar.parquet")[["msno", "churn_risk"]]
        report = ChurnReport.model_validate_json((churn / "report.json").read_text("utf-8"))
        evaluation = run_evaluation(
            scores,
            features,
            audit_attrs,
            report,
            self._sim,
            self._cfg,
            run_id=self.run_id,
            git_sha=self.git_sha,
            config_hash=ctx.config_hash,
            simulator_hash=ctx.simulator_hash or "none",
            prereg_status=self.prereg_status,
            data_source=self.data_source,
        )
        write(evaluation, out, stable=self.stable_clock)
        audit = {"clean": evaluation.audit_clean, "rollouts": list(evaluation.audit)}
        (out / "audit.json").write_text(
            json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
