import copy
import json
from typing import Any

import numpy as np
import pytest
import yaml

from harness_lib import ROOT
from respectful_offers.cli import main
from respectful_offers.runtime.seeds import member_hashes
from respectful_offers.schemas import ConfigError, load_simulator_config
from respectful_offers.schemas.simulator import CELLS, SEGMENTS
from respectful_offers.sim.prereg import PreregError, prereg_status, register, registered_hash
from respectful_offers.sim.response import (
    DISCOUNT,
    NO_OFFER,
    NUDGE,
    PLAN,
    Tables,
    cell_index,
    draw_segments,
    expected_reward,
    expected_reward_by_segment,
    respond,
)
from respectful_offers.sim.validate import direction_problems

CFG_PATH = ROOT / "configs" / "simulator.yaml"


@pytest.fixture(scope="module")
def cfg():
    return load_simulator_config(CFG_PATH)


def forced(cfg, accept: float) -> Tables:
    t = Tables.from_config(cfg, "central")
    return Tables(
        t.mix,
        np.full_like(t.acceptance, accept),
        t.exposure,
        t.nudge_effect,
        t.discount_fraction,
        t.price_ratio,
    )


def step(t, chosen, n=4, base=0.5, segment=1, mult=1.0, period=1):
    return respond(
        seed=1,
        hashes=member_hashes([f"M{i}" for i in range(n)]),
        period=period,
        base=np.full(n, base),
        segment=np.full(n, segment),
        price=np.full(n, 149.0),
        plan_multiplier=np.full(n, mult),
        chosen=np.full(n, chosen),
        t=t,
    )


def test_accepted_offers_renew_at_their_price(cfg):
    t = forced(cfg, 1.0)
    d = step(t, DISCOUNT)
    assert (
        d.renewed.all()
        and np.allclose(d.revenue, 149 * 0.5)
        and np.allclose(d.discount_cost, 149 * 0.5)
    )
    assert set(d.response) == {"accepted"}
    p = step(t, PLAN)
    assert np.allclose(p.revenue, 149 * 0.67) and np.allclose(p.plan_multiplier, 0.67)
    later = step(t, NO_OFFER, mult=0.67, period=2, base=1.0)
    assert np.allclose(later.revenue, 149 * 0.67) and np.allclose(later.discount_cost, 149 * 0.33)
    assert set(later.response) == {"not_shown"}


def test_declines_apply_exposure_and_engaged_nudges_add_their_effect(cfg):
    t = forced(cfg, 0.0)
    d = step(t, DISCOUNT, n=20000, base=0.5, segment=3)  # sleeping dogs
    assert set(d.response) == {"declined"}
    assert abs(d.renewed.mean() - (0.5 + t.exposure[1, 3])) < 0.015
    t1 = forced(cfg, 1.0)
    nd = step(t1, NUDGE, n=20000, base=0.5, segment=1)  # engaged persuadables
    assert abs(nd.renewed.mean() - (0.5 + t1.exposure[0, 1] + t1.nudge_effect[1])) < 0.015


def test_no_offer_renews_at_one_minus_risk_and_sleeping_dogs_lose_from_offers(cfg):
    t = Tables.from_config(cfg, "central")
    base = np.full(50000, 0.8)
    common: dict[str, Any] = dict(
        seed=3,
        hashes=member_hashes([f"X{i}" for i in range(50000)]),
        period=1,
        base=base,
        price=np.full(50000, 149.0),
        plan_multiplier=np.ones(50000),
        t=t,
    )
    none = respond(segment=np.full(50000, 3), chosen=np.full(50000, NO_OFFER), **common)
    disc = respond(segment=np.full(50000, 3), chosen=np.full(50000, DISCOUNT), **common)
    assert abs(none.renewed.mean() - 0.8) < 0.01
    assert disc.renewed[disc.response == "declined"].mean() < none.renewed.mean() - 0.03


def test_simulator_yaml_has_three_explained_variants_awaiting_the_owner(cfg):
    assert set(cfg.variants) == {"conservative", "central", "optimistic"}
    assert direction_problems(cfg) == []
    text = CFG_PATH.read_text(encoding="utf-8")
    assert "NOT yet confirmed by the owner" in text
    for word in (
        "risk_bands",
        "segment_mix",
        "acceptance",
        "exposure_effect",
        "conservative",
        "optimistic",
    ):
        assert f"#   {word}" in text or f"# {word}" in text or f"#   {word} " in text


