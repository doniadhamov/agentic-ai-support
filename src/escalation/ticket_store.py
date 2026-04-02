"""Conversation thread store — maps Telegram conversations to Zendesk tickets (PostgreSQL only)."""

from __future__ import annotations

from loguru import logger

from src.database.models import ConversationThread
from src.database.repositories import (
    close_thread,
    create_thread,
    get_active_thread,
    get_active_threads_in_group,
    get_thread_by_zendesk_ticket_id,
    touch_thread,
)
from src.escalation.ticket_client import ZendeskTicketClient
from src.escalation.ticket_schemas import ZendeskTicketCreate


class ConversationThreadStore:
    """Manages conversation threads backed by PostgreSQL.

    Each thread maps a Telegram group conversation to a Zendesk ticket.
    """

    def __init__(self, zendesk_client: ZendeskTicketClient) -> None:
        self._zendesk = zendesk_client

    async def get_or_create_thread(
        self,
        group_id: int,
        user_id: int,
        group_name: str,
        subject: str,
        body: str | None = None,
        requester_id: int | None = None,
        author_id: int | None = None,
        custom_fields: list[dict] | None = None,
    ) -> tuple[int, bool]:
        """Get the active thread or create a new one with a Zendesk ticket.

        Returns:
            Tuple of (zendesk_ticket_id, is_new).
        """
        existing = await get_active_thread(group_id, user_id)
        if existing is not None:
            await touch_thread(existing.id)
            return existing.zendesk_ticket_id, False

        ticket_id = await self._zendesk.create_ticket(
            ZendeskTicketCreate(
                subject=subject,
                body=body or f"New conversation from Telegram group: {group_name}",
                requester_id=requester_id,
                author_id=author_id,
                tags=["source_telegram"],
                custom_fields=custom_fields,
            )
        )

        await create_thread(
            group_id=group_id,
            user_id=user_id,
            zendesk_ticket_id=ticket_id,
            subject=subject,
        )

        logger.info(
            "ConversationThreadStore: created thread group={} user={} ticket={}",
            group_id,
            user_id,
            ticket_id,
        )
        return ticket_id, True

    async def close_thread_for_ticket(self, zendesk_ticket_id: int) -> ConversationThread | None:
        """Close the thread associated with a Zendesk ticket.

        Returns:
            The closed ConversationThread, or None if not found.
        """
        thread = await get_thread_by_zendesk_ticket_id(zendesk_ticket_id)
        if thread is None:
            logger.warning(
                "ConversationThreadStore: no thread found for zendesk_ticket_id={}",
                zendesk_ticket_id,
            )
            return None

        await close_thread(thread.id)
        logger.info(
            "ConversationThreadStore: closed thread id={} ticket={}",
            thread.id,
            zendesk_ticket_id,
        )
        return thread

    async def create_followup_thread(
        self,
        group_id: int,
        user_id: int,
        group_name: str,
        subject: str,
        body: str,
        followup_source_id: int,
        requester_id: int | None = None,
        author_id: int | None = None,
        custom_fields: list[dict] | None = None,
    ) -> tuple[int, bool]:
        """Create a Zendesk follow-up ticket linked to a closed ticket, and a new DB thread.

        Returns:
            Tuple of (zendesk_ticket_id, True).
        """
        ticket_id = await self._zendesk.create_ticket(
            ZendeskTicketCreate(
                subject=subject,
                body=body,
                requester_id=requester_id,
                author_id=author_id,
                tags=["source_telegram", "follow_up"],
                custom_fields=custom_fields,
                via_followup_source_id=followup_source_id,
            )
        )

        await create_thread(
            group_id=group_id,
            user_id=user_id,
            zendesk_ticket_id=ticket_id,
            subject=subject,
        )

        logger.info(
            "ConversationThreadStore: created follow-up thread group={} ticket={} followup_of={}",
            group_id,
            ticket_id,
            followup_source_id,
        )
        return ticket_id, True

    async def get_active_ticket_id(self, group_id: int, user_id: int) -> int | None:
        """Return the Zendesk ticket ID for the user's active thread, or None."""
        thread = await get_active_thread(group_id, user_id)
        return thread.zendesk_ticket_id if thread else None

    async def get_all_active_threads(self) -> list[ConversationThread]:
        """Return all active threads across all groups (for admin/monitoring)."""
        from sqlalchemy import select

        from src.database.engine import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            stmt = select(ConversationThread).where(
                ConversationThread.status.in_(["open", "pending"]),
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_active_threads_for_group(self, group_id: int) -> list[ConversationThread]:
        """Return all active threads in a specific group."""
        return await get_active_threads_in_group(group_id)

    async def get_thread_for_ticket(self, zendesk_ticket_id: int) -> ConversationThread | None:
        """Look up a thread by Zendesk ticket ID."""
        return await get_thread_by_zendesk_ticket_id(zendesk_ticket_id)
