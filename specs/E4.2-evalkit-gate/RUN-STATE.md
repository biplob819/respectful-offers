# E4.2 run state

**Now:** spec (blocked on EvalKit v0.3.0, B5.4)

## History
- 2026-11-17 — spec written ahead of EvalKit v0.3.0 so the node can start when EvalKit tags (owner approved pre-speccing). EvalKit's build session will message when v0.3.0 is tagged.
- 2026-11-18 — EvalKit v0.3.0 on PyPI; built: extra and dev pin, CI on `evalkit gate`, contract tests (41), D-53.
- 2026-11-18 — verifier round 1: no blocker; canary command run in an isolated venv (41 passed), CI exit propagation and the CI import guard confirmed. Fixed: the public-API test now also checks `importorskip` modules and every attribute read through their aliases; README no longer says the canary already runs (it waits on EvalKit's registry flip); agreement now also covers a `1` written for a `true` label, a malformed gates file and a duplicate metric, and asserts the expected exit code, not just equality; disparity rows compare their attribute instead of dropping it, and label values are no longer lowercased. Spec corrected: CI writes EvalKit's gate.json to the runner's temp folder. Ruled: no second round.
- 2026-11-18 — converged twice; rows flipped green. EVK-04's last clause (EvalKit's canary green on this repo) is confirmed when EvalKit records the registry flip.
