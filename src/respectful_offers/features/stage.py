"""The features stage and the bring-your-own-data loader (FEA-06, FEA-07).

`FeaturesStage` builds both cohorts and the audit table from raw KKBox files. Its input is
the verified manifest (`offers data verify`), so its cache key changes exactly when a raw
file's checksum does; before building, it checks every file's size and sha256 against the
manifest, so a file changed after verification can never be built under the old key.

`load_features_table` lets anyone run the policy on their own subscription data: a CSV or
Parquet table with exactly the `FEATURES` columns. Use cohort `feb` for the labelled month you
train the churn model on and `mar` for the month you score and simulate (D-27). A member may
appear in both cohorts, once each.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import ValidationError

from respectful_offers.data.kkbox import REQUIRED
from respectful_offers.data.verify import DataError, sha256_file
from respectful_offers.features.build import build_audit_attributes, build_cohort, summary_stats
from respectful_offers.runtime.stage import RunContext, Stage
from respectful_offers.schemas.contracts import FEATURES, ContractError, check_frame
from respectful_offers.schemas.rows import MemberFeatures, row_from_record

BOOL_COLUMNS = ("auto_renew", "churn_label")
BOOL_TEXT = {"true": True, "false": False, "1": True, "0": False, "1.0": True, "0.0": False}


class FeaturesStage(Stage):
    name = "features"
    code_version = "3"

    def __init__(self, raw_dir: Path) -> None:
        self._raw_dir = Path(raw_dir)  # private: the manifest, not the path, is the identity

    def run(self, inputs: Mapping[str, Path], out: Path, ctx: RunContext) -> None:
        manifest = json.loads((inputs["manifest"] / "manifest.json").read_text(encoding="utf-8"))
        for name in REQUIRED:  # contents, not just sizes: the manifest is this stage's identity
            f = self._raw_dir / name
            rec = manifest["files"][name]
            if (
                not f.is_file()
                or f.stat().st_size != rec["bytes"]
                or sha256_file(f) != rec["sha256"]
            ):
                raise DataError(
                    f"{name} differs from the verified manifest; run `offers data verify`"
                )
        stats = {}
        members: list[str] = []
        for cohort in ("feb", "mar"):
            cf = build_cohort(self._raw_dir, cohort)
            cf.features.to_parquet(out / f"features_{cohort}.parquet", index=False)
            stats[cohort] = summary_stats(cf)
            members += cf.features["msno"].tolist()
        audit = build_audit_attributes(self._raw_dir, pd.Series(sorted(set(members))))
        audit.to_parquet(out / "audit_attributes.parquet", index=False)
        text = json.dumps(stats, indent=2, sort_keys=True) + "\n"
        (out / "stats.json").write_text(text, encoding="utf-8")


def _first(mask: pd.Series) -> int:
    return int(np.flatnonzero(mask.to_numpy())[0])


def _coerce_bool(s: pd.Series, column: str, where: str, offset: int) -> pd.Series:
    if s.dtype == bool:
        return s
    text = s.astype(str).str.strip().str.lower()
    bad = ~text.isin(BOOL_TEXT.keys())
    if bad.any():
        row = _first(bad)
        raise ContractError(
            f"{where}: row {row + offset}: column {column}: {s.iloc[row]!r} is not true/false/1/0"
        )
    return text.map(BOOL_TEXT).astype(bool)


def load_features_table(path: Path) -> pd.DataFrame:
    """Read and validate a user's features table; errors name the row and the column.

    Rows are numbered as the user sees them: CSV rows count the header line (first data row
    is row 2), Parquet rows start at 1."""
    path = Path(path)
    where = str(path)
    if not path.is_file():
        raise ContractError(f"{where}: no such file")
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        df = pd.read_parquet(path)
    elif suffix == ".csv":
        df = pd.read_csv(path, dtype={"msno": str, "cohort": str})
    else:
        raise ContractError(f"{where}: use a .csv or .parquet file")
    offset = 2 if suffix == ".csv" else 1
    missing = [c for c in FEATURES.names if c not in df.columns]
    if missing:
        raise ContractError(f"{where}: missing column(s) {missing}")
    extra = [c for c in df.columns if c not in FEATURES.names]
    if extra:
        raise ContractError(
            f"{where}: unexpected column(s) {extra}; keep only {list(FEATURES.names)}"
        )
    if pd.api.types.is_datetime64_any_dtype(df["as_of"]):
        timed = df["as_of"].notna() & (df["as_of"] != df["as_of"].dt.normalize())
        if timed.any():
            row = _first(timed)
            raise ContractError(
                f"{where}: row {row + offset}: column as_of: {df['as_of'].iloc[row]} has a time "
                "of day; give a date"
            )
        df["as_of"] = df["as_of"].dt.date
    elif not df["as_of"].map(lambda v: type(v).__name__ == "date").all():
        parsed = pd.to_datetime(df["as_of"], format="%Y-%m-%d", errors="coerce")
        if parsed.isna().any():
            row = _first(parsed.isna())
            raise ContractError(
                f"{where}: row {row + offset}: column as_of: "
                f"{df['as_of'].iloc[row]!r} is not YYYY-MM-DD"
            )
        df["as_of"] = parsed.dt.date
    for c in BOOL_COLUMNS:
        df[c] = _coerce_bool(df[c], c, where, offset)
    try:
        check_frame(df, FEATURES, where)
    except ContractError as exc:
        for i, rec in enumerate(df.to_dict("records")):
            try:
                row_from_record(MemberFeatures, {str(k): v for k, v in rec.items()})
            except ValidationError as verr:
                err = verr.errors()[0]
                col = ".".join(str(x) for x in err["loc"])
                raise ContractError(
                    f"{where}: row {i + offset} (msno {rec.get('msno')}): "
                    f"column {col}: {err['msg']}"
                ) from exc
        raise
    dup = df.duplicated(["cohort", "msno"], keep="first")
    if dup.any():
        row = _first(dup)
        raise ContractError(
            f"{where}: row {row + offset}: column msno: {df['msno'].iloc[row]!r} appears twice "
            f"in cohort {df['cohort'].iloc[row]!r}"
        )
    return df.sort_values(["cohort", "msno"], kind="mergesort").reset_index(drop=True)
