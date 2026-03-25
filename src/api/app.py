"""FastAPI application with health check, metrics, and Zendesk webhook endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI, Request
from loguru import logger

from src.config.settings import get_settings

app = FastAPI(title="DataTruck AI Support Bot", version="0.1.0")

# Zendesk webhook handler — injected at startup by bot.py
_webhook_handler = None


def set_webhook_handler(handler: object) -> None:
    """Inject the ZendeskWebhookHandler at startup."""
    global _webhook_handler
    _webhook_handler = handler


@app.get("/health")
async def health_check() -> dict:
    """Basic health check — always returns 200 if the process is alive."""
    return {
        "status": "ok",
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }


@app.get("/health/ready")
async def readiness_check() -> dict:
    """Readiness probe — checks connectivity to external services."""
    checks: dict[str, str] = {}
    settings = get_settings()

    # Check Qdrant
    try:
        from src.vector_db.qdrant_client import get_qdrant_client

        qdrant = get_qdrant_client()
        await qdrant.client.get_collections()
        checks["qdrant"] = "ok"
    except Exception as exc:
        checks["qdrant"] = f"error: {exc}"
        logger.warning("Readiness check: Qdrant unreachable — {}", exc)

    # Check PostgreSQL (required for Zendesk sync)
    if settings.database_url:
        try:
            from sqlalchemy import text

            from src.database.engine import get_session_factory

            factory = get_session_factory()
            async with factory() as session:
                await session.execute(text("SELECT 1"))
            checks["postgres"] = "ok"
        except Exception as exc:
            checks["postgres"] = f"error: {exc}"
            logger.warning("Readiness check: PostgreSQL unreachable — {}", exc)

    # Check Zendesk API connectivity
    if settings.zendesk_api_token:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"https://{settings.zendesk_subdomain}/api/v2/tickets/count.json",
                    auth=(f"{settings.zendesk_email}/token", settings.zendesk_api_token),
                )
                resp.raise_for_status()
            checks["zendesk"] = "ok"
        except Exception as exc:
            checks["zendesk"] = f"error: {exc}"
            logger.warning("Readiness check: Zendesk unreachable — {}", exc)

    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "ready" if all_ok else "degraded",
        "checks": checks,
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }


@app.get("/metrics")
async def basic_metrics() -> dict:
    """Return basic operational metrics."""
    settings = get_settings()
    metrics: dict = {}

    try:
        from src.vector_db.collections import DOCS_COLLECTION, MEMORY_COLLECTION
        from src.vector_db.qdrant_client import get_qdrant_client

        qdrant = get_qdrant_client()
        docs_info = await qdrant.client.get_collection(DOCS_COLLECTION)
        memory_info = await qdrant.client.get_collection(MEMORY_COLLECTION)
        metrics["docs_points"] = docs_info.points_count
        metrics["memory_points"] = memory_info.points_count
    except Exception:
        metrics["docs_points"] = None
        metrics["memory_points"] = None

    if settings.database_url:
        try:
            from sqlalchemy import func, select

            from src.database.engine import get_session_factory
            from src.database.models import ConversationThread, TicketRow

            factory = get_session_factory()
            async with factory() as session:
                result = await session.execute(
                    select(func.count()).select_from(TicketRow).where(TicketRow.status == "open")
                )
                metrics["open_tickets"] = result.scalar() or 0

                result = await session.execute(
                    select(func.count())
                    .select_from(ConversationThread)
                    .where(ConversationThread.status == "active")
                )
                metrics["active_conversation_threads"] = result.scalar() or 0
        except Exception:
            metrics["open_tickets"] = None
            metrics["active_conversation_threads"] = None

    return metrics


@app.post("/api/zendesk/webhook")
async def zendesk_webhook(request: Request) -> dict:
    """Receive Zendesk webhook payloads when an agent adds a comment."""
    if _webhook_handler is None:
        logger.warning("Zendesk webhook received but handler not configured")
        return {"status": "error", "reason": "webhook handler not configured"}

    try:
        payload = await request.json()
    except Exception:
        return {"status": "error", "reason": "invalid JSON"}

    logger.info(
        "Zendesk webhook received: ticket_id={}",
        payload.get("ticket_id", "unknown"),
    )
    return await _webhook_handler.handle_comment(payload)
