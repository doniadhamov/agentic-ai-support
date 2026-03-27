"""Unit tests for ZendeskTicketClient — all HTTP calls mocked via respx."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from src.escalation.ticket_client import ZendeskTicketClient
from src.escalation.ticket_schemas import ZendeskComment, ZendeskTicketCreate


@pytest.fixture
def client() -> ZendeskTicketClient:
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
async def test_create_ticket_returns_ticket_id(client: ZendeskTicketClient) -> None:
    respx.post("https://test.zendesk.com/api/v2/tickets.json").mock(
        return_value=Response(201, json={"ticket": {"id": 42, "status": "new"}}),
    )

    ticket_id = await client.create_ticket(
        ZendeskTicketCreate(subject="Test", body="Hello"),
    )
    assert ticket_id == 42


@pytest.mark.asyncio
@respx.mock
async def test_create_ticket_sends_correct_payload(client: ZendeskTicketClient) -> None:
    route = respx.post("https://test.zendesk.com/api/v2/tickets.json").mock(
        return_value=Response(201, json={"ticket": {"id": 1}}),
    )

    await client.create_ticket(
        ZendeskTicketCreate(subject="Bug report", body="Something broke", tags=["telegram"]),
    )

    request = route.calls.last.request
    import json

    payload = json.loads(request.content)
    assert payload["ticket"]["subject"] == "test-tg-chat: Bug report"
    assert payload["ticket"]["comment"]["body"] == "Something broke"
    assert payload["ticket"]["tags"] == ["telegram"]


# ---------------------------------------------------------------------------
# add_comment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_add_comment_returns_comment_id(client: ZendeskTicketClient) -> None:
    respx.put("https://test.zendesk.com/api/v2/tickets/42.json").mock(
        return_value=Response(
            200,
            json={
                "ticket": {"id": 42},
                "audit": {"events": [{"type": "Comment", "id": 999}]},
            },
        ),
    )

    comment_id = await client.add_comment(
        ticket_id=42,
        comment=ZendeskComment(body="Follow-up info"),
    )
    assert comment_id == 999


@pytest.mark.asyncio
@respx.mock
async def test_add_comment_with_attachments(client: ZendeskTicketClient) -> None:
    route = respx.put("https://test.zendesk.com/api/v2/tickets/42.json").mock(
        return_value=Response(
            200,
            json={"ticket": {"id": 42}, "audit": {"events": []}},
        ),
    )

    await client.add_comment(
        ticket_id=42,
        comment=ZendeskComment(body="See attached", attachment_tokens=["tok_abc"]),
    )

    import json

    payload = json.loads(route.calls.last.request.content)
    assert payload["ticket"]["comment"]["uploads"] == ["tok_abc"]


# ---------------------------------------------------------------------------
# upload_attachment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_upload_attachment_returns_token(client: ZendeskTicketClient) -> None:
    respx.post("https://test.zendesk.com/api/v2/uploads.json").mock(
        return_value=Response(201, json={"upload": {"token": "tok_xyz"}}),
    )

    token = await client.upload_attachment(
        filename="screenshot.png",
        content_type="image/png",
        data=b"\x89PNG...",
    )
    assert token == "tok_xyz"


# ---------------------------------------------------------------------------
# get_ticket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_get_ticket_returns_ticket_dict(client: ZendeskTicketClient) -> None:
    respx.get("https://test.zendesk.com/api/v2/tickets/42.json").mock(
        return_value=Response(
            200, json={"ticket": {"id": 42, "status": "open", "subject": "Test"}}
        ),
    )

    ticket = await client.get_ticket(42)
    assert ticket["id"] == 42
    assert ticket["status"] == "open"


# ---------------------------------------------------------------------------
# get_ticket_comments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_get_ticket_comments_returns_list(client: ZendeskTicketClient) -> None:
    respx.get("https://test.zendesk.com/api/v2/tickets/42/comments.json").mock(
        return_value=Response(
            200,
            json={"comments": [{"id": 1, "body": "First"}, {"id": 2, "body": "Second"}]},
        ),
    )

    comments = await client.get_ticket_comments(42)
    assert len(comments) == 2
    assert comments[0]["body"] == "First"


# ---------------------------------------------------------------------------
# create_ticket with requester_id + custom_fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_create_ticket_with_requester_and_custom_fields(
    client: ZendeskTicketClient,
) -> None:
    route = respx.post("https://test.zendesk.com/api/v2/tickets.json").mock(
        return_value=Response(201, json={"ticket": {"id": 99}}),
    )

    await client.create_ticket(
        ZendeskTicketCreate(
            subject="User ticket",
            body="Hello from Telegram",
            requester_id=50184591324691,
            author_id=50184591324691,
            tags=["source_telegram"],
            custom_fields=[{"id": "50187371410579", "value": "-5196436916"}],
        ),
    )

    import json

    payload = json.loads(route.calls.last.request.content)
    ticket = payload["ticket"]
    assert ticket["requester_id"] == 50184591324691
    assert ticket["comment"]["author_id"] == 50184591324691
    assert ticket["tags"] == ["source_telegram"]
    assert ticket["custom_fields"] == [{"id": "50187371410579", "value": "-5196436916"}]


# ---------------------------------------------------------------------------
# add_comment with author_id + tags + custom_fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_add_comment_with_author_id(client: ZendeskTicketClient) -> None:
    route = respx.put("https://test.zendesk.com/api/v2/tickets/42.json").mock(
        return_value=Response(
            200,
            json={"ticket": {"id": 42}, "audit": {"events": [{"type": "Comment", "id": 555}]}},
        ),
    )

    comment_id = await client.add_comment(
        ticket_id=42,
        comment=ZendeskComment(body="Reply text", author_id=39755600127379),
        tags=["source_telegram"],
        custom_fields=[{"id": "50187371410579", "value": "-5196436916"}],
    )

    import json

    payload = json.loads(route.calls.last.request.content)
    assert payload["ticket"]["comment"]["author_id"] == 39755600127379
    assert payload["ticket"]["tags"] == ["source_telegram"]
    assert payload["ticket"]["custom_fields"] == [{"id": "50187371410579", "value": "-5196436916"}]
    assert comment_id == 555


# ---------------------------------------------------------------------------
# create_or_update_profile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_create_or_update_profile(client: ZendeskTicketClient) -> None:
    route = respx.put("https://test.zendesk.com/api/v2/user_profiles").mock(
        return_value=Response(
            200,
            json={
                "profile": {
                    "id": "01KME30Z8QWFGC5PFBC54RJ8R5",
                    "user_id": "50184591324691",
                    "source": "telegram",
                    "type": "customer",
                    "name": "Doniyor A",
                }
            },
        ),
    )

    profile = await client.create_or_update_profile(
        name="Doniyor A",
        identifier_value="telegram_1901442684",
    )

    assert profile["user_id"] == "50184591324691"
    assert profile["id"] == "01KME30Z8QWFGC5PFBC54RJ8R5"

    import json

    payload = json.loads(route.calls.last.request.content)
    assert payload["profile"]["name"] == "Doniyor A"
    assert payload["profile"]["identifiers"][0]["value"] == "telegram_1901442684"

    # Check query param (colons are URL-encoded as %3A)
    request = route.calls.last.request
    assert "telegram_1901442684" in str(request.url)


# ---------------------------------------------------------------------------
# get_profile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_get_profile_found(client: ZendeskTicketClient) -> None:
    respx.get("https://test.zendesk.com/api/v2/user_profiles").mock(
        return_value=Response(
            200,
            json={
                "profile": {
                    "id": "01KME30Z8QWFGC5PFBC54RJ8R5",
                    "user_id": "50184591324691",
                }
            },
        ),
    )

    profile = await client.get_profile("telegram_1901442684")
    assert profile is not None
    assert profile["user_id"] == "50184591324691"


@pytest.mark.asyncio
@respx.mock
async def test_get_profile_not_found(client: ZendeskTicketClient) -> None:
    respx.get("https://test.zendesk.com/api/v2/user_profiles").mock(
        return_value=Response(404),
    )

    profile = await client.get_profile("telegram_nonexistent")
    assert profile is None
