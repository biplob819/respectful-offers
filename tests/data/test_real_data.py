"""N1.5: the real KKBox download, its facts and the licence ruling (DAT-03, DAT-07).

The real files never reach CI (they are git-ignored and too large); what CI checks is the
committed manifest of the real download, the data card that states its facts, and the
owner's ruling. `OFFERS_REAL_DATA=1` re-verifies the local real files against it.
"""

import json
import os
import re

import pytest

from harness_lib import ROOT
from respectful_offers.data.kkbox import COLUMNS, REQUIRED
from respectful_offers.data.verify import read_manifest

CARD = ROOT / "DATA_CARD.md"
MANIFEST = ROOT / "docs" / "data" / "kkbox-manifest.json"
DECISIONS = ROOT / "docs" / "decisions.md"
RULES_URL = "https://www.kaggle.com/competitions/kkbox-churn-prediction-challenge/rules"

QUOTES = (
    # section 7.A, Data Access and Use
    "you may access and use the Competition Data only for the purposes of the Competition, "
    "participation on Kaggle Website forums, academic research and education.",
    # section 7.B, Data Security
    "You agree not to transmit, duplicate, publish, redistribute or otherwise provide or make "
    "available the Data to any party not participating in the Competition.",
    # section 8.B, Public Code Sharing
    "You are permitted to publicly share source or executable code developed in connection "
    "with or based upon the Competition Data",
)


def card() -> str:
    return CARD.read_text(encoding="utf-8")


def manifest() -> dict:
    data = read_manifest(MANIFEST)
    assert data is not None, "docs/data/kkbox-manifest.json is missing"
    return data


# --- DAT-03 ---------------------------------------------------------------------------


def test_data_card_quotes_the_rules_and_the_ruling():
    text = " ".join(card().split())  # quotes may wrap
    for quote in QUOTES:
        assert quote in text, f"the data card does not quote: {quote[:60]}..."
    assert RULES_URL in text
    licence = text[text.index("## Licence") : text.index("## Synthetic fixture")]
    assert "OWNER D-46" in licence
    assert "never redistributed" in licence and "aggregate" in licence
    assert "cit" in licence  # the challenge is cited on every published output
    assert "not an explicit permission" in licence  # the ruling is a reading, said so
    assert "withdrawn" in licence


def test_decision_log_holds_the_owner_licence_ruling():
    rows = [r for r in DECISIONS.read_text(encoding="utf-8").splitlines() if r.startswith("|")]
    ruling = [r for r in rows if r.startswith("| OWNER D-46 |")]
    assert len(ruling) == 1, "exactly one OWNER D-46 row"
    cells = [c.strip() for c in ruling[0].strip("|").split("|")]
    assert len(cells) == 5 and all(cells), "ID, date, decision, alternatives, reason"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", cells[1])
    assert "never redistributed" in cells[2] and "DATA_CARD.md" in cells[2]


def test_data_card_has_no_pending_facts():
    text = card()
    assert "pending" not in text.lower(), "N1.5 fills every pending section"
    assert "docs/data/kkbox-manifest.json" in text


def test_the_ruling_states_the_disclosure_rules_the_code_enforces():
    from respectful_offers.demo.cube import MIN_CELL

    licence = " ".join(card().split())
    licence = licence[licence.index("## Licence") : licence.index("## Synthetic fixture")]
    assert f"every cell {MIN_CELL} or more members" in licence
    assert "counts rounded to fives" in licence and "three significant figures" in licence
    assert "not in git" in licence and "not in the demo" in licence


# --- DAT-07 ---------------------------------------------------------------------------


def test_committed_manifest_is_the_real_download():
    data = manifest()
    assert data["source"] == "kaggle"
    assert sorted(data["files"]) == sorted(REQUIRED)
    for name, rec in data["files"].items():
        assert tuple(rec["columns"]) == tuple(COLUMNS[name]), name
        assert re.fullmatch(r"[0-9a-f]{64}", rec["sha256"]), name
        assert rec["rows"] > 900_000, f"{name}: far fewer rows than the real file"
        assert all(n == 0 for n in rec["unparseable_dates"].values()), name
    logs = data["files"]["user_logs.csv"]
    assert logs["rows"] > 300_000_000 and logs["bytes"] > 25e9  # the ~30 GB user log
    assert logs["date_ranges"]["date"][1] == 20170228
    assert data["files"]["user_logs_v2.csv"]["date_ranges"]["date"] == [20170301, 20170331]


