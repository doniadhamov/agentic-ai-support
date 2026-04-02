"""Learn node — extract knowledge from resolved tickets.

Triggered by ZendeskWebhookHandler when a ticket is solved/closed,
NOT part of the main LangGraph state machine.

Flow:
1. Fetch all messages for the ticket from DB
2. Use TicketSummarizer (Haiku) to extract a generalized Q&A pair
3. Store Q&A in Qdrant datatruck_memory via ApprovedMemory
4. Record full conversation trajectory in episodic memory (LangGraph Store)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from src.agent.ticket_summarizer import TicketSummarizer
from src.database.repositories import get_messages_by_ticket_id
from src.memory.approved_memory import ApprovedMemory
from src.memory.memory_schemas import ApprovedAnswer

if TYPE_CHECKING:
    from src.learning.episode_recorder import EpisodeRecorder


async def learn_from_ticket(
    ticket_id: int,
    group_id: int,
    summarizer: TicketSummarizer,
    memory: ApprovedMemory,
    episode_recorder: EpisodeRecorder | None = None,
    subject: str = "",
    user_id: int = 0,
) -> dict | None:
    """Extract a Q&A pair from a resolved ticket and store in memory.

    Args:
        ticket_id: The Zendesk ticket ID that was solved/closed.
        group_id: The Telegram group ID associated with the ticket.
        summarizer: TicketSummarizer instance for Haiku-based extraction.
        memory: ApprovedMemory instance for Qdrant storage.
        episode_recorder: Optional EpisodeRecorder for saving conversation trajectory.
        subject: Ticket subject line (for episode recording).
        user_id: Telegram user ID who asked (for episode recording).

    Returns:
        Dict with question, answer, point_id on success; None if no messages
        or extraction failed.
    """
    messages = await get_messages_by_ticket_id(ticket_id)
    if not messages:
        logger.warning("learn: no messages found for ticket={}", ticket_id)
        return None

    # Filter out empty messages that won't help summarization
    non_empty = [m for m in messages if m.get("text", "").strip()]
    if len(non_empty) < 2:
        logger.info(
            "learn: ticket={} has fewer than 2 non-empty messages, skipping",
            ticket_id,
        )
        return None

    summary = await summarizer.summarize(non_empty)

    question = summary["question"]
    answer = summary["answer"]
    tags = summary.get("tags", [])

    if not question or not answer:
        logger.warning("learn: summarizer returned empty Q or A for ticket={}", ticket_id)
        return None

    point_id = await memory.store(
        ApprovedAnswer(
            question=question,
            answer=answer,
            ticket_id=ticket_id,
            group_id=group_id,
        )
    )

    # Record episode in LangGraph Store for episodic memory
    if episode_recorder:
        try:
            await episode_recorder.record_episode(
                ticket_id=ticket_id,
                group_id=group_id,
                user_id=user_id,
                subject=subject or question[:80],
                question=question,
                answer=answer,
                action="answer",
                ticket_action="create_new",
                messages=non_empty,
                tags=tags,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("learn: failed to record episode for ticket={}: {}", ticket_id, exc)

    logger.info(
        "learn: stored Q&A for ticket={} point_id={} q={!r}",
        ticket_id,
        point_id,
        question[:60],
    )
    return {
        "question": question,
        "answer": answer,
        "tags": tags,
        "point_id": point_id,
    }
