# D3.2 — Demo page

**Wave 3. Depends on:** D3.1, B2.2. **Unblocks:** D3.3.

## Goal
The public policy simulator a growth PM can play with: budget and threshold sliders, a variant switch, members kept and discount spent per policy, the live respect audit, a holdout card and a footer that never lets anyone forget the outcomes are simulated (PRD wireframe, Tech Spec §8, US7).

## Outputs
- `demo/app.py`: the Streamlit page, reading one local cube file; no network or model calls.
- `offers demo-bundle`: a deploy folder (`streamlit_app.py`, `cube.json`, `requirements.txt`) that runs the page from its own files.
- `[demo]` optional dependency: Streamlit.

## Rules
- Central variant by default; the bandit's training threshold is shown when the threshold moves.
- The footer and the "Simulated" caption are always visible; a respectful policy with a violation turns the audit banner red.
- Publishing the bundle to the shared `portfolio-demos` app is the owner's step, done with the real-data cube after A2.8 (D-44).
