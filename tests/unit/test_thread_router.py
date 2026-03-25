"""Unit tests for ThreadRouter — Claude responses are mocked."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.schemas import ThreadRoutingAction
from src.agent.thread_router import ThreadRouter


def _mock_tool_response(action: str, ticket_id: int | None = None, reasoning: str = "test") -> MagicMock:
    """Build a mock Claude response with a tool_use block."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "produce_output"
    tool_block.input = {
        "action": action,
        "ticket_id": ticket_id,
        "reasoning": reasoning,
    }
    response = MagicMock()
    response.content = [tool_block]
    return response


def _make_router(mock_response: MagicMock) -> ThreadRouter:
    """Build a ThreadRouter with a mocked Anthropic client."""
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(return_value=mock_response)
    router = ThreadRouter(client=client)
    return router


# ---------------------------------------------------------------------------
# route_to_existing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_to_existing_ticket() -> None:
    response = _mock_tool_response("route_to_existing", ticket_id=42, reasoning="Same topic")
    router = _make_router(response)

    result = await router.route(
        message_text="Still having the same error",
        message_category="SUPPORT_QUESTION",
        active_tickets=[{"ticket_id": 42, "subject": "Login error"}],
    )

    assert result.action == ThreadRoutingAction.ROUTE_TO_EXISTING
    assert result.ticket_id == 42


# ---------------------------------------------------------------------------
# create_new
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_new_ticket() -> None:
    response = _mock_tool_response("create_new", reasoning="New topic")
    router = _make_router(response)

    result = await router.route(
        message_text="How do I export invoices?",
        message_category="SUPPORT_QUESTION",
        active_tickets=[{"ticket_id": 42, "subject": "Login error"}],
    )

    assert result.action == ThreadRoutingAction.CREATE_NEW
    assert result.ticket_id is None


# ---------------------------------------------------------------------------
# skip_zendesk
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skip_zendesk_for_greeting() -> None:
    response = _mock_tool_response("skip_zendesk", reasoning="Casual greeting")
    router = _make_router(response)

    result = await router.route(
        message_text="Good morning!",
        message_category="NON_SUPPORT",
    )

    assert result.action == ThreadRoutingAction.SKIP_ZENDESK


# ---------------------------------------------------------------------------
# Reply-based routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_with_reply_context() -> None:
    response = _mock_tool_response("route_to_existing", ticket_id=99, reasoning="Follow-up")
    router = _make_router(response)

    result = await router.route(
        message_text="Same issue here",
        message_category="SUPPORT_QUESTION",
        reply_to_text="I can't log in after resetting password",
        reply_to_ticket_id=99,
        active_tickets=[{"ticket_id": 99, "subject": "Login issue"}],
    )

    assert result.action == ThreadRoutingAction.ROUTE_TO_EXISTING
    assert result.ticket_id == 99


@pytest.mark.asyncio
async def test_route_passes_history_and_tickets() -> None:
    """Verify the router passes all context to Claude."""
    response = _mock_tool_response("create_new")
    router = _make_router(response)

    await router.route(
        message_text="New question",
        message_category="SUPPORT_QUESTION",
        recent_history=["User A: hello", "User B: hi"],
        active_tickets=[
            {"ticket_id": 1, "subject": "Ticket A", "recent_comments": "Comment 1"},
            {"ticket_id": 2, "subject": "Ticket B"},
        ],
    )

    # Verify the Claude API was called
    router._client.messages.create.assert_called_once()
    call_kwargs = router._client.messages.create.call_args
    prompt = call_kwargs.kwargs["messages"][0]["content"]
    assert "Ticket A" in prompt
    assert "Ticket B" in prompt
    assert "User A: hello" in prompt
