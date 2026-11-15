import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from respectful_offers.policy.audit import audit
from respectful_offers.policy.baselines import (
    Holdout,
    LoggingPolicy,
    NoOffer,
    Policy,
    RuleFollowingBaseline,
    SegmentOracle,
    StatusQuo,
)
from respectful_offers.policy.budget import admit
from respectful_offers.policy.rollout import rollout
from respectful_offers.sim.response import Tables, expected_reward_by_segment

THRESHOLD = 0.15
ALL = (NoOffer, Holdout, StatusQuo, RuleFollowingBaseline, LoggingPolicy, SegmentOracle)


def run(policy, cohort, sim, budget=3000.0, seed=7, **kw):
    return rollout(
        policy,
        cohort,
        sim,
        "central",
        periods=3,
        risk_threshold=THRESHOLD,
        budget_per_1000=budget,
        seed=seed,
        run_id="t",
        **kw,
    )


def audit_of(res, cohort, name):
    return audit(
        res.decisions,
        res.outcomes,
        churn_risk=pd.Series(cohort.churn_risk, index=cohort.msno),
        holdout=pd.Series(name == "holdout", index=cohort.msno),
        risk_threshold=THRESHOLD,
        context_columns={name: ()},
        allow_list=(),
    ).violations(name, "central")


@pytest.mark.parametrize("cls", ALL)
def test_probabilities_are_distributions_and_rollouts_audit_as_expected(cls, cohort, sim):
    hold = np.ones(len(cohort), bool) if cls is Holdout else None
    res = run(cls(), cohort, sim, in_holdout=hold)
    v = audit_of(res, cohort, cls.name)
    if cls is StatusQuo:
        assert v["R1"] > 0 and v["R2"] > 0
    else:
        assert v == {"R1": 0, "R2": 0, "R3": 0, "R7": 0, "R8": 0}
    assert not res.decisions.duplicated(["msno", "period"]).any()


class Rogue(Policy):
    name = "bandit"

    def probabilities(self, view):
        p = np.zeros((len(view.allowed), 4))
        p[:, 2] = 1.0  # always a discount, ignoring the filter
        return p


def test_a_respectful_policy_cannot_put_mass_on_a_forbidden_action(cohort, sim):
    with pytest.raises(RuntimeError, match="forbidden action"):
        run(Rogue(), cohort, sim)


def test_choose_samples_in_proportion():
    probs = np.tile([0.1, 0.2, 0.3, 0.4], (100_000, 1))
    picks = NoOffer().choose(probs, np.random.default_rng(0).uniform(size=len(probs)))
    assert np.allclose(np.bincount(picks, minlength=4) / 1e5, [0.1, 0.2, 0.3, 0.4], atol=0.01)


def test_no_offer_and_holdout_offer_nothing(cohort, sim):
    for cls in (NoOffer, Holdout):
        assert set(run(cls(), cohort, sim).decisions["chosen"]) == {"no_offer"}


def test_status_quo_discounts_the_at_risk_every_period(cohort, sim):
    res = run(StatusQuo(), cohort, sim, budget=1e9)
    d = res.decisions.merge(
        pd.DataFrame({"msno": cohort.msno, "risk": cohort.churn_risk}), on="msno"
    )
    at_risk = d["risk"] >= THRESHOLD
    assert (d.loc[at_risk, "chosen"] == "discount_1m").all()
    assert (d.loc[~at_risk, "chosen"] == "no_offer").all()
    assert (d.groupby("msno")["period"].max() >= 2).any()


def test_rule_following_nudges_first_and_never_reoffers(cohort, sim):
    d = run(RuleFollowingBaseline(), cohort, sim, budget=1e9).decisions
    first = d[d["period"] == 1].merge(
        pd.DataFrame({"msno": cohort.msno, "risk": cohort.churn_risk}), on="msno"
    )
    assert set(first.loc[first["risk"] >= THRESHOLD, "chosen"]) == {"content_nudge"}
    assert "discount_1m" in set(d.loc[d["period"] == 2, "chosen"])


