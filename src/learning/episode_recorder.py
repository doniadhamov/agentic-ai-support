"""Episode recorder — save full conversation trajectories to LangGraph Store.

Episodic memory stores complete resolution trajectories: what happened from
message receipt through decision, response, and resolution. These episodes
are retrieved by the perceive node to help the think node recognize similar
situations.

Namespace: ("episodes", <topic_category>)
Key: "ticket_<ticket_id>"
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from langgraph.store.base import BaseStore


def _topic_key(text: str) -> str:
    """Derive a short topic category key from text for namespace partitioning."""
    return hashlib.md5(text.encode()).hexdigest()[:8]  # noqa: S324


class EpisodeRecorder:
    """Records and retrieves conversation episodes from LangGraph Store."""

    def __init__(self, store: BaseStore) -> None:
        self._store = store

    async def record_episode(
        self,
        ticket_id: int,
        group_id: int,
        user_id: int,
        subject: str,
        question: str,
        answer: str,
        action: str,
        ticket_action: str,
        messages: list[dict],
        tags: list[str] | None = None,
    ) -> None:
        """Save a complete resolution episode to the store.

        Args:
            ticket_id: Zendesk ticket ID.
            group_id: Telegram group ID.
            user_id: Telegram user ID who asked.
            subject: Ticket subject line.
            question: Generalized question extracted by summarizer.
            answer: Resolution answer.
            action: Final action taken (answer/escalate).
            ticket_action: Ticket routing action taken.
            messages: Conversation messages (list of dicts with username, text, source).
            tags: Optional topic tags.
        """
        # Build a condensed conversation transcript
        transcript_lines = []
        for msg in messages[-20:]:  # cap at last 20 messages
            source = msg.get("source", "telegram")
            name = (
                "[Agent]"
                if source == "zendesk"
                else "[Bot]"
                if source == "bot"
                else msg.get("username", "User")
            )
            text = msg.get("text", "")
            if text.strip():
                transcript_lines.append(f"{name}: {text}")

        episode = {
            "ticket_id": ticket_id,
            "group_id": group_id,
            "user_id": user_id,
            "subject": subject,
            "question": question,
            "answer": answer,
            "action": action,
            "ticket_action": ticket_action,
            "transcript": "\n".join(transcript_lines),
            "tags": tags or [],
        }

        topic = _topic_key(question)
        namespace = ("episodes", topic)
        key = f"ticket_{ticket_id}"

        await self._store.aput(
            namespace,
            key,
            episode,
            index=["question", "subject", "transcript"],
        )

        logger.info(
            "EpisodeRecorder: saved episode ticket={} ns=({}, {}) q={!r}",
            ticket_id,
            "episodes",
            topic,
            question[:60],
        )

    async def find_similar_episodes(
        self,
        query: str,
        limit: int = 2,
    ) -> list[dict]:
        """Search for episodes similar to the given query.

        Args:
            query: The current message or extracted question to match against.
            limit: Maximum number of episodes to return.

        Returns:
            List of episode dicts, most relevant first.
        """
        try:
            results = await self._store.asearch(
                ("episodes",),
                query=query,
                limit=limit,
            )
            episodes = [item.value for item in results]
            logger.debug(
                "EpisodeRecorder: found {} episodes for query={!r}",
                len(episodes),
                query[:60],
            )
            return episodes
        except Exception as exc:  # noqa: BLE001
            logger.warning("EpisodeRecorder: search failed: {}", exc)
            return []
