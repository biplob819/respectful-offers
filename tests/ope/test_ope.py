import numpy as np
import pytest

from respectful_offers.ope.data import logs_from_pilot, period1_view, target_probabilities
from respectful_offers.ope.estimators import (
    Logs,
    SupportError,
    check_support,
    estimate,
    fit_reward_model,
    oracle_value,
)
from respectful_offers.policy.bandit import static_context
from respectful_offers.policy.baselines import (
    LoggingPolicy,
    NoOffer,
    RuleFollowingBaseline,
    SegmentOracle,
)
from respectful_offers.policy.rollout import rollout
from respectful_offers.sim.response import Tables, expected_reward_by_segment

DF = ("churn_risk", "auto_renew", "tenure_days", "listening_trend_30d", "price_30d")


def pilot(cohort, sim, seed=7):
    x, _ = static_context(cohort.features, cohort.churn_risk, DF)
    view = period1_view(cohort, sim, "central", 0.15, x)
    res = rollout(
        LoggingPolicy(),
        cohort,
        sim,
        "central",
        periods=1,
        risk_threshold=0.15,
        budget_per_1000=0.0,
        seed=seed,
        run_id="pilot",
    )
    return logs_from_pilot(cohort, res, x, view, "central"), view


def exact(cohort, sim):
    t = Tables.from_config(sim, "central")
    return expected_reward_by_segment(cohort.base, cohort.segment, cohort.price, t)


def test_ips_of_the_logger_itself_is_the_mean_reward(cohort, sim):
    logs, view = pilot(cohort, sim)
    target = target_probabilities(LoggingPolicy(), view)
    iv, ess = estimate(logs, target, "ips", blocks=100, resamples=500)
    assert iv.point == pytest.approx(logs.reward.mean(), rel=1e-6)
    assert ess == pytest.approx(len(logs.action))


def test_dr_with_a_perfect_reward_model_equals_the_oracle_up_to_noise(cohort, sim):
    logs, view = pilot(cohort, sim)
    q = exact(cohort, sim)  # the true conditional expectation
    target = target_probabilities(RuleFollowingBaseline(), view)
    iv, _ = estimate(logs, target, "dr", q=q, blocks=100, resamples=500)
    assert iv.lo <= oracle_value(target, q) <= iv.hi


@pytest.mark.parametrize("estimator", ["ips", "snips", "dr"])
def test_estimates_cover_the_oracle_on_one_pilot(cohort, sim, estimator):
    logs, view = pilot(cohort, sim)
    q = fit_reward_model(logs, seed=1) if estimator == "dr" else None
    for policy in (NoOffer(), RuleFollowingBaseline(), SegmentOracle()):
        target = target_probabilities(policy, view)
        iv, _ = estimate(logs, target, estimator, q=q, blocks=200, resamples=1000)
        truth = oracle_value(target, exact(cohort, sim))
        assert iv.lo <= truth <= iv.hi, (policy.name, estimator, iv, truth)


class Peaked(LoggingPolicy):
    """A stochastic target that leans hard on one action: heavy importance weights."""

    name = "logging"

    def probabilities(self, view):
        w = view.allowed * np.array([1.0, 8.0, 1.0, 1.0])
        return w / w.sum(axis=1, keepdims=True)


@pytest.mark.ope
def test_dr_and_snips_coverage_over_replicates_is_near_nominal(cohort, sim):
    """200 replicate pilots on the 4,000-member fixture: for every kind of target, 95%
    intervals cover the exact oracle value (members' own segments) 90–99% of the time and the
    mean signed error is below 1 NTD per member (OPE-04, D-36)."""
    truth_q = exact(cohort, sim)
    targets = {
        "no_offer": NoOffer(),
        "rule_following": RuleFollowingBaseline(),
        "segment_oracle": SegmentOracle(),
        "peaked": Peaked(),
    }
    reps = 200
    hits = {(t, e): 0 for t in targets for e in ("snips", "dr")}
    err = {(t, e): [] for t in targets for e in ("snips", "dr")}
    for r in range(reps):
        logs, view = pilot(cohort, sim, seed=1000 + r)
        q = fit_reward_model(logs, seed=r)
        for name, policy in targets.items():
            target = target_probabilities(policy, view)
            truth = oracle_value(target, truth_q)
            for est in ("snips", "dr"):
                iv, _ = estimate(
                    logs,
                    target,
                    est,
                    q=q if est == "dr" else None,
                    blocks=200,
                    resamples=400,
                    seed=r,
                )
                hits[name, est] += iv.lo <= truth <= iv.hi
                err[name, est].append(iv.point - truth)
    for key in hits:
        coverage = hits[key] / reps
        assert 0.90 <= coverage <= 0.99, (key, coverage)
        e = np.asarray(err[key])
        se = e.std(ddof=1) / np.sqrt(reps)
        # unbiased within 3.5 standard errors of the replicate mean (about 0.5 NTD here), and
        # never more than 1 NTD per member (D-36)
        assert abs(e.mean()) < min(1.0, 3.5 * se), (key, e.mean(), se)


