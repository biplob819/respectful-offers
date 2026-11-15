"""Regression tests for the N1.3 verifier's round-2 findings."""

import contextlib
import json
import subprocess
import sys
import textwrap
from abc import ABC
from typing import Generic, TypeVar

import pytest

from respectful_offers.runtime import RunContext, Stage, import_artifact, run_stage, versions
from respectful_offers.runtime.seeds import member_hashes, member_uniforms, stage_seed

In = TypeVar("In")


class AbcStage(Stage, ABC):
    name = "abc-stage"
    code_version = "1"

    def run(self, inputs, out, ctx):
        pass


class GenericStage(Stage, Generic[In]):
    name = "generic-stage"
    code_version = "1"

    def run(self, inputs, out, ctx):
        pass


def test_abc_and_generic_bases_hash_without_library_sources():
    assert len(versions.behaviour_hash(AbcStage)) == 64
    assert not versions._is_project_class(Generic)  # type: ignore[arg-type]
    assert not versions._is_project_class(ABC)
    assert versions._is_project_class(Stage)


def test_generic_stage_hash_is_identical_on_every_python(tmp_path):
    pkg = tmp_path / "gen"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "m.py").write_text(
        textwrap.dedent("""
        from typing import Generic, TypeVar
        from respectful_offers.runtime import Stage
        T = TypeVar("T")
        class G(Stage, Generic[T]):
            name = "g"
            code_version = "1"
            def run(self, inputs, out, ctx):
                pass
    """),
        encoding="utf-8",
    )
    code = (
        f"import sys; sys.path.insert(0, {str(tmp_path)!r})\n"
        "from respectful_offers.runtime import versions; import gen.m as m\n"
        "print(versions.behaviour_hash(m.G))\n"
    )
    hashes = set()
    for py in ("3.11", "3.13"):
        r = subprocess.run(
            [
                "uv",
                "run",
                "--python",
                py,
                "--isolated",
                "--with-editable",
                ".",
                "python",
                "-c",
                code,
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"Python {py} not available: {r.stderr[-200:]}")
        hashes.add(r.stdout.strip())
    assert len(hashes) == 1


def test_imported_constants_change_the_hash(tmp_path):
    pkg = tmp_path / "impcfg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "cfg.py").write_text("THRESH = 0.5\n", encoding="utf-8")
    (pkg / "m.py").write_text(
        textwrap.dedent("""
        from impcfg.cfg import THRESH
        from respectful_offers.runtime import Stage
        class S(Stage):
            name = "s"
            code_version = "1"
            def run(self, inputs, out, ctx):
                return THRESH
    """),
        encoding="utf-8",
    )
    code = (
        f"import sys; sys.path.insert(0, {str(tmp_path)!r})\n"
        "from respectful_offers.runtime import versions; import impcfg.m as m\n"
        "print(versions.behaviour_hash(m.S))\n"
    )

    def run():
        return subprocess.run(
            [sys.executable, "-B", "-c", code], capture_output=True, text=True, check=True
        ).stdout

    before = run()
    (pkg / "cfg.py").write_text("THRESH = 0.9\n", encoding="utf-8")
    assert run() != before


class Gone(Stage):
    name = "gone"
    code_version = "1"

    def run(self, inputs, out, ctx):
        pass


def test_a_removed_stage_cannot_come_back_at_an_old_version(tmp_path):
    path = tmp_path / "v.json"
    assert versions.update({"gone": Gone}, path) == []
    assert versions.update({}, path) == []
    assert json.loads(path.read_text(encoding="utf-8"))["gone"]["retired"] is True
    assert versions.problems({}, json.loads(path.read_text(encoding="utf-8"))) == []
    refused = versions.update({"gone": Gone}, path)
    assert refused and "must exceed" in refused[0]

    class Back(Gone):
        code_version = "2"

    assert versions.update({"gone": Back}, path) == []


def test_a_hand_edited_manifest_version_gives_a_clear_message():
    out = versions.problems({"gone": Gone}, {"gone": {"code_version": "1a", "hash": "x"}})
    assert out == ["gone: versions.json holds a non-integer code_version '1a'"]


class Poisoner(Stage):
    name = "poisoner"
    code_version = "1"

    def run(self, inputs, out, ctx):
        target = inputs["src"] / "in.txt"
        for p in (inputs["src"], target):
            with contextlib.suppress(PermissionError):
                p.chmod(0o755 if p.is_dir() else 0o644)
        target.unlink()
        target.write_text("POISON", encoding="utf-8")
        raise RuntimeError("stage failed after poisoning")


class Reader(Stage):
    name = "reader"
    code_version = "1"

    def run(self, inputs, out, ctx):
        (out / "copy.txt").write_text(
            (inputs["src"] / "in.txt").read_text(encoding="utf-8"), encoding="utf-8"
        )


def test_a_failing_stage_that_poisons_its_input_is_caught_and_the_input_evicted(tmp_path):
    ctx = RunContext(tmp_path, "r", "cfg", 1)
    f = tmp_path / "in.txt"
    f.write_text("hello", encoding="utf-8")
    src = import_artifact(ctx, "source", {"in.txt": f})
    with pytest.raises(RuntimeError, match="modified its input artifact"):
        run_stage(Poisoner(), {"src": src}, ctx)
    assert ctx.store.get(src.key) is None  # evicted, never served again
    fresh = import_artifact(ctx, "source", {"in.txt": f})
    out = run_stage(Reader(), {"src": fresh}, ctx)
    assert (out.path / "copy.txt").read_text(encoding="utf-8") == "hello"


@pytest.mark.parametrize("bad", ["C:evil.txt", "c:/x.txt", "a:b"])
def test_windows_drive_names_are_refused(tmp_path, bad):
    ctx = RunContext(tmp_path, "r", "cfg", 1)
    f = tmp_path / "a.txt"
    f.write_text("a", encoding="utf-8")
    with pytest.raises(ValueError):
        import_artifact(ctx, "source", {bad: f})


def test_float_root_seeds_are_refused():
    with pytest.raises(TypeError):
        stage_seed(42.0, "x")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        member_uniforms(42.0, member_hashes(["a"]), 1, "s")  # type: ignore[arg-type]
