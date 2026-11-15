import json
import math
from typing import Any

import numpy as np
import pandas as pd
import pytest

from respectful_offers.policy.audit import audit
from respectful_offers.policy.bandit import (
    Posterior,
    ThompsonBandit,
    greedy_value,
    static_context,
    train_bandit,
)
from respectful_offers.policy.baselines import View
from respectful_offers.policy.rollout import rollout
from respectful_offers.sim.response import Tables, expected_reward_by_segment

DF = (
    "churn_risk",
    "auto_renew",
    "tenure_days",
    "listening_trend_30d",
    "price_30d",
    "nudged",
    "declined",
)
KW: dict[str, Any] = dict(prior_precision=1.0, noise_variance=0.2)


def make(cohort, **kw):
    x, cols = static_context(cohort.features, cohort.churn_risk, DF)
    return ThompsonBandit(x, cols, DF, **{**KW, **kw}), x


COLS = ("churn_risk", "auto_renew", "tenure_days", "listening_trend_30d", "price_30d")


def view(cohort, sim, allowed=None, ctx=None, cols=COLS):
    n = len(cohort)
    return View(
        1,
        3,
        np.ones((n, 4), bool) if allowed is None else allowed,
        cohort.churn_risk,
        cohort.price,
        np.zeros(n, bool),
        np.zeros((n, 4), bool),
        ctx if ctx is not None else np.zeros((n, 0)),
        0.15,
        np.array([True, True, False, False]),
        cohort.base,
        cohort.segment,
        Tables.from_config(sim, "central"),
        context_columns=tuple(cols) if ctx is not None else (),
    )


def test_posterior_equals_closed_form_bayesian_ridge(cohort, sim):
    b, x = make(cohort)
    v = view(cohort, sim, ctx=x)
    rng = np.random.default_rng(0)
    chosen = rng.integers(0, 4, len(cohort))
    revenue = rng.uniform(0, 1, len(cohort)) * cohort.price
    b.observe(v, chosen, revenue)
    X = b.features(v)
    y = revenue / cohort.price
    for a in range(4):
        m = chosen == a
        A = np.eye(X.shape[1]) * 1.0 + X[m].T @ X[m] / 0.2
        mu = np.linalg.solve(A, X[m].T @ y[m] / 0.2)
        assert np.allclose(b.posterior.precision[a], A) and np.allclose(b.posterior.mu[a], mu)


@pytest.mark.parametrize(
    "bad",
    [
        dict(prior_precision=0.0),
        dict(noise_variance=-1.0),
        dict(prior_precision=float("nan")),
        dict(integration_nodes=5),
        dict(integration_nodes=10_000),
        dict(integration_nodes=32.0),
        dict(prior_precision=True),
        dict(support_floor=0.3),
        dict(support_floor=0.0),
    ],
)
def test_bad_hyperparameters_are_refused(cohort, bad):
    with pytest.raises(ValueError):
        make(cohort, **bad)


@pytest.fixture(scope="module")
def trained(cohort, sim):
    return train_bandit(
        cohort,
        sim,
        "central",
        decision_features=DF,
        risk_threshold=0.15,
        budget_per_1000=3000.0,
        periods=3,
        epochs=2,
        **KW,
        seed=11,
    )


def test_training_freezes_and_round_trips(cohort, sim, trained):
    before = trained.posterior.to_json()
    x, _ = static_context(cohort.features, cohort.churn_risk, DF)
    rollout(
        trained,
        cohort,
        sim,
        "central",
        periods=3,
        risk_threshold=0.15,
        budget_per_1000=3000.0,
        seed=1,
        run_id="e",
        context=x,
        context_columns=COLS,
    )
    assert trained.posterior.to_json() == before
    again = Posterior.from_json(before)
    assert again.to_json() == before
    twin = train_bandit(
        cohort,
        sim,
        "central",
        decision_features=DF,
        risk_threshold=0.15,
        budget_per_1000=3000.0,
        periods=3,
        epochs=2,
        **KW,
        seed=11,
    )
    assert twin.posterior.to_json() == before


def _scripted(cohort, means, sds, floor=0.001):
    """A bandit whose every member has the given score means and sds (intercept only)."""
    b, x = make(cohort, support_floor=floor)
    b.posterior.mu[:] = 0.0
    b.posterior.mu[:, 0] = means
    cov = np.tile(np.eye(b.posterior.dim) * 1e-14, (4, 1, 1))
    cov[:, 0, 0] = np.square(sds)
    b.posterior.precision[:] = np.linalg.inv(cov)
    return b, x


