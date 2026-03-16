"""Pydantic models for the admin dashboard."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class AllowedGroup(BaseModel):
    """A Telegram group that is allowed to use the bot."""

    group_id: int = Field(..., description="Telegram group/supergroup chat ID")
    name: str = Field(default="", description="Human-readable group name")
    added_at: datetime = Field(default_factory=_utcnow)


class IngestResult(BaseModel):
    """Result of a file ingestion operation."""

    filename: str
    article_id: int
    chunks: int
    language: str = "en"
