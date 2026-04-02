"""Async repository helpers for the LangGraph redesign."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import delete, desc, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.database.engine import get_session_factory
from src.database.models import (
    BotDecision,
    ConversationThread,
    Message,
    TelegramGroup,
    TelegramUser,
    ZendeskUser,
)

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
# Message repository — for perceive node
# ---------------------------------------------------------------------------


async def get_recent_messages(chat_id: int, limit: int = 30) -> list[dict]:
    """Recent messages in this group, oldest first.

    Returns dicts with: message_id, user_id, username, text, source,
    file_id, file_type, file_description, created_at.
    """
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(desc(Message.created_at))
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
            "file_id": r.file_id,
            "file_type": r.file_type,
            "file_description": r.file_description,
            "created_at": r.created_at,
        }
        for r in rows
    ]


async def get_bot_last_response(chat_id: int) -> dict | None:
    """Most recent bot message in this group."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            select(Message)
            .where(Message.chat_id == chat_id, Message.source == "bot")
            .order_by(desc(Message.created_at))
            .limit(1)
        )
        result = await session.execute(stmt)
        row = result.scalars().first()
    if row is None:
        return None
    return {
        "text": row.text,
        "created_at": row.created_at,
        "reply_to_message_id": row.reply_to_message_id,
    }


async def get_message_by_telegram_id(chat_id: int, message_id: int) -> Message | None:
    """Look up a message by its Telegram chat_id + message_id."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(Message).where(
            Message.chat_id == chat_id,
            Message.message_id == message_id,
        )
        result = await session.execute(stmt)
        return result.scalars().first()


# ---------------------------------------------------------------------------
# Message repository — for remember node
# ---------------------------------------------------------------------------


async def save_message(
    chat_id: int,
    message_id: int,
    user_id: int,
    username: str,
    text: str,
    source: str = "telegram",
    reply_to_message_id: int | None = None,
    file_id: str | None = None,
    file_type: str | None = None,
    zendesk_ticket_id: int | None = None,
    zendesk_comment_id: int | None = None,
    link_type: str | None = None,
) -> None:
    """Insert a message row. ON CONFLICT (chat_id, message_id) DO NOTHING."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = pg_insert(Message).values(
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
            username=username,
            text=text,
            source=source,
            reply_to_message_id=reply_to_message_id,
            file_id=file_id,
            file_type=file_type,
            zendesk_ticket_id=zendesk_ticket_id,
            zendesk_comment_id=zendesk_comment_id,
            link_type=link_type,
            created_at=datetime.now(tz=UTC),
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=["chat_id", "message_id"])
        await session.execute(stmt)
        await session.commit()


