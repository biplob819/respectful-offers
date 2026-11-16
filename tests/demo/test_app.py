"""D3.2: the demo page, driven in-process by Streamlit's AppTest (DEM-01..03)."""

import re
import socket
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from harness_lib import ROOT
from respectful_offers.demo import gate

APP = ROOT / "src" / "respectful_offers" / "demo" / "app.py"
PASSKEY = "correct horse battery"
HASH = gate.hash_passkey(PASSKEY, iterations=gate.MIN_ITERATIONS)


@pytest.fixture(scope="module")
def cube_file(tmp_path_factory) -> Path:
    import pandas as pd

    from respectful_offers import cli
    from respectful_offers.demo.cube import dumps, make_cube
    from respectful_offers.schemas import load_simulator_config
    from respectful_offers.schemas.config import load_run_config

    root = tmp_path_factory.mktemp("app")
    assert (
        cli.main(["data", "synthetic", "--data-dir", str(root / "data"), "--members", "8000"]) == 0
    )
    assert (
        cli.main(
            ["evaluate", "--data-dir", str(root / "data"), "--root", str(root), "--run-id", "r"]
        )
        == 0
    )
    store = root / ".offers" / "store"
    feats = pd.read_parquet(next(store.rglob("features_mar.parquet")))
    scores = pd.read_parquet(next(store.rglob("scores_mar.parquet")))[["msno", "churn_risk"]]
    cube = make_cube(
        scores,
        feats,
        root / "runs" / "r",
        ROOT / "configs" / "simulator.yaml",
        load_run_config(ROOT / "configs" / "run.yaml"),
        load_simulator_config(ROOT / "configs" / "simulator.yaml"),
    )
    path = root / "cube.json"
    path.write_text(dumps(cube), encoding="utf-8")
    return path


