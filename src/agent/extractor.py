"""Question extractor: derives a clean standalone question using Claude tool-use."""

from __future__ import annotations

import base64
import json

import anthropic
from loguru import logger

from src.agent.prompts.extractor_prompt import EXTRACTOR_PROMPT
from src.agent.prompts.system_prompt import SYSTEM_PROMPT
from src.agent.schemas import ExtractorResult
from src.config.settings import get_settings
from src.utils.retry import async_retry

_TOOL_NAME = "produce_output"

_TOOL_SCHEMA: dict = {
    "name": _TOOL_NAME,
    "description": "Return the extracted support question and conversation summary.",
    "input_schema": {
        "type": "object",
        "properties": {
            "extracted_question": {
                "type": "string",
                "description": "Clean standalone support question",
            },
            "language": {
                "type": "string",
                "enum": ["en", "ru", "uz"],
                "description": "Detected language of the support request",
            },
            "conversation_summary": {
                "type": "string",
                "description": "Brief summary of relevant conversation context (1-2 sentences)",
            },
        },
        "required": ["extracted_question", "language"],
    },
}


class QuestionExtractor:
    """Extracts a clean, standalone support question using Claude tool-use at temperature=0.0."""

    def __init__(self, client: anthropic.AsyncAnthropic | None = None) -> None:
        settings = get_settings()
        self._client = client or anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_fast_model

    @async_retry()
    async def extract(
        self,
        message_text: str,
        conversation_context: list[str] | None = None,
        images: list[bytes] | None = None,
    ) -> ExtractorResult:
        """Extract a standalone support question from *message_text*.

        Args:
            message_text: The raw incoming Telegram message.
            conversation_context: Recent prior messages from the same group.
            images: Optional list of image byte arrays (photos, image documents).

        Returns:
            :class:`ExtractorResult` with the extracted question and language.
        """
        context_block = ""
        if conversation_context:
            formatted = "\n".join(f"- {m}" for m in conversation_context[-10:])
            context_block = f"\nRECENT CONTEXT:\n{formatted}\n"

        prompt_text = f"{EXTRACTOR_PROMPT}{context_block}\nMESSAGE:\n{message_text or '(no text — see attached image(s))'}"

        # Build multimodal content blocks when images are attached
        if images:
            user_content: str | list[dict] = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.standard_b64encode(img).decode(),
                    },
                }
                for img in images
            ]
            user_content.append({"type": "text", "text": prompt_text})
        else:
            user_content = prompt_text

        logger.debug(
            "Extracting question from message (len={}, images={})",
            len(message_text or ""),
            len(images or []),
        )

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=512,
            temperature=0.0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
        )

        tool_input = _extract_tool_input(response)
        result = ExtractorResult(
            extracted_question=tool_input["extracted_question"],
            language=tool_input.get("language", "en"),
            conversation_summary=tool_input.get("conversation_summary", ""),
        )

        logger.info(
            "Extracted question (lang={}): {!r}",
            result.language,
            result.extracted_question[:100],
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
