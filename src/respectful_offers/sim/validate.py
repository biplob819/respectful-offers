"""Direction and ordering rules for simulator values (SIM-06).

Structure is checked by the schema (N1.1). These rules check meaning:
  - persuadables never lose from being shown an offer or engaging with a nudge;
  - sleeping dogs never gain from a commercial offer (exposure effect ≤ 0);
  - sure things and lost causes are barely moved by anything (|effect| ≤ 0.02);
  - variants named conservative, central and optimistic all exist, ordered as named on every
    acceptance rate and every persuadable effect;
  - the nudge costs nothing (nudge costs are not modelled).
A config that breaks a rule is refused unless it sets `allow_unconventional: true`, which the
report then stamps.
"""

from __future__ import annotations

from respectful_offers.schemas.simulator import OFFER_ACTIONS, SimulatorConfig

NEUTRAL = ("sure_thing", "lost_cause")
NEUTRAL_LIMIT = 0.02
ORDER = ("conservative", "central", "optimistic")


def direction_problems(cfg: SimulatorConfig) -> list[str]:
    out: list[str] = []
    missing = [o for o in ORDER if o not in cfg.variants]
    if missing:
        out.append(f"variants {missing} are missing: the three named variants are required")
    if cfg.actions.content_nudge.cost != 0:
        out.append("content_nudge.cost must be 0: nudge costs are not modelled (A2.2 verifier)")
    for name, v in sorted(cfg.variants.items()):
        for a in OFFER_ACTIONS:
            if v.exposure_effect[a]["persuadable"] < 0:
                out.append(f"{name}: persuadables lose from being shown {a}")
            for s in NEUTRAL:
                if abs(v.exposure_effect[a][s]) > NEUTRAL_LIMIT:
                    out.append(f"{name}: {s} moved by {v.exposure_effect[a][s]:+} when shown {a}")
        for a in ("discount_1m", "plan_change"):
            if v.exposure_effect[a]["sleeping_dog"] > 0:
                out.append(f"{name}: sleeping dogs gain from being shown {a}")
        if v.exposure_effect["content_nudge"]["sleeping_dog"] > NEUTRAL_LIMIT:
            out.append(f"{name}: sleeping dogs gain from being shown content_nudge")
        if v.acceptance_effect["content_nudge"]["sleeping_dog"] > NEUTRAL_LIMIT:
            out.append(f"{name}: sleeping dogs gain from engaging with content_nudge")
        eff = v.acceptance_effect["content_nudge"]
        if eff["persuadable"] < 0:
            out.append(f"{name}: persuadables lose from engaging with a nudge")
        for s in NEUTRAL:
            if abs(eff[s]) > NEUTRAL_LIMIT:
                out.append(f"{name}: {s} moved by {eff[s]:+} when engaging with a nudge")
    if all(o in cfg.variants for o in ORDER):
        lo, mid, hi = (cfg.variants[o] for o in ORDER)
        for a in OFFER_ACTIONS:
            for s in ("sure_thing", "persuadable", "lost_cause", "sleeping_dog"):
                if not lo.acceptance[a][s] <= mid.acceptance[a][s] <= hi.acceptance[a][s]:
                    out.append(f"variants not ordered on acceptance of {a} by {s}")
            if (
                not lo.exposure_effect[a]["persuadable"]
                <= mid.exposure_effect[a]["persuadable"]
                <= hi.exposure_effect[a]["persuadable"]
            ):
                out.append(f"variants not ordered on persuadable exposure effect of {a}")
        n = "content_nudge"
        if (
            not lo.acceptance_effect[n]["persuadable"]
            <= mid.acceptance_effect[n]["persuadable"]
            <= hi.acceptance_effect[n]["persuadable"]
        ):
            out.append("variants not ordered on the persuadable nudge effect")
    return out


def check(cfg: SimulatorConfig) -> list[str]:
    """Problems that refuse the config; empty when it passes or allows the unconventional."""
    problems = direction_problems(cfg)
    return [] if cfg.allow_unconventional else problems