@settings(max_examples=200, deadline=None)
@given(st.integers(1, 60), st.floats(0, 5000), st.integers(0, 10_000))
def test_the_pacer_never_overspends(n, budget, seed):
    rng = np.random.default_rng(seed)
    fv = np.zeros((n, 4))
    fv[:, 2] = rng.uniform(10, 200, n)
    fv[:, 3] = rng.uniform(10, 300, n)
    requested = rng.integers(0, 4, n)
    adm = admit(
        requested,
        np.zeros(n, int),
        rng.uniform(size=n),
        rng.integers(0, 2**31, n).astype(np.uint64),
        fv,
        budget,
    )
    assert adm.committed <= budget * (1 + 1e-9) + 1e-9
    assert (adm.face_value[adm.downgraded] == 0).all()


def test_the_pacer_admits_by_priority_with_stable_ties():
    fv = np.zeros((4, 4))
    fv[:, 2] = 100.0
    req = np.full(4, 2)
    adm = admit(
        req,
        np.zeros(4, int),
        np.array([0.1, 0.9, 0.5, 0.5]),
        np.array([4, 3, 2, 1], np.uint64),
        fv,
        250.0,
    )
    assert adm.chosen.tolist() == [0, 2, 0, 2]  # 0.9 first, then the 0.5 tie with the lower hash
    zero = admit(req, np.zeros(4, int), np.ones(4), np.arange(4, dtype=np.uint64), fv, 0.0)
    assert (zero.chosen == 0).all()
    for bad in (-1.0, float("nan")):
        with pytest.raises(ValueError):
            admit(req, np.zeros(4, int), np.ones(4), np.arange(4, dtype=np.uint64), fv, bad)
    with pytest.raises(ValueError):
        admit(
            req,
            np.zeros(4, int),
            np.array([1, np.nan, 1, 1]),
            np.arange(4, dtype=np.uint64),
            fv,
            10.0,
        )


def test_budgeted_rollouts_stay_within_the_budget(cohort, sim):
    res = run(StatusQuo(), cohort, sim, budget=500.0)
    for s in res.spend:
        assert s["face_value_committed"] <= s["budget"]  # exactly, no tolerance
    # a plan change is charged in full when sent and realised over later periods, so realised
    # cost is bounded by face value over the horizon, not period by period
    realised = sum(s["realised_cost"] for s in res.spend)
    assert realised <= sum(s["face_value_committed"] for s in res.spend) + 1e-9
    assert res.decisions["budget_downgraded"].any()


def test_logging_is_uniform_with_exact_propensities(cohort, sim):
    d = run(LoggingPolicy(), cohort, sim).decisions
    sizes = d["allowed"].map(len)
    assert np.allclose(d["propensity"], 1.0 / sizes)
    assert not d["budget_downgraded"].any()


def test_the_segment_oracle_is_the_ceiling_at_period_one(cohort, sim):
    t = Tables.from_config(sim, "central")
    ev = expected_reward_by_segment(cohort.base, cohort.segment, cohort.price, t)
    values = {}
    for cls in (NoOffer, RuleFollowingBaseline, LoggingPolicy, SegmentOracle):
        d = run(cls(), cohort, sim, budget=1e9).decisions
        p1 = d[d["period"] == 1].set_index("msno").loc[cohort.msno]
        idx = (
            p1["chosen"]
            .map({"no_offer": 0, "content_nudge": 1, "discount_1m": 2, "plan_change": 3})
            .to_numpy()
        )
        values[cls.name] = ev[np.arange(len(cohort)), idx].mean()
    assert all(values["segment_oracle"] >= v - 1e-9 for v in values.values())


def test_rollouts_are_deterministic_and_share_luck(cohort, sim):
    a = run(RuleFollowingBaseline(), cohort, sim)
    b = run(RuleFollowingBaseline(), cohort, sim)
    pd.testing.assert_frame_equal(a.decisions, b.decisions)
    pd.testing.assert_frame_equal(a.outcomes, b.outcomes)
    n = run(NoOffer(), cohort, sim)
    o1 = a.outcomes[a.outcomes["period"] == 1].set_index("msno")
    n1 = n.outcomes[n.outcomes["period"] == 1].set_index("msno")
    same = a.decisions[(a.decisions["period"] == 1) & (a.decisions["chosen"] == "no_offer")]["msno"]
    assert (o1.loc[same, "renewed"] == n1.loc[same, "renewed"]).all()


