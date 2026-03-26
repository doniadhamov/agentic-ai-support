"""Pydantic models for the Zendesk ticket workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class TicketStatus(StrEnum):
    """Zendesk ticket statuses."""

    NEW = "new"
    OPEN = "open"
    PENDING = "pending"
    HOLD = "hold"
    SOLVED = "solved"
    CLOSED = "closed"


class ZendeskTicketCreate(BaseModel):
    """Payload for creating a new Zendesk ticket."""

    subject: str = Field(..., description="Ticket subject line")
    body: str = Field(..., description="First comment body (HTML or plain text)")
    requester_name: str = Field(
        default="Telegram User",
        description="Display name for the requester",
    )
    requester_id: int | None = Field(default=None, description="Zendesk user ID for requester")
    author_id: int | None = Field(default=None, description="Zendesk user ID for comment author")
    tags: list[str] = Field(default_factory=lambda: ["source_telegram"])
    custom_fields: list[dict] | None = Field(
        default=None,
        description="Zendesk custom fields for the ticket",
    )


class ZendeskComment(BaseModel):
    """A comment to add to an existing Zendesk ticket."""

    body: str = Field(..., description="Comment body text")
    public: bool = Field(default=True, description="Whether the comment is public")
    author_id: int | None = Field(default=None, description="Zendesk user ID for comment author")
    attachment_tokens: list[str] = Field(
        default_factory=list,
        description="Upload tokens from the Zendesk Attachments API",
    )


class TicketRecord(BaseModel):
    """In-memory representation of a ticket tracked by the store."""

    ticket_id: int = Field(..., description="Zendesk ticket ID (integer)")
    group_id: int
    user_id: int
    message_id: int = Field(..., description="Original Telegram message ID to reply to")
    language: str = Field(default="en")
    question: str
    status: TicketStatus = Field(default=TicketStatus.OPEN)
    answer: str = Field(default="", description="Human answer; populated when status=answered")
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class TicketResponse(BaseModel):
    """Response returned by the Zendesk API for a status check."""

    ticket_id: int
    status: TicketStatus
    answer: str = Field(default="")
