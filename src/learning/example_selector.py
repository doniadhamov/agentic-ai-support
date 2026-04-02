"""Example selector — dynamically retrieve few-shot decision examples from LangGraph Store.

Procedural memory stores curated decision examples that teach the think node
how to handle specific message patterns. These examples are dynamically
retrieved based on similarity to the incoming message.

Namespace: ("procedural", "decision_examples")
Key: deterministic from the example message text
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from langgraph.store.base import BaseStore

_NAMESPACE = ("procedural", "decision_examples")


def _example_key(message: str) -> str:
    """Deterministic key from the example message text."""
    return hashlib.md5(message.encode()).hexdigest()[:12]  # noqa: S324


class ExampleSelector:
    """Manages and retrieves few-shot decision examples for the think node."""

    def __init__(self, store: BaseStore) -> None:
        self._store = store

    async def add_example(
        self,
        message: str,
        action: str,
        ticket_action: str,
        language: str = "en",
        reasoning: str = "",
        context: str = "",
        urgency: str = "normal",
        extracted_question: str | None = None,
    ) -> str:
        """Add a decision example to procedural memory.

        Args:
            message: The user message text.
            action: Correct action (answer/ignore/wait/escalate).
            ticket_action: Correct ticket action (route_existing/create_new/skip/follow_up).
            language: Message language.
            reasoning: Why this decision is correct.
            context: Optional context description (e.g., "user has active ticket #101").
            urgency: Urgency level.
            extracted_question: Extracted question if action=answer.

        Returns:
            The key used to store the example.
        """
        example = {
            "message": message,
            "action": action,
            "ticket_action": ticket_action,
            "language": language,
            "urgency": urgency,
            "reasoning": reasoning,
            "context": context,
            "extracted_question": extracted_question,
        }

        key = _example_key(message)
        await self._store.aput(
            _NAMESPACE,
            key,
            example,
            index=["message", "context", "reasoning"],
        )

        logger.debug(
            "ExampleSelector: stored example key={} action={} msg={!r}",
            key,
            action,
            message[:60],
        )
        return key

    async def get_relevant_examples(
        self,
        query: str,
        limit: int = 5,
    ) -> list[dict]:
        """Retrieve the most relevant decision examples for the current message.

        Args:
            query: The incoming message text to match against.
            limit: Maximum number of examples to return.

        Returns:
            List of example dicts, most relevant first.
        """
        try:
            results = await self._store.asearch(
                _NAMESPACE,
                query=query,
                limit=limit,
            )
            examples = [item.value for item in results]
            logger.debug(
                "ExampleSelector: found {} examples for query={!r}",
                len(examples),
                query[:60],
            )
            return examples
        except Exception as exc:  # noqa: BLE001
            logger.warning("ExampleSelector: search failed: {}", exc)
            return []

    async def seed_default_examples(self) -> int:
        """Seed procedural memory with default decision examples.

        Called during bootstrap or on first startup. Idempotent — re-seeding
        overwrites existing entries with same keys.

        Returns:
            Number of examples seeded.
        """
        count = 0
        for ex in _DEFAULT_EXAMPLES:
            await self.add_example(**ex)
            count += 1
        logger.info("ExampleSelector: seeded {} default examples", count)
        return count


# Default examples that cover the most common patterns.
# These are used until enough real examples are collected from decision review.
_DEFAULT_EXAMPLES: list[dict] = [
    {
        "message": "Good morning everyone!",
        "action": "ignore",
        "ticket_action": "skip",
        "language": "en",
        "reasoning": "Casual greeting with no support context.",
        "context": "No active tickets.",
    },
    {
        "message": "How do I update a load status to Delivered?",
        "action": "answer",
        "ticket_action": "create_new",
        "language": "en",
        "reasoning": "Clear support question about product functionality.",
        "extracted_question": "How to update load status to Delivered?",
    },
    {
        "message": "thanks that helped",
        "action": "ignore",
        "ticket_action": "route_existing",
        "language": "en",
        "reasoning": "Acknowledgment after receiving help. Route to existing ticket for history.",
        "context": "User has active ticket #101.",
    },
    {
        "message": "I have more questions",
        "action": "wait",
        "ticket_action": "route_existing",
        "language": "en",
        "reasoning": "User signals they have more to say but hasn't asked yet.",
        "context": "User has active ticket #101, bot just answered.",
    },
    {
        "message": "still not working after clearing cache",
        "action": "escalate",
        "ticket_action": "route_existing",
        "language": "en",
        "reasoning": "User reports documented solution didn't work. Needs human investigation.",
        "context": "Active ticket #101: 'Login issue'.",
    },
    {
        "message": "@Xojiakbar_CS_DataTruck can you check my account?",
        "action": "ignore",
        "ticket_action": "create_new",
        "language": "en",
        "reasoning": "User @mentions a specific human agent. Bot stays silent.",
    },
    {
        "message": "The GPS is still not working after the fix",
        "action": "escalate",
        "ticket_action": "follow_up",
        "language": "en",
        "reasoning": "Issue recurred after being resolved. Create follow-up ticket.",
        "context": "Solved ticket #200: 'GPS sync issue' closed 3 days ago.",
    },
    {
        "message": "Как добавить нового водителя в систему?",
        "action": "answer",
        "ticket_action": "create_new",
        "language": "ru",
        "reasoning": "Support question in Russian about adding a driver.",
        "extracted_question": "Как добавить нового водителя в систему?",
    },
    {
        "message": "tel qiling",
        "action": "escalate",
        "ticket_action": "create_new",
        "language": "uz",
        "reasoning": "User requests a phone call. Bot cannot make calls.",
    },
    {
        "message": "please add a new driver to our company account",
        "action": "escalate",
        "ticket_action": "create_new",
        "language": "en",
        "reasoning": "Account-specific action requiring admin access.",
    },
    {
        "message": "ok",
        "action": "ignore",
        "ticket_action": "route_existing",
        "language": "en",
        "reasoning": "Simple acknowledgment. Route to ticket for history.",
        "context": "User has active ticket #102.",
    },
    {
        "message": "rahmat",
        "action": "ignore",
        "ticket_action": "route_existing",
        "language": "uz",
        "reasoning": "'Thank you' in Uzbek after receiving help.",
        "context": "User has active ticket #103, agent just replied.",
    },
]
