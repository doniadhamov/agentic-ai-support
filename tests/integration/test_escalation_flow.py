"""Integration test: mock ticket API, verify create payload and response delivery.

This test does NOT require Qdrant — it mocks all external HTTP and
the Telegram bot. It tests the full escalation loop:
  1. TicketAPIClient.create_ticket() sends the correct payload.
  2. TicketStore persists the record and surfaces it as open.
  3. TicketPoller.run() detects the answered ticket and delivers the reply.
  4. TicketStore.close() is called with the answer.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
import httpx

from src.escalation.ticket_client import TicketAPIClient
from src.escalation.ticket_schemas import TicketCreate, TicketRecord, TicketResponse, TicketStatus
from src.escalation.ticket_store import TicketStore
from src.escalation.poller import TicketPoller


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ticket_create_payload() -> TicketCreate:
    return TicketCreate(
        group_id=-100123456789,
        user_id=42,
        message_id=7,
        language="en",
        question="How do I reset my password?",
        conversation_summary="User asked about password reset.",
    )


@pytest.fixture
def tmp_store(tmp_path) -> TicketStore:
    return TicketStore(file_path=str(tmp_path / "tickets.json"))


# ---------------------------------------------------------------------------
# 7.2 — TicketAPIClient
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_ticket_sends_correct_payload(ticket_create_payload: TicketCreate) -> None:
    """create_ticket() POSTs the full payload and returns a TicketRecord."""
    base_url = "http://fake-ticket-api"

    with respx.mock(base_url=base_url) as mock:
        mock.post("/tickets").mock(
            return_value=httpx.Response(
                200,
                json={"ticket_id": "TKT-001", "status": "open"},
            )
        )

        client = TicketAPIClient(base_url=base_url, api_key="test-key")
        record = await client.create_ticket(ticket_create_payload)

    assert record.ticket_id == "TKT-001"
    assert record.status == TicketStatus.OPEN
    assert record.group_id == ticket_create_payload.group_id
    assert record.user_id == ticket_create_payload.user_id
    assert record.message_id == ticket_create_payload.message_id
    assert record.question == ticket_create_payload.question

    # Verify the request body contained the full payload
    sent_request = mock.calls[0].request
    import json
    body = json.loads(sent_request.content)
    assert body["question"] == ticket_create_payload.question
    assert body["language"] == "en"


@pytest.mark.asyncio
async def test_get_ticket_status_returns_answered(ticket_create_payload: TicketCreate) -> None:
    """get_ticket_status() returns TicketResponse with the human answer."""
    base_url = "http://fake-ticket-api"

    with respx.mock(base_url=base_url):
        respx.get("/tickets/TKT-001").mock(
            return_value=httpx.Response(
                200,
                json={
                    "ticket_id": "TKT-001",
                    "status": "answered",
                    "answer": "Go to Settings → Security → Reset Password.",
                },
            )
        )

        client = TicketAPIClient(base_url=base_url, api_key="test-key")
        response = await client.get_ticket_status("TKT-001")

    assert response.ticket_id == "TKT-001"
    assert response.status == TicketStatus.ANSWERED
    assert "Reset Password" in response.answer


# ---------------------------------------------------------------------------
# 7.3 — TicketStore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ticket_store_add_and_get_open(tmp_store: TicketStore) -> None:
    """add() stores a record; get_open_tickets() returns it."""
    record = TicketRecord(
        ticket_id="TKT-100",
        group_id=-100123,
        user_id=99,
        message_id=5,
        language="ru",
        question="Как сбросить пароль?",
    )
    await tmp_store.add(record)
    open_tickets = await tmp_store.get_open_tickets()
    assert len(open_tickets) == 1
    assert open_tickets[0].ticket_id == "TKT-100"


@pytest.mark.asyncio
async def test_ticket_store_close_removes_from_open(tmp_store: TicketStore) -> None:
    """close() marks the ticket CLOSED so it no longer appears in get_open_tickets()."""
    record = TicketRecord(
        ticket_id="TKT-200",
        group_id=-100123,
        user_id=99,
        message_id=6,
        language="en",
        question="How to upgrade?",
    )
    await tmp_store.add(record)
    await tmp_store.close("TKT-200", answer="Upgrade via Settings → Plan.")

    open_tickets = await tmp_store.get_open_tickets()
    assert len(open_tickets) == 0

    closed = await tmp_store.get("TKT-200")
    assert closed is not None
    assert closed.status == TicketStatus.CLOSED
    assert "Settings" in closed.answer


@pytest.mark.asyncio
async def test_ticket_store_persists_to_disk(tmp_path) -> None:
    """Records survive a store reload (JSON persistence)."""
    path = str(tmp_path / "tickets.json")
    store1 = TicketStore(file_path=path)
    record = TicketRecord(
        ticket_id="TKT-300",
        group_id=-1,
        user_id=1,
        message_id=1,
        language="uz",
        question="Parolni qanday tiklash mumkin?",
    )
    await store1.add(record)

    store2 = TicketStore(file_path=path)
    reloaded = await store2.get("TKT-300")
    assert reloaded is not None
    assert reloaded.question == record.question


# ---------------------------------------------------------------------------
# 7.4 — TicketPoller: end-to-end delivery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poller_delivers_answer_and_closes_ticket(tmp_store: TicketStore) -> None:
    """Poller fetches answered ticket, sends Telegram reply, and closes it."""
    record = TicketRecord(
        ticket_id="TKT-999",
        group_id=-100999,
        user_id=55,
        message_id=10,
        language="en",
        question="How do I export data?",
    )
    await tmp_store.add(record)

    # Mock ticket client
    mock_client = MagicMock(spec=TicketAPIClient)
    mock_client.get_ticket_status = AsyncMock(
        return_value=TicketResponse(
            ticket_id="TKT-999",
            status=TicketStatus.ANSWERED,
            answer="Use the Export button in the dashboard.",
        )
    )

    # Mock Telegram bot
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    poller = TicketPoller(
        store=tmp_store,
        client=mock_client,
        bot=mock_bot,
        interval=1,
    )

    # Run one poll cycle directly
    await poller._poll_once()

    # Verify Telegram reply was sent
    mock_bot.send_message.assert_awaited_once_with(
        chat_id=-100999,
        text="Use the Export button in the dashboard.",
        reply_to_message_id=10,
    )

    # Verify ticket was closed
    closed = await tmp_store.get("TKT-999")
    assert closed is not None
    assert closed.status == TicketStatus.CLOSED
    assert "Export" in closed.answer


@pytest.mark.asyncio
async def test_poller_stores_approved_memory_on_answer(tmp_store: TicketStore) -> None:
    """Poller stores the human-approved Q&A pair in datatruck_memory."""
    record = TicketRecord(
        ticket_id="TKT-MEM-1",
        group_id=-100777,
        user_id=42,
        message_id=15,
        language="en",
        question="How do I export data?",
    )
    await tmp_store.add(record)

    mock_client = MagicMock(spec=TicketAPIClient)
    mock_client.get_ticket_status = AsyncMock(
        return_value=TicketResponse(
            ticket_id="TKT-MEM-1",
            status=TicketStatus.ANSWERED,
            answer="Use the Export button in the dashboard.",
        )
    )

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    mock_memory = MagicMock()
    mock_memory.store = AsyncMock()

    poller = TicketPoller(
        store=tmp_store,
        client=mock_client,
        bot=mock_bot,
        approved_memory=mock_memory,
        interval=1,
    )
    await poller._poll_once()

    mock_memory.store.assert_awaited_once()
    stored = mock_memory.store.call_args[0][0]
    assert stored.question == "How do I export data?"
    assert stored.answer == "Use the Export button in the dashboard."
    assert stored.ticket_id == "TKT-MEM-1"
    assert stored.language == "en"


@pytest.mark.asyncio
async def test_poller_memory_failure_does_not_block_ticket_close(tmp_store: TicketStore) -> None:
    """If approved memory storage fails, the ticket should still be closed."""
    record = TicketRecord(
        ticket_id="TKT-MEM-2",
        group_id=-100666,
        user_id=43,
        message_id=16,
        language="ru",
        question="Как экспортировать данные?",
    )
    await tmp_store.add(record)

    mock_client = MagicMock(spec=TicketAPIClient)
    mock_client.get_ticket_status = AsyncMock(
        return_value=TicketResponse(
            ticket_id="TKT-MEM-2",
            status=TicketStatus.ANSWERED,
            answer="Нажмите кнопку Экспорт.",
        )
    )

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    mock_memory = MagicMock()
    mock_memory.store = AsyncMock(side_effect=RuntimeError("Qdrant down"))

    poller = TicketPoller(
        store=tmp_store,
        client=mock_client,
        bot=mock_bot,
        approved_memory=mock_memory,
        interval=1,
    )
    await poller._poll_once()

    # Ticket should still be closed despite memory failure
    closed = await tmp_store.get("TKT-MEM-2")
    assert closed is not None
    assert closed.status == TicketStatus.CLOSED


@pytest.mark.asyncio
async def test_poller_skips_open_tickets(tmp_store: TicketStore) -> None:
    """Poller does not send a reply when ticket is still OPEN."""
    record = TicketRecord(
        ticket_id="TKT-888",
        group_id=-100888,
        user_id=11,
        message_id=3,
        language="en",
        question="Is there a free trial?",
    )
    await tmp_store.add(record)

    mock_client = MagicMock(spec=TicketAPIClient)
    mock_client.get_ticket_status = AsyncMock(
        return_value=TicketResponse(
            ticket_id="TKT-888",
            status=TicketStatus.OPEN,
            answer="",
        )
    )

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    poller = TicketPoller(store=tmp_store, client=mock_client, bot=mock_bot, interval=1)
    await poller._poll_once()

    mock_bot.send_message.assert_not_awaited()

    still_open = await tmp_store.get_open_tickets()
    assert len(still_open) == 1
