"""Unit tests for file ingestion orchestrator — mock embedder + indexer."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.admin.file_ingest import _generate_article_id, ingest_file


class TestGenerateArticleId:
    def test_deterministic(self) -> None:
        id1 = _generate_article_id("test.pdf")
        id2 = _generate_article_id("test.pdf")
        assert id1 == id2

    def test_different_files_different_ids(self) -> None:
        id1 = _generate_article_id("file_a.pdf")
        id2 = _generate_article_id("file_b.pdf")
        assert id1 != id2

    def test_offset_applied(self) -> None:
        article_id = _generate_article_id("anything.txt")
        assert article_id >= 10_000_000


class TestIngestFile:
    @pytest.mark.asyncio
    async def test_ingest_text_file(self) -> None:
        mock_indexer = AsyncMock()
        mock_embedder = AsyncMock()
        mock_qdrant = AsyncMock()

        with (
            patch("src.admin.file_ingest.GeminiEmbedder", return_value=mock_embedder),
            patch("src.admin.file_ingest.get_qdrant_client", return_value=mock_qdrant),
            patch("src.admin.file_ingest.ArticleIndexer", return_value=mock_indexer),
        ):
            result = await ingest_file("test.txt", b"Some test content for ingestion.")

        assert result.filename == "test.txt"
        assert result.chunks >= 1
        assert result.article_id >= 10_000_000
        mock_indexer.index_chunks.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ingest_empty_file_raises(self) -> None:
        with pytest.raises(ValueError, match="No content"):
            await ingest_file("empty.txt", b"")

    @pytest.mark.asyncio
    async def test_ingest_unsupported_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported file type"):
            await ingest_file("data.csv", b"a,b,c")
