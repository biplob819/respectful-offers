import ast
import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

import data_scan
from harness_lib import ROOT
from respectful_offers.cli import main
from respectful_offers.data import download as dl
from respectful_offers.data.kkbox import COLUMNS, REQUIRED
from respectful_offers.data.synthetic import SyntheticSpec, generate
from respectful_offers.data.verify import DataError, verify

SMALL = SyntheticSpec(n_members=600, seed=7)


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    d = tmp_path_factory.mktemp("raw")
    generate(d, SMALL)
    return d


def test_synthetic_files_have_the_competition_columns(synth):
    for name in REQUIRED:
        assert tuple(pd.read_csv(synth / name, nrows=1).columns) == COLUMNS[name], name


def test_synthetic_is_deterministic_per_seed(tmp_path, synth):
    generate(tmp_path / "a", SMALL)
    generate(tmp_path / "b", SyntheticSpec(n_members=600, seed=8))
    for name in REQUIRED:
        assert (tmp_path / "a" / name).read_bytes() == (synth / name).read_bytes()
    assert (tmp_path / "b" / "train.csv").read_bytes() != (synth / "train.csv").read_bytes()


def test_synthetic_dates_follow_the_file_split(synth):
    tx = pd.read_csv(synth / "transactions.csv")
    tx2 = pd.read_csv(synth / "transactions_v2.csv")
    logs = pd.read_csv(synth / "user_logs.csv")
    logs2 = pd.read_csv(synth / "user_logs_v2.csv")
    assert tx["transaction_date"].max() <= 20170228 and logs["date"].max() <= 20170228
    assert tx2["transaction_date"].between(20170301, 20170331).all()
    assert logs2["date"].between(20170301, 20170331).all()
    for col in ("transaction_date", "membership_expire_date"):
        pd.to_datetime(tx[col].astype(str), format="%Y%m%d")  # valid YYYYMMDD


def test_synthetic_labels_follow_the_competition_definition(synth):
    train = pd.read_csv(synth / "train.csv")
    tx = pd.concat(
        [pd.read_csv(synth / "transactions.csv"), pd.read_csv(synth / "transactions_v2.csv")]
    )
    tx["td"] = pd.to_datetime(tx["transaction_date"].astype(str), format="%Y%m%d")
    tx["ed"] = pd.to_datetime(tx["membership_expire_date"].astype(str), format="%Y%m%d")
    feb = tx[(tx["ed"] >= "2017-02-01") & (tx["ed"] <= "2017-02-28")].groupby("msno")["ed"].max()
    later = tx[tx["ed"] > "2017-02-28"].groupby("msno")["td"].min()
    j = train.set_index("msno").join(feb.rename("feb_exp")).join(later.rename("renew"))
    renewed = (j["renew"] - j["feb_exp"]).dt.days.le(30) & j["renew"].notna()
    assert ((j["is_churn"] == 1) == ~renewed).all()
    rates = [train["is_churn"].mean(), pd.read_csv(synth / "train_v2.csv")["is_churn"].mean()]
    assert all(0.03 <= r <= 0.12 for r in rates), rates


def test_synthetic_churn_is_learnable(tmp_path):
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score

    d = tmp_path / "big"
    generate(d, SyntheticSpec(n_members=4000, seed=3))
    train = pd.read_csv(d / "train.csv")
    tx = pd.read_csv(d / "transactions.csv")
    tx = tx[tx["transaction_date"] < 20170201]
    last = tx.sort_values("transaction_date").groupby("msno").tail(1).set_index("msno")
    x = train.join(last[["is_auto_renew", "plan_list_price"]], on="msno").fillna(0)
    model = LogisticRegression().fit(x[["is_auto_renew", "plan_list_price"]], x["is_churn"])
    auc = roc_auc_score(
        x["is_churn"], model.predict_proba(x[["is_auto_renew", "plan_list_price"]])[:, 1]
    )
    assert auc > 0.7


@pytest.mark.safety
def test_synthetic_ids_never_look_like_kkbox_ids(synth):
    assert data_scan.scan(sorted(synth.iterdir()), synth) == [
        f"{n}: KKBox raw file name" for n in sorted(REQUIRED)
    ]  # refused by name if ever staged, and never by member id
    ids = pd.read_csv(synth / "members_v3.csv")["msno"]
    assert not ids.str.fullmatch(r"[A-Za-z0-9+/]{43}=").any()


