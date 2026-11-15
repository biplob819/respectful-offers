"""The `offers` command line. Each node adds its commands; B2.2 completes the contract (§4).

Exit codes: 0 ok, 1 audit failed, 2 configuration or runtime error, 3 raw data missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from respectful_offers import __version__

EXIT_OK, EXIT_AUDIT, EXIT_ERROR, EXIT_DATA = 0, 1, 2, 3


def _emit(payload: dict, as_json: bool, text: str) -> None:
    print(json.dumps(payload, sort_keys=True) if as_json else text)


def cmd_data(args: argparse.Namespace) -> int:
    from respectful_offers.data.download import download
    from respectful_offers.data.synthetic import SyntheticSpec, write_synthetic
    from respectful_offers.data.verify import DataError, verify

    data_dir = Path(args.data_dir)
    try:
        if args.action == "download":
            manifest = download(data_dir)
        elif args.action == "verify":
            manifest = verify(data_dir / "raw", data_dir / "manifest.json")
        else:
            spec = SyntheticSpec(n_members=args.members, seed=args.seed)
            manifest = write_synthetic(data_dir, spec)
    except DataError as exc:
        _emit({"ok": False, "error": str(exc)}, args.json, f"offers data {args.action}: {exc}")
        return EXIT_DATA
    files = manifest["files"]
    summary = ", ".join(f"{n} {f['rows']:,} rows" for n, f in sorted(files.items()))
    _emit({"ok": True, **manifest}, args.json, f"offers data {args.action}: OK ({summary})")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="offers", description=__doc__)
    parser.add_argument("--version", action="version", version=f"offers {__version__}")
    sub = parser.add_subparsers(dest="command")
    data = sub.add_parser("data", help="download, verify or synthesise the KKBox files")
    data.add_argument("action", choices=["download", "verify", "synthetic"])
    data.add_argument("--data-dir", default="data", help="folder holding raw/ and manifest.json")
    data.add_argument("--members", type=int, default=5_000, help="synthetic only")
    data.add_argument("--seed", type=int, default=20261121, help="synthetic only")
    data.add_argument("--json", action="store_true")
    data.set_defaults(func=cmd_data)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_OK
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return EXIT_ERROR
    except Exception as exc:  # a CLI owns its exit codes (EvalKit L-29)
        print(f"offers: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
