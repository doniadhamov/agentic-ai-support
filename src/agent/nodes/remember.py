"""Remember node — update working memory + sync to Zendesk + log decision.

Runs on ALL paths (answer, ignore, wait, escalate).
Handles bidirectional Zendesk sync: user message → ticket/comment, bot response → comment.
"""

from __future__ import annotations

import time

from aiogram import Bot
from loguru import logger

from src.agent.state import SupportState
from src.database.repositories import (
    save_bot_decision,
    save_message,
    touch_thread,
    update_message_file_description,
    update_message_zendesk_ids,
)
from src.escalation.profile_service import ZendeskProfileService
from src.escalation.ticket_client import ZendeskTicketClient
from src.escalation.ticket_schemas import (
    ZendeskComment,
    ZendeskTicketClosedError,
)
from src.escalation.ticket_store import ConversationThreadStore


async def remember_node(
    state: SupportState,
    bot: Bot | None = None,
    zendesk_client: ZendeskTicketClient | None = None,
    profile_service: ZendeskProfileService | None = None,
    thread_store: ConversationThreadStore | None = None,
    bot_zendesk_user_id: int = 0,
) -> dict:
    """Persist state changes, sync to Zendesk, and log decision."""
    t0 = time.monotonic()

    group_id = int(state["group_id"])
    group_name = state.get("group_name", str(group_id))
    sender_id = int(state["sender_id"])
    sender_name = state.get("sender_name", str(sender_id))
    message_id = state["telegram_message_id"]
    raw_text = state.get("raw_text", "")
    action = state.get("action", "ignore")
    ticket_action = state.get("ticket_action", "skip")
    urgency = state.get("urgency", "normal")
    target_ticket_id = state.get("target_ticket_id")
    follow_up_source_id = state.get("follow_up_source_id")
    extracted_question = state.get("extracted_question")
    images = state.get("images", [])

    synced_ticket_id: int | None = None
    synced_comment_id: int | None = None
    link_type: str | None = None

    # 1. Update file_description on the user's message (if think produced one)
    file_description = state.get("file_description")
    if file_description:
        try:
            await update_message_file_description(group_id, message_id, file_description)
        except Exception as exc:  # noqa: BLE001
            logger.warning("remember: failed to update file_description: {}", exc)

    # 2. ZENDESK SYNC (user's message)
    zendesk_enabled = zendesk_client is not None and thread_store is not None
    if zendesk_enabled and ticket_action != "skip":
        try:
            synced_ticket_id, synced_comment_id, link_type = await _sync_user_message(
                state=state,
                zendesk_client=zendesk_client,
                profile_service=profile_service,
                thread_store=thread_store,
                group_id=group_id,
                group_name=group_name,
                sender_id=sender_id,
                sender_name=sender_name,
                raw_text=raw_text,
                images=images,
                ticket_action=ticket_action,
                target_ticket_id=target_ticket_id,
                follow_up_source_id=follow_up_source_id,
                extracted_question=extracted_question,
                urgency=urgency,
                bot=bot,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("remember: Zendesk sync failed: {}", exc)

    # 3. Update user's message row in DB with Zendesk IDs
    if synced_ticket_id:
        try:
            await update_message_zendesk_ids(
                chat_id=group_id,
                message_id=message_id,
                zendesk_ticket_id=synced_ticket_id,
                zendesk_comment_id=synced_comment_id,
                link_type=link_type,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("remember: failed to update message zendesk IDs: {}", exc)

    # 4. ZENDESK SYNC (bot's response — only if bot replied in Telegram)
    bot_response_text = state.get("bot_response_text")
    bot_response_message_id = state.get("bot_response_message_id")

    if zendesk_enabled and bot_response_text and synced_ticket_id:
        try:
            bot_comment_id = await zendesk_client.add_comment(
                ticket_id=synced_ticket_id,
                comment=ZendeskComment(
                    body=bot_response_text,
                    public=True,
                    author_id=bot_zendesk_user_id or None,
                ),
            )
            logger.debug(
                "remember: synced bot response to ticket={} comment={}",
                synced_ticket_id,
                bot_comment_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("remember: failed to sync bot response to Zendesk: {}", exc)

    # 5. Save bot's response to DB (so perceive sees it in conversation_history)
    if bot_response_message_id and bot_response_text:
        try:
            await save_message(
                chat_id=group_id,
                message_id=bot_response_message_id,
                user_id=0,  # bot
                username="DataTruck Support",
                text=bot_response_text,
                source="bot",
                reply_to_message_id=message_id,
                zendesk_ticket_id=synced_ticket_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("remember: failed to save bot response to DB: {}", exc)

    # 6. Log decision for dashboard analytics
    try:
        total_ms = (
            (state.get("perceive_ms") or 0)
            + (state.get("think_ms") or 0)
            + (state.get("retrieve_ms") or 0)
            + (state.get("generate_ms") or 0)
        )
        await save_bot_decision(
            group_id=group_id,
            user_id=sender_id,
            message_id=message_id,
            message_text=raw_text,
            action=action,
            ticket_action=ticket_action,
            language=state.get("language", "en"),
            urgency=urgency,
            reasoning=state.get("decision_reasoning", ""),
            file_description=file_description,
            target_ticket_id=synced_ticket_id or target_ticket_id,
            extracted_question=extracted_question,
            answer_text=state.get("answer_text"),
            retrieval_confidence=state.get("retrieval_confidence"),
            needs_escalation=state.get("needs_escalation", False),
            perceive_ms=state.get("perceive_ms"),
            think_ms=state.get("think_ms"),
            retrieve_ms=state.get("retrieve_ms"),
            generate_ms=state.get("generate_ms"),
            total_ms=total_ms,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("remember: failed to log decision: {}", exc)

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    logger.debug(
        "remember: action={} ticket_action={} ticket={} elapsed={}ms",
        action,
        ticket_action,
        synced_ticket_id,
        elapsed_ms,
    )

    return {
        "synced_ticket_id": synced_ticket_id,
        "synced_comment_id": synced_comment_id,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _sync_user_message(
    *,
    state: SupportState,
    zendesk_client: ZendeskTicketClient,
    profile_service: ZendeskProfileService | None,
    thread_store: ConversationThreadStore,
    group_id: int,
    group_name: str,
    sender_id: int,
    sender_name: str,
    raw_text: str,
    images: list[bytes],
    ticket_action: str,
    target_ticket_id: int | None,
    follow_up_source_id: int | None,
    extracted_question: str | None,
    urgency: str,
    bot: Bot | None,
) -> tuple[int | None, int | None, str | None]:
    """Sync the user's message to Zendesk. Returns (ticket_id, comment_id, link_type)."""
    from src.config.settings import get_settings

    settings = get_settings()

    # Resolve Zendesk user for the sender
    requester_id: int | None = None
    if profile_service is not None:
        try:
            requester_id = await profile_service.get_or_create_zendesk_user(
                telegram_user_id=sender_id,
                display_name=sender_name,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("remember: failed to resolve Zendesk user: {}", exc)

    # Upload images as Zendesk attachments
    attachment_tokens = await _upload_attachments(zendesk_client, images)

    # Build custom fields (telegram_chat_id)
    custom_fields: list[dict] | None = None
    if settings.zendesk_telegram_chat_id_field_id:
        custom_fields = [
            {"id": int(settings.zendesk_telegram_chat_id_field_id), "value": str(group_id)}
        ]

    subject = (extracted_question or raw_text)[:80] or "Telegram support request"

    if ticket_action == "route_existing" and target_ticket_id:
        return await _route_to_existing_ticket(
            zendesk_client=zendesk_client,
            thread_store=thread_store,
            target_ticket_id=target_ticket_id,
            raw_text=raw_text,
            requester_id=requester_id,
            attachment_tokens=attachment_tokens,
            urgency=urgency,
            # Fallback params for create_new recovery
            group_id=group_id,
            group_name=group_name,
            sender_id=sender_id,
            subject=subject,
            custom_fields=custom_fields,
        )

    if ticket_action == "create_new":
        return await _create_new_ticket(
            thread_store=thread_store,
            group_id=group_id,
            group_name=group_name,
            sender_id=sender_id,
            subject=subject,
            raw_text=raw_text,
            requester_id=requester_id,
            attachment_tokens=attachment_tokens,
            custom_fields=custom_fields,
            urgency=urgency,
        )

    if ticket_action == "follow_up" and follow_up_source_id:
        return await _create_follow_up_ticket(
            thread_store=thread_store,
            group_id=group_id,
            group_name=group_name,
            sender_id=sender_id,
            subject=f"Follow-up: {subject}",
            raw_text=raw_text,
            follow_up_source_id=follow_up_source_id,
            requester_id=requester_id,
            attachment_tokens=attachment_tokens,
            custom_fields=custom_fields,
        )

    return None, None, None


async def _route_to_existing_ticket(
    *,
    zendesk_client: ZendeskTicketClient,
    thread_store: ConversationThreadStore,
    target_ticket_id: int,
    raw_text: str,
    requester_id: int | None,
    attachment_tokens: list[str],
    urgency: str,
    # Fallback params for 422 recovery
    group_id: int,
    group_name: str,
    sender_id: int,
    subject: str,
    custom_fields: list[dict] | None,
) -> tuple[int, int | None, str]:
    """Add comment to existing ticket. On 422, close stale thread and create new."""
    try:
        comment_id = await zendesk_client.add_comment(
            ticket_id=target_ticket_id,
            comment=ZendeskComment(
                body=raw_text,
                public=True,
                author_id=requester_id,
                attachment_tokens=attachment_tokens,
            ),
        )

        # Touch the thread to update last_message_at
        thread = await thread_store.get_thread_for_ticket(target_ticket_id)
        if thread:
            await touch_thread(thread.id)

        # Set urgency if high/critical
        if urgency in ("high", "critical"):
            import contextlib

            with contextlib.suppress(Exception):
                await zendesk_client.add_comment(
                    ticket_id=target_ticket_id,
                    comment=ZendeskComment(body="", public=False),
                    tags=[f"urgency_{urgency}"],
                )

        logger.info(
            "remember: routed to existing ticket={} comment={}",
            target_ticket_id,
            comment_id,
        )
        return target_ticket_id, comment_id, "reply"

    except ZendeskTicketClosedError:
        # Ticket is closed/solved — close stale thread and create new
        logger.warning(
            "remember: ticket {} is closed, closing thread and creating new",
            target_ticket_id,
        )
        await thread_store.close_thread_for_ticket(target_ticket_id)

        return await _create_new_ticket(
            thread_store=thread_store,
            group_id=group_id,
            group_name=group_name,
            sender_id=sender_id,
            subject=subject,
            raw_text=raw_text,
            requester_id=requester_id,
            attachment_tokens=attachment_tokens,
            custom_fields=custom_fields,
            urgency="normal",
        )


async def _create_new_ticket(
    *,
    thread_store: ConversationThreadStore,
    group_id: int,
    group_name: str,
    sender_id: int,
    subject: str,
    raw_text: str,
    requester_id: int | None,
    attachment_tokens: list[str],
    custom_fields: list[dict] | None,
    urgency: str,
) -> tuple[int, None, str]:
    """Create a new Zendesk ticket and conversation thread."""
    ticket_id, _is_new = await thread_store.get_or_create_thread(
        group_id=group_id,
        user_id=sender_id,
        group_name=group_name,
        subject=subject,
        body=raw_text,
        requester_id=requester_id,
        author_id=requester_id,
        custom_fields=custom_fields,
    )

    # Upload attachments as a follow-up comment if we have them
    # (the initial ticket body was plain text, attachments go as first comment)
    if attachment_tokens:
        try:
            from src.escalation.ticket_schemas import ZendeskComment as _ZC

            await thread_store._zendesk.add_comment(
                ticket_id=ticket_id,
                comment=_ZC(
                    body="[Attached files from Telegram]",
                    public=True,
                    author_id=requester_id,
                    attachment_tokens=attachment_tokens,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("remember: failed to attach files to ticket {}: {}", ticket_id, exc)

    logger.info(
        "remember: created new ticket={} for user={} in group={}", ticket_id, sender_id, group_id
    )
    return ticket_id, None, "root"


async def _create_follow_up_ticket(
    *,
    thread_store: ConversationThreadStore,
    group_id: int,
    group_name: str,
    sender_id: int,
    subject: str,
    raw_text: str,
    follow_up_source_id: int,
    requester_id: int | None,
    attachment_tokens: list[str],
    custom_fields: list[dict] | None,
) -> tuple[int, None, str]:
    """Create a follow-up ticket linked to a previously solved ticket."""
    ticket_id, _ = await thread_store.create_followup_thread(
        group_id=group_id,
        user_id=sender_id,
        group_name=group_name,
        subject=subject,
        body=raw_text,
        followup_source_id=follow_up_source_id,
        requester_id=requester_id,
        author_id=requester_id,
        custom_fields=custom_fields,
    )

    if attachment_tokens:
        try:
            await thread_store._zendesk.add_comment(
                ticket_id=ticket_id,
                comment=ZendeskComment(
                    body="[Attached files from Telegram]",
                    public=True,
                    author_id=requester_id,
                    attachment_tokens=attachment_tokens,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "remember: failed to attach files to follow-up ticket {}: {}", ticket_id, exc
            )

    logger.info(
        "remember: created follow-up ticket={} from source={} for user={}",
        ticket_id,
        follow_up_source_id,
        sender_id,
    )
    return ticket_id, None, "root"


async def _upload_attachments(
    zendesk_client: ZendeskTicketClient,
    images: list[bytes],
) -> list[str]:
    """Upload image bytes to Zendesk and return upload tokens."""
    tokens: list[str] = []
    for i, img_bytes in enumerate(images):
        try:
            token = await zendesk_client.upload_attachment(
                filename=f"telegram_image_{i + 1}.jpg",
                content_type="image/jpeg",
                data=img_bytes,
            )
            tokens.append(token)
        except Exception as exc:  # noqa: BLE001
            logger.warning("remember: failed to upload attachment {}: {}", i + 1, exc)
    return tokens
