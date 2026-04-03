"""Unit tests for ZendeskWebhookHandler gate logic and delivery."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.escalation.webhook_handler import ZendeskWebhookHandler


@pytest.fixture
def handler() -> ZendeskWebhookHandler:
    bot = MagicMock()
    # send_message returns a mock with message_id
    sent_msg = MagicMock()
    sent_msg.message_id = 42
    bot.send_message = AsyncMock(return_value=sent_msg)

    thread_store = MagicMock()
    thread_store.get_thread_for_ticket = AsyncMock(return_value=None)
    thread_store.close_thread_for_ticket = AsyncMock(return_value=None)

    return ZendeskWebhookHandler(
        bot=bot,
        thread_store=thread_store,
        ticket_summarizer=MagicMock(),
    )


def _make_payload(
    *,
    event_type: str = "zen:event-type:ticket.comment_added",
    ticket_id: str = "7741",
    tags: list[str] | None = None,
    body: str = "Agent reply",
    author_id: str = "12345",
    author_name: str = "Agent",
    status: str = "OPEN",
    actor_id: str = "99999",
) -> dict:
    if tags is None:
        tags = ["source_telegram"]
    return {
        "type": event_type,
        "detail": {
            "id": ticket_id,
            "status": status,
            "tags": tags,
            "actor_id": actor_id,
        },
        "event": {
            "comment": {
                "body": body,
                "author": {"id": author_id, "name": author_name, "is_staff": True},
            },
        },
    }


# ---------------------------------------------------------------------------
# Gate 1 — only comment_added and status_changed are accepted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsupported_event_type_rejected(handler: ZendeskWebhookHandler) -> None:
    result = await handler.handle_event(
        _make_payload(event_type="zen:event-type:ticket.TagsChanged")
    )
    assert result["status"] == "ignored"
    assert "unsupported event type" in result["reason"]


@pytest.mark.asyncio
async def test_empty_event_type_rejected(handler: ZendeskWebhookHandler) -> None:
    payload = _make_payload()
    payload.pop("type")
    result = await handler.handle_event(payload)
    assert result["status"] == "ignored"


# ---------------------------------------------------------------------------
# Gate 2 — ticket must carry source_telegram tag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_source_telegram_tag_rejected(handler: ZendeskWebhookHandler) -> None:
    result = await handler.handle_event(_make_payload(tags=["production", "auto_route"]))
    assert result["status"] == "ignored"
    assert "source_telegram" in result["reason"]


@pytest.mark.asyncio
async def test_empty_tags_rejected(handler: ZendeskWebhookHandler) -> None:
    result = await handler.handle_event(_make_payload(tags=[]))
    assert result["status"] == "ignored"
    assert "source_telegram" in result["reason"]


@pytest.mark.asyncio
async def test_no_tags_field_rejected(handler: ZendeskWebhookHandler) -> None:
    payload = _make_payload()
    payload["detail"].pop("tags")
    result = await handler.handle_event(payload)
    assert result["status"] == "ignored"


# ---------------------------------------------------------------------------
# Comment added — delivery to Telegram
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.escalation.webhook_handler.save_message", new_callable=AsyncMock)
async def test_comment_delivered_to_telegram(
    mock_save: AsyncMock,
    handler: ZendeskWebhookHandler,
) -> None:
    """Agent comment is sent to the correct Telegram group."""
    # Set up thread lookup to return a thread
    thread = MagicMock()
    thread.group_id = -1001234567890
    handler._thread_store.get_thread_for_ticket = AsyncMock(return_value=thread)

    result = await handler.handle_event(_make_payload(ticket_id="7741"))

    assert result["status"] == "delivered"
    assert result["ticket_id"] == "7741"
    assert result["group_id"] == -1001234567890

    # Verify bot.send_message was called with the right group
    handler._bot.send_message.assert_awaited_once()
    call_kwargs = handler._bot.send_message.call_args
    assert call_kwargs.kwargs["chat_id"] == -1001234567890
    assert "(#7741)" in call_kwargs.kwargs["text"]
    assert "Agent reply" in call_kwargs.kwargs["text"]

    # Verify message was persisted
    mock_save.assert_awaited_once()
    save_kwargs = mock_save.call_args.kwargs
    assert save_kwargs["chat_id"] == -1001234567890
    assert save_kwargs["source"] == "zendesk"
    assert save_kwargs["zendesk_ticket_id"] == 7741


@pytest.mark.asyncio
async def test_comment_skipped_for_api_originated(handler: ZendeskWebhookHandler) -> None:
    """Comments originating from our API account are ignored (actor_id filter)."""
    handler._api_account_user_id = 33333
    result = await handler.handle_event(_make_payload(author_id="12345", actor_id="33333"))
    assert result["status"] == "ignored"
    assert "API-originated" in result["reason"]


@pytest.mark.asyncio
async def test_comment_skipped_for_bot_own_comment(handler: ZendeskWebhookHandler) -> None:
    """Bot's own comments are ignored (author_id fallback filter)."""
    handler._bot_zendesk_user_id = 12345
    result = await handler.handle_event(_make_payload(author_id="12345"))
    assert result["status"] == "ignored"
    assert "bot's own comment" in result["reason"]


@pytest.mark.asyncio
async def test_comment_skipped_when_no_thread(handler: ZendeskWebhookHandler) -> None:
    """Comment is ignored when no conversation thread exists for the ticket."""
    handler._thread_store.get_thread_for_ticket = AsyncMock(return_value=None)

    result = await handler.handle_event(_make_payload())

    assert result["status"] == "ignored"
    assert "no conversation thread" in result["reason"]


@pytest.mark.asyncio
async def test_comment_skipped_for_empty_body(handler: ZendeskWebhookHandler) -> None:
    """Empty comment bodies are ignored."""
    result = await handler.handle_event(_make_payload(body=""))

    assert result["status"] == "ignored"
    assert "empty comment" in result["reason"]


# ---------------------------------------------------------------------------
# Status changed — thread closure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_solved_closes_thread(handler: ZendeskWebhookHandler) -> None:
    """Solved status triggers thread closure."""
    thread = MagicMock()
    thread.group_id = -1001234567890
    handler._thread_store.close_thread_for_ticket = AsyncMock(return_value=thread)

    result = await handler.handle_event(
        _make_payload(
            event_type="zen:event-type:ticket.status_changed",
            status="solved",
        )
    )

    assert result["status"] == "closed"
    handler._thread_store.close_thread_for_ticket.assert_awaited_once_with(7741)


@pytest.mark.asyncio
async def test_status_open_does_not_close_thread(handler: ZendeskWebhookHandler) -> None:
    """Non-closed statuses don't trigger closure."""
    result = await handler.handle_event(
        _make_payload(
            event_type="zen:event-type:ticket.status_changed",
            status="open",
        )
    )

    assert result["status"] == "received"
    handler._thread_store.close_thread_for_ticket.assert_not_awaited()
