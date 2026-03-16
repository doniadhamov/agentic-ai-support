"""Async repository helpers for messages and tickets."""

from __future__ import annotations

from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import delete, desc, select, update

from src.database.engine import get_session_factory
from src.database.models import MessageRow, TicketRow
from src.escalation.ticket_schemas import TicketRecord, TicketStatus


# ---------------------------------------------------------------------------
# Message repository
# ---------------------------------------------------------------------------


async def save_message(
    chat_id: int,
    message_id: int,
    user_id: int,
    username: str,
    text: str,
) -> None:
    """Insert a message row."""
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            MessageRow(
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                username=username,
                text=text,
                created_at=datetime.now(tz=UTC),
            )
        )
        await session.commit()


async def get_recent_messages(chat_id: int, limit: int = 20) -> list[dict]:
    """Return the most recent messages for *chat_id* ordered oldest-first."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            select(MessageRow)
            .where(MessageRow.chat_id == chat_id)
            .order_by(desc(MessageRow.created_at))
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
    rows.reverse()  # oldest first
    return [
        {
            "message_id": r.message_id,
            "user_id": r.user_id,
            "username": r.username,
            "text": r.text,
            "timestamp": r.created_at,
        }
        for r in rows
    ]


async def prune_old_messages(chat_id: int, keep: int = 50) -> int:
    """Delete messages beyond the *keep* most recent for a group. Returns count deleted."""
    factory = get_session_factory()
    async with factory() as session:
        # Find the cutoff ID
        subq = (
            select(MessageRow.id)
            .where(MessageRow.chat_id == chat_id)
            .order_by(desc(MessageRow.created_at))
            .limit(keep)
        )
        cutoff_result = await session.execute(subq)
        keep_ids = {row[0] for row in cutoff_result.all()}

        if not keep_ids:
            return 0

        stmt = delete(MessageRow).where(
            MessageRow.chat_id == chat_id,
            MessageRow.id.notin_(keep_ids),
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount or 0


# ---------------------------------------------------------------------------
# Ticket repository
# ---------------------------------------------------------------------------


async def save_ticket(record: TicketRecord) -> None:
    """Insert or update a ticket row from a TicketRecord."""
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(TicketRow, record.ticket_id)
        if row is None:
            session.add(
                TicketRow(
                    ticket_id=record.ticket_id,
                    group_id=record.group_id,
                    user_id=record.user_id,
                    message_id=record.message_id,
                    language=record.language,
                    question=record.question,
                    status=record.status.value,
                    answer=record.answer,
                    created_at=record.created_at,
                )
            )
        else:
            row.status = record.status.value
            row.answer = record.answer
        await session.commit()
    logger.debug("DB: saved ticket_id={}", record.ticket_id)


async def get_open_tickets() -> list[TicketRecord]:
    """Return all open tickets as TicketRecord objects."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(TicketRow).where(TicketRow.status == TicketStatus.OPEN.value)
        result = await session.execute(stmt)
        return [_row_to_record(r) for r in result.scalars().all()]


async def close_ticket(ticket_id: str, answer: str = "") -> None:
    """Mark a ticket as closed in the DB."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            update(TicketRow)
            .where(TicketRow.ticket_id == ticket_id)
            .values(status=TicketStatus.CLOSED.value, answer=answer or TicketRow.answer)
        )
        await session.execute(stmt)
        await session.commit()
    logger.info("DB: closed ticket_id={}", ticket_id)


async def get_ticket(ticket_id: str) -> TicketRecord | None:
    """Fetch a single ticket by ID."""
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(TicketRow, ticket_id)
        return _row_to_record(row) if row else None


async def get_all_tickets() -> list[TicketRecord]:
    """Return all tickets (for admin dashboard)."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(TicketRow).order_by(desc(TicketRow.created_at))
        result = await session.execute(stmt)
        return [_row_to_record(r) for r in result.scalars().all()]


def _row_to_record(row: TicketRow) -> TicketRecord:
    return TicketRecord(
        ticket_id=row.ticket_id,
        group_id=row.group_id,
        user_id=row.user_id,
        message_id=row.message_id,
        language=row.language,
        question=row.question,
        status=TicketStatus(row.status),
        answer=row.answer,
        created_at=row.created_at,
    )
