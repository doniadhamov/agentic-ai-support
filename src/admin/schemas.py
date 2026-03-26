"""Pydantic models for the admin dashboard."""

from __future__ import annotations

from pydantic import BaseModel


class IngestResult(BaseModel):
    """Result of a file ingestion operation."""

    filename: str
    article_id: int
    chunks: int
    language: str = "en"