def test_data_card_table_matches_the_manifest():
    text = card()
    for name, rec in manifest()["files"].items():
        rows = [ln for ln in text.splitlines() if ln.startswith(f"| `{name}` |") and " MB |" in ln]
        line = rows[0] if len(rows) == 1 else None  # the verified-files table, once
        assert line is not None, f"no data card row for {name}"
        assert f"{rec['rows']:,}" in line, name
        assert rec["sha256"][:16] in line, name
        assert f"{rec['bytes'] / 1e6:,.1f} MB" in line, name
        for col, (lo, hi) in rec["date_ranges"].items():
            span = f"`{col}` {str(lo)[:4]}-{str(lo)[4:6]}-{str(lo)[6:]} to "
            span += f"{str(hi)[:4]}-{str(hi)[4:6]}-{str(hi)[6:]}"
            assert span in line, f"{name}: {col}"


def test_committed_manifest_round_trips_unchanged():
    raw = MANIFEST.read_text(encoding="utf-8")
    assert raw == json.dumps(json.loads(raw), indent=2, sort_keys=True) + "\n"  # verify's format
    assert manifest()["manifest_version"] == "1.0"


def test_committed_manifest_holds_no_member_data():
    data = manifest()
    allowed = {"bytes", "columns", "date_ranges", "rows", "sha256", "unparseable_dates"}
    assert set(data) == {"files", "manifest_version", "source"}
    for rec in data["files"].values():
        assert set(rec) == allowed
    raw = MANIFEST.read_text(encoding="utf-8")
    assert not re.search(r"[A-Za-z0-9+/]{43}=", raw), "nothing shaped like a KKBox member id"


@pytest.mark.skipif(os.environ.get("OFFERS_REAL_DATA") != "1", reason="set OFFERS_REAL_DATA=1")
def test_local_real_files_still_match_the_committed_manifest(tmp_path):
    from respectful_offers.data.verify import verify

    local = ROOT / "data" / "manifest.json"
    assert local.read_bytes() == MANIFEST.read_bytes()
    out = verify(ROOT / "data" / "raw", tmp_path / "manifest.json", source="kaggle")
    assert out == json.loads(MANIFEST.read_text(encoding="utf-8"))


@pytest.mark.skipif(os.environ.get("OFFERS_REAL_DATA") != "1", reason="set OFFERS_REAL_DATA=1")
def test_the_data_cards_real_date_facts_hold():
    import duckdb

    raw = ROOT / "data" / "raw"
    con = duckdb.connect()
    v1 = f"read_csv('{(raw / 'transactions.csv').as_posix()}', header=true, all_varchar=true)"
    v2 = f"read_csv('{(raw / 'transactions_v2.csv').as_posix()}', header=true, all_varchar=true)"

    def one(sql: str) -> int:
        return int(con.execute(sql).fetchone()[0])  # type: ignore[index]

    before_march = one(f"SELECT count(*) FROM {v2} WHERE transaction_date < '20170301'")
    overlap = one(f"SELECT count(*) FROM (SELECT * FROM {v2} INTERSECT ALL SELECT * FROM {v1})")
    dupes = one(f"SELECT count(*) FROM (SELECT * FROM {v1} EXCEPT ALL SELECT DISTINCT * FROM {v1})")
    text = card()
    assert f"{before_march:,} of its rows were booked before March" in text
    assert overlap == 0 and "No row appears in both transaction files" in text
    assert f"{dupes:,} exact duplicate rows" in text
    assert manifest()["files"]["transactions.csv"]["date_ranges"]["membership_expire_date"][0] == (
        19700101
    )
