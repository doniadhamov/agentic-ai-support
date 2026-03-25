"""Unit tests for ScoreThresholdFilter — filter by score, source tagging preserved."""

from __future__ import annotations

from src.rag.reranker import ScoreThresholdFilter
from src.rag.retriever import RetrievedChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chunk(score: float, source: str = "docs", text: str = "chunk") -> RetrievedChunk:
    return RetrievedChunk(
        point_id="p1",
        score=score,
        text=text,
        source=source,
    )


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def test_keeps_chunks_above_threshold() -> None:
    f = ScoreThresholdFilter(min_score=0.5)
    chunks = [_chunk(0.9), _chunk(0.6), _chunk(0.3)]
    result = f.filter(chunks)
    assert len(result) == 2
    assert all(c.score >= 0.5 for c in result)


def test_keeps_chunk_at_exact_threshold() -> None:
    f = ScoreThresholdFilter(min_score=0.75)
    result = f.filter([_chunk(0.75)])
    assert len(result) == 1


def test_drops_all_below_threshold() -> None:
    f = ScoreThresholdFilter(min_score=0.9)
    result = f.filter([_chunk(0.5), _chunk(0.3)])
    assert result == []


def test_empty_input_returns_empty() -> None:
    f = ScoreThresholdFilter(min_score=0.5)
    assert f.filter([]) == []


def test_preserves_order() -> None:
    f = ScoreThresholdFilter(min_score=0.1)
    chunks = [_chunk(0.9, text="first"), _chunk(0.5, text="second"), _chunk(0.2, text="third")]
    result = f.filter(chunks)
    assert [c.text for c in result] == ["first", "second", "third"]


# ---------------------------------------------------------------------------
# Source tagging preserved
# ---------------------------------------------------------------------------


def test_source_tag_docs_preserved() -> None:
    f = ScoreThresholdFilter(min_score=0.1)
    result = f.filter([_chunk(0.8, source="docs")])
    assert result[0].source == "docs"


def test_source_tag_memory_preserved() -> None:
    f = ScoreThresholdFilter(min_score=0.1)
    result = f.filter([_chunk(0.8, source="memory")])
    assert result[0].source == "memory"


def test_mixed_sources_preserved() -> None:
    f = ScoreThresholdFilter(min_score=0.1)
    chunks = [_chunk(0.9, source="docs"), _chunk(0.8, source="memory")]
    result = f.filter(chunks)
    assert result[0].source == "docs"
    assert result[1].source == "memory"


# ---------------------------------------------------------------------------
# Default threshold from settings
# ---------------------------------------------------------------------------


def test_default_threshold_from_settings() -> None:
    """When no min_score is provided, defaults to settings.support_min_confidence_score (0.70)."""
    f = ScoreThresholdFilter()
    chunks = [_chunk(0.8), _chunk(0.65)]
    result = f.filter(chunks)
    assert len(result) == 1
    assert result[0].score == 0.8
