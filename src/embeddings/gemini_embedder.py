"""Gemini Embedding 2 client for text and multimodal embeddings."""

from __future__ import annotations

import asyncio
import base64

import google.generativeai as genai
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.settings import get_settings


class GeminiEmbedder:
    """Wrapper around Gemini text-embedding-004 for text and multimodal embeddings."""

    def __init__(self) -> None:
        settings = get_settings()
        genai.configure(api_key=settings.google_api_key)
        self._model = settings.gemini_embedding_model

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def embed_text(self, text: str) -> list[float]:
        """Embed a plain text string.

        Args:
            text: The text to embed.

        Returns:
            768-dimensional embedding vector.
        """
        logger.debug("Embedding text ({} chars)", len(text))
        result = await asyncio.to_thread(
            genai.embed_content,
            model=self._model,
            content=text,
            task_type="retrieval_document",
        )
        return result["embedding"]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def embed_multimodal(self, text: str, image_bytes: bytes) -> list[float]:
        """Embed text combined with an image.

        Falls back to text-only embedding if the model does not support
        multimodal input, logging a warning.

        Args:
            text: Contextual text accompanying the image.
            image_bytes: Raw image bytes (JPEG, PNG, etc.).

        Returns:
            768-dimensional embedding vector.
        """
        logger.debug("Embedding multimodal content ({} chars + {} bytes image)", len(text), len(image_bytes))
        image_part = {
            "mime_type": "image/jpeg",
            "data": base64.b64encode(image_bytes).decode(),
        }
        try:
            result = await asyncio.to_thread(
                genai.embed_content,
                model=self._model,
                content=[text, image_part],
                task_type="retrieval_document",
            )
        except Exception:
            logger.warning("Multimodal embedding failed, falling back to text-only embedding")
            result = await asyncio.to_thread(
                genai.embed_content,
                model=self._model,
                content=text,
                task_type="retrieval_document",
            )
        return result["embedding"]
