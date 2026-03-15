"""SyncManager: orchestrates full and delta ingestion from Zendesk."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from loguru import logger

from src.ingestion.article_processor import process_article_html
from src.ingestion.chunker import ArticleChunk, chunk_article
from src.ingestion.zendesk_client import ZendeskClient
from src.utils.language import normalize_language

if TYPE_CHECKING:
    pass


class SyncManager:
    """Orchestrates Zendesk → chunker ingestion.

    Downstream consumers (indexer) receive :class:`ArticleChunk` lists via the
    ``on_chunks`` callback so this class stays independent of vector-DB code.

    Args:
        on_chunks: Async callable that receives a list of chunks to index.
            Called once per article.
        chunk_size: Character limit per chunk (default 1 000).
        chunk_overlap: Overlap between consecutive chunks (default 200).
    """

    def __init__(
        self,
        on_chunks: SyncManager.ChunkCallback | None = None,
        chunk_size: int = 1_000,
        chunk_overlap: int = 200,
    ) -> None:
        from collections.abc import Awaitable, Callable

        ChunkCallback = Callable[[list[ArticleChunk]], Awaitable[None]]
        self._on_chunks: ChunkCallback | None = on_chunks
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    # ------------------------------------------------------------------ #
    # Public helpers                                                       #
    # ------------------------------------------------------------------ #

    async def full_ingest(self, *, dry_run: bool = False) -> dict[str, int]:
        """Ingest every article from Zendesk Help Center.

        Args:
            dry_run: When ``True``, chunks are produced but ``on_chunks`` is
                NOT called (useful for validation).

        Returns:
            Summary dict with ``articles`` and ``chunks`` counts.
        """
        logger.info("Starting full Zendesk ingestion", dry_run=dry_run)
        async with ZendeskClient() as client:
            sections = await client.get_sections()
            section_map = {s["id"]: s for s in sections}

            articles = await client.get_articles()

        total_chunks = self._process_articles(articles, section_map)
        stats = {"articles": len(articles), "chunks": sum(len(c) for c in total_chunks)}

        if not dry_run and self._on_chunks:
            for chunk_list in total_chunks:
                await self._on_chunks(chunk_list)

        logger.info(
            "Full ingestion complete",
            articles=stats["articles"],
            chunks=stats["chunks"],
            dry_run=dry_run,
        )
        return stats

    async def delta_sync(
        self,
        *,
        since: datetime | None = None,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Ingest only articles updated since *since*.

        If *since* is ``None`` the sync falls back to the last 24 hours.

        Args:
            since: Lower-bound timestamp (UTC). Defaults to 24 h ago.
            dry_run: Skip indexing callback when ``True``.

        Returns:
            Summary dict with ``articles`` and ``chunks`` counts.
        """
        if since is None:
            from datetime import timedelta

            since = datetime.now(tz=UTC) - timedelta(hours=24)

        updated_since = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        logger.info("Starting delta Zendesk sync", since=updated_since, dry_run=dry_run)

        async with ZendeskClient() as client:
            sections = await client.get_sections()
            section_map = {s["id"]: s for s in sections}
            articles = await client.get_articles(updated_since=updated_since)

        total_chunks = self._process_articles(articles, section_map)
        stats = {"articles": len(articles), "chunks": sum(len(c) for c in total_chunks)}

        if not dry_run and self._on_chunks:
            for chunk_list in total_chunks:
                await self._on_chunks(chunk_list)

        logger.info(
            "Delta sync complete",
            articles=stats["articles"],
            chunks=stats["chunks"],
            dry_run=dry_run,
        )
        return stats

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _process_articles(
        self,
        articles: list[dict],
        section_map: dict[int, dict],
    ) -> list[list[ArticleChunk]]:
        """Convert raw Zendesk article dicts to lists of :class:`ArticleChunk`."""
        results: list[list[ArticleChunk]] = []

        for article in articles:
            article_id: int = article["id"]
            body: str = article.get("body") or ""
            if not body.strip():
                logger.debug(f"Skipping empty article {article_id}")
                continue

            section_id: int | None = article.get("section_id")
            section = section_map.get(section_id) if section_id else None
            category_id: int | None = section.get("category_id") if section else None

            updated_at_raw: str = article.get("updated_at") or article.get("created_at", "")
            try:
                updated_at = datetime.fromisoformat(updated_at_raw.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                updated_at = datetime.now(tz=UTC)

            language = normalize_language(article.get("locale", "en"))

            blocks = process_article_html(body)
            chunks = chunk_article(
                article_id=article_id,
                article_title=article.get("title", ""),
                article_url=article.get("html_url", ""),
                content_blocks=blocks,
                updated_at=updated_at,
                section_id=section_id,
                category_id=category_id,
                language=language,
                chunk_size=self._chunk_size,
                chunk_overlap=self._chunk_overlap,
            )

            logger.debug(
                f"Article {article_id!r} → {len(chunks)} chunks",
                title=article.get("title"),
            )
            results.append(chunks)

        return results

    # Type alias (for documentation only; evaluated lazily)
    from collections.abc import Awaitable, Callable

    ChunkCallback = Callable[[list[ArticleChunk]], Awaitable[None]]
