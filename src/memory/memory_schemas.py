"""Pydantic models for approved Q&A memory entries."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ApprovedAnswer(BaseModel):
    """A resolved Q&A pair to be stored in the approved memory collection."""

    question: str = Field(..., description="Cleaned standalone question")
    answer: str = Field(..., description="Approved answer text")
    language: str = Field(default="en", description="Language code (en/ru/uz)")
    ticket_id: int = Field(default=0, description="Associated Zendesk ticket ID if any")
    group_id: int = Field(default=0, description="Source Telegram group ID")
