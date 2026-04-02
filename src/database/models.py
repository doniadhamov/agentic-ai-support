"""SQLAlchemy ORM models — clean schema for LangGraph redesign."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Identity models
# ---------------------------------------------------------------------------


class TelegramUser(Base):
    """One row per Telegram person."""

    __tablename__ = "telegram_users"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ZendeskUser(Base):
    """Zendesk identity linked to a Telegram user via Profiles API."""

    __tablename__ = "zendesk_users"

    zendesk_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    external_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    zendesk_profile_id: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TelegramGroup(Base):
    """One row per Telegram group (each group = one client company)."""

    __tablename__ = "telegram_groups"

    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str | None] = mapped_column(String(255))
    zendesk_organization_id: Mapped[int | None] = mapped_column(BigInteger)
    zendesk_group_id: Mapped[int | None] = mapped_column(BigInteger)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# Message model
# ---------------------------------------------------------------------------


class Message(Base):
    """Every message from any source: Telegram users, bot, Zendesk agents."""

    __tablename__ = "messages"
    __table_args__ = (
        Index("uq_chat_message", "chat_id", "message_id", unique=True),
        Index("idx_msg_chat_created", "chat_id", "created_at"),
        Index("idx_msg_chat_source_created", "chat_id", "source", "created_at"),
        Index("idx_msg_chat_msgid", "chat_id", "message_id"),
        Index("idx_msg_ticket", "zendesk_ticket_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="telegram")
    # source values: "telegram" (user), "bot" (our bot), "zendesk" (human agent)
    reply_to_message_id: Mapped[int | None] = mapped_column(BigInteger)
    file_id: Mapped[str | None] = mapped_column(String(255))
    file_type: Mapped[str | None] = mapped_column(String(20))
    # "photo", "voice", "document", or None for text-only
    file_description: Mapped[str | None] = mapped_column(Text)
    zendesk_ticket_id: Mapped[int | None] = mapped_column(BigInteger)
    zendesk_comment_id: Mapped[int | None] = mapped_column(BigInteger)
    link_type: Mapped[str | None] = mapped_column(String(20))
    # link_type values: "root" (first msg that created ticket), "reply" (subsequent), "mirror" (from Zendesk)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Conversation thread model
# ---------------------------------------------------------------------------


class ConversationThread(Base):
    """Maps a Telegram user's conversation in a group to a Zendesk ticket."""

    __tablename__ = "conversation_threads"
    __table_args__ = (
        Index("idx_thread_group_user_status", "group_id", "user_id", "status"),
        Index("idx_thread_group_status", "group_id", "status"),
        Index("idx_thread_ticket", "zendesk_ticket_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    zendesk_ticket_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    # status values: "open", "pending", "solved", "closed"
    urgency: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    # urgency values: "normal", "high", "critical"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(tz=UTC)
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(tz=UTC)
    )


# ---------------------------------------------------------------------------
# Bot decision log (for dashboard analytics and decision review)
# ---------------------------------------------------------------------------


class BotDecision(Base):
    """Log of every bot decision — for performance analytics and decision review."""

    __tablename__ = "bot_decisions"
    __table_args__ = (
        Index("idx_decision_created", "created_at"),
        Index("idx_decision_group_created", "group_id", "created_at"),
        Index("idx_decision_action", "action", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    file_description: Mapped[str | None] = mapped_column(Text)

    # Think node output
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    urgency: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    ticket_action: Mapped[str] = mapped_column(String(20), nullable=False)
    target_ticket_id: Mapped[int | None] = mapped_column(BigInteger)
    extracted_question: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Generate node output (if action="answer")
    answer_text: Mapped[str | None] = mapped_column(Text)
    retrieval_confidence: Mapped[float | None] = mapped_column(nullable=True)
    needs_escalation: Mapped[bool] = mapped_column(Boolean, default=False)

    # Timing (milliseconds)
    perceive_ms: Mapped[int | None] = mapped_column(Integer)
    think_ms: Mapped[int | None] = mapped_column(Integer)
    retrieve_ms: Mapped[int | None] = mapped_column(Integer)
    generate_ms: Mapped[int | None] = mapped_column(Integer)
    total_ms: Mapped[int | None] = mapped_column(Integer)

    # Correction (set by admin in Decision Review page)
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    correct_action: Mapped[str | None] = mapped_column(String(20))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
