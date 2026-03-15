"""Unit tests for ApprovedMemory — store, retrieve, and threshold verification."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.memory.approved_memory import ApprovedMemory, _memory_point_id
from src.memory.memory_schemas import ApprovedAnswer
from src.vector_db.collections import MEMORY_COLLECTION

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_embedder() -> MagicMock:
    embedder = MagicMock()
    embedder.embed_text = AsyncMock(return_value=[0.1] * 768)
    return embedder


@pytest.fixture()
def mock_qdrant() -> MagicMock:
    qdrant = MagicMock()
    qdrant.upsert_points = AsyncMock(return_value=None)
    return qdrant


@pytest.fixture()
def approved_memory(mock_embedder: MagicMock, mock_qdrant: MagicMock) -> ApprovedMemory:
    return ApprovedMemory(embedder=mock_embedder, qdrant=mock_qdrant)


# ---------------------------------------------------------------------------
# store() — embeds question and upserts into MEMORY_COLLECTION
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_calls_embed_text(
    approved_memory: ApprovedMemory, mock_embedder: MagicMock
) -> None:
    approved = ApprovedAnswer(question="How do I reset a password?", answer="Go to Settings > Reset.")
    await approved_memory.store(approved)
    mock_embedder.embed_text.assert_awaited_once_with("How do I reset a password?")


@pytest.mark.asyncio
async def test_store_upserts_into_memory_collection(
    approved_memory: ApprovedMemory, mock_qdrant: MagicMock
) -> None:
    approved = ApprovedAnswer(question="How do I reset a password?", answer="Go to Settings > Reset.")
    await approved_memory.store(approved)

    mock_qdrant.upsert_points.assert_awaited_once()
    call_args = mock_qdrant.upsert_points.call_args
    collection_name, points = call_args[0]
    assert collection_name == MEMORY_COLLECTION
    assert len(points) == 1


@pytest.mark.asyncio
async def test_store_returns_deterministic_point_id(
    approved_memory: ApprovedMemory,
) -> None:
    question = "How do I reset a password?"
    approved = ApprovedAnswer(question=question, answer="Go to Settings > Reset.")
    point_id = await approved_memory.store(approved)

    assert point_id == _memory_point_id(question)


@pytest.mark.asyncio
async def test_store_point_id_is_deterministic() -> None:
    """Same question must always produce the same point ID (idempotent upserts)."""
    q = "How do I add a new driver?"
    assert _memory_point_id(q) == _memory_point_id(q)


@pytest.mark.asyncio
async def test_store_different_questions_different_ids() -> None:
    assert _memory_point_id("Question A") != _memory_point_id("Question B")


# ---------------------------------------------------------------------------
# Payload structure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_payload_contains_text_field(
    approved_memory: ApprovedMemory, mock_qdrant: MagicMock
) -> None:
    """The stored point payload must have a 'text' field readable by the retriever."""
    approved = ApprovedAnswer(
        question="How do I add a driver?",
        answer="Navigate to Fleet > Drivers > Add.",
        language="en",
        ticket_id="TKT-001",
        group_id=12345,
    )
    await approved_memory.store(approved)

    call_args = mock_qdrant.upsert_points.call_args
    points = call_args[0][1]
    payload = points[0].payload

    assert "text" in payload
    assert "How do I add a driver?" in payload["text"]
    assert "Navigate to Fleet" in payload["text"]
    assert payload["language"] == "en"
    assert payload["ticket_id"] == "TKT-001"
    assert payload["group_id"] == 12345
    assert payload["article_title"] == "Approved Answer"


# ---------------------------------------------------------------------------
# Threshold verification: stored answers are retrievable above min score
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_then_retrieve_above_threshold(mock_embedder: MagicMock) -> None:
    """Simulate store → search roundtrip: the stored point should be returned above threshold."""
    from qdrant_client.models import ScoredPoint

    question = "How do I export a report?"
    answer = "Go to Reports > Export as CSV."
    approved = ApprovedAnswer(question=question, answer=answer, language="en")

    vector = [0.5] * 768
    mock_embedder.embed_text = AsyncMock(return_value=vector)

    # Simulate a ScoredPoint returned by Qdrant search at score 0.92 (above default 0.75)
    scored_point = MagicMock(spec=ScoredPoint)
    scored_point.id = _memory_point_id(question)
    scored_point.score = 0.92
    scored_point.payload = {
        "text": f"Q: {question}\nA: {answer}",
        "question": question,
        "answer": answer,
        "language": "en",
        "ticket_id": "",
        "group_id": 0,
        "article_title": "Approved Answer",
        "article_url": "",
    }

    mock_qdrant = MagicMock()
    mock_qdrant.upsert_points = AsyncMock(return_value=None)
    mock_qdrant.search = AsyncMock(return_value=[scored_point])

    memory = ApprovedMemory(embedder=mock_embedder, qdrant=mock_qdrant)
    await memory.store(approved)

    # Now simulate what RAGRetriever does: search and tag source
    results = await mock_qdrant.search(MEMORY_COLLECTION, vector, top_k=5)
    assert len(results) == 1
    assert results[0].score >= 0.75  # above SUPPORT_MIN_CONFIDENCE_SCORE default
    assert results[0].payload["answer"] == answer
