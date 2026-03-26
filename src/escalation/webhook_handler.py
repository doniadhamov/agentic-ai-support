"""Zendesk→Telegram webhook handler: delivers agent responses back to Telegram groups."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from loguru import logger

from src.agent.ticket_summarizer import TicketSummarizer
from src.escalation.ticket_store import ConversationThreadStore
from src.memory.approved_memory import ApprovedMemory

if TYPE_CHECKING:
    from aiogram import Bot

_SUPPORTED_EVENT_TYPES = {
    "zen:event-type:ticket.comment_added",
    "zen:event-type:ticket.status_changed",
}

_SOURCE_TAG = "source_telegram"


class ZendeskWebhookHandler:
    """Handles incoming Zendesk webhook payloads."""

    def __init__(
        self,
        bot: Bot,
        thread_store: ConversationThreadStore,
        ticket_summarizer: TicketSummarizer,
        approved_memory: ApprovedMemory | None = None,
    ) -> None:
        self._bot = bot
        self._thread_store = thread_store
        self._summarizer = ticket_summarizer
        self._memory = approved_memory

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def handle_event(self, payload: dict) -> dict:
        """Route a Zendesk webhook event after common gate checks.

        Gate logic (in order):
        1. Event type must be comment_added or status_changed.
        2. Ticket must carry the ``source_telegram`` tag.
        3. If all gates pass, log the full event JSON for now.
        """
        event_type = payload.get("type", "")
        detail = payload.get("detail") or {}
        ticket_id = detail.get("id")
        tags: list[str] = detail.get("tags") or []

        # Gate 1 — supported event type
        if event_type not in _SUPPORTED_EVENT_TYPES:
            logger.debug(
                "Webhook: ignoring unsupported event type={} ticket={}",
                event_type,
                ticket_id,
            )
            return {"status": "ignored", "reason": f"unsupported event type: {event_type}"}

        # Gate 2 — source_telegram tag
        if _SOURCE_TAG not in tags:
            logger.debug(
                "Webhook: ignoring ticket={} without {} tag",
                ticket_id,
                _SOURCE_TAG,
            )
            return {"status": "ignored", "reason": "missing source_telegram tag"}

        # All gates passed — log the full event
        logger.info(
            "Webhook: matched event type={} ticket={} | payload:\n{}",
            event_type,
            ticket_id,
            json.dumps(payload, indent=2, ensure_ascii=False),
        )

        return {"status": "received", "ticket_id": ticket_id, "event_type": event_type}
