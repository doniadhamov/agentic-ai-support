"""Perceive node — assemble complete context from all memory types.

No LLM call. Pure data queries. Enforces group isolation.
"""

from __future__ import annotations

import time

from loguru import logger

from src.agent.state import SupportState
from src.config.settings import get_settings
from src.database.repositories import (
    get_active_thread,
    get_active_threads_in_group,
    get_bot_last_response,
    get_message_by_telegram_id,
    get_recent_messages,
    get_recently_solved_threads,
)
from src.learning.episode_recorder import EpisodeRecorder
from src.learning.example_selector import ExampleSelector


def _format_conversation_history(messages: list[dict]) -> list[dict]:
    """Format raw message dicts into the conversation_history format for think's prompt."""
    formatted = []
    for msg in messages:
        line = ""
        file_type = msg.get("file_type")
        file_desc = msg.get("file_description")
        source = msg.get("source", "telegram")
        text = msg.get("text", "")
        username = msg.get("username", "")

        if source == "bot":
            line = f"Bot: {text}"
        elif file_type == "photo" and file_desc:
            line = f"{username}: [Photo: {file_desc}]"
            if text:
                line += f" {text}"
        elif file_type == "voice":
            line = f"{username}: [Voice] {text}"
        elif file_type == "document" and file_desc:
            line = f"{username}: [File: {file_desc}]"
            if text:
                line += f" {text}"
        else:
            line = f"{username}: {text}"

        formatted.append({**msg, "formatted": line})
    return formatted


async def perceive_node(
    state: SupportState,
    episode_recorder: EpisodeRecorder | None = None,
    example_selector: ExampleSelector | None = None,
) -> dict:
    """Load all context needed by the think node."""
    t0 = time.monotonic()
    settings = get_settings()

    group_id = int(state["group_id"])
    sender_id = int(state["sender_id"])
    reply_to_message_id = state.get("reply_to_message_id")
    raw_text = state.get("raw_text", "")

    # 1. Conversation history
    raw_messages = await get_recent_messages(
        chat_id=group_id, limit=settings.conversation_history_limit
    )
    conversation_history = _format_conversation_history(raw_messages)

    # 2. Active tickets in this group
    active_thread_rows = await get_active_threads_in_group(group_id)
    active_tickets = [
        {
            "ticket_id": t.zendesk_ticket_id,
            "subject": t.subject,
            "user_id": t.user_id,
            "status": t.status,
            "urgency": t.urgency,
            "last_message_at": str(t.last_message_at),
        }
        for t in active_thread_rows
    ]

    # 3. User's active ticket
    user_thread = await get_active_thread(group_id, sender_id)
    user_active_ticket = None
    if user_thread:
        user_active_ticket = {
            "ticket_id": user_thread.zendesk_ticket_id,
            "subject": user_thread.subject,
            "status": user_thread.status,
            "urgency": user_thread.urgency,
        }

    # 4. Recently solved tickets (for follow_up detection)
    recently_solved_tickets = await get_recently_solved_threads(group_id, days=7)

    # 5. Bot's last response in this group
    bot_resp = await get_bot_last_response(group_id)
    bot_last_response = bot_resp["text"] if bot_resp else None

    # 6. Reply-to context
    reply_to_ticket_id = None
    reply_to_text = None
    if reply_to_message_id:
        replied_msg = await get_message_by_telegram_id(group_id, reply_to_message_id)
        if replied_msg:
            reply_to_ticket_id = replied_msg.zendesk_ticket_id
            reply_to_text = replied_msg.text

    # 7. Episodic memory — find similar past resolution episodes
    relevant_episodes: list[dict] = []
    if episode_recorder and raw_text:
        relevant_episodes = await episode_recorder.find_similar_episodes(query=raw_text, limit=2)

    # 8. Procedural memory — retrieve relevant few-shot decision examples
    decision_examples: list[dict] = []
    if example_selector and raw_text:
        decision_examples = await example_selector.get_relevant_examples(query=raw_text, limit=5)

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    logger.debug(
        "perceive: group={} history={} active_tickets={} episodes={} examples={} elapsed={}ms",
        group_id,
        len(conversation_history),
        len(active_tickets),
        len(relevant_episodes),
        len(decision_examples),
        elapsed_ms,
    )

    return {
        "conversation_history": conversation_history,
        "active_tickets": active_tickets,
        "user_active_ticket": user_active_ticket,
        "recently_solved_tickets": recently_solved_tickets,
        "bot_last_response": bot_last_response,
        "reply_to_ticket_id": reply_to_ticket_id,
        "reply_to_text": reply_to_text,
        "relevant_episodes": relevant_episodes,
        "decision_examples": decision_examples,
        "perceive_ms": elapsed_ms,
    }
