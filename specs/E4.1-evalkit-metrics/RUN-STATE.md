# E4.1 run state

**Now:** green

## History
- 2026-11-17 — spec written against EvalKit's frozen `metrics-1` (B5.3 spec at 7986e5c); gate severities ruled by the owner (OWNER D-52).
- 2026-11-17 — built: `offers metrics` (633 metrics from the real run), the validator, `configs/gates.yaml` (OWNER D-52) and `scripts/gate.py`; the real run passes with two age-band disparity warnings. EvalKit's efficiency block (B5.3 §1b) is not emitted: it measures model calls and this project makes none.
- 2026-11-17 — verifier round 1: no blocker; all 192 intervals copied exactly; claim orientation (a − b, a = bandit) confirmed against `scripts/prfaq.py`. Fixed: malformed gates (list op or disparity) crashed with exit 1 and no gate.json, now exit 2 with gate.json; disparity labelled with the variant it was computed on, not a hard-coded `central`; bare disparity keys refused instead of dropped; the scaling test now checks interval bounds and `n`; non-finite thresholds refused; claim and disparity gates name each variant and policy, so a missing one is an error, not a pass; gate.json truncates label values at 64 characters. Kept: `p_value` as `rate` (it lies in [0, 1]); policy intervals without `n` (block bootstrap, not binomial). Ruled: no second round.
- 2026-11-17 — converged twice; rows flipped green.