def test_members_who_leave_get_no_more_decisions_and_state_carries(cohort, sim):
    res = run(RuleFollowingBaseline(), cohort, sim, budget=1e9)
    o = res.outcomes
    gone = o[(o["period"] == 1) & ~o["renewed"]]["msno"]
    assert not res.decisions[
        (res.decisions["period"] == 2) & res.decisions["msno"].isin(gone)
    ].shape[0]
    st2 = res.states[res.states["period"] == 2].set_index("msno")
    nudged1 = res.decisions[
        (res.decisions["period"] == 1) & (res.decisions["chosen"] == "content_nudge")
    ]["msno"]
    still = [m for m in nudged1 if m in st2.index]
    assert st2.loc[still, "nudged"].all()


def test_the_rollout_never_offers_a_second_plan_change(sim):
    import pandas as pd

    from respectful_offers.policy.baselines import Policy
    from respectful_offers.policy.cohort import build_cohort
    from respectful_offers.policy.rollout import rollout

    class PlanFan(Policy):
        name = "bandit"

        def probabilities(self, view):
            p = np.where(view.allowed, 0.0, 0.0)
            p[:, 3] = np.where(view.allowed[:, 3], 1.0, 0.0)
            p[:, 0] = 1.0 - p[:, 3]
            return p

    n = 500
    feats = pd.DataFrame(
        {
            "msno": [f"P{i}" for i in range(n)],
            "cohort": "mar",
            "as_of": pd.Timestamp("2017-03-01").date(),
            "tenure_days": 100,
            "auto_renew": True,
            "cancels_90d": 0,
            "listening_trend_30d": 0.0,
            "price_30d": 149.0,
            "plan_days": 30,
            "churn_label": False,
        }
    )
    c = build_cohort(
        pd.DataFrame({"msno": feats["msno"], "churn_risk": 0.05}), feats, sim, "central", 1
    )
    d = rollout(
        PlanFan(),
        c,
        sim,
        "central",
        periods=3,
        risk_threshold=0.15,
        budget_per_1000=1e9,
        seed=1,
        run_id="p",
    ).decisions
    assert (d.groupby("msno")["chosen"].apply(lambda s: (s == "plan_change").sum()) <= 1).all()
    moved = set(d[(d["period"] == 1) & (d["chosen"] == "plan_change")]["msno"])
    later = d[(d["period"] > 1) & d["msno"].isin(moved)]
    assert len(later) and all("plan_change" not in tuple(a) for a in later["allowed"])


# -- A2.4 verifier findings -----------------------------------------------------------------


class Broken(Policy):
    name = "logging"
    budgeted = False

    def __init__(self, probs):
        self.p = np.asarray(probs, dtype=float)

    def probabilities(self, view):
        return np.tile(self.p, (len(view.allowed), 1))


@pytest.mark.parametrize(
    "probs", [[1.5, 0.0, 0.0, -0.5], [0.5, 0.0, 0.0, 0.0], [np.nan, 1.0, 0.0, 0.0]]
)
def test_probabilities_must_be_distributions_before_choosing(cohort, sim, probs):
    with pytest.raises(ValueError, match="action probabilities"):
        run(Broken(probs), cohort, sim)


def test_a_zero_probability_action_is_never_drawn():
    probs = np.tile([0.3, 0.0, 0.7, 0.0], (50_000, 1))
    u = np.random.default_rng(1).uniform(size=50_000)
    u[:10] = np.nextafter(1.0, 0.0)  # the largest uniform below 1
    picks = NoOffer().choose(probs, u)
    assert set(np.unique(picks)) <= {0, 2}


def test_the_status_quo_never_contacts_the_holdout(cohort, sim):
    hold = np.zeros(len(cohort), bool)
    hold[::3] = True
    res = run(StatusQuo(), cohort, sim, budget=1e9, in_holdout=hold)
    d = res.decisions.set_index("msno")
    held = d.loc[cohort.msno[hold]]
    assert (held["chosen"] == "no_offer").all()
    assert audit_of(res, cohort, "status_quo") is not None


