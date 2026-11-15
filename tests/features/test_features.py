import datetime as dt
import json

import pandas as pd
import pytest

from respectful_offers.cli import main
from respectful_offers.data.kkbox import COLUMNS
from respectful_offers.data.synthetic import SyntheticSpec, generate
from respectful_offers.features.build import (
    LeakageError,
    build_audit_attributes,
    build_cohort,
    check_provenance,
)
from respectful_offers.features.stage import load_features_table
from respectful_offers.schemas import FEATURES, ConfigError, load_run_config
from tests.schemas.conftest import FIX


def write_raw(d, members, tx, tx2=(), logs=(), logs2=(), train=(), train2=()):
    d.mkdir(parents=True, exist_ok=True)
    frames = {
        "members_v3.csv": members,
        "transactions.csv": tx,
        "transactions_v2.csv": tx2,
        "user_logs.csv": logs,
        "user_logs_v2.csv": logs2,
        "train.csv": train,
        "train_v2.csv": train2,
    }
    for name, rows in frames.items():
        pd.DataFrame(list(rows), columns=list(COLUMNS[name])).to_csv(d / name, index=False)
    return d


def t(msno, txd, exp, plan=30, price=149, paid=149, auto: int | None = 1, cancel=0):
    return (msno, 41, plan, price, paid, auto, txd, exp, cancel)


def log(msno, date, songs):
    return (msno, date, 0, 0, 0, 0, songs, songs, songs * 200.0)


@pytest.fixture
def hand(tmp_path):
    members = [("A", 1, 30, "male", 7, 20160101), ("B", 1, 0, "", 7, 20161201)]
    tx = [
        t("A", 20161201, 20170101),
        t("A", 20170101, 20170201, plan=30, price=149, paid=99, auto=0),
        t("A", 20170101, 20170201, auto=1, cancel=1),  # same day, expiry tie: non-cancel wins
        t("A", 20161020, 20161119, cancel=1),  # cancellation 104 days before as_of: outside window
        t("A", 20161105, 20161205, cancel=1),  # 88 days before: inside
        t("B", 20161215, 20170214, plan=60, price=298, paid=298),
        t("C", 20170105, 20170204),  # C has no members_v3 row
    ]
    logs = [log("A", 20161210, 40), log("A", 20170115, 10), log("B", 20170120, 30)]
    train = [("A", 1), ("B", 0), ("C", 0)]
    return write_raw(tmp_path / "raw", members, tx, logs=logs, train=train, train2=[("A", 0)])


def test_each_feature_equals_its_hand_computed_value(hand):
    f = build_cohort(hand, "feb").features.set_index("msno")
    a, b, c = (f.loc[k].to_dict() for k in ("A", "B", "C"))
    assert a["tenure_days"] == (dt.date(2017, 2, 1) - dt.date(2016, 1, 1)).days
    assert (
        not a["auto_renew"] and a["price_30d"] == 99.0 and a["plan_days"] == 30
    )  # non-cancel row wins
    assert a["cancels_90d"] == 2  # the January cancel row and the one 88 days back; 104 days is out
    assert a["listening_trend_30d"] == pytest.approx((10 - 40) / 40)
    assert (
        b["tenure_days"] == 62 and b["price_30d"] == pytest.approx(149.0) and b["plan_days"] == 60
    )
    assert (
        b["listening_trend_30d"] == 5.0
    )  # 30 songs after a zero prior: (30 - 0) / 1, clipped to 5
    assert c["tenure_days"] == (dt.date(2017, 2, 1) - dt.date(2017, 1, 5)).days  # first transaction
    assert c["listening_trend_30d"] == 0.0
    assert list(f.reset_index().columns) == list(FEATURES.names)


@pytest.mark.safety
def test_events_on_or_after_as_of_never_change_a_feature(tmp_path, hand):
    base = build_cohort(hand, "feb").features
    noisy = tmp_path / "noisy"
    noisy.mkdir()
    for name in COLUMNS:
        (noisy / name).write_bytes((hand / name).read_bytes())
    tx = pd.read_csv(noisy / "transactions.csv")
    extra = pd.DataFrame(
        [
            t("A", 20170201, 20170303, auto=0, price=1, paid=1, cancel=1),
            t("B", 20170227, 20170329, auto=0),
        ],
        columns=tx.columns,
    )
    pd.concat([tx, extra]).to_csv(noisy / "transactions.csv", index=False)
    pd.DataFrame(
        [log("A", 20170201, 999), log("B", 20170215, 999)], columns=list(COLUMNS["user_logs.csv"])
    ).to_csv(noisy / "user_logs_v2.csv", index=False)
    pd.testing.assert_frame_equal(build_cohort(noisy, "feb").features, base)


