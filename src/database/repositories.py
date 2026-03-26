"""Async repository helpers for messages, threads, tickets, and identity."""

from __future__ import annotations

from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import delete, desc, select, update

from src.database.engine import get_session_factory
from src.database.models import (
    ConversationThread,
    MessageRow,
    TelegramGroup,
    TelegramUser,
    TicketRow,
    ZendeskUser,
)
from src.escalation.ticket_schemas import TicketRecord, TicketStatus

# ---------------------------------------------------------------------------
# Telegram user repository
# ---------------------------------------------------------------------------


async def get_or_create_telegram_user(
    telegram_user_id: int,
    display_name: str = "",
) -> TelegramUser:
    """Upsert a Telegram user — create if missing, update display_name if changed."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(TelegramUser).where(
            TelegramUser.telegram_user_id == telegram_user_id,
        )
        result = await session.execute(stmt)
        user = result.scalars().first()

        if user is None:
            user = TelegramUser(
                telegram_user_id=telegram_user_id,
                display_name=display_name,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            logger.debug("DB: created telegram_user tg_id={}", telegram_user_id)
        elif user.display_name != display_name and display_name:
            user.display_name = display_name
            user.updated_at = datetime.now(tz=UTC)
            await session.commit()
            await session.refresh(user)
        return user


async def get_telegram_user(telegram_user_id: int) -> TelegramUser | None:
    """Look up a Telegram user by their Telegram user ID."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(TelegramUser).where(
            TelegramUser.telegram_user_id == telegram_user_id,
        )
        result = await session.execute(stmt)
        return result.scalars().first()


# ---------------------------------------------------------------------------
# Zendesk user repository
# ---------------------------------------------------------------------------


async def get_zendesk_user_by_telegram_id(telegram_user_id: int) -> ZendeskUser | None:
    """Look up a cached Zendesk user by Telegram user ID."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(ZendeskUser).where(
            ZendeskUser.telegram_user_id == telegram_user_id,
        )
        result = await session.execute(stmt)
        return result.scalars().first()


async def save_zendesk_user(
    zendesk_user_id: int,
    external_id: str,
    telegram_user_id: int | None = None,
    zendesk_profile_id: str | None = None,
    name: str | None = None,
    role: str | None = None,
) -> ZendeskUser:
    """Insert or update a Zendesk user record."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(ZendeskUser).where(
            ZendeskUser.zendesk_user_id == zendesk_user_id,
        )
        result = await session.execute(stmt)
        user = result.scalars().first()

        if user is None:
            user = ZendeskUser(
                zendesk_user_id=zendesk_user_id,
                external_id=external_id,
                telegram_user_id=telegram_user_id,
                zendesk_profile_id=zendesk_profile_id,
                name=name,
                role=role,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            logger.debug("DB: created zendesk_user zd_id={}", zendesk_user_id)
        else:
            changed = False
            if zendesk_profile_id and user.zendesk_profile_id != zendesk_profile_id:
                user.zendesk_profile_id = zendesk_profile_id
                changed = True
            if name and user.name != name:
                user.name = name
                changed = True
            if telegram_user_id and user.telegram_user_id != telegram_user_id:
                user.telegram_user_id = telegram_user_id
                changed = True
            if changed:
                user.updated_at = datetime.now(tz=UTC)
                await session.commit()
                await session.refresh(user)
        return user


async def update_zendesk_user_name(zendesk_user_id: int, name: str) -> None:
    """Update the cached name for a Zendesk user."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            update(ZendeskUser)
            .where(ZendeskUser.zendesk_user_id == zendesk_user_id)
            .values(name=name, updated_at=datetime.now(tz=UTC))
        )
        await session.execute(stmt)
        await session.commit()


# ---------------------------------------------------------------------------
# Telegram group repository
# ---------------------------------------------------------------------------


async def get_or_create_telegram_group(
    telegram_chat_id: int,
    title: str | None = None,
) -> TelegramGroup:
    """Upsert a Telegram group — create if missing, update title if changed."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(TelegramGroup).where(
            TelegramGroup.telegram_chat_id == telegram_chat_id,
        )
        result = await session.execute(stmt)
        group = result.scalars().first()

        if group is None:
            group = TelegramGroup(
                telegram_chat_id=telegram_chat_id,
                title=title,
            )
            session.add(group)
            await session.commit()
            await session.refresh(group)
            logger.debug("DB: created telegram_group chat_id={}", telegram_chat_id)
        elif title and group.title != title:
            group.title = title
            group.updated_at = datetime.now(tz=UTC)
            await session.commit()
            await session.refresh(group)
        return group


async def get_telegram_group(telegram_chat_id: int) -> TelegramGroup | None:
    """Look up a Telegram group by chat ID."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(TelegramGroup).where(
            TelegramGroup.telegram_chat_id == telegram_chat_id,
        )
        result = await session.execute(stmt)
        return result.scalars().first()


async def get_all_telegram_groups() -> list[TelegramGroup]:
    """Return all Telegram groups (for admin dashboard)."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(TelegramGroup).order_by(TelegramGroup.created_at)
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def set_group_active(telegram_chat_id: int, active: bool) -> None:
    """Set the active flag on a Telegram group."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            update(TelegramGroup)
            .where(TelegramGroup.telegram_chat_id == telegram_chat_id)
            .values(active=active, updated_at=datetime.now(tz=UTC))
        )
        await session.execute(stmt)
        await session.commit()


async def add_telegram_group(telegram_chat_id: int, title: str | None = None) -> TelegramGroup:
    """Add a new Telegram group (admin dashboard). Returns the created group."""
    return await get_or_create_telegram_group(telegram_chat_id, title)


async def remove_telegram_group(telegram_chat_id: int) -> None:
    """Delete a Telegram group from the DB."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = delete(TelegramGroup).where(
            TelegramGroup.telegram_chat_id == telegram_chat_id,
        )
        await session.execute(stmt)
        await session.commit()


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
    link_type: str | None = None,
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
                link_type=link_type,
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


async def get_messages_by_ticket_id(zendesk_ticket_id: int) -> list[dict]:
    """Return all messages linked to a Zendesk ticket, ordered oldest-first."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            select(MessageRow)
            .where(MessageRow.zendesk_ticket_id == zendesk_ticket_id)
            .order_by(MessageRow.created_at)
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
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
    link_type: str | None = None,
) -> None:
    """Set Zendesk ticket/comment IDs and link_type on an existing message row."""
    factory = get_session_factory()
    async with factory() as session:
        values: dict = {
            "zendesk_ticket_id": zendesk_ticket_id,
            "zendesk_comment_id": zendesk_comment_id,
        }
        if link_type is not None:
            values["link_type"] = link_type
        stmt = (
            update(MessageRow)
            .where(
                MessageRow.chat_id == chat_id,
                MessageRow.message_id == message_id,
            )
            .values(**values)
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
            thread.id,
            group_id,
            zendesk_ticket_id,
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
