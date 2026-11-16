"""DEM-04: the passkey gate's pure parts (hashing, checking, configuration, throttle)."""

import json

import pytest

from respectful_offers.demo import gate
from respectful_offers.demo.gate import PasskeyError

FAST = gate.MIN_ITERATIONS  # tests derive at the minimum; deployed hashes use ITERATIONS


def h(passkey: str) -> str:
    return gate.hash_passkey(passkey, iterations=FAST)


def test_hash_then_check_accepts_only_the_right_passkey():
    a, b = h("correct horse battery"), h("another long passkey")
    assert gate.check_passkey("correct horse battery", [a])
    assert gate.check_passkey("another long passkey", [a, b])  # any listed hash unlocks
    for wrong in ("correct horse batter", "Correct horse battery", "", " correct horse battery"):
        assert not gate.check_passkey(wrong, [a, b])
    assert not gate.check_passkey("correct horse battery", [])  # no hashes, no entry
    assert not gate.check_passkey("x" * (gate.MAX_LENGTH + 1), [a])


def test_hashes_are_salted_and_never_hold_the_passkey():
    a, b = h("correct horse battery"), h("correct horse battery")
    assert a != b  # fresh salt each time
    assert "correct" not in a and "horse" not in a
    assert gate.hash_passkey("correct horse battery").split("$")[1] == str(gate.ITERATIONS)
    assert gate.ITERATIONS >= 600_000  # OWASP 2023 guidance for PBKDF2-SHA256


def test_weak_passkeys_and_settings_are_refused():
    with pytest.raises(PasskeyError, match="at least 12"):
        gate.hash_passkey("short")
    with pytest.raises(PasskeyError, match="spaces"):
        gate.hash_passkey(" padded passkey here ")
    with pytest.raises(PasskeyError, match="iterations"):
        gate.hash_passkey("correct horse battery", iterations=1000)
    assert len(gate.generate_passkey()) >= 24


@pytest.mark.parametrize(
    "bad",
    [
        "plaintext-passkey",
        "md5$1$abc$def",
        "pbkdf2_sha256$1000$c2FsdHNhbHQ$" + "A" * 43,  # too few iterations
        "pbkdf2_sha256$600000$c2FsdA$" + "A" * 43,  # salt too short
        "pbkdf2_sha256$600000$c2FsdHNhbHQ$short",  # digest too short
        "pbkdf2_sha256$many$c2FsdHNhbHQ$" + "A" * 43,
    ],
)
def test_a_malformed_stored_hash_is_a_configuration_error_never_skipped(bad):
    with pytest.raises(PasskeyError):
        gate.configured_hashes({"passkey_hashes": [h("correct horse battery"), bad]}, {})
    with pytest.raises(PasskeyError):
        gate.check_passkey("correct horse battery", [bad])


def test_configuration_comes_from_secrets_then_the_environment():
    a, b = h("correct horse battery"), h("another long passkey")
    assert gate.configured_hashes({}, {}) == []
    assert gate.configured_hashes(None, {}) == []
    assert gate.configured_hashes({"passkey_hashes": a}, {}) == [a]  # one string is allowed
    assert gate.configured_hashes({"passkey_hashes": [a, " ", b]}, {}) == [a, b]
    env = {gate.HASHES_ENV: f"{a},{b}"}
    assert gate.configured_hashes({}, env) == [a, b]
    assert gate.configured_hashes({"passkey_hashes": [b]}, env) == [b]  # secrets win
    assert gate.required({gate.REQUIRE_ENV: "1"}) and not gate.required({})
    assert not gate.required({gate.REQUIRE_ENV: "true"})  # only the bundle's exact value


def test_the_throttle_blocks_after_many_failures_and_recovers():
    t = gate.Throttle(limit=3, window=10.0)
    for s in (0.0, 1.0, 2.0):
        assert not t.blocked(s)
        t.fail(s)
    assert t.blocked(3.0) and t.blocked(9.5)  # three failures within the window
    assert not t.blocked(10.5)  # the first failure has aged out: two remain
    t.fail(10.6)
    assert t.blocked(10.7)
    assert not t.blocked(30.0)  # all aged out


def test_demo_passkey_command_prints_a_hash_that_unlocks(capsys, monkeypatch):
    import io

    from respectful_offers import cli

    monkeypatch.setattr("sys.stdin", io.StringIO("correct horse battery\n"))
    assert cli.main(["demo-passkey", "--stdin", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert gate.check_passkey("correct horse battery", [out["hash"]])
    assert "correct horse battery" not in json.dumps(out)  # the passkey is never echoed
    assert out["secrets_toml"].startswith("[demo]\npasskey_hashes = [")
    assert cli.main(["demo-passkey", "--generate", "--json"]) == 0
    gen = json.loads(capsys.readouterr().out)
    assert gate.check_passkey(gen["passkey"], [gen["hash"]])  # shown once, to the owner
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert cli.main(["demo-passkey", "--stdin", "--json"]) == cli.EXIT_ERROR


def test_low_variety_passkeys_are_refused_and_generate_is_suggested():
    with pytest.raises(PasskeyError, match=r"different characters.*--generate"):
        gate.hash_passkey("aaaaaaaaaaaa")
    with pytest.raises(PasskeyError):
        gate.hash_passkey("abababababab")


def test_the_same_passkey_typed_in_another_unicode_form_unlocks():
    import unicodedata

    nfc = unicodedata.normalize("NFC", "café crème brûlée")
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd
    assert gate.check_passkey(nfd, [h(nfc)]) and gate.check_passkey(nfc, [h(nfd)])


@pytest.mark.parametrize("iterations", ["10000000000", "600_000", "٦٠٠٠٠٠", "+600000", " 600000"])
def test_stored_iterations_must_be_plain_digits_within_bounds(iterations):
    good = h("correct horse battery").split("$")
    bad = "$".join([good[0], iterations, good[2], good[3]])
    with pytest.raises(PasskeyError):
        gate.parse_hash(bad)
    with pytest.raises(PasskeyError, match="iterations"):
        gate.hash_passkey("correct horse battery", iterations=gate.MAX_ITERATIONS + 1)


def test_parallel_checks_cannot_overshoot_the_throttle():
    import threading

    t = gate.Throttle(limit=30, window=60.0)
    got: list[float | None] = []
    lock = threading.Lock()

    def worker() -> None:
        for _ in range(10):
            slot = t.try_acquire()
            with lock:
                got.append(slot)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert sum(s is not None for s in got) == 30  # exactly the limit, never more
    assert t.blocked()
    slot_ok = gate.Throttle(limit=1, window=60.0)
    s = slot_ok.try_acquire(0.0)
    assert s is not None and slot_ok.try_acquire(0.1) is None
    slot_ok.refund(s)  # a right passkey gives its slot back
    assert slot_ok.try_acquire(0.2) is not None


def test_throttle_defaults_follow_the_module_settings(monkeypatch):
    monkeypatch.setattr(gate, "GLOBAL_FAILURES", 2)
    t = gate.Throttle()
    assert t.limit == 2 and t.window == gate.GLOBAL_WINDOW