def test_verify_records_everything_and_detects_changes(tmp_path, synth):
    raw = tmp_path / "raw"
    raw.mkdir()
    for name in REQUIRED:
        (raw / name).write_bytes((synth / name).read_bytes())
    m = verify(raw, tmp_path / "manifest.json")
    f = m["files"]["transactions.csv"]
    assert len(f["sha256"]) == 64 and f["rows"] == len(pd.read_csv(raw / "transactions.csv"))
    assert f["date_ranges"]["transaction_date"][1] <= 20170228
    assert f["columns"] == list(COLUMNS["transactions.csv"])
    with (raw / "train.csv").open("a", encoding="utf-8") as fh:
        fh.write("S999999,0\n")
    with pytest.raises(DataError, match=r"changed since the manifest.*train.csv"):
        verify(raw, tmp_path / "manifest.json")


def test_verify_names_missing_files_and_wrong_columns(tmp_path, synth):
    raw = tmp_path / "raw"
    raw.mkdir()
    with pytest.raises(DataError, match="offers data download"):
        verify(raw)
    for name in REQUIRED:
        (raw / name).write_bytes((synth / name).read_bytes())
    pd.read_csv(raw / "train.csv").rename(columns={"is_churn": "churn"}).to_csv(
        raw / "train.csv", index=False
    )
    with pytest.raises(DataError, match=r"train.csv: header"):
        verify(raw, tmp_path / "m.json")


class FakeKaggle:
    """Serves a bundle zip holding one zip per file, like the competition download."""

    def __init__(self, src: Path, evil: bool = False):
        self.src, self.evil = src, evil

    def download_competition(self, competition: str, dest: Path) -> None:
        assert competition == "kkbox-churn-prediction-challenge"
        bundle = dest / f"{competition}.zip"
        with zipfile.ZipFile(bundle, "w") as outer:
            for name in REQUIRED:
                inner = dest / f"{name}.zip"
                with zipfile.ZipFile(inner, "w") as z:
                    z.write(self.src / name, arcname=f"data/churn_comp_refresh/{name}")
                outer.write(inner, arcname=inner.name)
                inner.unlink()
            if self.evil:
                outer.writestr("../../escape.txt", "x")


def test_download_unpacks_nested_archives_and_verifies(tmp_path, synth):
    m = dl.download(tmp_path / "data", client=FakeKaggle(synth))
    names = sorted(p.name for p in (tmp_path / "data" / "raw").iterdir())
    assert names == sorted([*REQUIRED, ".source"])
    assert set(m["files"]) == set(REQUIRED)
    assert json.loads((tmp_path / "data" / "manifest.json").read_text(encoding="utf-8"))["files"]


def test_download_refuses_archives_that_escape(tmp_path, synth):
    with pytest.raises(DataError, match="unsafe path"):
        dl.download(tmp_path / "data", client=FakeKaggle(synth, evil=True))


