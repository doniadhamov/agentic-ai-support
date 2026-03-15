"""Async image downloader with a local file-system cache."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from src.utils.retry import async_retry

_DEFAULT_CACHE_DIR = Path(".cache/images")


class ImageDownloader:
    """Downloads images asynchronously and caches them on disk.

    Subsequent requests for the same URL return cached bytes without hitting
    the network.
    """

    def __init__(self, cache_dir: Path = _DEFAULT_CACHE_DIR) -> None:
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> ImageDownloader:
        self._client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _cache_path(self, url: str) -> Path:
        key = hashlib.sha256(url.encode()).hexdigest()
        # Preserve extension if present (up to 5 chars)
        suffix = Path(url.split("?")[0]).suffix[:5]
        return self._cache_dir / f"{key}{suffix}"

    @async_retry(max_attempts=3, min_wait=1.0, max_wait=10.0, exceptions=(httpx.HTTPError,))
    async def _fetch(self, url: str) -> bytes:
        assert self._client is not None, "Use async context manager"
        response = await self._client.get(url)
        response.raise_for_status()
        return response.content

    async def download(self, url: str) -> bytes:
        """Return image bytes for *url*, using the local cache when available.

        Args:
            url: Public image URL.

        Returns:
            Raw image bytes.
        """
        cache_path = self._cache_path(url)

        if cache_path.exists():
            logger.debug(f"Cache hit for image: {url!r}")
            return cache_path.read_bytes()

        logger.debug(f"Downloading image: {url!r}")
        data = await self._fetch(url)
        cache_path.write_bytes(data)
        logger.debug(f"Cached image to {cache_path}")
        return data

    def clear_cache(self) -> int:
        """Delete all cached images. Returns the number of files removed."""
        count = 0
        for path in self._cache_dir.iterdir():
            if path.is_file():
                path.unlink()
                count += 1
        logger.info(f"Cleared {count} cached images from {self._cache_dir}")
        return count
