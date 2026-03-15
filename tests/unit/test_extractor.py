"""Unit tests for QuestionExtractor — mocked Claude responses."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.extractor import QuestionExtractor
from src.agent.schemas import ExtractorResult


def _make_tool_use_response(
    extracted_question: str,
    language: str = "en",
    conversation_summary: str = "",
) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = "produce_output"
    block.input = {
        "extracted_question": extracted_question,
        "language": language,
        "conversation_summary": conversation_summary,
    }

    response = MagicMock()
    response.content = [block]
    return response


@pytest.fixture()
def mock_anthropic_client() -> MagicMock:
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# Basic extraction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_returns_extractor_result(mock_anthropic_client: MagicMock) -> None:
    mock_anthropic_client.messages.create.return_value = _make_tool_use_response(
        "How do I update a load status to Delivered?", language="en"
    )
    extractor = QuestionExtractor(client=mock_anthropic_client)

    result = await extractor.extract("hey can u help. load status wont update to delivered??")

    assert isinstance(result, ExtractorResult)
    assert result.extracted_question == "How do I update a load status to Delivered?"
    assert result.language == "en"


@pytest.mark.asyncio
async def test_extract_russian_question(mock_anthropic_client: MagicMock) -> None:
    mock_anthropic_client.messages.create.return_value = _make_tool_use_response(
        "Как сбросить пароль водителя?", language="ru"
    )
    extractor = QuestionExtractor(client=mock_anthropic_client)

    result = await extractor.extract("блин забыл пароль водителя как сбросить")

    assert result.language == "ru"
    assert "пароль" in result.extracted_question


@pytest.mark.asyncio
async def test_extract_uzbek_question(mock_anthropic_client: MagicMock) -> None:
    mock_anthropic_client.messages.create.return_value = _make_tool_use_response(
        "Haydovchi parolini qanday tiklash mumkin?", language="uz"
    )
    extractor = QuestionExtractor(client=mock_anthropic_client)

    result = await extractor.extract("haydovchi kirish imkoni yo'q")

    assert result.language == "uz"


# ---------------------------------------------------------------------------
# Conversation summary populated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_includes_conversation_summary(mock_anthropic_client: MagicMock) -> None:
    summary = "User reported load #123 stuck in 'In Transit' status."
    mock_anthropic_client.messages.create.return_value = _make_tool_use_response(
        "Why is load #123 stuck in 'In Transit'?",
        language="en",
        conversation_summary=summary,
    )
    extractor = QuestionExtractor(client=mock_anthropic_client)

    result = await extractor.extract("same issue", conversation_context=["load 123 is stuck"])

    assert result.conversation_summary == summary


# ---------------------------------------------------------------------------
# Conversation context forwarded to Claude
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_forwards_context_to_claude(mock_anthropic_client: MagicMock) -> None:
    mock_anthropic_client.messages.create.return_value = _make_tool_use_response("Q?")
    extractor = QuestionExtractor(client=mock_anthropic_client)

    context = ["prev msg 1", "prev msg 2"]
    await extractor.extract("follow-up", conversation_context=context)

    call_kwargs = mock_anthropic_client.messages.create.call_args.kwargs
    assert "prev msg 1" in call_kwargs["messages"][0]["content"]


# ---------------------------------------------------------------------------
# Missing tool_use block raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_raises_on_missing_tool_use(mock_anthropic_client: MagicMock) -> None:
    bad_response = MagicMock()
    bad_response.content = []
    mock_anthropic_client.messages.create.return_value = bad_response

    with patch("src.agent.extractor.async_retry", return_value=lambda f: f):
        extractor = QuestionExtractor(client=mock_anthropic_client)
        with pytest.raises(ValueError, match="produce_output"):
            await extractor.extract("some message")
