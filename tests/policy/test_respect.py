import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from respectful_offers.policy import audit as audit_mod
from respectful_offers.policy.audit import RULES, audit
from respectful_offers.policy.respect import (
    allowed_actions,
    assign_cohorts,
    check_context_columns,
    declined_mask,
)
from tests.policy import minirollout

ALLOW = ("churn_risk", "auto_renew", "tenure_days")


def call(in_holdout, risk, nudged, declined, threshold=0.5):
    return allowed_actions(
        in_holdout=np.array(in_holdout, dtype=bool),
        churn_risk=np.array(risk, dtype=float),
        nudged=np.array(nudged, dtype=bool),
        declined=np.array(declined, dtype=bool),
        risk_threshold=threshold,
    )


def test_each_rule_by_hand():
    none = [False] * 4
    a = call(
        [False, False, False, True, False],
        [0.2, 0.5, 0.5, 0.2, 0.9],
        [False, False, True, False, False],
        [none, none, none, none, [False, True, False, False]],
    )
    assert a[0].tolist() == [True, True, True, True]  # low risk: everything
    assert a[1].tolist() == [True, True, False, False]  # at the threshold, no nudge yet: R2
    assert a[2].tolist() == [True, True, True, True]  # nudged before: commerce allowed
    assert a[3].tolist() == [True, False, False, False]  # holdout: R3
    assert a[4].tolist() == [True, False, False, False]  # declined nudge (R1) and R2


@settings(max_examples=300, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.booleans(),
            st.floats(0, 1),
            st.booleans(),
            st.lists(st.booleans(), min_size=3, max_size=3),
        ),
        min_size=1,
        max_size=30,
    ),
    st.floats(0.01, 0.99),
)
def test_random_states_never_allow_a_forbidden_action(rows, threshold):
    hold = [r[0] for r in rows]
    risk = [r[1] for r in rows]
    nud = [r[2] for r in rows]
    dec = [[False, *r[3]] for r in rows]
    a = call(hold, risk, nud, dec, threshold)
    for i, (h, r, n, d) in enumerate(zip(hold, risk, nud, dec, strict=True)):
        assert a[i, 0]
        assert not (a[i] & np.array(d)).any()
        if r >= threshold and not n:
            assert not a[i, 2] and not a[i, 3]
        if h:
            assert a[i].tolist() == [True, False, False, False]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"in_holdout": [0, 1]},
        {"risk": [0.2, 1.5]},
        {"risk": [0.2, float("nan")]},
        {"declined": [[True, False, False, False]] * 2},
        {"threshold": 1.0},
        {"declined": [[False] * 3] * 2},
    ],
)
def test_bad_inputs_raise(kwargs):
    base = {
        "in_holdout": [False, False],
        "risk": [0.2, 0.3],
        "nudged": [False, False],
        "declined": [[False] * 4] * 2,
        "threshold": 0.5,
    }
    base.update(kwargs)
    with pytest.raises(ValueError):
        allowed_actions(
            in_holdout=np.array(base["in_holdout"]),
            churn_risk=np.array(base["risk"]),
            nudged=np.array(base["nudged"], dtype=bool),
            declined=np.array(base["declined"], dtype=bool),
            risk_threshold=base["threshold"],
        )


def test_declined_mask():
    m = declined_mask([(), ("content_nudge", "plan_change")])
    assert m.tolist() == [[False] * 4, [False, True, False, True]]
    with pytest.raises(ValueError):
        declined_mask([("no_offer",)])
    with pytest.raises(ValueError):
        declined_mask([("teleport",)])


BUCKETS = {"holdout": (0, 10), "train": (10, 40), "logging": (40, 60), "eval": (60, 100)}


