"""Retrieve node — RAG search from docs + learned answers."""

from __future__ import annotations

import time

from loguru import logger

from src.agent.state import SupportState
from src.config.settings import get_settings
from src.embeddings.gemini_embedder import GeminiEmbedder
from src.rag.reranker import ScoreThresholdFilter
from src.rag.retriever import RAGRetriever
from src.vector_db.qdrant_client import get_qdrant_client


async def retrieve_node(state: SupportState) -> dict:
    """Search docs + learned memory for the extracted question."""
    t0 = time.monotonic()
    settings = get_settings()

    question = state.get("extracted_question") or state.get("raw_text", "")
    language = state.get("language", "en")

    if not question:
        logger.warning("retrieve: no question to search for")
        return {
            "retrieved_docs": [],
            "retrieval_confidence": 0.0,
            "recent_image_bytes": state.get("images", []),
            "retrieve_ms": 0,
        }

    # Use existing RAG infrastructure
    embedder = GeminiEmbedder()
    qdrant = get_qdrant_client()
    retriever = RAGRetriever(embedder=embedder, qdrant=qdrant)
    reranker = ScoreThresholdFilter(min_score=settings.support_min_confidence_score)

    # Retrieve and filter
    chunks = await retriever.retrieve(
        question=question, language=language, top_k=settings.rag_top_k
    )
    filtered = reranker.filter(chunks)

    # Convert to serializable dicts
    retrieved_docs = [
        {
            "point_id": c.point_id,
            "score": c.score,
            "text": c.text,
            "article_title": c.article_title,
            "article_url": c.article_url,
            "image_url": c.image_url,
            "language": c.language,
            "chunk_index": c.chunk_index,
            "article_id": c.article_id,
            "source": c.source,
        }
        for c in filtered
    ]

    retrieval_confidence = max((c.score for c in filtered), default=0.0)

    # Images: use current message images (already in state)
    # Phase 2+ can download recent file_ids from conversation_history
    recent_image_bytes = state.get("images", [])

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "retrieve: {} chunks (confidence={:.3f}) elapsed={}ms",
        len(retrieved_docs),
        retrieval_confidence,
        elapsed_ms,
    )

    return {
        "retrieved_docs": retrieved_docs,
        "retrieval_confidence": retrieval_confidence,
        "recent_image_bytes": recent_image_bytes,
        "retrieve_ms": elapsed_ms,
    }
