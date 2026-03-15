"""Qdrant collection constants and initialisation helpers."""

from __future__ import annotations

from loguru import logger
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams

DOCS_COLLECTION = "datatruck_docs"
MEMORY_COLLECTION = "datatruck_memory"

VECTOR_SIZE = 3072
DISTANCE = Distance.COSINE

_COLLECTIONS = (DOCS_COLLECTION, MEMORY_COLLECTION)


async def create_collections_if_not_exist(client: AsyncQdrantClient) -> None:
    """Ensure both Qdrant collections exist, creating them if needed.

    Args:
        client: An initialised :class:`AsyncQdrantClient` instance.
    """
    existing = {c.name for c in (await client.get_collections()).collections}

    for name in _COLLECTIONS:
        if name in existing:
            logger.debug("Collection '{}' already exists — skipping creation", name)
            continue

        await client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=DISTANCE),
        )
        logger.info("Created Qdrant collection '{}'", name)
