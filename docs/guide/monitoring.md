# Monitoring a period and challenging the champion

Once a policy is live, two questions come back every period. Have the inputs or the churn
model's calibration moved? Would a retrained model and bandit do better? `offers monitor` answers the first and
`offers challenge` the second. [EvalKit](https://github.com/biplob819/evalkit) 0.4 (`pip install
'respectful-offers[evalkit]'`) does the drift statistics and keeps the ledgers; this repo hands
it aggregates only, never a member row.

**Honest limit.** Member features, churn scores and churn labels are real KKBox data, so drift
and calibration are measured for real. Offer responses still come from the pre-registered
simulator, so every outcome check and every challenge carries `simulated: true`.

## Each period

```bash
uv run offers monitor export                                   # needs the downloaded data
uv run offers monitor drift --ledger docs/measurements/runs.jsonl
uv run offers monitor check --period results/kkbox/metrics.json
```

- `monitor export` writes the drift inputs in [`results/kkbox/monitor/`](https://github.com/biplob819/respectful-offers/tree/main/results/kkbox/monitor):
  each model feature's share of members per bin (bins fixed by February, none under 30
  members) and the churn model's Brier score, ECE and ten equal-width reliability bins, for
  February (the baseline) and March (the period).
- `monitor drift` has EvalKit freeze the February reference and check March against it at
  [`configs/drift.yaml`](https://github.com/biplob819/respectful-offers/blob/main/configs/drift.yaml):
  a PSI per feature and the Brier, ECE and per-bin changes with 95% intervals. It writes
  `drift-ref.json`, `drift.json` and `drift.metrics.json`, and with `--ledger` adds the period
  to EvalKit's hash-chained run history.
- `monitor check` runs the outcome checks: respect violations, the claim, cost per extra
  member kept and the age-band gap. Cost and disparity need `--baseline` (a baseline period's
  metrics); without one they are reported as not checked, never as passed.

**Severities (OWNER D-56).** Drift and calibration *warn*: they are reasons to run a challenger,
not to block. A respect violation, the claim lost, cost per extra member up by more than 25%
with its interval clear, or the age-band gap wider by more than 0.05 *fail* (exit 1).

**What March shows.** Feature drift is negligible (every PSI under 0.01). The churn model's
calibration did move: Brier up 0.015 and ECE up 0.024, both beyond EvalKit's tolerances, with
three mid-risk reliability bins (0.3 to 0.6) out by 0.12 to 0.20. Part of that is built in, since the February
reference is the calibrator's own fold and flatters it. All of it warns, so the period passes
and a challenger is the response.

## Challenging the champion

```bash
uv run offers challenge --challenger-seed 20261122 --baseline <a baseline period's metrics.json>
```

The challenger is a churn model and a bandit retrained with another seed on February only. Both
it and the champion are rolled out on the champion's evaluation members in the champion's
simulated world, under common random numbers, so the champion arm reproduces the published
bandit figure for figure (D-58). The rule, stated before any challenger ran: promote only if,
in every variant, extra members kept per 1,000 NTD improve (paired bootstrap lower bound above
0, separated after Holm), neither arm breaks a respect rule, and no outcome check fails.

Every challenge is recorded. It is opened in EvalKit's experiment ledger before either arm is
rolled out, and closed with EvalKit's compare of the two arms. That compare is unpaired, so it
is recorded beside the paired test, which decides. A PROMOTION or NO-PROMOTION row goes into
`docs/decisions.md`. A refused challenge (a changed simulator, missing members, a challenger
identical to the champion) is refused before anything is opened; `--no-record` reruns one
already recorded. Cost and disparity need a baseline period (`--baseline`): a challenge without
one is never promoted, because a check that did not run is never read as passed.

**The first challenge: NO-PROMOTION.** Challenger minus champion, extra members kept per 1,000
NTD: conservative +0.16 (−0.10 to +0.42), central −0.03 (−0.25 to +0.19), optimistic +0.63
(+0.29 to +0.97). It improves in one variant out of three, so the champion stays.
