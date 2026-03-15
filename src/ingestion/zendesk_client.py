"""Async Zendesk Help Center API client with pagination and retry."""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger

from src.config.settings import get_settings
from src.utils.retry import async_retry


class ZendeskClient:
    """Async client for Zendesk Help Center API."""

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = f"https://{settings.zendesk_subdomain}/api/v2"
        self._auth = httpx.BasicAuth(
            username=f"{settings.zendesk_email}/token",
            password=settings.zendesk_api_token,
        )
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "ZendeskClient":
        self._client = httpx.AsyncClient(auth=self._auth, timeout=30.0)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @async_retry(max_attempts=3, min_wait=1.0, max_wait=10.0, exceptions=(httpx.HTTPError,))
    async def _get(self, url: str) -> dict[str, Any]:
        assert self._client is not None, "Client not initialised; use async context manager"
        response = await self._client.get(url)
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    async def _paginate(self, path: str) -> list[dict[str, Any]]:
        """Fetch all pages from a paginated Help Center endpoint."""
        url: str | None = f"{self._base_url}{path}"
        results: list[dict[str, Any]] = []

        while url:
            data = await self._get(url)
            # Zendesk wraps results in a key named after the resource
            for key, value in data.items():
                if isinstance(value, list):
                    results.extend(value)
                    break
            url = data.get("next_page")  # None when last page
            logger.debug(f"Fetched {len(results)} items so far from {path!r}")

        return results

    async def get_categories(self) -> list[dict[str, Any]]:
        """Return all Help Center categories."""
        logger.info("Fetching Zendesk categories")
        return await self._paginate("/help_center/categories")

    async def get_sections(self) -> list[dict[str, Any]]:
        """Return all Help Center sections."""
        logger.info("Fetching Zendesk sections")
        return await self._paginate("/help_center/sections")

    async def get_articles(self, updated_since: str | None = None) -> list[dict[str, Any]]:
        """Return all Help Center articles, optionally filtered by update time.

        Args:
            updated_since: ISO-8601 timestamp; only articles updated after this are returned.
        """
        logger.info("Fetching Zendesk articles", updated_since=updated_since)
        path = "/help_center/articles"
        if updated_since:
            path += f"?start_time={updated_since}"
        return await self._paginate(path)

    async def get_article(self, article_id: int) -> dict[str, Any]:
        """Fetch a single article by ID."""
        data = await self._get(f"{self._base_url}/help_center/articles/{article_id}")
        return data.get("article", data)  # type: ignore[return-value]
