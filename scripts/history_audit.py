#!/usr/bin/env python3
"""Audit the whole git history before release (OSS-01): every blob ever committed, on every
ref, goes through the same secret scan and data scan as the working tree, under the path it
was committed at. A file deleted later still counts: history is public too.

    python scripts/history_audit.py          # exit 1 and list hits if anything is found
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))


def blobs(root: Path = ROOT) -> dict[str, set[str]]:
    """Every blob id in the history of every ref, with the paths it was committed under."""
    out = subprocess.run(
        ["git", "rev-list", "--objects", "--all"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    ids = [line.split(" ", 1) for line in out.splitlines() if " " in line]
    kinds = subprocess.run(
        ["git", "cat-file", "--batch-check=%(objectname) %(objecttype)"],
        cwd=root,
        input="\n".join(i for i, _ in ids),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    is_blob = {line.split()[0] for line in kinds if line.endswith(" blob")}
    found: dict[str, set[str]] = {}
    for oid, path in ids:
        if oid in is_blob:
            found.setdefault(oid, set()).add(path)
    return found


def audit(root: Path = ROOT) -> tuple[int, list[str]]:
    import data_scan
    import secret_scan

    found = blobs(root)
    every_path = {p for paths in found.values() for p in paths}
    hits: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for oid, paths in sorted(found.items()):
            raw = subprocess.run(
                ["git", "cat-file", "blob", oid], cwd=root, capture_output=True, check=True
            ).stdout
            for path in sorted(paths):
                f = Path(tmp) / oid / path  # scanned under its committed name and suffix
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(raw)
                stem = path.rsplit(".", 1)[0]
                if path.lower().endswith(".pdf") and any(
                    stem + s in every_path for s in data_scan.PDF_SOURCES
                ):  # its committed text source is scanned in its own right
                    (f.parent / Path(path).with_suffix(".md").name).write_text("", "utf-8")
                for hit in secret_scan.scan([f]) + data_scan.scan([f], Path(tmp) / oid):
                    hits.append(f"{oid[:10]} {hit.replace(str(f), path)}")
    return len(found), hits


def main() -> int:
    n, hits = audit()
    for h in hits:
        print(f"history: {h}", file=sys.stderr)
    print(f"history audit: {n} blobs on every ref, {len(hits)} hit(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
