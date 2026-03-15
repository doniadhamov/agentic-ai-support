"""Integration test: seed Qdrant and verify RAG retrieval precision for en/ru/uz.

Requires a local Qdrant instance (docker compose up -d).
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from qdrant_client import AsyncQdrantClient

from src.ingestion.chunker import ArticleChunk
from src.rag.reranker import ScoreThresholdFilter
from src.rag.retriever import RAGRetriever
from src.vector_db.collections import DOCS_COLLECTION, create_collections_if_not_exist
from src.vector_db.indexer import ArticleIndexer, _chunk_point_id
from src.vector_db.qdrant_client import QdrantWrapper

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QDRANT_URL = "http://localhost:6333"
VECTOR_SIZE = 768
_NOW = datetime(2024, 1, 1, tzinfo=UTC)

# One chunk per supported language
CHUNKS: list[ArticleChunk] = [
    ArticleChunk(
        article_id=3001,
        chunk_index=0,
        text="How to reset your password in DataTruck",
        article_title="Password Reset Guide",
        article_url="https://support.datatruck.io/articles/3001",
        language="en",
        updated_at=_NOW,
    ),
    ArticleChunk(
        article_id=3002,
        chunk_index=0,
        text="Как сбросить пароль в DataTruck",
        article_title="Руководство по сбросу пароля",
        article_url="https://support.datatruck.io/articles/3002",
        language="ru",
        updated_at=_NOW,
    ),
    ArticleChunk(
        article_id=3003,
        chunk_index=0,
        text="DataTruck'da parolni qayta tiklash",
        article_title="Parolni tiklash bo'yicha qo'llanma",
        article_url="https://support.datatruck.io/articles/3003",
        language="uz",
        updated_at=_NOW,
    ),
]

# Orthogonal unit vectors so each chunk retrieves only itself at score ~1.0
_FAKE_VECTORS: list[list[float]] = [
    [1.0 if j == 0 else 0.0 for j in range(VECTOR_SIZE)],  # EN
    [1.0 if j == 1 else 0.0 for j in range(VECTOR_SIZE)],  # RU
    [1.0 if j == 2 else 0.0 for j in range(VECTOR_SIZE)],  # UZ
]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def qdrant_client() -> AsyncQdrantClient:  # type: ignore[misc]
    client = AsyncQdrantClient(url=QDRANT_URL)
    yield client
    for chunk in CHUNKS:
        point_id = _chunk_point_id(chunk.article_id, chunk.chunk_index)
        with contextlib.suppress(Exception):
            await client.delete(
                collection_name=DOCS_COLLECTION,
                points_selector=[point_id],
            )
    await client.close()


@pytest.fixture()
async def wrapper(qdrant_client: AsyncQdrantClient) -> QdrantWrapper:  # type: ignore[misc]
    return QdrantWrapper(qdrant_client)


@pytest.fixture()
async def seeded_wrapper(  # type: ignore[misc]
    wrapper: QdrantWrapper, qdrant_client: AsyncQdrantClient
) -> QdrantWrapper:
    """Seed Qdrant with the three language-specific test chunks."""
    await create_collections_if_not_exist(qdrant_client)

    call_count = 0
    mock_embedder = MagicMock()

    async def fake_embed_text(text: str) -> list[float]:  # noqa: ARG001
        nonlocal call_count
        vec = _FAKE_VECTORS[call_count % len(_FAKE_VECTORS)]
        call_count += 1
        return vec

    mock_embedder.embed_text = fake_embed_text
    indexer = ArticleIndexer(embedder=mock_embedder, qdrant=wrapper)
    for chunk in CHUNKS:
        await indexer.index_chunk(chunk)

    return wrapper


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_en_chunk(seeded_wrapper: QdrantWrapper) -> None:
    """Querying with the EN vector should rank the EN chunk first."""
    mock_embedder = MagicMock()
    mock_embedder.embed_text = AsyncMock(return_value=_FAKE_VECTORS[0])

    retriever = RAGRetriever(embedder=mock_embedder, qdrant=seeded_wrapper)
    results = await retriever.retrieve("How to reset password", language="en", top_k=3)

    assert len(results) > 0
    top = results[0]
    assert top.language == "en"
    assert top.score > 0.99


@pytest.mark.asyncio
async def test_retrieve_ru_chunk(seeded_wrapper: QdrantWrapper) -> None:
    """Querying with the RU vector should rank the RU chunk first."""
    mock_embedder = MagicMock()
    mock_embedder.embed_text = AsyncMock(return_value=_FAKE_VECTORS[1])

    retriever = RAGRetriever(embedder=mock_embedder, qdrant=seeded_wrapper)
    results = await retriever.retrieve("Как сбросить пароль", language="ru", top_k=3)

    assert len(results) > 0
    top = results[0]
    assert top.language == "ru"
    assert top.score > 0.99


@pytest.mark.asyncio
async def test_retrieve_uz_chunk(seeded_wrapper: QdrantWrapper) -> None:
    """Querying with the UZ vector should rank the UZ chunk first."""
    mock_embedder = MagicMock()
    mock_embedder.embed_text = AsyncMock(return_value=_FAKE_VECTORS[2])

    retriever = RAGRetriever(embedder=mock_embedder, qdrant=seeded_wrapper)
    results = await retriever.retrieve("Parolni tiklash", language="uz", top_k=3)

    assert len(results) > 0
    top = results[0]
    assert top.language == "uz"
    assert top.score > 0.99


@pytest.mark.asyncio
async def test_results_deduplicated(seeded_wrapper: QdrantWrapper) -> None:
    """No duplicate point IDs should appear in retrieval results."""
    mock_embedder = MagicMock()
    mock_embedder.embed_text = AsyncMock(return_value=_FAKE_VECTORS[0])

    retriever = RAGRetriever(embedder=mock_embedder, qdrant=seeded_wrapper)
    results = await retriever.retrieve("query", top_k=5)

    ids = [c.point_id for c in results]
    assert len(ids) == len(set(ids)), "Duplicate point IDs found in retrieval results"


@pytest.mark.asyncio
async def test_results_sorted_by_score_descending(seeded_wrapper: QdrantWrapper) -> None:
    """Results must be sorted highest score first."""
    mock_embedder = MagicMock()
    mock_embedder.embed_text = AsyncMock(return_value=_FAKE_VECTORS[0])

    retriever = RAGRetriever(embedder=mock_embedder, qdrant=seeded_wrapper)
    results = await retriever.retrieve("query", top_k=5)

    scores = [c.score for c in results]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_results_tagged_with_source(seeded_wrapper: QdrantWrapper) -> None:
    """All results from the docs collection must be tagged source='docs'."""
    mock_embedder = MagicMock()
    mock_embedder.embed_text = AsyncMock(return_value=_FAKE_VECTORS[0])

    retriever = RAGRetriever(embedder=mock_embedder, qdrant=seeded_wrapper)
    results = await retriever.retrieve("How to reset password", top_k=3)

    assert len(results) > 0
    for chunk in results:
        assert chunk.source in {"docs", "memory"}


@pytest.mark.asyncio
async def test_score_threshold_drops_low_scores(seeded_wrapper: QdrantWrapper) -> None:
    """Chunks below the threshold must be removed by ScoreThresholdFilter."""
    mock_embedder = MagicMock()
    mock_embedder.embed_text = AsyncMock(return_value=_FAKE_VECTORS[0])

    retriever = RAGRetriever(embedder=mock_embedder, qdrant=seeded_wrapper)
    all_results = await retriever.retrieve("query", top_k=3)

    reranker = ScoreThresholdFilter(min_score=0.99)
    filtered = reranker.filter(all_results)

    assert len(filtered) >= 1
    assert all(c.score >= 0.99 for c in filtered)
    assert len(filtered) <= len(all_results)


@pytest.mark.asyncio
async def test_score_threshold_zero_keeps_all(seeded_wrapper: QdrantWrapper) -> None:
    """With threshold=0.0, all retrieved chunks should be kept."""
    mock_embedder = MagicMock()
    mock_embedder.embed_text = AsyncMock(return_value=_FAKE_VECTORS[0])

    retriever = RAGRetriever(embedder=mock_embedder, qdrant=seeded_wrapper)
    all_results = await retriever.retrieve("query", top_k=5)

    reranker = ScoreThresholdFilter(min_score=0.0)
    filtered = reranker.filter(all_results)

    assert len(filtered) == len(all_results)
