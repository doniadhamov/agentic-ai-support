"""Gemini Embedding client for text and multimodal embeddings."""

from __future__ import annotations

from google import genai
from google.genai import types
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.settings import get_settings


class GeminiEmbedder:
    """Wrapper around Gemini embedding models for text and multimodal embeddings."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = genai.Client(api_key=settings.google_api_key)
        self._model = settings.gemini_embedding_model
        self._dimensions = settings.gemini_embedding_dimensions

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
            Embedding vector with configured dimensionality.
        """
        logger.debug("Embedding text ({} chars)", len(text))
        result = await self._client.aio.models.embed_content(
            model=self._model,
            contents=text,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=self._dimensions,
            ),
        )
        return result.embeddings[0].values

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def embed_query(self, text: str) -> list[float]:
        """Embed a search query using RETRIEVAL_QUERY task type.

        Args:
            text: The query text to embed.

        Returns:
            Embedding vector with configured dimensionality.
        """
        logger.debug("Embedding query ({} chars)", len(text))
        result = await self._client.aio.models.embed_content(
            model=self._model,
            contents=text,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=self._dimensions,
            ),
        )
        return result.embeddings[0].values

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def embed_texts_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple text strings in a single API call.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.
        """
        logger.debug("Batch embedding {} texts", len(texts))
        result = await self._client.aio.models.embed_content(
            model=self._model,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=self._dimensions,
            ),
        )
        return [e.values for e in result.embeddings]

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
            Embedding vector with configured dimensionality.
        """
        logger.debug("Embedding multimodal content ({} chars + {} bytes image)", len(text), len(image_bytes))
        try:
            image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
            result = await self._client.aio.models.embed_content(
                model=self._model,
                contents=[text, image_part],
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=self._dimensions,
                ),
            )
        except Exception:
            logger.warning("Multimodal embedding failed, falling back to text-only embedding")
            result = await self._client.aio.models.embed_content(
                model=self._model,
                contents=text,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=self._dimensions,
                ),
            )
        return result.embeddings[0].values