@pytest.mark.safety
def test_provenance_is_before_as_of_and_a_planted_leak_is_refused(hand):
    cf = build_cohort(hand, "feb")
    assert all(v is None or v < 20170201 for v in cf.provenance.values())
    with pytest.raises(LeakageError, match="any_later_transaction"):
        check_provenance({**cf.provenance, "any_later_transaction": 20170215}, cf.as_of)


@pytest.mark.safety
def test_early_renewals_are_excluded_and_counted(tmp_path):
    raw = write_raw(
        tmp_path / "r",
        [("A", 1, 30, "male", 7, 20160101)],
        [t("A", 20161220, 20170120), t("A", 20170125, 20170324, plan=58, auto=0, paid=1)],
        train=[("A", 0)],
        train2=[],
    )
    cf = build_cohort(raw, "feb")
    assert cf.early_renewal_rows == 1
    row = cf.features.iloc[0].to_dict()
    assert row["auto_renew"] and row["price_30d"] == 149.0  # from the January row, not the renewal


def test_cohorts_carry_their_own_labels(hand):
    feb = build_cohort(hand, "feb").features.set_index("msno")
    mar = build_cohort(hand, "mar").features.set_index("msno")
    assert bool(feb.loc["A", "churn_label"]) and not bool(mar.loc["A", "churn_label"])
    assert set(mar.index) == {"A"} and set(feb["cohort"]) == {"feb"}


def test_members_without_history_are_dropped_and_counted(tmp_path):
    raw = write_raw(tmp_path / "r", [], [t("A", 20170101, 20170201)], train=[("A", 0), ("Z", 1)])
    cf = build_cohort(raw, "feb")
    assert list(cf.features["msno"]) == ["A"] and cf.dropped_no_history == 1


@pytest.mark.safety
def test_age_and_gender_live_only_in_the_audit_table(hand):
    f = build_cohort(hand, "feb").features
    assert not {"bd", "age", "gender", "city", "registered_via"} & set(f.columns)
    audit = build_audit_attributes(hand, f["msno"]).set_index("msno")
    a = audit.loc["A"].to_dict()
    b = audit.loc["B"].to_dict()
    assert a["age_band"] == "25-34" and a["gender"] == "male"
    assert b["age_band"] == "unknown" and b["gender"] == "unknown"
    c = audit.loc["C"].to_dict()  # no members_v3 row: listed, as unknown, never dropped
    assert c["age_band"] == "unknown" and c["gender"] == "unknown"
    assert set(audit.index) == set(f["msno"])


def test_protected_attributes_cannot_be_decision_features(tmp_path):
    text = (
        (FIX / "run_config.yaml")
        .read_text(encoding="utf-8")
        .replace("decision_features: [churn_risk", "decision_features: [bd, churn_risk")
    )
    p = tmp_path / "c.yaml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="protected"):
        load_run_config(p)


def test_synthetic_cohorts_build_and_learnable(tmp_path):
    raw = tmp_path / "raw"
    generate(raw, SyntheticSpec(n_members=3000, seed=4))
    from sklearn.metrics import roc_auc_score

    for cohort in ("feb", "mar"):
        cf = build_cohort(raw, cohort)
        f = cf.features
        labels = pd.read_csv(raw / ("train.csv" if cohort == "feb" else "train_v2.csv"))
        assert len(f) + cf.dropped_no_history == len(labels)
        assert f["msno"].is_unique and cf.early_renewal_rows == 0
        assert roc_auc_score(f["churn_label"], ~f["auto_renew"]) > 0.6


def test_cli_builds_once_then_reuses_the_cache(tmp_path, capsys):
    assert (
        main(["data", "synthetic", "--data-dir", str(tmp_path / "data"), "--members", "500"]) == 0
    )
    capsys.readouterr()
    args = ["features", "--data-dir", str(tmp_path / "data"), "--root", str(tmp_path), "--json"]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["source"] == "synthetic" and first["stats"]["feb"]["members"] > 0
    assert main(args) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["artifact"] == first["artifact"]
    run = json.loads((tmp_path / "runs" / "features" / "run.json").read_text(encoding="utf-8"))
    assert [s for s in run["stages"] if s["stage"] == "features"][-1]["cache_hit"]


