"""Unit tests for MessageClassifier — mocked Claude responses."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.classifier import MessageClassifier
from src.agent.schemas import ClassifierResult, MessageCategory


def _make_tool_use_response(category: str, language: str = "en") -> MagicMock:
    """Build a fake anthropic.types.Message with a tool_use content block."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = "produce_output"
    block.input = {"category": category, "language": language, "confidence": 0.95, "reasoning": "test"}

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
# NON_SUPPORT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_non_support(mock_anthropic_client: MagicMock) -> None:
    mock_anthropic_client.messages.create.return_value = _make_tool_use_response("NON_SUPPORT")
    classifier = MessageClassifier(client=mock_anthropic_client)

    result = await classifier.classify("Good morning everyone!")

    assert isinstance(result, ClassifierResult)
    assert result.category == MessageCategory.NON_SUPPORT
    assert result.language == "en"


# ---------------------------------------------------------------------------
# SUPPORT_QUESTION
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_support_question_english(mock_anthropic_client: MagicMock) -> None:
    mock_anthropic_client.messages.create.return_value = _make_tool_use_response(
        "SUPPORT_QUESTION", "en"
    )
    classifier = MessageClassifier(client=mock_anthropic_client)

    result = await classifier.classify("How do I update a load status to Delivered?")

    assert result.category == MessageCategory.SUPPORT_QUESTION
    assert result.language == "en"


@pytest.mark.asyncio
async def test_classify_support_question_russian(mock_anthropic_client: MagicMock) -> None:
    mock_anthropic_client.messages.create.return_value = _make_tool_use_response(
        "SUPPORT_QUESTION", "ru"
    )
    classifier = MessageClassifier(client=mock_anthropic_client)

    result = await classifier.classify("Как добавить нового водителя в систему?")

    assert result.category == MessageCategory.SUPPORT_QUESTION
    assert result.language == "ru"


@pytest.mark.asyncio
async def test_classify_support_question_uzbek(mock_anthropic_client: MagicMock) -> None:
    mock_anthropic_client.messages.create.return_value = _make_tool_use_response(
        "SUPPORT_QUESTION", "uz"
    )
    classifier = MessageClassifier(client=mock_anthropic_client)

    result = await classifier.classify("Haydovchi parolini qanday tiklash mumkin?")

    assert result.category == MessageCategory.SUPPORT_QUESTION
    assert result.language == "uz"


# ---------------------------------------------------------------------------
# CLARIFICATION_NEEDED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_clarification_needed(mock_anthropic_client: MagicMock) -> None:
    mock_anthropic_client.messages.create.return_value = _make_tool_use_response(
        "CLARIFICATION_NEEDED", "en"
    )
    classifier = MessageClassifier(client=mock_anthropic_client)

    result = await classifier.classify("It still doesn't work.")

    assert result.category == MessageCategory.CLARIFICATION_NEEDED


# ---------------------------------------------------------------------------
# ESCALATION_REQUIRED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_escalation_required(mock_anthropic_client: MagicMock) -> None:
    mock_anthropic_client.messages.create.return_value = _make_tool_use_response(
        "ESCALATION_REQUIRED", "en"
    )
    classifier = MessageClassifier(client=mock_anthropic_client)

    result = await classifier.classify(
        "I've followed all the steps three times but the driver still can't log in."
    )

    assert result.category == MessageCategory.ESCALATION_REQUIRED


# ---------------------------------------------------------------------------
# Conversation context is passed through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_passes_context_to_claude(mock_anthropic_client: MagicMock) -> None:
    mock_anthropic_client.messages.create.return_value = _make_tool_use_response("SUPPORT_QUESTION")
    classifier = MessageClassifier(client=mock_anthropic_client)

    context = ["User A: My load is stuck.", "User B: Which load?"]
    await classifier.classify("Load ID 12345 is stuck", conversation_context=context)

    call_kwargs = mock_anthropic_client.messages.create.call_args.kwargs
    # The user content should include the recent context
    assert "User A: My load is stuck." in call_kwargs["messages"][0]["content"]


# ---------------------------------------------------------------------------
# Missing tool_use block raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_raises_on_missing_tool_use(mock_anthropic_client: MagicMock) -> None:
    bad_response = MagicMock()
    bad_response.content = []  # no tool_use block
    mock_anthropic_client.messages.create.return_value = bad_response

    # Patch async_retry to not retry so the test is fast
    with patch("src.agent.classifier.async_retry", return_value=lambda f: f):
        classifier = MessageClassifier(client=mock_anthropic_client)
        with pytest.raises(ValueError, match="produce_output"):
            await classifier.classify("some message")