def test_cohorts_are_stable_disjoint_and_sized():
    ids = [f"S{i:06d}" for i in range(30_000)]
    c = assign_cohorts(ids, "salt", BUCKETS)
    assert (c == assign_cohorts(ids, "salt", BUCKETS)).all()
    rev = assign_cohorts(ids[::-1], "salt", BUCKETS)
    assert (rev[::-1] == c).all()
    share = pd.Series(c).value_counts(normalize=True)
    for name, (lo, hi) in BUCKETS.items():
        assert abs(share[name] - (hi - lo) / 100) < 0.012
    assert set(c) == set(BUCKETS)
    with pytest.raises(ValueError):
        assign_cohorts(ids, "salt", {**BUCKETS, "eval": (61, 100)})


def test_context_columns_r7():
    check_context_columns(ALLOW, ALLOW)
    with pytest.raises(ValueError, match="protected"):
        check_context_columns([*ALLOW, "gender"], [*ALLOW, "gender"])
    with pytest.raises(ValueError, match="outside the allow-list"):
        check_context_columns([*ALLOW, "price_30d"], ALLOW)


def logs(rows):
    d = pd.DataFrame(
        [{k: r[k] for k in ("policy", "variant", "msno", "period", "chosen")} for r in rows]
    )
    o = pd.DataFrame(
        [{k: r[k] for k in ("policy", "variant", "msno", "period", "response")} for r in rows]
    )
    return d, o


def row(msno, period, chosen, response, policy="bandit"):
    return {
        "policy": policy,
        "variant": "central",
        "msno": msno,
        "period": period,
        "chosen": chosen,
        "response": response,
    }


def run_audit(rows, risk, holdout, ctx=None):
    d, o = logs(rows)
    return audit(
        d,
        o,
        churn_risk=pd.Series(risk),
        holdout=pd.Series(holdout),
        risk_threshold=0.5,
        context_columns=ctx or {"bandit": ALLOW, "holdout": ()},
        allow_list=ALLOW,
    )


@pytest.mark.respect
def test_auditor_counts_each_rule_exactly():
    rows = [
        row("A", 1, "discount_1m", "declined"),
        row("A", 2, "discount_1m", "declined"),  # R1
        row("B", 1, "content_nudge", "declined"),
        row("B", 2, "content_nudge", "declined"),  # R1 nudge
        row("C", 1, "plan_change", "accepted"),  # R2: at threshold, no nudge
        row("D", 1, "content_nudge", "accepted"),
        row("D", 2, "discount_1m", "accepted"),  # clean
        row("E", 1, "content_nudge", "declined", policy="bandit"),  # R3: holdout in bandit
        row("F", 1, "no_offer", "not_shown", policy="holdout"),  # R3: non-holdout in holdout policy
        row("G", 1, "no_offer", "not_shown"),
        row("G", 1, "no_offer", "not_shown"),  # R8
    ]
    risk = {"A": 0.1, "B": 0.1, "C": 0.5, "D": 0.9, "E": 0.1, "F": 0.1, "G": 0.1}
    hold = dict.fromkeys(risk, False) | {"E": True}
    rep = run_audit(rows, risk, hold)
    c = {k: v for k, v in rep.violations("bandit", "central").items()}
    assert c == {"R1": 2, "R2": 1, "R3": 1, "R7": 0, "R8": 1}
    assert rep.violations("holdout", "central")["R3"] == 1
    assert not rep.respectful_policies_clean()
    assert any("A period 2" in e for e in rep.examples[("bandit", "central")])


@pytest.mark.respect
def test_auditor_reports_r7_per_policy_and_clean_logs_count_zero():
    rows = [row("A", 1, "content_nudge", "accepted"), row("A", 2, "discount_1m", "accepted")]
    rep = run_audit(rows, {"A": 0.9}, {"A": False}, ctx={"bandit": (*ALLOW, "gender", "city")})
    assert rep.violations("bandit", "central") == {"R1": 0, "R2": 0, "R3": 0, "R7": 2, "R8": 0}
    clean = run_audit(rows, {"A": 0.9}, {"A": False})
    assert clean.respectful_policies_clean()
    assert set(clean.violations("bandit", "central")) == set(RULES)


