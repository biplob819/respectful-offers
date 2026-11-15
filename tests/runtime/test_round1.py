"""Regression tests for the N1.3 verifier's round-1 findings."""

import importlib
import json
import subprocess
import sys
import textwrap
import threading

import pytest

from respectful_offers.runtime import (
    RunContext,
    Stage,
    canonical_json,
    import_artifact,
    run_stage,
    versions,
)
from respectful_offers.runtime.seeds import member_hashes, member_uniforms


def test_mixed_key_types_are_refused_not_merged():
    with pytest.raises(ValueError, match="string keys"):
        canonical_json({1: "a", "1": "b"})


def _stage_module(tmp_path, body):
    pkg = tmp_path / "pkgv"
    pkg.mkdir(exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(textwrap.dedent(body), encoding="utf-8")
    return pkg / "mod.py"


BODY = """
from respectful_offers.runtime import Stage

THRESH = {thresh}


def helper():
    return {ret}


class Mixin:
    def extra(self):
        return {mix}


class S(Stage, Mixin):
    name = "s-under-test"
    code_version = "1"
    extra_sources = (helper,)
    tags = {{"b", "a", "c"}}

    def run(self, inputs, out, ctx):
        pass
"""


def _hash_in_subprocess(tmp_path):
    code = (
        f"import sys; sys.path.insert(0, {str(tmp_path)!r})\n"
        "from respectful_offers.runtime import versions\n"
        "import pkgv.mod as m\n"
        "print(versions.behaviour_hash(m.S))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_behaviour_hash_is_stable_across_processes_with_helpers_and_sets(tmp_path):
    _stage_module(tmp_path, BODY.format(thresh=0.5, ret=1, mix=1))
    a = _hash_in_subprocess(tmp_path)
    b = _hash_in_subprocess(tmp_path)
    assert a == b and len(a) == 64


@pytest.mark.parametrize(
    "change",
    [
        {"thresh": 0.9, "ret": 1, "mix": 1},
        {"thresh": 0.5, "ret": 2, "mix": 1},
        {"thresh": 0.5, "ret": 1, "mix": 2},
    ],
)
def test_module_constants_helpers_and_late_mixins_change_the_hash(tmp_path, change):
    _stage_module(tmp_path, BODY.format(thresh=0.5, ret=1, mix=1))
    before = _hash_in_subprocess(tmp_path)
    _stage_module(tmp_path, BODY.format(**change))
    assert _hash_in_subprocess(tmp_path) != before


class V(Stage):
    name = "v"
    code_version = "2"

    def run(self, inputs, out, ctx):
        pass


def test_version_downgrades_and_non_integer_versions_are_refused(tmp_path):
    path = tmp_path / "v.json"
    path.write_text(
        json.dumps({"v": {"code_version": "3", "hash": versions.behaviour_hash(V)}}),
        encoding="utf-8",
    )
    assert any("went down" in p for p in versions.update({"v": V}, path))

    class W(V):
        code_version = "2a"

    assert any("decimal integer" in p for p in versions.problems({"v": W}, {}))


def test_unstable_constants_are_refused():
    class X(V):
        handler = object()

    with pytest.raises(ValueError, match="stable representation"):
        versions.behaviour_hash(X)


class Mutator(Stage):
    name = "mutator"
    code_version = "1"

    def run(self, inputs, out, ctx):
        target = inputs["src"] / "in.txt"
        try:
            target.write_text("MUTATED", encoding="utf-8")
        except PermissionError:
            target.chmod(0o644)
            target.write_text("MUTATED", encoding="utf-8")
        (out / "x").write_text("1", encoding="utf-8")


def test_a_stage_cannot_rewrite_its_inputs(tmp_path):
    ctx = RunContext(tmp_path, "r", "cfg", 1)
    f = tmp_path / "in.txt"
    f.write_text("hello", encoding="utf-8")
    src = import_artifact(ctx, "source", {"in.txt": f})
    with pytest.raises(PermissionError):
        (src.path / "in.txt").write_text("x", encoding="utf-8")
    with pytest.raises(RuntimeError, match="modified its input artifact 'src'"):
        run_stage(Mutator(), {"src": src}, ctx)
    run = ctx.lineage[-1]
    assert run["stage"] == "mutator" and "modified" in run["error"]


class Pol(Stage):
    name = "pol"
    code_version = "1"

    def __init__(self, kind):
        self.kind = kind

    def run(self, inputs, out, ctx):
        (out / "k").write_text(self.kind, encoding="utf-8")


def test_instance_parameters_and_simulator_hash_are_in_the_key(tmp_path):
    ctx = RunContext(tmp_path, "r", "cfg", 1)
    assert Pol("greedy").cache_key({}, ctx) != Pol("bandit").cache_key({}, ctx)
    other = RunContext(tmp_path, "r", "cfg", 1, simulator_hash="abc")
    assert Pol("greedy").cache_key({}, ctx) != Pol("greedy").cache_key({}, other)


def test_import_artifact_refuses_escaping_names_and_logs_lineage(tmp_path):
    ctx = RunContext(tmp_path, "r", "cfg", 1)
    f = tmp_path / "a.txt"
    f.write_text("a", encoding="utf-8")
    for bad in ("../../escaped.txt", "/abs.txt", "", "a\\\\b.txt"):
        with pytest.raises(ValueError):
            import_artifact(ctx, "source", {bad: f})
    ref = import_artifact(ctx, "source", {"a.txt": f})
    assert ctx.lineage[-1] == {**ctx.lineage[-1], "stage": "source:source", "key": ref.key}


def test_concurrent_lineage_writers_do_not_collide(tmp_path):
    errors = []

    def go():
        try:
            for _ in range(50):
                RunContext(tmp_path, "same", "cfg", 1).write_lineage()
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert errors == []
    assert (
        json.loads((tmp_path / "runs" / "same" / "run.json").read_text(encoding="utf-8"))["run_id"]
        == "same"
    )
    assert not list((tmp_path / "runs" / "same").glob(".run-*"))


class BadKey(Stage):
    name = "badkey"
    code_version = "1"

    def params(self):
        return {"x": float("nan")}


def test_errors_in_the_cache_key_are_logged(tmp_path):
    ctx = RunContext(tmp_path, "r", "cfg", 1)
    with pytest.raises(ValueError):
        run_stage(BadKey(), {}, ctx)
    line = json.loads((ctx.run_dir / "run.log").read_text(encoding="utf-8").splitlines()[-1])
    assert line["stage"] == "badkey" and "NaN" in line["error"]


def test_float_periods_are_refused():
    with pytest.raises(TypeError, match="integer"):
        member_uniforms(1, member_hashes(["a"]), 1.0, "s")  # type: ignore[arg-type]
    importlib.import_module("respectful_offers.runtime.seeds")
