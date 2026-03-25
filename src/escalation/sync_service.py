"""Orchestrates Telegram→Zendesk sync: routes messages to tickets via AI ThreadRouter."""

from __future__ import annotations

from loguru import logger

from src.agent.schemas import ThreadRoutingAction
from src.agent.thread_router import ThreadRouter
from src.database.repositories import (
    get_active_threads_in_group,
    get_message_by_telegram_id,
    get_recent_messages,
    update_message_zendesk_ids,
)
from src.escalation.ticket_client import ZendeskTicketClient
from src.escalation.ticket_schemas import ZendeskComment
from src.escalation.ticket_store import ConversationThreadStore


class ZendeskSyncService:
    """Syncs Telegram messages to Zendesk tickets using AI-powered thread routing."""

    def __init__(
        self,
        zendesk_client: ZendeskTicketClient,
        thread_store: ConversationThreadStore,
        thread_router: ThreadRouter,
    ) -> None:
        self._zendesk = zendesk_client
        self._thread_store = thread_store
        self._router = thread_router

    async def sync_message(
        self,
        group_id: int,
        user_id: int,
        group_name: str,
        username: str,
        text: str,
        message_category: str,
        chat_id: int,
        message_id: int,
        images: list[bytes] | None = None,
        reply_to_message_id: int | None = None,
        conversation_context: list[str] | None = None,
    ) -> int | None:
        """Sync a Telegram message to Zendesk. Returns the Zendesk comment ID or None.

        Uses the AI ThreadRouter to determine which ticket to route the message to.
        """
        # Gather context for the router
        reply_to_text: str | None = None
        reply_to_ticket_id: int | None = None

        if reply_to_message_id:
            replied_msg = await get_message_by_telegram_id(chat_id, reply_to_message_id)
            if replied_msg:
                reply_to_text = replied_msg.text
                reply_to_ticket_id = replied_msg.zendesk_ticket_id

        # Get active tickets in the group
        active_threads = await get_active_threads_in_group(group_id)
        active_tickets = [
            {
                "ticket_id": t.zendesk_ticket_id,
                "subject": t.subject,
            }
            for t in active_threads
        ]

        # Get recent history for the router
        recent_msgs = await get_recent_messages(chat_id, limit=30)
        recent_history = [
            f"{m['username'] or 'User'}: {m['text'][:200]}" for m in recent_msgs
        ]

        # Route via AI
        routing = await self._router.route(
            message_text=text,
            message_category=message_category,
            reply_to_text=reply_to_text,
            reply_to_ticket_id=reply_to_ticket_id,
            active_tickets=active_tickets,
            recent_history=recent_history,
        )

        if routing.action == ThreadRoutingAction.SKIP_ZENDESK:
            logger.debug("SyncService: skipping Zendesk for message ({})", routing.reasoning[:60])
            return None

        # Determine target ticket
        zendesk_ticket_id: int
        if routing.action == ThreadRoutingAction.ROUTE_TO_EXISTING and routing.ticket_id:
            zendesk_ticket_id = routing.ticket_id
        else:
            # Create new ticket
            subject = text[:80] if text else f"Support request from {username}"
            zendesk_ticket_id, _ = await self._thread_store.get_or_create_thread(
                group_id=group_id,
                user_id=user_id,
                group_name=group_name,
                subject=subject,
            )

        # Upload attachments if any
        attachment_tokens: list[str] = []
        if images:
            for i, img_data in enumerate(images):
                try:
                    token = await self._zendesk.upload_attachment(
                        filename=f"photo_{i + 1}.jpg",
                        content_type="image/jpeg",
                        data=img_data,
                    )
                    attachment_tokens.append(token)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("SyncService: failed to upload attachment — {}", exc)

        # Post comment to ticket
        comment_body = f"[{username}]: {text}" if text else f"[{username}]: (photo)"
        comment = ZendeskComment(
            body=comment_body,
            public=True,
            attachment_tokens=attachment_tokens,
        )

        comment_id = await self._zendesk.add_comment(zendesk_ticket_id, comment)

        # Update the message row with Zendesk IDs
        await update_message_zendesk_ids(
            chat_id=chat_id,
            message_id=message_id,
            zendesk_ticket_id=zendesk_ticket_id,
            zendesk_comment_id=comment_id if comment_id else None,
        )

        logger.info(
            "SyncService: synced message to ticket={} comment={}",
            zendesk_ticket_id, comment_id,
        )
        return comment_id

    async def sync_bot_response(
        self,
        group_id: int,
        user_id: int,
        text: str,
    ) -> int | None:
        """Post an AI bot response as a Zendesk comment on the user's active ticket."""
        ticket_id = await self._thread_store.get_active_ticket_id(group_id, user_id)
        if not ticket_id:
            logger.debug("SyncService: no active ticket for bot response, skipping")
            return None

        comment = ZendeskComment(
            body=f"[AI Bot]: {text}",
            public=True,
        )
        comment_id = await self._zendesk.add_comment(ticket_id, comment)
        logger.debug("SyncService: synced bot response to ticket={}", ticket_id)
        return comment_id

    async def sync_escalation_notice(
        self,
        group_id: int,
        user_id: int,
        notice_text: str,
    ) -> int | None:
        """Post an escalation notification as a Zendesk comment."""
        ticket_id = await self._thread_store.get_active_ticket_id(group_id, user_id)
        if not ticket_id:
            logger.debug("SyncService: no active ticket for escalation notice, skipping")
            return None

        comment = ZendeskComment(
            body=f"[ESCALATION]: {notice_text}",
            public=True,
        )
        comment_id = await self._zendesk.add_comment(ticket_id, comment)
        logger.info("SyncService: posted escalation notice to ticket={}", ticket_id)
        return comment_id
