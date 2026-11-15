import json
import threading
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from respectful_offers.runtime import (
    RunContext,
    Stage,
    Store,
    bucket,
    canonical_json,
    content_hash,
    import_artifact,
    member_hashes,
    member_uniforms,
    run_stage,
    stage_seed,
    versions,
)


class Count(Stage):
    name = "count"
    code_version = "1"
    calls = 0

    def run(self, inputs, out, ctx):
        type(self).calls += 1
        text = (inputs["src"] / "in.txt").read_text(encoding="utf-8")
        (out / "n.txt").write_text(str(len(text)), encoding="utf-8")


class Double(Stage):
    name = "double"
    code_version = "1"
    calls = 0

    def run(self, inputs, out, ctx):
        type(self).calls += 1
        n = int((inputs["count"] / "n.txt").read_text(encoding="utf-8"))
        (out / "d.txt").write_text(str(2 * n), encoding="utf-8")


class Boom(Stage):
    name = "boom"
    code_version = "1"

    def run(self, inputs, out, ctx):
        (out / "half.txt").write_text("partial", encoding="utf-8")
        raise RuntimeError("stage exploded")


def ctx_at(tmp_path, seed=7, config_hash="cfg"):
    return RunContext(root=tmp_path, run_id="r1", config_hash=config_hash, seed=seed)


def pipeline(tmp_path, text="hello", **kw):
    tmp_path.mkdir(parents=True, exist_ok=True)
    ctx = ctx_at(tmp_path, **kw)
    src_file = tmp_path / "in.txt"
    src_file.write_text(text, encoding="utf-8")
    src = import_artifact(ctx, "source", {"in.txt": src_file})
    c = run_stage(Count(), {"src": src}, ctx)
    d = run_stage(Double(), {"count": c}, ctx)
    ctx.write_lineage()
    return ctx, c, d


def test_cache_key_inputs_each_change_the_key(tmp_path):
    ctx, c, _ = pipeline(tmp_path)
    base = Double().cache_key({"count": c}, ctx)
    assert Double().cache_key({"count": c}, ctx_at(tmp_path, seed=8)) != base
    assert Double().cache_key({"count": c}, ctx_at(tmp_path, config_hash="other")) != base

    class Double2(Double):
        code_version = "2"

    class Renamed(Double):
        name = "double-renamed"

    class WithParams(Double):
        def params(self):
            return {"k": 3}

    for other in (Double2(), Renamed(), WithParams()):
        assert other.cache_key({"count": c}, ctx) != base
    _, c2, _ = pipeline(tmp_path / "b", text="hello!")
    assert Double().cache_key({"count": c2}, ctx) != base


@given(st.dictionaries(st.text(min_size=1, max_size=5), st.integers(), max_size=6))
def test_canonical_json_is_stable_under_key_order(d):
    reordered = dict(reversed(list(d.items())))
    assert canonical_json(d) == canonical_json(reordered)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), {1, 2}])
def test_cache_keys_refuse_nan_infinity_and_sets(bad):
    with pytest.raises(ValueError):
        canonical_json({"x": bad})


def test_a_stage_must_name_itself(tmp_path):
    class Nameless(Stage):
        pass

    with pytest.raises(TypeError, match="name and code_version"):
        Nameless().cache_key({}, ctx_at(tmp_path))


def test_failed_write_leaves_no_artifact_and_first_writer_wins(tmp_path):
    store = Store(tmp_path / "s")
    key = "a" * 64

    def broken(out: Path):
        (out / "x").write_text("1", encoding="utf-8")
        raise OSError("disk full")

    with pytest.raises(OSError):
        store.put(key, broken)
    assert store.get(key) is None
    assert not list((tmp_path / "s" / "aa").iterdir())
    first = store.put(key, lambda out: (out / "x").write_text("first", encoding="utf-8"))
    again = store.put(key, lambda out: (out / "x").write_text("second", encoding="utf-8"))
    assert first == again and (first / "x").read_text(encoding="utf-8") == "first"
    with pytest.raises(ValueError):
        store.path("../../etc")


