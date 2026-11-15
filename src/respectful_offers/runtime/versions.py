"""Stale-cache guard (RUN-05): a stage whose behaviour changes must bump `code_version`.

`behaviour_hash` covers, for every class in the stage's MRO (mixins included, wherever they
sit; `object` and built-ins excepted):
  - the class source,
  - its class-level constants, rendered stably (sets sorted; anything whose repr holds a
    memory address is refused, since it would change every run),
  - the module-level constants (top-level assignments) of the module it is defined in,
plus the source of any helper functions the stage lists in `extra_sources`
(EvalKit L-13, L-21, L-23; N1.3 verifier).

`code_version` is a decimal integer string. The manifest `versions.json` records, per stage
name, the version and hash last accepted. A hash change without a version increase is an
error, and so is a version that goes down (it would revive stale cache entries).

    python -m respectful_offers.runtime.versions           # check
    python -m respectful_offers.runtime.versions --update  # accept increased versions
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import importlib.util
import inspect
import json
import pkgutil
import re
import sys
import sysconfig
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

import respectful_offers
from respectful_offers.runtime.stage import Stage

MANIFEST = Path(__file__).with_name("versions.json")
_ADDRESS = re.compile(r" at 0x[0-9a-fA-F]+")


def all_stages() -> dict[str, type[Stage]]:
    for mod in pkgutil.walk_packages(respectful_offers.__path__, "respectful_offers."):
        importlib.import_module(mod.name)
    found: dict[str, type[Stage]] = {}

    def walk(cls: type[Stage]) -> None:
        for sub in cls.__subclasses__():
            if sub.name and sub.__module__.startswith("respectful_offers."):
                if sub.name in found and found[sub.name] is not sub:
                    raise ValueError(f"two stages are named {sub.name!r}")
                found[sub.name] = sub
            walk(sub)

    walk(Stage)
    return dict(sorted(found.items()))


def _stable(value: Any) -> str:
    if isinstance(value, set | frozenset):
        return "{" + ", ".join(sorted(_stable(v) for v in value)) + "}"
    if isinstance(value, list | tuple):
        inner = ", ".join(_stable(v) for v in value)
        return f"[{inner}]" if isinstance(value, list) else f"({inner})"
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(
                f"{_stable(k)}: {_stable(v)}"
                for k, v in sorted(value.items(), key=lambda kv: repr(kv[0]))
            )
            + "}"
        )
    text = repr(value)
    if _ADDRESS.search(text):
        raise ValueError(f"constant {text!r} has no stable representation; use plain data")
    return text


_LIBRARY_ROOTS = tuple(
    {
        Path(sysconfig.get_paths()[k]).resolve()
        for k in ("stdlib", "platstdlib", "purelib", "platlib")
    }
)


def _is_project_class(klass: type) -> bool:
    """Only the project's own classes (and test stages) are hashed: standard-library and
    third-party sources (typing.Generic, abc.ABC, ...) differ across Python versions and
    would make one manifest fail on another version (N1.3 verifier)."""
    if klass is object or klass.__module__ in ("builtins", "typing", "abc"):
        return False
    if klass.__module__.startswith("respectful_offers"):
        return True
    try:
        src = inspect.getsourcefile(klass)
    except TypeError:
        return False
    if src is None:
        return False
    path = Path(src).resolve()
    return not any(path.is_relative_to(root) for root in _LIBRARY_ROOTS)


def _constants(cls: type) -> dict[str, str]:
    out = {}
    for k, v in vars(cls).items():
        if k.startswith("__") or k.startswith("_abc") or k == "extra_sources":
            continue
        if callable(v) or isinstance(v, classmethod | staticmethod | property):
            continue
        out[k] = _stable(v)
    return out


@cache
def _module_constants(module_name: str) -> str:
    module = sys.modules.get(module_name)
    try:
        source = inspect.getsource(module) if module else ""
    except (OSError, TypeError):
        return ""
    tree = ast.parse(source)
    parts = []
    for node in tree.body:
        if isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
            parts.append(ast.get_source_segment(source, node) or "")
        elif isinstance(node, ast.ImportFrom):
            # constants imported from elsewhere count as this module's constants
            for alias in node.names:
                value = getattr(module, alias.asname or alias.name, None)
                if _is_data(value):
                    parts.append(f"{alias.asname or alias.name} = {_stable(value)}")
    return "\n".join(parts)


def _is_data(value: Any) -> bool:
    if isinstance(value, bool | int | float | str | bytes) or value is None:
        return True
    if isinstance(value, list | tuple | set | frozenset):
        return all(_is_data(v) for v in value)
    if isinstance(value, dict):
        return all(_is_data(k) and _is_data(v) for k, v in value.items())
    return False


# The runner and this guard are infrastructure, not stage behaviour; editing them must not
# force every stage to bump.
_INFRASTRUCTURE = ("respectful_offers.runtime",)


@cache
def _module_source(name: str) -> str:
    module = sys.modules.get(name) or importlib.import_module(name)
    try:
        return inspect.getsource(module)
    except (OSError, TypeError):
        return ""


def _imports_of(name: str) -> set[str]:
    source = _module_source(name)
    if not source:
        return set()
    found: set[str] = set()
    package = name.rsplit(".", 1)[0]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = ".".join(name.split(".")[: -node.level]) if node.level else package
                mod = f"{base}.{node.module}" if node.module else base
            else:
                mod = node.module or ""
            candidates = [mod] + [f"{mod}.{a.name}" for a in node.names]
        elif isinstance(node, ast.Import):
            candidates = [a.name for a in node.names]
        else:
            continue
        for c in candidates:
            if c.startswith("respectful_offers.") and _is_module(c):
                found.add(c)
    return found


def _is_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ModuleNotFoundError, ValueError):  # e.g. a function imported from a module
        return False


def _project_imports(start: tuple[str, ...]) -> set[str]:
    """Project modules reachable from `start` by import, excluding the runtime package."""
    seen: set[str] = set()
    todo = [m for m in start if m.startswith("respectful_offers.")]
    while todo:
        m = todo.pop()
        if m in seen or m.startswith(_INFRASTRUCTURE):
            continue
        seen.add(m)
        todo.extend(_imports_of(m) - seen)
    return seen


def behaviour_hash(cls: type[Stage]) -> str:
    h = hashlib.sha256()
    modules = []
    for klass in cls.__mro__:
        if not _is_project_class(klass):
            continue
        try:
            src = inspect.getsource(klass)
        except (OSError, TypeError):  # built-in or C class
            continue
        h.update(src.encode("utf-8"))
        h.update(json.dumps(_constants(klass), sort_keys=True).encode("utf-8"))
        if klass.__module__ not in modules:
            modules.append(klass.__module__)
    for name in modules:
        h.update(_module_constants(name).encode("utf-8"))
    # every project module the stage's modules import, transitively, by full source: a change
    # to any helper a stage calls (in any module) changes its hash (N1.4 verifier)
    for name in sorted(_project_imports(tuple(modules))):
        h.update(name.encode("utf-8") + b"\0" + _module_source(name).encode("utf-8"))
    extra: tuple[Callable[..., Any], ...] = getattr(cls, "extra_sources", ())
    for fn in extra:
        h.update(inspect.getsource(fn).encode("utf-8"))
    return h.hexdigest()


def _version(cls: type[Stage]) -> int:
    if not re.fullmatch(r"[0-9]+", cls.code_version or ""):
        raise ValueError(
            f"{cls.name}: code_version must be a decimal integer, got {cls.code_version!r}"
        )
    return int(cls.code_version)


def load_manifest(path: Path = MANIFEST) -> dict[str, dict[str, str]]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def problems(stages: dict[str, type[Stage]], manifest: dict[str, dict[str, str]]) -> list[str]:
    out = []
    for name, cls in stages.items():
        rec = manifest.get(name)
        try:
            version = _version(cls)
        except ValueError as exc:
            out.append(str(exc))
            continue
        if rec is None:
            out.append(f"{name}: not in versions.json (run with --update)")
            continue
        try:
            old = int(str(rec["code_version"]))
        except ValueError:
            out.append(
                f"{name}: versions.json holds a non-integer code_version {rec['code_version']!r}"
            )
            continue
        if rec.get("retired"):
            if version <= old:
                out.append(
                    f"{name}: re-added at code_version {version}; it must exceed the retired {old}"
                )
            else:
                out.append(f"{name}: re-added at code_version {version}; run --update")
            continue
        if version < old:
            out.append(f"{name}: code_version went down from {old} to {version}")
        elif behaviour_hash(cls) != rec["hash"]:
            if version == old:
                out.append(f"{name}: behaviour changed but code_version is still {version}")
            else:
                out.append(f"{name}: code_version bumped to {version}; run --update")
        elif version != old:
            out.append(f"{name}: code_version changed to {version}; run --update")
    for name, rec in manifest.items():
        if name not in stages and not rec.get("retired"):
            out.append(f"{name}: in versions.json but no such stage (run --update to retire it)")
    return out


def update(stages: dict[str, type[Stage]], path: Path = MANIFEST) -> list[str]:
    """Accept new stages and increased versions; refuse unbumped changes and downgrades."""
    manifest = load_manifest(path)
    refused = [
        p
        for p in problems(stages, manifest)
        if any(w in p for w in ("still", "went down", "decimal", "must exceed", "non-integer"))
    ]
    if refused:
        return refused
    new: dict[str, dict[str, Any]] = {
        n: {"code_version": c.code_version, "hash": behaviour_hash(c)} for n, c in stages.items()
    }
    for name, rec in manifest.items():  # retired stages keep their highest version forever
        if name not in new:
            new[name] = {
                "code_version": str(rec["code_version"]),
                "hash": rec["hash"],
                "retired": True,
            }
    path.write_text(json.dumps(new, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--update", action="store_true")
    args = ap.parse_args(argv)
    stages = all_stages()
    issues = update(stages) if args.update else problems(stages, load_manifest())
    for p in issues:
        print(p)
    print("versions:", "FAIL" if issues else f"OK ({len(stages)} stages)")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
