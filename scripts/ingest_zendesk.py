#!/usr/bin/env python
"""CLI: full Zendesk Help Center ingestion.

Usage
-----
    uv run python scripts/ingest_zendesk.py            # full ingest
    uv run python scripts/ingest_zendesk.py --dry-run  # validate only (no writes)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow running from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from src.embeddings.gemini_embedder import GeminiEmbedder
from src.ingestion.image_downloader import ImageDownloader
from src.ingestion.sync_manager import SyncManager
from src.utils.logging import setup_logging
from src.vector_db.collections import create_collections_if_not_exist
from src.vector_db.indexer import ArticleIndexer
from src.vector_db.qdrant_client import get_qdrant_client


async def main(dry_run: bool) -> None:
    setup_logging()

    if dry_run:
        logger.info("DRY-RUN mode — no chunks will be indexed")
        manager = SyncManager(on_chunks=None)
        stats = await manager.full_ingest(dry_run=dry_run)
    else:
        qdrant = get_qdrant_client()
        await create_collections_if_not_exist(qdrant._client)
        embedder = GeminiEmbedder()
        async with ImageDownloader() as image_downloader:
            indexer = ArticleIndexer(embedder, qdrant, image_downloader)
            manager = SyncManager(on_chunks=indexer.index_chunks)
            stats = await manager.full_ingest(dry_run=dry_run)

    logger.info(
        "Ingestion finished",
        articles=stats["articles"],
        chunks=stats["chunks"],
        dry_run=dry_run,
    )
    print(
        f"\nDone — {stats['articles']} articles, {stats['chunks']} chunks "
        f"({'dry-run' if dry_run else 'indexed'})"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest Zendesk Help Center articles into Qdrant")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Process articles and produce chunks but do NOT write to Qdrant",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(dry_run=args.dry_run))