def test_support_outside_the_logger_is_refused(cohort, sim):
    logs, view = pilot(cohort, sim)
    bad = np.zeros_like(view.allowed, dtype=float)
    bad[:, 2] = 1.0  # discount everyone, including at-risk members who could not be discounted
    assert (~view.allowed[:, 2]).any()
    with pytest.raises(SupportError):
        check_support(logs, bad)
    with pytest.raises(ValueError, match="distributions"):
        check_support(logs, np.zeros_like(bad))


def test_effective_sample_size_shrinks_for_a_peaked_target(cohort, sim):
    logs, view = pilot(cohort, sim)
    _, ess_uniform = estimate(
        logs, target_probabilities(LoggingPolicy(), view), "ips", blocks=50, resamples=200
    )
    _, ess_greedy = estimate(
        logs, target_probabilities(NoOffer(), view), "ips", blocks=50, resamples=200
    )
    assert ess_greedy < ess_uniform


def test_only_period_one_is_in_scope(cohort, sim):
    logs, _view = pilot(cohort, sim)
    with pytest.raises(ValueError, match="period 1"):
        Logs(logs.x, logs.allowed, logs.action, logs.propensity, logs.reward, logs.hashes, period=2)
    later = period1_view(cohort, sim, "central", 0.15)
    from dataclasses import replace

    with pytest.raises(ValueError, match="period 1"):
        target_probabilities(NoOffer(), replace(later, period=2))


def test_logs_must_come_from_the_logging_pilot(cohort, sim):
    x, _ = static_context(cohort.features, cohort.churn_risk, DF)
    view = period1_view(cohort, sim, "central", 0.15, x)
    res = rollout(
        NoOffer(),
        cohort,
        sim,
        "central",
        periods=1,
        risk_threshold=0.15,
        budget_per_1000=0.0,
        seed=1,
        run_id="x",
    )
    with pytest.raises(ValueError, match="logging pilot"):
        logs_from_pilot(cohort, res, x, view, "central")


def test_dr_needs_a_reward_model(cohort, sim):
    logs, view = pilot(cohort, sim)
    with pytest.raises(ValueError, match="reward-model"):
        estimate(logs, target_probabilities(NoOffer(), view), "dr")


def test_reward_model_is_cross_fitted(cohort, sim):
    logs, _ = pilot(cohort, sim)
    q1 = fit_reward_model(logs, seed=1)
    noisy = Logs(
        logs.x,
        logs.allowed,
        logs.action,
        logs.propensity,
        np.where(logs.hashes % np.uint64(2) == 0, logs.reward + 1000.0, logs.reward),
        logs.hashes,
    )
    q2 = fit_reward_model(noisy, seed=1)
    fold0 = (logs.hashes % np.uint64(2)) == 0
    # changing fold-0 rewards moves predictions for fold 1 (trained on fold 0) but not fold 0
    assert np.allclose(q1[fold0], q2[fold0]) and not np.allclose(q1[~fold0], q2[~fold0])


def test_logs_must_match_what_the_logger_did(cohort, sim):
    x, _ = static_context(cohort.features, cohort.churn_risk, DF)
    view = period1_view(cohort, sim, "central", 0.15, x)
    res = rollout(
        LoggingPolicy(),
        cohort,
        sim,
        "central",
        periods=1,
        risk_threshold=0.15,
        budget_per_1000=0.0,
        seed=7,
        run_id="pilot",
    )
    other = period1_view(cohort, sim, "central", 0.05, x)  # different allowed sets
    with pytest.raises(ValueError, match="allowed sets differ"):
        logs_from_pilot(cohort, res, x, other, "central")
    bad = res.decisions.copy()
    bad.loc[0, "propensity"] = 0.5 if bad.loc[0, "propensity"] != 0.5 else 0.25
    with pytest.raises(ValueError, match="1/\\|allowed\\|"):
        logs_from_pilot(
            cohort, type(res)(bad, res.outcomes, res.states, res.spend), x, view, "central"
        )
    short = res.decisions.iloc[1:]
    with pytest.raises(ValueError, match="every cohort member exactly once"):
        logs_from_pilot(
            cohort, type(res)(short, res.outcomes, res.states, res.spend), x, view, "central"
        )


