"""Zendesk→Telegram webhook handler: delivers agent responses back to Telegram groups."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from loguru import logger

from src.agent.ticket_summarizer import TicketSummarizer
from src.database.repositories import get_messages_by_ticket_id, get_root_message_id, save_message
from src.escalation.ticket_store import ConversationThreadStore
from src.memory.approved_memory import ApprovedMemory
from src.memory.memory_schemas import ApprovedAnswer

if TYPE_CHECKING:
    from aiogram import Bot

_SUPPORTED_EVENT_TYPES = {
    "zen:event-type:ticket.comment_added",
    "zen:event-type:ticket.status_changed",
}

_SOURCE_TAG = "source_telegram"

_CLOSED_STATUSES = {"solved", "closed"}


class ZendeskWebhookHandler:
    """Handles incoming Zendesk webhook payloads."""

    def __init__(
        self,
        bot: Bot,
        thread_store: ConversationThreadStore,
        ticket_summarizer: TicketSummarizer,
        approved_memory: ApprovedMemory | None = None,
        bot_zendesk_user_id: int | None = None,
        api_account_user_id: int | None = None,
    ) -> None:
        self._bot = bot
        self._thread_store = thread_store
        self._summarizer = ticket_summarizer
        self._memory = approved_memory
        self._bot_zendesk_user_id = bot_zendesk_user_id
        self._api_account_user_id = api_account_user_id

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def handle_event(self, payload: dict) -> dict:
        """Route a Zendesk webhook event after common gate checks.

        Gate logic (in order):
        1. Event type must be comment_added or status_changed.
        2. Ticket must carry the ``source_telegram`` tag.
        3. Dispatch to comment or status handler.
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

        logger.info(
            "Webhook: matched event type={} ticket={} | payload:\n{}",
            event_type,
            ticket_id,
            json.dumps(payload, indent=2, ensure_ascii=False),
        )

        # Dispatch by event type
        if event_type == "zen:event-type:ticket.comment_added":
            return await self._handle_comment_added(payload, detail, ticket_id)

        if event_type == "zen:event-type:ticket.status_changed":
            return await self._handle_status_changed(payload, detail, ticket_id)

        return {"status": "received", "ticket_id": ticket_id, "event_type": event_type}

    # ------------------------------------------------------------------
    # Comment added — deliver agent reply to Telegram
    # ------------------------------------------------------------------

    async def _handle_comment_added(
        self, payload: dict, detail: dict, ticket_id: str | int
    ) -> dict:
        event = payload.get("event") or {}
        comment = event.get("comment") or {}
        body = comment.get("body", "").strip()
        author = comment.get("author") or {}
        author_id = str(author.get("id", ""))
        author_name = author.get("name", "Zendesk Agent")

        # Gate — skip comments made via our API account (catches all bot-synced
        # comments regardless of author_id: user messages, bot replies, etc.)
        actor_id = str((payload.get("detail") or {}).get("actor_id", ""))
        if self._api_account_user_id and actor_id == str(self._api_account_user_id):
            logger.debug(
                "Webhook: skipping API-originated comment on ticket={} actor={} author={}",
                ticket_id,
                actor_id,
                author_name,
            )
            return {"status": "ignored", "reason": "API-originated comment"}

        # Gate — skip bot's own comments to avoid echo loops
        if self._bot_zendesk_user_id and author_id == str(self._bot_zendesk_user_id):
            logger.debug("Webhook: skipping bot's own comment on ticket={}", ticket_id)
            return {"status": "ignored", "reason": "bot's own comment"}

        # Gate — must have a body
        if not body:
            logger.debug("Webhook: skipping empty comment on ticket={}", ticket_id)
            return {"status": "ignored", "reason": "empty comment body"}

        # Look up conversation thread → Telegram group
        ticket_id_int = int(ticket_id)
        thread = await self._thread_store.get_thread_for_ticket(ticket_id_int)
        if thread is None:
            logger.warning(
                "Webhook: no conversation thread for ticket={}, cannot deliver to Telegram",
                ticket_id,
            )
            return {"status": "ignored", "reason": "no conversation thread found"}

        group_id = thread.group_id

        # Find the original user message to reply to
        reply_to = await get_root_message_id(ticket_id_int, group_id)

        # Format and send to Telegram (plain text to avoid MarkdownV2 escaping issues)
        telegram_text = f"🎫 Ticket #{ticket_id}\n💬 Agent: {author_name}:\n\n{body}"
        try:
            sent_msg = await self._bot.send_message(
                chat_id=group_id,
                text=telegram_text,
                parse_mode=None,
                reply_to_message_id=reply_to,
            )
            logger.info(
                "Webhook: delivered agent comment to Telegram group={} ticket={} msg_id={}",
                group_id,
                ticket_id,
                sent_msg.message_id,
            )
        except Exception as exc:
            logger.error(
                "Webhook: failed to send to Telegram group={} ticket={}: {}",
                group_id,
                ticket_id,
                exc,
            )
            return {"status": "error", "reason": f"telegram send failed: {exc}"}

        # Persist the agent message in DB
        try:
            await save_message(
                chat_id=group_id,
                message_id=sent_msg.message_id,
                user_id=0,
                username=author_name,
                text=body,
                source="zendesk",
                zendesk_ticket_id=ticket_id_int,
                link_type="mirror",
            )
        except Exception as exc:
            logger.error("Webhook: failed to save message in DB: {}", exc)

        return {"status": "delivered", "ticket_id": ticket_id, "group_id": group_id}

    # ------------------------------------------------------------------
    # Status changed — close thread + summarize on solved/closed
    # ------------------------------------------------------------------

    async def _handle_status_changed(
        self, payload: dict, detail: dict, ticket_id: str | int
    ) -> dict:
        new_status = str(detail.get("status", "")).lower()

        if new_status not in _CLOSED_STATUSES:
            logger.debug(
                "Webhook: ticket={} status changed to {} (not closed), ignoring",
                ticket_id,
                new_status,
            )
            return {"status": "received", "ticket_id": ticket_id, "event_type": "status_changed"}

        ticket_id_int = int(ticket_id)

        # Close the conversation thread
        thread = await self._thread_store.close_thread_for_ticket(ticket_id_int)
        if thread is None:
            logger.warning("Webhook: no thread to close for ticket={}", ticket_id)
            return {"status": "received", "ticket_id": ticket_id, "event_type": "status_changed"}

        # Summarize and store in memory
        if self._memory is not None:
            try:
                messages = await get_messages_by_ticket_id(ticket_id_int)
                if messages:
                    summary = await self._summarizer.summarize(messages)
                    await self._memory.store(
                        ApprovedAnswer(
                            question=summary["question"],
                            answer=summary["answer"],
                            ticket_id=ticket_id_int,
                            group_id=thread.group_id,
                        )
                    )
                    logger.info(
                        "Webhook: stored memory for closed ticket={} q={!r}",
                        ticket_id,
                        summary["question"][:60],
                    )
            except Exception as exc:
                logger.error(
                    "Webhook: failed to summarize/store memory for ticket={}: {}",
                    ticket_id,
                    exc,
                )

        return {
            "status": "closed",
            "ticket_id": ticket_id,
            "event_type": "status_changed",
        }
