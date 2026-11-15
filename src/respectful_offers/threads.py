"""Thread limits for small model fits."""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext

SMALL_FIT_ROWS = 100_000


def small_fit_threads(n: int) -> AbstractContextManager[object]:
    """One OpenMP thread for small fits: thread start-up dominated them 30-fold (7.3 s → 0.25 s
    for eight gradient-boosting fits on 1,000 rows). Results do not depend on the thread count."""
    from threadpoolctl import threadpool_limits

    return threadpool_limits(1) if n < SMALL_FIT_ROWS else nullcontext()
