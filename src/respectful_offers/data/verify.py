"""`offers data verify` (DAT-02): check the raw files and write `data/manifest.json`.

For every required file: present, exact header (read directly, BOM tolerated), comma
delimited, no ragged rows, at least one data row, sha256, size, row count, and the min/max
of each date column (YYYYMMDD) with a count of unparseable dates. DuckDB streams the files
with an explicit all-text schema, so the ~30 GB user log is never loaded whole and nothing
is guessed. Error messages never echo row contents (they may hold member ids).

The manifest records where the data came from (`source`: kaggle, synthetic or local), so a
real-data run can never mistake the synthetic fixture for KKBox data. An existing manifest
is compared: a changed checksum is an error.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

import duckdb

from respectful_offers.data.kkbox import COLUMNS, DATE_COLUMNS, REQUIRED

MANIFEST_VERSION = "1.0"
MAX_BAD_DATE_SHARE = 0.001
SOURCE_MARKER = ".source"  # inside raw/: where the files came from, kept if the manifest goes
Source = Literal["kaggle", "synthetic", "local"]


class DataError(RuntimeError):
    """Raw data is missing, malformed or changed. The message says which command fixes it."""


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def _sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def _header(path: Path) -> tuple[str, ...]:
    with path.open("rb") as fh:
        first = fh.readline(1 << 16)
    text = first.decode("utf-8-sig", errors="replace").rstrip("\r\n")
    return tuple(c.strip().strip('"') for c in text.split(","))


def inspect_file(path: Path, name: str) -> dict[str, Any]:
    header = _header(path)
    if header != COLUMNS[name]:
        raise DataError(
            f"{name}: header {list(header)[:12]} differs from the expected {list(COLUMNS[name])} "
            "(wrong file, delimiter or format)"
        )
    cols = ", ".join(f"'{c}': 'VARCHAR'" for c in COLUMNS[name])
    rel = (
        f"read_csv('{_sql_path(path)}', header=true, delim=',', quote='\"', auto_detect=false, "
        f"columns={{{cols}}})"
    )
    exprs = ["count(*)"]
    for c in DATE_COLUMNS.get(name, ()):
        exprs += [
            f"min(TRY_CAST({c} AS BIGINT))",
            f"max(TRY_CAST({c} AS BIGINT))",
            f"count(*) FILTER (WHERE TRY_STRPTIME({c}, '%Y%m%d') IS NULL)",
        ]
    con = duckdb.connect()
    try:
        row = con.execute(f"SELECT {', '.join(exprs)} FROM {rel}").fetchone()
    except duckdb.Error as exc:
        line = re.search(r"[Ll]ine:?\s*(\d+)", str(exc))
        where = f" near line {line.group(1)}" if line else ""
        raise DataError(
            f"{name}: malformed CSV{where} ({type(exc).__name__}); re-download it"
        ) from None
    finally:
        con.close()
    assert row is not None
    rows = int(row[0])
    if rows == 0:
        raise DataError(f"{name}: has a header but no rows (truncated download?); re-download it")
    ranges, bad = {}, {}
    for i, c in enumerate(DATE_COLUMNS.get(name, ())):
        ranges[c] = [row[1 + 3 * i], row[2 + 3 * i]]
        bad[c] = int(row[3 + 3 * i])
        if bad[c] > MAX_BAD_DATE_SHARE * rows or ranges[c][0] is None:
            raise DataError(
                f"{name}: {bad[c]:,} of {rows:,} values in {c} are not YYYYMMDD dates; "
                "re-download it"
            )
    return {
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "rows": int(row[0]),
        "columns": list(header),
        "date_ranges": ranges,
        "unparseable_dates": bad,
    }


def read_manifest(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        files = data["files"]
        if not all(isinstance(rec["sha256"], str) for rec in files.values()):
            raise TypeError("sha256 must be text")
        return data
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        raise DataError(
            f"{path} is corrupt ({type(exc).__name__}); delete it and run `offers data verify`"
        ) from None


def verify(
    raw_dir: Path, manifest_path: Path | None = None, source: Source | None = None
) -> dict[str, Any]:
    raw_dir = Path(raw_dir)
    path = Path(manifest_path) if manifest_path else raw_dir.parent / "manifest.json"
    old = read_manifest(path)
    missing = [f for f in REQUIRED if not (raw_dir / f).is_file()]
    if missing:
        raise DataError(
            f"missing raw file(s) in {raw_dir}: {missing}. Run `offers data download` "
            "(needs a Kaggle API token and the competition rules accepted)."
        )
    files = {name: inspect_file(raw_dir / name, name) for name in REQUIRED}
    if old is not None:
        changed = [
            n
            for n in REQUIRED
            if n in old["files"] and old["files"][n]["sha256"] != files[n]["sha256"]
        ]
        if changed:
            raise DataError(
                f"raw file(s) changed since the manifest was written: {changed}. "
                "Re-run `offers data download` (or `offers data synthetic`) to restore them."
            )
    marker = raw_dir / SOURCE_MARKER
    marked = marker.read_text(encoding="utf-8").strip() if marker.is_file() else None
    resolved = source or (old or {}).get("source") or marked or "local"
    if resolved != marked:
        marker.write_text(resolved + "\n", encoding="utf-8")
    manifest = {"manifest_version": MANIFEST_VERSION, "source": resolved, "files": files}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return manifest
