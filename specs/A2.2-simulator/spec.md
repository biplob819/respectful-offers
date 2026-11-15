# A2.2 — Response simulator

**Wave 2. Depends on:** A2.1, N1.3. **Unblocks:** A2.4.

## Goal
Offer responses that the data cannot supply, simulated from explicit, pre-registered assumptions in which "no offer" is sometimes the right answer (sleeping dogs) and the bandit has something to learn (segments hidden behind real features), with an exact oracle to score estimators against (Tech Spec §5, D-1, D-2, D-3, C1, C2, C6).

## Outputs (`respectful_offers.sim`)
- `response.py`: `Tables.from_config`, `cell_index`, `draw_segments`, `respond` (one period, CRN draws keyed by member, period and stream), `expected_reward` (exact period-1 oracle per member and action), `expected_reward_by_segment` (the segment oracle's view).
- `validate.py`: direction and ordering rules (SIM-06).
- `prereg.py`: `register`, `registered_hash`, `prereg_status`; CLI `offers prereg`.
- `configs/simulator.yaml`: three variants with recommended starting values and their rationale in comments, marked as not yet confirmed by the owner.

## Rules
- Base renewal is 1 − calibrated risk; accepting a commercial offer means renewing on it; a plan change lasts the rest of the horizon; revenue is what is paid; discount cost is what is forgone against list price.
- The owner confirms or changes the values before the real-data run (A2.8); until then the registration's scope is "synthetic runs only".

## Out of scope
- The rollout engine and policies (A2.4).
