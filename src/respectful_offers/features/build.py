"""Member features as of a cohort's label month (Tech Spec §9, FEA-01..FEA-05).

DuckDB reads the raw KKBox CSVs in place (the ~30 GB user log is streamed with date and
member filters, never loaded whole). Every query filters on `< as_of`, and every feature's
latest source event date is recorded in `provenance`; `check_provenance` refuses any
feature that used an event on or after `as_of` (the label window), which is how leakage is
caught (C4).

Features (the `FEATURES` column contract):
  tenure_days          as_of − registration date (first transaction if registration missing)
  auto_renew           is_auto_renew on the latest transaction before as_of
  cancels_90d          cancellations in the 90 days before as_of
  listening_trend_30d  (songs in the last 30 days − songs in the 30 before) / max(prior, 1),
                       clipped to [−1, 5]
  price_30d            amount paid on the latest transaction, per 30 days of plan
  plan_days            plan length of the latest transaction
  churn_label          `is_churn` from train.csv (February) or train_v2.csv (March)

Age (`bd`) and gender never enter this table: they go to a separate audit table (R7).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from respectful_offers.data.kkbox import duckdb_columns
from respectful_offers.data.verify import DataError
from respectful_offers.schemas.contracts import AUDIT_ATTRIBUTES, FEATURES, check_frame

COHORTS: dict[str, tuple[dt.date, str]] = {
    "feb": (dt.date(2017, 2, 1), "train.csv"),
    "mar": (dt.date(2017, 3, 1), "train_v2.csv"),
}
LABEL_MONTH_END: dict[str, dt.date] = {"feb": dt.date(2017, 2, 28), "mar": dt.date(2017, 3, 31)}
TREND_CLIP = (-1.0, 5.0)


class LeakageError(RuntimeError):
    """A feature used an event on or after the cohort's as-of date."""


@dataclass(frozen=True)
class CohortFeatures:
    cohort: str
    as_of: dt.date
    features: pd.DataFrame
    provenance: dict[str, int | None]  # feature -> latest source event (YYYYMMDD) used
    dropped_no_history: int
    early_renewal_rows: int = 0  # booked before as_of, expiring after the label month (D-28):
    # early renewals or long plans; either way the member's membership does not lapse in the
    # label month as of as_of, so these rows never reach features
    dropped_only_excluded_rows: int = 0  # had history, but every row was excluded


