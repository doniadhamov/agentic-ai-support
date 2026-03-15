"""Optional aiohttp webhook handler for inbound ticket-resolution push callbacks.

When ``ticket_callback_mode = webhook`` the external ticket API POSTs resolved
answers to this endpoint instead of the bot polling for them.

Expected JSON payload::

    {
        "ticket_id": "TKT-001",
        "chat_id": -1001234567890,
        "message_id": 42,
        "answer": "Here is the resolution …"
    }
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import web
from loguru import logger

if TYPE_CHECKING:
    from aiogram import Bot

WEBHOOK_PATH = "/ticket-callback"


async def ticket_callback_handler(request: web.Request) -> web.Response:
    """Receive a resolved-ticket callback and relay the answer to Telegram.

    The ``Bot`` instance must be stored under the ``"bot"`` key in
    ``request.app``.
    """
    try:
        payload: dict = await request.json()
    except Exception as exc:
        logger.warning("ticket_callback: invalid JSON — {}", exc)
        return web.Response(status=400, text="Invalid JSON")

    ticket_id: str = payload.get("ticket_id", "")
    chat_id: int | None = payload.get("chat_id")
    message_id: int | None = payload.get("message_id")
    answer: str = payload.get("answer", "")

    if not (ticket_id and chat_id and message_id and answer):
        logger.warning("ticket_callback: missing required fields — {}", payload)
        return web.Response(status=422, text="Missing required fields")

    bot: Bot = request.app["bot"]

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=answer,
            reply_to_message_id=message_id,
        )
        logger.info(
            "ticket_callback: sent resolution ticket_id={} chat_id={} message_id={}",
            ticket_id,
            chat_id,
            message_id,
        )
    except Exception as exc:
        logger.error("ticket_callback: failed to send Telegram reply — {}", exc)
        return web.Response(status=500, text="Failed to deliver reply")

    return web.Response(status=200, text="OK")


def build_webhook_app(bot: Bot) -> web.Application:
    """Create a minimal aiohttp application with the ticket-callback route.

    Args:
        bot: The aiogram :class:`Bot` instance used to send replies.

    Returns:
        An :class:`aiohttp.web.Application` ready to be run alongside the bot.
    """
    app = web.Application()
    app["bot"] = bot
    app.router.add_post(WEBHOOK_PATH, ticket_callback_handler)
    return app