def test_cli_without_data_exits_3(tmp_path, capsys):
    assert main(["features", "--data-dir", str(tmp_path / "none"), "--root", str(tmp_path)]) == 3
    assert "offers data" in capsys.readouterr().out


def user_table():
    return pd.DataFrame(
        {
            "msno": ["u1", "u2", "u3"],
            "cohort": ["feb", "feb", "mar"],
            "as_of": ["2017-02-01", "2017-02-01", "2017-03-01"],
            "tenure_days": [10, 400, 50],
            "auto_renew": ["true", "false", "1"],
            "cancels_90d": [0, 1, 0],
            "listening_trend_30d": [0.1, -0.5, 0.0],
            "price_30d": [149.0, 99.0, 129.0],
            "plan_days": [30, 30, 30],
            "churn_label": ["false", "true", "0"],
        }
    )


def test_your_own_table_loads_from_csv_and_parquet(tmp_path, capsys):
    p = tmp_path / "mine.csv"
    user_table().to_csv(p, index=False)
    df = load_features_table(p)
    assert df["auto_renew"].tolist() == [True, False, True]
    assert df["as_of"].iloc[0] == dt.date(2017, 2, 1)
    q = tmp_path / "mine.parquet"
    df.to_parquet(q)
    assert len(load_features_table(q)) == 3
    # the CLI also applies the cohort rules every command on a table needs (B2.2)
    assert main(["features", "--from-table", str(p), "--json"]) == 2
    assert "need both churners and renewers" in json.loads(capsys.readouterr().out)["error"]
    full = pd.concat([user_table(), user_table().iloc[[2]].assign(msno="u4", churn_label="1")])
    full.to_csv(p, index=False)
    assert main(["features", "--from-table", str(p), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["members"] == {"feb": 2, "mar": 2}


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda d: d.assign(auto_renew=["true", "maybe", "1"]), r"row 3: column auto_renew"),
        (
            lambda d: d.assign(as_of=["2017-02-01", "01/02/2017", "2017-03-01"]),
            r"row 3: column as_of",
        ),
        (lambda d: d.assign(tenure_days=[10, -4, 50]), r"row 3 \(msno u2\): column tenure_days"),
        (lambda d: d.drop(columns=["price_30d"]), "missing column"),
        (
            lambda d: d.assign(msno=["u1", "u1", "u3"]),
            r"row 3: column msno: .u1. appears twice in cohort .feb.",
        ),
    ],
)
def test_your_own_table_errors_name_row_and_column(tmp_path, change, match):
    from respectful_offers.schemas import ContractError

    p = tmp_path / "mine.csv"
    change(user_table()).to_csv(p, index=False)
    with pytest.raises(ContractError, match=match):
        load_features_table(p)


def test_the_90_day_window_edge_is_inclusive(tmp_path):
    raw = write_raw(
        tmp_path / "r",
        [("A", 1, 30, "male", 7, 20160101)],
        [
            t("A", 20161103, 20161203, cancel=1),
            t("A", 20161102, 20161202, cancel=1),
            t("A", 20170101, 20170201),
        ],
        train=[("A", 0)],
    )
    # as_of 2017-02-01 minus 90 days is 2016-11-03: counted; 2016-11-02 is not
    assert build_cohort(raw, "feb").features.iloc[0]["cancels_90d"] == 1


def test_a_member_only_in_train_v2_is_only_in_march(tmp_path):
    raw = write_raw(
        tmp_path / "r",
        [],
        [t("A", 20170101, 20170201), t("Z", 20170210, 20170312)],
        train=[("A", 0)],
        train2=[("A", 0), ("Z", 1)],
    )
    assert build_cohort(raw, "feb").features["msno"].tolist() == ["A"]
    assert build_cohort(raw, "mar").features["msno"].tolist() == ["A", "Z"]


def test_duplicate_members_in_a_label_file_are_refused(tmp_path):
    from respectful_offers.data.verify import DataError

    raw = write_raw(tmp_path / "r", [], [t("A", 20170101, 20170201)], train=[("A", 1), ("A", 1)])
    with pytest.raises(DataError, match="more than once"):
        build_cohort(raw, "feb")


