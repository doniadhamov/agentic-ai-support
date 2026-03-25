"""Zendesk→Telegram webhook handler: delivers agent responses back to Telegram groups."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from src.agent.ticket_summarizer import TicketSummarizer
from src.config.settings import get_settings
from src.database.repositories import (
    get_recent_messages,
    get_thread_by_zendesk_ticket_id,
    save_message,
)
from src.escalation.ticket_store import ConversationThreadStore
from src.memory.approved_memory import ApprovedMemory

if TYPE_CHECKING:
    from aiogram import Bot


class ZendeskWebhookHandler:
    """Handles incoming Zendesk webhook payloads when an agent adds a comment."""

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

    async def handle_comment(self, payload: dict) -> dict:
        """Process a Zendesk webhook payload for a new comment.

        Expected payload keys:
            ticket_id (int): Zendesk ticket ID
            comment_body (str): The comment text
            author_id (int): Zendesk user ID of the comment author
            ticket_status (str, optional): Current ticket status

        Returns:
            Dict with processing result.
        """
        settings = get_settings()

        ticket_id = payload.get("ticket_id")
        comment_body = payload.get("comment_body", "")
        author_id = payload.get("author_id")
        ticket_status = payload.get("ticket_status", "")

        if not ticket_id or not comment_body:
            logger.warning("Webhook: missing ticket_id or comment_body")
            return {"status": "ignored", "reason": "missing fields"}

        # Skip bot's own comments
        if author_id and author_id == settings.zendesk_bot_user_id:
            logger.debug("Webhook: ignoring own comment on ticket={}", ticket_id)
            return {"status": "ignored", "reason": "own comment"}

        # Look up the conversation thread
        thread = await get_thread_by_zendesk_ticket_id(ticket_id)
        if not thread:
            logger.warning("Webhook: no thread found for ticket_id={}", ticket_id)
            return {"status": "ignored", "reason": "unknown ticket"}

        group_id = thread.group_id

        # Store the agent message in DB
        await save_message(
            chat_id=group_id,
            message_id=0,  # No Telegram message ID yet
            user_id=0,  # Zendesk agent, not a Telegram user
            username="Zendesk Agent",
            text=comment_body,
            source="zendesk",
            zendesk_ticket_id=ticket_id,
        )

        # Send the agent's response to the Telegram group
        try:
            sent = await self._bot.send_message(
                chat_id=group_id,
                text=comment_body,
            )
            logger.info(
                "Webhook: delivered agent response to group={} ticket={}",
                group_id, ticket_id,
            )

            # Update the stored message with the Telegram message ID
            from src.database.repositories import update_message_zendesk_ids

            await update_message_zendesk_ids(
                chat_id=group_id,
                message_id=sent.message_id,
                zendesk_ticket_id=ticket_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Webhook: failed to send message to Telegram — {}", exc)
            return {"status": "error", "reason": str(exc)}

        # Handle ticket closure
        if ticket_status in ("solved", "closed"):
            await self._handle_ticket_close(ticket_id, group_id)

        return {"status": "delivered", "group_id": group_id}

    async def _handle_ticket_close(self, ticket_id: int, group_id: int) -> None:
        """Close the thread and summarize the conversation for approved memory."""
        # Close the thread
        thread = await self._thread_store.close_thread_for_ticket(ticket_id)
        if not thread:
            return

        logger.info("Webhook: ticket {} closed, summarizing conversation", ticket_id)

        # Fetch conversation messages for summarization
        try:
            messages = await get_recent_messages(group_id, limit=100)
            if not messages:
                return

            # Summarize and store in approved memory
            summary = await self._summarizer.summarize(messages)

            if self._memory and summary.get("question") and summary.get("answer"):
                await self._memory.store(
                    question=summary["question"],
                    answer=summary["answer"],
                )
                logger.info(
                    "Webhook: stored resolved Q&A in memory for ticket={}",
                    ticket_id,
                )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Webhook: failed to summarize/store ticket={} — {}",
                ticket_id, exc,
            )