@pytest.mark.respect
def test_a_status_quo_violation_does_not_fail_the_run():
    rows = [
        row("A", 1, "discount_1m", "declined", "status_quo"),
        row("A", 2, "discount_1m", "declined", "status_quo"),
    ]
    rep = run_audit(rows, {"A": 0.9}, {"A": False}, ctx={"status_quo": ALLOW})
    assert rep.violations("status_quo", "central")["R1"] == 1
    assert rep.violations("status_quo", "central")["R2"] == 2
    assert rep.respectful_policies_clean()


@pytest.mark.respect
def test_auditor_refuses_missing_inputs():
    d, o = logs([row("A", 1, "no_offer", "not_shown")])
    with pytest.raises(ValueError, match="without outcomes"):
        audit(
            d,
            o.iloc[0:0],
            churn_risk=pd.Series({"A": 0.1}),
            holdout=pd.Series({"A": False}),
            risk_threshold=0.5,
            context_columns={"bandit": ALLOW},
            allow_list=ALLOW,
        )
    with pytest.raises(ValueError, match="churn_risk is missing"):
        audit(
            d,
            o,
            churn_risk=pd.Series({"Z": 0.1}),
            holdout=pd.Series({"A": False}),
            risk_threshold=0.5,
            context_columns={"bandit": ALLOW},
            allow_list=ALLOW,
        )


