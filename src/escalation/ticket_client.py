"""Async HTTP client for the Zendesk Support API v2."""

from __future__ import annotations

import httpx
from loguru import logger

from src.config.settings import get_settings
from src.escalation.ticket_schemas import ZendeskComment, ZendeskTicketCreate
from src.utils.retry import async_retry


class ZendeskTicketClient:
    """Async wrapper around the Zendesk Tickets + Attachments API.

    Auth uses ``{email}/token:{api_token}`` basic auth as per Zendesk docs.
    """

    def __init__(
        self,
        subdomain: str | None = None,
        email: str | None = None,
        api_token: str | None = None,
    ) -> None:
        settings = get_settings()
        self._subdomain = subdomain or settings.zendesk_subdomain
        email = email or settings.zendesk_email
        api_token = api_token or settings.zendesk_api_token
        self._base_url = f"https://{self._subdomain}/api/v2"
        self._auth = (f"{email}/token", api_token)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            auth=self._auth,
            timeout=30.0,
            headers={"Content-Type": "application/json"},
        )

    @async_retry(max_attempts=3, min_wait=1.0, max_wait=10.0, exceptions=(httpx.HTTPError,))
    async def create_ticket(
        self, payload: ZendeskTicketCreate,
    ) -> int:
        """Create a new Zendesk ticket.

        Returns:
            The Zendesk ticket ID (integer).
        """
        body = {
            "ticket": {
                "subject": payload.subject,
                "comment": {"body": payload.body},
                "tags": payload.tags,
            },
        }
        async with self._client() as client:
            response = await client.post("/tickets.json", json=body)
            response.raise_for_status()
            data = response.json()

        ticket_id: int = data["ticket"]["id"]
        logger.info("Zendesk: created ticket_id={} subject={!r}", ticket_id, payload.subject)
        return ticket_id

    @async_retry(max_attempts=3, min_wait=1.0, max_wait=10.0, exceptions=(httpx.HTTPError,))
    async def add_comment(
        self,
        ticket_id: int,
        comment: ZendeskComment,
    ) -> int:
        """Add a comment to an existing Zendesk ticket.

        Returns:
            The Zendesk comment ID (integer).
        """
        comment_body: dict = {
            "body": comment.body,
            "public": comment.public,
        }
        if comment.attachment_tokens:
            comment_body["uploads"] = comment.attachment_tokens

        body = {"ticket": {"comment": comment_body}}
        async with self._client() as client:
            response = await client.put(f"/tickets/{ticket_id}.json", json=body)
            response.raise_for_status()
            data = response.json()

        audit = data.get("audit", {})
        events = audit.get("events", [])
        comment_id = 0
        for event in events:
            if event.get("type") == "Comment":
                comment_id = event.get("id", 0)
                break

        logger.debug("Zendesk: added comment to ticket_id={} comment_id={}", ticket_id, comment_id)
        return comment_id

    @async_retry(max_attempts=3, min_wait=1.0, max_wait=10.0, exceptions=(httpx.HTTPError,))
    async def get_ticket(self, ticket_id: int) -> dict:
        """Fetch a Zendesk ticket by ID.

        Returns:
            Raw ticket dict from the Zendesk API.
        """
        async with self._client() as client:
            response = await client.get(f"/tickets/{ticket_id}.json")
            response.raise_for_status()
            return response.json()["ticket"]

    @async_retry(max_attempts=3, min_wait=1.0, max_wait=10.0, exceptions=(httpx.HTTPError,))
    async def upload_attachment(
        self,
        filename: str,
        content_type: str,
        data: bytes,
    ) -> str:
        """Upload a file to Zendesk and return an upload token.

        The token is used when creating/updating tickets with attachments.

        Returns:
            Zendesk upload token string.
        """
        async with self._client() as client:
            response = await client.post(
                "/uploads.json",
                params={"filename": filename},
                content=data,
                headers={"Content-Type": content_type},
            )
            response.raise_for_status()
            result = response.json()

        token: str = result["upload"]["token"]
        logger.debug("Zendesk: uploaded attachment {!r} token={}", filename, token)
        return token

    @async_retry(max_attempts=3, min_wait=1.0, max_wait=10.0, exceptions=(httpx.HTTPError,))
    async def get_ticket_comments(self, ticket_id: int) -> list[dict]:
        """Fetch all comments for a ticket.

        Returns:
            List of comment dicts from the Zendesk API.
        """
        async with self._client() as client:
            response = await client.get(f"/tickets/{ticket_id}/comments.json")
            response.raise_for_status()
            return response.json().get("comments", [])
