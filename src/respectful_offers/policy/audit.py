"""The independent respect auditor (Tech Spec §6.2, D-4).

Recomputes every rule from the decision and outcome logs alone. It deliberately does not
import `respect.py`: a filter that audited itself would report zero violations exactly when
it was wrong (L-4). Member histories (what was declined, whether a nudge was shown) are
rebuilt from the logs, never read from the member-state table.

Counts per policy × variant:
  R1  a chosen action that the member declined in an earlier period;
  R2  a commercial action for a member at or above the risk threshold with no earlier nudge;
  R3  any shown action to a holdout member, or a holdout member in a non-holdout policy,
      or a non-holdout member in the holdout policy;
  R7  context columns outside the allow-list or protected attributes, per policy;
  R8  more than one decision for a member in one period.
"""

from __future__ import annotations

import itertools
import numbers
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

RULES = ("R1", "R2", "R3", "R7", "R8")
KEYS = ["policy", "variant", "msno", "period"]
# Written out here rather than imported, so a mistake in a shared constant cannot carry into
# both the filter and its auditor (A2.3 verifier).
_ALL_ACTIONS = frozenset({"no_offer", "content_nudge", "discount_1m", "plan_change"})
_RESPONSES = frozenset({"accepted", "declined", "not_shown"})
_PROTECTED = frozenset({"age", "bd", "age_band", "gender", "sex", "city", "registered_via", "msno"})
_PROTECTED_WORDS = frozenset(
    {
        "age",
        "bd",
        "gender",
        "gndr",
        "sex",
        "city",
        "region",
        "location",
        "zip",
        "postcode",
        "birth",
        "dob",
        "yob",
        "registered",
        "registration",
        "msno",
    }
)
_PROTECTED_PAIRS = frozenset(
    {("reg", "via"), ("registered", "via"), ("age", "band"), ("user", "id")}
)


