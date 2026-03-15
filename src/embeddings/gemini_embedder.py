"""Gemini Embedding 2 client for text and multimodal embeddings."""

from __future__ import annotations

from google import genai
from google.genai import types
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.settings import get_settings


class GeminiEmbedder:
    """Wrapper around Gemini text-embedding-004 for text and multimodal embeddings."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = genai.Client(api_key=settings.google_api_key)
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
        result = await self._client.aio.models.embed_content(
            model=self._model,
            contents=text,
            config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
        )
        return result.embeddings[0].values

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
        try:
            image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
            result = await self._client.aio.models.embed_content(
                model=self._model,
                contents=[text, image_part],
                config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
            )
        except Exception:
            logger.warning("Multimodal embedding failed, falling back to text-only embedding")
            result = await self._client.aio.models.embed_content(
                model=self._model,
                contents=text,
                config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
            )
        return result.embeddings[0].values