def test_missing_credentials_name_the_fix_and_exit_3(tmp_path, monkeypatch, capsys):
    for var in ("KAGGLE_USERNAME", "KAGGLE_KEY", "KAGGLE_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("KAGGLE_CONFIG_DIR", str(tmp_path / "nowhere"))
    assert not dl.credentials_present()
    code = main(["data", "download", "--data-dir", str(tmp_path / "data"), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 3 and not out["ok"]
    assert "KAGGLE_USERNAME" in out["error"] and "rules" in out["error"]


def test_credentials_detected_without_echoing_them(tmp_path, monkeypatch):
    secret = "f" * 32
    assert dl.credentials_present({"KAGGLE_USERNAME": "u", "KAGGLE_KEY": secret})
    assert dl.credentials_present({"KAGGLE_API_TOKEN": "tok"})
    (tmp_path / ".kaggle").mkdir()
    (tmp_path / ".kaggle" / "kaggle.json").write_text("{}", encoding="utf-8")
    assert not dl.credentials_present({}, home=tmp_path)  # an empty file is not a credential
    (tmp_path / ".kaggle" / "kaggle.json").write_text(
        '{"username": "u", "key": "k"}', encoding="utf-8"
    )
    assert dl.credentials_present({}, home=tmp_path)
    (tmp_path / ".kaggle" / "kaggle.json").unlink()
    (tmp_path / ".kaggle" / "access_token").write_text("tok", encoding="utf-8")
    assert dl.credentials_present({}, home=tmp_path)


def test_kaggle_errors_map_to_actionable_messages_without_secrets(monkeypatch):
    import sys
    import types

    class Api:
        def authenticate(self):
            pass

        def competition_download_files(self, *a, **k):
            raise RuntimeError("403 Forbidden key=" + "a" * 32)

    mod = types.ModuleType("kaggle.api.kaggle_api_extended")
    mod.KaggleApi = Api  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kaggle", types.ModuleType("kaggle"))
    monkeypatch.setitem(sys.modules, "kaggle.api", types.ModuleType("kaggle.api"))
    monkeypatch.setitem(sys.modules, "kaggle.api.kaggle_api_extended", mod)
    with pytest.raises(DataError) as exc:
        dl.KaggleApiClient().download_competition("x", Path("."))
    assert "accept the competition rules" in str(exc.value).lower() and "a" * 32 not in str(
        exc.value
    )


def test_cli_synthetic_then_verify(tmp_path, capsys):
    assert main(["data", "synthetic", "--data-dir", str(tmp_path), "--members", "300"]) == 0
    assert "train.csv" in capsys.readouterr().out
    assert main(["data", "verify", "--data-dir", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"]


@pytest.mark.safety
def test_no_network_client_outside_the_download_module():
    net = {
        "requests",
        "urllib.request",
        "http.client",
        "httpx",
        "aiohttp",
        "socket",
        "kaggle",
        "urllib3",
    }
    offenders = []
    for path in (ROOT / "src" / "respectful_offers").rglob("*.py"):
        if path.name == "download.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            offenders += [
                f"{path.name}: {m}"
                for m in mods
                if any(m == n or m.startswith(n + ".") for n in net)
            ]
    assert offenders == []


def test_gitignore_covers_data_folders():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert {"/data/", "/.offers/", "/runs/"} <= set(lines)


def test_data_card_is_honest_about_pending_facts():
    text = (ROOT / "DATA_CARD.md").read_text(encoding="utf-8")
    for name in REQUIRED:
        assert name.replace("_v2", "") in text or name in text
    assert "within 30 days" in text and "2017-03-01" in text
    assert text.count("*Pending N1.5.*") >= 2
    assert "simulated" in text and "never committed" in text.lower()
    assert '"source": "synthetic"' in text and "refuses to write over" in text
    assert "exactly the KKBox formats" not in text  # the fixture's semantics are simpler


def test_synthetic_never_overwrites_real_data(tmp_path):
    from respectful_offers.data.synthetic import write_synthetic

    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "train.csv").write_text("msno,is_churn\nREAL,0\n", encoding="utf-8")
    with pytest.raises(DataError, match="not marked synthetic"):
        write_synthetic(tmp_path, SyntheticSpec(n_members=300, seed=1))
    assert (raw / "train.csv").read_text(encoding="utf-8") == "msno,is_churn\nREAL,0\n"


def test_synthetic_can_be_regenerated_and_is_marked_in_the_manifest(tmp_path):
    from respectful_offers.data.synthetic import write_synthetic

    m1 = write_synthetic(tmp_path, SyntheticSpec(n_members=300, seed=1))
    m2 = write_synthetic(tmp_path, SyntheticSpec(n_members=300, seed=2))
    on_disk = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert m1["source"] == m2["source"] == on_disk["source"] == "synthetic"
    assert m1["files"]["train.csv"]["sha256"] != m2["files"]["train.csv"]["sha256"]


def test_download_refuses_to_replace_real_data_and_is_all_or_nothing(tmp_path, synth):
    data = tmp_path / "data"
    dl.download(data, client=FakeKaggle(synth))
    with pytest.raises(DataError, match="already downloaded"):
        dl.download(data, client=FakeKaggle(synth))

    class Broken(FakeKaggle):
        def download_competition(self, competition, dest):
            super().download_competition(competition, dest)
            raise RuntimeError("connection dropped")

    other = tmp_path / "other"
    with pytest.raises(RuntimeError):
        dl.download(other, client=Broken(synth))
    assert not (other / "raw").exists() and not (other / ".download").exists()


def test_duplicate_files_in_a_download_are_refused(tmp_path, synth):
    class Decoy(FakeKaggle):
        def download_competition(self, competition, dest):
            super().download_competition(competition, dest)
            (dest / "aaa").mkdir()
            (dest / "aaa" / "train.csv").write_text("msno,is_churn\nX,1\n", encoding="utf-8")

    with pytest.raises(DataError, match=r"copies of train\.csv"):
        dl.download(tmp_path / "data", client=Decoy(synth))


def test_kaggle_exit_calls_become_data_errors(monkeypatch):
    import sys
    import types

    class Api:
        def authenticate(self):
            raise SystemExit(1)

    mod = types.ModuleType("kaggle.api.kaggle_api_extended")
    mod.KaggleApi = Api  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kaggle", types.ModuleType("kaggle"))
    monkeypatch.setitem(sys.modules, "kaggle.api", types.ModuleType("kaggle.api"))
    monkeypatch.setitem(sys.modules, "kaggle.api.kaggle_api_extended", mod)
    with pytest.raises(DataError, match="credentials"):
        dl.KaggleApiClient().download_competition("x", Path("."))


def test_the_real_kaggle_client_imports_with_the_data_extra():
    pytest.importorskip("kaggle")
    import importlib

    importlib.import_module("kaggle.api.kaggle_api_extended")  # needs `six` (in the extra)


@pytest.mark.parametrize(
    ("content", "match"),
    [
        ("msno,is_churn\n", "no rows"),
        ("msno;is_churn\nS1;0\n", "header"),
        ("msno,is_churn\nS1,0,extra\nS2,1\n", "malformed CSV"),
    ],
)
def test_verify_refuses_truncated_wrongly_delimited_and_ragged_files(
    tmp_path, synth, content, match
):
    raw = tmp_path / "raw"
    raw.mkdir()
    for name in REQUIRED:
        (raw / name).write_bytes((synth / name).read_bytes())
    (raw / "train.csv").write_text(content, encoding="utf-8")
    with pytest.raises(DataError, match=match) as exc:
        verify(raw, tmp_path / "m.json")
    assert "S2" not in str(exc.value)  # never echo row contents


def test_a_corrupt_manifest_names_the_fix(tmp_path, synth):
    raw = tmp_path / "raw"
    raw.mkdir()
    for name in REQUIRED:
        (raw / name).write_bytes((synth / name).read_bytes())
    (tmp_path / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(DataError, match=r"corrupt.*offers data verify"):
        verify(raw)


def test_fixture_holds_the_awkward_real_data_cases(synth):
    tx = pd.concat(
        [pd.read_csv(synth / "transactions.csv"), pd.read_csv(synth / "transactions_v2.csv")]
    )
    assert set(tx["payment_plan_days"]) > {30}
    assert (tx["actual_amount_paid"] < tx["plan_list_price"]).any()
    assert tx.duplicated().any()
    train = set(pd.read_csv(synth / "train.csv")["msno"])
    train_v2 = set(pd.read_csv(synth / "train_v2.csv")["msno"])
    members = set(pd.read_csv(synth / "members_v3.csv")["msno"])
    assert train_v2 - train and (train | train_v2) - members
    assert (pd.read_csv(synth / "user_logs.csv")["total_secs"] < 0).any()


def test_no_renewal_is_booked_before_the_cohort_as_of_date(synth):
    tx = pd.read_csv(synth / "transactions.csv")
    feb = set(pd.read_csv(synth / "train.csv")["msno"])
    early = tx[(tx["transaction_date"] < 20170201) & (tx["membership_expire_date"] > 20170228)]
    assert not set(early["msno"]) & feb


def test_march_only_members_never_have_a_february_expiry(synth):
    tx = pd.read_csv(synth / "transactions.csv")
    train = set(pd.read_csv(synth / "train.csv")["msno"])
    feb_expirers = set(tx[tx["membership_expire_date"].between(20170201, 20170228)]["msno"])
    assert feb_expirers <= train


@pytest.mark.parametrize("bad", ["hello", "2017-01-05"])
def test_verify_refuses_columns_of_bad_dates(tmp_path, synth, bad):
    raw = tmp_path / "raw"
    raw.mkdir()
    for name in REQUIRED:
        (raw / name).write_bytes((synth / name).read_bytes())
    tx = pd.read_csv(raw / "transactions.csv")
    tx["transaction_date"] = bad
    tx.to_csv(raw / "transactions.csv", index=False)
    with pytest.raises(DataError, match="not YYYYMMDD dates"):
        verify(raw, tmp_path / "m.json")


def test_source_survives_a_deleted_manifest(tmp_path):
    from respectful_offers.data.synthetic import write_synthetic

    write_synthetic(tmp_path, SyntheticSpec(n_members=300, seed=1))
    (tmp_path / "manifest.json").unlink()
    assert verify(tmp_path / "raw", tmp_path / "manifest.json")["source"] == "synthetic"


def test_kaggle_chatter_goes_to_stderr_so_json_stays_valid(monkeypatch, capsys):
    import sys
    import types

    class Api:
        def authenticate(self):
            print("Warning: Your Kaggle API key is readable by other users")

        def competition_download_files(self, *a, **k):
            raise RuntimeError("401 Unauthorized")

    mod = types.ModuleType("kaggle.api.kaggle_api_extended")
    mod.KaggleApi = Api  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kaggle", types.ModuleType("kaggle"))
    monkeypatch.setitem(sys.modules, "kaggle.api", types.ModuleType("kaggle.api"))
    monkeypatch.setitem(sys.modules, "kaggle.api.kaggle_api_extended", mod)
    with pytest.raises(DataError):
        dl.KaggleApiClient().download_competition("x", Path("."))
    out = capsys.readouterr()
    assert out.out == "" and "readable" in out.err
