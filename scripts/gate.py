#!/usr/bin/env python3
"""Release gates over a metrics-1 file, in EvalKit's gates format (E4.1, OWNER D-50, D-52).

A stand-in for `evalkit gate` until EvalKit v0.3.0 ships it: it implements the subset of
EvalKit's B5.3 gates format that `configs/gates.yaml` uses, with EvalKit's exit codes.

    uv run python scripts/gate.py results/kkbox/metrics.json --out results/kkbox/gate.json
    uv run python scripts/gate.py results/kkbox/metrics.json --check results/kkbox/gate.json

Exit 0: every `fail` gate holds (warns allowed). 1: a `fail` gate fails. 2: bad input, an
unknown key or op, a gate that matches no metric, or a bound on a metric with no interval.
`--out` is written on every exit path, including 2. No network, no keys, no model calls.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import yaml

from respectful_offers.metrics1 import MetricsError, validate_metrics1

ROOT = Path(__file__).resolve().parents[1]
GATES = ROOT / "configs" / "gates.yaml"
GATE_KEYS = {"metric", "labels", "bound", "op", "value", "severity", "disparity"}
OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, "==": lambda a, b: a == b}
EXIT_OK, EXIT_FAIL, EXIT_ERROR = 0, 1, 2


class GateError(ValueError):
    """Bad input: exit 2."""


def _matches(metric: dict[str, Any], want: dict[str, Any]) -> bool:
    labels = metric.get("labels", {})
    for k, v in want.items():
        if k not in labels:
            return False
        if v == "*":
            continue
        got = labels[k]
        if type(got) is not type(v) or got != v:  # True never matches 1, "1" never matches 1
            return False
    return True


def _num(v: Any, where: str) -> float | int | bool:
    if isinstance(v, float) and not math.isfinite(v):
        raise GateError(f"{where}: threshold {v!r} is not finite")
    if isinstance(v, (bool, int, float)):
        return v
    raise GateError(f"{where}: threshold {v!r} is not a number or boolean")


def _compare(op: str, observed: Any, threshold: Any, where: str) -> bool:
    if isinstance(observed, bool) != isinstance(threshold, bool):
        raise GateError(f"{where}: compares a boolean with a number")
    if isinstance(observed, bool) and op != "==":
        raise GateError(f"{where}: booleans only take op '=='")
    return OPS[op](observed, threshold)


def _check_gate(i: int, g: Any) -> dict[str, Any]:
    where = f"gates[{i}]"
    if not isinstance(g, dict):
        raise GateError(f"{where}: a gate is a mapping")
    unknown = sorted(set(g) - GATE_KEYS)
    if unknown:
        raise GateError(f"{where}: unknown keys {unknown}")
    for k in ("metric", "op", "value"):
        if k not in g:
            raise GateError(f"{where}: missing {k!r}")
    if not isinstance(g["metric"], str) or not g["metric"]:
        raise GateError(f"{where}: metric must be a name")
    if not isinstance(g["op"], str) or g["op"] not in OPS:
        raise GateError(f"{where}: unknown op {g['op']!r} (use >=, <= or ==)")
    if "disparity" in g and not (isinstance(g["disparity"], str) and g["disparity"]):
        raise GateError(f"{where}: disparity must name a label")
    if not isinstance(g.get("bound", "point"), str) or g.get("bound", "point") not in (
        "point",
        "lower",
        "upper",
    ):
        raise GateError(f"{where}: bound must be point, lower or upper")
    if not isinstance(g.get("severity", "fail"), str) or g.get("severity", "fail") not in (
        "fail",
        "warn",
    ):
        raise GateError(f"{where}: severity must be fail or warn")
    if not isinstance(g.get("labels", {}), dict):
        raise GateError(f"{where}: labels must be a mapping")
    _num(g["value"], where)
    return g


def _rows_for(i: int, g: dict[str, Any], metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    where = f"gates[{i}] {g['metric']}"
    want = g.get("labels", {})
    bound = g.get("bound", "point")
    hits = [m for m in metrics if m["name"] == g["metric"] and _matches(m, want)]
    attr = g.get("disparity")
    if attr is not None:
        hits = [m for m in hits if attr in m.get("labels", {})]
    if not hits:
        raise GateError(f"{where}: matches no metric (a gate never passes silently)")
    base = {
        "metric": g["metric"],
        "bound": bound,
        "op": g["op"],
        "threshold": g["value"],
        "severity": g.get("severity", "fail"),
    }
    rows = []
    if attr is not None:
        if bound != "point":
            raise GateError(f"{where}: a disparity bound needs group n, which this file lacks")
        groups: dict[str, list[dict[str, Any]]] = {}
        for m in hits:
            rest = {k: v for k, v in m.get("labels", {}).items() if k != attr}
            groups.setdefault(json.dumps(rest, sort_keys=True), []).append(m)
        for key, ms in sorted(groups.items()):
            if len(ms) < 2:
                raise GateError(f"{where}: disparity over {attr} needs two or more groups")
            vals = [m["value"] for m in ms]
            if any(isinstance(v, bool) for v in vals):
                raise GateError(f"{where}: disparity needs numeric values")
            gap = round(max(vals) - min(vals), 12)
            ok = _compare(g["op"], gap, g["value"], where)
            rows.append(
                {
                    **base,
                    "labels": {**json.loads(key), "disparity": attr},
                    "observed": gap,
                    "ok": ok,
                }
            )
        return rows
    for m in hits:
        if bound == "point":
            observed = m["value"]
        elif "ci_low" not in m:
            raise GateError(f"{where}: bound {bound} on a metric with no interval")
        else:
            observed = m["ci_low"] if bound == "lower" else m["ci_high"]
        ok = _compare(g["op"], observed, g["value"], where)
        rows.append({**base, "labels": m.get("labels", {}), "observed": observed, "ok": ok})
    return rows


def evaluate(doc: Any, config: Any) -> tuple[int, list[dict[str, Any]]]:
    """Exit code and one row per gate × matched metric (or group set for a disparity)."""
    try:
        validate_metrics1(doc)
    except MetricsError as exc:
        raise GateError(f"metrics file: {exc}") from exc
    if not isinstance(config, dict) or not isinstance(config.get("gates"), list):
        raise GateError("gates file needs a list under 'gates'")
    unknown = sorted(set(config) - {"gates", "heldout_splits"})
    if unknown:
        raise GateError(f"gates file: unknown keys {unknown}")
    gates = [_check_gate(i, g) for i, g in enumerate(config["gates"])]
    rows = [r for i, g in enumerate(gates) for r in _rows_for(i, g, doc.get("metrics", []))]
    for r in rows:
        r["status"] = "pass" if r.pop("ok") else r["severity"]
        r["labels"] = _short(r["labels"])
    failed = any(r["status"] == "fail" for r in rows)
    return (EXIT_FAIL if failed else EXIT_OK), rows


def _short(labels: dict[str, Any]) -> dict[str, Any]:
    """Gate output never echoes a free-text label value longer than 64 characters (GAT-04)."""
    return {k: (v[:64] if isinstance(v, str) else v) for k, v in labels.items()}


def _label_text(labels: dict[str, Any]) -> str:
    return ",".join(f"{k}={str(v)[:64]}" for k, v in sorted(labels.items())) or "-"


def run(metrics_path: Path, gates_path: Path) -> dict[str, Any]:
    """The gate result as written to gate.json, on every path."""
    simulated = None
    try:
        try:
            doc = json.loads(metrics_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GateError(f"cannot read {metrics_path.name}: {exc}") from exc
        if isinstance(doc, dict):
            simulated = doc.get("simulated")
        try:
            config = yaml.safe_load(gates_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise GateError(f"cannot read {gates_path.name}: {exc}") from exc
        code, rows = evaluate(doc, config)
    except (GateError, TypeError, ValueError, KeyError) as exc:
        return {
            "simulated": simulated,
            "exit": EXIT_ERROR,
            "verdict": "error",
            "error": str(exc),
            "rows": [],
        }
    verdict = "fail" if code == EXIT_FAIL else "pass"
    return {
        "simulated": simulated,
        "exit": code,
        "verdict": verdict,
        "rows": rows,
        "warnings": sum(r["status"] == "warn" for r in rows),
    }


def render(result: dict[str, Any]) -> str:
    lines = [f"simulated: {json.dumps(result['simulated'])}"]
    for r in result["rows"]:
        lines.append(
            f"{r['status'].upper():<5} {r['metric']} [{_label_text(r['labels'])}] "
            f"{r['bound']} {r['op']} {r['threshold']} observed {r['observed']} ({r['severity']})"
        )
    if result["verdict"] == "error":
        lines.append(f"error: {result['error']}")
    lines.append(f"verdict: {result['verdict']} (exit {result['exit']})")
    return "\n".join(lines)


def dumps(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=1, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("metrics", type=Path)
    ap.add_argument("--config", type=Path, default=GATES)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", type=Path, help="write gate.json here, on every exit path")
    ap.add_argument("--check", type=Path, help="exit 1 if this committed gate.json is stale")
    args = ap.parse_args(argv)
    result = run(args.metrics, args.config)
    text = dumps(result)
    if args.out:
        args.out.write_text(text, encoding="utf-8", newline="\n")
    print(text if args.json else render(result), end="" if args.json else "\n")
    if args.check:
        current = args.check.is_file() and args.check.read_text(encoding="utf-8") == text
        if not current:
            print(f"stale: {args.check}; rerun with --out", file=sys.stderr)
            return max(result["exit"], EXIT_FAIL)
    return result["exit"]


if __name__ == "__main__":
    raise SystemExit(main())