@pytest.mark.respect
def test_auditor_never_imports_the_filter():
    tree = ast.parse(Path(audit_mod.__file__).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
    forbidden = {"respectful_offers.policy.respect", "respect", "allowed_actions", "declined_mask"}
    assert not (names & forbidden), names
    assert not any(n.endswith(".respect") for n in names), names


@pytest.mark.respect
def test_the_real_filter_audits_clean_over_random_rollouts():
    for seed in range(5):
        d, o, risk, hold = minirollout.run(allowed_actions, seed=seed)
        rep = audit(
            d,
            o,
            churn_risk=risk,
            holdout=hold,
            risk_threshold=0.5,
            context_columns={"bandit": ALLOW, "holdout": ALLOW},
            allow_list=ALLOW,
        )
        assert rep.respectful_policies_clean(), rep.counts


def _broken(mutant):
    """Broken filters, from blunt to subtle, each expected to trip one rule."""

    def f(**kw):
        a = allowed_actions(**kw)
        hold, risk, nud, dec = kw["in_holdout"], kw["churn_risk"], kw["nudged"], kw["declined"]
        if mutant == "R1: ignores every decline":
            a |= dec
        elif mutant == "R1: ignores declined nudges only":
            a[:, 1] |= dec[:, 1] & ~hold
        elif mutant == "R1: ignores declined plan changes only":
            a[:, 3] |= dec[:, 3] & ~hold & ((risk < 0.5) | nud)
        elif mutant == "R2: ignores the rule":
            a[:, 2:] |= ~hold[:, None]
        elif mutant == "R2: uses > instead of >=":
            at = (risk == 0.5) & ~nud & ~hold
            a[at, 2] = ~dec[at, 2]
        elif mutant == "R3: offers holdout members a nudge":
            a[hold, 1] = True
        elif mutant == "R3: only for high-risk holdout members":
            a[hold & (risk >= 0.9), 1] = True
        return a

    return f


MUTANTS = [
    ("R1: ignores every decline", "R1"),
    ("R1: ignores declined nudges only", "R1"),
    ("R1: ignores declined plan changes only", "R1"),
    ("R2: ignores the rule", "R2"),
    ("R2: uses > instead of >=", "R2"),
    ("R3: offers holdout members a nudge", "R3"),
    ("R3: only for high-risk holdout members", "R3"),
]


@pytest.mark.respect
@pytest.mark.parametrize(("mutant", "rule"), MUTANTS)
def test_each_broken_filter_is_caught_on_its_rule(mutant, rule):
    for seed in range(6):
        d, o, risk, hold = minirollout.run(_broken(mutant), seed=seed, n=600)
        rep = audit(
            d,
            o,
            churn_risk=risk,
            holdout=hold,
            risk_threshold=0.5,
            context_columns={"bandit": ALLOW, "holdout": ()},
            allow_list=ALLOW,
        )
        total = {r: sum(c[r] for c in rep.counts.values()) for r in RULES}
        assert total[rule] > 0, (mutant, seed, total)


def drow(**over):
    base = row("A", 1, "discount_1m", "declined")
    base.update(over)
    return base


@pytest.mark.respect
def test_duplicate_or_conflicting_outcomes_cannot_hide_a_decline():
    d = pd.DataFrame(
        [
            {k: r[k] for k in ("policy", "variant", "msno", "period", "chosen")}
            for r in (drow(), drow(period=2))
        ]
    )
    o = pd.DataFrame(
        [
            {
                "policy": "bandit",
                "variant": "central",
                "msno": "A",
                "period": 1,
                "response": "accepted",
            },
            {
                "policy": "bandit",
                "variant": "central",
                "msno": "A",
                "period": 1,
                "response": "declined",
            },
            {
                "policy": "bandit",
                "variant": "central",
                "msno": "A",
                "period": 2,
                "response": "declined",
            },
        ]
    )
    rep = audit(
        d,
        o,
        churn_risk=pd.Series({"A": 0.1}),
        holdout=pd.Series({"A": False}),
        risk_threshold=0.5,
        context_columns={"bandit": ALLOW},
        allow_list=ALLOW,
    )
    c = rep.violations("bandit", "central")
    assert c["R1"] == 1 and c["R8"] == 1


@pytest.mark.respect
@pytest.mark.parametrize(
    ("over", "match"),
    [
        ({"response": "Declined"}, "unknown response"),
        ({"chosen": "Discount_1m"}, "unknown chosen action"),
        ({"chosen": "free_month"}, "unknown chosen action"),
        ({"period": 1.5}, "positive integer"),
    ],
)
def test_unknown_values_are_refused_not_ignored(over, match):
    r = drow(**over)
    d, o = logs([r])
    with pytest.raises(ValueError, match=match):
        audit(
            d,
            o,
            churn_risk=pd.Series({"A": 0.9}),
            holdout=pd.Series({"A": False}),
            risk_threshold=0.5,
            context_columns={"bandit": ALLOW},
            allow_list=ALLOW,
        )


@pytest.mark.respect
def test_orphan_outcomes_and_missing_context_fail_closed():
    d, o = logs([drow()])
    o2 = pd.concat([o, o.assign(period=2)], ignore_index=True)
    kw = {
        "churn_risk": pd.Series({"A": 0.1}),
        "holdout": pd.Series({"A": False}),
        "risk_threshold": 0.5,
        "allow_list": ALLOW,
    }
    with pytest.raises(ValueError, match="outcomes without decisions"):
        audit(d, o2, context_columns={"bandit": ALLOW}, **kw)
    with pytest.raises(ValueError, match="no logged context columns"):
        audit(d, o, context_columns={}, **kw)


@pytest.mark.respect
@pytest.mark.parametrize(
    ("kw", "match"),
    [
        ({"risk_threshold": float("nan")}, "risk_threshold"),
        ({"churn_risk": pd.Series({"A": 1.5})}, "finite probabilities"),
        ({"holdout": pd.Series({"A": "False"})}, "booleans"),
    ],
)
def test_bad_auditor_inputs_raise(kw, match):
    d, o = logs([drow()])
    base = {
        "churn_risk": pd.Series({"A": 0.1}),
        "holdout": pd.Series({"A": False}),
        "risk_threshold": 0.5,
        "context_columns": {"bandit": ALLOW},
        "allow_list": ALLOW,
    }
    base.update(kw)
    with pytest.raises(ValueError, match=match):
        audit(d, o, **base)
    with pytest.raises(ValueError, match="empty log"):
        audit(d.iloc[0:0], o.iloc[0:0], **{**base, **{k: v for k, v in kw.items() if False}})


@pytest.mark.respect
def test_r8_counts_one_violation_per_extra_decision():
    rows = [row("G", 1, "no_offer", "not_shown")] * 3
    rep = run_audit(rows, {"G": 0.1}, {"G": False})
    assert rep.violations("bandit", "central")["R8"] == 2


def test_filter_refuses_string_risks_and_array_thresholds():
    with pytest.raises(ValueError):
        allowed_actions(
            in_holdout=np.array([False]),
            churn_risk=np.array(["0.9"]),
            nudged=np.array([False]),
            declined=np.zeros((1, 4), bool),
            risk_threshold=0.5,
        )
    with pytest.raises(ValueError):
        allowed_actions(
            in_holdout=np.array([False]),
            churn_risk=np.array([0.9]),
            nudged=np.array([False]),
            declined=np.zeros((1, 4), bool),
            risk_threshold=np.array([0.5]),  # type: ignore[arg-type]
        )


@pytest.mark.respect
@pytest.mark.parametrize(
    ("chosen", "response"),
    [("discount_1m", "not_shown"), ("no_offer", "declined"), ("content_nudge", "not_shown")],
)
def test_responses_must_agree_with_the_action(chosen, response):
    d, o = logs([drow(chosen=chosen, response=response)])
    with pytest.raises(ValueError, match="contradicts"):
        audit(
            d,
            o,
            churn_risk=pd.Series({"A": 0.1}),
            holdout=pd.Series({"A": False}),
            risk_threshold=0.5,
            context_columns={"bandit": ALLOW},
            allow_list=ALLOW,
        )


@pytest.mark.respect
@pytest.mark.parametrize("period", [True, 1e20])
def test_boolean_and_absurd_periods_are_refused(period):
    d, o = logs([drow(period=period)])
    with pytest.raises(ValueError, match="period"):
        audit(
            d,
            o,
            churn_risk=pd.Series({"A": 0.1}),
            holdout=pd.Series({"A": False}),
            risk_threshold=0.5,
            context_columns={"bandit": ALLOW},
            allow_list=ALLOW,
        )


def test_filter_and_auditor_agree_on_protected_names_and_float32_thresholds():
    for name in ("sex", "msno"):
        with pytest.raises(ValueError, match="protected"):
            check_context_columns([name], [name])
    a = allowed_actions(
        in_holdout=np.array([False]),
        churn_risk=np.array([0.5]),
        nudged=np.array([False]),
        declined=np.zeros((1, 4), bool),
        risk_threshold=np.float32(0.5),
    )
    assert a.tolist() == [[True, True, False, False]]


R7_NAMES = (
    "birthYear",
    "birth_date",
    "year_of_birth",
    "registered",
    "registered_days",
    "registration_init_time",
    "dob",
    "yob",
    "regVia",
    "registration_method",
    "gndr",
    "user_id",
    "userId",
    "zip",
    "region",
    "location",
    "BD",
    "bd2",
    "Gender2",
    "cityName",
    "registeredVia",
    "cityId",
    "city_id",
    "ageBand",
    "age_band",
    "sex_code",
    "userGender",
    "registered_via_code",
    "postcode_area",
    "msno",
    "age",
    "account_age_days",
)
R7_ALLOWED = (
    "average_listen",
    "tenure_days",
    "cancels_90d",
    "listening_trend_30d",
    "price_30d",
    "auto_renew",
    "churn_risk",
    "nudged",
    "declined",
    "percentage",
    "payment_method_id",
    "plan_days",
    "is_cancel",
)


def test_r7_filter_and_auditor_agree_on_protected_names():
    """Two independent copies of one rule (D-37): they must never drift apart."""
    from respectful_offers.policy.audit import _protected
    from respectful_offers.schemas.config import protected_name

    for name in (*R7_NAMES, *R7_ALLOWED):
        assert protected_name(name) == _protected(name), name
    assert all(protected_name(n) for n in R7_NAMES)
    assert not any(protected_name(n) for n in R7_ALLOWED)
