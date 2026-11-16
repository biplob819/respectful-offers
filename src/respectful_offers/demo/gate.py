"""Passkey gate for the deployed demo page (DEM-04, D-48).

The owner hands out passkeys; only their salted PBKDF2-SHA256 hashes are stored, in the
Streamlit app's secrets (never in the repository):

    [demo]
    passkey_hashes = ["pbkdf2_sha256$600000$<salt>$<hash>", ...]

`offers demo-passkey` makes a hash. Several hashes may be listed, one per person or group, so
one can be revoked without changing the others. The deploy bundle always requires a passkey
and fails closed: with no hash configured the page shows that it is locked and nothing else.
A local run (`streamlit run .../app.py`) is open unless a hash is configured, so people
running the open-source project on their own machine need no passkey.

Guessing is slowed three ways: each check costs a PBKDF2 derivation per stored hash, a session
is locked out after `MAX_ATTEMPTS` wrong passkeys, and the whole app stops checking for a
while after `GLOBAL_FAILURES` wrong passkeys within `GLOBAL_WINDOW` seconds from any sessions.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import os
import secrets
import threading
import time
import unicodedata
from collections import deque
from collections.abc import Iterable, Mapping
from typing import Any

ALGO = "pbkdf2_sha256"
ITERATIONS = 600_000
MIN_ITERATIONS = 100_000
MAX_ITERATIONS = 10_000_000  # a mistyped hash must not hang every check
MIN_DISTINCT = 6
MIN_LENGTH = 12
MAX_LENGTH = 256
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 300
GLOBAL_FAILURES = 30
GLOBAL_WINDOW = 60.0
REQUIRE_ENV = "OFFERS_DEMO_REQUIRE_PASSKEY"
HASHES_ENV = "OFFERS_DEMO_PASSKEY_HASHES"


class PasskeyError(ValueError):
    """A passkey or a stored hash that cannot be used."""


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def check_new_passkey(passkey: str) -> None:
    if len(passkey) < MIN_LENGTH:
        raise PasskeyError(f"a passkey needs at least {MIN_LENGTH} characters")
    if len(passkey) > MAX_LENGTH:
        raise PasskeyError(f"a passkey holds at most {MAX_LENGTH} characters")
    if passkey != passkey.strip():
        raise PasskeyError("a passkey cannot start or end with spaces")
    if len(set(passkey)) < MIN_DISTINCT:
        raise PasskeyError(
            f"a passkey needs at least {MIN_DISTINCT} different characters "
            "(or use --generate for a random one)"
        )


def _norm(passkey: str) -> bytes:
    """The same passkey typed on different keyboards (NFC vs NFD accents) hashes the same."""
    return unicodedata.normalize("NFC", passkey).encode("utf-8")


def hash_passkey(passkey: str, *, salt: bytes | None = None, iterations: int = ITERATIONS) -> str:
    check_new_passkey(passkey)
    if not MIN_ITERATIONS <= iterations <= MAX_ITERATIONS:
        raise PasskeyError(f"iterations must be {MIN_ITERATIONS:,} to {MAX_ITERATIONS:,}")
    salt = salt if salt is not None else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", _norm(passkey), salt, iterations)
    return f"{ALGO}${iterations}${_b64(salt)}${_b64(digest)}"


def generate_passkey() -> str:
    """A random passkey: 24 URL-safe characters (144 bits)."""
    return secrets.token_urlsafe(18)


def parse_hash(stored: str) -> tuple[int, bytes, bytes]:
    parts = stored.strip().split("$")
    if len(parts) != 4 or parts[0] != ALGO:
        raise PasskeyError(
            f"a stored passkey hash must look like {ALGO}$<iterations>$<salt>$<hash>"
        )
    if not (parts[1].isascii() and parts[1].isdigit()):
        raise PasskeyError("a stored passkey hash is malformed")
    try:
        iterations = int(parts[1])
        salt, digest = _unb64(parts[2]), _unb64(parts[3])
    except ValueError:
        raise PasskeyError("a stored passkey hash is malformed") from None
    if not MIN_ITERATIONS <= iterations <= MAX_ITERATIONS or len(salt) < 8 or len(digest) != 32:
        raise PasskeyError("a stored passkey hash is too weak or malformed")
    return iterations, salt, digest


def check_passkey(passkey: str, hashes: Iterable[str]) -> bool:
    """True when the passkey matches any stored hash; every hash is checked (constant work)."""
    if not passkey or len(passkey) > MAX_LENGTH:
        return False
    ok = False
    for stored in hashes:
        iterations, salt, digest = parse_hash(stored)
        got = hashlib.pbkdf2_hmac("sha256", _norm(passkey), salt, iterations)
        ok |= hmac.compare_digest(got, digest)
    return ok


def configured_hashes(
    secrets_section: Mapping[str, Any] | None, environ: Mapping[str, str] | None = None
) -> list[str]:
    """Hashes from the `[demo]` secrets section, else from the environment; all validated."""
    environ = os.environ if environ is None else environ
    raw: Any = (secrets_section or {}).get("passkey_hashes")
    if raw is None and environ.get(HASHES_ENV):
        raw = environ[HASHES_ENV].split(",")
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    hashes = [str(h).strip() for h in raw if str(h).strip()]
    for h in hashes:
        parse_hash(h)  # a malformed hash is a configuration error, never silently skipped
    return hashes


def required(environ: Mapping[str, str] | None = None) -> bool:
    """A local run may opt in to requiring a passkey. The deploy bundle never relies on this:
    Streamlit copies top-level secrets into the environment, so a stray secret could unset it;
    the bundle passes `require_passkey=True` to the page instead."""
    environ = os.environ if environ is None else environ
    return environ.get(REQUIRE_ENV, "") == "1"


class Throttle:
    """App-wide brake on guessing: at most `limit` failed checks within `window` seconds.

    A check reserves a slot before the (slow) derivation and gets it back on success, so
    parallel sessions cannot overshoot the limit. The cost: a flood of wrong passkeys also
    makes holders of a right one wait, at most `window` seconds after the flood stops.
    """

    def __init__(self, limit: int | None = None, window: float | None = None) -> None:
        self.limit = GLOBAL_FAILURES if limit is None else limit
        self.window = GLOBAL_WINDOW if window is None else window
        self._failures: deque[float] = deque()
        self._lock = threading.Lock()

    def _trim(self, now: float) -> None:
        while self._failures and now - self._failures[0] > self.window:
            self._failures.popleft()

    def blocked(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._trim(now)
            return len(self._failures) >= self.limit

    def fail(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._trim(now)
            self._failures.append(now)

    def try_acquire(self, now: float | None = None) -> float | None:
        """Reserve a slot for one check (counted as a failure until refunded), or None."""
        now = time.monotonic() if now is None else now
        with self._lock:
            self._trim(now)
            if len(self._failures) >= self.limit:
                return None
            self._failures.append(now)
            return now

    def refund(self, slot: float) -> None:
        with self._lock, contextlib.suppress(ValueError):  # already aged out
            self._failures.remove(slot)
