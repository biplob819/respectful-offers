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


def cmd_features(args: argparse.Namespace) -> int:
    from respectful_offers.data.verify import DataError, read_manifest
    from respectful_offers.features.stage import FeaturesStage, load_features_table
    from respectful_offers.runtime import RunContext, git_sha, import_artifact, run_stage
    from respectful_offers.schemas.contracts import ContractError

    try:
        if args.from_table:
            df = load_features_table(Path(args.from_table))
            counts = df.groupby("cohort").size().to_dict()
            _emit(
                {"ok": True, "source": "table", "members": counts},
                args.json,
                f"offers features: OK (your table: {counts})",
            )
            return EXIT_OK
        data_dir = Path(args.data_dir)
        manifest = read_manifest(data_dir / "manifest.json")
        if manifest is None:
            raise DataError(
                "no verified data: run `offers data download` or `offers data synthetic` first"
            )
        ctx = RunContext(
            Path(args.root),
            run_id=args.run_id,
            config_hash="features",
            seed=0,
            git_sha=git_sha(Path(args.root)),
        )
        src = import_artifact(ctx, "manifest", {"manifest.json": data_dir / "manifest.json"})
        ref = run_stage(FeaturesStage(data_dir / "raw"), {"manifest": src}, ctx)
        ctx.write_lineage()
        stats = json.loads((ref.path / "stats.json").read_text(encoding="utf-8"))
    except (DataError, ContractError) as exc:
        _emit({"ok": False, "error": str(exc)}, args.json, f"offers features: {exc}")
        return EXIT_DATA if isinstance(exc, DataError) else EXIT_ERROR
    summary = ", ".join(
        f"{c}: {s['members']:,} members, churn {s['churn_rate']:.1%}" for c, s in stats.items()
    )
    _emit(
        {"ok": True, "source": manifest.get("source"), "artifact": ref.key, "stats": stats},
        args.json,
        f"offers features: OK ({summary}; data source: {manifest.get('source')})",
    )
    return EXIT_OK


def cmd_prereg(args: argparse.Namespace) -> int:
    from respectful_offers.schemas.config import ConfigError
    from respectful_offers.sim.prereg import PreregError, register

    try:
        digest = register(
            Path(args.simulator),
            Path(args.out),
            scope=args.scope,
            decisions_path=Path(args.decisions),
            replace_reason=args.replace,
        )
    except (ConfigError, PreregError) as exc:
        _emit({"ok": False, "error": str(exc)}, args.json, f"offers prereg: {exc}")
        return EXIT_ERROR
    _emit(
        {"ok": True, "sha256": digest, "file": args.simulator},
        args.json,
        f"offers prereg: registered {args.simulator} (sha256 {digest[:12]}…) in {args.out}",
    )
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
    feats = sub.add_parser("features", help="build member features as of each cohort's label month")
    feats.add_argument("--data-dir", default="data")
    feats.add_argument(
        "--from-table", help="your own features table (.csv or .parquet) instead of KKBox"
    )
    feats.add_argument("--root", default=".", help="project folder holding .offers/ and runs/")
    feats.add_argument("--run-id", default="features")
    feats.add_argument("--json", action="store_true")
    feats.set_defaults(func=cmd_features)
    pre = sub.add_parser("prereg", help="validate the simulator and freeze it by its sha256 (D-3)")
    pre.add_argument("--simulator", default="configs/simulator.yaml")
    pre.add_argument("--out", default="docs/prereg.md")
    pre.add_argument("--scope", choices=["synthetic", "real"], default="synthetic")
    pre.add_argument("--decisions", default="docs/decisions.md", help="decision log to append to")
    pre.add_argument("--replace", metavar="REASON", help="replace a registration, saying why")
    pre.add_argument("--json", action="store_true")
    pre.set_defaults(func=cmd_prereg)
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
