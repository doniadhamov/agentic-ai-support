"""CLI script: print Qdrant collection stats."""

from __future__ import annotations

import asyncio

from loguru import logger
from qdrant_client import AsyncQdrantClient

from src.config.settings import get_settings
from src.utils.logging import setup_logging
from src.vector_db.collections import DOCS_COLLECTION, MEMORY_COLLECTION


async def main() -> None:
    setup_logging()
    settings = get_settings()

    kwargs: dict[str, object] = {"url": settings.qdrant_url}
    if settings.qdrant_api_key:
        kwargs["api_key"] = settings.qdrant_api_key

    client = AsyncQdrantClient(**kwargs)

    try:
        collections_response = await client.get_collections()
        existing = {c.name for c in collections_response.collections}

        for name in (DOCS_COLLECTION, MEMORY_COLLECTION):
            if name not in existing:
                logger.info("Collection '{}' does not exist", name)
                continue

            info = await client.get_collection(name)
            count = await client.count(collection_name=name)
            logger.info(
                "Collection '{}': {} points | status={} | vector_size={} | distance={}",
                name,
                count.count,
                info.status,
                info.config.params.vectors.size,
                info.config.params.vectors.distance,
            )
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
