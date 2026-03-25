"""Summarizes closed tickets into generalized Q&A pairs for approved memory."""

from __future__ import annotations

import json

import anthropic
from loguru import logger

from src.config.settings import get_settings
from src.utils.retry import async_retry

_TOOL_NAME = "produce_output"

_TOOL_SCHEMA: dict = {
    "name": _TOOL_NAME,
    "description": "Return the generalized Q&A summary for the resolved ticket.",
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "Generalized question (no user-specific data)",
            },
            "answer": {
                "type": "string",
                "description": "Generalized answer (no user-specific data)",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Topic tags for the Q&A pair",
            },
        },
        "required": ["question", "answer"],
    },
}

_SUMMARIZER_PROMPT = """\
You are summarizing a resolved support conversation into a generalized Q&A pair \
that can be stored in a knowledge base for future reference.

RULES:
1. Remove ALL user-specific data: names, user IDs, group names, Telegram references, \
company names, specific account details.
2. Generalize the question so it applies to anyone with the same issue.
3. The answer should be the actionable resolution — steps to fix the problem or the \
information that was provided.
4. Keep the language of the original conversation (en, ru, or uz).
5. Be concise but complete.

CONVERSATION:
{conversation}

Use the produce_output tool to return the generalized Q&A pair.
"""


class TicketSummarizer:
    """Summarizes resolved ticket conversations into de-identified Q&A pairs."""

    def __init__(self, client: anthropic.AsyncAnthropic | None = None) -> None:
        settings = get_settings()
        self._client = client or anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_fast_model

    @async_retry()
    async def summarize(
        self,
        messages: list[dict],
    ) -> dict:
        """Summarize a list of conversation messages into a generalized Q&A pair.

        Args:
            messages: List of message dicts with keys: username, text, source, timestamp.

        Returns:
            Dict with keys: question, answer, tags.
        """
        conversation_lines = []
        for msg in messages:
            source = msg.get("source", "telegram")
            prefix = "[Support Agent]" if source == "zendesk" else msg.get("username", "User")
            conversation_lines.append(f"{prefix}: {msg.get('text', '')}")

        conversation_text = "\n".join(conversation_lines)
        prompt = _SUMMARIZER_PROMPT.format(conversation=conversation_text)

        logger.debug("TicketSummarizer: summarizing {} messages", len(messages))

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
        )

        tool_input = _extract_tool_input(response)
        result = {
            "question": tool_input["question"],
            "answer": tool_input["answer"],
            "tags": tool_input.get("tags", []),
        }

        logger.info(
            "TicketSummarizer: generated Q&A — q={!r} tags={}",
            result["question"][:60],
            result["tags"],
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