def test_logs_refuse_mixed_runs_variants_and_misaligned_features(cohort, sim):
    x, _ = static_context(cohort.features, cohort.churn_risk, DF)
    view = period1_view(cohort, sim, "central", 0.15, x)

    def run(policy, seed=7, variant="central"):
        return rollout(
            policy,
            cohort,
            sim,
            variant,
            periods=1,
            risk_threshold=0.15,
            budget_per_1000=0.0,
            seed=seed,
            run_id=f"r{seed}",
        )

    log = run(LoggingPolicy())
    mixed = type(log)(log.decisions, run(NoOffer()).outcomes, log.states, log.spend)
    with pytest.raises(ValueError, match="logging pilot"):
        logs_from_pilot(cohort, mixed, x, view, "central")
    other_seed = type(log)(
        log.decisions, run(LoggingPolicy(), seed=8).outcomes, log.states, log.spend
    )
    with pytest.raises(ValueError, match="different runs"):
        logs_from_pilot(cohort, other_seed, x, view, "central")
    with pytest.raises(ValueError, match="variant"):
        logs_from_pilot(cohort, run(LoggingPolicy(), variant="conservative"), x, view, "central")
    with pytest.raises(ValueError, match="aligned"):
        logs_from_pilot(cohort, log, x[::-1], view, "central")


def test_logs_refuse_bad_arrays(cohort, sim):
    logs, _ = pilot(cohort, sim)
    base = dict(
        x=logs.x,
        allowed=logs.allowed,
        action=logs.action,
        propensity=logs.propensity,
        reward=logs.reward,
        hashes=logs.hashes,
    )
    bad = {
        "1/|allowed|": dict(propensity=np.full(len(logs.action), 0.9)),
        "misaligned": dict(propensity=logs.propensity[:1]),
        "action indices": dict(action=np.where(np.arange(len(logs.action)) == 0, -1, logs.action)),
        "distinct": dict(hashes=np.zeros(len(logs.action), np.uint64)),
        "finite": dict(
            x=np.where(np.arange(logs.x.size).reshape(logs.x.shape) == 0, np.nan, logs.x)
        ),
    }
    for match, change in bad.items():
        with pytest.raises(ValueError, match=match.replace("|", "\\|")):
            Logs(**{**base, **change})


def test_intervals_refuse_degenerate_bootstraps(cohort, sim):
    logs, view = pilot(cohort, sim)
    target = target_probabilities(RuleFollowingBaseline(), view)
    with pytest.raises(ValueError, match="bootstrap blocks"):
        estimate(logs, target, "snips", blocks=1, resamples=200)
    keep = logs.allowed.sum(axis=1) >= 2  # rows where another allowed action exists
    sub = Logs(
        logs.x[keep],
        logs.allowed[keep],
        logs.action[keep],
        logs.propensity[keep],
        logs.reward[keep],
        logs.hashes[keep],
    )
    other = np.array(
        [
            np.flatnonzero(al & (np.arange(4) != a))[0]
            for al, a in zip(sub.allowed, sub.action, strict=True)
        ]
    )
    zero = np.zeros((len(sub.action), 4))
    zero[np.arange(len(other)), other] = 1.0  # never the action the logger took
    with pytest.raises(SupportError, match="zero probability"):
        estimate(sub, zero, "ips", blocks=100, resamples=200)


def test_support_tolerances_are_exact(cohort, sim):
    logs, view = pilot(cohort, sim)
    t = target_probabilities(RuleFollowingBaseline(), view).copy()
    loose = t * (1 + 9e-6)
    with pytest.raises(ValueError, match="distributions"):
        check_support(logs, loose)
    tiny = t.copy()
    row = np.flatnonzero(~logs.allowed.all(axis=1))[0]
    col = np.flatnonzero(~logs.allowed[row])[0]
    tiny[row, col] = 1e-13
    tiny[row] /= tiny[row].sum()
    with pytest.raises(SupportError):
        check_support(logs, tiny)
