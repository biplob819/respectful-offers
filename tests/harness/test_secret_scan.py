import pytest

import secret_scan

FAKES = {
    "anthropic key": "sk-ant-" + "a1B2" * 10,
    "openai key": "sk-proj-" + "Z9y8" * 10,
    "aws access key": "AKIA" + "ABCDEFGHIJKLMNOP",
    "github token": "ghp_" + "x" * 36,
    "pypi token": "pypi-" + "A" * 60,
    "private key": "-----BEGIN RSA " + "PRIVATE KEY-----",
    "kaggle key": '{"username": "someone", "key": "' + "0123456789abcdef" * 2 + '"}',
}
MORE = {
    "github fine-grained token": "github_pat_" + "A1b2" * 15,
    "aws access key (session)": "ASIA" + "ABCDEFGHIJKLMNOP",
    "aws secret key": "aws_secret_access_key = " + "a/B+" * 10,
    "encrypted private key": "-----BEGIN ENCRYPTED " + "PRIVATE KEY-----",
    "dsa private key": "-----BEGIN DSA " + "PRIVATE KEY-----",
    "pgp private key": "-----BEGIN PGP " + "PRIVATE KEY BLOCK-----",
    "kaggle env key": "KAGGLE_KEY=" + "a1" * 16,
    "kaggle single-quoted json": "{'username': 'someone', 'key': '" + "b2" * 16 + "'}",
    "kaggle yaml": "kaggle_key: " + "c3" * 16,
    "kaggle api token": "KGAT_" + "Ab3d" * 8,
}


def test_self_test_passes():
    assert secret_scan.self_test() == 0


@pytest.mark.parametrize("kind", sorted(FAKES))
def test_detects_each_kind(tmp_path, kind):
    f = tmp_path / "leak.txt"
    f.write_text(f"value = {FAKES[kind]}\n", encoding="utf-8")
    hits = secret_scan.scan([f])
    assert hits and kind in hits[0]


@pytest.mark.parametrize("label", sorted(MORE))
def test_detects_formats_found_by_the_verifier(tmp_path, label):
    f = tmp_path / ".env.example"
    f.write_text(f"{MORE[label]}\n", encoding="utf-8")
    assert secret_scan.scan([f]), label


def test_non_utf8_file_is_still_scanned(tmp_path):
    f = tmp_path / "latin1.txt"
    f.write_bytes(b"caf\xe9 " + FAKES["anthropic key"].encode() + b"\n")
    assert secret_scan.scan([f])


def test_scan_is_deterministic(tmp_path):
    for i, kind in enumerate(sorted(FAKES)):
        (tmp_path / f"f{i}.txt").write_text(FAKES[kind] + "\n", encoding="utf-8")
    files = sorted(tmp_path.iterdir())
    assert secret_scan.scan(files) == secret_scan.scan(files)
    assert len(secret_scan.scan(files)) == len(FAKES)


def test_env_var_reference_is_clean(tmp_path):
    f = tmp_path / "ok.py"
    f.write_text('key = os.environ["OPENAI_API_KEY"]\n', encoding="utf-8")
    assert secret_scan.scan([f]) == []


@pytest.mark.safety
def test_live_repo_has_no_secrets():
    assert secret_scan.scan(secret_scan.candidate_files(secret_scan.ROOT)) == []


def test_an_md5_cache_key_is_not_a_kaggle_key(tmp_path):
    f = tmp_path / "cache.json"
    f.write_text('{"key": "' + "d41d8cd98f00b204e9800998ecf8427e" + '"}\n', encoding="utf-8")
    assert secret_scan.scan([f]) == []


def test_pretty_printed_and_key_first_kaggle_json_are_caught(tmp_path):
    hexkey = "0a1b2c3d4e5f60718293a4b5c6d7e8f9"
    pretty = tmp_path / "kaggle.json"
    pretty.write_text(
        '{\n  "username": "someone",\n  "key": "' + hexkey + '"\n}\n', encoding="utf-8"
    )
    first = tmp_path / "k2.json"
    first.write_text('{"key": "' + hexkey + '", "username": "someone"}', encoding="utf-8")
    assert secret_scan.scan([pretty]) and secret_scan.scan([first])


def test_a_kaggle_checksum_is_not_a_key(tmp_path):
    f = tmp_path / "manifest.yaml"
    f.write_text("kaggle_sha: 0a1b2c3d4e5f60718293a4b5c6d7e8f9\n", encoding="utf-8")
    assert secret_scan.scan([f]) == []
