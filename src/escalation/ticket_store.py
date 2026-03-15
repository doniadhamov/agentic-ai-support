"""In-memory ticket store with JSON file persistence."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from loguru import logger

from src.escalation.ticket_schemas import TicketRecord, TicketStatus


class TicketStore:
    """Thread-safe in-memory store for open tickets, backed by a JSON file.

    All mutations hold an :class:`asyncio.Lock` to prevent race conditions
    between the poller and the message handler.

    Args:
        file_path: Path to the JSON persistence file. Created automatically.
    """

    def __init__(self, file_path: str = "data/tickets.json") -> None:
        self._path = Path(file_path)
        self._lock = asyncio.Lock()
        self._records: dict[str, TicketRecord] = {}
        self._load_from_disk()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def add(self, record: TicketRecord) -> None:
        """Persist a newly created ticket.

        Args:
            record: The :class:`TicketRecord` returned by the ticket API client.
        """
        async with self._lock:
            self._records[record.ticket_id] = record
            self._save_to_disk()
        logger.debug("TicketStore: added ticket_id={}", record.ticket_id)

    async def get_open_tickets(self) -> list[TicketRecord]:
        """Return all tickets whose status is OPEN.

        Returns:
            List of open :class:`TicketRecord` objects.
        """
        async with self._lock:
            return [r for r in self._records.values() if r.status == TicketStatus.OPEN]

    async def close(self, ticket_id: str, answer: str = "") -> None:
        """Mark a ticket as CLOSED and optionally store the final answer.

        Args:
            ticket_id: The ticket to close.
            answer: The human-provided answer (stored for approved-memory phase).
        """
        async with self._lock:
            if ticket_id not in self._records:
                logger.warning("TicketStore: close called for unknown ticket_id={}", ticket_id)
                return
            self._records[ticket_id].status = TicketStatus.CLOSED
            if answer:
                self._records[ticket_id].answer = answer
            self._save_to_disk()
        logger.info("TicketStore: closed ticket_id={}", ticket_id)

    async def get(self, ticket_id: str) -> TicketRecord | None:
        """Return a single record by ID, or ``None`` if not found."""
        async with self._lock:
            return self._records.get(ticket_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _save_to_disk(self) -> None:
        """Serialise current state to the JSON file (called within the lock)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {tid: rec.model_dump(mode="json") for tid, rec in self._records.items()}
        self._path.write_text(json.dumps(data, indent=2, default=str))

    def _load_from_disk(self) -> None:
        """Deserialise tickets from disk on startup (called synchronously)."""
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            self._records = {tid: TicketRecord.model_validate(rec) for tid, rec in raw.items()}
            logger.info("TicketStore: loaded {} ticket(s) from {}", len(self._records), self._path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("TicketStore: failed to load from disk — {}", exc)
