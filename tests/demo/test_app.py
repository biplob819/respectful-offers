"""D3.2: the demo page, driven in-process by Streamlit's AppTest (DEM-01..03)."""

import socket
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from harness_lib import ROOT

APP = ROOT / "src" / "respectful_offers" / "demo" / "app.py"


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
    at = AppTest.from_file(str(out / "streamlit_app.py"), default_timeout=120)
    at.run()
    assert not at.exception and at.title[0].value == "Respectful Offers: policy simulator"
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
