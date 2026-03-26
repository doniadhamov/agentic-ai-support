"""RAG retriever: embed query, search both Qdrant collections, merge results."""

from __future__ import annotations

import asyncio

from loguru import logger
from pydantic import BaseModel, Field
from qdrant_client.models import FieldCondition, Filter, MatchValue

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
    chunk_index: int = Field(default=0, description="Chunk position within the article")
    article_id: int | None = Field(default=None, description="Source article ID")
    source: str = Field(
        default="docs",
        description="Source collection: 'docs' (Zendesk) or 'memory' (approved Q&A)",
    )


class RAGRetriever:
    """Retrieves top-k relevant chunks from ``datatruck_docs`` and ``datatruck_memory``."""

    def __init__(self, embedder: GeminiEmbedder, qdrant: QdrantWrapper) -> None:
        self._embedder = embedder
        self._qdrant = qdrant

    async def _expand_sibling_chunks(
        self,
        chunks: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """Fetch all sibling chunks from the same articles as the retrieved docs chunks.

        When a chunk from ``datatruck_docs`` is retrieved, this method fetches all
        other chunks belonging to the same ``article_id`` so the full article content
        is available to the generator.

        Sibling chunks inherit the best score of the initially retrieved chunk from
        their article, and are ordered by ``chunk_index`` within each article group.
        """
        # Collect unique article_ids from docs chunks that were retrieved
        article_scores: dict[int, float] = {}
        for chunk in chunks:
            if chunk.source == "docs" and chunk.article_id is not None:
                if (
                    chunk.article_id not in article_scores
                    or chunk.score > article_scores[chunk.article_id]
                ):
                    article_scores[chunk.article_id] = chunk.score

        if not article_scores:
            return chunks

        # Fetch sibling chunks for each article concurrently
        async def _fetch_siblings(article_id: int) -> list[RetrievedChunk]:
            scroll_filter = Filter(
                must=[FieldCondition(key="article_id", match=MatchValue(value=article_id))]
            )
            records = await self._qdrant.scroll_by_filter(
                DOCS_COLLECTION, scroll_filter=scroll_filter
            )
            best_score = article_scores[article_id]
            siblings: list[RetrievedChunk] = []
            for record in records:
                payload = record.payload or {}
                siblings.append(
                    RetrievedChunk(
                        point_id=str(record.id),
                        score=best_score,
                        text=payload.get("text", ""),
                        article_title=payload.get("article_title", ""),
                        article_url=payload.get("article_url", ""),
                        image_url=payload.get("image_url"),
                        language=payload.get("language", "en"),
                        chunk_index=payload.get("chunk_index", 0),
                        article_id=payload.get("article_id"),
                        source="docs",
                    )
                )
            siblings.sort(key=lambda c: c.chunk_index)
            return siblings

        sibling_tasks = [_fetch_siblings(aid) for aid in article_scores]
        sibling_results = await asyncio.gather(*sibling_tasks)

        # Build the expanded chunk list: docs chunks replaced by full article chunks,
        # memory chunks preserved as-is
        seen_point_ids: set[str] = set()
        expanded: list[RetrievedChunk] = []

        # First add all expanded article chunks (ordered by article score desc, then chunk_index)
        article_groups: list[tuple[float, list[RetrievedChunk]]] = []
        for siblings in sibling_results:
            if siblings:
                article_groups.append((siblings[0].score, siblings))
        article_groups.sort(key=lambda g: g[0], reverse=True)

        for _score, siblings in article_groups:
            for chunk in siblings:
                if chunk.point_id not in seen_point_ids:
                    seen_point_ids.add(chunk.point_id)
                    expanded.append(chunk)

        # Then add memory chunks
        for chunk in chunks:
            if chunk.source == "memory" and chunk.point_id not in seen_point_ids:
                seen_point_ids.add(chunk.point_id)
                expanded.append(chunk)

        logger.info(
            "Sibling expansion: {} article(s) expanded, {} → {} chunk(s)",
            len(article_scores),
            len(chunks),
            len(expanded),
        )
        return expanded

    async def retrieve(
        self,
        question: str,
        language: str = "en",
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        """Embed *question* and search both collections concurrently.

        Results from the two collections are merged and deduplicated by point ID,
        then sorted by descending similarity score. Docs chunks are then expanded
        to include all sibling chunks from the same article so multi-step articles
        are returned in full.

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
                    chunk_index=payload.get("chunk_index", 0),
                    article_id=payload.get("article_id"),
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

        # Expand docs chunks to include all sibling chunks from the same articles
        chunks = await self._expand_sibling_chunks(chunks)

        return chunks
