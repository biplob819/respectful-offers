# Pre-registration

Written by `offers prereg` (D-3). Evaluations refuse a simulator file whose sha256 is not the one below, unless run with `--exploratory` (stamped, never published). A `synthetic` registration never certifies a run on real KKBox data.

| Field | Value |
| --- | --- |
| Simulator YAML sha256 | `f56881c05863cc5e51ade687e7373eac3544d3b4518a7f45aebc464bc9ebf3e3` |
| File | `configs/simulator.yaml` |
| Registered on | 2026-11-15 |
| Scope | synthetic |
| Variants | central, conservative, optimistic |
| Pre-registered success criteria | Retained members per 1,000 at risk, discount cost per incremental retained member, 90-day LTV proxy and offer fatigue are reported for every policy under all three variants with 95% intervals, whatever they show. The respectful policies must have zero R1, R2, R3, R7 and R8 violations. The headline claim ("the bandit keeps more members per discount dollar than the rule-following baseline") is made for a variant only if the Holm-corrected paired interval excludes zero; otherwise the report says it is a tie. |
