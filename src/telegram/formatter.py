"""Format :class:`AgentOutput` into a Telegram-ready reply string."""

from __future__ import annotations

from src.agent.schemas import AgentOutput

_MAX_LEN = 4096  # Telegram hard limit


def format_reply(output: AgentOutput) -> str:
    """Convert an :class:`AgentOutput` to a Telegram message string.

    - Respects the 4 096-character Telegram message limit (truncates with ``…``).
    - Uses light Markdown formatting (bold/italic) compatible with ``ParseMode.MARKDOWN``.

    Args:
        output: The agent's processing result.

    Returns:
        A non-empty string ready to be sent via ``bot.send_message``.
    """
    text = _build_text(output)

    if len(text) > _MAX_LEN:
        text = text[: _MAX_LEN - 1] + "…"

    return text


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_text(output: AgentOutput) -> str:
    """Assemble the raw (pre-truncation) reply text."""

    # --- Escalation notice --------------------------------------------------
    if output.needs_escalation:
        lines = [
            "Your question has been forwarded to our support team.",
            "We will get back to you as soon as possible.",
        ]
        if output.escalation_reason:
            lines.append(f"\n_{output.escalation_reason}_")
        return "\n".join(lines)

    # --- Clarification / follow-up question ---------------------------------
    if output.follow_up_question and not output.answer:
        return output.follow_up_question

    # --- Regular answer -----------------------------------------------------
    if output.answer:
        parts: list[str] = [output.answer]

        sources = _format_sources(output)
        if sources:
            parts.append(sources)

        if output.follow_up_question:
            parts.append(f"\n{output.follow_up_question}")

        return "\n\n".join(parts)

    # --- Fallback -----------------------------------------------------------
    return "I could not find a relevant answer. Please try rephrasing your question."


def _format_sources(output: AgentOutput) -> str:
    """Return a compact sources line, or empty string if none."""
    titles = [s.title for s in output.knowledge_sources_used if s.title]
    if not titles:
        return ""
    unique_titles = list(dict.fromkeys(titles))[:3]  # dedupe, cap at 3
    return "*Sources:* " + " · ".join(unique_titles)
