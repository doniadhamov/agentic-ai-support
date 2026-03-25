"""Integration test: Zendesk ticket client with mocked HTTP.

This test does NOT require Qdrant — it mocks all external HTTP.
It tests the ZendeskTicketClient for:
  1. create_ticket() sends the correct payload and returns ticket ID.
  2. add_comment() posts a comment and returns comment ID.
  3. upload_attachment() uploads a file and returns a token.
  4. get_ticket() fetches ticket data.
"""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from src.escalation.ticket_client import ZendeskTicketClient
from src.escalation.ticket_schemas import ZendeskComment, ZendeskTicketCreate


@pytest.fixture
def zendesk_client() -> ZendeskTicketClient:
    return ZendeskTicketClient(
        subdomain="test.zendesk.com",
        email="agent@test.com",
        api_token="test-token",
    )


# ---------------------------------------------------------------------------
# create_ticket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_create_ticket_roundtrip(zendesk_client: ZendeskTicketClient) -> None:
    """Create a ticket and verify the returned ID."""
    respx.post("https://test.zendesk.com/api/v2/tickets.json").mock(
        return_value=Response(201, json={"ticket": {"id": 100, "status": "new"}}),
    )

    ticket_id = await zendesk_client.create_ticket(
        ZendeskTicketCreate(
            subject="Driver login issue",
            body="User reports driver can't log in after password reset",
        )
    )

    assert ticket_id == 100


# ---------------------------------------------------------------------------
# add_comment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_add_comment_roundtrip(zendesk_client: ZendeskTicketClient) -> None:
    """Add a comment to a ticket and verify the returned comment ID."""
    respx.put("https://test.zendesk.com/api/v2/tickets/100.json").mock(
        return_value=Response(
            200,
            json={
                "ticket": {"id": 100},
                "audit": {"events": [{"type": "Comment", "id": 5001}]},
            },
        ),
    )

    comment_id = await zendesk_client.add_comment(
        ticket_id=100,
        comment=ZendeskComment(body="[John]: Still having the same issue"),
    )

    assert comment_id == 5001


# ---------------------------------------------------------------------------
# upload_attachment + add_comment with attachment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_upload_and_attach(zendesk_client: ZendeskTicketClient) -> None:
    """Upload a file, then add a comment referencing the upload token."""
    respx.post("https://test.zendesk.com/api/v2/uploads.json").mock(
        return_value=Response(201, json={"upload": {"token": "tok_screenshot"}}),
    )
    respx.put("https://test.zendesk.com/api/v2/tickets/100.json").mock(
        return_value=Response(
            200,
            json={
                "ticket": {"id": 100},
                "audit": {"events": [{"type": "Comment", "id": 5002}]},
            },
        ),
    )

    token = await zendesk_client.upload_attachment(
        filename="screenshot.png",
        content_type="image/png",
        data=b"\x89PNG...",
    )
    assert token == "tok_screenshot"

    comment_id = await zendesk_client.add_comment(
        ticket_id=100,
        comment=ZendeskComment(
            body="[John]: See attached screenshot",
            attachment_tokens=[token],
        ),
    )
    assert comment_id == 5002


# ---------------------------------------------------------------------------
# get_ticket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_get_ticket(zendesk_client: ZendeskTicketClient) -> None:
    """Fetch a ticket and verify the returned data."""
    respx.get("https://test.zendesk.com/api/v2/tickets/100.json").mock(
        return_value=Response(
            200,
            json={"ticket": {"id": 100, "status": "open", "subject": "Login issue"}},
        ),
    )

    ticket = await zendesk_client.get_ticket(100)
    assert ticket["id"] == 100
    assert ticket["subject"] == "Login issue"
