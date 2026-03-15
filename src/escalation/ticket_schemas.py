"""Pydantic models for the escalation ticket workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class TicketStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    CLOSED = "closed"


class TicketCreate(BaseModel):
    """Payload sent to the external ticket API when creating a new ticket."""

    group_id: int = Field(..., description="Telegram group chat ID")
    user_id: int = Field(..., description="Telegram user ID who asked the question")
    message_id: int = Field(..., description="Original Telegram message ID to reply to")
    language: str = Field(default="en", description="Detected language code")
    question: str = Field(..., description="Clean standalone question extracted by the agent")
    conversation_summary: str = Field(
        default="", description="Brief summary of relevant conversation context"
    )


class TicketRecord(BaseModel):
    """In-memory representation of a ticket tracked by the TicketStore."""

    ticket_id: str = Field(..., description="Unique ticket ID returned by the ticket API")
    group_id: int
    user_id: int
    message_id: int = Field(..., description="Original Telegram message ID to reply to")
    language: str = Field(default="en")
    question: str
    status: TicketStatus = Field(default=TicketStatus.OPEN)
    answer: str = Field(default="", description="Human answer; populated when status=answered")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=UTC)
    )


class TicketResponse(BaseModel):
    """Response returned by the ticket API for a status check."""

    ticket_id: str
    status: TicketStatus
    answer: str = Field(default="")
