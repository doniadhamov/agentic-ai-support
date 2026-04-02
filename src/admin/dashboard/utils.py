"""Shared helpers for the Streamlit admin dashboard."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from typing import Any

_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    """Return a persistent event loop (created once, reused across calls).

    Using a single loop avoids the uvloop/asyncpg issue where asyncio.run()
    closes the loop after each call, leaving connection pool transports dead
    for subsequent calls.
    """
    global _loop
    if _loop is None or _loop.is_closed():
        with _loop_lock:
            if _loop is None or _loop.is_closed():
                _loop = asyncio.new_event_loop()
    return _loop


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine from synchronous Streamlit code.

    Uses a persistent event loop so that SQLAlchemy async engine connections
    (bound to the loop) survive across multiple calls.
    """
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop and running_loop.is_running():
        # We're inside an existing event loop (e.g. Jupyter / nested);
        # run in a thread to avoid deadlocks.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: _get_loop().run_until_complete(coro)).result()
    else:
        return _get_loop().run_until_complete(coro)
