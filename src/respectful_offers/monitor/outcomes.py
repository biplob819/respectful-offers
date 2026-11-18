"""The outcome checks of a monitored period, at the severities OWNER D-56 set (E4.3 MON-01).

All four checks read metrics-1 documents (E4.1), so they judge exactly what EvalKit sees.
Each one fails the period:

1. **respect**: a respectful policy has a rule violation (`violations`, `respectful: true`).
2. **claim**: the release gate's own test is lost in some variant: bandit minus the
   rule-following baseline, extra members kept per 1,000 NTD, lower bound >= 0 and separated
   after Holm (`configs/gates.yaml`). A missing claim row counts as lost.
3. **cost**: against the baseline period, a policy's cost per extra member kept is up by
   more than 25% and its interval lies clear of the baseline value (lower bound above it).
4. **disparity**: against the baseline period, a policy's age-band offer-rate gap (largest
   group rate minus smallest) is wider by more than 0.05.

Checks 3 and 4 need a baseline period; with none they are reported as not checked, never as
passed. Drift and calibration alarms are EvalKit's (LED-04) and only warn (OWNER D-56).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

CLAIM = "incremental_retained_per_1000_ntd"
CLAIM_A, CLAIM_B = "bandit", "rule_following_baseline"
POLICIES = ("bandit", "rule_following_baseline")  # the respectful policies that make offers
COST_RISE = 0.25
GAP_WIDENING = 0.05
DISPARITY_ATTRIBUTE = "age_band"


@dataclass(frozen=True)
class Alarm:
    check: str  # respect | claim | cost | disparity
    severity: str  # fail (every outcome check fails under OWNER D-56)
    labels: dict[str, Any]
    message: str


def _rows(doc: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [m for m in doc.get("metrics", []) if m.get("name") == name]


def _find(doc: dict[str, Any], name: str, **labels: Any) -> dict[str, Any] | None:
    for m in _rows(doc, name):
        lab = m.get("labels", {})
        if all(lab.get(k) == v for k, v in labels.items()):
            return m
    return None


class OutcomeError(ValueError):
    """The file holds no policy outcomes, so no outcome check can run: bad input, never a pass."""


def _variants(doc: dict[str, Any]) -> list[str]:
    names = ("violations", f"diff.{CLAIM}", f"separated.{CLAIM}")
    got = {m["labels"]["variant"] for n in names for m in _rows(doc, n) if "variant" in m["labels"]}
    if not got:
        raise OutcomeError(
            f"{doc.get('run_id')}: no violations or claim rows: not a period's outcomes "
            "(a drift input or an empty export?)"
        )
    return sorted(got)


def respect_alarms(period: dict[str, Any]) -> list[Alarm]:
    out = []
    for m in _rows(period, "violations"):
        lab = m.get("labels", {})
        if lab.get("respectful") is True and m["value"] > 0:
            out.append(
                Alarm(
                    "respect",
                    "fail",
                    dict(lab),
                    f"{lab.get('policy')} broke {lab.get('rule')} {m['value']} times "
                    f"({lab.get('variant')})",
                )
            )
    return out


def claim_alarms(period: dict[str, Any]) -> list[Alarm]:
    out = []
    for v in _variants(period):
        lab = {"a": CLAIM_A, "b": CLAIM_B, "variant": v}
        diff = _find(period, f"diff.{CLAIM}", **lab)
        sep = _find(period, f"separated.{CLAIM}", **lab)
        if diff is None or sep is None:
            out.append(Alarm("claim", "fail", lab, f"{v}: no claim comparison: counted as lost"))
            continue
        if not (diff["ci_low"] >= 0 and sep["value"] is True):
            out.append(
                Alarm(
                    "claim",
                    "fail",
                    lab,
                    f"{v}: claim lost (lower bound {diff['ci_low']}, separated {sep['value']})",
                )
            )
    return out


def cost_alarms(baseline: dict[str, Any], period: dict[str, Any]) -> list[Alarm]:
    out = []
    for v in _variants(period):
        for p in POLICIES:
            lab = {"policy": p, "variant": v}
            before = _find(baseline, "cost_per_incremental_retained", **lab)
            now = _find(period, "cost_per_incremental_retained", **lab)
            if before is None:
                continue  # no baseline cost (no extra members then): nothing to compare
            if now is None:
                out.append(
                    Alarm(
                        "cost",
                        "fail",
                        lab,
                        f"{p} ({v}): the cost per extra member is undefined this period "
                        f"(no extra members it can be sure of); baseline {before['value']}",
                    )
                )
                continue
            b = before["value"]
            if now["value"] > (1 + COST_RISE) * b and now["ci_low"] > b:
                out.append(
                    Alarm(
                        "cost",
                        "fail",
                        lab,
                        f"{p} ({v}): cost per extra member {now['value']} against {b} "
                        f"(+{now['value'] / b - 1:.0%}, interval from {now['ci_low']})",
                    )
                )
    return out


def _gaps(doc: dict[str, Any]) -> dict[tuple[str, str], float]:
    groups: dict[tuple[str, str], list[float]] = {}
    for m in _rows(doc, "group.offer_rate"):
        lab = m.get("labels", {})
        if DISPARITY_ATTRIBUTE in lab:
            groups.setdefault((lab["policy"], lab["variant"]), []).append(m["value"])
    return {k: max(v) - min(v) for k, v in groups.items() if len(v) >= 2}


def disparity_alarms(baseline: dict[str, Any], period: dict[str, Any]) -> list[Alarm]:
    before, now = _gaps(baseline), _gaps(period)
    out = []
    for key, gap in sorted(now.items()):
        if key in before and gap - before[key] > GAP_WIDENING:
            p, v = key
            out.append(
                Alarm(
                    "disparity",
                    "fail",
                    {"policy": p, "variant": v, "attribute": DISPARITY_ATTRIBUTE},
                    f"{p} ({v}): age-band offer-rate gap {gap:.4f} against {before[key]:.4f}",
                )
            )
    return out


def outcome_alarms(baseline: dict[str, Any] | None, period: dict[str, Any]) -> dict[str, Any]:
    """Every outcome check of `period`, against `baseline` where a check needs one."""
    _variants(period)  # refuses a file with no outcomes before any check reads it
    if baseline is not None:
        _variants(baseline)
    alarms = respect_alarms(period) + claim_alarms(period)
    not_checked: list[str] = []
    if baseline is None:
        not_checked = ["cost", "disparity"]
    else:
        alarms += cost_alarms(baseline, period) + disparity_alarms(baseline, period)
    return {
        "schema_version": "outcome-alarms-1",
        "period": period.get("run_id"),
        "baseline": None if baseline is None else baseline.get("run_id"),
        "simulated": True,  # offer responses come from the pre-registered simulator
        "fail": any(a.severity == "fail" for a in alarms),
        "alarms": [asdict(a) for a in alarms],
        "not_checked": not_checked,
    }
