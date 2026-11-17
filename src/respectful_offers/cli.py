"""The `offers` command line. Each node adds its commands; B2.2 completes the contract (§4).

Exit codes: 0 ok, 1 audit failed, 2 configuration or runtime error, 3 raw data missing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from respectful_offers import __version__

EXIT_OK, EXIT_AUDIT, EXIT_ERROR, EXIT_DATA = 0, 1, 2, 3


CANDIDATES = {
    # option: (files tried in order, bundled template used when none exists)
    "config": (("configs/run.yaml", "offers-run.yaml"), "run.yaml"),
    "simulator": (("configs/simulator.yaml", "simulator.yaml"), "simulator.yaml"),
}


def _resolve_defaults(args: argparse.Namespace) -> None:
    """An explicit path is used as given. Otherwise the repo layout (configs/), then the files
    `offers init` writes, then the templates bundled with the package, so `offers doctor` and
    friends work in any folder (OSS-06)."""
    from importlib import resources

    if hasattr(args, "prereg") and args.prereg is None:
        args.prereg = "docs/prereg.md"
    registered = None
    if getattr(args, "command", None) not in ("prereg", "doctor") and hasattr(args, "prereg"):
        from respectful_offers.sim.prereg import registered_file

        registered = registered_file(Path(args.prereg))
    for option, (tried, template) in CANDIDATES.items():
        if not hasattr(args, option) or getattr(args, option) is not None:
            continue
        if option == "simulator" and registered is not None and Path(registered).is_file():
            setattr(args, option, registered)  # the file this project registered
            continue
        found = next((Path(c) for c in tried if Path(c).is_file()), None)
        if found is None:
            found = Path(str(resources.files("respectful_offers.templates").joinpath(template)))
        setattr(args, option, str(found))
    if hasattr(args, "prereg") and args.prereg is None:
        args.prereg = "docs/prereg.md"


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
    from respectful_offers.features.stage import FeaturesStage
    from respectful_offers.runtime import RunContext, git_sha, import_artifact, run_stage
    from respectful_offers.schemas.contracts import ContractError

    try:
        if args.from_table:
            from respectful_offers.features.table import load_audit_table, load_user_table

            table = Path(args.from_table)
            _check_table_path(table)
            df = load_user_table(table)  # the checks every command on the table makes
            if args.audit_table:
                audit = Path(args.audit_table)
                if not audit.is_file():
                    raise DataError(f"{audit}: no such file")
                load_audit_table(audit, set(df["msno"]))
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
        sim_path = Path(args.simulator).resolve()
        if (
            sim_path.parent.name == "templates"
            and sim_path.parent.parent.name == "respectful_offers"
        ):
            raise ConfigError(
                "no simulator file here: run `offers init` for one to edit, or pass --simulator"
            )
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


def _check_table_path(path: Path) -> None:
    from respectful_offers.data.verify import DataError
    from respectful_offers.schemas.contracts import ContractError

    if not path.is_file():
        raise DataError(f"{path}: no such file")
    if path.suffix.lower() not in (".csv", ".parquet"):
        raise ContractError(f"{path}: use a .csv or .parquet file")


def _check_raw_files(data_dir: Path, manifest: dict) -> None:
    """A cached features artifact is keyed on the manifest, so check the raw files are still
    there (and the size each was verified at) before reusing it."""
    from respectful_offers.data.verify import DataError

    for name, rec in manifest.get("files", {}).items():
        f = data_dir / "raw" / name
        if not f.is_file() or f.stat().st_size != rec.get("bytes"):
            raise DataError(
                f"{f} is missing or changed since it was verified: run `offers data verify`"
            )


class _Pipeline:
    """Features and churn artifacts for a run, from KKBox data or from your own table."""

    def __init__(self, args: argparse.Namespace, *, need_simulator: bool = True) -> None:
        from respectful_offers.churn.stage import ChurnStage
        from respectful_offers.data.verify import DataError, read_manifest
        from respectful_offers.features.stage import FeaturesStage
        from respectful_offers.features.table import TableFeaturesStage
        from respectful_offers.runtime import RunContext, import_artifact, run_stage
        from respectful_offers.schemas import load_simulator_config
        from respectful_offers.schemas.config import ConfigError, load_run_config
        from respectful_offers.sim.prereg import sha256

        self.root = Path(args.root)
        self.config = Path(args.config)
        self.cfg = load_run_config(self.config)
        self.sim_path = Path(args.simulator)
        self.sim = load_simulator_config(self.sim_path) if need_simulator else None
        table = getattr(args, "from_table", None)
        data_dir = Path(getattr(args, "data_dir", "data"))
        audit_table = getattr(args, "audit_table", None)
        if audit_table and not table:
            raise ConfigError("--audit-table goes with --from-table (your own features table)")
        if table:
            _check_table_path(Path(table))
            self.source = "your_table"
        else:
            manifest = read_manifest(data_dir / "manifest.json")
            if manifest is None:
                raise DataError(
                    "no verified data: run `offers data download` or `offers data synthetic`, "
                    "or pass --from-table with your own features table"
                )
            self.source = str(manifest.get("source"))
            _check_raw_files(data_dir, manifest)
        self.ctx = RunContext(
            self.root,
            run_id=args.run_id,
            config_hash=sha256(self.config)[:16],
            seed=self.cfg.seed,
            git_sha=_commit(self.root),
            simulator_hash=sha256(self.sim_path)[:16] if self.sim_path.is_file() else None,
        )
        if table:
            path = Path(table)
            files = {
                ("features.parquet" if path.suffix.lower() == ".parquet" else "features.csv"): path
            }
            audit = getattr(args, "audit_table", None)
            if audit:
                files["audit.csv"] = Path(audit)
            for f in files.values():
                if not f.is_file():
                    raise DataError(f"{f}: no such file")
            src = import_artifact(self.ctx, "table", files)
            shown = (str(path), str(audit) if audit else "audit table")
            self.features = run_stage(TableFeaturesStage(shown), {"table": src}, self.ctx)
        else:
            src = import_artifact(
                self.ctx, "manifest", {"manifest.json": data_dir / "manifest.json"}
            )
            self.features = run_stage(FeaturesStage(data_dir / "raw"), {"manifest": src}, self.ctx)
        self._churn_stage = ChurnStage()
        self._run_stage = run_stage
        self._churn = None

    @property
    def churn(self):
        if self._churn is None:
            self._churn = self._run_stage(self._churn_stage, {"features": self.features}, self.ctx)
        return self._churn


def _user_errors():
    from respectful_offers.data.verify import DataError
    from respectful_offers.report.build import ReportError
    from respectful_offers.schemas.config import ConfigError
    from respectful_offers.schemas.contracts import ContractError
    from respectful_offers.sim.prereg import PreregError

    return (DataError, ContractError, ConfigError, PreregError, ReportError)


def _fail(args: argparse.Namespace, command: str, exc: Exception) -> int:
    from respectful_offers.data.verify import DataError

    _emit({"ok": False, "error": str(exc)}, args.json, f"offers {command}: {exc}")
    return EXIT_DATA if isinstance(exc, DataError) else EXIT_ERROR


def cmd_churn(args: argparse.Namespace) -> int:
    from respectful_offers.schemas.summary import ChurnReport

    try:
        pipe = _Pipeline(args, need_simulator=False)
        ref = pipe.churn
        pipe.ctx.write_lineage()
        rep = ChurnReport.model_validate_json((ref.path / "report.json").read_text("utf-8"))
    except _user_errors() as exc:
        return _fail(args, "churn", exc)
    text = (
        f"offers churn: AUC {rep.auc.point:.3f} [{rep.auc.lo:.3f}, {rep.auc.hi:.3f}], Brier "
        f"{rep.brier.point:.4f}, ECE {rep.ece:.4f}, two-feature baseline AUC "
        f"{rep.baseline_auc.point:.3f} (data: {pipe.source}; labels are real, not simulated)"
    )
    _emit(
        {
            "ok": True,
            "artifact": ref.key,
            "report": json.loads(rep.model_dump_json()),
            "data_source": pipe.source,
        },
        args.json,
        text,
    )
    return EXIT_OK


def cmd_simulate(args: argparse.Namespace) -> int:
    """Train the bandit for one variant on the training cohort and save its posterior."""
    import pandas as pd

    from respectful_offers.evaluate.pipeline import split
    from respectful_offers.policy.bandit import train_bandit
    from respectful_offers.policy.cohort import build_cohort
    from respectful_offers.schemas.config import ConfigError
    from respectful_offers.sim.prereg import prereg_status

    try:
        pipe = _Pipeline(args)
        cfg, sim = pipe.cfg, pipe.sim
        assert sim is not None
        if args.variant not in cfg.variants:
            raise ConfigError(f"variant {args.variant!r} is not in {list(cfg.variants)}")
        status = prereg_status(pipe.sim_path, Path(args.prereg), args.exploratory, pipe.source)
        scores = pd.read_parquet(pipe.churn.path / "scores_mar.parquet")[["msno", "churn_risk"]]
        features = pd.read_parquet(pipe.features.path / "features_mar.parquet")
        parts = split(build_cohort(scores, features, sim, args.variant, cfg.seed), cfg)
        bandit = train_bandit(
            parts["train"],
            sim,
            args.variant,
            decision_features=cfg.decision_features,
            risk_threshold=cfg.risk_threshold,
            budget_per_1000=cfg.budget_per_1000_per_period,
            periods=cfg.horizon_periods,
            epochs=3,
            prior_precision=cfg.ts_prior_precision,
            noise_variance=cfg.ts_noise_variance,
            integration_nodes=cfg.ts_integration_nodes,
            support_floor=cfg.ts_support_floor,
            seed=cfg.seed,
        )
        pipe.ctx.write_lineage()
        out = pipe.ctx.run_dir / f"bandit-{args.variant}.json"
        record = json.loads(bandit.posterior.to_json())
        record.update(prereg_status=status, simulated=True, data_source=pipe.source)
        out.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
    except _user_errors() as exc:
        return _fail(args, "simulate", exc)
    curve = bandit.posterior.learning_curve
    text = (
        f"offers simulate: trained the bandit on {len(parts['train']):,} members under the "
        f"{args.variant} variant (simulated); greedy value {curve[0]['value']:.2f} → "
        f"{curve[-1]['value']:.2f} NTD per member; posterior in {out}"
    )
    payload = {"ok": True, "posterior": str(out), "learning_curve": curve, "prereg_status": status}
    _emit(payload, args.json, text)
    return EXIT_OK


def _evaluate(args: argparse.Namespace) -> tuple[Any, bool, Path]:
    import shutil

    from respectful_offers.evaluate.stage import EvaluateStage
    from respectful_offers.schemas.config import ConfigError
    from respectful_offers.schemas.summary import RunSummary
    from respectful_offers.sim.prereg import prereg_status

    pipe = _Pipeline(args)
    cfg, sim = pipe.cfg, pipe.sim
    assert sim is not None
    if args.variant != "all":
        if args.variant not in cfg.variants:
            raise ConfigError(f"variant {args.variant!r} is not in {list(cfg.variants)}")
        cfg = cfg.model_copy(update={"variants": (args.variant,)})
    status = prereg_status(pipe.sim_path, Path(args.prereg), args.exploratory, pipe.source)
    stage = EvaluateStage(
        cfg, sim, status, args.run_id, git_sha=pipe.ctx.git_sha, data_source=pipe.source
    )
    ref = pipe._run_stage(stage, {"features": pipe.features, "churn": pipe.churn}, pipe.ctx)
    pipe.ctx.write_lineage()
    for name in ("summary.json", "frontier.json", "audit.json"):
        shutil.copyfile(ref.path / name, pipe.ctx.run_dir / name)
    summary = RunSummary.model_validate_json((ref.path / "summary.json").read_text("utf-8"))
    clean = json.loads((ref.path / "audit.json").read_text("utf-8"))["clean"]
    return summary, bool(clean), pipe.ctx.run_dir


def cmd_evaluate(args: argparse.Namespace) -> int:
    try:
        summary, clean, run_dir = _evaluate(args)
    except _user_errors() as exc:
        return _fail(args, "evaluate", exc)
    variants = ", ".join(summary.variants)
    lines = [f"offers evaluate: {summary.prereg_status}, simulated, variants {variants}"]
    for p in summary.policies:
        lines.append(
            f"  {p.variant:12s} {p.policy:24s} retained/1000 {p.retained_per_1000.point:7.1f}  "
            f"LTV {p.ltv_proxy_per_member.point:8.2f}  violations {sum(p.violations.values())}"
        )
    lines.append(f"  respectful policies audit {'clean' if clean else 'FAILED'}; {run_dir}")
    payload = {
        "ok": clean,
        "run_dir": str(run_dir),
        "prereg_status": summary.prereg_status,
        "audit_clean": clean,
        "data_source": summary.data_source,
    }
    _emit(payload, args.json, "\n".join(lines))
    return EXIT_OK if clean else EXIT_AUDIT


def cmd_run(args: argparse.Namespace) -> int:
    """Every stage with one command: features, churn, evaluate, report (CLI-05)."""
    from respectful_offers.report.build import build_report

    if not args.all:
        _emit(
            {"ok": False, "error": "pass --all"},
            args.json,
            "offers run: pass --all to run every stage",
        )
        return EXIT_ERROR
    try:
        summary, clean, run_dir = _evaluate(args)
        path = build_report(run_dir, Path(args.simulator), Path(args.out))
    except _user_errors() as exc:
        return _fail(args, "run", exc)
    text = (
        f"offers run: {summary.prereg_status}, simulated, data {summary.data_source}; audit "
        f"{'clean' if clean else 'FAILED'}; report {path}"
    )
    _emit(
        {"ok": clean, "run_dir": str(run_dir), "report": str(path), "audit_clean": clean},
        args.json,
        text,
    )
    return EXIT_OK if clean else EXIT_AUDIT


def cmd_demo_cube(args: argparse.Namespace) -> int:
    """The demo's aggregates-only cohort cube from a finished run (D3.1, D-12)."""
    import pandas as pd

    from respectful_offers.demo.cube import dumps, make_cube
    from respectful_offers.schemas.config import ConfigError

    try:
        pipe = _Pipeline(args)
        assert pipe.sim is not None
        scores = pd.read_parquet(pipe.churn.path / "scores_mar.parquet")[["msno", "churn_risk"]]
        features = pd.read_parquet(pipe.features.path / "features_mar.parquet")
        run_dir = pipe.root / "runs" / args.run_id
        if not (run_dir / "summary.json").is_file():
            from respectful_offers.data.verify import DataError

            raise DataError(f"no finished run in {run_dir}: run `offers evaluate` first")
        audit = run_dir / "audit.json"
        if audit.is_file() and json.loads(audit.read_text("utf-8")).get("clean") is not True:
            _emit(
                {"ok": False, "error": "the run's audit failed: no demo is built from it"},
                args.json,
                "offers demo-cube: the run's audit failed: no demo is built from it",
            )
            return EXIT_AUDIT
        out = Path(args.out)
        if "runs" in out.resolve().parts or out.is_symlink() or out.suffix != ".json":
            raise ConfigError("--out must be a .json file outside any runs/ folder")
        if out.exists():
            try:
                previous = json.loads(out.read_text("utf-8"))
            except (OSError, ValueError):
                previous = None
            if not (
                isinstance(previous, dict) and "cube_version" in previous and "cells" in previous
            ):
                raise ConfigError(f"{out} exists and is not a demo cube: it is never overwritten")
        cube = make_cube(
            scores,
            features,
            run_dir,
            pipe.sim_path,
            pipe.cfg,
            pipe.sim,
            config_path=pipe.config,
            data_source=pipe.source,
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(dumps(cube), encoding="utf-8", newline="\n")
    except (*_user_errors(), ValueError) as exc:
        return _fail(args, "demo-cube", exc)
    text = (
        f"offers demo-cube: {len(cube['cells'])} cells from {cube['members']:,} members "
        f"(every cell 20 or more; no member rows) in {out}"
    )
    _emit({"ok": True, "cube": str(out), "cells": len(cube["cells"])}, args.json, text)
    return EXIT_OK


BUNDLE_APP = """# Respectful Offers demo page (deploy bundle, DEM-03). All outcomes are simulated.
import os
from pathlib import Path

os.environ.setdefault("OFFERS_DEMO_CUBE", str(Path(__file__).with_name("cube.json")))

from respectful_offers.demo.app import main

main(require_passkey=True)  # deployed: locked until a passkey hash is set, never by a setting
"""


def cmd_demo_passkey(args: argparse.Namespace) -> int:
    """Hash a passkey for the deployed demo's secrets (DEM-04); the passkey is never stored."""
    import getpass

    from respectful_offers.demo import gate

    generated = None
    try:
        if args.generate:
            passkey = generated = gate.generate_passkey()
        elif args.stdin:
            passkey = sys.stdin.readline().rstrip("\r\n")
        else:
            passkey = getpass.getpass("New demo passkey: ")
            if getpass.getpass("Same passkey again: ") != passkey:
                raise gate.PasskeyError("the two passkeys differ")
        stored = gate.hash_passkey(passkey)
    except gate.PasskeyError as exc:
        return _fail(args, "demo-passkey", exc)
    toml = f'[demo]\npasskey_hashes = ["{stored}"]'
    payload: dict = {"ok": True, "hash": stored, "secrets_toml": toml}
    text = (
        "Paste into the Streamlit app's Settings > Secrets (add more hashes to the list to give "
        "different people their own passkey; `--generate` makes a strong random one):"
        f"\n\n{toml}\n"
    )
    if generated is not None:
        payload["passkey"] = generated
        text = f"Passkey (shown once, not stored anywhere): {generated}\n\n" + text
    _emit(payload, args.json, text)
    return EXIT_OK


def cmd_demo_bundle(args: argparse.Namespace) -> int:
    """A folder that deploys the demo page as files: the page, the cube, requirements (DEM-03)."""
    import shutil

    from respectful_offers import __version__
    from respectful_offers.demo.engine import load_cube
    from respectful_offers.schemas.config import ConfigError

    try:
        if args.ref and not re.fullmatch(r"[0-9a-f]{7,40}|v\d+\.\d+\.\d+", args.ref):
            raise ConfigError("--ref is a commit sha (7-40 hex characters) or a tag like v0.1.0")
        cube = Path(args.cube)
        if not cube.is_file():
            raise ConfigError(f"{cube}: no such cube; run `offers demo-cube` first")
        load_cube(cube)  # refuse a tampered or foreign cube before shipping it
        out = Path(args.out)
        ours = {
            "streamlit_app.py",
            "cube.json",
            "requirements.txt",
            ".streamlit",
            ".streamlit/config.toml",
        }
        if out.is_symlink() or (out.exists() and not out.is_dir()):
            raise ConfigError(f"{out} is a symlink or a file: choose a new folder")
        if "runs" in out.resolve().parts:
            raise ConfigError("the bundle never goes into a runs/ folder")
        if out.exists():
            for path in out.rglob("*"):
                rel = path.relative_to(out).as_posix()
                if path.is_symlink():
                    raise ConfigError(f"{out} holds a symlink ({rel}): choose a new folder")
                if rel not in ours:
                    raise ConfigError(
                        f"{out} holds {rel}, which is not part of a bundle: choose a new folder"
                    )
        (out / ".streamlit").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cube, out / "cube.json")
        (out / "streamlit_app.py").write_text(BUNDLE_APP, encoding="utf-8")
        # no usage statistics leave viewers' browsers (DEM-02, privacy)
        (out / ".streamlit" / "config.toml").write_text(
            "[browser]\ngatherUsageStats = false\n", encoding="utf-8"
        )
        (out / "requirements.txt").write_text(
            "# Installable today from the public repository; after v0.1.0 is on PyPI this may be\n"
            f"# replaced by: respectful-offers[demo]=={__version__}\n"
            "respectful-offers[demo] @ git+https://github.com/biplob819/respectful-offers"
            + (f"@{args.ref}" if args.ref else "")
            + "\n",
            encoding="utf-8",
        )
    except (*_user_errors(), ValueError) as exc:
        return _fail(args, "demo-bundle", exc)
    _emit(
        {"ok": True, "bundle": str(out)},
        args.json,
        f"offers demo-bundle: {out} holds streamlit_app.py, cube.json and requirements.txt",
    )
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    from respectful_offers.doctor import run_checks

    checks = run_checks(
        Path(args.root),
        Path(args.data_dir),
        Path(args.simulator),
        Path(args.prereg),
        Path(args.config),
    )
    problems = [c for c in checks if c.required and not c.ok]
    lines = ["offers doctor:"] + [
        f"  {'ok  ' if c.ok else ('FAIL' if c.required else 'note')} {c.name}: {c.detail}"
        for c in checks
    ]
    payload = {"ok": not problems, "checks": [c.__dict__ for c in checks]}
    _emit(payload, args.json, "\n".join(lines))
    return EXIT_ERROR if problems else EXIT_OK


