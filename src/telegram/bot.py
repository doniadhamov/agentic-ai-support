"""Bot factory and entry point.

Usage::

    uv run python -m src.telegram.bot
"""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from loguru import logger

from src.agent.agent import create_support_agent
from src.config.settings import get_settings
from src.telegram.context.context_manager import ContextManager
from src.telegram.handlers.message_handler import router as message_router
from src.utils.logging import setup_logging


def create_bot() -> tuple[Bot, Dispatcher]:
    """Instantiate the :class:`Bot` and :class:`Dispatcher`, wire all handlers.

    Dependencies (:class:`SupportAgent` and :class:`ContextManager`) are
    injected into the Dispatcher's workflow data so that handler functions
    receive them as typed parameters.

    Returns:
        A ``(bot, dp)`` tuple ready for long-polling or webhook mode.
    """
    from src.escalation.ticket_client import TicketAPIClient
    from src.escalation.ticket_store import TicketStore

    settings = get_settings()

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2),
    )

    dp = Dispatcher()

    # --- Escalation components ----------------------------------------------
    ticket_client = TicketAPIClient()
    ticket_store = TicketStore()

    # --- Dependency injection via Dispatcher workflow data ------------------
    agent = create_support_agent(ticket_client=ticket_client, ticket_store=ticket_store)
    context_manager = ContextManager()

    dp["agent"] = agent
    dp["context_manager"] = context_manager
    dp["ticket_store"] = ticket_store
    dp["ticket_client"] = ticket_client

    # --- Register routers ---------------------------------------------------
    dp.include_router(message_router)

    logger.info("Bot configured (long-poll={}) ✓", not bool(settings.telegram_webhook_url))
    return bot, dp


async def _init_database() -> None:
    """Create database tables if PostgreSQL is configured."""
    settings = get_settings()
    if not settings.database_url:
        logger.info("DATABASE_URL not set — using JSON/in-memory fallback")
        return
    from src.database.engine import get_engine
    from src.database.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured ✓")


async def run_bot() -> None:
    """Start the bot in long-polling or webhook mode based on settings."""
    from src.escalation.poller import TicketPoller

    setup_logging()
    settings = get_settings()

    # --- Ensure DB tables exist (no-op if DATABASE_URL is empty) ----------
    await _init_database()

    bot, dp = create_bot()

    # --- Hydrate ticket store from DB if available ------------------------
    ticket_store = dp["ticket_store"]
    await ticket_store.init_from_db()

    # --- Start the ticket poller as a background task -----------------------
    from src.embeddings.gemini_embedder import GeminiEmbedder
    from src.memory.approved_memory import ApprovedMemory
    from src.vector_db.qdrant_client import get_qdrant_client

    ticket_client = dp["ticket_client"]
    approved_memory = ApprovedMemory(embedder=GeminiEmbedder(), qdrant=get_qdrant_client())
    poller = TicketPoller(
        store=ticket_store,
        client=ticket_client,
        bot=bot,
        approved_memory=approved_memory,
    )
    asyncio.create_task(poller.run(), name="ticket_poller")
    logger.info("TicketPoller background task started")

    # --- Start the scheduled Zendesk sync task ------------------------------
    if settings.zendesk_sync_interval_hours > 0:
        asyncio.create_task(
            _run_zendesk_sync(settings.zendesk_sync_interval_hours),
            name="zendesk_sync",
        )
        logger.info("Zendesk sync scheduled every {} hour(s)", settings.zendesk_sync_interval_hours)

    # --- Start FastAPI health/metrics server as background task ---------------
    asyncio.create_task(_run_api_server(), name="api_server")

    if settings.telegram_webhook_url:
        await _run_webhook(bot, dp, settings.telegram_webhook_url)
    else:
        await _run_polling(bot, dp)


async def _run_api_server(port: int = 8000) -> None:
    """Run the FastAPI health/metrics server in the background."""
    import uvicorn

    from src.api.app import app as fastapi_app

    config = uvicorn.Config(fastapi_app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    logger.info("FastAPI server starting on :{}", port)
    await server.serve()


async def _run_zendesk_sync(interval_hours: int) -> None:
    """Run Zendesk delta sync on a recurring schedule.

    Sleeps for *interval_hours* before the first run so the bot is fully
    initialised, then re-syncs on every subsequent interval.
    """
    from src.embeddings.gemini_embedder import GeminiEmbedder
    from src.ingestion.chunker import ArticleChunk
    from src.ingestion.sync_manager import SyncManager
    from src.vector_db.indexer import ArticleIndexer
    from src.vector_db.qdrant_client import get_qdrant_client

    interval_seconds = interval_hours * 3600

    async def _index_chunks(chunks: list[ArticleChunk]) -> None:
        embedder = GeminiEmbedder()
        qdrant = get_qdrant_client()
        indexer = ArticleIndexer(embedder=embedder, qdrant=qdrant)
        for chunk in chunks:
            await indexer.index_chunk(chunk)

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            manager = SyncManager(on_chunks=_index_chunks)
            stats = await manager.delta_sync()
            logger.info(
                "Scheduled Zendesk sync complete articles={} chunks={}",
                stats["articles"],
                stats["chunks"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Scheduled Zendesk sync failed — {}", exc)


async def _run_polling(bot: Bot, dp: Dispatcher) -> None:
    """Run the bot in long-polling mode (development default)."""
    logger.info("Starting long-polling …")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


async def _run_webhook(bot: Bot, dp: Dispatcher, webhook_url: str) -> None:
    """Run the bot in webhook mode and optionally expose the ticket callback endpoint.

    The ticket-callback aiohttp app is mounted on the same server if
    ``ticket_callback_mode = webhook``.
    """
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
    from aiohttp import web

    settings = get_settings()
    telegram_webhook_path = "/webhook"

    await bot.set_webhook(f"{webhook_url}{telegram_webhook_path}")
    logger.info("Telegram webhook set to {}{}", webhook_url, telegram_webhook_path)

    app = web.Application()

    if settings.ticket_callback_mode == "webhook":
        from src.telegram.handlers.webhook_handler import WEBHOOK_PATH, build_webhook_app

        ticket_app = build_webhook_app(bot)
        app.add_subapp("/tickets", ticket_app)
        logger.info("Ticket callback endpoint mounted at /tickets{}", WEBHOOK_PATH)

    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=telegram_webhook_path)
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=8080)
    await site.start()
    logger.info("Webhook server listening on :8080")

    # Keep running until cancelled
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(run_bot())
