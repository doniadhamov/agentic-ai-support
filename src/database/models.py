"""SQLAlchemy ORM models for conversation messages, threads, tickets, and identity."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Identity models
# ---------------------------------------------------------------------------


class TelegramUser(Base):
    """One row per Telegram person. Central identity entity."""

    __tablename__ = "telegram_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        index=True,
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ZendeskUser(Base):
    """Zendesk identity linked to a Telegram user via Profiles API."""

    __tablename__ = "zendesk_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    zendesk_user_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        nullable=False,
    )
    zendesk_profile_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        default=None,
    )
    external_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )
    telegram_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        index=True,
        nullable=True,
        default=None,
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    role: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TelegramGroup(Base):
    """One row per Telegram group. DB is source of truth for group metadata."""

    __tablename__ = "telegram_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_chat_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        index=True,
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    zendesk_organization_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        default=None,
    )
    zendesk_group_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        default=None,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


# ---------------------------------------------------------------------------
# Message model
# ---------------------------------------------------------------------------


class MessageRow(Base):
    """Persisted conversation message for group context recovery after restart."""

    __tablename__ = "telegram_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="telegram",
    )
    reply_to_message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        default=None,
    )
    zendesk_ticket_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        default=None,
    )
    zendesk_comment_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        default=None,
    )
    link_type: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ConversationThread(Base):
    """Maps a Telegram conversation thread to a Zendesk ticket."""

    __tablename__ = "conversation_threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    zendesk_ticket_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        nullable=False,
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(tz=UTC),
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(tz=UTC),
    )


class TicketRow(Base):
    """Persisted escalation ticket (Zendesk ticket IDs are integers)."""

    __tablename__ = "tickets"

    ticket_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(tz=UTC),
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
