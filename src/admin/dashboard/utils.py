"""Shared helpers for the Streamlit admin dashboard."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine from synchronous Streamlit code.

    Creates a new event loop if none is running (Streamlit's default),
    or uses the existing loop if available.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're inside an existing event loop (e.g. Jupyter / nested);
        # create a new loop in a thread to avoid deadlocks.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)
