"""Unit tests for TicketSummarizer — Claude responses are mocked."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.ticket_summarizer import TicketSummarizer


def _mock_tool_response(question: str, answer: str, tags: list[str] | None = None) -> MagicMock:
    """Build a mock Claude response with a tool_use block."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "produce_output"
    tool_block.input = {
        "question": question,
        "answer": answer,
        "tags": tags or [],
    }
    response = MagicMock()
    response.content = [tool_block]
    return response


def _make_summarizer(mock_response: MagicMock) -> TicketSummarizer:
    """Build a TicketSummarizer with a mocked Anthropic client."""
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(return_value=mock_response)
    summarizer = TicketSummarizer(client=client)
    return summarizer


@pytest.mark.asyncio
async def test_summarize_returns_qa_pair() -> None:
    response = _mock_tool_response(
        question="How to reset a driver's password?",
        answer="Go to Settings > Users > Select driver > Reset Password.",
        tags=["password", "driver"],
    )
    summarizer = _make_summarizer(response)

    result = await summarizer.summarize(
        messages=[
            {"username": "John", "text": "Driver can't log in", "source": "telegram"},
            {"username": "[AI Bot]", "text": "Have you tried resetting?", "source": "telegram"},
            {"username": "Support Agent", "text": "Go to Settings > Users", "source": "zendesk"},
        ]
    )

    assert result["question"] == "How to reset a driver's password?"
    assert "Settings" in result["answer"]
    assert "password" in result["tags"]


@pytest.mark.asyncio
async def test_summarize_passes_conversation_to_claude() -> None:
    response = _mock_tool_response(question="Q", answer="A")
    summarizer = _make_summarizer(response)

    await summarizer.summarize(
        messages=[
            {"username": "Alice", "text": "My load is stuck", "source": "telegram"},
            {"username": "Bob", "text": "Try refreshing", "source": "zendesk"},
        ]
    )

    summarizer._client.messages.create.assert_called_once()
    call_kwargs = summarizer._client.messages.create.call_args
    prompt = call_kwargs.kwargs["messages"][0]["content"]
    assert "My load is stuck" in prompt
    assert "[Support Agent]: Try refreshing" in prompt


@pytest.mark.asyncio
async def test_summarize_handles_empty_tags() -> None:
    response = _mock_tool_response(question="Q", answer="A")
    summarizer = _make_summarizer(response)

    result = await summarizer.summarize(messages=[{"username": "User", "text": "Help", "source": "telegram"}])
    assert result["tags"] == []
