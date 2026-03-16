"""In-memory ticket store with PostgreSQL persistence (preferred) or JSON file fallback."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from loguru import logger

from src.config.settings import get_settings
from src.escalation.ticket_schemas import TicketRecord, TicketStatus


class TicketStore:
    """Thread-safe in-memory store for open tickets.

    When ``DATABASE_URL`` is configured, all mutations are persisted to
    PostgreSQL via :mod:`src.database.repositories`.  Otherwise the store
    falls back to the original JSON file on disk.

    Args:
        file_path: Path to the JSON persistence file (fallback only).
    """

    def __init__(self, file_path: str = "data/tickets.json") -> None:
        self._path = Path(file_path)
        self._lock = asyncio.Lock()
        self._records: dict[str, TicketRecord] = {}
        self._use_db: bool = bool(get_settings().database_url)
        if not self._use_db:
            self._load_from_disk()

    async def init_from_db(self) -> None:
        """Load open tickets from PostgreSQL on startup (call once after event loop is running)."""
        if not self._use_db:
            return
        from src.database.repositories import get_open_tickets

        open_tickets = await get_open_tickets()
        async with self._lock:
            for rec in open_tickets:
                self._records[rec.ticket_id] = rec
        logger.info("TicketStore: loaded {} open ticket(s) from DB", len(open_tickets))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def add(self, record: TicketRecord) -> None:
        """Persist a newly created ticket."""
        async with self._lock:
            self._records[record.ticket_id] = record
            if self._use_db:
                await self._db_save(record)
            else:
                self._save_to_disk()
        logger.debug("TicketStore: added ticket_id={}", record.ticket_id)

    async def get_open_tickets(self) -> list[TicketRecord]:
        """Return all tickets whose status is OPEN."""
        async with self._lock:
            return [r for r in self._records.values() if r.status == TicketStatus.OPEN]

    async def close(self, ticket_id: str, answer: str = "") -> None:
        """Mark a ticket as CLOSED and optionally store the final answer."""
        async with self._lock:
            if ticket_id not in self._records:
                logger.warning("TicketStore: close called for unknown ticket_id={}", ticket_id)
                return
            self._records[ticket_id].status = TicketStatus.CLOSED
            if answer:
                self._records[ticket_id].answer = answer
            if self._use_db:
                await self._db_close(ticket_id, answer)
            else:
                self._save_to_disk()
        logger.info("TicketStore: closed ticket_id={}", ticket_id)

    async def get(self, ticket_id: str) -> TicketRecord | None:
        """Return a single record by ID, or ``None`` if not found."""
        async with self._lock:
            return self._records.get(ticket_id)

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _db_save(record: TicketRecord) -> None:
        from src.database.repositories import save_ticket

        await save_ticket(record)

    @staticmethod
    async def _db_close(ticket_id: str, answer: str) -> None:
        from src.database.repositories import close_ticket

        await close_ticket(ticket_id, answer)

    # ------------------------------------------------------------------
    # JSON fallback helpers
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
