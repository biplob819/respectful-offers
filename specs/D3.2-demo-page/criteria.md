# D3.2 acceptance criteria

**DEM-01 — the page**
- The page renders every policy (no offer, rule-following baseline, bandit, status quo) with members kept and discount spent, the live audit banner, the holdout card, the simulator quoted in full, and the "every outcome on this screen is simulated" footer; every metric is labelled simulated; a failed live audit shows an error and no numbers; the holdout card quotes the run's holdout share and check; the threshold slider spans the cube's risk range and warns when nobody is at risk; the sliders drive the numbers (a zero budget means no discount spent).

**DEM-02 — defaults and no network**
- The central variant is selected by default; rendering the page opens no network connection; the deploy bundle turns off Streamlit's usage statistics.

**DEM-03 — deploy as files**
- `offers demo-bundle` writes `streamlit_app.py`, `cube.json` (validated, integrity and simulator hash checked), `.streamlit/config.toml` and an installable `requirements.txt`; the bundle runs the page from its own files; it refuses a tampered cube, symlinks and folders holding other files. Publishing to the shared app is the owner's step after A2.8 (D-44).
