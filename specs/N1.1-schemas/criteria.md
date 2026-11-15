# N1.1 acceptance criteria

**SCH-01 — row contracts**
- Each row model accepts a valid row and rejects: unknown fields, non-finite floats, an action outside `ACTIONS`, a chosen action outside `allowed`, a downgrade that kept the action, propensity 0 or above 1, unsorted or duplicated `declined`, `no_offer` in `declined`, a non-renewal with revenue or cost.
- Models are strict (no string-to-number, bool-to-number, set-to-tuple or int-to-date coercion), deeply immutable, hashable, picklable and deep-copyable; a decision may only request an allowed action.

**SCH-02 — simulator config schema**
- The fixture loads. Missing cell, missing segment, missing action, a mix summing to 0.99, a probability of 1.2, an effect of 1.5, and non-increasing risk cuts are each refused with the offending key in the message.

**SCH-03 — run config and loader**
- The fixture loads. Overlapping or gapped cohort buckets, a protected attribute in `decision_features`, a negative budget, a NaN, an unknown key, a duplicate YAML key, a directory and a non-UTF-8 file each raise `ConfigError` naming the file and key. A budget of 0 loads as 0.

**SCH-04 — summary schemas**
- The run-summary fixture loads. `simulated` must be true; an interval with lo > hi, a cost ratio present with non-positive incremental retention (or absent with positive), duplicate policy × variant rows, and comparisons or OPE rows naming a policy not in the summary are refused.

**SCH-05 — column contracts**
- `check_frame` passes a valid frame and raises `ContractError` naming stage and column for: a missing, extra or duplicated column, a wrong dtype (dates must be calendar dates; action lists must be ordered sequences of actions), a null in a non-null column, a value out of range, a value outside an allowed set.
- Every respect shape a row model enforces is also a table rule: declined sets, allowed sets holding `no_offer`, chosen and requested within allowed, the downgrade flag, and no revenue without renewal. Each row table's contract columns equal its row model's fields (checked against both, so either drifting fails).

**SCH-06 — results format v1**
- Every fixture round-trips losslessly and byte-stably (dump → load → dump identical); `schema_version` is required and a 2.x version is refused; every schema named in Tech Spec §3 is exported, checked against an independent list.
