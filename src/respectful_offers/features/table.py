"""Your own data (OWNER D-21): a features table in place of the KKBox files.

`TableFeaturesStage` turns a user's features table (validated against the `MemberFeatures`
contract by `load_features_table`, errors naming row and column) into the same artifact the
KKBox features stage writes, so the churn and evaluate stages run unchanged:
`features_feb.parquet`, `features_mar.parquet`, `stats.json` and `audit_attributes.parquet`.

The table must hold both cohorts: `feb` (the churn model trains on it) and `mar` (the cohort
the policies are evaluated on). Age band and gender, if you have them, go in a separate audit
table (`msno, age_band, gender`): they are audited, never used to decide (R7). Without one,
every member is `unknown` and the disparity audit has nothing to show.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from respectful_offers.features.stage import load_features_table
from respectful_offers.runtime.stage import RunContext, Stage
from respectful_offers.schemas.contracts import AUDIT_ATTRIBUTES, ContractError, check_frame

TABLE_NAMES = ("features.csv", "features.parquet")
AUDIT_NAME = "audit.csv"
AGE_BANDS = ("<18", "18-24", "25-34", "35-44", "45+", "unknown")  # as AUDIT_ATTRIBUTES allows
GENDERS = ("female", "male", "unknown")


def load_audit_table(path: Path, members: set[str], where: str | None = None) -> pd.DataFrame:
    """Read an optional audit table; errors name the row and the column."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    where = where or str(path)
    want = ["msno", "age_band", "gender"]
    if list(df.columns) != want:
        raise ContractError(f"{where}: the columns must be exactly {want}, got {list(df.columns)}")
    for col, allowed in (("age_band", AGE_BANDS), ("gender", GENDERS)):
        bad = ~df[col].isin(allowed)
        if bad.any():
            row = int(bad.to_numpy().nonzero()[0][0])
            raise ContractError(
                f"{where}: row {row + 2}: column {col}: {df[col].iloc[row]!r} is not one of "
                f"{list(allowed)}"
            )
    if df["msno"].duplicated().any():
        raise ContractError(f"{where}: a member is listed more than once")
    if not df["msno"].isin(members).any():
        raise ContractError(
            f"{where}: no member in the audit table is in the features table; check the msno values"
        )
    df = df[df["msno"].isin(members)]
    missing = sorted(members - set(df["msno"]))
    if missing:  # members without a row are unknown, as with KKBox's members file
        extra = pd.DataFrame({"msno": missing, "age_band": "unknown", "gender": "unknown"})
        df = pd.concat([df, extra], ignore_index=True)
    return df.sort_values("msno", kind="mergesort").reset_index(drop=True)


def check_cohorts(df: pd.DataFrame, where: str) -> None:
    """What the pipeline needs beyond the row contract, checked the same way by
    `offers features --from-table` and by every command that runs on the table."""
    for cohort in ("feb", "mar"):
        f = df[df["cohort"] == cohort]
        if f.empty:
            raise ContractError(
                f"{where}: no {cohort!r} rows: the table needs both cohorts, 'feb' to train the "
                "churn model and 'mar' to evaluate the policies on"
            )
        if f["churn_label"].nunique() < 2:
            raise ContractError(f"{where}: the {cohort!r} rows need both churners and renewers")
        dupes = f["msno"].duplicated()
        if dupes.any():
            raise ContractError(
                f"{where}: member {f['msno'][dupes].iloc[0]!r} appears twice in the {cohort!r} rows"
            )


def load_user_table(path: Path, where: str | None = None) -> pd.DataFrame:
    """The user's table, validated: the row contract, then the cohort rules. Errors name the
    user's own file (`where`), never the cache's copy of it."""
    where = where or str(path)
    try:
        df = load_features_table(path)
    except ContractError as exc:
        raise ContractError(str(exc).replace(str(path), where)) from None
    check_cohorts(df, where)
    return df


class TableFeaturesStage(Stage):
    name = "features_table"
    code_version = "1"

    def __init__(self, shown_as: tuple[str, str] = ("features table", "audit table")) -> None:
        self._shown_as = shown_as  # the user's file names for messages; not part of the key

    def run(self, inputs: Mapping[str, Path], out: Path, ctx: RunContext) -> None:
        src = inputs["table"]
        tables = [src / n for n in TABLE_NAMES if (src / n).is_file()]
        if len(tables) != 1:
            raise ContractError(f"the table artifact must hold exactly one of {list(TABLE_NAMES)}")
        df = load_user_table(tables[0], self._shown_as[0])
        stats = {}
        for cohort in ("feb", "mar"):
            f = df[df["cohort"] == cohort].sort_values("msno", kind="mergesort")
            f = f.reset_index(drop=True)
            f.to_parquet(out / f"features_{cohort}.parquet", index=False)
            stats[cohort] = {
                "cohort": cohort,
                "as_of": str(f["as_of"].iloc[0]),
                "members": len(f),
                "churn_rate": round(float(f["churn_label"].mean()), 6),
                "auto_renew_rate": round(float(f["auto_renew"].mean()), 6),
                "provenance": {"source": "your own features table"},
                "early_renewal_rows_dropped": None,
            }
        members = set(df["msno"])
        audit_path = src / AUDIT_NAME
        if audit_path.is_file():
            audit = load_audit_table(audit_path, members, self._shown_as[1])
        else:
            audit = pd.DataFrame(
                {"msno": sorted(members), "age_band": "unknown", "gender": "unknown"}
            )
        check_frame(audit, AUDIT_ATTRIBUTES, "audit_attributes")
        audit.to_parquet(out / "audit_attributes.parquet", index=False)
        (out / "stats.json").write_text(
            json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
