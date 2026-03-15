"""Unit tests for QdrantWrapper — verifies correct delegation to AsyncQdrantClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from qdrant_client.models import Filter, PointStruct, ScoredPoint

from src.vector_db.qdrant_client import QdrantWrapper


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_async_client() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def wrapper(mock_async_client: MagicMock) -> QdrantWrapper:
    return QdrantWrapper(mock_async_client)


# ---------------------------------------------------------------------------
# search() — must delegate to query_points, not the removed .search()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_calls_query_points(
    wrapper: QdrantWrapper, mock_async_client: MagicMock
) -> None:
    """search() must use query_points (not the removed .search method)."""
    fake_point = MagicMock(spec=ScoredPoint)
    fake_point.id = "abc"
    fake_point.score = 0.95
    fake_point.payload = {"text": "hello"}

    response = MagicMock()
    response.points = [fake_point]
    mock_async_client.query_points = AsyncMock(return_value=response)

    results = await wrapper.search(
        collection_name="test_collection",
        query_vector=[0.1] * 768,
        top_k=3,
        score_threshold=0.5,
    )

    mock_async_client.query_points.assert_awaited_once_with(
        collection_name="test_collection",
        query=[0.1] * 768,
        limit=3,
        score_threshold=0.5,
        query_filter=None,
        with_payload=True,
    )
    assert len(results) == 1
    assert results[0].score == 0.95


@pytest.mark.asyncio
async def test_search_passes_query_filter(
    wrapper: QdrantWrapper, mock_async_client: MagicMock
) -> None:
    """search() must forward query_filter to query_points."""
    response = MagicMock()
    response.points = []
    mock_async_client.query_points = AsyncMock(return_value=response)

    test_filter = Filter(must=[])
    await wrapper.search(
        collection_name="col",
        query_vector=[0.0],
        query_filter=test_filter,
    )

    call_kwargs = mock_async_client.query_points.call_args.kwargs
    assert call_kwargs["query_filter"] is test_filter


@pytest.mark.asyncio
async def test_search_returns_empty_list(
    wrapper: QdrantWrapper, mock_async_client: MagicMock
) -> None:
    """search() returns empty list when no points match."""
    response = MagicMock()
    response.points = []
    mock_async_client.query_points = AsyncMock(return_value=response)

    results = await wrapper.search("col", [0.1])
    assert results == []


# ---------------------------------------------------------------------------
# upsert_points()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_points_delegates(
    wrapper: QdrantWrapper, mock_async_client: MagicMock
) -> None:
    mock_async_client.upsert = AsyncMock(return_value=None)
    points = [PointStruct(id="p1", vector=[0.1], payload={"text": "hi"})]

    await wrapper.upsert_points("col", points)

    mock_async_client.upsert.assert_awaited_once_with(
        collection_name="col", points=points
    )


# ---------------------------------------------------------------------------
# delete_by_filter()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_by_filter_delegates(
    wrapper: QdrantWrapper, mock_async_client: MagicMock
) -> None:
    mock_async_client.delete = AsyncMock(return_value=None)
    test_filter = Filter(must=[])

    await wrapper.delete_by_filter("col", test_filter)

    mock_async_client.delete.assert_awaited_once_with(
        collection_name="col", points_selector=test_filter
    )
