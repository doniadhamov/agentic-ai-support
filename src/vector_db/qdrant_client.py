"""Async Qdrant wrapper with upsert, search, and delete operations."""

from __future__ import annotations

from functools import lru_cache

from loguru import logger
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Filter, PointStruct, ScoredPoint
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.settings import get_settings


class QdrantWrapper:
    """Thin async wrapper around :class:`AsyncQdrantClient` with tenacity retries."""

    def __init__(self, client: AsyncQdrantClient) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def upsert_points(self, collection_name: str, points: list[PointStruct]) -> None:
        """Upsert a batch of points into the given collection.

        Args:
            collection_name: Target collection name.
            points: List of :class:`PointStruct` objects to upsert.
        """
        await self._client.upsert(collection_name=collection_name, points=points)
        logger.debug("Upserted {} point(s) into '{}'", len(points), collection_name)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def delete_by_filter(self, collection_name: str, points_filter: Filter) -> None:
        """Delete all points matching the given filter.

        Args:
            collection_name: Target collection name.
            points_filter: Qdrant :class:`Filter` expression.
        """
        await self._client.delete(collection_name=collection_name, points_selector=points_filter)
        logger.debug("Deleted points from '{}' matching filter", collection_name)

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def search(
        self,
        collection_name: str,
        query_vector: list[float],
        top_k: int = 5,
        score_threshold: float | None = None,
        query_filter: Filter | None = None,
    ) -> list[ScoredPoint]:
        """Perform a nearest-neighbour search.

        Args:
            collection_name: Collection to search.
            query_vector: Query embedding vector.
            top_k: Maximum number of results to return.
            score_threshold: Optional minimum similarity score.
            query_filter: Optional Qdrant filter to apply.

        Returns:
            Ordered list of :class:`ScoredPoint` (highest score first).
        """
        results = await self._client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=top_k,
            score_threshold=score_threshold,
            query_filter=query_filter,
            with_payload=True,
        )
        logger.debug("Search in '{}' returned {} result(s)", collection_name, len(results))
        return results


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantWrapper:
    """Return a singleton :class:`QdrantWrapper` configured from settings."""
    settings = get_settings()
    kwargs: dict[str, object] = {"url": settings.qdrant_url}
    if settings.qdrant_api_key:
        kwargs["api_key"] = settings.qdrant_api_key
    return QdrantWrapper(AsyncQdrantClient(**kwargs))
