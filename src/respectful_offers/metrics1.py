"""EvalKit's metrics-summary format `metrics-1` (E4.1, OWNER D-50).

`to_metrics1(summary)` writes a run's `summary.json` in the format frozen in EvalKit's
`specs/B5.3-gates/spec.md` §1 (commit 7986e5c), so `evalkit gate` (EvalKit v0.3.0) can gate a
release on it. `validate_metrics1(doc)` applies every rule of that format. Intervals are the
run's own block-bootstrap intervals, copied exactly and never recomputed (EvalKit D-63).
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterator
from typing import Any

from respectful_offers.schemas.summary import Interval, RunSummary

SCHEMA_VERSION = "metrics-1"
PROJECT = "respectful-offers"
CI_METHOD = "block-bootstrap percentile 95% (D-16)"
CI_METHOD_PAIRED = "paired block-bootstrap percentile 95%; Holm per metric and variant (D-16)"

TOP_REQUIRED = ("schema_version", "project", "run_id", "created_at")
TOP_OPTIONAL = ("simulated", "provenance", "metrics")
PROVENANCE_KEYS = ("code_version", "snapshot", "config_hash", "evalkit")
METRIC_KEYS = ("name", "unit", "value", "n", "k", "ci_low", "ci_high", "ci_method", "labels")
NAME_RE = re.compile(r"^[a-z][a-z0-9_.]*$")
UNIT_WORDS = ("count", "rate", "bool", "ratio", "ms", "s")
UNIT_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]*$")
ISO_ZONED_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d(:\d\d(\.\d+)?)?(Z|[+-]\d\d:\d\d)$")
MSNO_RE = re.compile(r"[A-Za-z0-9+/]{43}=")  # a KKBox member id: 44 base64 characters
ID_KEY_RE = re.compile(r"(^|_)(id|ids|msno|member|case)(_|$)", re.IGNORECASE)

# units of each comparison metric (Tech Spec §7.3)
COMPARISON_UNITS = {
    "incremental_retained_per_1000": "ratio",
    "incremental_retained_per_1000_ntd": "ratio",
    "ltv_proxy_per_member": "NTD",
}


class MetricsError(ValueError):
    """A metrics-1 document breaks a rule of the format."""


def _metric(
    name: str,
    unit: str,
    value: Any,
    labels: dict[str, Any] | None = None,
    *,
    iv: Interval | None = None,
    n: int | None = None,
    method: str = CI_METHOD,
) -> dict[str, Any]:
    m: dict[str, Any] = {"name": name, "unit": unit, "value": value}
    if iv is not None:
        if not iv.lo <= iv.point <= iv.hi:
            raise MetricsError(
                f"{name} {labels}: point {iv.point} lies outside its own interval "
                f"[{iv.lo}, {iv.hi}]; refusing to export it"
            )
        m["value"], m["ci_low"], m["ci_high"], m["ci_method"] = iv.point, iv.lo, iv.hi, method
    if n is not None:
        m["n"] = n
    if labels:
        m["labels"] = dict(labels)
    return m


def _metrics(s: RunSummary) -> Iterator[dict[str, Any]]:
    for p in s.policies:
        lab = {"policy": p.policy, "variant": p.variant}
        yield _metric("retained_per_1000", "ratio", None, lab, iv=p.retained_per_1000)
        yield _metric(
            "incremental_retained_per_1000", "ratio", None, lab, iv=p.incremental_retained_per_1000
        )
        if p.retained_per_1000_at_risk is not None:
            yield _metric(
                "retained_per_1000_at_risk", "ratio", None, lab, iv=p.retained_per_1000_at_risk
            )
        yield _metric("offers_per_member_month", "ratio", None, lab, iv=p.offers_per_member_month)
        yield _metric("ltv_proxy_per_member", "NTD", None, lab, iv=p.ltv_proxy_per_member)
        if p.cost_per_incremental_retained is not None:
            yield _metric(
                "cost_per_incremental_retained",
                "NTD",
                None,
                lab,
                iv=p.cost_per_incremental_retained,
            )
        yield _metric("discount_cost_total", "NTD", p.discount_cost_total, lab)
        yield _metric("no_offer_share", "rate", p.no_offer_share, lab, n=p.n_members)
        if p.exploration_rate is not None:
            yield _metric("exploration_rate", "rate", p.exploration_rate, lab, n=p.n_members)
        yield _metric("max_offers_in_a_month", "count", p.max_offers_in_a_month, lab)
        for rule, count in sorted(p.violations.items()):
            yield _metric(
                "violations", "count", count, {"rule": rule, **lab, "respectful": p.respectful}
            )
        for sp in p.spend:
            plab = {**lab, "period": sp.period}
            yield _metric("spend.budget", "NTD", sp.budget, plab)
            yield _metric("spend.face_value_committed", "NTD", sp.face_value_committed, plab)
            yield _metric("spend.realised_cost", "NTD", sp.realised_cost, plab)
    for c in s.comparisons:
        lab = {"a": c.a, "b": c.b, "variant": c.variant}
        unit = COMPARISON_UNITS.get(c.metric)
        if unit is None:
            raise MetricsError(f"no unit known for comparison metric {c.metric!r}")
        yield _metric(f"diff.{c.metric}", unit, None, lab, iv=c.diff, method=CI_METHOD_PAIRED)
        yield _metric(f"separated.{c.metric}", "bool", c.separated, lab)
        yield _metric(f"p_value.{c.metric}", "rate", c.p_value, lab)
    for o in s.ope:
        lab = {"policy": o.policy, "variant": o.variant, "estimator": o.estimator}
        yield _metric("ope.value", "NTD", None, lab, iv=o.value)
        yield _metric("ope.oracle", "NTD", o.oracle, lab)
        yield _metric("ope.covered", "bool", o.covered, lab)
        yield _metric("ope.effective_sample_size", "ratio", o.effective_sample_size, lab)
    for variant, iv in sorted(s.holdout_check.items()):
        yield _metric("holdout_check", "ratio", None, {"variant": variant}, iv=iv)
    ch = s.churn
    yield _metric("churn.auc", "ratio", None, iv=ch.auc)
    yield _metric("churn.baseline_auc", "ratio", None, iv=ch.baseline_auc)
    yield _metric("churn.brier", "ratio", None, iv=ch.brier)
    yield _metric("churn.ece", "ratio", ch.ece)
    for i, (predicted, observed, count) in enumerate(ch.reliability):
        yield _metric("churn.reliability.predicted", "rate", predicted, {"bin": i}, n=count)
        yield _metric("churn.reliability.observed", "rate", observed, {"bin": i}, n=count)
    # disparity is computed on the central variant, or the first one without it (A2.7)
    dvar = "central" if "central" in s.variants else s.variants[0]
    for key, groups in sorted(s.disparity.items()):
        parts = key.split(".")
        if len(parts) != 3:
            raise MetricsError(
                f"disparity key {key!r} names no policy and metric; metrics-1 needs both labels"
            )
        policy, metric, attr = parts
        unit = "rate" if metric == "offer_rate" else "ratio"
        for group, iv in sorted(groups.items()):
            lab = {"policy": policy, "variant": dvar, attr: group}
            yield _metric(f"group.{metric}", unit, None, lab, iv=iv)


def to_metrics1(s: RunSummary) -> dict[str, Any]:
    """The run's summary as a metrics-1 document; a pure function of the summary."""
    stamp = s.finished_at or s.started_at
    created = stamp.isoformat().replace("+00:00", "Z")
    doc = {
        "schema_version": SCHEMA_VERSION,
        "project": PROJECT,
        "run_id": s.run_id,
        "created_at": created,
        "simulated": True,
        "provenance": {
            "code_version": s.git_sha,
            "snapshot": f"simulator:{s.simulator_hash}",
            "config_hash": s.config_hash,
            "evalkit": None,
        },
        "metrics": list(_metrics(s)),
    }
    validate_metrics1(doc)
    return doc


