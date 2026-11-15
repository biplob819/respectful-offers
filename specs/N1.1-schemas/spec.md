# N1.1 — Schemas and config

**Wave 1. Depends on:** W0.1. **Unblocks:** N1.2, N1.3, A2.3, and through them everything else.

## Goal
Every record the pipeline writes or reads has one typed, frozen definition (Tech Spec §3), and every table crossing a stage boundary is checked against a column contract (D-11). Configs load from YAML with errors that name the file, the key and the rule.

## Outputs (`respectful_offers.schemas`)
- `_base.py`: `Model` (frozen, `extra="forbid"`, no non-finite floats), `Versioned`, `FrozenDict`, strict scalar types. Copied from EvalKit's schema base.
- `rows.py`: `Action`, `ACTIONS`, `Response`, `PolicyName`, `MemberFeatures`, `AuditAttributes`, `MemberState`, `Decision`, `Outcome`.
- `simulator.py`: `SimulatorConfig` (§5.3) with structural validation only. Direction and ordering rules (SIM-06) belong to A2.2.
- `config.py`: `RunConfig` and `load_yaml`, `load_run_config`, `load_simulator_config`. Duplicate YAML keys, a directory, a non-UTF-8 file, unknown keys and bad values are `ConfigError`s that name the file and the key.
- `summary.py`: `Interval`, `PeriodSpend`, `PolicySummary`, `OPEEstimate`, `Comparison`, `ChurnReport`, `RunSummary`.
- `contracts.py`: `ColumnSpec`, `TableContract`, `check_frame(df, contract, stage)` raising `ContractError` naming stage, column and rule; one contract per row table.
- Fixtures under `tests/fixtures/v1/`: a run config, a simulator config (structure-valid values, not the pre-registered ones), a run summary.

## Rules
- Results format v1: every top-level file carries `schema_version`; a different major version is refused.
- `Decision.chosen` is in `allowed`; a downgraded decision changed the action; propensity is in (0, 1].
- `MemberState.declined` is a sorted tuple of shown actions with no duplicates and never `no_offer`.
- An `Outcome` that did not renew has zero revenue and zero discount cost.
- `PolicySummary.cost_per_incremental_retained` is null exactly when the incremental point estimate is ≤ 0.
- `RunSummary.simulated` is always true; summaries reference only policies and variants they contain; one summary per policy × variant.
- `SimulatorConfig`: all six risk × trend cells, all four segments, the three offer actions; probabilities in [0, 1]; each segment mix sums to 1 within 1e-9; effects in [−1, 1]; band cuts strictly increasing inside (0, 1) for risk.
- `RunConfig`: cohort buckets are disjoint and cover 0–100 exactly with the four names; `decision_features` holds no protected attribute (`age`, `bd`, `gender`, `city`, `registered_via`); every number finite; a zero budget is a zero budget.

## Out of scope
- Reading data (N1.2), stage runner (N1.3), simulator semantics (A2.2).
