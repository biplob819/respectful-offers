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


def _commit(root: Path) -> str:
    """The commit a run used, marked `-dirty` when the working tree has uncommitted changes
    (the code that ran is then not exactly that commit)."""
    import subprocess

    from respectful_offers.runtime import git_sha

    sha = git_sha(root)
    if sha == "unknown":
        return sha
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return sha
    return f"{sha}-dirty" if status.strip() else sha


def cmd_evaluate(args: argparse.Namespace) -> int:
    import shutil

    from respectful_offers.churn.stage import ChurnStage
    from respectful_offers.data.verify import DataError, read_manifest
    from respectful_offers.evaluate.stage import EvaluateStage
    from respectful_offers.features.stage import FeaturesStage
    from respectful_offers.runtime import RunContext, import_artifact, run_stage
    from respectful_offers.schemas import load_simulator_config
    from respectful_offers.schemas.config import ConfigError, load_run_config
    from respectful_offers.schemas.contracts import ContractError
    from respectful_offers.schemas.summary import RunSummary
    from respectful_offers.sim.prereg import PreregError, prereg_status, sha256

    root = Path(args.root)
    try:
        cfg = load_run_config(Path(args.config))
        sim_path = Path(args.simulator)
        sim = load_simulator_config(sim_path)
        if args.variant != "all":
            if args.variant not in cfg.variants:
                raise ConfigError(f"variant {args.variant!r} is not in {list(cfg.variants)}")
            cfg = cfg.model_copy(update={"variants": (args.variant,)})
        data_dir = Path(args.data_dir)
        manifest = read_manifest(data_dir / "manifest.json")
        if manifest is None:
            raise DataError(
                "no verified data: run `offers data download` or `offers data synthetic` first"
            )
        status = prereg_status(
            sim_path, Path(args.prereg), args.exploratory, str(manifest.get("source"))
        )
        ctx = RunContext(
            root,
            run_id=args.run_id,
            config_hash=sha256(Path(args.config))[:16],
            seed=cfg.seed,
            git_sha=_commit(root),
            simulator_hash=sha256(sim_path)[:16],
        )
        src = import_artifact(ctx, "manifest", {"manifest.json": data_dir / "manifest.json"})
        feats = run_stage(FeaturesStage(data_dir / "raw"), {"manifest": src}, ctx)
        churn = run_stage(ChurnStage(), {"features": feats}, ctx)
        stage = EvaluateStage(
            cfg,
            sim,
            status,
            args.run_id,
            git_sha=ctx.git_sha,
            data_source=str(manifest.get("source")),
        )
        ref = run_stage(stage, {"features": feats, "churn": churn}, ctx)
        ctx.write_lineage()
        for name in ("summary.json", "frontier.json", "audit.json"):
            shutil.copyfile(ref.path / name, ctx.run_dir / name)
        summary = RunSummary.model_validate_json((ref.path / "summary.json").read_text("utf-8"))
        clean = json.loads((ref.path / "audit.json").read_text("utf-8"))["clean"]
    except (DataError, ContractError, ConfigError, PreregError) as exc:
        _emit({"ok": False, "error": str(exc)}, args.json, f"offers evaluate: {exc}")
        return EXIT_DATA if isinstance(exc, DataError) else EXIT_ERROR
    variants = ", ".join(summary.variants)
    lines = [f"offers evaluate: {summary.prereg_status}, simulated, variants {variants}"]
    for p in summary.policies:
        lines.append(
            f"  {p.variant:12s} {p.policy:24s} retained/1000 {p.retained_per_1000.point:7.1f}  "
            f"LTV {p.ltv_proxy_per_member.point:8.2f}  violations {sum(p.violations.values())}"
        )
    lines.append(f"  respectful policies audit {'clean' if clean else 'FAILED'}; {ctx.run_dir}")
    _emit(
        {
            "ok": clean,
            "run_dir": str(ctx.run_dir),
            "prereg_status": summary.prereg_status,
            "audit_clean": clean,
        },
        args.json,
        "\n".join(lines),
    )
    return EXIT_OK if clean else EXIT_AUDIT


def cmd_report(args: argparse.Namespace) -> int:
    from respectful_offers.report.build import ReportError, build_report
    from respectful_offers.schemas.config import ConfigError

    run_dir = Path(args.root) / "runs" / args.run_id
    try:
        card = Path(args.model_card) if args.model_card else None
        path = build_report(run_dir, Path(args.simulator), Path(args.out), card)
    except (ReportError, ConfigError) as exc:
        _emit({"ok": False, "error": str(exc)}, args.json, f"offers report: {exc}")
        return EXIT_ERROR
    _emit({"ok": True, "report": str(path)}, args.json, f"offers report: wrote {path}")
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
    ev = sub.add_parser("evaluate", help="roll out every policy under every variant; summary.json")
    ev.add_argument("--variant", default="all", help="'all' or one variant name")
    ev.add_argument("--config", default="configs/run.yaml")
    ev.add_argument("--simulator", default="configs/simulator.yaml")
    ev.add_argument("--prereg", default="docs/prereg.md")
    ev.add_argument(
        "--exploratory",
        action="store_true",
        help="allow an unregistered simulator (never published)",
    )
    ev.add_argument("--data-dir", default="data")
    ev.add_argument("--root", default=".", help="project folder holding .offers/ and runs/")
    ev.add_argument("--run-id", default="latest")
    ev.add_argument("--json", action="store_true")
    ev.set_defaults(func=cmd_evaluate)
    rep = sub.add_parser("report", help="build the static HTML report from a run's summary.json")
    rep.add_argument("--root", default=".", help="project folder holding runs/")
    rep.add_argument("--run-id", default="latest")
    rep.add_argument("--simulator", default="configs/simulator.yaml", help="the file the run used")
    rep.add_argument("--model-card", help="model_card.json from the churn stage (optional)")
    rep.add_argument("--out", default="report", help="folder for index.html and charts/")
    rep.add_argument("--json", action="store_true")
    rep.set_defaults(func=cmd_report)
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
        message = f"{type(exc).__name__}: {exc}"
        if getattr(args, "json", False):  # --json promises JSON on stdout, even for a crash
            print(json.dumps({"ok": False, "error": message}, sort_keys=True))
        print(f"offers: {message}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
