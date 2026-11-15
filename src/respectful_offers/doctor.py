"""`offers doctor`: is this machine and project ready to run? (CLI-02, NFR4)

Read-only and offline. It never prints a credential, only whether one is present.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from pathlib import Path

from respectful_offers import __version__


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True  # a failed optional check is a note, not a problem


def run_checks(
    root: Path, data_dir: Path, simulator: Path, prereg: Path, config: Path
) -> list[Check]:
    from respectful_offers.data.download import credentials_present
    from respectful_offers.data.verify import read_manifest
    from respectful_offers.schemas import load_simulator_config
    from respectful_offers.schemas.config import load_run_config
    from respectful_offers.sim.prereg import registered_hash, registered_scope, sha256

    checks = [
        Check(
            "python",
            sys.version_info >= (3, 11),
            f"Python {platform.python_version()} (3.11 or later)",
        ),
        Check("package", True, f"respectful-offers {__version__}"),
    ]
    for label, path, loader in (
        ("run config", config, load_run_config),
        ("simulator", simulator, load_simulator_config),
    ):
        try:
            loader(path)
            checks.append(Check(label, True, f"{path} is valid"))
        except Exception as exc:  # report, never crash: this is a diagnostic
            first = str(exc).splitlines()[0][:200]  # never echo file contents (could hold a secret)
            checks.append(Check(label, False, f"{path}: {first}"))
    if simulator.is_file() and prereg.is_file():
        want, scope = registered_hash(prereg), registered_scope(prereg)
        same = want is not None and sha256(simulator) == want
        detail = f"{simulator} is pre-registered (scope: {scope})"
        if same and scope == "synthetic":
            detail += "; real data (KKBox or your own table) needs `offers prereg --scope real`"
        if not same:
            detail = f"{simulator} is not the registered file: use --exploratory or `offers prereg`"
        checks.append(Check("pre-registration", same, detail, required=False))
    else:
        checks.append(
            Check("pre-registration", False, f"no {prereg}; run `offers prereg`", required=False)
        )
    try:
        manifest = read_manifest(data_dir / "manifest.json")
    except Exception as exc:
        manifest = None
        checks.append(
            Check(
                "data",
                False,
                f"{data_dir}/manifest.json is unreadable: {str(exc).splitlines()[0][:200]}",
            )
        )
    if manifest is None and not any(c.name == "data" for c in checks):
        checks.append(
            Check(
                "data",
                False,
                f"no verified data in {data_dir}: run `offers data download` or "
                "`offers data synthetic`, or use --from-table",
                required=False,
            )
        )
    elif manifest is not None:
        checks.append(
            Check(
                "data",
                True,
                f"{data_dir}: {manifest.get('source')} data, "
                f"{len(manifest.get('files', {}))} files verified",
            )
        )
    checks.append(
        Check(
            "kaggle credentials",
            credentials_present(),
            "present (never shown)"
            if credentials_present()
            else "absent: needed only for `offers data download`",
            required=False,
        )
    )
    store = root / ".offers"
    checks.append(
        Check("cache", True, f"{store} ({'exists' if store.is_dir() else 'created on first run'})")
    )
    return checks
