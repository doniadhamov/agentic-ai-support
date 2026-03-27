"""Orchestrates Telegram→Zendesk sync: routes messages to tickets via AI ThreadRouter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from src.agent.schemas import ThreadRoutingAction, ThreadRoutingResult
from src.agent.thread_router import ThreadRouter
from src.config.settings import get_settings
from src.database.repositories import (
    get_active_threads_in_group,
    get_message_by_telegram_id,
    get_recent_messages,
    update_message_zendesk_ids,
)
from src.escalation.ticket_client import ZendeskTicketClient
from src.escalation.ticket_schemas import ZendeskComment, ZendeskTicketClosedError
from src.escalation.ticket_store import ConversationThreadStore

if TYPE_CHECKING:
    from src.escalation.profile_service import ZendeskProfileService


class ZendeskSyncService:
    """Syncs Telegram messages to Zendesk tickets using AI-powered thread routing."""

    def __init__(
        self,
        zendesk_client: ZendeskTicketClient,
        thread_store: ConversationThreadStore,
        thread_router: ThreadRouter,
        profile_service: ZendeskProfileService | None = None,
        bot_zendesk_user_id: int | None = None,
    ) -> None:
        self._zendesk = zendesk_client
        self._thread_store = thread_store
        self._router = thread_router
        self._profile_service = profile_service
        self._bot_zendesk_user_id = bot_zendesk_user_id

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
        first_name: str | None = None,
        last_name: str | None = None,
        tg_username: str | None = None,
    ) -> int | None:
        """Sync a Telegram message to Zendesk. Returns the Zendesk comment ID or None.

        Uses the AI ThreadRouter to determine which ticket to route the message to.
        """
        # Resolve Zendesk user via profile service
        zendesk_user_id: int | None = None
        if self._profile_service:
            try:
                from src.escalation.profile_service import ZendeskProfileService

                display_name = ZendeskProfileService.resolve_display_name(
                    first_name,
                    last_name,
                    tg_username,
                    user_id,
                )
                zendesk_user_id = await self._profile_service.get_or_create_zendesk_user(
                    telegram_user_id=user_id,
                    display_name=display_name,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("SyncService: failed to resolve Zendesk user — {}", exc)

        # Build custom_fields for telegram_chat_id
        settings = get_settings()
        custom_fields: list[dict] | None = None
        if settings.zendesk_telegram_chat_id_field_id:
            custom_fields = [
                {"id": settings.zendesk_telegram_chat_id_field_id, "value": str(chat_id)},
            ]

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
        recent_history = [f"{m['username'] or 'User'}: {m['text'][:200]}" for m in recent_msgs]

        # Route via AI
        routing = await self._router.route(
            message_text=text,
            message_category=message_category,
            reply_to_text=reply_to_text,
            reply_to_ticket_id=reply_to_ticket_id,
            active_tickets=active_tickets,
            recent_history=recent_history,
        )

        # Execute routing and handle closed-ticket recovery
        try:
            return await self._execute_routing(
                routing=routing,
                text=text,
                username=username,
                group_id=group_id,
                user_id=user_id,
                group_name=group_name,
                zendesk_user_id=zendesk_user_id,
                custom_fields=custom_fields,
                images=images,
                chat_id=chat_id,
                message_id=message_id,
            )
        except ZendeskTicketClosedError as exc:
            logger.warning(
                "SyncService: ticket {} is closed/solved, closing stale thread and re-routing",
                exc.ticket_id,
            )
            return await self._handle_closed_ticket_reroute(
                closed_ticket_id=exc.ticket_id,
                text=text,
                username=username,
                group_id=group_id,
                user_id=user_id,
                group_name=group_name,
                zendesk_user_id=zendesk_user_id,
                custom_fields=custom_fields,
                images=images,
                chat_id=chat_id,
                message_id=message_id,
                message_category=message_category,
                reply_to_text=reply_to_text,
                reply_to_ticket_id=reply_to_ticket_id,
                active_tickets=active_tickets,
                recent_history=recent_history,
            )

    # ------------------------------------------------------------------
    # Execute a routing decision
    # ------------------------------------------------------------------

    async def _execute_routing(
        self,
        routing: ThreadRoutingResult,
        text: str,
        username: str,
        group_id: int,
        user_id: int,
        group_name: str,
        zendesk_user_id: int | None,
        custom_fields: list[dict] | None,
        images: list[bytes] | None,
        chat_id: int,
        message_id: int,
    ) -> int | None:
        """Execute a routing decision: select/create ticket, post comment, update DB."""
        if routing.action == ThreadRoutingAction.SKIP_ZENDESK:
            logger.debug("SyncService: skipping Zendesk for message ({})", routing.reasoning[:60])
            return None

        # Determine target ticket
        zendesk_ticket_id: int
        is_new_ticket = False

        if routing.action == ThreadRoutingAction.ROUTE_TO_EXISTING and routing.ticket_id:
            zendesk_ticket_id = routing.ticket_id

        elif routing.action == ThreadRoutingAction.FOLLOW_UP and routing.follow_up_source_id:
            subject = text[:80] if text else f"Follow-up from {username}"
            comment_body = text or "(follow-up)"
            zendesk_ticket_id, is_new_ticket = await self._thread_store.create_followup_thread(
                group_id=group_id,
                user_id=user_id,
                group_name=group_name,
                subject=subject,
                body=comment_body,
                followup_source_id=routing.follow_up_source_id,
                requester_id=zendesk_user_id,
                author_id=zendesk_user_id,
                custom_fields=custom_fields,
            )

        else:
            # CREATE_NEW (or fallback)
            subject = text[:80] if text else f"Support request from {username}"
            comment_body = text or "(photo attached)"
            zendesk_ticket_id, is_new_ticket = await self._thread_store.get_or_create_thread(
                group_id=group_id,
                user_id=user_id,
                group_name=group_name,
                subject=subject,
                body=comment_body,
                requester_id=zendesk_user_id,
                author_id=zendesk_user_id,
                custom_fields=custom_fields,
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

        # Post comment to ticket (clean body — no [username]: prefix)
        if is_new_ticket:
            # Comment was already included in ticket creation, only post if attachments
            comment_id = 0
            if attachment_tokens:
                comment = ZendeskComment(
                    body="(attachments)",
                    public=True,
                    author_id=zendesk_user_id,
                    attachment_tokens=attachment_tokens,
                )
                comment_id = await self._zendesk.add_comment(
                    zendesk_ticket_id,
                    comment,
                    tags=["source_telegram"],
                    custom_fields=custom_fields,
                )
        else:
            comment_body = text or "(photo attached)"
            comment = ZendeskComment(
                body=comment_body,
                public=True,
                author_id=zendesk_user_id,
                attachment_tokens=attachment_tokens,
            )
            comment_id = await self._zendesk.add_comment(
                zendesk_ticket_id,
                comment,
                tags=["source_telegram"],
                custom_fields=custom_fields,
            )

        # Determine link_type
        link_type = "root" if is_new_ticket else "reply"

        # Update the message row with Zendesk IDs
        await update_message_zendesk_ids(
            chat_id=chat_id,
            message_id=message_id,
            zendesk_ticket_id=zendesk_ticket_id,
            zendesk_comment_id=comment_id if comment_id else None,
            link_type=link_type,
        )

        logger.info(
            "SyncService: synced message to ticket={} comment={} link_type={}",
            zendesk_ticket_id,
            comment_id,
            link_type,
        )
        return comment_id

    # ------------------------------------------------------------------
    # Handle closed-ticket re-routing
    # ------------------------------------------------------------------

    async def _handle_closed_ticket_reroute(
        self,
        closed_ticket_id: int,
        text: str,
        username: str,
        group_id: int,
        user_id: int,
        group_name: str,
        zendesk_user_id: int | None,
        custom_fields: list[dict] | None,
        images: list[bytes] | None,
        chat_id: int,
        message_id: int,
        message_category: str,
        reply_to_text: str | None,
        reply_to_ticket_id: int | None,
        active_tickets: list[dict],
        recent_history: list[str],
    ) -> int | None:
        """Close the stale thread and re-route the message via AI."""
        # 1. Close stale thread in DB
        closed_thread = await self._thread_store.close_thread_for_ticket(closed_ticket_id)
        closed_subject = closed_thread.subject if closed_thread else f"Ticket #{closed_ticket_id}"

        # 2. Build solved_tickets list and remove from active_tickets
        solved_tickets = [{"ticket_id": closed_ticket_id, "subject": closed_subject}]
        updated_active = [t for t in active_tickets if t["ticket_id"] != closed_ticket_id]

        # 3. Clear reply_to_ticket_id if it pointed to the closed ticket
        if reply_to_ticket_id == closed_ticket_id:
            reply_to_ticket_id = None

        # 4. Re-route with solved_tickets context
        new_routing = await self._router.route(
            message_text=text,
            message_category=message_category,
            reply_to_text=reply_to_text,
            reply_to_ticket_id=reply_to_ticket_id,
            active_tickets=updated_active,
            recent_history=recent_history,
            solved_tickets=solved_tickets,
        )

        logger.info(
            "SyncService: re-routed after 422 → action={} ticket_id={} follow_up_source_id={}",
            new_routing.action.value,
            new_routing.ticket_id,
            new_routing.follow_up_source_id,
        )

        # 5. Execute the new routing (no 422 recovery — let errors propagate)
        return await self._execute_routing(
            routing=new_routing,
            text=text,
            username=username,
            group_id=group_id,
            user_id=user_id,
            group_name=group_name,
            zendesk_user_id=zendesk_user_id,
            custom_fields=custom_fields,
            images=images,
            chat_id=chat_id,
            message_id=message_id,
        )

    # ------------------------------------------------------------------
    # Bot response sync
    # ------------------------------------------------------------------

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

        try:
            comment = ZendeskComment(
                body=f"[AI Bot]: {text}",
                public=True,
                author_id=self._bot_zendesk_user_id,
            )
            comment_id = await self._zendesk.add_comment(
                ticket_id,
                comment,
                tags=["source_telegram"],
            )
            logger.debug("SyncService: synced bot response to ticket={}", ticket_id)
            return comment_id
        except ZendeskTicketClosedError:
            logger.warning(
                "SyncService: ticket {} is closed, closing stale thread (bot response skipped)",
                ticket_id,
            )
            await self._thread_store.close_thread_for_ticket(ticket_id)
            return None
