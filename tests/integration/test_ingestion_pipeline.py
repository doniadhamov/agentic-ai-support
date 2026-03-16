"""Integration test: ingest 3 chunks into Qdrant and verify retrieval.

Requires a local Qdrant instance (docker compose up -d).
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from qdrant_client import AsyncQdrantClient

from src.ingestion.chunker import ArticleChunk
from src.vector_db.collections import DOCS_COLLECTION, create_collections_if_not_exist
from src.vector_db.indexer import ArticleIndexer, _chunk_point_id
from src.vector_db.qdrant_client import QdrantWrapper

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

QDRANT_URL = "http://localhost:6333"
VECTOR_SIZE = 768

_NOW = datetime(2024, 1, 1, tzinfo=UTC)

CHUNKS: list[ArticleChunk] = [
    ArticleChunk(
        article_id=1001,
        chunk_index=0,
        text="How to reset your password in DataTruck",
        article_title="Password Reset Guide",
        article_url="https://support.datatruck.io/articles/1001",
        language="en",
        updated_at=_NOW,
    ),
    ArticleChunk(
        article_id=1001,
        chunk_index=1,
        text="Navigate to the login page and click Forgot Password",
        article_title="Password Reset Guide",
        article_url="https://support.datatruck.io/articles/1001",
        language="en",
        updated_at=_NOW,
    ),
    ArticleChunk(
        article_id=1002,
        chunk_index=0,
        text="Как отслеживать доставку в DataTruck",
        article_title="Отслеживание доставки",
        article_url="https://support.datatruck.io/articles/1002",
        language="ru",
        updated_at=_NOW,
    ),
]

# Deterministic fake vectors — one per chunk (768-dim unit vectors are not
# required for this test; any floats work with a local cosine collection).
_FAKE_VECTORS: list[list[float]] = [
    [0.1] * VECTOR_SIZE,
    [0.2] * VECTOR_SIZE,
    [0.9] * VECTOR_SIZE,
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def qdrant_client() -> AsyncQdrantClient:  # type: ignore[misc]
    client = AsyncQdrantClient(url=QDRANT_URL)
    yield client
    # Cleanup: remove test points inserted during the test
    for chunk in CHUNKS:
        point_id = _chunk_point_id(chunk.article_id, chunk.chunk_index)
        with contextlib.suppress(Exception):
            await client.delete(
                collection_name=DOCS_COLLECTION,
                points_selector=[point_id],
            )
    await client.close()


@pytest.fixture()
async def wrapper(qdrant_client: AsyncQdrantClient) -> QdrantWrapper:
    return QdrantWrapper(qdrant_client)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_and_retrieve(
    wrapper: QdrantWrapper, qdrant_client: AsyncQdrantClient
) -> None:
    """Ingest 3 chunks with mock embeddings and verify retrieval by vector search."""
    await create_collections_if_not_exist(qdrant_client)

    # Build mock embedder that returns our deterministic vectors
    embedder = MagicMock()
    call_count = 0

    async def fake_embed_text(text: str) -> list[float]:
        nonlocal call_count
        vec = _FAKE_VECTORS[call_count % len(_FAKE_VECTORS)]
        call_count += 1
        return vec

    embedder.embed_text = fake_embed_text

    indexer = ArticleIndexer(embedder=embedder, qdrant=wrapper)

    # Index all 3 chunks
    for chunk in CHUNKS:
        await indexer.index_chunk(chunk)

    # Verify each chunk can be retrieved by its own vector (score should be ~1.0)
    for i, chunk in enumerate(CHUNKS):
        results = await wrapper.search(
            collection_name=DOCS_COLLECTION,
            query_vector=_FAKE_VECTORS[i],
            top_k=1,
        )
        assert len(results) >= 1, f"No results returned for chunk {i}"
        top = results[0]
        assert top.payload is not None
        assert top.payload["article_id"] == chunk.article_id
        assert top.payload["chunk_index"] == chunk.chunk_index
        assert top.payload["language"] == chunk.language
        assert top.score > 0.99, f"Expected near-perfect score, got {top.score}"


@pytest.mark.asyncio
async def test_point_ids_are_deterministic() -> None:
    """UUID5 IDs must be stable across calls."""
    id_a = _chunk_point_id(1001, 0)
    id_b = _chunk_point_id(1001, 0)
    id_c = _chunk_point_id(1001, 1)

    assert id_a == id_b
    assert id_a != id_c
    # Must be valid UUID strings
    uuid.UUID(id_a)
    uuid.UUID(id_c)