def test_draws_are_common_random_numbers(cfg):
    t = Tables.from_config(cfg, "central")
    ids = [f"M{i}" for i in range(500)]
    h = member_hashes(ids)
    args: dict[str, Any] = dict(
        seed=9,
        period=2,
        base=np.full(500, 0.6),
        segment=np.full(500, 1),
        price=np.full(500, 149.0),
        plan_multiplier=np.ones(500),
        t=t,
    )
    a = respond(hashes=h, chosen=np.full(500, NO_OFFER), **args)
    order = np.random.default_rng(0).permutation(500)
    b = respond(
        hashes=h[order], chosen=np.full(500, NO_OFFER), **{**args, "base": args["base"][order]}
    )
    assert (b.renewed == a.renewed[order]).all()
    c = respond(hashes=h, chosen=np.full(500, DISCOUNT), **args)  # another policy's choice
    refused = c.response == "declined"
    # same renewal draw per member: a declining persuadable (positive exposure effect) renews
    # whenever they would have renewed with no offer
    assert refused.any() and (c.renewed[refused] >= a.renewed[refused]).all()
    cells = cell_index(np.array(["high"] * 500), np.array(["declining"] * 500))
    s1 = draw_segments(9, h, cells, t)
    s2 = draw_segments(9, h[order], cells[order], t)
    assert (s2 == s1[order]).all()


def test_the_oracle_matches_monte_carlo(cfg):
    t = Tables.from_config(cfg, "central")
    n = 200_000
    rng = np.random.default_rng(1)
    h = member_hashes([f"O{i}" for i in range(n)])
    risk_band = rng.choice(np.array(["low", "medium", "high"]), n)
    trend = rng.choice(np.array(["stable", "declining"]), n)
    cells = cell_index(risk_band, trend)
    base = rng.uniform(0.4, 0.98, n)
    price = rng.choice([99.0, 149.0], n)
    seg = draw_segments(5, h, cells, t)
    exact = expected_reward(base, cells, price, t)
    for action in range(4):
        out = respond(
            seed=5,
            hashes=h,
            period=1,
            base=base,
            segment=seg,
            price=price,
            plan_multiplier=np.ones(n),
            chosen=np.full(n, action),
            t=t,
        )
        se = out.revenue.std() / np.sqrt(n)
        assert abs(out.revenue.mean() - exact[:, action].mean()) < 3 * se + 1e-9, action
    by_seg = np.stack(
        [expected_reward_by_segment(base, np.full(n, s), price, t) for s in range(len(SEGMENTS))]
    )
    mixed = (t.mix[cells].T[:, :, None] * by_seg).sum(axis=0)
    assert np.allclose(mixed, exact)


def test_preregistration_freezes_the_file(tmp_path):
    y = tmp_path / "sim.yaml"
    y.write_bytes(CFG_PATH.read_bytes())
    pre = tmp_path / "prereg.md"
    with pytest.raises(PreregError, match="no simulator is pre-registered"):
        prereg_status(y, pre, exploratory=False)
    digest = register(y, pre, scope="synthetic")
    assert registered_hash(pre) == digest and prereg_status(y, pre, False) == "preregistered"
    y.write_text(y.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    with pytest.raises(PreregError, match="changed since it was pre-registered"):
        prereg_status(y, pre, False)
    assert prereg_status(y, pre, True) == "exploratory"
    text = pre.read_text(encoding="utf-8")
    assert "Pre-registered success criteria" in text and "Holm" in text


def _bad(tmp_path, mutate):
    data = yaml.safe_load(CFG_PATH.read_text(encoding="utf-8"))
    mutate(data)
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda d: d["variants"]["central"]["exposure_effect"]["discount_1m"].update(
                persuadable=-0.01
            ),
            "central: persuadables lose",
        ),
        (
            lambda d: d["variants"]["central"]["exposure_effect"]["plan_change"].update(
                sleeping_dog=0.02
            ),
            "central: sleeping dogs gain",
        ),
        (
            lambda d: d["variants"]["optimistic"]["exposure_effect"]["content_nudge"].update(
                sure_thing=0.05
            ),
            "optimistic: sure_thing moved",
        ),
        (
            lambda d: d["variants"]["conservative"]["acceptance"]["discount_1m"].update(
                persuadable=0.9
            ),
            "not ordered on acceptance",
        ),
    ],
)
def test_direction_rules_refuse_with_a_named_message(tmp_path, mutate, match):
    p = _bad(tmp_path, mutate)
    assert any(match in m for m in direction_problems(load_simulator_config(p)))
    with pytest.raises(ConfigError, match=match):
        register(p, tmp_path / "pre.md", scope="synthetic")
    allowed = _bad(tmp_path, lambda d: (mutate(d), d.update(allow_unconventional=True)))
    register(allowed, tmp_path / "pre2.md", scope="synthetic")