def cmd_init(args: argparse.Namespace) -> int:
    from respectful_offers.scaffold import scaffold

    folder = Path(args.folder)
    if folder.exists() and not folder.is_dir():
        _emit(
            {"ok": False, "error": f"{folder} is a file"},
            args.json,
            f"offers init: {folder} is a file",
        )
        return EXIT_ERROR
    result = scaffold(folder)
    text = f"offers init: wrote {', '.join(result['written']) or 'nothing'} in {folder}"
    if result["kept"]:
        text += f"; kept your existing {', '.join(result['kept'])}"
    _emit({"ok": True, "folder": str(folder), **result}, args.json, text)
    return EXIT_OK


EXAMPLE_MARK = ".offers-example"


def _example_files(out: Path) -> dict[str, str]:
    """Files an earlier `--example` wrote into `out`, with their sha256 (from its mark)."""
    try:
        record = json.loads((out / EXAMPLE_MARK).read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in record["files"].items()}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def _safe_example_target(out: Path) -> None:
    """Refuse anything that could overwrite a user's file: a symlink anywhere, a runs/ folder,
    or any file the example did not write itself (checked by content hash, EvalKit L-30)."""
    import hashlib

    from respectful_offers.report.build import ReportError

    if out.is_symlink() or (out.exists() and not out.is_dir()):
        raise ReportError(f"{out} is a symlink or a file: choose a new folder for --out")
    if "runs" in out.resolve().parts:
        raise ReportError("the example never writes into a runs/ folder")
    if not out.exists():
        return
    ours = _example_files(out)
    for path in sorted(out.rglob("*")):
        rel = path.relative_to(out).as_posix()
        if path.is_symlink():
            raise ReportError(f"{out} holds a symlink ({rel}): choose a new folder for --out")
        if path.is_dir() or rel == EXAMPLE_MARK:
            continue
        if ours.get(rel) != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ReportError(
                f"{out} holds {rel}, which `offers report --example` did not write: choose "
                "another --out"
            )


