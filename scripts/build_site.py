#!/usr/bin/env python3
"""Assemble the GitHub Pages site (REL-02, OWNER D-15) and refuse to publish anything the
publish scan rejects.

    python scripts/build_site.py _site

The site is the published results report at the root (`results/kkbox/report/`), plus any
extra pages under `docs/site/` (the PR/FAQ, the case study). Only these folders are copied:
nothing from data/, .offers/ or runs/ can reach it.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (ROOT / "results" / "kkbox" / "report", ROOT / "docs" / "site")
ROW_SUFFIXES = {".csv", ".tsv", ".jsonl", ".ndjson"}


def build(out: Path) -> list[str]:
    import data_scan

    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for src in SOURCES:
        if src.is_dir():
            shutil.copytree(src, out, dirs_exist_ok=True)
    (out / ".nojekyll").write_text("", encoding="utf-8")
    if not (out / "index.html").is_file():
        return [f"{out}: no index.html (the results report is missing)"]
    rows = [  # a published page never needs a table of rows
        f"{p.relative_to(out).as_posix()}: row-data file type"
        for p in sorted(out.rglob("*"))
        if p.suffix.lower() in ROW_SUFFIXES
    ]
    return rows + data_scan.scan_publish(out)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    out = Path(args[0] if args else "_site")
    problems = build(out)
    for p in problems:
        print(f"publish scan: {p}", file=sys.stderr)
    if problems:
        return 1
    print(f"site: {sum(1 for p in out.rglob('*') if p.is_file())} files in {out}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
