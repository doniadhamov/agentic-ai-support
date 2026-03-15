"""TicketPoller: background task that polls open tickets and delivers answers via Telegram."""

from __future__ import annotations

import asyncio

from aiogram import Bot
from loguru import logger

from src.config.settings import get_settings
from src.escalation.ticket_client import TicketAPIClient
from src.escalation.ticket_schemas import TicketStatus
from src.escalation.ticket_store import TicketStore


class TicketPoller:
    """Polls open tickets on a fixed interval and forwards answered tickets to Telegram.

    When a ticket transitions to ``answered``:
    1. Sends the human answer as a reply to the original Telegram message.
    2. Marks the ticket ``CLOSED`` in the :class:`TicketStore`.

    Args:
        store: Shared :class:`TicketStore` instance.
        client: :class:`TicketAPIClient` for status checks.
        bot: Aiogram :class:`Bot` used to send Telegram replies.
        interval: Polling interval in seconds (defaults to the settings value).
    """

    def __init__(
        self,
        store: TicketStore,
        client: TicketAPIClient,
        bot: Bot,
        interval: int | None = None,
    ) -> None:
        self._store = store
        self._client = client
        self._bot = bot
        self._interval = interval or get_settings().ticket_poll_interval_seconds

    async def run(self) -> None:
        """Infinite polling loop.  Run as a background asyncio task."""
        logger.info("TicketPoller started (interval={}s)", self._interval)
        while True:
            await asyncio.sleep(self._interval)
            await self._poll_once()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _poll_once(self) -> None:
        """Check all open tickets and deliver any answered ones."""
        open_tickets = await self._store.get_open_tickets()
        if not open_tickets:
            return

        logger.debug("TicketPoller: checking {} open ticket(s)", len(open_tickets))

        for record in open_tickets:
            try:
                response = await self._client.get_ticket_status(record.ticket_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "TicketPoller: failed to fetch ticket_id={} — {}", record.ticket_id, exc
                )
                continue

            if response.status == TicketStatus.ANSWERED and response.answer:
                await self._deliver_answer(record.ticket_id, record.group_id, record.message_id, response.answer)
                await self._store.close(record.ticket_id, answer=response.answer)

    async def _deliver_answer(
        self,
        ticket_id: str,
        group_id: int,
        message_id: int,
        answer: str,
    ) -> None:
        """Send the human answer as a Telegram reply to the original message."""
        try:
            await self._bot.send_message(
                chat_id=group_id,
                text=answer,
                reply_to_message_id=message_id,
            )
            logger.info(
                "TicketPoller: delivered answer for ticket_id={} group_id={} message_id={}",
                ticket_id,
                group_id,
                message_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "TicketPoller: failed to deliver answer for ticket_id={} — {}", ticket_id, exc
            )