def _exact(means, sds, allowed):
    from scipy.integrate import quad
    from scipy.stats import norm

    out = np.zeros(4)
    for a in np.flatnonzero(allowed):
        others = [b for b in np.flatnonzero(allowed) if b != a]

        def f(t, a=a, others=others):
            return norm.pdf(t, means[a], sds[a]) * np.prod(
                [norm.cdf(t, means[b], sds[b]) for b in others]
            )

        lo, hi = means[a] - 12 * sds[a], means[a] + 12 * sds[a]
        out[a] = quad(f, lo, hi, limit=400, points=[means[b] for b in others])[0]
    return out / out.sum()


def test_probabilities_match_the_two_action_formula(cohort, sim):
    b, x = _scripted(cohort, [0.60, 0.55, 0.0, 0.0], [0.05, 0.08, 1.0, 1.0], floor=1e-9)
    allowed = np.zeros((len(cohort), 4), bool)
    allowed[:, :2] = True
    p = b.probabilities(view(cohort, sim, allowed, x))
    expected = 0.5 * (1 + math.erf((0.60 - 0.55) / math.sqrt(0.05**2 + 0.08**2) / math.sqrt(2)))
    assert np.abs(p[:, 0] - expected).max() < 1e-3
    assert (p[:, 2:] == 0).all() and np.allclose(p.sum(axis=1), 1, rtol=0, atol=1e-12)


@pytest.mark.parametrize("seed", range(6))
def test_probabilities_match_numerical_integration_for_three_and_four_actions(seed):
    from respectful_offers.policy.bandit import win_probabilities

    rng = np.random.default_rng(seed)
    for _ in range(25):
        means = rng.normal(0.5, 0.1, 4)
        sds = np.exp(rng.uniform(np.log(0.002), np.log(0.3), 4))  # sds up to 150x apart
        allowed = np.ones(4, bool)
        allowed[rng.integers(1, 4)] = rng.uniform() < 0.5
        got = win_probabilities(means[None], sds[None], allowed[None], 32)[0]
        assert np.abs(got - _exact(means, sds, allowed)).max() < 2e-3


def test_the_support_floor_holds_after_normalising(cohort, sim):
    floor = 1 / 800
    b, x = _scripted(cohort, [0.9, 0.2, 0.25, 0.22], [0.01, 0.01, 0.01, 0.01], floor=floor)
    p = b.probabilities(view(cohort, sim, None, x))
    assert p.min() >= floor - 1e-15 and np.allclose(p.sum(axis=1), 1, rtol=0, atol=1e-12)
    assert np.allclose(p[:, 1:], floor)  # the floor really binds here


def test_propensity_is_the_probability_of_the_requested_action(cohort, sim, trained):
    x, _ = static_context(cohort.features, cohort.churn_risk, DF)
    r = rollout(
        trained,
        cohort,
        sim,
        "central",
        periods=1,
        risk_threshold=0.15,
        budget_per_1000=1e9,
        seed=2,
        run_id="p",
        context=x,
        context_columns=COLS,
    )
    d = r.decisions.set_index("msno").loc[cohort.msno]
    code = {"no_offer": 0, "content_nudge": 1, "discount_1m": 2, "plan_change": 3}
    # same allowed sets as the rollout at period 1 with threshold 0.15
    from respectful_offers.policy.respect import allowed_actions

    allowed = allowed_actions(
        in_holdout=np.zeros(len(cohort), bool),
        churn_risk=cohort.churn_risk,
        nudged=np.zeros(len(cohort), bool),
        declined=np.zeros((len(cohort), 4), bool),
        risk_threshold=0.15,
    )
    p = trained.probabilities(view(cohort, sim, allowed, x))
    want = p[np.arange(len(cohort)), d["requested"].map(code).to_numpy()]
    assert np.array_equal(d["propensity"].to_numpy(), want)


def test_no_offer_when_no_offer_dominates(cohort, sim):
    b, x = make(cohort)
    b.posterior.mu[:] = 0.0
    b.posterior.mu[0, 0] = 1.0
    b.posterior.precision[:] = np.tile(np.eye(b.posterior.dim) * 1e8, (4, 1, 1))
    p = b.probabilities(view(cohort, sim, None, x))
    picks = b.choose(p, np.random.default_rng(0).uniform(size=len(p)))
    assert (picks == 0).mean() > 0.99


def test_trained_bandit_reports_a_no_offer_share_and_exploration(cohort, sim, trained):
    x, _ = static_context(cohort.features, cohort.churn_risk, DF)
    d = rollout(
        trained,
        cohort,
        sim,
        "central",
        periods=3,
        risk_threshold=0.15,
        budget_per_1000=3000.0,
        seed=4,
        run_id="s",
        context=x,
        context_columns=COLS,
    ).decisions
    share = (d["chosen"] == "no_offer").mean()
    # well above what the support floor alone would give (R5 is learned, not a floor artefact)
    assert 0.05 < share < 1
    rate = trained.summary()["exploration_rate"]
    assert rate is not None and 0 < rate < 1