def _protected(column: str) -> bool:
    """Its own proxy rule, written apart from the filter's: a column is protected if its name,
    any word in it (snake, kebab or camel case, digits split off), or any adjacent pair of
    words is protected (D-37)."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", column)
    words = [w for w in re.split(r"[^a-z]+", spaced.lower()) if w]
    pairs = set(itertools.pairwise(words))
    return (
        column in _PROTECTED
        or bool(set(words) & _PROTECTED_WORDS)
        or bool(pairs & _PROTECTED_PAIRS)
    )


_AUDIT_ACTIONS = ("content_nudge", "discount_1m", "plan_change")
_COMMERCIAL = ("discount_1m", "plan_change")
MAX_PERIOD = 1_000
NOT_RESPECTFUL = frozenset({"status_quo", "unfiltered_bandit"})


@dataclass(frozen=True)
class AuditReport:
    counts: dict[tuple[str, str], dict[str, int]]
    examples: dict[tuple[str, str], list[str]] = field(default_factory=dict)

    def violations(self, policy: str, variant: str) -> dict[str, int]:
        return self.counts.get((policy, variant), dict.fromkeys(RULES, 0))

    def respectful_policies_clean(self) -> bool:
        return all(
            sum(c.values()) == 0 for (p, _), c in self.counts.items() if p not in NOT_RESPECTFUL
        )


def audit(
    decisions: pd.DataFrame,
    outcomes: pd.DataFrame,
    *,
    churn_risk: pd.Series,
    holdout: pd.Series,
    risk_threshold: float,
    context_columns: Mapping[str, Sequence[str]],
    allow_list: Sequence[str],
) -> AuditReport:
    """`churn_risk` and `holdout` are indexed by msno and come from the scoring and cohort
    stages, not from the rollout's own state. Bad or incomplete inputs raise; the auditor
    never fails open."""
    if decisions.empty:
        raise ValueError("no decisions to audit: an empty log cannot be certified clean")
    if (
        isinstance(risk_threshold, bool)
        or not isinstance(risk_threshold, numbers.Real)
        or not (0.0 < float(risk_threshold) < 1.0)
    ):
        raise ValueError(f"risk_threshold must be a number inside (0, 1), got {risk_threshold!r}")
    risk_values = pd.to_numeric(churn_risk, errors="coerce")
    if risk_values.isna().any() or not risk_values.between(0.0, 1.0).all():
        raise ValueError("churn_risk must be finite probabilities")
    if holdout.dtype != bool:
        raise ValueError(f"holdout flags must be booleans, got dtype {holdout.dtype}")

    d = decisions[[*KEYS, "chosen"]].copy()
    o = outcomes[[*KEYS, "response"]].copy()
    for frame, name in ((d, "decisions"), (o, "outcomes")):
        if (
            frame["period"].dtype == bool
            or frame["period"].map(lambda v: isinstance(v, bool)).any()
        ):
            raise ValueError(f"{name}: period must be a positive integer, not a boolean")
        try:
            periods = pd.to_numeric(frame["period"], errors="raise")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name}: period must be an integer") from exc
        if (
            (periods != periods.round()).any()
            or (periods < 1).any()
            or (periods > MAX_PERIOD).any()
        ):
            raise ValueError(f"{name}: period must be a positive integer up to {MAX_PERIOD}")
        frame["period"] = periods.astype(np.int64)
    bad_actions = sorted(set(d["chosen"].astype(str)) - _ALL_ACTIONS)
    if bad_actions:
        raise ValueError(f"unknown chosen action(s) {bad_actions}")
    bad_responses = sorted(set(o["response"].astype(str)) - _RESPONSES)
    if bad_responses:
        raise ValueError(f"unknown response value(s) {bad_responses}")
    joined = d.merge(o, on=KEYS, how="inner")
    shown = joined["chosen"].ne("no_offer")
    inconsistent = (shown & joined["response"].eq("not_shown")) | (
        ~shown & joined["response"].ne("not_shown")
    )
    if inconsistent.any():
        r = joined.loc[inconsistent].iloc[0]
        raise ValueError(
            f"response {r['response']!r} contradicts chosen {r['chosen']!r} for {r['msno']} "
            f"period {r['period']}: a shown action is accepted or declined, no_offer is not_shown"
        )
    missing_ctx = sorted(set(d["policy"].astype(str)) - set(context_columns))
    if missing_ctx:
        raise ValueError(
            f"no logged context columns for policy {missing_ctx} (R7 cannot pass unseen)"
        )

    # R8: every surplus row for a member-period counts once, whether it is an extra decision or
    # an extra (possibly conflicting) outcome; any decline among duplicate outcomes is a decline
    dec_n = d.groupby(KEYS, sort=False).size().rename("dec_n")
    out_n = o.groupby(KEYS, sort=False).size().rename("out_n")
    o["declined"] = o["response"].eq("declined")
    o = o.groupby(KEYS, as_index=False, sort=False).agg(declined=("declined", "max"))
    merged = d.merge(o, on=KEYS, how="outer", indicator=True, validate="many_to_one")
    if (merged["_merge"] == "left_only").any():
        missing = merged.loc[merged["_merge"] == "left_only", KEYS].head(3).to_dict("records")
        raise ValueError(f"decisions without outcomes, e.g. {missing}")
    if (merged["_merge"] == "right_only").any():
        orphan = merged.loc[merged["_merge"] == "right_only", KEYS].head(3).to_dict("records")
        raise ValueError(f"outcomes without decisions, e.g. {orphan}")
    d = merged.drop(columns="_merge")
    d = d.sort_values([*KEYS[:3], "period"], kind="mergesort").reset_index(drop=True)
    extra = (
        pd.concat([dec_n, out_n], axis=1)
        .fillna(1)
        .sub(1)
        .max(axis=1)
        .astype(np.int64)
        .rename("extra")
    )
    d = d.merge(extra.reset_index(), on=KEYS, how="left")
    d["dup"] = np.where(~d.duplicated(KEYS, keep="first"), d["extra"], 0)
    members = ["policy", "variant", "msno"]

    declined_now = d["declined"].astype(bool)
    r1 = np.zeros(len(d), dtype=bool)
    for action in _AUDIT_ACTIONS:
        d["_h"] = (declined_now & d["chosen"].eq(action)).astype(np.int64)
        before = d.groupby(members, sort=False)["_h"].cumsum() - d["_h"]
        r1 |= (before > 0).to_numpy() & d["chosen"].eq(action).to_numpy()
    d["_n"] = d["chosen"].eq("content_nudge").astype(np.int64)
    nudged_before = (d.groupby(members, sort=False)["_n"].cumsum() - d["_n"]) > 0

    risk = d["msno"].map(risk_values)
    if risk.isna().any():
        raise ValueError("churn_risk is missing for some audited members")
    commercial = d["chosen"].isin(_COMMERCIAL)
    r2 = commercial & (risk >= float(risk_threshold)) & ~nudged_before

    in_holdout = d["msno"].map(holdout)
    if in_holdout.isna().any():
        raise ValueError("holdout flag is missing for some audited members")
    in_holdout = in_holdout.astype(bool)
    is_holdout_policy = d["policy"].eq("holdout")
    r3 = (in_holdout & d["chosen"].ne("no_offer")) | (in_holdout != is_holdout_policy)

    d["R1"], d["R2"], d["R3"], d["R8"] = r1, r2.to_numpy(), r3.to_numpy(), d["dup"].to_numpy()
    counts: dict[tuple[str, str], dict[str, int]] = {}
    examples: dict[tuple[str, str], list[str]] = {}
    allowed = set(allow_list)
    for (policy, variant), g in d.groupby(["policy", "variant"], sort=True):
        cols = context_columns.get(str(policy), ())
        r7 = len((set(cols) - allowed) | {c for c in cols if _protected(c)})
        c = {r: int(g[r].sum()) for r in ("R1", "R2", "R3", "R8")}
        c["R7"] = r7
        key = (str(policy), str(variant))
        counts[key] = {r: c[r] for r in RULES}
        bad = g[g[["R1", "R2", "R3", "R8"]].any(axis=1)].head(3)
        examples[key] = [_example(r) for r in bad.itertuples()]
    return AuditReport(counts, examples)


def _example(r: Any) -> str:
    rules = ", ".join(x for x in ("R1", "R2", "R3", "R8") if getattr(r, x))
    return f"{r.msno} period {r.period}: {r.chosen} ({rules})"
