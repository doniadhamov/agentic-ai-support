"""Async repository helpers for messages, conversation threads, and tickets."""

from __future__ import annotations

from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import delete, desc, select, update

from src.database.engine import get_session_factory
from src.database.models import ConversationThread, MessageRow, TicketRow
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
    source: str = "telegram",
    reply_to_message_id: int | None = None,
    zendesk_ticket_id: int | None = None,
    zendesk_comment_id: int | None = None,
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
                source=source,
                reply_to_message_id=reply_to_message_id,
                zendesk_ticket_id=zendesk_ticket_id,
                zendesk_comment_id=zendesk_comment_id,
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
            "source": r.source,
            "timestamp": r.created_at,
        }
        for r in rows
    ]


async def get_message_by_telegram_id(chat_id: int, message_id: int) -> MessageRow | None:
    """Look up a message by its Telegram chat_id + message_id (for reply-based ticket lookup)."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(MessageRow).where(
            MessageRow.chat_id == chat_id,
            MessageRow.message_id == message_id,
        )
        result = await session.execute(stmt)
        return result.scalars().first()


async def update_message_zendesk_ids(
    chat_id: int,
    message_id: int,
    zendesk_ticket_id: int,
    zendesk_comment_id: int | None = None,
) -> None:
    """Set Zendesk ticket/comment IDs on an existing message row."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            update(MessageRow)
            .where(
                MessageRow.chat_id == chat_id,
                MessageRow.message_id == message_id,
            )
            .values(
                zendesk_ticket_id=zendesk_ticket_id,
                zendesk_comment_id=zendesk_comment_id,
            )
        )
        await session.execute(stmt)
        await session.commit()


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
# Conversation thread repository
# ---------------------------------------------------------------------------


async def create_thread(
    group_id: int,
    user_id: int,
    zendesk_ticket_id: int,
    subject: str = "",
) -> ConversationThread:
    """Create a new conversation thread mapping."""
    factory = get_session_factory()
    async with factory() as session:
        now = datetime.now(tz=UTC)
        thread = ConversationThread(
            group_id=group_id,
            user_id=user_id,
            zendesk_ticket_id=zendesk_ticket_id,
            subject=subject,
            status="active",
            created_at=now,
            last_message_at=now,
        )
        session.add(thread)
        await session.commit()
        await session.refresh(thread)
        logger.info(
            "DB: created thread id={} group={} ticket={}",
            thread.id, group_id, zendesk_ticket_id,
        )
        return thread


async def get_active_thread(group_id: int, user_id: int) -> ConversationThread | None:
    """Return the active thread for a specific user in a group (if any)."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            select(ConversationThread)
            .where(
                ConversationThread.group_id == group_id,
                ConversationThread.user_id == user_id,
                ConversationThread.status == "active",
            )
            .order_by(desc(ConversationThread.last_message_at))
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalars().first()


async def get_active_threads_in_group(group_id: int) -> list[ConversationThread]:
    """Return all active threads in a group (across all users)."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            select(ConversationThread)
            .where(
                ConversationThread.group_id == group_id,
                ConversationThread.status == "active",
            )
            .order_by(desc(ConversationThread.last_message_at))
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def get_thread_by_zendesk_ticket_id(zendesk_ticket_id: int) -> ConversationThread | None:
    """Look up a conversation thread by its Zendesk ticket ID."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(ConversationThread).where(
            ConversationThread.zendesk_ticket_id == zendesk_ticket_id,
        )
        result = await session.execute(stmt)
        return result.scalars().first()


async def close_thread(thread_id: int) -> None:
    """Mark a conversation thread as closed."""
    factory = get_session_factory()
    now = datetime.now(tz=UTC)
    async with factory() as session:
        stmt = (
            update(ConversationThread)
            .where(ConversationThread.id == thread_id)
            .values(status="closed", closed_at=now)
        )
        await session.execute(stmt)
        await session.commit()
    logger.info("DB: closed thread id={}", thread_id)


async def touch_thread(thread_id: int) -> None:
    """Update last_message_at on a thread to now."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            update(ConversationThread)
            .where(ConversationThread.id == thread_id)
            .values(last_message_at=datetime.now(tz=UTC))
        )
        await session.execute(stmt)
        await session.commit()


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


async def close_ticket(ticket_id: int, answer: str = "") -> None:
    """Mark a ticket as closed in the DB."""
    factory = get_session_factory()
    now = datetime.now(tz=UTC)
    async with factory() as session:
        stmt = (
            update(TicketRow)
            .where(TicketRow.ticket_id == ticket_id)
            .values(
                status=TicketStatus.CLOSED.value,
                answer=answer or TicketRow.answer,
                closed_at=now,
            )
        )
        await session.execute(stmt)
        await session.commit()
    logger.info("DB: closed ticket_id={}", ticket_id)


async def get_ticket(ticket_id: int) -> TicketRecord | None:
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
