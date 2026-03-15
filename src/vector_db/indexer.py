"""ArticleIndexer — embed an ArticleChunk and upsert it into Qdrant."""

from __future__ import annotations

import uuid
from datetime import timezone

from loguru import logger
from qdrant_client.models import PointStruct

from src.embeddings.gemini_embedder import GeminiEmbedder
from src.ingestion.chunker import ArticleChunk
from src.ingestion.image_downloader import ImageDownloader
from src.vector_db.collections import DOCS_COLLECTION
from src.vector_db.qdrant_client import QdrantWrapper

# UUID5 namespace for deterministic point IDs
_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # uuid.NAMESPACE_URL


def _chunk_point_id(article_id: int, chunk_index: int) -> str:
    """Generate a deterministic UUID5 string for a chunk.

    Args:
        article_id: Zendesk article ID.
        chunk_index: Zero-based chunk position within the article.

    Returns:
        UUID5 string suitable as a Qdrant point ID.
    """
    return str(uuid.uuid5(_NAMESPACE, f"{article_id}_{chunk_index}"))


class ArticleIndexer:
    """Embeds :class:`ArticleChunk` objects and upserts them into Qdrant."""

    def __init__(
        self,
        embedder: GeminiEmbedder,
        qdrant: QdrantWrapper,
        image_downloader: ImageDownloader | None = None,
    ) -> None:
        self._embedder = embedder
        self._qdrant = qdrant
        self._image_downloader = image_downloader

    async def index_chunk(self, chunk: ArticleChunk) -> None:
        """Embed a single chunk and upsert it into the docs collection.

        If the chunk has an associated image URL, a multimodal embedding is
        produced; otherwise a text-only embedding is used.

        Args:
            chunk: The :class:`ArticleChunk` to index.
        """
        image_bytes: bytes | None = None
        if chunk.image_url and self._image_downloader:
            try:
                image_bytes = await self._image_downloader.download(chunk.image_url)
            except Exception as exc:
                logger.warning("Failed to download image {}: {}", chunk.image_url, exc)

        if image_bytes:
            vector = await self._embedder.embed_multimodal(chunk.text, image_bytes)
        else:
            vector = await self._embedder.embed_text(chunk.text)

        point_id = _chunk_point_id(chunk.article_id, chunk.chunk_index)
        payload = {
            "article_id": chunk.article_id,
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "image_url": chunk.image_url,
            "article_title": chunk.article_title,
            "article_url": chunk.article_url,
            "section_id": chunk.section_id,
            "category_id": chunk.category_id,
            "language": chunk.language,
            "updated_at": chunk.updated_at.astimezone(timezone.utc).isoformat(),
        }

        point = PointStruct(id=point_id, vector=vector, payload=payload)
        await self._qdrant.upsert_points(DOCS_COLLECTION, [point])
        logger.info(
            "Indexed chunk {}/{} for article {} ({})",
            chunk.chunk_index,
            chunk.article_id,
            chunk.article_title,
            point_id,
        )

    async def index_chunks(self, chunks: list[ArticleChunk]) -> None:
        """Index multiple chunks sequentially.

        Args:
            chunks: List of :class:`ArticleChunk` objects to index.
        """
        for chunk in chunks:
            await self.index_chunk(chunk)
