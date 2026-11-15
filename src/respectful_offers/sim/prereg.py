"""Pre-registration (D-3, SIM-05): freeze the simulator before evaluating on real data.

`offers prereg` validates `configs/simulator.yaml`, then records its sha256 in
`docs/prereg.md`, with the date and the pre-registered success criteria. Every evaluation
calls `prereg_status(yaml_path, prereg_path, exploratory)`: a file whose hash is not
registered is refused, unless the run is `--exploratory`, which is stamped on every output
and can never be published.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from pathlib import Path
from typing import Literal

from respectful_offers.schemas.config import ConfigError, load_simulator_config
from respectful_offers.sim.validate import check

HASH_LINE = re.compile(r"^\| Simulator YAML sha256 \| `?([0-9a-f]{64})`? \|$", re.M)
CRITERIA = (
    "Retained members per 1,000 at risk, discount cost per incremental retained member, "
    "90-day LTV proxy and offer fatigue are reported for every policy under all three "
    "variants with 95% intervals, whatever they show. The respectful policies must have zero "
    'R1, R2, R3, R7 and R8 violations. The headline claim ("the bandit keeps more members '
    'per discount dollar than the rule-following baseline") is made for a variant only if '
    "the Holm-corrected paired interval excludes zero; otherwise the report says it is a tie."
)


class PreregError(ValueError):
    """The simulator is not pre-registered (or its file changed since)."""


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


Scope = Literal["synthetic", "real"]
SCOPE_LINE = re.compile(r"^\| Scope \| (synthetic|real)\b", re.M)
FILE_LINE = re.compile(r"^\| File \| `([^`]+)` \|$", re.M)


def register(
    yaml_path: Path,
    prereg_path: Path,
    *,
    scope: Scope,
    decisions_path: Path | None = None,
    replace_reason: str | None = None,
    today: dt.date | None = None,
) -> str:
    """Validate and freeze the simulator. Replacing a different registration needs a reason,
    which is logged; every registration's hash is appended to the decision log (D-3)."""
    if scope not in ("synthetic", "real"):
        raise ConfigError(f"scope must be 'synthetic' or 'real', got {scope!r}")
    cfg = load_simulator_config(yaml_path)
    problems = check(cfg)
    if problems:
        raise ConfigError(f"{yaml_path}: " + "; ".join(problems))
    digest = sha256(yaml_path)
    old = registered_hash(prereg_path)
    old_scope = registered_scope(prereg_path)
    if old is not None and (old != digest or old_scope != scope) and not replace_reason:
        raise PreregError(
            f"{prereg_path} already registers {old[:12]}… ({old_scope}); "
            "pass a reason to replace it"
        )
    when = (today or dt.date.today()).isoformat()
    stamp = " (allow_unconventional: direction rules bypassed)" if cfg.allow_unconventional else ""
    text = (
        "# Pre-registration\n\n"
        "Written by `offers prereg` (D-3). Evaluations refuse a simulator file whose sha256 is "
        "not the one below, unless run with `--exploratory` (stamped, never published). A "
        "`synthetic` registration never certifies a run on real data (KKBox or your own table).\n\n"
        "| Field | Value |\n| --- | --- |\n"
        f"| Simulator YAML sha256 | `{digest}` |\n"
        f"| File | `{Path(yaml_path).as_posix()}` |\n"
        f"| Registered on | {when} |\n"
        f"| Scope | {scope}{stamp} |\n"
        f"| Variants | {', '.join(sorted(cfg.variants))} |\n"
        f"| Pre-registered success criteria | {CRITERIA} |\n"
    )
    Path(prereg_path).parent.mkdir(parents=True, exist_ok=True)  # a fresh `offers init` project
    Path(prereg_path).write_text(text, encoding="utf-8")
    if decisions_path is not None and Path(decisions_path).is_file():
        why = (
            f"replaces {old[:12]}…: {replace_reason}"
            if old and old != digest
            else "first registration"
        )
        line = (
            f"| PREREG | {when} | Simulator registered for {scope} runs: "
            f"sha256 `{digest}`{stamp} | "
            f"— | {why} |\n"
        )
        with Path(decisions_path).open("a", encoding="utf-8") as fh:
            fh.write(line)
    return digest


def registered_scope(prereg_path: Path) -> str | None:
    p = Path(prereg_path)
    if not p.is_file():
        return None
    m = SCOPE_LINE.search(p.read_text(encoding="utf-8"))
    return m.group(1) if m else None


FILE_LINE = re.compile(r"^\| File \| `([^`]+)` \|$", re.MULTILINE)


def registered_file(prereg_path: Path) -> str | None:
    """The simulator file a registration names, so commands default to it."""
    p = Path(prereg_path)
    if not p.is_file():
        return None
    m = FILE_LINE.search(p.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def registered_hash(prereg_path: Path) -> str | None:
    p = Path(prereg_path)
    if not p.is_file():
        return None
    m = HASH_LINE.search(p.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def prereg_status(
    yaml_path: Path, prereg_path: Path, exploratory: bool, data_source: str = "synthetic"
) -> Literal["preregistered", "exploratory"]:
    """`preregistered` only if the evaluated file's hash is registered with a scope that covers
    the data (a synthetic registration never certifies real data: KKBox, local files or your
    own table)."""
    if not Path(yaml_path).is_file():
        raise PreregError(f"simulator file {yaml_path} does not exist")
    want = registered_hash(prereg_path)
    scope = registered_scope(prereg_path)
    real = data_source != "synthetic"  # KKBox, verified local files and your own table
    if want is not None and sha256(yaml_path) == want and (scope == "real" or not real):
        return "preregistered"
    if exploratory:
        return "exploratory"
    if want is None:
        raise PreregError(
            f"no simulator is pre-registered in {prereg_path}; run `offers prereg` first"
        )
    if sha256(yaml_path) == want:
        raise PreregError(
            f"{prereg_path} registers this simulator for synthetic data only; for real data (KKBox "
            "or your own table), confirm the values and run `offers prereg --scope real`, or run "
            "with --exploratory (never published)"
        )
    raise PreregError(
        f"{yaml_path} changed since it was pre-registered ({prereg_path}); register the change as "
        "a decision and run `offers prereg` again, or run with --exploratory (never published)"
    )
