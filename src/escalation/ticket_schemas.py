"""Pydantic models for the Zendesk ticket workflow."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ZendeskTicketClosedError(Exception):
    """Raised when a Zendesk API call fails because the ticket is solved/closed (HTTP 422)."""

    def __init__(self, ticket_id: int, status_code: int = 422, detail: str = "") -> None:
        self.ticket_id = ticket_id
        self.status_code = status_code
        self.detail = detail
        super().__init__(
            f"Zendesk ticket {ticket_id} is closed/solved (HTTP {status_code}): {detail}"
        )


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
    via_followup_source_id: int | None = Field(
        default=None,
        description="Zendesk ticket ID to create a follow-up for (closed tickets only)",
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
