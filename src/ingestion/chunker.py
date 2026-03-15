"""Sliding-window text chunker that produces ArticleChunk Pydantic models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.ingestion.article_processor import ContentBlock


class ArticleChunk(BaseModel):
    """A single chunk derived from a Zendesk article."""

    article_id: int = Field(..., description="Zendesk article ID")
    chunk_index: int = Field(..., description="Zero-based chunk position within the article")
    text: str = Field(..., description="Text content of this chunk")
    image_url: str | None = Field(default=None, description="Image URL associated with this chunk")
    article_title: str = Field(..., description="Title of the source article")
    article_url: str = Field(..., description="Public URL of the source article")
    section_id: int | None = Field(default=None, description="Zendesk section ID")
    category_id: int | None = Field(default=None, description="Zendesk category ID")
    language: str = Field(default="en", description="Article language code (en/ru/uz)")
    updated_at: datetime = Field(..., description="When the article was last updated")


def chunk_article(
    *,
    article_id: int,
    article_title: str,
    article_url: str,
    content_blocks: list[ContentBlock],
    updated_at: datetime,
    section_id: int | None = None,
    category_id: int | None = None,
    language: str = "en",
    chunk_size: int = 1_000,
    chunk_overlap: int = 200,
) -> list[ArticleChunk]:
    """Split article content into overlapping text chunks.

    Images found inside the article are pinned to the nearest preceding text
    chunk (or the first chunk if no text precedes the image).

    Args:
        article_id: Zendesk article ID.
        article_title: Human-readable title of the article.
        article_url: Public URL for the article.
        content_blocks: Ordered content blocks from :func:`process_article_html`.
        updated_at: Last-modified timestamp of the article.
        section_id: Optional Zendesk section ID.
        category_id: Optional Zendesk category ID.
        language: Language code (en/ru/uz).
        chunk_size: Maximum number of characters per chunk.
        chunk_overlap: Number of characters to overlap between consecutive chunks.

    Returns:
        List of :class:`ArticleChunk` objects in document order.
    """
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be less than chunk_size")

    # Separate text and record image associations
    # Build a list of (text, image_url | None) pairs where each image is
    # associated with the text block immediately before it.
    segments: list[tuple[str, str | None]] = []  # (text, image_url)
    pending_text = ""
    pending_image: str | None = None

    for block in content_blocks:
        if block.is_text:
            assert block.text is not None
            if pending_image:
                # Flush accumulated text with the pending image before starting new text
                segments.append((pending_text, pending_image))
                pending_text = ""
                pending_image = None
            pending_text += (" " if pending_text else "") + block.text
        elif block.is_image:
            assert block.image_url is not None
            if pending_image:
                # Consecutive images: flush previous image with accumulated text
                segments.append((pending_text, pending_image))
                pending_text = ""
            pending_image = block.image_url

    # Flush remaining content
    if pending_text or pending_image:
        segments.append((pending_text, pending_image))

    # Merge consecutive segments that share the same image (or lack of image)
    # and attach orphaned images (no text) to the following text segment.
    merged: list[tuple[str, str | None]] = []
    orphan_image: str | None = None
    for seg_text, seg_image in segments:
        if seg_image and not seg_text:
            # Image with no text — carry forward to the next text segment
            orphan_image = seg_image
            continue
        # Attach any orphaned image to this segment if it has no image of its own
        if orphan_image and not seg_image:
            seg_image = orphan_image
        orphan_image = None
        if merged and merged[-1][1] == seg_image:
            prev_text, prev_image = merged[-1]
            joined = (prev_text + " " + seg_text).strip() if prev_text and seg_text else (prev_text or seg_text)
            merged[-1] = (joined, prev_image)
        else:
            merged.append((seg_text, seg_image))

    # Chunk each segment independently, preserving its image association.
    chunks: list[ArticleChunk] = []
    step = chunk_size - chunk_overlap
    common = dict(
        article_id=article_id,
        article_title=article_title,
        article_url=article_url,
        section_id=section_id,
        category_id=category_id,
        language=language,
        updated_at=updated_at,
    )

    for seg_text, seg_image in merged:
        if not seg_text:
            continue
        start = 0
        while start < len(seg_text):
            end = min(start + chunk_size, len(seg_text))
            chunk_text = seg_text[start:end].strip()
            if chunk_text:
                chunks.append(
                    ArticleChunk(
                        chunk_index=len(chunks),
                        text=chunk_text,
                        image_url=seg_image if start == 0 else None,
                        **common,
                    )
                )
            if end == len(seg_text):
                break
            start += step

    return chunks