def test_the_pacer_never_exceeds_the_budget_even_by_rounding():
    fv = np.zeros((2, 4))
    fv[:, 2] = [0.1, 0.2]
    adm = admit(
        np.array([2, 2]),
        np.zeros(2, int),
        np.array([2.0, 1.0]),
        np.arange(2, dtype=np.uint64),
        fv,
        0.3,
    )
    assert adm.committed <= 0.3
    assert adm.downgraded.sum() == 1  # 0.1 + 0.2 > 0.3 in exact arithmetic


def test_choices_are_keyed_by_member_not_by_cohort_make_up(cohort, sim):
    a = run(LoggingPolicy(), cohort, sim).decisions
    keep = np.ones(len(cohort), bool)
    keep[0] = False
    b = run(LoggingPolicy(), cohort.subset(keep), sim).decisions
    a1 = a[a["period"] == 1].set_index("msno")["requested"]
    b1 = b[b["period"] == 1].set_index("msno")["requested"]
    assert (a1.loc[b1.index] == b1).all()


class FreeOracle(SegmentOracle):
    """The oracle restricted to free actions: what a downgraded oracle can always do."""

    def _values(self, view):
        v = super()._values(view)
        return np.where(view.free[None, :], v, -np.inf)


# threshold 0.99: almost nobody is at risk, so R2 lets costly offers through at period 1 and
# the budget, not the respect filter, decides who gets them
@pytest.mark.parametrize("budget", [0.0, 50.0, 1e9])
def test_the_oracle_is_the_ceiling_at_period_one_under_any_budget(cohort, sim, budget):
    t = Tables.from_config(sim, "central")
    ev = expected_reward_by_segment(cohort.base, cohort.segment, cohort.price, t)
    code = {"no_offer": 0, "content_nudge": 1, "discount_1m": 2, "plan_change": 3}
    values = {}
    for pol in (NoOffer(), RuleFollowingBaseline(), LoggingPolicy(), FreeOracle(), SegmentOracle()):
        d = rollout(
            pol,
            cohort,
            sim,
            "central",
            periods=1,
            risk_threshold=0.99,
            budget_per_1000=budget,
            seed=7,
            run_id="t",
        ).decisions
        p1 = d.set_index("msno").loc[cohort.msno]
        values[type(pol).__name__] = ev[np.arange(len(cohort)), p1["chosen"].map(code)].mean()
    assert all(values["SegmentOracle"] >= v - 1e-9 for v in values.values()), values


def test_a_refused_oracle_request_falls_back_to_its_best_free_action(cohort, sim):
    t = Tables.from_config(sim, "central")
    ev = expected_reward_by_segment(cohort.base, cohort.segment, cohort.price, t)
    d = rollout(
        SegmentOracle(),
        cohort,
        sim,
        "central",
        periods=1,
        risk_threshold=0.99,
        budget_per_1000=0.0,
        seed=7,
        run_id="t",
    ).decisions.set_index("msno")
    down = d.loc[cohort.msno, "budget_downgraded"].to_numpy()
    assert down.any()
    free_best = np.where(np.array([True, True, False, False]), ev, -np.inf).max(axis=1)
    code = {"no_offer": 0, "content_nudge": 1, "discount_1m": 2, "plan_change": 3}
    got = ev[np.arange(len(cohort)), d.loc[cohort.msno, "chosen"].map(code)]
    assert np.allclose(got[down], free_best[down])


def test_empty_cohorts_and_zero_periods_fail_clearly(cohort, sim):
    with pytest.raises(ValueError, match="cohort is empty"):
        run(NoOffer(), cohort.subset(np.zeros(len(cohort), bool)), sim)
    with pytest.raises(ValueError, match="at least one period"):
        rollout(
            NoOffer(),
            cohort,
            sim,
            "central",
            periods=0,
            risk_threshold=0.15,
            budget_per_1000=0.0,
            seed=7,
            run_id="t",
        )
