"""Full E2E integration test: seed Qdrant → call SupportAgent → verify output.

Requires a local Qdrant instance (docker compose up -d).
Anthropic and Gemini API calls are mocked — no real API keys needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from qdrant_client import AsyncQdrantClient

from src.agent.agent import SupportAgent
from src.agent.classifier import MessageClassifier
from src.agent.extractor import QuestionExtractor
from src.agent.generator import AnswerGenerator
from src.agent.schemas import (
    AgentInput,
    ClassifierResult,
    ExtractorResult,
    GeneratorResult,
    KnowledgeSource,
    MessageCategory,
)
from src.ingestion.chunker import ArticleChunk
from src.rag.reranker import ScoreThresholdFilter
from src.rag.retriever import RAGRetriever
from src.vector_db.collections import DOCS_COLLECTION, create_collections_if_not_exist
from src.vector_db.indexer import ArticleIndexer, _chunk_point_id
from src.vector_db.qdrant_client import QdrantWrapper

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QDRANT_URL = "http://localhost:6333"
VECTOR_SIZE = 768

_NOW = datetime(2024, 6, 1, tzinfo=timezone.utc)
_QUESTION_VEC = [1.0 if j == 0 else 0.0 for j in range(VECTOR_SIZE)]

_CHUNK = ArticleChunk(
    article_id=9001,
    chunk_index=0,
    text="To reset your DataTruck password, go to Settings > Security > Reset Password.",
    article_title="Password Reset Guide",
    article_url="https://support.datatruck.io/articles/9001",
    language="en",
    updated_at=_NOW,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def qdrant_client() -> AsyncQdrantClient:  # type: ignore[misc]
    client = AsyncQdrantClient(url=QDRANT_URL)
    yield client
    # Cleanup seeded point after each test
    try:
        await client.delete(
            collection_name=DOCS_COLLECTION,
            points_selector=[_chunk_point_id(_CHUNK.article_id, _CHUNK.chunk_index)],
        )
    except Exception:
        pass
    await client.close()


@pytest.fixture()
async def seeded_qdrant(qdrant_client: AsyncQdrantClient) -> QdrantWrapper:  # type: ignore[misc]
    """Create collections and index the test chunk with a deterministic vector."""
    await create_collections_if_not_exist(qdrant_client)

    mock_embedder = MagicMock()
    mock_embedder.embed_text = AsyncMock(return_value=_QUESTION_VEC)

    wrapper = QdrantWrapper(qdrant_client)
    indexer = ArticleIndexer(embedder=mock_embedder, qdrant=wrapper)
    await indexer.index_chunk(_CHUNK)
    return wrapper


def _mock_anthropic(
    category: MessageCategory = MessageCategory.SUPPORT_QUESTION,
    language: str = "en",
    extracted_question: str = "How do I reset my password?",
    answer: str = "Go to Settings > Security > Reset Password.",
) -> MagicMock:
    """Return a fake Anthropic client that returns structured tool-use responses."""

    def _tool_use_block(**kwargs: object) -> MagicMock:
        block = MagicMock()
        block.type = "tool_use"
        block.name = "produce_output"
        block.input = kwargs
        resp = MagicMock()
        resp.content = [block]
        return resp

    client = MagicMock()
    client.messages = MagicMock()

    # Each Claude call (classify, extract, generate) gets a tailored response
    client.messages.create = AsyncMock(
        side_effect=[
            # 1st call: classifier
            _tool_use_block(
                category=category.value,
                language=language,
                confidence=0.95,
                reasoning="clear support question",
            ),
            # 2nd call: extractor
            _tool_use_block(
                extracted_question=extracted_question,
                language=language,
                conversation_summary="User needs password reset help.",
            ),
            # 3rd call: generator
            _tool_use_block(
                answer=answer,
                follow_up_question="",
                needs_escalation=False,
                escalation_reason="",
                knowledge_sources_used=[
                    {"type": "documentation", "title": "Password Reset Guide", "id": "9001"}
                ],
            ),
        ]
    )
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_support_question_returns_grounded_answer(
    seeded_qdrant: QdrantWrapper,
) -> None:
    """Full path: classify SUPPORT_QUESTION → retrieve doc chunk → generate answer."""
    mock_anthropic = _mock_anthropic()

    mock_embedder = MagicMock()
    mock_embedder.embed_text = AsyncMock(return_value=_QUESTION_VEC)

    classifier = MessageClassifier(client=mock_anthropic)
    extractor = QuestionExtractor(client=mock_anthropic)
    generator = AnswerGenerator(client=mock_anthropic)
    retriever = RAGRetriever(embedder=mock_embedder, qdrant=seeded_qdrant)
    reranker = ScoreThresholdFilter(min_score=0.0)

    agent = SupportAgent(
        classifier=classifier,
        extractor=extractor,
        retriever=retriever,
        reranker=reranker,
        generator=generator,
    )

    agent_input = AgentInput(
        message_text="How do I reset my password?",
        user_id=501,
        group_id=601,
        message_id=701,
        language="en",
        conversation_context=[],
    )

    output = await agent.process(agent_input)

    assert output.should_reply is True
    assert output.category == MessageCategory.SUPPORT_QUESTION
    assert output.language == "en"
    assert output.answer != ""
    assert output.needs_escalation is False
    assert output.ticket_id == ""


@pytest.mark.asyncio
async def test_e2e_non_support_message_no_reply(seeded_qdrant: QdrantWrapper) -> None:
    """NON_SUPPORT messages must produce should_reply=False without hitting retrieval."""
    mock_anthropic = _mock_anthropic(category=MessageCategory.NON_SUPPORT)

    # Classifier returns NON_SUPPORT — only the first side_effect is consumed
    mock_embedder = MagicMock()
    mock_embedder.embed_text = AsyncMock(return_value=_QUESTION_VEC)

    classifier = MessageClassifier(client=mock_anthropic)
    extractor = QuestionExtractor(client=mock_anthropic)
    generator = AnswerGenerator(client=mock_anthropic)
    retriever = RAGRetriever(embedder=mock_embedder, qdrant=seeded_qdrant)
    reranker = ScoreThresholdFilter(min_score=0.0)

    agent = SupportAgent(
        classifier=classifier,
        extractor=extractor,
        retriever=retriever,
        reranker=reranker,
        generator=generator,
    )

    agent_input = AgentInput(
        message_text="Good morning everyone!",
        user_id=501,
        group_id=601,
        message_id=702,
        language="en",
        conversation_context=[],
    )

    output = await agent.process(agent_input)

    assert output.should_reply is False
    assert output.category == MessageCategory.NON_SUPPORT
    # Embedder must not have been called (no retrieval)
    mock_embedder.embed_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_e2e_escalation_creates_ticket(seeded_qdrant: QdrantWrapper) -> None:
    """When generator decides escalation, a ticket must be created and ticket_id returned."""

    def _tool_use_block(**kwargs: object) -> MagicMock:
        block = MagicMock()
        block.type = "tool_use"
        block.name = "produce_output"
        block.input = kwargs
        resp = MagicMock()
        resp.content = [block]
        return resp

    mock_anthropic = MagicMock()
    mock_anthropic.messages = MagicMock()
    mock_anthropic.messages.create = AsyncMock(
        side_effect=[
            _tool_use_block(
                category="SUPPORT_QUESTION",
                language="en",
                confidence=0.9,
                reasoning="needs help",
            ),
            _tool_use_block(
                extracted_question="My account is completely broken.",
                language="en",
                conversation_summary="Account broken.",
            ),
            _tool_use_block(
                answer="",
                follow_up_question="",
                needs_escalation=True,
                escalation_reason="Complex billing issue requiring human review.",
                knowledge_sources_used=[],
            ),
        ]
    )

    mock_embedder = MagicMock()
    mock_embedder.embed_text = AsyncMock(return_value=_QUESTION_VEC)

    ticket_record = MagicMock()
    ticket_record.ticket_id = "E2E-TICKET-007"

    ticket_client = MagicMock()
    ticket_client.create_ticket = AsyncMock(return_value=ticket_record)
    ticket_store = MagicMock()
    ticket_store.add = AsyncMock()

    classifier = MessageClassifier(client=mock_anthropic)
    extractor = QuestionExtractor(client=mock_anthropic)
    generator = AnswerGenerator(client=mock_anthropic)
    retriever = RAGRetriever(embedder=mock_embedder, qdrant=seeded_qdrant)
    reranker = ScoreThresholdFilter(min_score=0.0)

    agent = SupportAgent(
        classifier=classifier,
        extractor=extractor,
        retriever=retriever,
        reranker=reranker,
        generator=generator,
        ticket_client=ticket_client,
        ticket_store=ticket_store,
    )

    agent_input = AgentInput(
        message_text="My account is completely broken and nobody is helping.",
        user_id=501,
        group_id=601,
        message_id=703,
        language="en",
        conversation_context=[],
    )

    output = await agent.process(agent_input)

    assert output.needs_escalation is True
    assert output.ticket_id == "E2E-TICKET-007"
    assert output.category == MessageCategory.ESCALATION_REQUIRED
    ticket_client.create_ticket.assert_awaited_once()
    ticket_store.add.assert_awaited_once()
