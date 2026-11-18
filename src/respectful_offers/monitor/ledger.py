"""EvalKit's drift monitor and ledgers, driven from this repo (E4.3, EvalKit B5.7 LED-01..04).

EvalKit owns the machinery (OWNER D-50): PSI, the Brier, ECE and reliability-bin changes, the
run history with its alarm bands, and the experiment ledger are all EvalKit's. This module
only hands it this repo's aggregates and the drift config at the OWNER D-56 severities, and
writes what comes back. It needs the `evalkit` extra; without it every call raises
`EvalKitMissing`, which the CLI reports as bad input (exit 2), never as a pass.

The ledgers are EvalKit's hash-chained, append-only files at its default paths
(`docs/measurements/runs.jsonl`, `docs/measurements/experiments.jsonl`). Rows in them are
metrics-1 aggregates only: no member id, no bin under 30 members.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from respectful_offers.metrics1 import dumps, validate_metrics1

RUNS = Path("docs/measurements/runs.jsonl")
EXPERIMENTS = Path("docs/measurements/experiments.jsonl")
DRIFT_CONFIG = Path("configs/drift.yaml")
CALIBRATION_PREFIX = "churn"
FEATURE_PREFIX = "drift"  # `drift.feature_share`, the export's prefix (EvalKit's default)


class EvalKitMissing(RuntimeError):
    """The `evalkit` extra is not installed, so nothing was checked."""


def _evalkit():
    """EvalKit's public drift and ledger calls, imported only when a command needs them."""
    try:
        from evalkit.drift import check, freeze_reference, to_metrics
        from evalkit.ledger import close_experiment, open_experiment, record_run
    except ImportError as exc:
        raise EvalKitMissing(
            "EvalKit is not installed: `uv sync --extra evalkit` (nothing was checked)"
        ) from exc
    return SimpleNamespace(
        check=check,
        freeze_reference=freeze_reference,
        to_metrics=to_metrics,
        record_run=record_run,
        open_experiment=open_experiment,
        close_experiment=close_experiment,
    )


def run_drift(
    reference_metrics: Path,
    period_metrics: Path,
    out_dir: Path,
    *,
    config: Path = DRIFT_CONFIG,
    project: str = "respectful-offers",
) -> dict[str, Any]:
    """Freeze the baseline, check the period against it, write drift-ref, drift-1, metrics-1."""
    drift = _evalkit()
    ref_doc = json.loads(Path(reference_metrics).read_text(encoding="utf-8"))
    period_doc = json.loads(Path(period_metrics).read_text(encoding="utf-8"))
    validate_metrics1(ref_doc)
    validate_metrics1(period_doc)
    ref = drift.freeze_reference(
        reference_metrics,
        calibration_prefix=CALIBRATION_PREFIX,
        created_at=ref_doc["created_at"],  # the baseline's own stamp: the same bytes each time
    )
    report = drift.check(ref, period_metrics, config=config)
    emitted = drift.to_metrics(
        report,
        project=project,
        run_id=f"{period_doc['run_id']}-drift",
        created_at=period_doc["created_at"],
    )
    emitted["provenance"] = period_doc["provenance"]
    validate_metrics1(emitted)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "drift-ref.json": json.dumps(ref, indent=1, sort_keys=True) + "\n",
        "drift.json": json.dumps(_report_json(report), indent=1, sort_keys=True) + "\n",
        "drift.metrics.json": dumps(emitted),
    }
    for name, text in files.items():
        (out_dir / name).write_text(text, encoding="utf-8", newline="\n")
    return {"report": report, "files": sorted(files), "metrics": out_dir / "drift.metrics.json"}


def _report_json(report) -> dict[str, Any]:
    return report.as_dict()


def summarise_drift(report) -> dict[str, Any]:
    """Counts and the flagged rows, for the CLI's one-screen summary."""
    rows = [
        {"check": f"psi {f['feature']}", "level": f["level"], "value": f["psi_shown"]}
        for f in report.features
    ]
    cal = report.calibration or {}
    for d in cal.get("deltas", []):
        rows.append({"check": d["name"], "level": d["status"], "value": d["delta"]})
    return {
        "exit_code": report.exit_code,
        "bins": cal.get("bins_status"),  # `compared` only with equal-width bins declared
        "rows": rows,
    }


def record_run(run: Path, *, ledger: Path = RUNS, gates: Path | None = None, note=None):
    """Append one run to EvalKit's run history and judge it against the runs before it."""
    led = _evalkit()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    return led.record_run(ledger, run, gates=gates, note=note)


def open_challenge(
    *, baseline: Path, challenger: str, ledger: Path = EXPERIMENTS, variant: str = "central"
) -> str:
    """Declare the challenge in EvalKit's experiment ledger before any arm is rolled out."""
    led = _evalkit()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    entry = led.open_experiment(
        ledger,
        hypothesis=(
            f"{challenger} keeps more members per NTD than the champion: its cost per extra "
            "member kept falls (promotion rule: every variant, paired test, Holm, D-58)"
        ),
        change=challenger,
        metric="cost_per_incremental_retained",
        labels={"policy": "bandit", "variant": variant},
        direction="down",
        baseline=baseline,
    )
    return str(entry["id"])


def close_challenge(exp_id: str, *, before: Path, after: Path, ledger: Path = EXPERIMENTS):
    """Record EvalKit's compare of the two arms; the paired test in this repo decides."""
    led = _evalkit()
    return led.close_experiment(ledger, exp_id, before=before, after=after)


def arm_doc(challenge: dict[str, Any], arm: str) -> dict[str, Any]:
    """One arm of a challenge as its own metrics-1 run, labelled like the published bandit."""
    rows = []
    for m in challenge["metrics"]:
        labels = m.get("labels", {})
        if labels.get("arm") != arm:
            continue
        rest = {k: v for k, v in labels.items() if k != "arm"}
        rows.append({**m, "labels": {"policy": "bandit", **rest}})
    doc = {**challenge, "run_id": f"{challenge['run_id']}-{arm}", "metrics": rows}
    validate_metrics1(doc)
    return doc
