"""Message classifier: uses Claude tool-use to classify incoming messages."""

from __future__ import annotations

import base64
import json

import anthropic
from loguru import logger

from src.agent.prompts.classifier_prompt import CLASSIFIER_PROMPT
from src.agent.prompts.system_prompt import SYSTEM_PROMPT
from src.agent.schemas import ClassifierResult, MessageCategory
from src.config.settings import get_settings
from src.utils.retry import async_retry

_TOOL_NAME = "produce_output"

_TOOL_SCHEMA: dict = {
    "name": _TOOL_NAME,
    "description": "Return the classification result for the incoming message.",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": [c.value for c in MessageCategory],
                "description": "Message category",
            },
            "language": {
                "type": "string",
                "enum": ["en", "ru", "uz"],
                "description": "Detected language of the support request",
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Classification confidence (0–1)",
            },
            "reasoning": {
                "type": "string",
                "description": "Brief reasoning for the classification",
            },
        },
        "required": ["category", "language"],
    },
}


class MessageClassifier:
    """Classifies Telegram messages using Claude tool-use at temperature=0.0."""

    def __init__(self, client: anthropic.AsyncAnthropic | None = None) -> None:
        settings = get_settings()
        self._client = client or anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_fast_model

    @async_retry()
    async def classify(
        self,
        message_text: str,
        conversation_context: list[str] | None = None,
        images: list[bytes] | None = None,
    ) -> ClassifierResult:
        """Classify *message_text* with optional conversation context and images.

        Args:
            message_text: The raw incoming Telegram message.
            conversation_context: Recent prior messages from the same group.
            images: Optional list of image byte arrays (photos, image documents).

        Returns:
            :class:`ClassifierResult` with category, language, confidence, and reasoning.
        """
        context_block = ""
        if conversation_context:
            formatted = "\n".join(f"- {m}" for m in conversation_context[-10:])
            context_block = f"\nRECENT CONTEXT:\n{formatted}\n"

        prompt_text = f"{CLASSIFIER_PROMPT}{context_block}\nMESSAGE:\n{message_text or '(no text — see attached image(s))'}"

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
            "Classifying message (len={}, images={})", len(message_text or ""), len(images or [])
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
        result = ClassifierResult(
            category=MessageCategory(tool_input["category"]),
            language=tool_input.get("language", "en"),
            confidence=tool_input.get("confidence", 1.0),
            reasoning=tool_input.get("reasoning", ""),
        )

        logger.info(
            "Classified message as {} (lang={}, confidence={:.2f})",
            result.category.value,
            result.language,
            result.confidence,
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
