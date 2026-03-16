"""FastAPI application with health check and basic API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from loguru import logger

from src.config.settings import get_settings

app = FastAPI(title="DataTruck AI Support Bot", version="0.1.0")


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

    # Check PostgreSQL (if configured)
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
            from src.database.models import TicketRow

            factory = get_session_factory()
            async with factory() as session:
                result = await session.execute(
                    select(func.count()).select_from(TicketRow).where(TicketRow.status == "open")
                )
                metrics["open_tickets"] = result.scalar() or 0
        except Exception:
            metrics["open_tickets"] = None

    return metrics
