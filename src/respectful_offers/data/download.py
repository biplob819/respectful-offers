"""`offers data download` (DAT-01): fetch the KKBox competition files with the user's own
Kaggle credentials, extract them, verify them (DAT-02), then install them into `data/raw/`.

Credentials come from `KAGGLE_USERNAME` + `KAGGLE_KEY`, `KAGGLE_API_TOKEN`,
`~/.kaggle/kaggle.json` or `~/.kaggle/access_token`. They are passed to the Kaggle client and
never printed or logged. Nothing else in the package touches the network (NFR3).

The download is all or nothing: archives are fetched and unpacked in `data/.download/`
(on the same disk as the data, so the final move is a rename), verified there, and only
then swapped into `data/raw/`. A failed or partial download leaves `data/raw/` as it was.
Real KKBox data is never overwritten; synthetic data may be replaced.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Protocol

from respectful_offers.data.kkbox import COMPETITION, REQUIRED, RULES_URL
from respectful_offers.data.verify import DataError, read_manifest, verify


class KaggleClient(Protocol):
    def download_competition(self, competition: str, dest: Path) -> None: ...


def _config_dir(env: dict[str, str], home: Path | None) -> Path:
    return Path(env.get("KAGGLE_CONFIG_DIR") or (home or Path.home()) / ".kaggle")


def credentials_present(env: dict[str, str] | None = None, home: Path | None = None) -> bool:
    env = dict(os.environ) if env is None else env
    if env.get("KAGGLE_API_TOKEN") or (env.get("KAGGLE_USERNAME") and env.get("KAGGLE_KEY")):
        return True
    cfg = _config_dir(env, home)
    if (cfg / "access_token").is_file() and (cfg / "access_token").stat().st_size > 0:
        return True
    try:
        data = json.loads((cfg / "kaggle.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and bool(data.get("username")) and bool(data.get("key"))


class KaggleApiClient:
    """The real client, from the optional extra: pip install 'respectful-offers[data]'."""

    def download_competition(self, competition: str, dest: Path) -> None:
        try:
            with contextlib.redirect_stdout(sys.stderr):
                from kaggle.api.kaggle_api_extended import KaggleApi  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            missing = exc.name or "kaggle"
            raise DataError(
                f"the Kaggle client cannot load (missing module {missing!r}): "
                "pip install 'respectful-offers[data]'"
            ) from None
        except BaseException as exc:  # the client may call exit() while importing
            raise DataError(f"the Kaggle client failed to load ({type(exc).__name__})") from None
        api = KaggleApi()
        try:
            with contextlib.redirect_stdout(sys.stderr):  # keep --json output clean
                api.authenticate()
                api.competition_download_files(competition, path=str(dest), quiet=True)
        except BaseException as exc:  # includes SystemExit: the client calls exit() on bad config
            if isinstance(exc, KeyboardInterrupt):
                raise
            text = str(exc)
            if "403" in text or "Forbidden" in text:
                raise DataError(
                    f"Kaggle refused the download (403). Accept the competition rules at "
                    f"{RULES_URL} with the same account, then retry."
                ) from None
            if "401" in text or "Unauthorized" in text or isinstance(exc, SystemExit):
                raise DataError(
                    "Kaggle rejected or could not read the credentials. Check KAGGLE_USERNAME and "
                    "KAGGLE_KEY or ~/.kaggle/kaggle.json."
                ) from None
            raise DataError(f"Kaggle download failed ({type(exc).__name__})") from None


def _safe_member(into: Path, name: str) -> None:
    if not (into / name).resolve().is_relative_to(into.resolve()):
        raise DataError(f"unsafe path in archive: {name}")


def _extract(archive: Path, into: Path) -> None:
    suffix = archive.suffix.lower()
    if suffix == ".zip":
        try:
            with zipfile.ZipFile(archive) as zf:
                for member in zf.infolist():
                    _safe_member(into, member.filename)
                    if (member.external_attr >> 16) & 0o170000 == 0o120000:
                        raise DataError(f"symbolic link in archive: {member.filename}")
                zf.extractall(into)
        except zipfile.BadZipFile as exc:
            raise DataError(f"{archive.name}: not a valid zip ({exc})") from None
    elif suffix == ".7z":
        try:
            import py7zr  # type: ignore[import-not-found]
        except ImportError as exc:
            raise DataError(
                "7z archives need py7zr: pip install 'respectful-offers[data]'"
            ) from exc
        try:
            with py7zr.SevenZipFile(archive, "r") as z:
                for name in z.getnames():
                    _safe_member(into, name)
                z.extractall(path=into)
        except DataError:
            raise
        except Exception as exc:  # py7zr raises its own types for bad or hostile archives
            raise DataError(
                f"{archive.name}: refused or unreadable 7z archive ({type(exc).__name__})"
            ) from None


def unpack(work: Path, staged: Path) -> None:
    """Extract nested archives until the required CSVs appear; move them into `staged`."""
    for _ in range(3):  # bundle zip → per-file .7z or .zip → csv
        archives = [p for p in work.rglob("*") if p.suffix.lower() in (".zip", ".7z")]
        if not archives:
            break
        for a in archives:
            _extract(a, a.parent)
            a.unlink()
    staged.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED:
        hits = sorted(p for p in work.rglob(name) if p.is_file() and not p.is_symlink())
        if len(hits) > 1:
            raise DataError(f"the download holds {len(hits)} copies of {name}; refusing to guess")
        if hits:
            shutil.move(str(hits[0]), staged / name)


def install(staged: Path, raw: Path) -> None:
    """Swap a verified staging folder into place as `raw` (same disk, so renames)."""
    old = raw.with_name(raw.name + ".old")
    if old.exists():
        shutil.rmtree(old)
    if raw.exists():
        raw.rename(old)
    staged.rename(raw)
    if old.exists():
        shutil.rmtree(old)


def download(data_dir: Path, client: KaggleClient | None = None) -> dict:
    data_dir = Path(data_dir)
    raw, manifest_path = data_dir / "raw", data_dir / "manifest.json"
    existing = read_manifest(manifest_path)
    if existing is not None and existing.get("source") == "kaggle" and raw.is_dir():
        raise DataError("KKBox data is already downloaded; run `offers data verify` to check it")
    if (
        raw.is_dir()
        and any(raw.iterdir())
        and (existing is None or existing.get("source") != "synthetic")
    ):
        raise DataError(f"{raw} already holds files that are not marked synthetic; move them first")
    if client is None:
        if not credentials_present():
            raise DataError(
                "no Kaggle credentials: set KAGGLE_USERNAME and KAGGLE_KEY (or KAGGLE_API_TOKEN), "
                f"or create ~/.kaggle/kaggle.json, and accept the rules at {RULES_URL}"
            )
        client = KaggleApiClient()
    work = data_dir / ".download"
    if work.exists():
        shutil.rmtree(work)
    (work / "fetch").mkdir(parents=True)
    try:
        client.download_competition(COMPETITION, work / "fetch")
        staged = work / "raw"
        unpack(work / "fetch", staged)
        missing = [n for n in REQUIRED if not (staged / n).is_file()]
        if missing:
            raise DataError(f"the download did not contain {missing}")
        staged_manifest = work / "manifest.json"
        manifest = verify(staged, staged_manifest, source="kaggle")
        # manifest first: if the process dies before the swap, raw/ still holds the old files
        # and a "kaggle" manifest whose checksums fail, never real data marked synthetic
        staged_manifest.replace(manifest_path)
        install(staged, raw)
    finally:
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)
    return manifest
