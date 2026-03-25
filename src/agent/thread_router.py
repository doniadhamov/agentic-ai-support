"""AI-powered thread router: determines which Zendesk ticket a message belongs to."""

from __future__ import annotations

import json

import anthropic
from loguru import logger

from src.agent.prompts.thread_router_prompt import THREAD_ROUTER_PROMPT
from src.agent.schemas import ThreadRoutingAction, ThreadRoutingResult
from src.config.settings import get_settings
from src.utils.retry import async_retry

_TOOL_NAME = "produce_output"

_TOOL_SCHEMA: dict = {
    "name": _TOOL_NAME,
    "description": "Return the thread routing decision for the incoming message.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [a.value for a in ThreadRoutingAction],
                "description": "Routing action to take",
            },
            "ticket_id": {
                "type": ["integer", "null"],
                "description": "Zendesk ticket ID to route to (only for route_to_existing)",
            },
            "reasoning": {
                "type": "string",
                "description": "Brief explanation for the routing decision",
            },
        },
        "required": ["action", "reasoning"],
    },
}


class ThreadRouter:
    """Uses Claude Haiku to route messages to the correct Zendesk ticket."""

    def __init__(self, client: anthropic.AsyncAnthropic | None = None) -> None:
        settings = get_settings()
        self._client = client or anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_fast_model

    @async_retry()
    async def route(
        self,
        message_text: str,
        message_category: str,
        reply_to_text: str | None = None,
        reply_to_ticket_id: int | None = None,
        active_tickets: list[dict] | None = None,
        recent_history: list[str] | None = None,
    ) -> ThreadRoutingResult:
        """Determine where an incoming message should be routed.

        Args:
            message_text: The current message text.
            message_category: Classification from the classifier (e.g. "SUPPORT_QUESTION").
            reply_to_text: Text of the message being replied to, if any.
            reply_to_ticket_id: Zendesk ticket ID of the replied-to message, if known.
            active_tickets: List of active tickets in the group, each with
                keys: ticket_id, subject, recent_comments (summary string).
            recent_history: Recent messages from the group for context.

        Returns:
            :class:`ThreadRoutingResult` with action, optional ticket_id, and reasoning.
        """
        # Build context sections
        sections: list[str] = [THREAD_ROUTER_PROMPT]

        sections.append(f"MESSAGE CATEGORY: {message_category}")

        if reply_to_text:
            sections.append(f"REPLY TO MESSAGE: {reply_to_text}")
        if reply_to_ticket_id:
            sections.append(f"REPLY TO TICKET ID: {reply_to_ticket_id}")

        if active_tickets:
            tickets_text = "\n".join(
                f"  - Ticket #{t['ticket_id']}: {t['subject']}"
                + (f"\n    Recent: {t['recent_comments']}" if t.get("recent_comments") else "")
                for t in active_tickets
            )
            sections.append(f"ACTIVE TICKETS IN GROUP:\n{tickets_text}")
        else:
            sections.append("ACTIVE TICKETS IN GROUP: (none)")

        if recent_history:
            history_text = "\n".join(f"  - {m}" for m in recent_history[-30:])
            sections.append(f"RECENT GROUP HISTORY:\n{history_text}")

        sections.append(f"CURRENT MESSAGE: {message_text or '(no text)'}")

        prompt_text = "\n\n".join(sections)

        logger.debug("ThreadRouter: routing message (category={})", message_category)

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=256,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt_text}],
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
        )

        tool_input = _extract_tool_input(response)
        result = ThreadRoutingResult(
            action=ThreadRoutingAction(tool_input["action"]),
            ticket_id=tool_input.get("ticket_id"),
            reasoning=tool_input.get("reasoning", ""),
        )

        logger.info(
            "ThreadRouter: action={} ticket_id={} reason={!r}",
            result.action.value,
            result.ticket_id,
            result.reasoning[:80],
        )
        return result


def _extract_tool_input(response: anthropic.types.Message) -> dict:
    """Extract the tool_use input dict from a Claude response."""
    for block in response.content:
        if block.type == "tool_use" and block.name == _TOOL_NAME:
            if isinstance(block.input, str):
                return json.loads(block.input)
            return block.input  # type: ignore[return-value]
    raise ValueError(f"No '{_TOOL_NAME}' tool_use block found in response")
