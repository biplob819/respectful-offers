import copy
import math

import pytest
import yaml

from respectful_offers.schemas import (
    ConfigError,
    RunConfig,
    SimulatorConfig,
    load_run_config,
    load_simulator_config,
)
from tests.schemas.conftest import FIX


def _write(tmp_path, data, name="c.yaml"):
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return p


@pytest.fixture
def run_data():
    return yaml.safe_load((FIX / "run_config.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def sim_data():
    return yaml.safe_load((FIX / "simulator.yaml").read_text(encoding="utf-8"))


def test_fixtures_load():
    cfg = load_run_config(FIX / "run_config.yaml")
    assert cfg.cohort_buckets["holdout"] == (0, 10)
    sim = load_simulator_config(FIX / "simulator.yaml")
    assert set(sim.variants) == {"conservative", "central", "optimistic"}
    assert sim.risk_band(0.1) == "low" and sim.risk_band(0.2) == "medium"
    assert sim.risk_band(0.5) == "high" and sim.trend_band(-0.3) == "declining"


@pytest.mark.parametrize(
    ("mutate", "key"),
    [
        (lambda d: d["cohort_buckets"].update(train=[10, 45]), "cohort_buckets"),  # overlap
        (lambda d: d["cohort_buckets"].update(eval=[61, 100]), "cohort_buckets"),  # gap
        (lambda d: d["cohort_buckets"].pop("logging"), "cohort_buckets"),
        (lambda d: d["decision_features"].append("gender"), "decision_features"),
        (lambda d: d["decision_features"].append("city"), "decision_features"),
        (lambda d: d.update(budget_per_1000_per_period=-1.0), "budget_per_1000_per_period"),
        (lambda d: d.update(risk_threshold=math.nan), "risk_threshold"),
        (lambda d: d.update(colour="blue"), "colour"),
        (lambda d: d.update(budget_sweep=[5000.0, 2500.0]), "budget_sweep"),
        (lambda d: d.update(seed="7"), "seed"),
    ],
)
def test_bad_run_configs_name_file_and_key(tmp_path, run_data, mutate, key):
    data = copy.deepcopy(run_data)
    mutate(data)
    p = _write(tmp_path, data)
    with pytest.raises(ConfigError) as exc:
        load_run_config(p)
    assert str(p) in str(exc.value) and key in str(exc.value)


def test_a_zero_budget_is_a_zero_budget(tmp_path, run_data):
    p = _write(tmp_path, {**run_data, "budget_per_1000_per_period": 0.0})
    assert load_run_config(p).budget_per_1000_per_period == 0.0


def test_duplicate_keys_directories_and_non_utf8(tmp_path):
    dup = tmp_path / "dup.yaml"
    dup.write_text("seed: 1\nseed: 2\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="duplicate key 'seed'"):
        load_run_config(dup)
    with pytest.raises(ConfigError, match="is a directory"):
        load_run_config(tmp_path)
    bad = tmp_path / "latin.yaml"
    bad.write_bytes(b"seed: caf\xe9\n")
    with pytest.raises(ConfigError, match="not UTF-8"):
        load_run_config(bad)
    with pytest.raises(ConfigError, match="cannot read"):
        load_run_config(tmp_path / "missing.yaml")


def _central(d):
    return d["variants"]["central"]


@pytest.mark.parametrize(
    ("mutate", "key"),
    [
        (lambda d: _central(d)["segment_mix"].pop("high.declining"), "high.declining"),
        (lambda d: _central(d)["segment_mix"]["low.stable"].pop("sleeping_dog"), "sleeping_dog"),
        (lambda d: _central(d)["acceptance"].pop("plan_change"), "plan_change"),
        (lambda d: _central(d)["segment_mix"]["low.stable"].update(sure_thing=0.69), "sums to"),
        (lambda d: _central(d)["acceptance"]["discount_1m"].update(persuadable=1.2), "1.2"),
        (lambda d: _central(d)["exposure_effect"]["discount_1m"].update(sleeping_dog=-1.5), "-1.5"),
        (lambda d: d["risk_bands"].update(cuts=[0.5, 0.2]), "increasing"),
        (lambda d: d["risk_bands"].update(cuts=[0.2, 1.0]), "risk_bands"),
        (lambda d: d["actions"]["plan_change"].update(price_ratio=1.0), "price_ratio"),
        (lambda d: d.update(segments=["sure_thing", "persuadable"]), "segments"),
    ],
)
def test_bad_simulator_configs_name_the_key(tmp_path, sim_data, mutate, key):
    data = copy.deepcopy(sim_data)
    mutate(data)
    with pytest.raises(ConfigError) as exc:
        load_simulator_config(_write(tmp_path, data))
    assert key in str(exc.value)


def test_configs_are_frozen():
    cfg = load_run_config(FIX / "run_config.yaml")
    with pytest.raises(TypeError):
        cfg.cohort_buckets["eval"] = (0, 1)  # type: ignore[index]
    assert isinstance(cfg, RunConfig)
    assert isinstance(load_simulator_config(FIX / "simulator.yaml"), SimulatorConfig)


@pytest.mark.parametrize(
    ("patch", "key"),
    [
        ("budget_per_1000_per_period: yes", "budget_per_1000_per_period"),
        ("budget_per_1000_per_period: '5000'", "budget_per_1000_per_period"),
        ("eval_sample: true", "eval_sample"),
        ("risk_threshold: !!binary aGVsbG8=", "not plain YAML"),
    ],
)
def test_yaml_values_are_strict(tmp_path, patch, key):
    text = (FIX / "run_config.yaml").read_text(encoding="utf-8")
    name = patch.split(":")[0]
    lines = [ln for ln in text.splitlines() if not ln.startswith(name + ":")]
    p = tmp_path / "c.yaml"
    p.write_text("\n".join([*lines, patch]) + "\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=key):
        load_run_config(p)


def test_boolean_list_items_and_quoted_flags_are_refused(tmp_path, run_data, sim_data):
    data = copy.deepcopy(run_data)
    data["cohort_buckets"]["holdout"] = [False, 10]
    with pytest.raises(ConfigError, match="cohort_buckets"):
        load_run_config(_write(tmp_path, data))
    sim = copy.deepcopy(sim_data)
    sim["allow_unconventional"] = "on"
    with pytest.raises(ConfigError, match="allow_unconventional"):
        load_simulator_config(_write(tmp_path, sim, "s.yaml"))
    sim = copy.deepcopy(sim_data)
    _central(sim)["acceptance"]["discount_1m"]["persuadable"] = True
    with pytest.raises(ConfigError, match="persuadable"):
        load_simulator_config(_write(tmp_path, sim, "s2.yaml"))


def test_unhashable_and_non_string_keys_name_the_file(tmp_path):
    p = tmp_path / "k.yaml"
    p.write_text("seed: 1\n? [a, b]\n: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="unhashable key") as exc:
        load_run_config(p)
    assert str(p) in str(exc.value)
    q = tmp_path / "n.yaml"
    q.write_text("1: 2\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="must be a string"):
        load_run_config(q)


@pytest.mark.parametrize("feature", ["Gender", "gender_x", "user_age", "msno", "City"])
def test_protected_attributes_are_caught_as_words(tmp_path, run_data, feature):
    data = copy.deepcopy(run_data)
    data["decision_features"].append(feature)
    with pytest.raises(ConfigError, match="protected"):
        load_run_config(_write(tmp_path, data))


def test_configs_pickle_and_deepcopy():
    import pickle

    cfg = load_run_config(FIX / "run_config.yaml")
    sim = load_simulator_config(FIX / "simulator.yaml")
    for obj in (cfg, sim):
        assert pickle.loads(pickle.dumps(obj)) == obj
        assert copy.deepcopy(obj) == obj
        assert obj.model_copy(deep=True) == obj
