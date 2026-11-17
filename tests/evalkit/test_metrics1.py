"""E4.1: summary.json in EvalKit's metrics-1 format (EVK-01, OWNER D-50)."""

import copy
import json
import subprocess
import sys
from typing import Any

import pytest

from harness_lib import ROOT
from respectful_offers.metrics1 import (
    CI_METHOD_PAIRED,
    MetricsError,
    dumps,
    to_metrics1,
    validate_metrics1,
)
from respectful_offers.schemas.summary import RunSummary, load_summary

SUMMARY = ROOT / "results" / "kkbox" / "summary.json"
COMMITTED = ROOT / "results" / "kkbox" / "metrics.json"


@pytest.fixture(scope="module")
def summary() -> RunSummary:
    return load_summary(SUMMARY)


@pytest.fixture(scope="module")
def doc(summary) -> dict:
    return to_metrics1(summary)


def find(doc: dict, name: str, **labels) -> dict:
    hits = [m for m in doc["metrics"] if m["name"] == name and m.get("labels", {}) == labels]
    assert len(hits) == 1, (name, labels, len(hits))
    return hits[0]


def test_the_export_is_valid_metrics1_and_simulated(doc, summary):
    validate_metrics1(doc)
    assert doc["schema_version"] == "metrics-1" and doc["project"] == "respectful-offers"
    assert doc["simulated"] is True and doc["run_id"] == summary.run_id
    assert doc["provenance"] == {
        "code_version": summary.git_sha,
        "snapshot": f"simulator:{summary.simulator_hash}",
        "config_hash": summary.config_hash,
        "evalkit": None,
    }
    assert doc["created_at"].endswith("Z")


def test_every_interval_is_carried_exactly(doc, summary):
    n = 0
    for p in summary.policies:
        lab = {"policy": p.policy, "variant": p.variant}
        for field in (
            "retained_per_1000",
            "incremental_retained_per_1000",
            "offers_per_member_month",
            "ltv_proxy_per_member",
            "cost_per_incremental_retained",
            "retained_per_1000_at_risk",
        ):
            iv = getattr(p, field)
            if iv is None:
                assert not [
                    m for m in doc["metrics"] if m["name"] == field and m.get("labels") == lab
                ]
                continue
            m = find(doc, field, **lab)
            assert (m["value"], m["ci_low"], m["ci_high"]) == (iv.point, iv.lo, iv.hi)
            assert m["unit"] == (
                "NTD"
                if field in ("ltv_proxy_per_member", "cost_per_incremental_retained")
                else "ratio"
            )
            n += 1
    for c in summary.comparisons:
        m = find(doc, f"diff.{c.metric}", a=c.a, b=c.b, variant=c.variant)
        assert (m["value"], m["ci_low"], m["ci_high"]) == (c.diff.point, c.diff.lo, c.diff.hi)
        assert m["ci_method"] == CI_METHOD_PAIRED
        assert find(doc, f"separated.{c.metric}", a=c.a, b=c.b, variant=c.variant)["value"] is (
            c.separated
        )
        n += 1
    for o in summary.ope:
        m = find(doc, "ope.value", policy=o.policy, variant=o.variant, estimator=o.estimator)
        assert (m["value"], m["ci_low"], m["ci_high"]) == (o.value.point, o.value.lo, o.value.hi)
        assert (
            find(doc, "ope.covered", policy=o.policy, variant=o.variant, estimator=o.estimator)[
                "value"
            ]
            is o.covered
        )
    for key, groups in summary.disparity.items():
        policy, metric, attr = key.split(".")
        for g, iv in groups.items():
            m = find(doc, f"group.{metric}", policy=policy, variant="central", **{attr: g})
            assert (m["value"], m["ci_low"], m["ci_high"]) == (iv.point, iv.lo, iv.hi)
    auc = find(doc, "churn.auc")
    assert (auc["value"], auc["ci_low"], auc["ci_high"]) == (
        summary.churn.auc.point,
        summary.churn.auc.lo,
        summary.churn.auc.hi,
    )
    assert n > 100
    assert all("ci_method" in m for m in doc["metrics"] if "ci_low" in m)


