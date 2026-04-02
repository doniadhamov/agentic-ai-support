"""SupportState — the shared state schema for the LangGraph support agent."""

from __future__ import annotations

from typing import Literal, TypedDict


class SupportState(TypedDict, total=False):
    # ── Input (set by handler before graph invocation) ──
    raw_text: str
    images: list[bytes]
    sender_id: str
    sender_name: str
    group_id: str
    group_name: str
    telegram_message_id: int
    reply_to_message_id: int | None

    # ── Context (set by perceive node) ──
    conversation_history: list[dict]
    active_tickets: list[dict]
    user_active_ticket: dict | None
    recently_solved_tickets: list[dict]
    bot_last_response: str | None
    reply_to_ticket_id: int | None
    reply_to_text: str | None
    relevant_episodes: list[dict]
    decision_examples: list[dict]

    # ── Decision (set by think node) ──
    action: Literal["answer", "ignore", "wait", "escalate"]
    urgency: Literal["normal", "high", "critical"]
    ticket_action: Literal["route_existing", "create_new", "skip", "follow_up"]
    target_ticket_id: int | None
    follow_up_source_id: int | None
    extracted_question: str | None
    language: str
    decision_reasoning: str
    file_description: str | None

    # ── Retrieval (set by retrieve node) ──
    retrieved_docs: list[dict]
    retrieval_confidence: float
    recent_image_bytes: list[bytes]

    # ── Generation (set by generate node) ──
    answer_text: str | None
    follow_up_question: str | None
    needs_escalation: bool
    escalation_reason: str
    knowledge_sources: list[dict]

    # ── Sync tracking (set by respond/remember nodes) ──
    bot_response_text: str | None
    bot_response_message_id: int | None
    synced_ticket_id: int | None
    synced_comment_id: int | None

    # ── Timing (set by each node for dashboard) ──
    perceive_ms: int | None
    think_ms: int | None
    retrieve_ms: int | None
    generate_ms: int | None
