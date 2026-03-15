"""RAG retriever: embed query, search both Qdrant collections, merge results."""

from __future__ import annotations

import asyncio

from loguru import logger
from pydantic import BaseModel, Field

from src.config.settings import get_settings
from src.embeddings.gemini_embedder import GeminiEmbedder
from src.rag.query_builder import build_query
from src.vector_db.collections import DOCS_COLLECTION, MEMORY_COLLECTION
from src.vector_db.qdrant_client import QdrantWrapper


class RetrievedChunk(BaseModel):
    """A retrieved chunk with its metadata and source collection tag."""

    point_id: str = Field(..., description="Qdrant point ID")
    score: float = Field(..., description="Cosine similarity score")
    text: str = Field(..., description="Chunk text content")
    article_title: str = Field(default="", description="Source article title")
    article_url: str = Field(default="", description="Source article URL")
    image_url: str | None = Field(default=None, description="Associated image URL")
    language: str = Field(default="en", description="Language code of the chunk")
    source: str = Field(
        default="docs",
        description="Source collection: 'docs' (Zendesk) or 'memory' (approved Q&A)",
    )


class RAGRetriever:
    """Retrieves top-k relevant chunks from ``datatruck_docs`` and ``datatruck_memory``."""

    def __init__(self, embedder: GeminiEmbedder, qdrant: QdrantWrapper) -> None:
        self._embedder = embedder
        self._qdrant = qdrant

    async def retrieve(
        self,
        question: str,
        language: str = "en",
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        """Embed *question* and search both collections concurrently.

        Results from the two collections are merged and deduplicated by point ID,
        then sorted by descending similarity score.

        Args:
            question: The cleaned standalone question.
            language: Language code (en/ru/uz) used by the query builder.
            top_k: Max results per collection. Defaults to ``settings.rag_top_k``.

        Returns:
            Deduplicated list of :class:`RetrievedChunk`, highest score first.
        """
        settings = get_settings()
        k = top_k if top_k is not None else settings.rag_top_k

        query = build_query(question, language)
        logger.debug("Retrieving top-{} chunks for query '{}' (lang={})", k, query[:80], language)

        vector = await self._embedder.embed_query(query)

        docs_results, memory_results = await asyncio.gather(
            self._qdrant.search(DOCS_COLLECTION, vector, top_k=k),
            self._qdrant.search(MEMORY_COLLECTION, vector, top_k=k),
        )

        seen: set[str] = set()
        chunks: list[RetrievedChunk] = []

        for scored_point, source in [
            *[(sp, "docs") for sp in docs_results],
            *[(sp, "memory") for sp in memory_results],
        ]:
            pid = str(scored_point.id)
            if pid in seen:
                continue
            seen.add(pid)

            payload = scored_point.payload or {}
            chunks.append(
                RetrievedChunk(
                    point_id=pid,
                    score=scored_point.score,
                    text=payload.get("text", ""),
                    article_title=payload.get("article_title", ""),
                    article_url=payload.get("article_url", ""),
                    image_url=payload.get("image_url"),
                    language=payload.get("language", language),
                    source=source,
                )
            )

        chunks.sort(key=lambda c: c.score, reverse=True)
        logger.info(
            "Retrieved {} chunk(s) ({} docs, {} memory)",
            len(chunks),
            sum(1 for c in chunks if c.source == "docs"),
            sum(1 for c in chunks if c.source == "memory"),
        )
        return chunks