def _report_example(args: argparse.Namespace) -> int:
    """Render the bundled synthetic run; never into a run folder or over anyone's files."""
    import hashlib
    from importlib import resources

    from respectful_offers.report.build import ReportError, build_report

    out = Path(args.out or "report-example")
    try:
        _safe_example_target(out)
        examples = resources.files("respectful_offers.examples")
        template = resources.files("respectful_offers.templates").joinpath("simulator.yaml")
        with resources.as_file(examples) as ex, resources.as_file(template) as sim:
            path = build_report(Path(ex), Path(sim), out)
        written = {
            p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(out.rglob("*"))
            if p.is_file() and p.name != EXAMPLE_MARK
        }
        mark = {"written_by": "offers report --example", "files": written}
        (out / EXAMPLE_MARK).write_text(
            json.dumps(mark, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
    except ReportError as exc:
        return _fail(args, "report", exc)
    text = f"offers report --example: wrote {path} (synthetic members, simulated outcomes)"
    _emit({"ok": True, "report": str(path), "example": True}, args.json, text)
    return EXIT_OK


def cmd_report(args: argparse.Namespace) -> int:
    if args.example:
        return _report_example(args)
    from respectful_offers.report.build import ReportError, build_report
    from respectful_offers.schemas.config import ConfigError

    args.out = args.out or "report"
    run_dir = Path(args.root) / "runs" / args.run_id
    try:
        card = Path(args.model_card) if args.model_card else None
        path = build_report(run_dir, Path(args.simulator), Path(args.out), card)
    except (ReportError, ConfigError) as exc:
        _emit({"ok": False, "error": str(exc)}, args.json, f"offers report: {exc}")
        return EXIT_ERROR
    _emit({"ok": True, "report": str(path)}, args.json, f"offers report: wrote {path}")
    return EXIT_OK


def cmd_metrics(args: argparse.Namespace) -> int:
    """Write summary.json in EvalKit's metrics-1 format (E4.1, OWNER D-50)."""
    from pydantic import ValidationError

    from respectful_offers.metrics1 import MetricsError, dumps, to_metrics1
    from respectful_offers.schemas.summary import load_summary

    out = Path(args.out)
    try:
        text = dumps(to_metrics1(load_summary(Path(args.summary))))
    except (OSError, ValidationError, MetricsError) as exc:
        return _fail(args, "metrics", exc)
    if args.check:
        if not out.is_file() or out.read_text(encoding="utf-8") != text:
            msg = f"offers metrics: {out} is stale; rerun without --check"
            _emit({"ok": False, "error": msg}, args.json, msg)
            return EXIT_AUDIT
        _emit({"ok": True, "metrics": str(out), "current": True}, args.json, f"{out} is current")
        return EXIT_OK
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    _emit({"ok": True, "metrics": str(out)}, args.json, f"offers metrics: wrote {out} (metrics-1)")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="offers", description=__doc__)
    parser.add_argument("--version", action="version", version=f"offers {__version__}")
    sub = parser.add_subparsers(dest="command", parser_class=_Parser)
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
    feats.add_argument("--audit-table", help="optional msno,age_band,gender table to check too")
    feats.add_argument("--root", default=".", help="project folder holding .offers/ and runs/")
    feats.add_argument("--run-id", default="features")
    feats.add_argument("--json", action="store_true")
    feats.set_defaults(func=cmd_features)
    pre = sub.add_parser("prereg", help="validate the simulator and freeze it by its sha256 (D-3)")
    pre.add_argument(
        "--simulator",
        default=None,
        help="simulator file (default: configs/simulator.yaml, simulator.yaml, or the bundled one)",
    )
    pre.add_argument("--out", default="docs/prereg.md")
    pre.add_argument("--scope", choices=["synthetic", "real"], default="synthetic")
    pre.add_argument("--decisions", default="docs/decisions.md", help="decision log to append to")
    pre.add_argument("--replace", metavar="REASON", help="replace a registration, saying why")
    pre.add_argument("--json", action="store_true")
    pre.set_defaults(func=cmd_prereg)
    ev = sub.add_parser("evaluate", help="roll out every policy under every variant; summary.json")
    ev.add_argument("--variant", default="all", help="'all' or one variant name")
    ev.add_argument("--prereg", default=None)
    ev.add_argument(
        "--exploratory",
        action="store_true",
        help="allow an unregistered simulator (never published)",
    )
    ev.add_argument(
        "--config",
        default=None,
        help="run config (default: configs/run.yaml, offers-run.yaml, or the bundled one)",
    )
    ev.add_argument(
        "--simulator",
        default=None,
        help="simulator file (default: configs/simulator.yaml, simulator.yaml, or the bundled one)",
    )
    ev.add_argument("--data-dir", default="data")
    ev.add_argument(
        "--from-table", help="your own features table (.csv or .parquet) instead of KKBox"
    )
    ev.add_argument(
        "--audit-table", help="optional msno,age_band,gender table for the disparity audit"
    )
    ev.add_argument("--root", default=".", help="project folder holding .offers/ and runs/")
    ev.add_argument("--run-id", default="latest")
    ev.add_argument("--json", action="store_true")
    ev.set_defaults(func=cmd_evaluate)
    rep = sub.add_parser("report", help="build the static HTML report from a run's summary.json")
    rep.add_argument("--root", default=".", help="project folder holding runs/")
    rep.add_argument("--run-id", default="latest")
    rep.add_argument(
        "--simulator",
        default=None,
        help="simulator file (default: configs/simulator.yaml, simulator.yaml, or the bundled one)",
    )
    rep.add_argument("--model-card", help="model_card.json from the churn stage (optional)")
    rep.add_argument(
        "--out",
        default=None,
        help="output folder (default report/, or report-example/ with --example)",
    )
    rep.add_argument("--example", action="store_true", help="render the bundled synthetic run")
    rep.add_argument("--json", action="store_true")
    rep.set_defaults(func=cmd_report)
    ch = sub.add_parser("churn", help="train, calibrate and report the churn model")
    ch.add_argument(
        "--config",
        default=None,
        help="run config (default: configs/run.yaml, offers-run.yaml, or the bundled one)",
    )
    ch.add_argument(
        "--simulator",
        default=None,
        help="simulator file (default: configs/simulator.yaml, simulator.yaml, or the bundled one)",
    )
    ch.add_argument("--data-dir", default="data")
    ch.add_argument(
        "--from-table", help="your own features table (.csv or .parquet) instead of KKBox"
    )
    ch.add_argument(
        "--audit-table", help="optional msno,age_band,gender table for the disparity audit"
    )
    ch.add_argument("--root", default=".", help="project folder holding .offers/ and runs/")
    ch.add_argument("--run-id", default="latest")
    ch.add_argument("--json", action="store_true")
    ch.set_defaults(func=cmd_churn)
    si = sub.add_parser("simulate", help="train the bandit for one variant (simulated)")
    si.add_argument("--variant", default="central")
    si.add_argument("--prereg", default=None)
    si.add_argument("--exploratory", action="store_true", help="allow an unregistered simulator")
    si.add_argument(
        "--config",
        default=None,
        help="run config (default: configs/run.yaml, offers-run.yaml, or the bundled one)",
    )
    si.add_argument(
        "--simulator",
        default=None,
        help="simulator file (default: configs/simulator.yaml, simulator.yaml, or the bundled one)",
    )
    si.add_argument("--data-dir", default="data")
    si.add_argument(
        "--from-table", help="your own features table (.csv or .parquet) instead of KKBox"
    )
    si.add_argument(
        "--audit-table", help="optional msno,age_band,gender table for the disparity audit"
    )
    si.add_argument("--root", default=".", help="project folder holding .offers/ and runs/")
    si.add_argument("--run-id", default="latest")
    si.add_argument("--json", action="store_true")
    si.set_defaults(func=cmd_simulate)
    rn = sub.add_parser("run", help="every stage with one command: features to report")
    rn.add_argument("--all", action="store_true", help="run every stage")
    rn.add_argument("--variant", default="all")
    rn.add_argument("--prereg", default=None)
    rn.add_argument("--exploratory", action="store_true")
    rn.add_argument("--out", default="report", help="folder for the report")
    rn.add_argument(
        "--config",
        default=None,
        help="run config (default: configs/run.yaml, offers-run.yaml, or the bundled one)",
    )
    rn.add_argument(
        "--simulator",
        default=None,
        help="simulator file (default: configs/simulator.yaml, simulator.yaml, or the bundled one)",
    )
    rn.add_argument("--data-dir", default="data")
    rn.add_argument(
        "--from-table", help="your own features table (.csv or .parquet) instead of KKBox"
    )
    rn.add_argument(
        "--audit-table", help="optional msno,age_band,gender table for the disparity audit"
    )
    rn.add_argument("--root", default=".", help="project folder holding .offers/ and runs/")
    rn.add_argument("--run-id", default="latest")
    rn.add_argument("--json", action="store_true")
    rn.set_defaults(func=cmd_run)
    dc = sub.add_parser("demo-cube", help="write the demo's aggregates-only cube from a run")
    dc.add_argument("--out", default="demo/cube.json")
    dc.add_argument("--config", default=None)
    dc.add_argument("--simulator", default=None)
    dc.add_argument("--data-dir", default="data")
    dc.add_argument("--from-table", help="your own features table, as for the run")
    dc.add_argument("--audit-table", help="optional audit table, as for the run")
    dc.add_argument("--root", default=".")
    dc.add_argument("--run-id", default="latest")
    dc.add_argument("--prereg", default=None)
    dc.add_argument("--json", action="store_true")
    dc.set_defaults(func=cmd_demo_cube)
    db = sub.add_parser("demo-bundle", help="a folder that deploys the demo page as files")
    db.add_argument("--cube", default="demo/cube.json")
    db.add_argument("--out", default="demo/bundle")
    db.add_argument(
        "--ref", default=None, help="pin the package to this commit sha or tag (a push reinstalls)"
    )
    db.add_argument("--json", action="store_true")
    db.set_defaults(func=cmd_demo_bundle)
    me = sub.add_parser("metrics", help="write summary.json in EvalKit's metrics-1 format")
    me.add_argument("--summary", default="results/kkbox/summary.json")
    me.add_argument("--out", default="results/kkbox/metrics.json")
    me.add_argument("--check", action="store_true", help="exit 1 if --out is stale")
    me.add_argument("--json", action="store_true")
    me.set_defaults(func=cmd_metrics)
    dp = sub.add_parser("demo-passkey", help="hash a passkey for the deployed demo's secrets")
    how = dp.add_mutually_exclusive_group()
    how.add_argument("--generate", action="store_true", help="make a random passkey")
    how.add_argument("--stdin", action="store_true", help="read the passkey from stdin")
    dp.add_argument("--json", action="store_true")
    dp.set_defaults(func=cmd_demo_passkey)
    dr = sub.add_parser("doctor", help="check this machine and project; prints no secrets")
    dr.add_argument("--root", default=".")
    dr.add_argument("--data-dir", default="data")
    dr.add_argument(
        "--config",
        default=None,
        help="run config (default: configs/run.yaml, offers-run.yaml, or the bundled one)",
    )
    dr.add_argument(
        "--simulator",
        default=None,
        help="simulator file (default: configs/simulator.yaml, simulator.yaml, or the bundled one)",
    )
    dr.add_argument("--prereg", default=None)
    dr.add_argument("--json", action="store_true")
    dr.set_defaults(func=cmd_doctor)
    it = sub.add_parser("init", help="scaffold a project for your own data; never overwrites")
    it.add_argument("folder", nargs="?", default=".")
    it.add_argument("--json", action="store_true")
    it.set_defaults(func=cmd_init)
    return parser


class UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    """Usage errors raise instead of exiting, so `--json` can still answer in JSON."""

    def error(self, message: str):  # type: ignore[override]
        raise UsageError(f"{self.prog}: {message}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parser.parse_args(raw)
    except UsageError as exc:
        if "--json" in raw:
            print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        print(f"{exc}\n(run `offers --help` or `offers <command> --help`)", file=sys.stderr)
        return EXIT_ERROR
    _resolve_defaults(args)
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