async def update_message_file_description(
    chat_id: int, message_id: int, file_description: str
) -> None:
    """Set file_description on a message row."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            update(Message)
            .where(Message.chat_id == chat_id, Message.message_id == message_id)
            .values(file_description=file_description)
        )
        await session.execute(stmt)
        await session.commit()


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
            update(Message)
            .where(Message.chat_id == chat_id, Message.message_id == message_id)
            .values(**values)
        )
        await session.execute(stmt)
        await session.commit()


# ---------------------------------------------------------------------------
# Message repository — for webhook handler & admin
# ---------------------------------------------------------------------------


async def get_root_message_id(zendesk_ticket_id: int, chat_id: int) -> int | None:
    """Return the Telegram message_id of the root message for a ticket, or None."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            select(Message.message_id)
            .where(
                Message.zendesk_ticket_id == zendesk_ticket_id,
                Message.chat_id == chat_id,
                Message.link_type == "root",
            )
            .order_by(Message.created_at)
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def get_messages_by_ticket_id(zendesk_ticket_id: int) -> list[dict]:
    """Return all messages linked to a Zendesk ticket, ordered oldest-first."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            select(Message)
            .where(Message.zendesk_ticket_id == zendesk_ticket_id)
            .order_by(Message.created_at)
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
            "created_at": r.created_at,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Conversation thread repository — for perceive node
# ---------------------------------------------------------------------------


async def get_active_threads_in_group(group_id: int) -> list[ConversationThread]:
    """All open/pending threads in this group."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            select(ConversationThread)
            .where(
                ConversationThread.group_id == group_id,
                ConversationThread.status.in_(["open", "pending"]),
            )
            .order_by(desc(ConversationThread.last_message_at))
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def get_active_thread(group_id: int, user_id: int) -> ConversationThread | None:
    """This user's open/pending thread in this group (if any)."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            select(ConversationThread)
            .where(
                ConversationThread.group_id == group_id,
                ConversationThread.user_id == user_id,
                ConversationThread.status.in_(["open", "pending"]),
            )
            .order_by(desc(ConversationThread.last_message_at))
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalars().first()


async def get_recently_solved_threads(group_id: int, days: int = 7) -> list[dict]:
    """Recently solved/closed threads in this group (for follow-up detection)."""
    factory = get_session_factory()
    cutoff = datetime.now(tz=UTC) - timedelta(days=days)
    async with factory() as session:
        stmt = (
            select(ConversationThread)
            .where(
                ConversationThread.group_id == group_id,
                ConversationThread.status.in_(["solved", "closed"]),
                ConversationThread.closed_at >= cutoff,
            )
            .order_by(desc(ConversationThread.closed_at))
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
    return [
        {
            "ticket_id": r.zendesk_ticket_id,
            "subject": r.subject,
            "user_id": r.user_id,
            "status": r.status,
            "closed_at": r.closed_at,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Conversation thread repository — for remember node
# ---------------------------------------------------------------------------


async def create_thread(
    group_id: int,
    user_id: int,
    zendesk_ticket_id: int,
    subject: str = "",
    urgency: str = "normal",
) -> ConversationThread:
    """Create a new conversation thread."""
    factory = get_session_factory()
    async with factory() as session:
        now = datetime.now(tz=UTC)
        thread = ConversationThread(
            group_id=group_id,
            user_id=user_id,
            zendesk_ticket_id=zendesk_ticket_id,
            subject=subject,
            status="open",
            urgency=urgency,
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
# Conversation thread repository — for webhook handler
# ---------------------------------------------------------------------------


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


async def update_thread_status(zendesk_ticket_id: int, status: str) -> None:
    """Update a conversation thread's status by Zendesk ticket ID."""
    factory = get_session_factory()
    async with factory() as session:
        values: dict = {"status": status}
        if status in ("solved", "closed"):
            values["closed_at"] = datetime.now(tz=UTC)
        stmt = (
            update(ConversationThread)
            .where(ConversationThread.zendesk_ticket_id == zendesk_ticket_id)
            .values(**values)
        )
        await session.execute(stmt)
        await session.commit()
    logger.info("DB: updated thread status for ticket={} -> {}", zendesk_ticket_id, status)


# ---------------------------------------------------------------------------
# Bot decision repository — for remember node & dashboard
# ---------------------------------------------------------------------------


async def save_bot_decision(
    group_id: int,
    user_id: int,
    message_id: int,
    message_text: str,
    action: str,
    ticket_action: str,
    language: str = "en",
    urgency: str = "normal",
    reasoning: str = "",
    file_description: str | None = None,
    target_ticket_id: int | None = None,
    extracted_question: str | None = None,
    answer_text: str | None = None,
    retrieval_confidence: float | None = None,
    needs_escalation: bool = False,
    perceive_ms: int | None = None,
    think_ms: int | None = None,
    retrieve_ms: int | None = None,
    generate_ms: int | None = None,
    total_ms: int | None = None,
) -> None:
    """Log a bot decision for analytics and review."""
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            BotDecision(
                group_id=group_id,
                user_id=user_id,
                message_id=message_id,
                message_text=message_text,
                file_description=file_description,
                action=action,
                urgency=urgency,
                ticket_action=ticket_action,
                target_ticket_id=target_ticket_id,
                extracted_question=extracted_question,
                language=language,
                reasoning=reasoning,
                answer_text=answer_text,
                retrieval_confidence=retrieval_confidence,
                needs_escalation=needs_escalation,
                perceive_ms=perceive_ms,
                think_ms=think_ms,
                retrieve_ms=retrieve_ms,
                generate_ms=generate_ms,
                total_ms=total_ms,
            )
        )
        await session.commit()