def test_violations_are_counts_per_rule_with_the_respectful_flag(doc, summary):
    for p in summary.policies:
        for rule, count in p.violations.items():
            m = find(
                doc,
                "violations",
                rule=rule,
                policy=p.policy,
                variant=p.variant,
                respectful=p.respectful,
            )
            assert m["unit"] == "count" and m["value"] == count and type(m["value"]) is int
    sq = sum(
        m["value"]
        for m in doc["metrics"]
        if m["name"] == "violations" and m["labels"]["policy"] == "status_quo"
    )
    assert sq > 0  # the unconstrained status quo breaks the rules, and the file says so


def test_no_member_id_appears(doc):
    text = dumps(doc)
    assert "msno" not in text
    validate_metrics1(json.loads(text))


GOOD_METRIC = {
    "name": "x",
    "unit": "rate",
    "value": 0.5,
    "n": 10,
    "ci_low": 0.4,
    "ci_high": 0.6,
    "ci_method": "m",
    "labels": {"policy": "bandit"},
}


def _doc(**metric_changes) -> dict:
    m = {**GOOD_METRIC, **metric_changes}
    m = {k: v for k, v in m.items() if v is not ...}
    return {
        "schema_version": "metrics-1",
        "project": "p",
        "run_id": "r",
        "created_at": "2026-11-17T00:00:00Z",
        "metrics": [m],
    }


def test_the_validator_accepts_a_good_metric():
    validate_metrics1(_doc())


@pytest.mark.parametrize(
    ("doc", "needle"),
    [
        ({**_doc(), "extra": 1}, "unknown top-level"),
        ({**_doc(), "schema_version": "metrics-2"}, "schema_version"),
        ({**_doc(), "created_at": "2026-11-17T00:00:00"}, "zone"),
        ({**_doc(), "provenance": {"commit": "x"}}, "provenance"),
        (_doc(unit="percent"), "unit"),
        (_doc(name="Bad-Name"), "name"),
        (_doc(unit="count", value=1.0, ci_low=..., ci_high=..., ci_method=...), "unit"),
        (_doc(unit="count", value=-1, ci_low=..., ci_high=..., ci_method=...), "unit"),
        (_doc(unit="count", value=True, ci_low=..., ci_high=..., ci_method=...), "unit"),
        (_doc(value=1.5, ci_low=..., ci_high=..., ci_method=...), "unit"),
        (_doc(unit="NTD", value=float("nan"), ci_low=..., ci_high=..., ci_method=...), "unit"),
        (_doc(ci_method=...), "ci_method"),
        (_doc(ci_high=...), "together"),
        (_doc(value=0.7), "outside"),
        (_doc(k=11), "k must"),
        (_doc(n=-1), "n must"),
        (_doc(labels={"policy": {"nested": 1}}), "label"),
        (_doc(labels={"member_id": "a"}), "id"),
        (
            _doc(labels={"policy": "Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXU="}),
            "member-id-shaped",
        ),
    ],
)
def test_the_validator_refuses_each_planted_defect(doc, needle):
    with pytest.raises(MetricsError, match=needle):
        validate_metrics1(doc)


def test_a_duplicate_name_and_labels_is_refused():
    d = _doc()
    d["metrics"].append(copy.deepcopy(d["metrics"][0]))
    with pytest.raises(MetricsError, match="duplicate"):
        validate_metrics1(d)


def test_a_point_outside_its_own_interval_is_refused_not_fixed(summary):
    data = json.loads(SUMMARY.read_text(encoding="utf-8"))
    data["churn"]["auc"]["point"] = data["churn"]["auc"]["hi"] + 0.001
    broken = RunSummary.model_validate_json(json.dumps(data))
    with pytest.raises(MetricsError, match="outside its own interval"):
        to_metrics1(broken)


