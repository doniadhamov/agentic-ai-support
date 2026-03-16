"""Answer generator: produces grounded replies using Claude tool-use."""

from __future__ import annotations

import base64
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
        header = f"[{i}] Source: {source_label} | Title: {title} | Score: {chunk.score:.3f}"
        if chunk.article_url:
            header += f" | URL: {chunk.article_url}"
        if chunk.image_url:
            header += f"\nscreenshot({chunk.image_url})"
        parts.append(f"{header}\n{chunk.text.strip()}")
    return "\n\n".join(parts)


def _build_sources_from_chunks(chunks: list[RetrievedChunk]) -> list[KnowledgeSource]:
    """Deduplicate chunks into a list of KnowledgeSources with URLs."""
    seen: set[str] = set()
    sources: list[KnowledgeSource] = []
    for chunk in chunks:
        key = chunk.article_url or chunk.article_title or chunk.point_id
        if key in seen:
            continue
        seen.add(key)
        sources.append(
            KnowledgeSource(
                type="documentation" if chunk.source == "docs" else "approved_memory",
                title=chunk.article_title,
                url=chunk.article_url,
                id=chunk.point_id,
            )
        )
    return sources


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
        image_data: bytes | None = None,
    ) -> GeneratorResult:
        """Generate an answer for *question* grounded in *chunks*.

        Args:
            question: The clean extracted support question.
            chunks: Retrieved and filtered knowledge chunks (docs + memory).
            language: Language code for the reply.
            image_data: Optional JPEG bytes of the user-attached screenshot.

        Returns:
            :class:`GeneratorResult` with the answer or escalation decision.
        """
        chunks_text = _format_chunks(chunks)
        prompt_text = GENERATOR_PROMPT.format(
            chunks=chunks_text,
            question=question,
            language=language,
        )

        # Include the user's screenshot so the generator can see what they see
        if image_data:
            user_content: str | list[dict] = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.standard_b64encode(image_data).decode(),
                    },
                },
                {"type": "text", "text": prompt_text},
            ]
        else:
            user_content = prompt_text

        logger.debug(
            "Generating answer for question (lang={}, {} chunk(s), has_image={})",
            language,
            len(chunks),
            bool(image_data),
        )

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            temperature=0.2,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
        )

        tool_input = _extract_tool_input(response)

        # Build sources from the actual chunks (not Claude's output) to ensure
        # we always have accurate URLs and titles.
        sources = _build_sources_from_chunks(chunks)

        result = GeneratorResult(
            answer=tool_input.get("answer", ""),
            follow_up_question=tool_input.get("follow_up_question", ""),
            needs_escalation=tool_input.get("needs_escalation", False),
            escalation_reason=tool_input.get("escalation_reason", ""),
            knowledge_sources_used=sources,
        )

        if result.needs_escalation:
            logger.info("Generator decided escalation: {}", result.escalation_reason)
        else:
            logger.info(
                "Generated answer (sources={})",
                len(result.knowledge_sources_used),
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
