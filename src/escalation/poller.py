"""TicketPoller: background task that polls open tickets and delivers answers via Telegram."""

from __future__ import annotations

import asyncio

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from loguru import logger

from src.config.settings import get_settings
from src.escalation.ticket_client import TicketAPIClient
from src.escalation.ticket_schemas import TicketRecord, TicketStatus
from src.escalation.ticket_store import TicketStore
from src.memory.approved_memory import ApprovedMemory
from src.memory.memory_schemas import ApprovedAnswer


class TicketPoller:
    """Polls open tickets on a fixed interval and forwards answered tickets to Telegram.

    When a ticket transitions to ``answered``:
    1. Sends the human answer as a reply to the original Telegram message.
    2. Stores the approved Q&A pair in ``datatruck_memory`` for future retrieval.
    3. Marks the ticket ``CLOSED`` in the :class:`TicketStore`.

    Args:
        store: Shared :class:`TicketStore` instance.
        client: :class:`TicketAPIClient` for status checks.
        bot: Aiogram :class:`Bot` used to send Telegram replies.
        approved_memory: :class:`ApprovedMemory` for storing human-approved Q&A pairs.
        interval: Polling interval in seconds (defaults to the settings value).
    """

    def __init__(
        self,
        store: TicketStore,
        client: TicketAPIClient,
        bot: Bot,
        approved_memory: ApprovedMemory | None = None,
        interval: int | None = None,
    ) -> None:
        self._store = store
        self._client = client
        self._bot = bot
        self._approved_memory = approved_memory
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
                await self._deliver_answer(
                    record.ticket_id, record.group_id, record.message_id, response.answer
                )
                await self._store_approved_memory(record, response.answer)
                await self._store.close(record.ticket_id, answer=response.answer)

    async def _store_approved_memory(self, record: TicketRecord, answer: str) -> None:
        """Store the human-approved Q&A pair in ``datatruck_memory``."""
        if not self._approved_memory:
            return
        try:
            await self._approved_memory.store(
                ApprovedAnswer(
                    question=record.question,
                    answer=answer,
                    language=record.language,
                    ticket_id=record.ticket_id,
                    group_id=record.group_id,
                )
            )
            logger.info("TicketPoller: stored approved memory for ticket_id={}", record.ticket_id)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "TicketPoller: failed to store approved memory for ticket_id={} — {}",
                record.ticket_id,
                exc,
            )

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
        except TelegramBadRequest as exc:
            if "can't parse entities" in str(exc):
                logger.warning(
                    "TicketPoller: Markdown parse failed for ticket_id={}, retrying plain text",
                    ticket_id,
                )
                await self._bot.send_message(
                    chat_id=group_id,
                    text=answer,
                    reply_to_message_id=message_id,
                    parse_mode=None,
                )
            else:
                logger.error(
                    "TicketPoller: failed to deliver answer for ticket_id={} — {}", ticket_id, exc
                )
                return
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "TicketPoller: failed to deliver answer for ticket_id={} — {}", ticket_id, exc
            )
            return

        logger.info(
            "TicketPoller: delivered answer for ticket_id={} group_id={} message_id={}",
            ticket_id,
            group_id,
            message_id,
        )
