"""Seeded synthetic data in the KKBox file layout (DAT-05).

The real KKBox files cannot be committed or redistributed, so tests, the golden run and
`offers report --example` use this generator. It writes the same seven files, with the same
columns and YYYYMMDD date encoding as the WSDM Cup 2018 KKBox churn competition:

    members_v3.csv        msno, city, bd, gender, registered_via, registration_init_time
    transactions.csv      msno, payment_method_id, payment_plan_days, plan_list_price,
                          actual_amount_paid, is_auto_renew, transaction_date,
                          membership_expire_date, is_cancel          (up to 2017-02-28)
    transactions_v2.csv   same columns                               (2017-03-01..03-31)
    user_logs.csv         msno, date, num_25, num_50, num_75, num_985, num_100, num_unq,
                          total_secs                                 (up to 2017-02-28)
    user_logs_v2.csv      same columns                               (2017-03-01..03-31)
    train.csv             msno, is_churn   (memberships expiring in February 2017)
    train_v2.csv          msno, is_churn   (memberships expiring in March 2017)

Churn follows the competition's definition: a member churns if there is no new valid
subscription within 30 days of the membership expiring. The fixture includes awkward cases
real data has (N1.2 verifier): older plans of 7, 31 and 90 days, discounts and free months,
duplicate same-day transactions, historical cancellations, churners who come back 31 to 60
days later, renewals spread up to 29 days after expiry, members who appear only in the March
cohort, members missing from `members_v3.csv`, impossible ages and negative `total_secs`.
It never books a renewal before the cohort's as-of date: in real data such a member would
not be in that cohort at all.

Member ids look like `S000042` (the data scan never mistakes them for KKBox ids). Output is
byte-identical for a seed under the locked numpy and pandas versions (uv.lock).
"""

from __future__ import annotations

import datetime as dt
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

FILES = (
    "members_v3.csv",
    "transactions.csv",
    "transactions_v2.csv",
    "user_logs.csv",
    "user_logs_v2.csv",
    "train.csv",
    "train_v2.csv",
)
PRICES = np.array([99, 129, 149, 180])
LOG_START = pd.Timestamp("2016-12-01")
FEB_START, FEB_END = pd.Timestamp("2017-02-01"), pd.Timestamp("2017-02-28")
MAR_START, MAR_END = pd.Timestamp("2017-03-01"), pd.Timestamp("2017-03-31")


def _ymd(d: Any) -> Any:
    if isinstance(d, dt.date):
        return d.year * 10000 + d.month * 100 + d.day
    s = pd.to_datetime(pd.Series(np.asarray(d)))
    return (s.dt.year * 10000 + s.dt.month * 100 + s.dt.day).to_numpy(dtype=np.int64)


@dataclass(frozen=True)
class SyntheticSpec:
    n_members: int = 5_000
    seed: int = 20261121
    log_days_fraction: float = 0.5  # share of days with a listening log, on average
    march_only_share: float = 0.05  # members whose first expiry in scope is in March


def _tx(msno: np.ndarray, plan: Any, list_price: Any, paid: Any, auto: np.ndarray, txd: Any,
        exp: Any, cancel: Any, method: Any) -> pd.DataFrame:  # fmt: skip
    return pd.DataFrame(
        {
            "msno": msno,
            "payment_method_id": method,
            "payment_plan_days": plan,
            "plan_list_price": list_price,
            "actual_amount_paid": paid,
            "is_auto_renew": auto.astype(int),
            "transaction_date": _ymd(txd),
            "membership_expire_date": _ymd(exp),
            "is_cancel": cancel,
        }
    )


def _days(values: np.ndarray) -> pd.TimedeltaIndex:
    return pd.to_timedelta(values, unit="D")


