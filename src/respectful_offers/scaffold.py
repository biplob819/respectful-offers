"""`offers init`: a project folder for your own data (CLI-06, OWNER D-21).

Writes a run configuration, a copy of the simulator template (to be edited and then
pre-registered before any real run), a features-table template, an audit-table template and
a short README. It never overwrites a file that already exists (EvalKit L-30): existing files
are reported as kept.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

FEATURES_TEMPLATE = (
    "msno,cohort,as_of,tenure_days,auto_renew,cancels_90d,listening_trend_30d,price_30d,plan_days,churn_label\n"
    "member-0001,feb,2017-02-01,420,true,0,0.05,149,30,false\n"
    "member-0002,mar,2017-03-01,35,false,1,-0.40,99,30,true\n"
)
AUDIT_TEMPLATE = "msno,age_band,gender\nmember-0001,25-34,female\nmember-0002,unknown,unknown\n"
README = """# Respectful Offers project

`features.csv` and `audit.csv` here only show the format: replace them with your members
(thousands, in both cohorts) before step 1.

1. Put your members in `features.csv`: one row per member and cohort; `feb` rows train the
   churn model, `mar` rows are the cohort the policies are evaluated on, and each cohort needs
   both churners and renewers. `offers features --from-table features.csv --audit-table
   audit.csv` checks both files and names any bad row and column.
2. Optional: age band and gender in `audit.csv`. They are audited for disparity, never used to
   decide.
3. Edit `simulator.yaml` with values you believe, then freeze them for your (real) data:
   `offers prereg --scope real`.
4. `offers run --all --from-table features.csv --audit-table audit.csv` builds features, the
   churn model, every policy under every simulator variant, the audit and the report in
   `report/index.html`. To try it before step 3, add `--exploratory` (stamped, never to be
   published).

Every result is simulated: the simulator decides how members respond. Nothing leaves this
machine.
"""


def template_text(name: str) -> str:
    return resources.files("respectful_offers.templates").joinpath(name).read_text(encoding="utf-8")


def scaffold(folder: Path) -> dict[str, list[str]]:
    """Create the project files; returns {"written": [...], "kept": [...]}."""
    folder.mkdir(parents=True, exist_ok=True)
    files = {
        "offers-run.yaml": template_text("run.yaml"),
        "simulator.yaml": template_text("simulator.yaml"),
        "features.csv": FEATURES_TEMPLATE,
        "audit.csv": AUDIT_TEMPLATE,
        "README.md": README,
    }
    result: dict[str, list[str]] = {"written": [], "kept": []}
    for name, text in files.items():
        path = folder / name
        if path.exists() or path.is_symlink():  # a dangling symlink counts as taken too
            result["kept"].append(name)
            continue
        try:
            with path.open("x", encoding="utf-8", newline="\n") as fh:  # "x": never overwrite
                fh.write(text)
        except FileExistsError:  # created meanwhile: keep theirs
            result["kept"].append(name)
            continue
        result["written"].append(name)
    return result
