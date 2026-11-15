"""Content-addressed artifact store (D-10, RUN-02).

An artifact is a directory of files under `.offers/store/<key[:2]>/<key>/`. It is written
into a temporary sibling directory and renamed into place, so a reader never sees half an
artifact. If another writer got there first, the first writer wins and the second copy is
discarded (EvalKit L-18). `content_hash` hashes file names and bytes, in sorted order.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

KEY_LEN = 64


MARKER = ".complete"


def file_sha256(path: Path, chunk: int = 1 << 20) -> bytes:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.digest()


def content_hash(directory: Path) -> str:
    """Hash of every file name and its bytes, in sorted order, excluding the store's marker."""
    h = hashlib.sha256()
    for p in sorted(directory.rglob("*")):
        if p.is_file() and not (p.parent == directory and p.name == MARKER):
            rel = p.relative_to(directory).as_posix()
            h.update(rel.encode("utf-8") + b"\0")
            h.update(file_sha256(p))
    return h.hexdigest()


def make_read_only(directory: Path) -> None:
    """Artifacts are immutable once stored: files and folders are read-only, so a stage cannot
    quietly rewrite, delete or add to its inputs (the folder itself is locked after rename)."""
    for p in sorted(directory.rglob("*"), reverse=True):
        p.chmod(0o555 if p.is_dir() else 0o444)


class Store:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path(self, key: str) -> Path:
        if len(key) != KEY_LEN or any(c not in "0123456789abcdef" for c in key):
            raise ValueError(f"not a store key: {key!r}")
        return self.root / key[:2] / key

    def get(self, key: str) -> Path | None:
        p = self.path(key)
        return p if (p / MARKER).is_file() else None

    def put(self, key: str, write: Callable[[Path], object]) -> Path:
        """Run `write(tmp_dir)` and publish the result atomically under `key`."""
        final = self.path(key)
        existing = self.get(key)
        if existing is not None:
            return existing
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=f".{key[:8]}-", dir=final.parent))
        try:
            write(tmp)
            digest = content_hash(tmp)
            make_read_only(tmp)
            (tmp / MARKER).write_text(digest + "\n", encoding="utf-8")
            try:
                os.replace(tmp, final)
            except OSError:
                if self.get(key) is None:  # not a lost race: a real failure
                    raise
        finally:
            if tmp.exists():
                _force_rmtree(tmp)
        got = self.get(key)
        if got is None:  # pragma: no cover - replace succeeded but marker vanished
            raise RuntimeError(f"artifact {key} missing after write")
        if os.name != "nt":
            got.chmod(0o555)
        return got

    def evict(self, key: str) -> None:
        """Remove an artifact (e.g. one a stage corrupted) so the next run rebuilds it."""
        p = self.path(key)
        if p.exists():
            _force_rmtree(p)

    def stored_hash(self, key: str) -> str:
        p = self.get(key)
        if p is None:
            raise KeyError(key)
        return (p / MARKER).read_text(encoding="utf-8").strip()


def _force_rmtree(path: Path) -> None:
    def retry(func, p, _exc):  # read-only files and folders
        os.chmod(p, 0o755)
        func(p)

    for root, dirs, files in os.walk(path):
        for name in dirs:
            os.chmod(os.path.join(root, name), 0o755)
        for name in files:
            os.chmod(os.path.join(root, name), 0o644)
    os.chmod(path, 0o755)

    shutil.rmtree(path, onexc=retry) if sys.version_info >= (3, 12) else shutil.rmtree(
        path, onerror=retry
    )  # type: ignore[call-arg]