def page(cube_file, monkeypatch) -> AppTest:
    monkeypatch.setenv("OFFERS_DEMO_CUBE", str(cube_file))
    at = AppTest.from_file(str(APP), default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    return at


def test_the_page_shows_every_policy_and_never_hides_that_it_is_simulated(cube_file, monkeypatch):
    at = page(cube_file, monkeypatch)
    assert at.title[0].value == "Respectful Offers: policy simulator"
    labels = [m.label for m in at.metric]
    names = ("No offer", "Rule-following baseline", "Bandit", "Status quo (breaks the rules)")
    assert labels == [f"{n} (simulated)" for n in names]
    text = " ".join(c.value for c in at.caption)
    assert "Every outcome on this screen is simulated" in text and "Simulated" in text
    assert any("zero violations" in s.value for s in at.success)


def test_central_is_the_default_and_the_sliders_drive_the_numbers(cube_file, monkeypatch):
    at = page(cube_file, monkeypatch)
    assert at.radio[0].value == "central"
    at.slider[0].set_value(0).run()  # no discount budget
    assert not at.exception
    spend = [c.value for c in at.caption if "NTD per member" in c.value]
    assert any(v.startswith("0.00 NTD") for v in spend)


def test_the_page_makes_no_network_calls(cube_file, monkeypatch):
    """Any connection off this machine fails the test. Loopback is allowed: on Windows the
    asyncio event loop connects a socket pair to itself as an internal wake-up pipe."""
    real_connect = socket.socket.connect
    real_create = socket.create_connection
    local = {"127.0.0.1", "::1", "localhost"}

    def guarded_connect(sock, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in local:
            raise AssertionError(f"the demo page tried to connect to {host}")
        return real_connect(sock, address, *a, **k)

    def guarded_create(address, *a, **k):
        if address[0] not in local:
            raise AssertionError(f"the demo page tried to connect to {address[0]}")
        return real_create(address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", guarded_create)
    page(cube_file, monkeypatch)


def test_the_deploy_bundle_runs_the_page_from_its_own_files(
    cube_file, tmp_path, monkeypatch, capsys
):
    from respectful_offers import cli

    out = tmp_path / "bundle"
    assert cli.main(["demo-bundle", "--cube", str(cube_file), "--out", str(out)]) == 0
    names = sorted(p.name for p in out.iterdir())
    assert names == [".streamlit", "cube.json", "requirements.txt", "streamlit_app.py"]
    assert "gatherUsageStats = false" in (out / ".streamlit" / "config.toml").read_text(
        encoding="utf-8"
    )
    reqs = (out / "requirements.txt").read_text(encoding="utf-8")
    assert "git+https://github.com/biplob819/respectful-offers" in reqs
    monkeypatch.delenv("OFFERS_DEMO_CUBE", raising=False)
    monkeypatch.delenv("OFFERS_DEMO_REQUIRE_PASSKEY", raising=False)
    locked = AppTest.from_file(str(out / "streamlit_app.py"), default_timeout=120).run()
    assert not locked.exception and not locked.metric  # deployed with no passkey set: locked
    assert any("has not set a passkey" in e.value for e in locked.error)
    # Streamlit copies top-level secrets into the environment: a stray one cannot unlock it
    stray = AppTest.from_file(str(out / "streamlit_app.py"), default_timeout=120)
    stray.secrets["OFFERS_DEMO_REQUIRE_PASSKEY"] = "0"
    stray.secrets["demo"] = {"passkey_hashes": []}
    stray.run()
    assert not stray.exception and not stray.metric
    assert any("has not set a passkey" in e.value for e in stray.error)
    at = AppTest.from_file(str(out / "streamlit_app.py"), default_timeout=120)
    at.secrets["demo"] = {"passkey_hashes": [HASH]}
    at.run()
    at.text_input[0].input(PASSKEY)
    at.button[0].click().run()
    assert not at.exception and at.title[0].value == "Respectful Offers: policy simulator"
    assert len(at.metric) == 4
    (tmp_path / "busy").mkdir()
    (tmp_path / "busy" / "notes.txt").write_text("x", encoding="utf-8")
    assert (
        cli.main(["demo-bundle", "--cube", str(cube_file), "--out", str(tmp_path / "busy")])
        == cli.EXIT_ERROR
    )


def test_a_failed_audit_shows_no_numbers(cube_file, monkeypatch):
    from respectful_offers.demo import engine

    real = engine.simulate

    def broken(*a, **k):
        out = real(*a, **k)
        out["policies"]["bandit"]["violations"]["R1"] = 3
        return out

    monkeypatch.setattr(engine, "simulate", broken)
    at = page(cube_file, monkeypatch)
    assert at.error and "no results are shown" in at.error[0].value
    assert len(at.metric) == 0  # nothing the audit forbids is on screen
    assert any("simulated" in c.value for c in at.caption)


def test_holdout_card_quotes_the_runs_own_check(cube_file, monkeypatch):
    at = page(cube_file, monkeypatch)
    text = " ".join(m.value for m in at.markdown)
    assert "per 1,000" in text and "95% interval" in text
    assert all("(simulated)" in m.label for m in at.metric)


def test_the_bundle_refuses_tampered_cubes_symlinks_and_foreign_files(cube_file, tmp_path):
    import json

    from respectful_offers import cli

    data = json.loads(cube_file.read_text(encoding="utf-8"))
    data["data_source"] = "kaggle"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    assert (
        cli.main(["demo-bundle", "--cube", str(bad), "--out", str(tmp_path / "b1")])
        == cli.EXIT_ERROR
    )
    out = tmp_path / "b2"
    assert cli.main(["demo-bundle", "--cube", str(cube_file), "--out", str(out)]) == 0
    (out / "notes.txt").write_text("mine", encoding="utf-8")
    assert cli.main(["demo-bundle", "--cube", str(cube_file), "--out", str(out)]) == cli.EXIT_ERROR
    victim = tmp_path / "victim.txt"
    victim.write_text("keep", encoding="utf-8")
    out3 = tmp_path / "b3"
    out3.mkdir()
    try:
        (out3 / "requirements.txt").symlink_to(victim)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert cli.main(["demo-bundle", "--cube", str(cube_file), "--out", str(out3)]) == cli.EXIT_ERROR
    assert victim.read_text(encoding="utf-8") == "keep"


def walk(node):
    """The element types under a node, at any depth (forms and columns included)."""
    yield getattr(node, "type", type(node).__name__)
    for child in getattr(node, "children", {}).values():
        yield from walk(child)


def nodes(node):
    yield node
    for child in getattr(node, "children", {}).values():
        yield from nodes(child)


def gated(cube_file, monkeypatch, hashes) -> AppTest:
    monkeypatch.setenv("OFFERS_DEMO_CUBE", str(cube_file))
    at = AppTest.from_file(str(APP), default_timeout=120)
    at.secrets["demo"] = {"passkey_hashes": hashes}
    at.run()
    assert not at.exception, at.exception
    return at


def unlock(at: AppTest, passkey: str) -> AppTest:
    at.text_input[0].input(passkey)
    at.button[0].click().run()
    assert not at.exception, at.exception
    return at


def test_a_passkey_hides_every_number_until_it_is_entered(cube_file, monkeypatch):
    at = gated(cube_file, monkeypatch, [HASH])
    shown = set(walk(at.main))  # every element on the page before unlock, at any depth
    allowed = {"main", "form", "markdown", "caption", "text_input", "button", "error"}
    assert shown <= allowed, shown - allowed  # the gate, its errors and the footer: no numbers
    assert not at.metric and not at.dataframe and not at.slider and not at.code
    assert (
        at.text_input[0].label == "Passkey"
        and at.text_input[0].proto.type == at.text_input[0].proto.PASSWORD
    )
    assert any("simulated" in c.value.lower() for c in at.caption)  # footer still shown
    unlock(at, "wrong passkey entirely")
    assert not at.metric and any("not right" in e.value for e in at.error)
    form = next(n for n in nodes(at.main) if getattr(n, "type", "") == "form")
    assert form.proto.form.clear_on_submit  # the wrong passkey does not linger in the box
    assert all("wrong passkey" not in e.value for e in at.error)  # never echoed
    unlock(at, PASSKEY)
    assert len(at.metric) == 4 and at.slider
    at.run()  # stays unlocked for the rest of the session
    assert len(at.metric) == 4


def test_any_listed_passkey_unlocks_so_one_can_be_revoked(cube_file, monkeypatch):
    other = gate.hash_passkey("a passkey for someone else", iterations=gate.MIN_ITERATIONS)
    assert len(unlock(gated(cube_file, monkeypatch, [other, HASH]), PASSKEY).metric) == 4
    revoked = unlock(gated(cube_file, monkeypatch, [other]), PASSKEY)
    assert not revoked.metric


def test_five_wrong_passkeys_lock_the_session_out(cube_file, monkeypatch):
    at = gated(cube_file, monkeypatch, [HASH])
    for _ in range(gate.MAX_ATTEMPTS):
        unlock(at, "wrong passkey entirely")
    at.run()
    assert not at.text_input  # no form while locked out
    assert any("Too many wrong passkeys" in e.value for e in at.error)
    assert not at.metric


def test_a_broken_passkey_setting_locks_the_page(cube_file, monkeypatch):
    at = gated(cube_file, monkeypatch, ["plaintext-passkey"])
    assert not at.metric and not at.text_input
    assert any("passkey setting is broken" in e.value for e in at.error)


def test_required_with_no_passkey_set_fails_closed(cube_file, monkeypatch):
    monkeypatch.setenv("OFFERS_DEMO_CUBE", str(cube_file))
    monkeypatch.setenv("OFFERS_DEMO_REQUIRE_PASSKEY", "1")
    at = AppTest.from_file(str(APP), default_timeout=120).run()
    assert not at.exception and not at.metric and not at.text_input
    assert any("has not set a passkey" in e.value for e in at.error)


def test_the_committed_deploy_files_are_the_current_bundle():
    from respectful_offers import cli

    demo = ROOT / "demo"
    assert (demo / "streamlit_app.py").read_text(encoding="utf-8") == cli.BUNDLE_APP
    assert "main(require_passkey=True)" in cli.BUNDLE_APP
    reqs = (demo / "requirements.txt").read_text(encoding="utf-8")
    url = r"respectful-offers\[demo\] @ git\+https://github.com/biplob819/respectful-offers"
    pin = re.search(url + r"@(\S+)", reqs)
    assert pin and re.fullmatch(r"[0-9a-f]{40}|v\d+\.\d+\.\d+", pin.group(1)), "pinned"
    root_cfg = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert "gatherUsageStats = false" in root_cfg


def test_bundle_pins_a_ref_and_refuses_a_bad_one(cube_file, tmp_path):
    from respectful_offers import cli

    sha = "a" * 40
    assert (
        cli.main(
            ["demo-bundle", "--cube", str(cube_file), "--out", str(tmp_path / "b"), "--ref", sha]
        )
        == 0
    )
    assert f"respectful-offers@{sha}\n" in (tmp_path / "b" / "requirements.txt").read_text("utf-8")
    bad = [
        "demo-bundle",
        "--cube",
        str(cube_file),
        "--out",
        str(tmp_path / "c"),
        "--ref",
        "main; rm",
    ]
    assert cli.main(bad) == cli.EXIT_ERROR


@pytest.mark.parametrize("setting", [5, {"nested": True}, [7]])
def test_an_oddly_typed_passkey_setting_locks_without_a_traceback(cube_file, monkeypatch, setting):
    at = gated(cube_file, monkeypatch, setting)
    assert not at.metric and not at.text_input
    assert any("passkey setting is broken" in e.value for e in at.error)


def test_the_page_uses_the_app_wide_throttle(cube_file, monkeypatch):
    import streamlit as st

    monkeypatch.setattr(gate, "GLOBAL_FAILURES", 2)
    st.cache_resource.clear()  # a fresh throttle with the lowered limit
    try:
        for _ in range(2):  # two visitors, one wrong passkey each
            unlock(gated(cube_file, monkeypatch, [HASH]), "wrong passkey entirely")
        third = gated(cube_file, monkeypatch, [HASH])  # a new session: its own count is zero
        assert not third.text_input and not third.metric
        assert any("many visitors" in e.value for e in third.error)
    finally:
        st.cache_resource.clear()
