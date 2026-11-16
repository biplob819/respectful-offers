# Pre-registration

Written by `offers prereg` (D-3). Evaluations refuse a simulator file whose sha256 is not the one below, unless run with `--exploratory` (stamped, never published). A `synthetic` registration never certifies a run on real data (KKBox or your own table).

| Field | Value |
| --- | --- |
| Simulator YAML sha256 | `6ae089599c41b7418c649a2cd7256f6090d4f071ced268adab9eddd0c0a44326` |
| File | `configs/simulator.yaml` |
| Registered on | 2026-11-17 |
| Scope | real |
| Variants | central, conservative, optimistic |
| Pre-registered success criteria | Retained members per 1,000 at risk, discount cost per incremental retained member, 90-day LTV proxy and offer fatigue are reported for every policy under all three variants with 95% intervals, whatever they show. The respectful policies must have zero R1, R2, R3, R7 and R8 violations. The headline claim ("the bandit keeps more members per discount dollar than the rule-following baseline") is made for a variant only if the Holm-corrected paired interval excludes zero; otherwise the report says it is a tie. |