def test_learning_curve_improves_and_stays_under_the_oracle(cohort, sim, trained):
    curve = trained.posterior.learning_curve
    assert [c["period"] for c in curve] == [0, 3, 6]
    gain = curve[-1]["value"] - curve[0]["value"]
    assert gain > 0.5  # learning is real: about 1.5 NTD per member on this cohort
    t = Tables.from_config(sim, "central")
    from respectful_offers.policy.respect import allowed_actions

    n = len(cohort)
    allowed = allowed_actions(
        in_holdout=np.zeros(n, bool),
        churn_risk=cohort.churn_risk,
        nudged=np.zeros(n, bool),
        declined=np.zeros((n, 4), bool),
        risk_threshold=0.15,
    )
    ev = expected_reward_by_segment(cohort.base, cohort.segment, cohort.price, t)
    oracle = np.where(allowed, ev, -np.inf).max(axis=1).mean()  # the respectful oracle
    assert all(c["value"] <= oracle + 1e-9 for c in curve)
    assert greedy_value(trained, cohort, sim, "central", 0.15) == pytest.approx(curve[-1]["value"])


def test_context_is_allow_listed_and_audits_clean(cohort, sim, trained):
    x, cols = static_context(cohort.features, cohort.churn_risk, DF)
    with pytest.raises(ValueError, match="R7"):
        ThompsonBandit(x, [*cols, "gender"], (*DF, "gender"), **KW)
    with pytest.raises(ValueError, match="R7"):
        ThompsonBandit(x, cols, ("churn_risk",), **KW)
    for proxy in ("city_id", "userGender", "registered_via_code"):  # proxies, not just names
        with pytest.raises(ValueError, match="R7"):
            ThompsonBandit(np.hstack([x, x[:, :1]]), [*cols, proxy], (*DF, proxy), **KW)
    r = rollout(
        trained,
        cohort,
        sim,
        "central",
        periods=3,
        risk_threshold=0.15,
        budget_per_1000=3000.0,
        seed=5,
        run_id="a",
        context=x,
        context_columns=COLS,
    )
    rep = audit(
        r.decisions,
        r.outcomes,
        churn_risk=pd.Series(cohort.churn_risk, index=cohort.msno),
        holdout=pd.Series(False, index=cohort.msno),
        risk_threshold=0.15,
        context_columns={"bandit": trained.context_columns},
        allow_list=DF,
    )
    assert rep.violations("bandit", "central") == {"R1": 0, "R2": 0, "R3": 0, "R7": 0, "R8": 0}


def test_choice_probabilities_are_a_function_of_the_member_alone(cohort, sim, trained):
    """Same view twice gives the same probabilities, and dropping members does not change
    anyone else's: probabilities are exact integrals, with no random draws."""
    x, _ = static_context(cohort.features, cohort.churn_risk, DF)
    v = view(cohort, sim, None, x)
    p1 = trained.probabilities(v)
    assert np.array_equal(p1, trained.probabilities(v))
    keep = np.arange(len(cohort)) % 2 == 0
    sub = cohort.subset(keep)
    p_sub = trained.probabilities(view(sub, sim, None, x[keep]))
    assert np.array_equal(p1[keep], p_sub)


def test_a_frozen_posterior_never_updates_and_is_never_shared(cohort, sim, trained):
    x, cols = static_context(cohort.features, cohort.churn_risk, DF)
    text = trained.posterior.to_json()
    reloaded = ThompsonBandit(x, cols, DF, **KW, posterior=Posterior.from_json(text))
    assert reloaded.posterior.frozen and not reloaded.learning
    rollout(
        reloaded,
        cohort,
        sim,
        "central",
        periods=2,
        risk_threshold=0.15,
        budget_per_1000=3000.0,
        seed=9,
        run_id="f",
        context=x,
        context_columns=COLS,
    )
    assert reloaded.posterior.to_json() == text
    thawed = Posterior.from_json(text)
    thawed.frozen = False
    other = ThompsonBandit(x, cols, DF, **KW, posterior=thawed)
    rollout(
        other,
        cohort,
        sim,
        "central",
        periods=1,
        risk_threshold=0.15,
        budget_per_1000=3000.0,
        seed=9,
        run_id="g",
        context=x,
        context_columns=COLS,
    )
    assert other.posterior.trained_periods == trained.posterior.trained_periods + 1
    assert thawed.trained_periods == trained.posterior.trained_periods  # a copy was updated
    assert trained.posterior.to_json() == text


