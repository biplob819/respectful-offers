"""Stage contract, executor, lineage and run log (Tech Spec §2.1, RUN-01, RUN-03..RUN-06).

A stage turns named input artifacts into one output artifact (a directory of files). Its
cache key covers the stage name, its `code_version`, every input artifact's content hash,
the run's config hash and the seed, so rerunning a run is resuming it: finished stages are
cache hits and only what changed runs again.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, ClassVar

from respectful_offers.runtime.store import Store, content_hash, file_sha256


def canonical_json(value: Any) -> str:
    """JSON with sorted keys and no whitespace; rejects NaN and infinity."""

    def check(v: Any) -> Any:
        if isinstance(v, float) and not math.isfinite(v):
            raise ValueError("NaN and infinity cannot be part of a cache key")
        if isinstance(v, Mapping):
            bad = [k for k in v if not isinstance(k, str)]
            if bad:
                raise ValueError(f"cache-key mappings need string keys, got {bad[:3]!r}")
            return {k: check(x) for k, x in v.items()}
        if isinstance(v, list | tuple):
            return [check(x) for x in v]
        if isinstance(v, set | frozenset):
            raise ValueError("sets have no order; use a sorted list")
        return v

    return json.dumps(check(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ArtifactRef:
    stage: str
    key: str
    path: Path
    content_hash: str


@dataclass
class RunContext:
    root: Path
    run_id: str
    config_hash: str
    seed: int
    git_sha: str = "unknown"
    simulator_hash: str | None = None
    store: Store = field(init=False)
    lineage: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.store = Store(self.root / ".offers" / "store")

    @property
    def run_dir(self) -> Path:
        return self.root / "runs" / self.run_id

    def log(self, **record: Any) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with (self.run_dir / "run.log").open("a", encoding="utf-8") as fh:
            fh.write(canonical_json(record) + "\n")

    def write_lineage(self) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        path = self.run_dir / "run.json"
        body = {
            "run_id": self.run_id,
            "git_sha": self.git_sha,
            "config_hash": self.config_hash,
            "simulator_hash": self.simulator_hash,
            "seed": self.seed,
            "stages": self.lineage,
        }
        fd, name = tempfile.mkstemp(prefix=".run-", suffix=".json", dir=self.run_dir)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:  # a unique temp file per writer
            fh.write(json.dumps(body, indent=2, sort_keys=True) + "\n")
        os.replace(name, path)
        return path


class Stage:
    """Subclass, set `name` and `code_version`, and implement `run`."""

    name: ClassVar[str] = ""
    code_version: ClassVar[str] = ""

    def params(self) -> dict[str, Any]:
        """Parameters that change the output; part of the cache key. By default every instance
        attribute, so `Policy("greedy")` and `Policy("bandit")` never share a key."""
        return {k: v for k, v in sorted(vars(self).items()) if not k.startswith("_")}

    def cache_key(self, inputs: Mapping[str, ArtifactRef], ctx: RunContext) -> str:
        if not self.name or not self.code_version:
            raise TypeError(f"{type(self).__name__} must set name and code_version")
        return sha256_text(
            canonical_json(
                {
                    "stage": self.name,
                    "code_version": self.code_version,
                    "inputs": {k: v.content_hash for k, v in sorted(inputs.items())},
                    "params": self.params(),
                    "config_hash": ctx.config_hash,
                    "simulator_hash": ctx.simulator_hash,
                    "seed": ctx.seed,
                }
            )
        )

    def run(self, inputs: Mapping[str, Path], out: Path, ctx: RunContext) -> None:
        raise NotImplementedError


def run_stage(stage: Stage, inputs: Mapping[str, ArtifactRef], ctx: RunContext) -> ArtifactRef:
    """Run a stage or reuse its cached artifact; record lineage and a run.log line.

    After the stage runs, every input artifact is re-hashed: a stage that changed its inputs
    fails and stores nothing (artifacts are also written read-only)."""
    started = time.perf_counter()
    started_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    key = "unknown"
    cached = None

    def check_inputs() -> None:
        for name, ref in inputs.items():
            if not ref.path.is_dir() or content_hash(ref.path) != ref.content_hash:
                ctx.store.evict(ref.key)  # never serve a corrupted artifact again
                raise RuntimeError(f"stage {stage.name} modified its input artifact {name!r}")

    def write(out: Path) -> None:
        try:
            stage.run({k: v.path for k, v in inputs.items()}, out, ctx)
        finally:  # also when the stage raised: a failing stage may have damaged its inputs
            check_inputs()

    try:
        key = stage.cache_key(inputs, ctx)
        cached = ctx.store.get(key)
        path = cached if cached is not None else ctx.store.put(key, write)
    except Exception as exc:
        seconds = round(time.perf_counter() - started, 3)
        error = f"{type(exc).__name__}: {exc}"
        ctx.lineage.append(
            {
                "stage": stage.name,
                "key": key,
                "parents": sorted(v.key for v in inputs.values()),
                "cache_hit": False,
                "started_at": started_at,
                "seconds": seconds,
                "error": error,
            }
        )
        ctx.log(stage=stage.name, key=key, cache_hit=False, seconds=seconds, error=error)
        raise
    ref = ArtifactRef(stage.name, key, path, ctx.store.stored_hash(key))
    seconds = round(time.perf_counter() - started, 3)
    ctx.lineage.append(
        {
            "stage": stage.name,
            "key": key,
            "parents": sorted(v.key for v in inputs.values()),
            "cache_hit": cached is not None,
            "started_at": started_at,
            "seconds": seconds,
            "error": None,
        }
    )
    ctx.log(stage=stage.name, key=key, cache_hit=cached is not None, seconds=seconds, error=None)
    return ref


def import_artifact(ctx: RunContext, stage_name: str, files: Mapping[str, Path]) -> ArtifactRef:
    """Bring external files (configs, small sources) into the store as a source artifact.

    Names must be relative paths inside the artifact. Files are hashed and copied in chunks.
    The import is recorded in lineage, so a source key named as a parent is always described.
    """
    for name in files:
        pure = PurePosixPath(name)
        if (
            pure.is_absolute()
            or ".." in pure.parts
            or "\\" in name
            or ":" in name
            or PureWindowsPath(name).drive
            or not name
        ):
            raise ValueError(f"artifact file name must be a relative path inside it: {name!r}")
    h = hashlib.sha256()
    for name, path in sorted(files.items()):
        h.update(name.encode("utf-8") + b"\0" + file_sha256(Path(path)))
    key = sha256_text(canonical_json({"source": stage_name, "files": h.hexdigest()}))

    def write(out: Path) -> None:
        for name, path in files.items():
            (out / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, out / name)

    path = ctx.store.put(key, write)
    ref = ArtifactRef(stage_name, key, path, ctx.store.stored_hash(key))
    ctx.lineage.append(
        {
            "stage": f"source:{stage_name}",
            "key": key,
            "parents": [],
            "files": sorted(files),
            "cache_hit": False,
            "started_at": None,
            "seconds": 0.0,
            "error": None,
        }
    )
    return ref


def git_sha(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
