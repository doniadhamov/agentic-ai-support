"""Unit tests for GroupContext: sliding window, lock behaviour, ticket tracking."""

from __future__ import annotations

import asyncio

import pytest

from src.telegram.context.group_context import GroupContext, MessageRecord


def _record(
    message_id: int = 1,
    user_id: int = 100,
    username: str = "alice",
    text: str = "hello",
) -> MessageRecord:
    return MessageRecord(
        message_id=message_id,
        user_id=user_id,
        username=username,
        text=text,
    )


# ---------------------------------------------------------------------------
# Sliding window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_message_appends_to_window() -> None:
    ctx = GroupContext(chat_id=1, window_size=5)
    await ctx.add_message(_record(message_id=1, text="first"))
    await ctx.add_message(_record(message_id=2, text="second"))

    strings = await ctx.get_context_strings()
    assert strings == ["alice: first", "alice: second"]


@pytest.mark.asyncio
async def test_window_evicts_oldest_when_full() -> None:
    ctx = GroupContext(chat_id=1, window_size=3)

    for i in range(4):
        await ctx.add_message(_record(message_id=i, text=str(i)))

    strings = await ctx.get_context_strings()
    assert len(strings) == 3
    # The first message (text="0") should have been evicted
    assert "alice: 0" not in strings
    assert "alice: 1" in strings
    assert "alice: 3" in strings


@pytest.mark.asyncio
async def test_window_size_property() -> None:
    ctx = GroupContext(chat_id=1, window_size=10)
    assert ctx.window_size == 10


@pytest.mark.asyncio
async def test_empty_context_returns_empty_list() -> None:
    ctx = GroupContext(chat_id=1, window_size=5)
    strings = await ctx.get_context_strings()
    assert strings == []


# ---------------------------------------------------------------------------
# Context strings format
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_strings_format() -> None:
    ctx = GroupContext(chat_id=99, window_size=5)
    await ctx.add_message(_record(username="Bob", text="Need help with login"))
    await ctx.add_message(_record(username="Alice", text="Which screen?"))

    strings = await ctx.get_context_strings()
    assert strings[0] == "Bob: Need help with login"
    assert strings[1] == "Alice: Which screen?"


# ---------------------------------------------------------------------------
# Ticket tracking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_and_close_ticket() -> None:
    ctx = GroupContext(chat_id=1, window_size=5)

    await ctx.add_ticket(message_id=42, ticket_id="TKT-001")
    assert ctx.open_tickets[42] == "TKT-001"

    await ctx.close_ticket(message_id=42)
    assert 42 not in ctx.open_tickets


@pytest.mark.asyncio
async def test_close_nonexistent_ticket_is_noop() -> None:
    ctx = GroupContext(chat_id=1, window_size=5)
    # Should not raise
    await ctx.close_ticket(message_id=999)
    assert ctx.open_tickets == {}


@pytest.mark.asyncio
async def test_multiple_open_tickets() -> None:
    ctx = GroupContext(chat_id=1, window_size=5)

    await ctx.add_ticket(message_id=1, ticket_id="TKT-001")
    await ctx.add_ticket(message_id=2, ticket_id="TKT-002")

    assert len(ctx.open_tickets) == 2
    await ctx.close_ticket(message_id=1)
    assert len(ctx.open_tickets) == 1
    assert ctx.open_tickets[2] == "TKT-002"


# ---------------------------------------------------------------------------
# Concurrent access (lock behaviour)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_add_messages_are_serialised() -> None:
    """Adding messages concurrently must not corrupt the deque."""
    ctx = GroupContext(chat_id=1, window_size=100)

    async def add(i: int) -> None:
        await ctx.add_message(_record(message_id=i, text=str(i)))

    await asyncio.gather(*[add(i) for i in range(50)])

    strings = await ctx.get_context_strings()
    assert len(strings) == 50


@pytest.mark.asyncio
async def test_concurrent_ticket_ops_are_safe() -> None:
    ctx = GroupContext(chat_id=1, window_size=5)

    async def add_close(i: int) -> None:
        await ctx.add_ticket(message_id=i, ticket_id=f"TKT-{i:03d}")
        await ctx.close_ticket(message_id=i)

    await asyncio.gather(*[add_close(i) for i in range(20)])
    assert ctx.open_tickets == {}


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repr_contains_chat_id() -> None:
    ctx = GroupContext(chat_id=123, window_size=5)
    assert "123" in repr(ctx)
