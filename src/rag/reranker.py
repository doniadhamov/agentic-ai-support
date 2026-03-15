"""Score threshold filter: drop low-confidence chunks after retrieval."""

from __future__ import annotations

from loguru import logger

from src.config.settings import get_settings
from src.rag.retriever import RetrievedChunk


class ScoreThresholdFilter:
    """Filters retrieved chunks to those at or above a minimum confidence score.

    Source tags (``'docs'`` / ``'memory'``) are already set by
    :class:`~src.rag.retriever.RAGRetriever` and are preserved as-is.
    """

    def __init__(self, min_score: float | None = None) -> None:
        settings = get_settings()
        self._min_score = (
            min_score if min_score is not None else settings.support_min_confidence_score
        )

    def filter(self, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Remove chunks whose similarity score falls below the threshold.

        Args:
            chunks: Retrieved chunks (already tagged with ``source``).

        Returns:
            Filtered list preserving the original order (highest score first
            when the input comes from :meth:`RAGRetriever.retrieve`).
        """
        filtered = [c for c in chunks if c.score >= self._min_score]
        dropped = len(chunks) - len(filtered)
        if dropped:
            logger.debug(
                "ScoreThresholdFilter: dropped {}/{} chunk(s) below threshold {:.3f}",
                dropped,
                len(chunks),
                self._min_score,
            )
        return filtered
