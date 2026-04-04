"""Respond node — send Telegram reply."""

from __future__ import annotations

import re

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from loguru import logger

from src.agent.state import SupportState

_MAX_LEN = 4096
_SCREENSHOT_RE = re.compile(r"\n?screenshot\(https?://[^)]+\)\n?")


async def respond_node(state: SupportState, bot: Bot) -> dict:
    """Compose and send the bot's reply to Telegram."""
    answer = state.get("answer_text") or ""
    follow_up = state.get("follow_up_question") or ""
    group_id = int(state["group_id"])
    reply_to = state["telegram_message_id"]

    # Build response text
    if answer and follow_up:
        text = f"{answer}\n\n{follow_up}"
    elif answer:
        text = answer
    elif follow_up:
        text = follow_up
    else:
        logger.warning("respond: no text to send — this node should not have been reached")
        return {"bot_response_text": None, "bot_response_message_id": None}

    # Append source links for all articles used
    sources = state.get("knowledge_sources", [])
    source_urls = [
        src["url"] for src in sources
        if src.get("url") and src.get("type") == "documentation"
    ]
    if len(source_urls) == 1:
        text += f"\n\nFor more information: {source_urls[0]}"
    elif source_urls:
        links = "\n".join(source_urls)
        text += f"\n\nFor more information:\n{links}"

    # Strip screenshot markers
    text = _SCREENSHOT_RE.sub("\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    # Truncate if needed
    if len(text) > _MAX_LEN:
        text = text[: _MAX_LEN - 1] + "\u2026"

    # Send to Telegram — try MarkdownV2 first, fall back to plain
    try:
        sent = await bot.send_message(
            chat_id=group_id,
            text=text,
            reply_to_message_id=reply_to,
            parse_mode=None,  # plain text for reliability
        )
    except TelegramBadRequest as exc:
        logger.warning("respond: send failed, retrying without reply_to: {}", exc)
        sent = await bot.send_message(
            chat_id=group_id,
            text=text,
            parse_mode=None,
        )

    logger.info("respond: sent message_id={} to group={}", sent.message_id, group_id)

    return {
        "bot_response_text": text,
        "bot_response_message_id": sent.message_id,
    }
