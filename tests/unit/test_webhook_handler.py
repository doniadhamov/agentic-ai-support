"""Unit tests for ZendeskWebhookHandler gate logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.escalation.webhook_handler import ZendeskWebhookHandler


@pytest.fixture
def handler() -> ZendeskWebhookHandler:
    return ZendeskWebhookHandler(
        bot=MagicMock(),
        thread_store=MagicMock(),
        ticket_summarizer=MagicMock(),
    )


def _make_payload(
    *,
    event_type: str = "zen:event-type:ticket.comment_added",
    ticket_id: str = "7741",
    tags: list[str] | None = None,
) -> dict:
    if tags is None:
        tags = ["source_telegram"]
    return {
        "type": event_type,
        "detail": {
            "id": ticket_id,
            "status": "OPEN",
            "tags": tags,
        },
        "event": {
            "comment": {
                "body": "Agent reply",
                "author": {"id": "12345", "name": "Agent", "is_staff": True},
                "is_public": True,
            },
        },
    }


# ---------------------------------------------------------------------------
# Gate 1 — only comment_added and status_changed are accepted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_comment_added_passes_gate1(handler: ZendeskWebhookHandler) -> None:
    result = await handler.handle_event(
        _make_payload(event_type="zen:event-type:ticket.comment_added")
    )
    assert result["status"] == "received"


@pytest.mark.asyncio
async def test_status_changed_passes_gate1(handler: ZendeskWebhookHandler) -> None:
    result = await handler.handle_event(
        _make_payload(event_type="zen:event-type:ticket.status_changed")
    )
    assert result["status"] == "received"


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
async def test_source_telegram_tag_passes_gate2(handler: ZendeskWebhookHandler) -> None:
    result = await handler.handle_event(
        _make_payload(tags=["source_telegram", "production"])
    )
    assert result["status"] == "received"


@pytest.mark.asyncio
async def test_missing_source_telegram_tag_rejected(handler: ZendeskWebhookHandler) -> None:
    result = await handler.handle_event(
        _make_payload(tags=["production", "auto_route"])
    )
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
# Gate pass — matching events return received with ticket info
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matching_event_returns_ticket_id(handler: ZendeskWebhookHandler) -> None:
    result = await handler.handle_event(_make_payload(ticket_id="7741"))
    assert result == {
        "status": "received",
        "ticket_id": "7741",
        "event_type": "zen:event-type:ticket.comment_added",
    }


@pytest.mark.asyncio
async def test_matching_event_logs_payload(handler: ZendeskWebhookHandler) -> None:
    from loguru import logger

    messages: list[str] = []
    sink_id = logger.add(lambda m: messages.append(m), level="INFO")
    try:
        payload = _make_payload(ticket_id="9999")
        await handler.handle_event(payload)
    finally:
        logger.remove(sink_id)

    combined = "".join(messages)
    assert "9999" in combined
    assert "payload" in combined.lower()
