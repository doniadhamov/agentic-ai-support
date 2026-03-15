"""Async HTTP client for the external support ticket API."""

from __future__ import annotations

import httpx
from loguru import logger

from src.config.settings import get_settings
from src.escalation.ticket_schemas import TicketCreate, TicketRecord, TicketResponse, TicketStatus
from src.utils.retry import async_retry


class TicketAPIClient:
    """Thin async wrapper around the external ticket REST API.

    Endpoints assumed:
    - ``POST /tickets``             — create a ticket; returns ``{ticket_id, status}``
    - ``GET  /tickets/{ticket_id}`` — poll ticket; returns ``{ticket_id, status, answer}``
    """

    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.support_api_base_url).rstrip("/")
        self._api_key = api_key or settings.support_api_key
        self._headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    @async_retry(max_attempts=3, min_wait=1.0, max_wait=10.0, exceptions=(httpx.HTTPError,))
    async def create_ticket(self, payload: TicketCreate) -> TicketRecord:
        """Create a new support ticket.

        Args:
            payload: Structured ticket creation data.

        Returns:
            :class:`TicketRecord` with the API-assigned ``ticket_id``.
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self._base_url}/tickets",
                json=payload.model_dump(),
                headers=self._headers,
            )
            response.raise_for_status()
            data = response.json()

        ticket_id: str = data["ticket_id"]
        logger.info(
            "Ticket created ticket_id={} group_id={} user_id={}",
            ticket_id,
            payload.group_id,
            payload.user_id,
        )
        return TicketRecord(
            ticket_id=ticket_id,
            group_id=payload.group_id,
            user_id=payload.user_id,
            message_id=payload.message_id,
            language=payload.language,
            question=payload.question,
            status=TicketStatus(data.get("status", TicketStatus.OPEN)),
        )

    @async_retry(max_attempts=3, min_wait=1.0, max_wait=10.0, exceptions=(httpx.HTTPError,))
    async def get_ticket_status(self, ticket_id: str) -> TicketResponse:
        """Poll the external API for the current status of a ticket.

        Args:
            ticket_id: The ticket ID returned by :meth:`create_ticket`.

        Returns:
            :class:`TicketResponse` with current status and optional answer.
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{self._base_url}/tickets/{ticket_id}",
                headers=self._headers,
            )
            response.raise_for_status()
            data = response.json()

        return TicketResponse(
            ticket_id=data["ticket_id"],
            status=TicketStatus(data["status"]),
            answer=data.get("answer", ""),
        )
