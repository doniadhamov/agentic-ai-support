"""Per-group sliding-window context with asyncio lock and open ticket tracking."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime

from loguru import logger
from pydantic import BaseModel, Field

from src.config.settings import get_settings


class MessageRecord(BaseModel):
    """Single message snapshot stored in the group context window."""

    message_id: int
    user_id: int
    username: str
    text: str
    has_image: bool = False
    has_voice: bool = False
    media_description: str = ""
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
        self._use_db: bool = bool(get_settings().database_url)

    # ------------------------------------------------------------------
    # Message window
    # ------------------------------------------------------------------

    async def add_message(self, record: MessageRecord) -> None:
        """Append a message to the sliding window (thread-safe).

        If PostgreSQL is configured, also persists the message to the DB.
        """
        async with self._lock:
            self._window.append(record)

        if self._use_db:
            try:
                from src.database.repositories import save_message

                await save_message(
                    chat_id=self.chat_id,
                    message_id=record.message_id,
                    user_id=record.user_id,
                    username=record.username,
                    text=record.text,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to persist message to DB: {}", exc)

    async def get_context_strings(self) -> list[str]:
        """Return recent messages as ``'username: text'`` strings (oldest first)."""
        async with self._lock:
            result: list[str] = []
            for r in self._window:
                prefix = f"{r.username}: "
                parts: list[str] = []
                if r.media_description:
                    parts.append(r.media_description)
                elif r.has_image:
                    parts.append("[sent a photo]")
                if r.text:
                    parts.append(r.text)
                result.append(prefix + " ".join(parts) if parts else f"{prefix}(empty)")
            return result

    async def load_from_db(self) -> None:
        """Hydrate the in-memory window from PostgreSQL on startup."""
        if not self._use_db:
            return
        try:
            from src.database.repositories import get_recent_messages

            rows = await get_recent_messages(self.chat_id, limit=self._window.maxlen or 20)
            async with self._lock:
                for row in rows:
                    self._window.append(
                        MessageRecord(
                            message_id=row["message_id"],
                            user_id=row["user_id"],
                            username=row["username"],
                            text=row["text"],
                            timestamp=row["timestamp"],
                        )
                    )
            logger.debug(
                "Hydrated {} message(s) for chat_id={} from DB",
                len(rows),
                self.chat_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to hydrate context from DB for chat_id={}: {}", self.chat_id, exc
            )

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