def test_a_context_in_another_shape_or_order_is_refused(cohort, sim, trained):
    x, cols = static_context(cohort.features, cohort.churn_risk, DF)
    with pytest.raises(ValueError, match="context must be"):
        trained.probabilities(view(cohort, sim, None, x[:, ::-1][:, :-1], cols=COLS[:-1]))
    swapped = (COLS[1], COLS[0], *COLS[2:])  # same shape, columns in another order
    with pytest.raises(ValueError, match="not the posterior's"):
        trained.probabilities(view(cohort, sim, None, x[:, [1, 0, 2, 3, 4]], cols=swapped))
    with pytest.raises(ValueError, match="not the posterior's"):
        trained.probabilities(view(cohort, sim, None, x, cols=()))  # names must travel too
    with pytest.raises(ValueError, match="trained on columns"):
        ThompsonBandit(x[:, ::-1], cols[::-1], DF, **KW, posterior=trained.posterior)
    with pytest.raises(ValueError, match="finite"):
        bad = x.copy()
        bad[0, 0] = np.nan
        trained.probabilities(view(cohort, sim, None, bad))
    assert np.array_equal(trained.context_for(cohort.features, cohort.churn_risk), x)


def test_nan_features_are_refused_before_training(cohort):
    f = cohort.features.copy()
    f.loc[0, "tenure_days"] = np.nan
    with pytest.raises(ValueError, match="finite"):
        static_context(f, cohort.churn_risk, DF)


@pytest.mark.parametrize(
    "change, match",
    [
        (dict(support_floor=0.3), "support_floor"),
        (dict(support_floor=-0.1), "support_floor"),
        (dict(integration_nodes=0), "integration_nodes"),
        (dict(integration_nodes=100_000), "integration_nodes"),
        (dict(integration_nodes=8), "integration_nodes"),
        (dict(frozen="false"), "true or false"),
    ],
)
def test_a_tampered_posterior_artifact_is_refused(trained, change, match):
    d = json.loads(trained.posterior.to_json())
    d.update(change)
    with pytest.raises(ValueError, match=match):
        Posterior.from_json(json.dumps(d))


def test_bad_posterior_arrays_and_old_artifacts_are_refused(trained):
    d = json.loads(trained.posterior.to_json())
    for key, value, match in (
        ("mu", [[float("nan")] * len(d["mu"][0])] * 4, "finite"),
        ("scale", [0.0] * len(d["scale"]), "positive"),
        ("mean", d["mean"][:-1], "shape"),
    ):
        bad = {**d, key: value}
        with pytest.raises(ValueError, match=match):
            Posterior.from_json(json.dumps(bad))
    old = {k: v for k, v in d.items() if k not in ("frozen", "integration_nodes", "support_floor")}
    with pytest.raises(ValueError, match="predates D-35"):
        Posterior.from_json(json.dumps(old))


def test_settings_that_disagree_with_a_loaded_posterior_are_refused(cohort, trained):
    x, cols = static_context(cohort.features, cohort.churn_risk, DF)
    clashes: list[dict[str, Any]] = [
        dict(integration_nodes=256),
        dict(support_floor=0.05),
        dict(noise_variance=99.0),
    ]
    for clash in clashes:
        with pytest.raises(ValueError, match="disagree"):
            ThompsonBandit(x, cols, DF, posterior=trained.posterior, **clash)
    ThompsonBandit(
        x, cols, DF, posterior=trained.posterior, integration_nodes=32
    )  # agreeing is fine


def test_non_finite_moments_are_refused_not_made_uniform():
    from respectful_offers.policy.bandit import win_probabilities

    allowed = np.ones((1, 4), bool)
    for mean, sd in (
        ([[np.inf, 0.5, 0.4, 0.3]], [[0.1] * 4]),
        ([[np.nan, 0.5, 0.4, 0.3]], [[0.1] * 4]),
        ([[0.6, 0.5, 0.4, 0.3]], [[0.0, 0.1, 0.1, 0.1]]),
    ):
        with pytest.raises(ValueError, match=r"finite|positive"):
            win_probabilities(np.array(mean), np.array(sd), allowed, 32)
    with pytest.raises(ValueError, match="at least one allowed"):
        win_probabilities(np.zeros((1, 4)), np.ones((1, 4)), np.zeros((1, 4), bool), 32)


def test_edits_to_the_precision_take_effect_immediately(cohort, sim):
    b, x = make(cohort)
    v = view(cohort, sim, None, x)
    before = b.probabilities(v)
    b.posterior.mu[1, 0] = 0.3
    b.posterior.precision[:] *= 100.0  # no stale covariance cache
    assert not np.allclose(before, b.probabilities(v))
