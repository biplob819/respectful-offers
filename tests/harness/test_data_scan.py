import pytest

import data_scan
from harness_lib import ROOT
from secret_scan import candidate_files

FAKE_ID = "Bb1/" * 10 + "Qrs="  # KKBox msno shape: 43 base64 chars then "="


def test_self_test_passes():
    assert data_scan.self_test() == 0


@pytest.mark.parametrize(
    "name",
    ["members_v3.csv", "transactions.csv", "transactions_v2.csv", "user_logs.csv", "train_v2.csv"],
)
def test_every_kkbox_raw_file_name_is_refused(tmp_path, name):
    f = tmp_path / name
    f.write_text("x\n", encoding="utf-8")
    assert data_scan.scan([f], tmp_path)


@pytest.mark.parametrize("suffix", [".parquet", ".duckdb", ".feather", ".pkl"])
def test_member_level_file_types_are_refused(tmp_path, suffix):
    f = tmp_path / f"scores{suffix}"
    f.write_bytes(b"\x00")
    assert data_scan.scan([f], tmp_path)


def test_member_id_anywhere_in_a_text_file_is_refused(tmp_path):
    f = tmp_path / "report.html"
    f.write_text(f"<td>{FAKE_ID}</td>\n", encoding="utf-8")
    hits = data_scan.scan([f], tmp_path)
    assert hits and "member id" in hits[0]


def test_longer_base64_and_hex_hashes_are_not_member_ids(tmp_path):
    f = tmp_path / "hashes.txt"
    f.write_text("A" * 87 + "=\n" + "f" * 64 + "\n", encoding="utf-8")
    assert data_scan.scan([f], tmp_path) == []


@pytest.mark.safety
def test_live_repo_has_no_raw_or_member_level_data():
    assert data_scan.scan(candidate_files(ROOT)) == []


@pytest.mark.parametrize(
    "name",
    [
        "members_v3.csv.7z",
        "user_logs_v2.csv.7z",
        "train_v2.csv.gz",
        "transactions_v2.csv.zip",
        "sample_submission_zero.csv",
        "kkbox-churn-prediction-challenge.zip",
    ],
)
def test_real_kaggle_archive_names_are_refused(tmp_path, name):
    f = tmp_path / name
    f.write_bytes(b"x")
    hits = data_scan.scan([f], tmp_path)
    assert hits and "raw file name" in hits[0]


@pytest.mark.parametrize(
    "name", ["rows.csv.gz", "scores.zip", "m.xlsx", "t.sqlite", "t.db", "a.npz", "a.h5"]
)
def test_archives_and_data_files_are_refused_whatever_they_hold(tmp_path, name):
    f = tmp_path / name
    f.write_bytes(b"anything")
    assert data_scan.scan([f], tmp_path)


def test_utf16_and_url_path_member_ids_are_found(tmp_path):
    a = tmp_path / "u16.csv"
    a.write_bytes(f"msno\n{FAKE_ID}\n".encode("utf-16"))
    b = tmp_path / "link.html"
    b.write_text(f'<a href="/m/{FAKE_ID}">x</a>', encoding="utf-8")
    assert len(data_scan.scan([a, b], tmp_path)) == 2


def test_sri_hashes_are_not_member_ids(tmp_path):
    f = tmp_path / "page.html"
    f.write_text('<script integrity="sha256-' + "Q" * 43 + '="></script>', encoding="utf-8")
    assert data_scan.scan([f], tmp_path) == []


def test_publish_scan_reads_ignored_files_in_the_site(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "cube.json").write_text(f'["{FAKE_ID}"]', encoding="utf-8")
    hits = data_scan.scan_publish(site)
    assert hits and "cube.json" in hits[0]
    assert data_scan.scan_publish(tmp_path / "missing")


def test_pandas_json_with_escaped_slashes_is_caught(tmp_path):
    pd = pytest.importorskip("pandas")
    f = tmp_path / "cube.json"
    pd.DataFrame({"msno": [FAKE_ID], "p": [0.3]}).to_json(f, orient="records")
    assert "\\/" in f.read_text(encoding="utf-8")
    hits = data_scan.scan([f], tmp_path)
    assert hits and "member id" in hits[0]


def test_percent_encoded_html_entity_and_utf32_ids_are_caught(tmp_path):
    from urllib.parse import quote

    files = {
        "a.txt": quote(FAKE_ID, safe="").encode(),
        "b.html": FAKE_ID.replace("/", "&#x2F;").encode(),
        "c.csv": f"msno\n{FAKE_ID}\n".encode("utf-32"),
    }
    for name, content in files.items():
        (tmp_path / name).write_bytes(content)
    hits = data_scan.scan(sorted(tmp_path.iterdir()), tmp_path)
    assert len(hits) == 3


def test_a_pdf_needs_its_scanned_text_source(tmp_path):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.7 " + FAKE_ID.encode())
    assert data_scan.scan([pdf], tmp_path)
    (tmp_path / "report.md").write_text(f"{FAKE_ID}\n", encoding="utf-8")
    hits = data_scan.scan([pdf, tmp_path / "report.md"], tmp_path)
    assert len(hits) == 1 and "report.md" in hits[0]


@pytest.mark.parametrize("name", ["train.py", "members.py", "transactions.md", "train.yaml"])
def test_code_and_docs_named_like_raw_files_are_allowed(tmp_path, name):
    f = tmp_path / name
    f.write_text("x = 1\n", encoding="utf-8")
    assert data_scan.scan([f], tmp_path) == []


@pytest.mark.safety
def test_live_repo_scan_works_without_git(tmp_path, monkeypatch):
    import shutil

    import secret_scan

    copy = tmp_path / "copy"
    shutil.copytree(
        ROOT, copy, ignore=shutil.ignore_patterns(".git", ".venv", "data", "Portfolio notes.md")
    )
    files = secret_scan.candidate_files(copy)
    assert not any(".ruff_cache" in p.parts or ".pytest_cache" in p.parts for p in files)
    assert data_scan.scan(files, copy) == []


def test_labels_use_forward_slashes_on_every_os(tmp_path):
    site = tmp_path / "site" / "assets"
    site.mkdir(parents=True)
    (site / "cube.json").write_text(f'["{FAKE_ID}"]', encoding="utf-8")
    hits = data_scan.scan_publish(tmp_path / "site")
    assert hits and hits[0].startswith("assets/cube.json")
