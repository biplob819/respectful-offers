"""The response simulator (Tech Spec §5.2, A2.2).

Each member has a calibrated churn risk ρ (from the real model), so their base renewal
probability is b = 1 − ρ in every period. A hidden segment (sure thing, persuadable, lost
cause, sleeping dog) is drawn once per member from the mix of their risk × trend cell. Each
period, given the chosen action:

    no_offer        renew ~ Bernoulli(b)
    content_nudge   engage with P = acceptance;
                    renew ~ Bernoulli(clip(b + exposure + engaged·acceptance_effect))
    discount_1m     accept with P = acceptance → renews at (1 − discount_fraction) × price;
                    else renew ~ Bernoulli(clip(b + exposure))
    plan_change     accept with P = acceptance → renews at price_ratio × price, for the rest of
                    the horizon; else renew ~ Bernoulli(clip(b + exposure))

A declined commercial offer can still lower renewal (sleeping dogs: negative exposure). Accepting
a commercial offer means renewing on it, so a sure thing who accepts is pure deadweight.
Revenue is what the member pays for the next period; `discount_cost` is what was forgone
against the list price. All randomness comes from common random numbers keyed by member,
period and stream, so every policy faces the same luck.

`expected_reward` gives the exact expected period-1 net revenue of each action for each member
(averaged over the segment mix of the member's cell): the oracle that OPE is scored against.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from respectful_offers.runtime.seeds import member_uniforms
from respectful_offers.schemas.rows import ACTIONS
from respectful_offers.schemas.simulator import CELLS, SEGMENTS, SimulatorConfig, Variant

NO_OFFER, NUDGE, DISCOUNT, PLAN = range(4)
OFFER_NAMES = ("content_nudge", "discount_1m", "plan_change")
RESPONSES = np.array(["not_shown", "accepted", "declined"], dtype=object)


@dataclass(frozen=True)
class Tables:
    """A variant as arrays: mix [cell, segment]; acceptance/exposure [action 1..3, segment]."""

    mix: np.ndarray
    acceptance: np.ndarray
    exposure: np.ndarray
    nudge_effect: np.ndarray
    discount_fraction: float
    price_ratio: float

    @classmethod
    def from_config(cls, cfg: SimulatorConfig, variant: str) -> Tables:
        if variant not in cfg.variants:
            raise KeyError(f"no simulator variant {variant!r}; have {sorted(cfg.variants)}")
        v: Variant = cfg.variants[variant]
        mix = np.array([[v.segment_mix[c][s] for s in SEGMENTS] for c in CELLS])
        acc = np.array([[v.acceptance[a][s] for s in SEGMENTS] for a in OFFER_NAMES])
        exp = np.array([[v.exposure_effect[a][s] for s in SEGMENTS] for a in OFFER_NAMES])
        eff = np.array([v.acceptance_effect["content_nudge"][s] for s in SEGMENTS])
        return cls(
            mix,
            acc,
            exp,
            eff,
            cfg.actions.discount_1m.discount_fraction,
            cfg.actions.plan_change.price_ratio,
        )


def cell_index(risk_band: np.ndarray, trend_band: np.ndarray) -> np.ndarray:
    keys = np.char.add(np.char.add(risk_band.astype(str), "."), trend_band.astype(str))
    lookup = {c: i for i, c in enumerate(CELLS)}
    try:
        return np.array([lookup[k] for k in keys], dtype=np.int64)
    except KeyError as exc:
        raise ValueError(f"unknown risk × trend cell {exc.args[0]!r}") from None


def draw_segments(seed: int, hashes: np.ndarray, cells: np.ndarray, t: Tables) -> np.ndarray:
    """One hidden segment per member, from the CRN stream 'segment' (period 0)."""
    u = member_uniforms(seed, hashes, 0, "segment")[:, 0]
    cum = np.cumsum(t.mix[cells], axis=1)
    seg = (u[:, None] >= cum).sum(axis=1)
    return np.minimum(seg, len(SEGMENTS) - 1)


@dataclass(frozen=True)
class Step:
    response: np.ndarray  # "not_shown" | "accepted" | "declined"
    renewed: np.ndarray
    revenue: np.ndarray
    discount_cost: np.ndarray
    plan_multiplier: np.ndarray  # after this period


def respond(
    *,
    seed: int,
    hashes: np.ndarray,
    period: int,
    base: np.ndarray,
    segment: np.ndarray,
    price: np.ndarray,
    plan_multiplier: np.ndarray,
    chosen: np.ndarray,
    t: Tables,
) -> Step:
    """One period of responses for active members (all arrays aligned)."""
    n = len(chosen)
    if not ((chosen >= 0) & (chosen < len(ACTIONS))).all():
        raise ValueError("chosen actions must be indexes into ACTIONS")
    if not (np.isfinite(base).all() and (base >= 0).all() and (base <= 1).all()):
        raise ValueError("base renewal probabilities must be finite and in [0, 1]")
    if not ((segment >= 0) & (segment < len(SEGMENTS))).all():
        raise ValueError("segments must be indexes into SEGMENTS")
    if not (np.isfinite(price).all() and (price >= 0).all()):
        raise ValueError("prices must be finite and non-negative")
    if ((chosen == PLAN) & (plan_multiplier < 1.0)).any():
        raise ValueError("a plan change is offered once, from the full plan")
    u_acc = member_uniforms(seed, hashes, period, "accept")[:, 0]
    u_ren = member_uniforms(seed, hashes, period, "renew")[:, 0]
    shown = chosen != NO_OFFER
    k = np.clip(chosen - 1, 0, 2)  # row into the offer tables (ignored when not shown)
    p_acc = np.where(shown, t.acceptance[k, segment], 0.0)
    accepted = shown & (u_acc < p_acc)
    exposure = np.where(shown, t.exposure[k, segment], 0.0)
    nudge_bonus = np.where((chosen == NUDGE) & accepted, t.nudge_effect[segment], 0.0)
    p_renew = np.clip(base + exposure + nudge_bonus, 0.0, 1.0)
    commercial_accept = accepted & ((chosen == DISCOUNT) | (chosen == PLAN))
    renewed = commercial_accept | (u_ren < p_renew)

    new_mult = np.where((chosen == PLAN) & accepted, t.price_ratio, plan_multiplier)
    pay_rate = new_mult * np.where((chosen == DISCOUNT) & accepted, 1.0 - t.discount_fraction, 1.0)
    revenue = np.where(renewed, price * pay_rate, 0.0)
    cost = np.where(renewed, price * (1.0 - pay_rate), 0.0)
    response = RESPONSES[np.where(~shown, 0, np.where(accepted, 1, 2))]
    assert len(response) == n
    return Step(response, renewed, revenue, cost, new_mult)


def _plan_ok(plan_multiplier: np.ndarray | None, n: int) -> tuple[np.ndarray, np.ndarray]:
    mult = np.ones(n) if plan_multiplier is None else np.asarray(plan_multiplier, dtype=float)
    return mult, mult >= 1.0  # a plan change is available once, from the full plan


def expected_reward(
    base: np.ndarray,
    cells: np.ndarray,
    price: np.ndarray,
    t: Tables,
    plan_multiplier: np.ndarray | None = None,
) -> np.ndarray:
    """Exact expected net revenue for one period, shape [n, 4], averaged over each cell's
    segment mix, for members on plan multiplier `plan_multiplier` (1 = full plan, the period-1
    state). A plan change is unavailable (−inf) once a member is on the cheaper plan."""
    mix = t.mix[cells]  # [n, S]
    b = base[:, None]
    mult, plan_ok = _plan_ok(plan_multiplier, len(base))
    paid = price * mult
    out = np.empty((len(base), len(ACTIONS)))
    out[:, NO_OFFER] = base * paid
    acc, exp = t.acceptance, t.exposure
    p_engaged = np.clip(b + exp[0] + t.nudge_effect, 0, 1)
    p_ignored = np.clip(b + exp[0], 0, 1)
    nudge = acc[0] * p_engaged + (1 - acc[0]) * p_ignored
    out[:, NUDGE] = paid * (mix * nudge).sum(axis=1)
    declined = np.clip(b + exp[1], 0, 1)
    out[:, DISCOUNT] = paid * (
        mix * (acc[1] * (1 - t.discount_fraction) + (1 - acc[1]) * declined)
    ).sum(axis=1)
    declined = np.clip(b + exp[2], 0, 1)
    plan = price * (mix * (acc[2] * t.price_ratio + (1 - acc[2]) * declined)).sum(axis=1)
    out[:, PLAN] = np.where(plan_ok, plan, -np.inf)
    return out


def expected_reward_by_segment(
    base: np.ndarray,
    segment: np.ndarray,
    price: np.ndarray,
    t: Tables,
    plan_multiplier: np.ndarray | None = None,
) -> np.ndarray:
    """Exact expected net revenue for one period when the segment is known (the segment
    oracle's view), for members on plan multiplier `plan_multiplier`."""
    b = base
    mult, plan_ok = _plan_ok(plan_multiplier, len(base))
    paid = price * mult
    acc = t.acceptance[:, segment]  # [3, n]
    exp = t.exposure[:, segment]
    out = np.empty((len(base), len(ACTIONS)))
    out[:, NO_OFFER] = b * paid
    engaged = np.clip(b + exp[0] + t.nudge_effect[segment], 0, 1)
    out[:, NUDGE] = paid * (acc[0] * engaged + (1 - acc[0]) * np.clip(b + exp[0], 0, 1))
    out[:, DISCOUNT] = paid * (
        acc[1] * (1 - t.discount_fraction) + (1 - acc[1]) * np.clip(b + exp[1], 0, 1)
    )
    plan = price * (acc[2] * t.price_ratio + (1 - acc[2]) * np.clip(b + exp[2], 0, 1))
    out[:, PLAN] = np.where(plan_ok, plan, -np.inf)
    return out