def test_concurrent_writers_of_one_key_are_safe(tmp_path):
    store = Store(tmp_path / "s")
    key = "b" * 64
    results, errors = [], []

    def writer(i):
        try:
            results.append(
                store.put(key, lambda out: (out / "x").write_text(str(i), encoding="utf-8"))
            )
        except Exception as exc:  # pragma: no cover - the test fails on any error
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and len(set(results)) == 1
    assert len([p for p in (tmp_path / "s" / "bb").iterdir()]) == 1


def test_content_hash_sees_names_and_bytes(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    (a / "f.txt").write_text("1", encoding="utf-8")
    h = content_hash(a)
    (a / "f.txt").write_text("2", encoding="utf-8")
    assert content_hash(a) != h
    (a / "f.txt").rename(a / "g.txt")
    assert content_hash(a) != h


def test_lineage_records_every_stage(tmp_path):
    ctx, c, _d = pipeline(tmp_path)
    run = json.loads((ctx.run_dir / "run.json").read_text(encoding="utf-8"))
    assert [s["stage"] for s in run["stages"]] == ["source:source", "count", "double"]
    assert run["stages"][1]["parents"] == [run["stages"][0]["key"]]
    assert run["stages"][2]["parents"] == [c.key]
    assert "simulator_hash" in run
    assert run["seed"] == 7 and run["config_hash"] == "cfg" and "git_sha" in run
    assert all({"key", "cache_hit", "started_at", "seconds"} <= set(s) for s in run["stages"])


def test_resume_reuses_finished_stages_and_reruns_only_what_changed(tmp_path):
    Count.calls = Double.calls = 0
    pipeline(tmp_path)
    assert (Count.calls, Double.calls) == (1, 1)
    ctx, _, d = pipeline(tmp_path)
    assert (Count.calls, Double.calls) == (1, 1)
    run = json.loads((ctx.run_dir / "run.json").read_text(encoding="utf-8"))
    assert all(s["cache_hit"] for s in run["stages"][-2:])
    pipeline(tmp_path, text="hello world")
    assert (Count.calls, Double.calls) == (2, 2)
    assert (d.path / "d.txt").read_text(encoding="utf-8") == "10"


def test_failed_stage_logs_its_error_and_stores_nothing(tmp_path):
    ctx = ctx_at(tmp_path)
    with pytest.raises(RuntimeError):
        run_stage(Boom(), {}, ctx)
    lines = [
        json.loads(x) for x in (ctx.run_dir / "run.log").read_text(encoding="utf-8").splitlines()
    ]
    assert lines[-1]["stage"] == "boom" and "stage exploded" in lines[-1]["error"]
    assert ctx.store.get(Boom().cache_key({}, ctx)) is None


def test_run_log_has_one_line_per_stage_run(tmp_path):
    ctx, _, _ = pipeline(tmp_path)
    lines = [
        json.loads(x) for x in (ctx.run_dir / "run.log").read_text(encoding="utf-8").splitlines()
    ]
    assert [x["stage"] for x in lines] == ["count", "double"]
    assert all({"stage", "key", "cache_hit", "seconds", "error"} == set(x) for x in lines)


def test_stage_seed_is_pinned_and_differs_by_stage():
    assert stage_seed(20261121, "features") == stage_seed(20261121, "features")
    assert stage_seed(20261121, "features") != stage_seed(20261121, "churn")
    assert stage_seed(1, "x") == PINNED_SEED
    assert 0 <= stage_seed(0, "a") < 2**63
    with pytest.raises(ValueError):
        stage_seed(-1, "a")


def test_member_draws_do_not_depend_on_cohort_order_or_batch():
    ids = [f"S{i:06d}" for i in range(500)]
    h = member_hashes(ids)
    full = member_uniforms(42, h, period=1, stream="renew", n_draws=3)
    rng = np.random.default_rng(0)
    order = rng.permutation(len(ids))
    shuffled = member_uniforms(42, h[order], period=1, stream="renew", n_draws=3)
    assert np.array_equal(shuffled, full[order])
    single = member_uniforms(42, member_hashes([ids[17]]), period=1, stream="renew", n_draws=3)
    assert np.array_equal(single[0], full[17])
    assert not np.array_equal(member_uniforms(42, h, 2, "renew", 3), full)
    assert not np.array_equal(member_uniforms(42, h, 1, "accept", 3), full)
    assert not np.array_equal(member_uniforms(43, h, 1, "renew", 3), full)


def test_member_uniforms_are_uniform():
    h = member_hashes(f"M{i}" for i in range(200_000))
    u = member_uniforms(5, h, 1, "renew").ravel()
    assert u.min() >= 0.0 and u.max() < 1.0
    counts, _ = np.histogram(u, bins=20, range=(0, 1))
    expected = len(u) / 20
    chi2 = float(((counts - expected) ** 2 / expected).sum())
    assert chi2 < 43.8  # 19 degrees of freedom, p = 0.001
    assert abs(float(np.corrcoef(u[:-1], u[1:])[0, 1])) < 0.01


def test_member_uniforms_refuse_bad_inputs():
    with pytest.raises(TypeError):
        member_uniforms(1, np.array([1, 2]), 1, "s")
    with pytest.raises(ValueError):
        member_uniforms(1, member_hashes(["a"]), -1, "s")


def test_bucket_is_stable_and_spreads_members():
    ids = [f"S{i:06d}" for i in range(20_000)]
    b = bucket("salt", ids)
    assert np.array_equal(b, bucket("salt", ids))
    assert b.min() >= 0 and b.max() <= 99
    counts = np.bincount(b, minlength=100)
    assert counts.min() > 120 and counts.max() < 280
    assert not np.array_equal(b, bucket("other-salt", ids))


class Base(Stage):
    name = ""
    code_version = "1"


class Child(Base):
    name = "child"
    code_version = "1"

    def run(self, inputs, out, ctx):
        pass


def helper():
    return 1


def test_version_check_catches_unbumped_changes(tmp_path, monkeypatch):
    manifest = {"child": {"code_version": "1", "hash": versions.behaviour_hash(Child)}}
    assert versions.problems({"child": Child}, manifest) == []
    stale = {"child": {"code_version": "1", "hash": "0" * 64}}
    assert "still 1" in versions.problems({"child": Child}, stale)[0]

    class Bumped(Child):
        code_version = "2"

    assert "run --update" in versions.problems({"child": Bumped}, stale)[0]
    assert versions.problems({}, manifest) == [
        "child: in versions.json but no such stage (run --update to retire it)"
    ]
    assert "not in versions.json" in versions.problems({"child": Child}, {})[0]
    path = tmp_path / "v.json"
    path.write_text(json.dumps(stale), encoding="utf-8")
    assert versions.update({"child": Child}, path)  # refused: changed without a bump
    assert json.loads(path.read_text(encoding="utf-8")) == stale
    assert versions.update({"child": Bumped}, path) == []


def test_base_class_and_helper_changes_change_the_hash(monkeypatch):
    before = versions.behaviour_hash(Child)
    monkeypatch.setattr(Base, "threshold", 0.5, raising=False)
    assert versions.behaviour_hash(Child) != before

    class WithHelper(Child):
        extra_sources = (helper,)

    class WithOtherHelper(Child):
        extra_sources = (other_helper,)

    assert versions.behaviour_hash(WithHelper) != versions.behaviour_hash(WithOtherHelper)


def other_helper():
    return 2


def test_live_manifest_matches_every_stage():
    assert versions.problems(versions.all_stages(), versions.load_manifest()) == []


PINNED_SEED = 36874684315098989  # stage_seed(1, "x"); a change breaks every cached run


def test_member_draws_are_pinned_across_machines_and_versions():
    got = member_uniforms(42, member_hashes(["S000001"]), 1, "renew", 2)[0].tolist()
    assert got == [0.3461975425047906, 0.47504223742393636]
