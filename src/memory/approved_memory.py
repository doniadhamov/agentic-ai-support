"""ApprovedMemory: store approved Q&A pairs in the datatruck_memory Qdrant collection."""

from __future__ import annotations

import uuid

from loguru import logger
from qdrant_client.models import PointStruct

from src.embeddings.gemini_embedder import GeminiEmbedder
from src.memory.memory_schemas import ApprovedAnswer
from src.vector_db.collections import MEMORY_COLLECTION
from src.vector_db.qdrant_client import QdrantWrapper

# Shared UUID5 namespace (same as indexer.py for consistency)
_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # uuid.NAMESPACE_URL


def _memory_point_id(question: str) -> str:
    """Generate a deterministic UUID5 from the question text.

    Args:
        question: The cleaned standalone question.

    Returns:
        UUID5 string suitable as a Qdrant point ID.
    """
    return str(uuid.uuid5(_NAMESPACE, question))


class ApprovedMemory:
    """Embeds questions and upserts approved Q&A pairs into ``datatruck_memory``.

    Re-storing the same question is idempotent: the deterministic point ID
    means the entry is simply overwritten with the latest answer.
    """

    def __init__(self, embedder: GeminiEmbedder, qdrant: QdrantWrapper) -> None:
        self._embedder = embedder
        self._qdrant = qdrant

    async def store(self, approved: ApprovedAnswer) -> str:
        """Embed the question and upsert the Q&A pair into ``datatruck_memory``.

        Args:
            approved: The resolved Q&A pair to persist.

        Returns:
            The Qdrant point ID used for the stored entry.
        """
        vector = await self._embedder.embed_text(approved.question)

        point_id = _memory_point_id(approved.question)
        payload = {
            "question": approved.question,
            # ``text`` is the field the retriever reads — include both Q and A
            # so the chunk is self-contained when shown to the generator.
            "text": f"Q: {approved.question}\nA: {approved.answer}",
            "answer": approved.answer,
            "language": approved.language,
            "ticket_id": approved.ticket_id,
            "group_id": approved.group_id,
            # Keep the same payload keys the retriever expects
            "article_title": "Approved Answer",
            "article_url": "",
        }

        point = PointStruct(id=point_id, vector=vector, payload=payload)
        await self._qdrant.upsert_points(MEMORY_COLLECTION, [point])

        logger.info(
            "Stored approved answer in datatruck_memory (lang={}, point_id={})",
            approved.language,
            point_id,
        )
        return point_id
