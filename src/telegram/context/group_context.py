"""Per-group sliding-window context with asyncio lock and open ticket tracking."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime

from pydantic import BaseModel, Field


class MessageRecord(BaseModel):
    """Single message snapshot stored in the group context window."""

    message_id: int
    user_id: int
    username: str
    text: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class GroupContext:
    """Sliding-window conversation context for a single Telegram group.

    Attributes:
        chat_id: Telegram chat ID this context belongs to.
        open_tickets: Mapping of ``message_id → ticket_id`` for outstanding escalations.
    """

    def __init__(self, chat_id: int, window_size: int = 20) -> None:
        self.chat_id: int = chat_id
        self.open_tickets: dict[int, str] = {}
        self._window: deque[MessageRecord] = deque(maxlen=window_size)
        self._lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Message window
    # ------------------------------------------------------------------

    async def add_message(self, record: MessageRecord) -> None:
        """Append a message to the sliding window (thread-safe)."""
        async with self._lock:
            self._window.append(record)

    async def get_context_strings(self) -> list[str]:
        """Return recent messages as ``'username: text'`` strings (oldest first)."""
        async with self._lock:
            return [f"{r.username}: {r.text}" for r in self._window]

    # ------------------------------------------------------------------
    # Ticket tracking
    # ------------------------------------------------------------------

    async def add_ticket(self, message_id: int, ticket_id: str) -> None:
        """Register an open escalation ticket for *message_id*."""
        async with self._lock:
            self.open_tickets[message_id] = ticket_id

    async def close_ticket(self, message_id: int) -> None:
        """Mark the ticket for *message_id* as closed (no-op if not found)."""
        async with self._lock:
            self.open_tickets.pop(message_id, None)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def window_size(self) -> int:
        """Maximum number of messages kept in memory."""
        return self._window.maxlen or 0

    def __repr__(self) -> str:
        return (
            f"GroupContext(chat_id={self.chat_id}, "
            f"messages={len(self._window)}, "
            f"open_tickets={len(self.open_tickets)})"
        )
