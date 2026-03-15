#!/usr/bin/env python
"""CLI: delta sync Zendesk Help Center articles updated in the last N hours.

Usage
-----
    uv run python scripts/sync_zendesk.py                    # sync last 24 h
    uv run python scripts/sync_zendesk.py --hours 6          # sync last 6 h
    uv run python scripts/sync_zendesk.py --dry-run          # validate only (no writes)
    uv run python scripts/sync_zendesk.py --hours 6 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Allow running from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from src.ingestion.chunker import ArticleChunk
from src.ingestion.sync_manager import SyncManager
from src.utils.logging import setup_logging


async def _index_chunks(chunks: list[ArticleChunk]) -> None:
    """Index chunks into Qdrant via ArticleIndexer."""
    from src.embeddings.gemini_embedder import GeminiEmbedder
    from src.vector_db.indexer import ArticleIndexer
    from src.vector_db.qdrant_client import get_qdrant_client

    embedder = GeminiEmbedder()
    qdrant = get_qdrant_client()
    indexer = ArticleIndexer(embedder=embedder, qdrant=qdrant)

    for chunk in chunks:
        await indexer.index_chunk(chunk)

    logger.debug("Indexed {} chunk(s) for article {}", len(chunks), chunks[0].article_id)


async def main(hours: int, dry_run: bool) -> None:
    setup_logging()

    since = datetime.now(tz=UTC) - timedelta(hours=hours)

    if dry_run:
        logger.info("DRY-RUN mode — no chunks will be indexed")

    on_chunks = None if dry_run else _index_chunks
    manager = SyncManager(on_chunks=on_chunks)
    stats = await manager.delta_sync(since=since, dry_run=dry_run)

    print(
        f"\nDelta sync complete — {stats['articles']} article(s), "
        f"{stats['chunks']} chunk(s) "
        f"({'dry-run' if dry_run else 'indexed'}, last {hours}h)"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delta-sync Zendesk Help Center articles into Qdrant"
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        metavar="N",
        help="Sync articles updated in the last N hours (default: 24)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Process articles and produce chunks but do NOT write to Qdrant",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(hours=args.hours, dry_run=args.dry_run))