def _ymd(d: dt.date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def _path(raw: Path, name: str) -> str:
    return (raw / name).as_posix().replace("'", "''")


def _csv(raw: Path, *names: str) -> str:
    """Read same-layout files with the explicit KKBox schema (verified by `offers data verify`)."""
    files = ", ".join(f"'{_path(raw, n)}'" for n in names)
    return (
        f"read_csv([{files}], header=true, delim=',', quote='\"', auto_detect=false, "
        f"columns={duckdb_columns(names[0])})"
    )


def check_provenance(provenance: dict[str, int | None], as_of: dt.date) -> None:
    cutoff = _ymd(as_of)
    leaks = {k: v for k, v in provenance.items() if v is not None and v >= cutoff}
    if leaks:
        raise LeakageError(f"features used events on or after {as_of}: {leaks}")


def build_cohort(raw: Path, cohort: str) -> CohortFeatures:
    as_of, label_file = COHORTS[cohort]
    cut = _ymd(as_of)
    month_end = _ymd(LABEL_MONTH_END[cohort])
    d30 = _ymd(as_of - dt.timedelta(days=30))
    d60 = _ymd(as_of - dt.timedelta(days=60))
    d90 = _ymd(as_of - dt.timedelta(days=90))
    tx = _csv(raw, "transactions.csv", "transactions_v2.csv")
    logs = _csv(raw, "user_logs.csv", "user_logs_v2.csv")
    con = duckdb.connect()
    try:
        con.execute(
            f"CREATE TEMP TABLE label AS SELECT msno, is_churn FROM {_csv(raw, label_file)}"
        )
        dupes = con.execute(
            "SELECT count(*) FROM (SELECT msno FROM label GROUP BY msno HAVING count(*) > 1)"
        ).fetchone()[0]  # type: ignore[index]
        if dupes:
            raise DataError(f"{label_file}: {dupes} member(s) are listed more than once")
        profile_dupes = con.execute(
            f"SELECT count(*) FROM (SELECT msno FROM {_csv(raw, 'members_v3.csv')} "
            "GROUP BY msno HAVING count(*) > 1)"
        ).fetchone()[0]  # type: ignore[index]
        if profile_dupes:
            raise DataError(f"members_v3.csv: {profile_dupes} member(s) are listed more than once")
        con.execute(
            f"""
            CREATE TEMP TABLE tx_all AS
            SELECT t.* FROM {tx} t JOIN label USING (msno)
            WHERE t.transaction_date < {cut}
            """
        )
        # an early renewal (booked before as_of, expiring after the label month) reveals the
        # label; such rows never reach features, and are counted (D-28)
        early = con.execute(
            f"SELECT count(*) FROM tx_all WHERE membership_expire_date > {month_end}"
        ).fetchone()[0]  # type: ignore[index]
        con.execute(
            "CREATE TEMP TABLE tx AS SELECT * FROM tx_all "
            f"WHERE membership_expire_date <= {month_end}"
        )
        last = con.execute(
            """
            SELECT msno, is_auto_renew, payment_plan_days, actual_amount_paid, plan_list_price,
                   transaction_date
            FROM (
              SELECT *, row_number() OVER (
                PARTITION BY msno ORDER BY transaction_date DESC, membership_expire_date DESC,
                  is_cancel ASC, payment_plan_days DESC, actual_amount_paid DESC,
                  plan_list_price DESC, is_auto_renew DESC, payment_method_id DESC) AS rn
              FROM tx WHERE payment_plan_days > 0
            ) WHERE rn = 1
            """
        ).df()
        cancels = con.execute(
            f"SELECT msno, sum(is_cancel)::BIGINT AS cancels_90d, max(transaction_date) AS last_d "
            f"FROM tx WHERE transaction_date >= {d90} GROUP BY msno"
        ).df()
        with_any = con.execute("SELECT count(DISTINCT msno) FROM tx_all").fetchone()[0]  # type: ignore[index]
        first_tx = con.execute(
            "SELECT msno, min(transaction_date) AS first_d FROM tx GROUP BY msno"
        ).df()
        listen = con.execute(
            f"""
            SELECT l.msno,
              sum(CASE WHEN l.date >= {d30} THEN num_25+num_50+num_75+num_985+num_100 ELSE 0 END)
                AS recent,
              sum(CASE WHEN l.date < {d30} THEN num_25+num_50+num_75+num_985+num_100 ELSE 0 END)
                AS prior,
              max(l.date) AS last_d
            FROM {logs} l JOIN label USING (msno)
            WHERE l.date >= {d60} AND l.date < {cut}
            GROUP BY l.msno
            """
        ).df()
        members = con.execute(
            "SELECT m.msno, registration_init_time, bd, gender "
            f"FROM {_csv(raw, 'members_v3.csv')} m JOIN label USING (msno)"
        ).df()
        label = con.execute("SELECT msno, is_churn FROM label").df()
        provenance = {
            "auto_renew": con.execute("SELECT max(transaction_date) FROM tx").fetchone()[0],  # type: ignore[index]
        }
    finally:
        con.close()

    df = label.merge(last, on="msno", how="inner")
    for col in ("is_auto_renew", "payment_plan_days", "actual_amount_paid"):
        if df[col].isna().any():
            raise DataError(
                f"transactions: {int(df[col].isna().sum())} latest transaction(s) have no {col}"
            )
    dropped = len(label) - len(df)
    df = df.merge(cancels[["msno", "cancels_90d"]], on="msno", how="left")
    df = df.merge(first_tx, on="msno", how="left").merge(
        listen[["msno", "recent", "prior"]], on="msno", how="left"
    )
    df = df.merge(members[["msno", "registration_init_time"]], on="msno", how="left")

    as_of_ts = pd.Timestamp(as_of)
    reg = pd.to_datetime(
        df["registration_init_time"].astype("Int64").astype(str), format="%Y%m%d", errors="coerce"
    )
    first = pd.to_datetime(
        df["first_d"].astype("Int64").astype(str), format="%Y%m%d", errors="coerce"
    )
    start = reg.where(reg.notna() & (reg <= as_of_ts), first)
    tenure = (as_of_ts - start).dt.days.fillna(0).clip(lower=0).astype(np.int64)
    recent = df["recent"].fillna(0).astype(float)
    prior = df["prior"].fillna(0).astype(float)
    trend = ((recent - prior) / np.maximum(prior, 1.0)).clip(*TREND_CLIP)

    out = (
        pd.DataFrame(
            {
                "msno": df["msno"].astype(str),
                "cohort": cohort,
                "as_of": as_of,
                "tenure_days": tenure,
                "auto_renew": df["is_auto_renew"].astype(int).astype(bool),
                "cancels_90d": df["cancels_90d"].fillna(0).astype(np.int64),
                "listening_trend_30d": trend.astype(float),
                "price_30d": (
                    df["actual_amount_paid"].astype(float)
                    / df["payment_plan_days"].astype(float)
                    * 30.0
                ).clip(lower=0.0),
                "plan_days": df["payment_plan_days"].astype(np.int64),
                "churn_label": df["is_churn"].astype(int).astype(bool),
            }
        )
        .sort_values("msno", kind="mergesort")
        .reset_index(drop=True)
    )
    provenance.update(
        {
            "price_30d": provenance["auto_renew"],
            "plan_days": provenance["auto_renew"],
            "cancels_90d": int(cancels["last_d"].max()) if len(cancels) else None,
            "listening_trend_30d": int(listen["last_d"].max()) if len(listen) else None,
            "tenure_days": int(first_tx["first_d"].max()) if len(first_tx) else None,
        }
    )
    provenance = {
        k: (int(v) if v is not None and not pd.isna(v) else None) for k, v in provenance.items()
    }
    check_provenance(provenance, as_of)
    check_frame(out, FEATURES, f"features[{cohort}]")
    only_excluded = max(int(with_any) - len(df), 0)
    return CohortFeatures(
        cohort, as_of, out, provenance, dropped - only_excluded, int(early), only_excluded
    )


def age_band(bd: pd.Series) -> pd.Series:
    b = pd.to_numeric(bd, errors="coerce")
    bands = pd.Series("unknown", index=bd.index, dtype=object)
    valid = b.between(1, 100)
    bands[valid & (b < 18)] = "<18"
    bands[valid & b.between(18, 24)] = "18-24"
    bands[valid & b.between(25, 34)] = "25-34"
    bands[valid & b.between(35, 44)] = "35-44"
    bands[valid & (b >= 45)] = "45+"
    return bands


def build_audit_attributes(raw: Path, members: pd.Series) -> pd.DataFrame:
    """Age band and gender for the given members, kept apart from features (R7)."""
    con = duckdb.connect()
    try:
        m = con.execute(f"SELECT msno, bd, gender FROM {_csv(raw, 'members_v3.csv')}").df()
        if m["msno"].duplicated().any():
            raise DataError("members_v3.csv: a member is listed more than once")
    finally:
        con.close()
    wanted = pd.DataFrame({"msno": pd.Series(sorted(set(members)), dtype=object)})
    m = wanted.merge(m, on="msno", how="left")  # members with no members_v3 row stay, as unknown
    g = m["gender"].fillna("").astype(str).str.lower()
    out = (
        pd.DataFrame(
            {
                "msno": m["msno"].astype(str),
                "age_band": age_band(m["bd"]),
                "gender": np.where(g.isin(["female", "male"]), g, "unknown"),
            }
        )
        .sort_values("msno", kind="mergesort")
        .reset_index(drop=True)
    )
    check_frame(out, AUDIT_ATTRIBUTES, "audit_attributes")
    return out


def summary_stats(cf: CohortFeatures) -> dict[str, Any]:
    f = cf.features
    return {
        "cohort": cf.cohort,
        "as_of": cf.as_of.isoformat(),
        "members": len(f),
        "dropped_no_history": cf.dropped_no_history,
        "dropped_only_excluded_rows": cf.dropped_only_excluded_rows,
        "early_renewal_rows_dropped": cf.early_renewal_rows,
        "churn_rate": round(float(f["churn_label"].mean()), 6) if len(f) else None,
        "auto_renew_rate": round(float(f["auto_renew"].mean()), 6) if len(f) else None,
        "provenance": cf.provenance,
        "means": {
            c: round(float(f[c].mean()), 6)
            for c in ("tenure_days", "cancels_90d", "listening_trend_30d", "price_30d")
        },
    }
