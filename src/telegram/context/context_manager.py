"""Singleton registry of per-group :class:`GroupContext` instances."""

from __future__ import annotations

import asyncio

from loguru import logger

from src.config.settings import get_settings
from src.telegram.context.group_context import GroupContext


class ContextManager:
    """Thread-safe registry that lazily creates one :class:`GroupContext` per chat.

    When PostgreSQL is configured, newly created contexts are automatically
    hydrated from the database so conversation history survives bot restarts.

    Usage::

        manager = ContextManager()
        ctx = await manager.get_or_create(chat_id=-1001234567890)
        await ctx.add_message(record)
    """

    def __init__(self) -> None:
        self._contexts: dict[int, GroupContext] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._window_size: int = get_settings().group_context_window

    async def get_or_create(self, chat_id: int) -> GroupContext:
        """Return the existing context for *chat_id* or create a new one."""
        async with self._lock:
            if chat_id not in self._contexts:
                ctx = GroupContext(
                    chat_id=chat_id,
                    window_size=self._window_size,
                )
                await ctx.load_from_db()
                self._contexts[chat_id] = ctx
                logger.debug("Created new GroupContext for chat_id={}", chat_id)
            return self._contexts[chat_id]

    def __len__(self) -> int:
        return len(self._contexts)


# Module-level singleton — import this where needed.
_manager: ContextManager | None = None


def get_context_manager() -> ContextManager:
    """Return the module-level :class:`ContextManager` singleton."""
    global _manager
    if _manager is None:
        _manager = ContextManager()
    return _manager
