"""The KKBox churn competition's file layout (Tech Spec §9). Written out from the competition's
data page; N1.5 checks it against the real files and records the real date ranges."""

from __future__ import annotations

COMPETITION = "kkbox-churn-prediction-challenge"
RULES_URL = f"https://www.kaggle.com/competitions/{COMPETITION}/rules"

COLUMNS: dict[str, tuple[str, ...]] = {
    "members_v3.csv": (
        "msno", "city", "bd", "gender", "registered_via", "registration_init_time",
    ),
    "transactions.csv": (
        "msno", "payment_method_id", "payment_plan_days", "plan_list_price",
        "actual_amount_paid", "is_auto_renew", "transaction_date", "membership_expire_date",
        "is_cancel",
    ),
    "user_logs.csv": (
        "msno", "date", "num_25", "num_50", "num_75", "num_985", "num_100", "num_unq",
        "total_secs",
    ),
    "train.csv": ("msno", "is_churn"),
}  # fmt: skip
COLUMNS["transactions_v2.csv"] = COLUMNS["transactions.csv"]
COLUMNS["user_logs_v2.csv"] = COLUMNS["user_logs.csv"]
COLUMNS["train_v2.csv"] = COLUMNS["train.csv"]

DATE_COLUMNS: dict[str, tuple[str, ...]] = {
    "members_v3.csv": ("registration_init_time",),
    "transactions.csv": ("transaction_date", "membership_expire_date"),
    "transactions_v2.csv": ("transaction_date", "membership_expire_date"),
    "user_logs.csv": ("date",),
    "user_logs_v2.csv": ("date",),
}
REQUIRED = tuple(COLUMNS)

# DuckDB types for reading each file with an explicit schema (no sniffing, so an empty or
# oddly formatted file can never change how columns are typed).
_TYPES = {
    "msno": "VARCHAR", "gender": "VARCHAR", "total_secs": "DOUBLE",
}  # fmt: skip


def duckdb_columns(name: str) -> str:
    """`columns={...}` argument for duckdb.read_csv: BIGINT unless listed in `_TYPES`."""
    return "{" + ", ".join(f"'{c}': '{_TYPES.get(c, 'BIGINT')}'" for c in COLUMNS[name]) + "}"
