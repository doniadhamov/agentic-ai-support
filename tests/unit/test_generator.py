"""Unit tests for AnswerGenerator — mocked Claude responses."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.generator import AnswerGenerator
from src.agent.schemas import GeneratorResult
from src.rag.retriever import RetrievedChunk


def _make_tool_use_response(
    answer: str = "",
    follow_up_question: str = "",
    needs_escalation: bool = False,
    escalation_reason: str = "",
    knowledge_sources: list[dict] | None = None,
) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = "produce_output"
    block.input = {
        "answer": answer,
        "follow_up_question": follow_up_question,
        "needs_escalation": needs_escalation,
        "escalation_reason": escalation_reason,
        "knowledge_sources_used": knowledge_sources or [],
    }

    response = MagicMock()
    response.content = [block]
    return response


def _chunk(text: str, source: str = "docs", score: float = 0.9) -> RetrievedChunk:
    return RetrievedChunk(
        point_id="abc123",
        score=score,
        text=text,
        article_title="Help Article",
        article_url="https://example.com/article",
        source=source,
    )


@pytest.fixture()
def mock_anthropic_client() -> MagicMock:
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# Successful answer generation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_returns_generator_result(mock_anthropic_client: MagicMock) -> None:
    mock_anthropic_client.messages.create.return_value = _make_tool_use_response(
        answer="To update the load status, go to Load Management and click 'Update Status'.",
        knowledge_sources=[{"type": "documentation", "title": "Load Management Guide", "id": "42"}],
    )
    generator = AnswerGenerator(client=mock_anthropic_client)

    result = await generator.generate(
        question="How do I update a load status?",
        chunks=[_chunk("Load Management: click Update Status button.")],
        language="en",
    )

    assert isinstance(result, GeneratorResult)
    assert "Update Status" in result.answer
    assert not result.needs_escalation
    assert len(result.knowledge_sources_used) == 1
    assert result.knowledge_sources_used[0].type == "documentation"


@pytest.mark.asyncio
async def test_generate_with_memory_source(mock_anthropic_client: MagicMock) -> None:
    mock_anthropic_client.messages.create.return_value = _make_tool_use_response(
        answer="Reset the password via the admin panel.",
        knowledge_sources=[{"type": "approved_memory", "title": "Password Reset", "id": "mem-1"}],
    )
    generator = AnswerGenerator(client=mock_anthropic_client)

    result = await generator.generate(
        question="How to reset driver password?",
        chunks=[_chunk("Reset via admin.", source="memory")],
        language="ru",
    )

    assert result.knowledge_sources_used[0].type == "approved_memory"


# ---------------------------------------------------------------------------
# Escalation decision
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_escalation_when_no_chunks(mock_anthropic_client: MagicMock) -> None:
    mock_anthropic_client.messages.create.return_value = _make_tool_use_response(
        answer="I've forwarded your issue to our support team.",
        needs_escalation=True,
        escalation_reason="No relevant documentation found for this account-specific issue.",
    )
    generator = AnswerGenerator(client=mock_anthropic_client)

    result = await generator.generate(
        question="Why is my account locked?",
        chunks=[],
        language="en",
    )

    assert result.needs_escalation is True
    assert result.escalation_reason != ""


@pytest.mark.asyncio
async def test_generate_escalation_with_low_confidence(mock_anthropic_client: MagicMock) -> None:
    mock_anthropic_client.messages.create.return_value = _make_tool_use_response(
        answer="Your issue has been forwarded to support.",
        needs_escalation=True,
        escalation_reason="Retrieved documentation does not address this specific error.",
    )
    generator = AnswerGenerator(client=mock_anthropic_client)

    low_score_chunk = _chunk("Unrelated content", score=0.5)
    result = await generator.generate(
        question="Error code 503 on login",
        chunks=[low_score_chunk],
        language="en",
    )

    assert result.needs_escalation is True


# ---------------------------------------------------------------------------
# Follow-up question
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_follow_up_question(mock_anthropic_client: MagicMock) -> None:
    mock_anthropic_client.messages.create.return_value = _make_tool_use_response(
        answer="Could you clarify which screen you're on?",
        follow_up_question="Which page or screen are you seeing the error on?",
    )
    generator = AnswerGenerator(client=mock_anthropic_client)

    result = await generator.generate(
        question="I have an error",
        chunks=[],
        language="en",
    )

    assert result.follow_up_question != ""


# ---------------------------------------------------------------------------
# Empty chunks formatting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_formats_empty_chunks_gracefully(mock_anthropic_client: MagicMock) -> None:
    mock_anthropic_client.messages.create.return_value = _make_tool_use_response(
        answer="Forwarded to support.", needs_escalation=True, escalation_reason="No docs found."
    )
    generator = AnswerGenerator(client=mock_anthropic_client)

    # Should not raise even with no chunks
    result = await generator.generate(question="unknown issue", chunks=[], language="uz")
    assert result.needs_escalation is True

    call_kwargs = mock_anthropic_client.messages.create.call_args.kwargs
    assert "no relevant documentation found" in call_kwargs["messages"][0]["content"].lower()


# ---------------------------------------------------------------------------
# Missing tool_use block raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_raises_on_missing_tool_use(mock_anthropic_client: MagicMock) -> None:
    bad_response = MagicMock()
    bad_response.content = []
    mock_anthropic_client.messages.create.return_value = bad_response

    with patch("src.agent.generator.async_retry", return_value=lambda f: f):
        generator = AnswerGenerator(client=mock_anthropic_client)
        with pytest.raises(ValueError, match="produce_output"):
            await generator.generate("q", [], "en")
