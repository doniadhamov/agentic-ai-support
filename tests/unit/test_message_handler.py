"""Unit tests for MessageHandler — full handler flow with mocked agent,
reply sending, plain-text fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramBadRequest

from src.agent.schemas import AgentOutput, MessageCategory
from src.telegram.handlers.message_handler import handle_group_message

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(text: str = "How do I reset?") -> MagicMock:
    msg = AsyncMock()
    msg.text = text
    msg.chat = MagicMock()
    msg.chat.id = 100
    msg.chat.type = "supergroup"
    msg.from_user = MagicMock()
    msg.from_user.id = 42
    msg.from_user.full_name = "Test User"
    msg.message_id = 999
    msg.reply = AsyncMock()
    return msg


def _make_output(
    should_reply: bool = True,
    answer: str = "Here is the answer.",
    category: MessageCategory = MessageCategory.SUPPORT_QUESTION,
) -> AgentOutput:
    return AgentOutput(
        category=category,
        should_reply=should_reply,
        answer=answer,
        language="en",
    )


def _make_context_manager() -> MagicMock:
    ctx = AsyncMock()
    ctx.get_context_strings = AsyncMock(return_value=["prev msg", "current msg"])
    cm = AsyncMock()
    cm.get_or_create = AsyncMock(return_value=ctx)
    return cm


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_sends_reply() -> None:
    msg = _make_message()
    agent = AsyncMock()
    agent.process = AsyncMock(return_value=_make_output())
    cm = _make_context_manager()

    await handle_group_message(msg, agent, cm)

    msg.reply.assert_awaited_once()


@pytest.mark.asyncio
async def test_handler_no_reply_when_should_reply_false() -> None:
    msg = _make_message()
    agent = AsyncMock()
    agent.process = AsyncMock(return_value=_make_output(should_reply=False))
    cm = _make_context_manager()

    await handle_group_message(msg, agent, cm)

    msg.reply.assert_not_awaited()


# ---------------------------------------------------------------------------
# Skips messages without text or user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_skips_no_text() -> None:
    msg = _make_message()
    msg.text = None
    agent = AsyncMock()
    cm = _make_context_manager()

    await handle_group_message(msg, agent, cm)

    agent.process.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_skips_no_user() -> None:
    msg = _make_message()
    msg.from_user = None
    agent = AsyncMock()
    cm = _make_context_manager()

    await handle_group_message(msg, agent, cm)

    agent.process.assert_not_awaited()


# ---------------------------------------------------------------------------
# Plain-text fallback on MarkdownV2 parse error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_falls_back_to_plain_text_on_parse_error() -> None:
    msg = _make_message()
    output = _make_output(answer="Simple answer")

    # First reply call raises TelegramBadRequest with parse error, second succeeds
    exc = TelegramBadRequest(method=MagicMock(), message="Bad Request: can't parse entities")
    msg.reply = AsyncMock(side_effect=[exc, None])

    agent = AsyncMock()
    agent.process = AsyncMock(return_value=output)
    cm = _make_context_manager()

    await handle_group_message(msg, agent, cm)

    # Should have been called twice: first with MarkdownV2, then plain text
    assert msg.reply.await_count == 2
    # Second call should use parse_mode=None
    _, kwargs = msg.reply.call_args_list[1]
    assert kwargs.get("parse_mode") is None


@pytest.mark.asyncio
async def test_handler_reraises_non_parse_telegram_error() -> None:
    msg = _make_message()
    exc = TelegramBadRequest(method=MagicMock(), message="Bad Request: chat not found")
    msg.reply = AsyncMock(side_effect=exc)

    agent = AsyncMock()
    agent.process = AsyncMock(return_value=_make_output())
    cm = _make_context_manager()

    with pytest.raises(TelegramBadRequest):
        await handle_group_message(msg, agent, cm)


# ---------------------------------------------------------------------------
# Format error fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_falls_back_on_format_error() -> None:
    msg = _make_message()
    output = _make_output(answer="raw answer")

    agent = AsyncMock()
    agent.process = AsyncMock(return_value=output)
    cm = _make_context_manager()

    with patch(
        "src.telegram.handlers.message_handler.format_reply",
        side_effect=ValueError("format broke"),
    ):
        await handle_group_message(msg, agent, cm)

    # Should still send a reply (the raw text fallback)
    msg.reply.assert_awaited_once()


# ---------------------------------------------------------------------------
# Context manager interaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_records_message_in_context() -> None:
    msg = _make_message()
    agent = AsyncMock()
    agent.process = AsyncMock(return_value=_make_output(should_reply=False))
    cm = _make_context_manager()

    await handle_group_message(msg, agent, cm)

    cm.get_or_create.assert_awaited_once_with(100)
    ctx = await cm.get_or_create(100)
    ctx.add_message.assert_awaited_once()
