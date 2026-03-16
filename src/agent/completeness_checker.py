"""Semantic completeness checker: uses the fast Claude model to decide whether
a batch of buffered user messages looks complete or if more messages are likely
coming.

Called by the debounce logic *after* the base silence timer fires — avoids an
LLM call on every single incoming message.
"""

from __future__ import annotations

import anthropic
from loguru import logger

from src.config.settings import get_settings
from src.utils.retry import async_retry

_PROMPT = """\
You are analyzing a batch of Telegram messages sent by the same user in quick succession.
Decide whether the user has finished typing their full thought or whether they are likely
to send more messages to complete it.

Signs the message is INCOMPLETE (more is coming):
- The text ends mid-sentence or trails off
- A photo was sent without any explanation — the user may be about to describe it
- The message is a short fragment that doesn't stand on its own
- The text explicitly says "wait", "one moment", "hold on", "сейчас", "кутинг" etc.
- The user seems to be typing a list and hasn't finished
- The sentence ends with a conjunction or connector ("and", "but", "because", "и", "va", etc.)

Signs the message is COMPLETE (ready to process):
- The text forms a coherent question or statement
- A photo was sent with a clear caption/question
- The user is greeting or thanking — no more expected
- The text ends with a question mark, period, or clear conclusion
- Multiple messages together already form a full thought

Messages (oldest first):
{messages}

Reply with exactly one word: COMPLETE or INCOMPLETE"""


class CompletenessChecker:
    """Thin wrapper around the fast Claude model for completeness checks."""

    def __init__(self, client: anthropic.AsyncAnthropic | None = None) -> None:
        settings = get_settings()
        self._client = client or anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
        )
        self._model = settings.anthropic_fast_model

    @async_retry(max_attempts=2, min_wait=0.5, max_wait=2.0)
    async def is_complete(
        self,
        message_texts: list[str],
        has_photo_without_text: bool = False,
    ) -> bool:
        """Return *True* if the buffered messages look like a complete thought.

        Args:
            message_texts: Text of each buffered message (oldest first).
            has_photo_without_text: Whether the batch includes a photo with no caption.
        """
        parts: list[str] = []
        for i, text in enumerate(message_texts, 1):
            parts.append(f"{i}. {text}" if text else f"{i}. [photo without text]")
        if has_photo_without_text and all(t for t in message_texts):
            parts.append(f"{len(parts) + 1}. [photo without text]")

        formatted = "\n".join(parts)
        prompt = _PROMPT.format(messages=formatted)

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=8,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )

        answer = response.content[0].text.strip().upper() if response.content else "COMPLETE"
        is_done = "INCOMPLETE" not in answer

        logger.debug(
            "Completeness check: {} ({} message(s), has_bare_photo={})",
            "COMPLETE" if is_done else "INCOMPLETE",
            len(message_texts),
            has_photo_without_text,
        )
        return is_done
