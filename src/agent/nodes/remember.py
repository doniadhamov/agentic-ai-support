"""Remember node — update working memory + sync to Zendesk + log decision.

Runs on ALL paths (answer, ignore, wait, escalate).
Phase 1: Zendesk sync is stubbed — logs the decision and saves bot message to DB.
Phase 2 will add full Zendesk sync logic.
"""

from __future__ import annotations

import time

from loguru import logger

from src.agent.state import SupportState
from src.database.repositories import (
    save_bot_decision,
    save_message,
    update_message_file_description,
)


async def remember_node(state: SupportState) -> dict:
    """Persist state changes and log decision."""
    t0 = time.monotonic()

    group_id = int(state["group_id"])
    sender_id = int(state["sender_id"])
    message_id = state["telegram_message_id"]
    action = state.get("action", "ignore")
    ticket_action = state.get("ticket_action", "skip")

    # 1. Update file_description on the user's message (if think produced one)
    file_description = state.get("file_description")
    if file_description:
        try:
            await update_message_file_description(group_id, message_id, file_description)
        except Exception as exc:  # noqa: BLE001
            logger.warning("remember: failed to update file_description: {}", exc)

    # 2. Save bot's response to DB (so perceive sees it in conversation_history)
    bot_response_text = state.get("bot_response_text")
    bot_response_message_id = state.get("bot_response_message_id")
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
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("remember: failed to save bot response to DB: {}", exc)

    # 3. Log decision for dashboard analytics
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
            message_text=state.get("raw_text", ""),
            action=action,
            ticket_action=ticket_action,
            language=state.get("language", "en"),
            urgency=state.get("urgency", "normal"),
            reasoning=state.get("decision_reasoning", ""),
            file_description=file_description,
            target_ticket_id=state.get("target_ticket_id"),
            extracted_question=state.get("extracted_question"),
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
        "remember: action={} ticket_action={} elapsed={}ms",
        action,
        ticket_action,
        elapsed_ms,
    )

    # Phase 2 TODO: Full Zendesk sync (create ticket, add comment, upload attachments)
    return {
        "synced_ticket_id": state.get("target_ticket_id"),
        "synced_comment_id": None,
    }