def dumps(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return (_is_int(v) or isinstance(v, float)) and not (
        isinstance(v, float) and not math.isfinite(v)
    )


def _check_value(where: str, unit: str, v: Any) -> None:
    if unit == "count":
        ok = _is_int(v) and v >= 0
    elif unit == "rate":
        ok = _is_num(v) and 0 <= v <= 1
    elif unit == "bool":
        ok = isinstance(v, bool)
    else:
        ok = _is_num(v)
    if not ok:
        raise MetricsError(f"{where}: value {v!r} does not fit unit {unit!r}")


def _no_member_values(obj: Any, path: str = "$") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            _no_member_values(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _no_member_values(v, f"{path}[{i}]")
    elif isinstance(obj, str) and MSNO_RE.search(obj):
        raise MetricsError(f"{path}: a member-id-shaped value; metrics-1 carries no member ids")


def validate_metrics1(doc: Any) -> None:
    """Raise MetricsError on the first rule of EvalKit's metrics-1 format the document breaks."""
    if not isinstance(doc, dict):
        raise MetricsError("a metrics-1 document is a JSON object")
    missing = [k for k in TOP_REQUIRED if k not in doc]
    if missing:
        raise MetricsError(f"missing top-level keys {missing}")
    unknown = sorted(set(doc) - set(TOP_REQUIRED) - set(TOP_OPTIONAL))
    if unknown:
        raise MetricsError(f"unknown top-level keys {unknown}")
    if doc["schema_version"] != SCHEMA_VERSION:
        raise MetricsError(f"schema_version must be {SCHEMA_VERSION!r}")
    for k in ("project", "run_id"):
        if not isinstance(doc[k], str) or not doc[k]:
            raise MetricsError(f"{k} must be a non-empty string")
    if not isinstance(doc["created_at"], str) or not ISO_ZONED_RE.match(doc["created_at"]):
        raise MetricsError("created_at must be ISO 8601 with a zone")
    if not isinstance(doc.get("simulated", False), bool):
        raise MetricsError("simulated must be true or false")
    prov = doc.get("provenance", {})
    if not isinstance(prov, dict):
        raise MetricsError("provenance must be an object")
    bad = sorted(set(prov) - set(PROVENANCE_KEYS))
    if bad:
        raise MetricsError(f"unknown provenance keys {bad}")
    if any(v is not None and not isinstance(v, str) for v in prov.values()):
        raise MetricsError("provenance values are strings or null")
    metrics = doc.get("metrics", [])
    if not isinstance(metrics, list):
        raise MetricsError("metrics must be a list")
    seen: set[tuple[str, str]] = set()
    for i, m in enumerate(metrics):
        where = f"metrics[{i}]"
        if not isinstance(m, dict):
            raise MetricsError(f"{where}: a metric is an object")
        unknown = sorted(set(m) - set(METRIC_KEYS))
        if unknown:
            raise MetricsError(f"{where}: unknown keys {unknown}")
        for k in ("name", "unit", "value"):
            if k not in m:
                raise MetricsError(f"{where}: missing {k!r}")
        name, unit, value = m["name"], m["unit"], m["value"]
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise MetricsError(f"{where}: name {name!r} must match [a-z][a-z0-9_.]*")
        where = f"{where} {name}"
        if not isinstance(unit, str) or not (unit in UNIT_WORDS or UNIT_CODE_RE.match(unit)):
            raise MetricsError(f"{where}: unknown unit {unit!r}")
        _check_value(where, unit, value)
        if "n" in m and not (_is_int(m["n"]) and m["n"] >= 0):
            raise MetricsError(f"{where}: n must be an integer >= 0")
        if "k" in m:
            if unit != "rate":
                raise MetricsError(f"{where}: k is only allowed on a rate")
            if "n" not in m or not (_is_int(m["k"]) and 0 <= m["k"] <= m["n"]):
                raise MetricsError(f"{where}: k must be an integer with 0 <= k <= n")
        has_lo, has_hi = "ci_low" in m, "ci_high" in m
        if has_lo != has_hi:
            raise MetricsError(f"{where}: ci_low and ci_high come together")
        if has_lo:
            lo, hi = m["ci_low"], m["ci_high"]
            if not (_is_num(lo) and _is_num(hi)) or isinstance(value, bool):
                raise MetricsError(f"{where}: interval bounds must be finite numbers")
            if not lo <= value <= hi:
                raise MetricsError(f"{where}: value {value} outside its interval [{lo}, {hi}]")
            if not isinstance(m.get("ci_method"), str) or not m["ci_method"]:
                raise MetricsError(f"{where}: an interval needs ci_method")
        elif "ci_method" in m:
            raise MetricsError(f"{where}: ci_method without an interval")
        labels = m.get("labels", {})
        if not isinstance(labels, dict):
            raise MetricsError(f"{where}: labels must be an object")
        for lk, lv in labels.items():
            if isinstance(lk, str) and ID_KEY_RE.search(lk):
                raise MetricsError(f"{where}: label {lk!r} looks like an id; no case or member ids")
            if not isinstance(lk, str) or not (isinstance(lv, (str, bool)) or _is_int(lv)):
                raise MetricsError(
                    f"{where}: label {lk!r} must map to a string, integer or boolean"
                )
        key = (name, json.dumps(labels, sort_keys=True))
        if key in seen:
            raise MetricsError(f"{where}: duplicate name and labels {labels}")
        seen.add(key)
    _no_member_values(doc)