def test_cli_prereg_writes_the_registration(tmp_path, capsys):
    out = tmp_path / "prereg.md"
    log = tmp_path / "decisions.md"
    log.write_text("# log\n", encoding="utf-8")
    args = [
        "prereg",
        "--simulator",
        str(CFG_PATH),
        "--out",
        str(out),
        "--decisions",
        str(log),
        "--json",
    ]
    assert main(args) == 0
    assert "| PREREG |" in log.read_text(encoding="utf-8")
    assert json.loads(capsys.readouterr().out)["sha256"] == registered_hash(out)
    assert len(CELLS) == 6 and copy.copy(SEGMENTS) == SEGMENTS


def test_a_plan_change_is_offered_once_from_the_full_plan(cfg):
    t = forced(cfg, 1.0)
    with pytest.raises(ValueError, match="offered once"):
        step(t, PLAN, mult=0.67)
    ev = expected_reward_by_segment(
        np.full(2, 0.7), np.full(2, 1), np.full(2, 100.0), t, plan_multiplier=np.array([1.0, 0.67])
    )
    assert np.isfinite(ev[0, PLAN]) and ev[1, PLAN] == -np.inf
    assert ev[1, NO_OFFER] == pytest.approx(0.7 * 67.0)  # revenue on the cheaper plan


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda d: d["actions"]["content_nudge"].update(cost=5.0), "nudge costs are not modelled"),
        (lambda d: d["variants"].pop("central"), "are missing"),
        (
            lambda d: d["variants"]["central"]["acceptance_effect"]["content_nudge"].update(
                sleeping_dog=0.3
            ),
            "sleeping dogs gain from engaging",
        ),
    ],
)
def test_round_one_rule_gaps_are_closed(tmp_path, mutate, match):
    p = _bad(tmp_path, mutate)
    assert any(match in m for m in direction_problems(load_simulator_config(p)))


def test_a_synthetic_registration_never_certifies_real_data(tmp_path):
    y = tmp_path / "sim.yaml"
    y.write_bytes(CFG_PATH.read_bytes())
    pre, log = tmp_path / "prereg.md", tmp_path / "decisions.md"
    log.write_text("# Decision log\n", encoding="utf-8")
    register(y, pre, scope="synthetic", decisions_path=log)
    assert prereg_status(y, pre, False, data_source="synthetic") == "preregistered"
    for real in ("kaggle", "local", "your_table"):  # every non-synthetic source is real data
        with pytest.raises(PreregError, match="synthetic data only"):
            prereg_status(y, pre, False, data_source=real)
    with pytest.raises(PreregError, match="pass a reason"):
        register(y, pre, scope="real", decisions_path=log)
    register(y, pre, scope="real", decisions_path=log, replace_reason="owner confirmed the values")
    assert prereg_status(y, pre, False, data_source="kaggle") == "preregistered"
    text = log.read_text(encoding="utf-8")
    assert (
        text.count("| PREREG |") == 2 and "owner confirmed the values" in text
    ) or "first registration" in text
    with pytest.raises(PreregError, match="does not exist"):
        prereg_status(tmp_path / "missing.yaml", pre, True)


def test_unconventional_registrations_are_stamped(tmp_path):
    p = _bad(
        tmp_path,
        lambda d: (
            d["variants"]["central"]["exposure_effect"]["discount_1m"].update(persuadable=-0.01),
            d.update(allow_unconventional=True),
        ),
    )
    register(p, tmp_path / "pre.md", scope="synthetic")
    assert "allow_unconventional" in (tmp_path / "pre.md").read_text(encoding="utf-8")


def test_respond_refuses_bad_segments_and_prices(cfg):
    t = Tables.from_config(cfg, "central")
    with pytest.raises(ValueError, match="segments"):
        step(t, NO_OFFER, segment=-1)
    with pytest.raises(ValueError, match="prices"):
        respond(
            seed=1,
            hashes=member_hashes(["a"]),
            period=1,
            base=np.array([0.5]),
            segment=np.array([0]),
            price=np.array([np.nan]),
            plan_multiplier=np.ones(1),
            chosen=np.array([0]),
            t=t,
        )