def _scale(x, path="", factor=0.93) -> Any:
    """Every field gets its own factor (an interval's point, lo and hi share one)."""
    if isinstance(x, (bool, str)) or x is None:
        return x
    if isinstance(x, int):
        return x * 2 if x else x
    if isinstance(x, float):
        return x * factor
    if isinstance(x, dict):
        own = 0.6 + (sum(map(ord, path)) % 35) / 100
        interval = {"point", "lo", "hi"} <= set(x)
        return {k: _scale(v, f"{path}.{k}", factor if interval else own) for k, v in x.items()}
    if isinstance(x, list):
        return [_scale(v, f"{path}[{i}]", factor) for i, v in enumerate(x)]
    return x


def test_a_scaled_summary_changes_every_exported_number(doc):
    data = json.loads(SUMMARY.read_text(encoding="utf-8"))
    keep = {k: data[k] for k in ("schema_version", "started_at", "finished_at", "variants")}
    scaled: dict = _scale(data)
    scaled.update(keep)
    for p, orig in zip(scaled["policies"], data["policies"], strict=True):
        for sp, o in zip(p["spend"], orig["spend"], strict=True):
            sp["period"] = o["period"]  # a label, not a number to scale
    for o in scaled["ope"]:  # covered must still say whether the oracle is inside
        o["covered"] = o["value"]["lo"] <= o["oracle"] <= o["value"]["hi"]
    for c in scaled["comparisons"]:
        c["p_value"] = min(c["p_value"], 1.0)
    other = to_metrics1(RunSummary.model_validate_json(json.dumps(scaled)))
    before = {
        (m["name"], json.dumps(m.get("labels", {}), sort_keys=True)): m for m in doc["metrics"]
    }
    unchanged = []
    for m in other["metrics"]:
        old = before[(m["name"], json.dumps(m.get("labels", {}), sort_keys=True))]
        if isinstance(m["value"], bool) or m["value"] == 0:
            continue
        for field in ("value", "ci_low", "ci_high"):
            if field in m and m[field] == old[field] and m[field] != 0:
                unchanged.append(f"{m['name']}.{field}")
        if "n" in m and m["n"] == old["n"] and m["n"]:
            unchanged.append(f"{m['name']}.n")
    assert not unchanged, sorted(set(unchanged))


def test_the_committed_metrics_file_is_current():
    out = subprocess.run(
        [sys.executable, "-m", "respectful_offers.cli", "metrics", "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert COMMITTED.read_text(encoding="utf-8") == dumps(to_metrics1(load_summary(SUMMARY)))


def test_check_fails_on_drift(tmp_path):
    stale = tmp_path / "metrics.json"
    stale.write_text("{}\n", encoding="utf-8")
    out = subprocess.run(
        [sys.executable, "-m", "respectful_offers.cli", "metrics", "--check", "--out", str(stale)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert out.returncode == 1 and "stale" in out.stdout


def test_a_bare_disparity_key_is_refused_not_dropped():
    data = json.loads(SUMMARY.read_text(encoding="utf-8"))
    data["disparity"]["age_band"] = data["disparity"]["bandit.offer_rate.age_band"]
    with pytest.raises(MetricsError, match="names no policy"):
        to_metrics1(RunSummary.model_validate_json(json.dumps(data)))


def test_disparity_is_labelled_with_the_variant_it_was_computed_on():
    data = json.loads(SUMMARY.read_text(encoding="utf-8"))
    rename = {"central": "middle"}
    data["variants"] = [rename.get(v, v) for v in data["variants"]]
    for section in ("policies", "ope", "comparisons"):
        for row in data[section]:
            row["variant"] = rename.get(row["variant"], row["variant"])
    data["holdout_check"] = {rename.get(k, k): v for k, v in data["holdout_check"].items()}
    doc = to_metrics1(RunSummary.model_validate_json(json.dumps(data)))
    groups = {m["labels"]["variant"] for m in doc["metrics"] if m["name"].startswith("group.")}
    assert groups == {data["variants"][0]}
