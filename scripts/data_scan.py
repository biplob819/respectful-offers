#!/usr/bin/env python3
"""Fail if KKBox raw data or member-level data would reach the public repo (NFR5, D-12).

The repo is public, so the scan is an allow-list (L-9): a file passes only if it is
  - text (UTF-8, or UTF-16 with a BOM) with no KKBox-shaped member id in it, or
  - a binary of an explicitly allowed kind (images, fonts, PDF), and
  - not named like a KKBox raw file, in any compression, and
  - at most 5 MB.
Archives (zip, gz, 7z, ...), spreadsheets and data-file types (parquet, duckdb, sqlite, ...)
are refused outright, because their contents cannot be checked line by line.

A member id is 43 base64 characters followed by "=" (KKBox `msno`). Lines containing the
marker `data-scan: allow` are skipped. Synthetic fixtures use ids such as `S000042`.

Two entry points:
  - `scan(files)`: tracked and untracked (not ignored) repo files; gate 9.
  - `scan_publish(directory)`: every file in a directory about to be published (report site,
    demo cube), ignored or not; gate 9 runs it on `site/` when that folder exists.

Usage:
    python scripts/data_scan.py [paths...]
    python scripts/data_scan.py --publish site/
    python scripts/data_scan.py --self-test
"""

from __future__ import annotations

import argparse
import gzip
import html
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote, unquote

from harness_lib import ROOT
from secret_scan import candidate_files

ALLOW = "data-scan: allow"
MAX_BYTES = 5 * 1024 * 1024
# Not preceded by a base64 letter, digit or "+" ("/" is allowed: ids appear in URL paths), and
# not a subresource-integrity hash ("sha256-<44 chars>").
MEMBER_ID = re.compile(
    r"(?<![A-Za-z0-9+])(?<!sha256-)(?<!sha384-)(?<!sha512-)[A-Za-z0-9+/]{43}=(?![A-Za-z0-9+/=])"
)
RAW_STEM = re.compile(
    r"^(?:members|transactions|user_logs|train|sample_submission)(?:_v\d+)?(?:_zero)?"
    r"(?:\.(?:csv|tsv|txt|json)(?:\.(?:7z|zip|gz|bz2|xz|tar|rar|zst))?"
    r"|\.(?:7z|zip|gz|bz2|xz|tar|rar|zst))$"
    r"|^kkbox[-_ ]churn",
    re.I,
)
REFUSED_SUFFIXES = {
    # archives and compression: contents cannot be scanned line by line
    ".zip", ".gz", ".tgz", ".7z", ".bz2", ".xz", ".tar", ".rar", ".zst",
    # data files that only ever hold rows
    ".parquet", ".duckdb", ".feather", ".pkl", ".pickle", ".arrow", ".avro", ".orc",
    ".sqlite", ".sqlite3", ".db", ".npz", ".npy", ".h5", ".hdf5", ".xlsx", ".xls", ".ods",
}  # fmt: skip
ALLOWED_BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".woff", ".woff2", ".ttf",
}  # fmt: skip
# A PDF cannot be scanned reliably (compressed streams), so one is allowed only next to the text
# source it was built from (same stem, .md or .html), and that source is scanned instead.
PDF_SOURCES = (".md", ".html")
TEXT_ENCODINGS = (("utf-16", (b"\xff\xfe", b"\xfe\xff")), ("utf-8-sig", (b"\xef\xbb\xbf",)))


def _decode(raw: bytes) -> str | None:
    """Text content, or None if the bytes are not text we can read."""
    if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return raw.decode("utf-32", errors="replace")
    for enc, boms in TEXT_ENCODINGS:
        if raw.startswith(boms):
            return raw.decode(enc, errors="replace")
    if b"\x00" in raw:
        return None
    return raw.decode("utf-8", errors="replace")


def _normalise(line: str) -> str:
    """Undo the encodings an id can hide behind: JSON `\\/`, percent-encoding, HTML entities."""
    return html.unescape(unquote(line.replace("\\/", "/")))


def _has_member_id(line: str) -> bool:
    return bool(MEMBER_ID.search(line) or MEMBER_ID.search(_normalise(line)))


def _check_file(f: Path, label: str) -> str | None:
    name = f.name
    if RAW_STEM.match(name):
        return f"{label}: KKBox raw file name"
    suffixes = {s.lower() for s in f.suffixes}
    refused = suffixes & REFUSED_SUFFIXES
    if refused:
        return f"{label}: archive or data-file type {sorted(refused)[0]} is not allowed"
    size = f.stat().st_size
    if size > MAX_BYTES:
        return f"{label}: {size / 1e6:.1f} MB is over the 5 MB limit"
    if f.suffix.lower() == ".pdf":
        if any(f.with_suffix(s).is_file() for s in PDF_SOURCES):
            return None
        return f"{label}: a PDF needs its text source (.md or .html) beside it to be scanned"
    if f.suffix.lower() in ALLOWED_BINARY_SUFFIXES:
        return None
    text = _decode(f.read_bytes())
    if text is None:
        return f"{label}: unrecognised binary file (only images, fonts and PDF are allowed)"
    for lineno, line in enumerate(text.splitlines(), start=1):
        if ALLOW not in line and _has_member_id(line):
            return f"{label}:{lineno}: KKBox-shaped member id"
    return None


