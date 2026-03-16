"""File upload ingestion — parse, chunk, embed, and index uploaded files."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from src.admin.schemas import IngestResult
from src.embeddings.gemini_embedder import GeminiEmbedder
from src.ingestion.chunker import chunk_article
from src.ingestion.file_parser import parse_file
from src.vector_db.indexer import ArticleIndexer
from src.vector_db.qdrant_client import get_qdrant_client

# Offset to avoid collision with Zendesk article IDs
_UPLOAD_ID_OFFSET = 10_000_000


def _generate_article_id(filename: str) -> int:
    """Generate a deterministic article ID from the filename.

    Uses a hash-based approach with an offset to avoid collisions
    with Zendesk article IDs.
    """
    digest = hashlib.sha256(filename.encode()).hexdigest()
    return _UPLOAD_ID_OFFSET + (int(digest[:8], 16) % 10_000_000)


async def ingest_file(filename: str, content: bytes) -> IngestResult:
    """Parse an uploaded file and ingest it into the Qdrant docs collection.

    Args:
        filename: Original filename (used for format detection and article title).
        content: Raw file bytes.

    Returns:
        :class:`IngestResult` with chunk count and article ID.

    Raises:
        ValueError: If the file type is not supported or content is empty.
    """
    blocks = parse_file(filename, content)
    if not blocks:
        raise ValueError(f"No content extracted from {filename}")

    article_id = _generate_article_id(filename)
    article_title = Path(filename).stem

    chunks = chunk_article(
        article_id=article_id,
        article_title=article_title,
        article_url="",
        content_blocks=blocks,
        updated_at=datetime.now(tz=UTC),
    )

    if not chunks:
        raise ValueError(f"Chunker produced no chunks from {filename}")

    embedder = GeminiEmbedder()
    qdrant = get_qdrant_client()
    indexer = ArticleIndexer(embedder=embedder, qdrant=qdrant)
    await indexer.index_chunks(chunks)

    logger.info(
        "Ingested file {!r}: article_id={} chunks={}",
        filename,
        article_id,
        len(chunks),
    )
    return IngestResult(
        filename=filename,
        article_id=article_id,
        chunks=len(chunks),
    )
