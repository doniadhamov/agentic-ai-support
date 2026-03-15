"""Answer generator: produces grounded replies using Claude tool-use."""

from __future__ import annotations

import json

import anthropic
from loguru import logger

from src.agent.prompts.generator_prompt import GENERATOR_PROMPT
from src.agent.prompts.system_prompt import SYSTEM_PROMPT
from src.agent.schemas import GeneratorResult, KnowledgeSource
from src.config.settings import get_settings
from src.rag.retriever import RetrievedChunk
from src.utils.retry import async_retry

_TOOL_NAME = "produce_output"

_TOOL_SCHEMA: dict = {
    "name": _TOOL_NAME,
    "description": "Return the generated support answer.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "description": "Final reply to send to the user",
            },
            "follow_up_question": {
                "type": "string",
                "description": "Clarification question if needed, otherwise empty string",
            },
            "needs_escalation": {
                "type": "boolean",
                "description": "True if the question cannot be answered from available knowledge",
            },
            "escalation_reason": {
                "type": "string",
                "description": "Brief reason for escalation if needs_escalation is true",
            },
            "knowledge_sources_used": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["documentation", "approved_memory"],
                        },
                        "title": {"type": "string"},
                        "id": {"type": "string"},
                    },
                    "required": ["type"],
                },
                "description": "List of knowledge sources used in the answer",
            },
            "store_resolution": {
                "type": "boolean",
                "description": "True if this resolution should be stored in approved memory",
            },
        },
        "required": ["answer", "needs_escalation"],
    },
}


def _format_chunks(chunks: list[RetrievedChunk]) -> str:
    """Render retrieved chunks as a numbered list for the prompt."""
    if not chunks:
        return "(no relevant documentation found)"
    parts: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        source_label = "documentation" if chunk.source == "docs" else "approved memory"
        title = chunk.article_title or "Untitled"
        parts.append(
            f"[{i}] Source: {source_label} | Title: {title} | Score: {chunk.score:.3f}\n"
            f"{chunk.text.strip()}"
        )
    return "\n\n".join(parts)


class AnswerGenerator:
    """Generates grounded support answers using Claude tool-use at temperature=0.2."""

    def __init__(self, client: anthropic.AsyncAnthropic | None = None) -> None:
        settings = get_settings()
        self._client = client or anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_model

    @async_retry()
    async def generate(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        language: str = "en",
    ) -> GeneratorResult:
        """Generate an answer for *question* grounded in *chunks*.

        Args:
            question: The clean extracted support question.
            chunks: Retrieved and filtered knowledge chunks (docs + memory).
            language: Language code for the reply.

        Returns:
            :class:`GeneratorResult` with the answer or escalation decision.
        """
        chunks_text = _format_chunks(chunks)
        user_content = GENERATOR_PROMPT.format(
            chunks=chunks_text,
            question=question,
            language=language,
        )

        logger.debug(
            "Generating answer for question (lang={}, {} chunk(s))",
            language,
            len(chunks),
        )

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            temperature=0.2,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
        )

        tool_input = _extract_tool_input(response)

        raw_sources: list[dict] = tool_input.get("knowledge_sources_used", [])
        sources = [
            KnowledgeSource(
                type=s.get("type", "documentation"),
                title=s.get("title", ""),
                id=s.get("id", ""),
            )
            for s in raw_sources
        ]

        result = GeneratorResult(
            answer=tool_input.get("answer", ""),
            follow_up_question=tool_input.get("follow_up_question", ""),
            needs_escalation=tool_input.get("needs_escalation", False),
            escalation_reason=tool_input.get("escalation_reason", ""),
            knowledge_sources_used=sources,
            store_resolution=tool_input.get("store_resolution", False),
        )

        if result.needs_escalation:
            logger.info("Generator decided escalation: {}", result.escalation_reason)
        else:
            logger.info(
                "Generated answer (sources={}, store={})",
                len(result.knowledge_sources_used),
                result.store_resolution,
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