def generate(out_dir: Path, spec: SyntheticSpec = SyntheticSpec()) -> dict[str, Path]:
    """Write all seven files into `out_dir` and return their paths."""
    if spec.n_members < 200:
        raise ValueError("n_members must be at least 200 (smaller fixtures give unstable rates)")
    rng = np.random.default_rng(spec.seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    n = spec.n_members
    msno = np.array([f"S{i:06d}" for i in range(1, n + 1)])
    march_only = rng.uniform(size=n) < spec.march_only_share

    # members (2% missing from members_v3, as in the real data)
    reg = np.where(
        march_only,
        np.datetime64("2016-12-15") + rng.integers(0, 40, n).astype("timedelta64[D]"),
        np.datetime64("2005-01-01") + rng.integers(0, 4000, n).astype("timedelta64[D]"),
    )
    bd = np.where(rng.uniform(size=n) < 0.4, 0, rng.integers(15, 61, n))
    outliers = rng.uniform(size=n) < 0.01
    bd[outliers] = rng.integers(-50, 1000, int(outliers.sum()))
    gender = rng.choice(np.array(["male", "female", ""], dtype=object), n, p=[0.3, 0.3, 0.4])
    in_members = rng.uniform(size=n) >= 0.02
    members = pd.DataFrame(
        {
            "msno": msno,
            "city": rng.integers(1, 23, n),
            "bd": bd,
            "gender": gender,
            "registered_via": rng.choice([3, 4, 7, 9, 13], n),
            "registration_init_time": _ymd(reg),
        }
    )[in_members]

    # hidden drivers of churn
    auto_renew = rng.uniform(size=n) < 0.85
    engagement = rng.lognormal(mean=3.0, sigma=0.6, size=n)  # songs per active day
    trend = np.clip(rng.normal(0.0, 0.25, n), -0.9, 0.9)  # change in listening, Jan to Feb
    cancels = rng.poisson(np.where(auto_renew, 0.05, 0.3))
    price = rng.choice(PRICES, n, p=[0.15, 0.15, 0.6, 0.1])
    tenure_days = np.maximum((np.datetime64("2017-02-01") - reg).astype(int), 0)
    logit = (
        -1.0
        - 2.4 * auto_renew
        - 3.0 * trend
        + 0.9 * np.minimum(cancels, 3)
        - 0.25 * np.log1p(tenure_days / 365)
        + 0.008 * (price - 149)
        + rng.normal(0, 0.6, n)
    )
    feb_churn = rng.uniform(size=n) < 1 / (1 + np.exp(-logit))
    mar_logit = logit - 0.6 * trend + rng.normal(0, 0.3, n)
    mar_churn = rng.uniform(size=n) < 1 / (1 + np.exp(-mar_logit))

    # history: monthly memberships; the last one before the label month expires in February
    # (March for March-only members); older rows have other plan lengths and discounts
    feb_expiry = FEB_START + _days(rng.integers(0, 28, n))
    mar_first = MAR_START + _days(rng.integers(2, 29, n))
    first_expiry = pd.DatetimeIndex(np.where(march_only, mar_first, feb_expiry))
    # March-only members are new: one first membership bought in February, expiring in March,
    # so they never have a February expiry (and rightly are not in train.csv)
    months_back = np.where(march_only, 1, np.minimum(1 + tenure_days // 30, 12))
    frames = []
    for k in range(int(months_back.max()), 0, -1):
        has = months_back >= k
        m = int(has.sum())
        exp = first_expiry[has] - _days(np.full(m, 30 * (k - 1)))
        older = k >= 4
        plan = np.where(older & (rng.uniform(size=m) < 0.15), rng.choice([7, 31, 90], m), 30)
        list_price = np.round(price[has] * plan / 30).astype(int)
        discount = np.where(rng.uniform(size=m) < 0.1, rng.choice([0.0, 0.5], m), 1.0)
        paid = np.round(list_price * discount).astype(int)
        txd = exp - _days(plan)
        cancel = (older & (rng.uniform(size=m) < np.minimum(cancels[has], 3) * 0.04)).astype(int)
        method = rng.choice([36, 38, 39, 40, 41], m)
        frames.append(
            _tx(msno[has], plan, list_price, paid, auto_renew[has], txd, exp, cancel, method)
        )
    history = pd.concat(frames, ignore_index=True)
    dup = history.sample(frac=0.01, random_state=int(rng.integers(0, 2**31 - 1)))
    history = pd.concat([history, dup], ignore_index=True)  # same-day duplicates

    def renewals(
        cohort: np.ndarray, expiry: pd.DatetimeIndex, churn: np.ndarray, floor: pd.Timestamp
    ):
        """Renewals within 30 days for non-churners (never before the as-of date) and late
        returns 31 to 60 days after expiry for a fifth of churners."""
        stay = cohort & ~churn
        when = expiry + _days(rng.integers(-3, 30, n))
        when = pd.DatetimeIndex(np.where(when < floor, floor, when))
        back = cohort & churn & (rng.uniform(size=n) < 0.2)
        late = expiry + _days(rng.integers(31, 61, n))
        rows = []
        for mask, dates in ((stay, when), (back, late)):
            d = dates[mask]
            rows.append(
                _tx(
                    msno[mask],
                    30,
                    price[mask],
                    price[mask],
                    auto_renew[mask],
                    d,
                    d + _days(np.full(len(d), 30)),
                    0,
                    41,
                )
            )
        return pd.concat(rows, ignore_index=True), stay, when

    feb_cohort = ~march_only
    feb_rows, feb_stay, feb_when = renewals(feb_cohort, feb_expiry, feb_churn, FEB_START)
    # March cohort: February stayers whose renewal expires in March, plus March-only members
    renewed_expiry = feb_when + _days(np.full(n, 30))
    mar_expiry = pd.DatetimeIndex(np.where(march_only, first_expiry, renewed_expiry))
    mar_cohort = march_only | (feb_stay & (renewed_expiry <= MAR_END))
    mar_rows, _, _ = renewals(mar_cohort, mar_expiry, mar_churn, MAR_START)

    all_tx = pd.concat([history, feb_rows, mar_rows], ignore_index=True)
    feb_cut, mar_cut = _ymd(FEB_END.date()), _ymd(MAR_END.date())
    order = ["msno", "transaction_date", "membership_expire_date"]
    tx_main = all_tx[all_tx["transaction_date"] <= feb_cut].sort_values(order, kind="mergesort")
    in_march = (all_tx["transaction_date"] > feb_cut) & (all_tx["transaction_date"] <= mar_cut)
    tx_v2 = all_tx[in_march].sort_values(order, kind="mergesort")

    def logs(days: pd.DatetimeIndex, t0: float, who: np.ndarray) -> pd.DataFrame:
        out_frames = []
        for i, day in enumerate(days):
            frac = (i / max(len(days) - 1, 1)) + t0
            scale = np.clip(1 + trend * frac, 0.05, None)
            active = who & (rng.uniform(size=n) < spec.log_days_fraction * np.clip(scale, 0.1, 1.5))
            k = int(active.sum())
            if not k:
                continue
            songs = rng.poisson(engagement[active] * scale[active])
            secs = np.round(songs * rng.uniform(180, 260, k), 3)
            secs[rng.uniform(size=k) < 0.001] = -9.2e15  # the real logs hold impossible values too
            out_frames.append(
                pd.DataFrame(
                    {
                        "msno": msno[active],
                        "date": _ymd(day.date()),
                        "num_25": rng.binomial(songs, 0.15),
                        "num_50": rng.binomial(songs, 0.05),
                        "num_75": rng.binomial(songs, 0.04),
                        "num_985": rng.binomial(songs, 0.04),
                        "num_100": rng.binomial(songs, 0.72),
                        "num_unq": np.maximum(1, (songs * rng.uniform(0.5, 0.9, k)).astype(int)),
                        "total_secs": secs,
                    }
                )
            )
        return pd.concat(out_frames, ignore_index=True)

    started = pd.DatetimeIndex(reg)
    logs_main = logs(pd.date_range(LOG_START, FEB_END, freq="D"), -0.5, np.ones(n, dtype=bool))
    log_day = pd.to_datetime(logs_main["date"].astype(str), format="%Y%m%d").to_numpy()
    member_start = started[pd.Index(msno).get_indexer(logs_main["msno"])].to_numpy()
    logs_main = logs_main[log_day >= member_start]  # no listening before registration
    logs_v2 = logs(pd.date_range(MAR_START, MAR_END, freq="D"), 0.5, mar_cohort)

    train = pd.DataFrame({"msno": msno[feb_cohort], "is_churn": feb_churn[feb_cohort].astype(int)})
    train_v2 = pd.DataFrame(
        {"msno": msno[mar_cohort], "is_churn": mar_churn[mar_cohort].astype(int)}
    )
    frames_out = {
        "members_v3.csv": members,
        "transactions.csv": tx_main,
        "transactions_v2.csv": tx_v2,
        "user_logs.csv": logs_main,
        "user_logs_v2.csv": logs_v2,
        "train.csv": train,
        "train_v2.csv": train_v2,
    }
    paths = {}
    for name, df in frames_out.items():
        p = out / name
        df.to_csv(p, index=False, lineterminator="\n")
        paths[name] = p
    return paths


def write_synthetic(data_dir: Path, spec: SyntheticSpec = SyntheticSpec()) -> dict:
    """`offers data synthetic`: generate into a staging folder, verify, then install into
    `data_dir/raw` only if that folder is empty or already marked synthetic. Real KKBox data
    is never overwritten (N1.2 verifier)."""
    from respectful_offers.data.download import install
    from respectful_offers.data.verify import DataError, read_manifest, verify

    data_dir = Path(data_dir)
    raw, manifest_path = data_dir / "raw", data_dir / "manifest.json"
    existing = read_manifest(manifest_path)
    occupied = raw.is_dir() and any(raw.iterdir())
    if occupied and (existing is None or existing.get("source") != "synthetic"):
        raise DataError(f"{raw} holds data that is not marked synthetic; use another --data-dir")
    staging = data_dir / ".synthetic"
    if staging.exists():
        shutil.rmtree(staging)
    generate(staging / "raw", spec)
    verify(staging / "raw", staging / "manifest.json", source="synthetic")
    (staging / "manifest.json").replace(manifest_path)
    install(staging / "raw", raw)
    staging.rmdir()
    return verify(raw, manifest_path, source="synthetic")