def _label(f: Path, root: Path) -> str:
    try:
        return str(f.relative_to(root))
    except ValueError:
        return str(f)


def scan(files: list[Path], root: Path = ROOT) -> list[str]:
    hits = []
    for f in files:
        if f.is_file():
            hit = _check_file(f, _label(f, root))
            if hit:
                hits.append(hit)
    return hits


def scan_publish(directory: Path) -> list[str]:
    """Every file under a directory about to be published, including ignored ones."""
    directory = Path(directory)
    if not directory.is_dir():
        return [f"{directory}: publish directory does not exist"]
    return scan(sorted(p for p in directory.rglob("*") if p.is_file()), directory)


def self_test() -> int:
    fake_id = "Aa0+" * 10 + "xy/="  # 43 base64 chars then "="
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        cases: list[tuple[str, Path, str | None]] = []

        def add(name: str, rel: str, content: bytes, expect: str | None) -> None:
            p = t / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
            cases.append((name, p, expect))

        add("raw file name", "data/user_logs_v2.csv", b"x\n", "raw file name")
        add("compressed raw name", "members_v3.csv.7z", b"x", "raw file name")
        add("zero-suffixed raw name", "sample_submission_zero.csv", b"x\n", "raw file name")
        add("Kaggle bundle", "kkbox-churn-prediction-challenge.zip", b"x", "raw file name")
        add("parquet file", "out/features.parquet", b"PAR1", "data-file type")
        add("gzip of rows", "rows.csv.gz", gzip.compress(f"msno\n{fake_id}\n".encode()), ".gz")
        add("sqlite file", "scores.db", b"SQLite format 3\x00", "data-file type")
        add("member id in a csv", "rows.csv", f"msno\n{fake_id}\n".encode(), "member id")
        add("member id in a url", "p.html", f'<a href="/m/{fake_id}">'.encode(), "member id")
        add("utf-16 csv", "u16.csv", f"msno\n{fake_id}\n".encode("utf-16"), "member id")
        add("unknown binary", "blob.bin", b"\x00\x01\x02", "unrecognised binary")
        add("oversized file", "big.txt", b"a" * (MAX_BYTES + 1), "5 MB")
        add("synthetic ids pass", "fixture.csv", b"msno\nS000042\n", None)
        add("allow marker", "doc.md", f"id {fake_id} <!-- {ALLOW} -->\n".encode(), None)
        add("sha256 hex passes", "lock.txt", ("sha256:" + "ab" * 32 + "\n").encode(), None)
        add("SRI hash passes", "s.html", ('integrity="sha256-' + "Q" * 43 + '="').encode(), None)
        add("png passes", "chart.png", b"\x89PNG\r\n\x1a\n\x00\x00", None)
        pandas_json = ('{"msno":"' + fake_id.replace("/", "\\/") + '","p":0.3}').encode()
        add("pandas JSON escapes slashes", "cube.json", pandas_json, "member id")
        add("percent-encoded id", "u.txt", quote(fake_id, safe="").encode(), "member id")
        add("html entity id", "e.html", fake_id.replace("/", "&#x2F;").encode(), "member id")
        add("utf-32 csv", "u32.csv", f"msno\n{fake_id}\n".encode("utf-32"), "member id")
        add("pdf without source", "report.pdf", b"%PDF-1.7 rows", "text source")
        add("pdf with its source", "prfaq/prfaq.pdf", b"%PDF-1.7", None)
        add("pdf source scanned", "prfaq/prfaq.md", b"# PR/FAQ\n", None)
        add("train.py is code, not data", "train.py", b"print(1)\n", None)
        for name, path, expect in cases:
            hits = scan([path], t)
            ok = (not hits) if expect is None else (len(hits) == 1 and expect in hits[0])
            failures += 0 if ok else 1
            print(f"  [{'ok' if ok else 'WRONG'}] {name}: {hits[0] if hits else 'clean'}")
        site = t / "site"
        (site / "assets").mkdir(parents=True)
        (site / "assets" / "cube.json").write_text(f'["{fake_id}"]', encoding="utf-8")
        hits = scan_publish(site)
        ok = len(hits) == 1 and "assets/cube.json" in hits[0] and "member id" in hits[0]
        failures += 0 if ok else 1
        print(f"  [{'ok' if ok else 'WRONG'}] publish scan finds a member id in a site file")
    print("self-test", "PASSED" if failures == 0 else f"FAILED ({failures})")
    return 0 if failures == 0 else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("paths", nargs="*", type=Path)
    ap.add_argument("--publish", type=Path, metavar="DIR", help="scan a directory to be published")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    hits = scan_publish(args.publish) if args.publish else scan(args.paths or candidate_files(ROOT))
    for h in hits:
        print(h)
    print("data scan:", "FAIL" if hits else "clean")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
