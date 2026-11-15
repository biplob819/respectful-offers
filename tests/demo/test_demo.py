"""D3.1: the demo engine (DMO-01..05), built from a real `offers evaluate` run."""

import json
import time

import numpy as np
import pandas as pd
import pytest

from harness_lib import ROOT
from respectful_offers import cli
from respectful_offers.demo.cube import MIN_CELL, dumps, make_cube, merge_small
from respectful_offers.demo.engine import DEMO_MEMBERS, agreement, load_cube, simulate
from respectful_offers.schemas import load_simulator_config
from respectful_offers.schemas.config import load_run_config


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("demo")
    assert (
        cli.main(
            [
                "data",
                "synthetic",
                "--data-dir",
                str(root / "data"),
                "--members",
                "20000",
                "--seed",
                "9",
            ]
        )
        == 0
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
    cfg = load_run_config(ROOT / "configs" / "run.yaml")
    sim = load_simulator_config(ROOT / "configs" / "simulator.yaml")
    cube = make_cube(
        scores, feats, root / "runs" / "r", ROOT / "configs" / "simulator.yaml", cfg, sim
    )
    path = root / "cube.json"
    path.write_text(dumps(cube), encoding="utf-8")
    return path, scores, cube


# -- DMO-01 aggregates only -------------------------------------------------------------------


def test_the_cube_holds_aggregates_only(built):
    path, scores, cube = built
    text = path.read_text(encoding="utf-8")
    assert not any(m in text for m in scores["msno"].head(500))  # no member id anywhere
    assert "msno" not in {k for c in cube["cells"] for k in c}
    assert min(c["count"] for c in cube["cells"]) >= MIN_CELL
    assert sum(c["count"] for c in cube["cells"]) == cube["members"]


def test_small_cells_are_merged_until_none_is_small():
    rng = np.random.default_rng(0)
    n = 300
    keys = pd.DataFrame(
        {
            "risk_decile": rng.integers(0, 10, n).astype(str),
            "trend_band": rng.choice(["declining", "stable"], n),
            "auto_renew": rng.choice(["yes", "no"], n),
            "tenure_band": rng.choice(["<6m", "6-24m", ">24m"], n),
            "price_band": rng.choice(["<=99", "100-149", ">149"], n),
        }
    )
    merged = merge_small(keys)
    assert merged.groupby(list(merged.columns)).size().min() >= MIN_CELL
    with pytest.raises(ValueError, match="too small"):
        merge_small(keys.head(MIN_CELL - 1))


# -- DMO-02 simulate --------------------------------------------------------------------------


def test_simulate_is_deterministic_and_reacts_to_the_sliders(built):
    cube = load_cube(built[0])
    a = simulate(cube, 3000.0, 0.15, "central")
    assert a == simulate(cube, 3000.0, 0.15, "central")
    assert a["members"] == DEMO_MEMBERS and set(a["policies"]) == {
        "no_offer",
        "rule_following_baseline",
        "bandit",
        "status_quo",
    }
    assert a["bandit_trained_at"] == 0.15 and a["simulated"] is True
    poor = simulate(cube, 0.0, 0.15, "central")
    assert poor["policies"]["status_quo"]["discount_per_member"] == 0.0  # no budget, no discounts
    low = simulate(cube, 3000.0, 0.05, "central")
    assert (
        low["policies"]["rule_following_baseline"]["offers_per_member_month"]
        != a["policies"]["rule_following_baseline"]["offers_per_member_month"]
    )


def test_bad_inputs_are_refused(built, tmp_path):
    cube = load_cube(built[0])
    for budget, threshold, variant in (
        (-1.0, 0.15, "central"),
        (3000.0, 1.0, "central"),
        (3000.0, 0.15, "nonesuch"),
    ):
        with pytest.raises(ValueError):
            simulate(cube, budget, threshold, variant)
    data = json.loads(built[0].read_text(encoding="utf-8"))
    data.pop("integrity")
    data["cells"][0]["count"] = 3
    bad = tmp_path / "bad.json"
    bad.write_text(dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="minimum"):
        load_cube(bad)


# -- DMO-03 latency ---------------------------------------------------------------------------


@pytest.mark.perf
def test_p95_latency_is_within_budget(built, tmp_path):
    """A regression guard: the cold first call under 5 s and p95 over ten settings under 3.5 s,
    each setting timed as the best of two so other processes' spikes do not count. The 2 s
    target is measured on the deployed page's own hardware (DEM-03, D-43); on an idle
    developer machine the engine takes about 1.1 s."""
    data = json.loads(built[0].read_text(encoding="utf-8"))
    data.pop("integrity")
    data["reference"]["run_id"] = "latency-fresh"  # new content, new digest: a cold cache
    fresh = tmp_path / "fresh.json"
    fresh.write_text(dumps(data), encoding="utf-8")
    cube = load_cube(fresh)
    t = time.perf_counter()
    simulate(cube, 3000.0, 0.15, "central")
    cold = time.perf_counter() - t
    times = []
    for i in range(10):
        best = float("inf")
        for _ in range(2):
            t = time.perf_counter()
            simulate(cube, 1000.0 + 500.0 * i, 0.10 + 0.01 * i, "central")
            best = min(best, time.perf_counter() - t)
        times.append(best)
    assert cold < 5.0, cold
    assert float(np.percentile(times, 95)) < 3.5, times


# -- DMO-04 live auditor ----------------------------------------------------------------------


def test_the_live_auditor_shows_zero_for_every_respectful_policy(built):
    out = simulate(load_cube(built[0]), 3000.0, 0.15, "central")
    for name, r in out["policies"].items():
        if r["respectful"]:
            assert sum(r["violations"].values()) == 0, name
    assert sum(out["policies"]["status_quo"]["violations"].values()) > 0  # reported, not hidden


# -- DMO-05 agreement with the full run --------------------------------------------------------


@pytest.mark.parametrize("variant", ["conservative", "central", "optimistic"])
def test_demo_agrees_with_the_full_run_at_the_reference_settings(built, variant):
    rows = agreement(load_cube(built[0]), variant)
    assert len(rows) == 12 and all(r["agrees"] for r in rows), [r for r in rows if not r["agrees"]]


def test_offers_demo_cube_writes_a_cube_from_a_run(tmp_path, capsys):
    root = tmp_path
    assert (
        cli.main(["data", "synthetic", "--data-dir", str(root / "data"), "--members", "6000"]) == 0
    )
    base = ["--data-dir", str(root / "data"), "--root", str(root), "--run-id", "r"]
    assert cli.main(["evaluate", *base, "--variant", "central"]) == 0
    capsys.readouterr()
    assert cli.main(["demo-cube", *base, "--out", str(root / "cube.json"), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and load_cube(root / "cube.json").data["data_source"] == "synthetic"
    assert (
        cli.main(
            ["demo-cube", "--data-dir", str(root / "data"), "--root", str(root), "--run-id", "none"]
        )
        == cli.EXIT_DATA
    )


def _mutant(built, tmp_path, change) -> list:
    data = json.loads(built[0].read_text(encoding="utf-8"))
    data.pop("integrity")
    change(data)
    path = tmp_path / "mutant.json"
    path.write_text(dumps(data), encoding="utf-8")
    return agreement(load_cube(path), "central")


@pytest.mark.parametrize(
    "name",
    ["swap bandit and status quo", "wrong posterior variant", "no spreads"],
)
def test_agreement_catches_a_broken_demo(built, tmp_path, name):
    def swap(d):
        a = d["agreement"]["central"]
        a["bandit"], a["status_quo"] = a["status_quo"], a["bandit"]

    def wrong_posterior(d):
        d["posteriors"]["central"] = d["posteriors"]["optimistic"]

    def no_spreads(d):
        for c in d["cells"]:
            c["sds"] = {k: 0.0 for k in c["sds"]}

    rows = _mutant(
        built,
        tmp_path,
        {
            "swap bandit and status quo": swap,
            "wrong posterior variant": wrong_posterior,
            "no spreads": no_spreads,
        }[name],
    )
    assert not all(r["agrees"] for r in rows), name


@pytest.mark.parametrize(
    "change, match",
    [
        (lambda d: d.update(min_cell=1) or d["cells"][0].update(count=3), "version|minimum"),
        (lambda d: d["cells"][0].update(count=3), "minimum"),
        (lambda d: d["cells"][0].update(count=20.5), "minimum"),
        (lambda d: d["cells"][0].update(msno=["a"]), "unexpected keys"),
        (lambda d: d.update(rows=[{"msno": "x"}]), "top-level keys"),
        (lambda d: d.update(members=d["members"] + 1), "add up"),
        (lambda d: d["cells"][0]["means"].update(churn_risk=5.0), "out of range"),
        (lambda d: d["reference"]["decision_features"].append("gender"), "protected"),
        (lambda d: d["posteriors"].pop("optimistic"), "no bandit posterior"),
    ],
)
def test_a_tampered_cube_is_refused(built, tmp_path, change, match):
    data = json.loads(built[0].read_text(encoding="utf-8"))
    data.pop("integrity")
    change(data)
    bad = tmp_path / "bad.json"
    bad.write_text(dumps(data), encoding="utf-8")  # re-sealed: the specific check must catch it
    with pytest.raises(ValueError, match=match):
        load_cube(bad)


def test_an_edit_after_demo_cube_fails_the_integrity_check(built, tmp_path):
    data = json.loads(built[0].read_text(encoding="utf-8"))
    data["data_source"] = "kaggle"  # relabelling synthetic members as real
    bad = tmp_path / "edited.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        load_cube(bad)
    data.pop("integrity")
    data["simulator_yaml"] = data["simulator_yaml"].replace(
        "discount_fraction: 0.5", "discount_fraction: 0.95"
    )
    bad.write_text(dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="pre-registered simulator"):
        load_cube(bad)


def test_a_variant_the_run_never_trained_is_a_clear_error(built, tmp_path):
    data = json.loads(built[0].read_text(encoding="utf-8"))
    data.pop("integrity")
    data["posteriors"].pop("optimistic")
    data["reference"]["variants"] = ["conservative", "central"]
    path = tmp_path / "two.json"
    path.write_text(dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="no variant 'optimistic'"):
        simulate(load_cube(path), 3000.0, 0.15, "optimistic")


def test_two_cubes_one_member_apart_do_not_reveal_that_member(tmp_path):
    from respectful_offers.demo.cube import build_cube

    rng = np.random.default_rng(1)
    n = 400
    feats = pd.DataFrame(
        {
            "msno": [f"m{i}" for i in range(n)],
            "tenure_days": rng.integers(30, 3000, n),
            "cancels_90d": rng.poisson(0.2, n),
            "listening_trend_30d": rng.normal(0, 0.3, n),
            "price_30d": rng.choice([99.0, 149.0], n),
            "auto_renew": rng.uniform(size=n) < 0.8,
        }
    )
    scores = pd.DataFrame({"msno": feats["msno"], "churn_risk": rng.beta(1.2, 12, n)})
    kw = dict(simulator_yaml="", posteriors={}, reference={}, agreement={}, data_source="synthetic")
    a = build_cube(scores, feats, -0.25, **kw)  # type: ignore[arg-type]
    b = build_cube(scores.iloc[1:], feats.iloc[1:], -0.25, **kw)  # type: ignore[arg-type]

    def total(c, col):
        return sum(cell["count"] * cell["means"][col] for cell in c["cells"])

    recovered = total(a, "tenure_days") - total(b, "tenure_days")
    assert (
        abs(recovered - float(feats["tenure_days"].iloc[0])) > 1.0
    )  # rounding defeats differencing
    assert all(c["count"] % 5 == 0 for c in a["cells"])


def test_demo_cube_never_overwrites_a_run_or_a_foreign_file(tmp_path, capsys):
    root = tmp_path
    assert (
        cli.main(["data", "synthetic", "--data-dir", str(root / "data"), "--members", "6000"]) == 0
    )
    base = ["--data-dir", str(root / "data"), "--root", str(root), "--run-id", "r"]
    assert cli.main(["evaluate", *base, "--variant", "central"]) == 0
    summary = (root / "runs" / "r" / "summary.json").read_text(encoding="utf-8")
    assert (
        cli.main(["demo-cube", *base, "--out", str(root / "runs" / "r" / "summary.json")])
        == cli.EXIT_ERROR
    )
    assert (root / "runs" / "r" / "summary.json").read_text(encoding="utf-8") == summary
    mine = root / "mine.json"
    mine.write_text('{"not": "a cube"}', encoding="utf-8")
    assert cli.main(["demo-cube", *base, "--out", str(mine)]) == cli.EXIT_ERROR
    assert mine.read_text(encoding="utf-8") == '{"not": "a cube"}'


def test_a_cube_is_bound_to_the_run_it_names(tmp_path):
    root = tmp_path
    assert cli.main(["data", "synthetic", "--data-dir", str(root / "d1"), "--members", "6000"]) == 0
    assert (
        cli.main(
            [
                "data",
                "synthetic",
                "--data-dir",
                str(root / "d2"),
                "--members",
                "9000",
                "--seed",
                "3",
            ]
        )
        == 0
    )
    assert (
        cli.main(
            [
                "evaluate",
                "--data-dir",
                str(root / "d1"),
                "--root",
                str(root),
                "--run-id",
                "r",
                "--variant",
                "central",
            ]
        )
        == 0
    )
    out = str(root / "c.json")
    other_data = [
        "demo-cube",
        "--data-dir",
        str(root / "d2"),
        "--root",
        str(root),
        "--run-id",
        "r",
        "--out",
        out,
    ]
    assert cli.main(other_data) == cli.EXIT_ERROR  # another cohort than the run evaluated
    alt = root / "run_alt.yaml"
    alt.write_text(
        (ROOT / "configs" / "run.yaml")
        .read_text(encoding="utf-8")
        .replace("risk_threshold: 0.15", "risk_threshold: 0.30"),
        encoding="utf-8",
    )
    other_config = [
        "demo-cube",
        "--data-dir",
        str(root / "d1"),
        "--root",
        str(root),
        "--run-id",
        "r",
        "--config",
        str(alt),
        "--out",
        out,
    ]
    assert cli.main(other_config) == cli.EXIT_ERROR
    assert (
        cli.main(
            [
                "evaluate",
                "--data-dir",
                str(root / "d1"),
                "--root",
                str(root),
                "--run-id",
                "x",
                "--variant",
                "central",
                "--simulator",
                str(alt),
                "--exploratory",
            ]
        )
        == cli.EXIT_ERROR
    )  # not even a simulator file
    assert (
        cli.main(
            [
                "demo-cube",
                "--data-dir",
                str(root / "d1"),
                "--root",
                str(root),
                "--run-id",
                "r",
                "--out",
                out,
            ]
        )
        == 0
    )


def test_merge_edge_cases_never_mislabel_or_crash():
    keys = pd.DataFrame(
        {
            "risk_decile": ["0"] * 25 + ["9"] * 14,
            "trend_band": ["stable"] * 25 + ["declining"] * 14,
            "auto_renew": "yes",
            "tenure_band": "<6m",
            "price_band": "<=99",
        }
    )
    merged = merge_small(keys)
    assert merged.groupby(list(merged.columns)).size().min() >= MIN_CELL
    assert set(merged["trend_band"]) == {"any"}  # the declining members are not called stable
    with pytest.raises(ValueError, match="too small"):
        merge_small(keys.head(0))


def test_odd_values_in_an_actions_column_raise_a_contract_error():
    from respectful_offers.schemas.contracts import MEMBER_STATES, ContractError, check_frame

    frame = pd.DataFrame(
        {
            "msno": ["a"],
            "period": [1],
            "active": [True],
            "in_holdout": [False],
            "churn_risk": [0.1],
            "risk_band": ["low"],
            "trend_band": ["stable"],
            "declined": [[["content_nudge"]]],
            "nudged": [False],
            "price_30d": [99.0],
            "plan_multiplier": [1.0],
        }
    )
    with pytest.raises(ContractError):
        check_frame(frame, MEMBER_STATES, "test")
