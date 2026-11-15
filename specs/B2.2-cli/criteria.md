# B2.2 acceptance criteria

**CLI-01 — every command**
- `data`, `features`, `churn`, `prereg`, `simulate`, `evaluate`, `report`, `run`, `doctor` and `init` exist; `churn` reports the model on verified data and `simulate` trains and saves a bandit posterior.

**CLI-02 — doctor**
- `offers doctor` passes in an empty folder using the bundled templates, reports optional problems as notes, and never prints a credential.

**CLI-03 — report --example**
- Renders the bundled synthetic run, labelled synthetic; re-renders into a folder holding exactly the files it wrote before (by sha256); refuses a folder holding any other file (even beside its mark), a symlink anywhere, or any `runs/` folder, leaving them untouched; the bundled run is a valid, clean synthetic summary whose simulator hash matches the template.

**CLI-04 — exit codes and --json**
- Every command takes `--json` and prints exactly one JSON document, usage errors included; missing raw data (including a raw file gone behind a warm cache) exits 3, configuration and usage errors exit 2, a real audit failure exits 1 from `evaluate` and `run --all`; a crash still prints JSON.

**CLI-05 — run --all**
- From raw files, and from the user's own table in a fresh `offers init` project following its README (`prereg --scope real`) to a pre-registered run, one command builds features, the churn model, every policy, the audit and the report; a synthetic-scope registration refuses the user's (real) data without `--exploratory`, in `evaluate`, `run` and `simulate`; `features --from-table` accepts and refuses exactly what running does; new files in an old synthetic folder are never labelled synthetic.

**CLI-06 — init**
- Scaffolds a run config, a simulator, features and audit templates and a README; never overwrites an existing file; refuses a file path; the templates equal `configs/` byte for byte.
