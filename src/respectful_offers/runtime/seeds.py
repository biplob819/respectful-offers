"""Seeds and common random numbers (Tech Spec §2.1, RUN-04).

`stage_seed` gives each stage its own seed from the root seed and the stage name.
`member_uniforms` gives each member, period and stream its own uniforms in [0, 1), computed
from a counter-based hash (splitmix64) of (root seed, member hash, period, stream, draw). A
member's draws therefore never depend on cohort order, sampling or which policy runs, which
is what makes common random numbers hold across policies.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

import numpy as np

_MASK = (1 << 64) - 1
_GOLDEN = np.uint64(0x9E3779B97F4A7C15)
_M1 = np.uint64(0xBF58476D1CE4E5B9)
_M2 = np.uint64(0x94D049BB133111EB)


def _h64(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")


def stage_seed(root_seed: int, stage_name: str) -> int:
    """A 63-bit seed for one stage, stable across machines and Python versions."""
    if isinstance(root_seed, bool) or not isinstance(root_seed, int):
        raise TypeError("root seed must be an integer (42.0 would change every draw)")
    if root_seed < 0:
        raise ValueError("root seed must be non-negative")
    return _h64(f"{root_seed}:stage:{stage_name}") >> 1


def member_hashes(msnos: Iterable[str]) -> np.ndarray:
    """uint64 hash per member id (first 8 bytes of sha256)."""
    return np.fromiter((_h64(m) for m in msnos), dtype=np.uint64)


def _splitmix(x: np.ndarray) -> np.ndarray:
    with np.errstate(over="ignore"):
        z = x + _GOLDEN
        z = (z ^ (z >> np.uint64(30))) * _M1
        z = (z ^ (z >> np.uint64(27))) * _M2
        return z ^ (z >> np.uint64(31))


def member_uniforms(
    root_seed: int, hashes: np.ndarray, period: int, stream: str, n_draws: int = 1
) -> np.ndarray:
    """Uniforms in [0, 1), shape (n_members, n_draws), keyed by member, period and stream."""
    if isinstance(root_seed, bool) or not isinstance(root_seed, int):
        raise TypeError("root seed must be an integer")
    if hashes.dtype != np.uint64:
        raise TypeError("hashes must be uint64 from member_hashes()")
    if isinstance(period, bool) or not isinstance(period, int | np.integer):
        raise TypeError("period must be an integer (a float period would change the draws)")
    if period < 0 or n_draws < 1:
        raise ValueError("period must be >= 0 and n_draws >= 1")
    key = np.uint64(_h64(f"{root_seed}:crn:{stream}:{period}"))
    with np.errstate(over="ignore"):
        base = _splitmix(hashes ^ key)
        draws = np.arange(n_draws, dtype=np.uint64)
        z = _splitmix(base[:, None] + draws[None, :] * _GOLDEN)
    return (z >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def bucket(salt: str, msnos: Iterable[str]) -> np.ndarray:
    """Hash bucket 0..99 per member: sha256(salt + msno) mod 100 (D-8)."""
    return np.fromiter(
        (
            int.from_bytes(hashlib.sha256((salt + m).encode("utf-8")).digest(), "big") % 100
            for m in msnos
        ),
        dtype=np.int64,
    )
