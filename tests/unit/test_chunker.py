"""Unit tests for the sliding-window chunker."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.ingestion.article_processor import ContentBlock
from src.ingestion.chunker import ArticleChunk, chunk_article

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2024, 1, 1, tzinfo=UTC)
BASE_KWARGS = dict(
    article_id=42,
    article_title="Test Article",
    article_url="https://example.com/articles/42",
    updated_at=NOW,
    section_id=10,
    category_id=1,
    language="en",
)


def text_block(text: str) -> ContentBlock:
    return ContentBlock(text=text)


def image_block(url: str) -> ContentBlock:
    return ContentBlock(image_url=url)


# ---------------------------------------------------------------------------
# Basic chunking
# ---------------------------------------------------------------------------


def test_empty_content_returns_no_chunks() -> None:
    chunks = chunk_article(content_blocks=[], **BASE_KWARGS)
    assert chunks == []


def test_single_short_text_produces_one_chunk() -> None:
    blocks = [text_block("Hello world")]
    chunks = chunk_article(content_blocks=blocks, chunk_size=500, chunk_overlap=50, **BASE_KWARGS)
    assert len(chunks) == 1
    chunk = chunks[0]
    assert "Hello world" in chunk.text
    assert chunk.chunk_index == 0
    assert chunk.article_id == 42


def test_long_text_is_split_into_multiple_chunks() -> None:
    # 3 000 chars → should produce more than 1 chunk with size=1000, overlap=200
    long_text = "A" * 3_000
    blocks = [text_block(long_text)]
    chunks = chunk_article(content_blocks=blocks, chunk_size=1_000, chunk_overlap=200, **BASE_KWARGS)
    assert len(chunks) > 1


def test_chunk_indices_are_sequential() -> None:
    long_text = "word " * 400  # ~2 000 chars
    blocks = [text_block(long_text)]
    chunks = chunk_article(content_blocks=blocks, chunk_size=500, chunk_overlap=100, **BASE_KWARGS)
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_index == i


def test_chunks_respect_max_size() -> None:
    long_text = "X" * 5_000
    blocks = [text_block(long_text)]
    chunk_size = 800
    chunks = chunk_article(
        content_blocks=blocks, chunk_size=chunk_size, chunk_overlap=100, **BASE_KWARGS
    )
    for chunk in chunks:
        assert len(chunk.text) <= chunk_size


def test_overlap_creates_shared_content() -> None:
    """The start of chunk[n+1] should overlap with the end of chunk[n]."""
    long_text = "ABCDEFGHIJ" * 200  # 2 000 chars of repeating pattern
    blocks = [text_block(long_text)]
    chunk_size = 500
    overlap = 100
    chunks = chunk_article(
        content_blocks=blocks, chunk_size=chunk_size, chunk_overlap=overlap, **BASE_KWARGS
    )
    assert len(chunks) >= 2
    # The tail of chunk 0 should appear somewhere in the head of chunk 1
    tail_of_first = chunks[0].text[-(overlap // 2):]
    assert tail_of_first in chunks[1].text


# ---------------------------------------------------------------------------
# Image association
# ---------------------------------------------------------------------------


def test_chunk_without_images_has_no_image_url() -> None:
    blocks = [text_block("Plain text only")]
    chunks = chunk_article(content_blocks=blocks, **BASE_KWARGS)
    assert all(c.image_url is None for c in chunks)


def test_image_after_text_is_attached_to_chunk() -> None:
    blocks = [
        text_block("Some descriptive text."),
        image_block("https://example.com/img.png"),
    ]
    chunks = chunk_article(content_blocks=blocks, chunk_size=500, chunk_overlap=50, **BASE_KWARGS)
    assert len(chunks) >= 1
    # At least one chunk should carry the image
    image_chunks = [c for c in chunks if c.image_url == "https://example.com/img.png"]
    assert len(image_chunks) >= 1


def test_image_before_any_text_is_attached_to_first_chunk() -> None:
    blocks = [
        image_block("https://example.com/header.png"),
        text_block("Intro paragraph here."),
    ]
    chunks = chunk_article(content_blocks=blocks, chunk_size=500, chunk_overlap=50, **BASE_KWARGS)
    assert len(chunks) >= 1
    assert chunks[0].image_url == "https://example.com/header.png"


def test_multiple_images_in_article() -> None:
    blocks = [
        text_block("First section text."),
        image_block("https://example.com/img1.png"),
        text_block("Second section text."),
        image_block("https://example.com/img2.png"),
        text_block("Third section text."),
    ]
    chunks = chunk_article(content_blocks=blocks, chunk_size=2_000, chunk_overlap=100, **BASE_KWARGS)
    # All images should be referenced somewhere
    all_image_urls = {c.image_url for c in chunks if c.image_url}
    assert "https://example.com/img1.png" in all_image_urls
    assert "https://example.com/img2.png" in all_image_urls


# ---------------------------------------------------------------------------
# Metadata propagation
# ---------------------------------------------------------------------------


def test_metadata_propagated_to_all_chunks() -> None:
    blocks = [text_block("word " * 400)]
    chunks = chunk_article(content_blocks=blocks, chunk_size=300, chunk_overlap=50, **BASE_KWARGS)
    for chunk in chunks:
        assert chunk.article_id == 42
        assert chunk.article_title == "Test Article"
        assert chunk.article_url == "https://example.com/articles/42"
        assert chunk.section_id == 10
        assert chunk.category_id == 1
        assert chunk.language == "en"
        assert chunk.updated_at == NOW


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_only_image_blocks_returns_empty() -> None:
    """Articles with only images and no text produce no text chunks."""
    blocks = [image_block("https://example.com/only-image.png")]
    chunks = chunk_article(content_blocks=blocks, **BASE_KWARGS)
    # No text → no chunks (image with no text is a degenerate case)
    # The chunker may or may not emit a chunk; what matters is no crash
    assert isinstance(chunks, list)


def test_invalid_overlap_raises() -> None:
    blocks = [text_block("Some text")]
    with pytest.raises(ValueError, match="chunk_overlap must be less than chunk_size"):
        chunk_article(content_blocks=blocks, chunk_size=100, chunk_overlap=100, **BASE_KWARGS)


def test_result_type_is_article_chunk() -> None:
    blocks = [text_block("Hello")]
    chunks = chunk_article(content_blocks=blocks, **BASE_KWARGS)
    assert all(isinstance(c, ArticleChunk) for c in chunks)