def test_latest_transaction_ties_break_deterministically(tmp_path):
    rows = [
        t("A", 20170101, 20170201, auto=0, paid=99),
        t("A", 20170101, 20170201, auto=1, paid=149),
    ]
    a = write_raw(tmp_path / "a", [], rows, train=[("A", 0)])
    b = write_raw(tmp_path / "b", [], rows[::-1], train=[("A", 0)])
    fa, fb = build_cohort(a, "feb").features, build_cohort(b, "feb").features
    pd.testing.assert_frame_equal(fa, fb)
    assert fa.iloc[0]["price_30d"] == 149.0  # higher amount paid wins the tie


def test_members_with_only_excluded_rows_are_counted_apart(tmp_path):
    raw = write_raw(
        tmp_path / "r",
        [],
        [t("A", 20170101, 20170201), t("B", 20170125, 20170324)],
        train=[("A", 0), ("B", 0), ("Z", 1)],
    )
    cf = build_cohort(raw, "feb")
    assert cf.dropped_no_history == 1 and cf.dropped_only_excluded_rows == 1


def test_the_stage_refuses_raw_files_changed_after_verify(tmp_path):
    from respectful_offers.data.verify import DataError

    assert (
        main(["data", "synthetic", "--data-dir", str(tmp_path / "data"), "--members", "300"]) == 0
    )
    train = tmp_path / "data" / "raw" / "train.csv"
    text = train.read_text(encoding="utf-8")
    swapped = text.replace(",0\n", ",X\n").replace(",1\n", ",0\n").replace(",X\n", ",1\n")
    train.write_text(swapped, encoding="utf-8")  # same size, labels flipped
    from respectful_offers.features.stage import FeaturesStage
    from respectful_offers.runtime import RunContext, import_artifact, run_stage

    ctx = RunContext(tmp_path / "fresh", "r", "features", 0)
    src = import_artifact(ctx, "manifest", {"manifest.json": tmp_path / "data" / "manifest.json"})
    with pytest.raises(DataError, match="differs from the verified manifest"):
        run_stage(FeaturesStage(tmp_path / "data" / "raw"), {"manifest": src}, ctx)


def test_a_member_may_appear_once_in_each_cohort(tmp_path):
    p = tmp_path / "mine.csv"
    user_table().assign(msno=["u1", "u2", "u1"]).to_csv(p, index=False)
    assert len(load_features_table(p)) == 3


def test_loader_messages_for_extra_columns_and_parquet_booleans(tmp_path):
    from respectful_offers.schemas import ContractError

    p = tmp_path / "x.csv"
    user_table().assign(age=[1, 2, 3]).to_csv(p, index=False)
    with pytest.raises(ContractError, match=r"unexpected column\(s\) \['age'\]"):
        load_features_table(p)
    q = tmp_path / "b.parquet"
    user_table().assign(auto_renew=[1.0, 0.0, 1.0], churn_label=[0.0, 1.0, 0.0]).to_parquet(q)
    assert load_features_table(q)["auto_renew"].tolist() == [True, False, True]
    bad = tmp_path / "bad.parquet"
    user_table().assign(auto_renew=["true", "maybe", "1"]).to_parquet(bad)
    with pytest.raises(ContractError, match=r"bad.parquet: row 2: column auto_renew"):
        load_features_table(bad)


def test_duplicate_profiles_are_refused_not_multiplied(tmp_path):
    from respectful_offers.data.verify import DataError

    profile = ("A", 1, 30, "male", 7, 20160101)
    raw = write_raw(
        tmp_path / "r", [profile, profile], [t("A", 20170101, 20170201)], train=[("A", 0)]
    )
    with pytest.raises(DataError, match=r"members_v3\.csv"):
        build_cohort(raw, "feb")
    with pytest.raises(DataError, match=r"members_v3\.csv"):
        build_audit_attributes(raw, pd.Series(["A"]))


def test_a_missing_auto_renew_flag_names_the_column(tmp_path):
    from respectful_offers.data.verify import DataError

    raw = write_raw(tmp_path / "r", [], [t("A", 20170101, 20170201, auto=None)], train=[("A", 0)])
    with pytest.raises(DataError, match="is_auto_renew"):
        build_cohort(raw, "feb")


def test_timestamps_with_a_time_of_day_are_refused(tmp_path):
    from respectful_offers.schemas import ContractError

    q = tmp_path / "t.parquet"
    df = user_table()
    df["as_of"] = pd.to_datetime(["2017-02-01", "2017-02-01 13:45", "2017-03-01"], format="ISO8601")
    df.to_parquet(q)
    with pytest.raises(ContractError, match=r"row 2: column as_of.*time of day"):
        load_features_table(q)
