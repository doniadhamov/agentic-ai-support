"""Unit tests for SupportAgent orchestrator — all sub-components are mocked."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.agent import SupportAgent
from src.agent.schemas import (
    AgentInput,
    AgentOutput,
    ClassifierResult,
    ExtractorResult,
    GeneratorResult,
    KnowledgeSource,
    MessageCategory,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(
    category: MessageCategory = MessageCategory.SUPPORT_QUESTION,
    language: str = "en",
    needs_escalation: bool = False,
    store_resolution: bool = False,
    answer: str = "Here is your answer.",
    follow_up: str = "",
    ticket_client: object | None = None,
    ticket_store: object | None = None,
    approved_memory: object | None = None,
) -> SupportAgent:
    classifier = MagicMock()
    classifier.classify = AsyncMock(
        return_value=ClassifierResult(
            category=category, language=language, confidence=0.95, reasoning="test"
        )
    )

    extractor = MagicMock()
    extractor.extract = AsyncMock(
        return_value=ExtractorResult(
            extracted_question="How do I reset my password?",
            language=language,
            conversation_summary="User wants to reset password.",
        )
    )

    source = KnowledgeSource(type="documentation", title="Password Guide", id="3001")
    generator = MagicMock()
    generator.generate = AsyncMock(
        return_value=GeneratorResult(
            answer=answer,
            follow_up_question=follow_up,
            needs_escalation=needs_escalation,
            escalation_reason="Cannot resolve" if needs_escalation else "",
            knowledge_sources_used=[source] if not needs_escalation else [],
            store_resolution=store_resolution,
        )
    )

    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=[])

    reranker = MagicMock()
    reranker.filter = MagicMock(return_value=[])

    return SupportAgent(
        classifier=classifier,
        extractor=extractor,
        retriever=retriever,
        reranker=reranker,
        generator=generator,
        ticket_client=ticket_client,
        ticket_store=ticket_store,
        approved_memory=approved_memory,
    )


def _make_input(text: str = "How do I reset my password?") -> AgentInput:
    return AgentInput(
        message_text=text,
        user_id=101,
        group_id=201,
        message_id=301,
        language="en",
        conversation_context=[],
    )


# ---------------------------------------------------------------------------
# NON_SUPPORT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_non_support_no_reply() -> None:
    agent = _make_agent(category=MessageCategory.NON_SUPPORT)
    output = await agent.process(_make_input("Good morning!"))

    assert isinstance(output, AgentOutput)
    assert output.should_reply is False
    assert output.category == MessageCategory.NON_SUPPORT


# ---------------------------------------------------------------------------
# SUPPORT_QUESTION — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_support_question_returns_answer() -> None:
    agent = _make_agent(
        category=MessageCategory.SUPPORT_QUESTION, answer="Go to Settings → Reset."
    )
    output = await agent.process(_make_input())

    assert output.should_reply is True
    assert output.category == MessageCategory.SUPPORT_QUESTION
    assert output.answer == "Go to Settings → Reset."
    assert output.language == "en"
    assert output.extracted_question != ""


@pytest.mark.asyncio
async def test_process_support_question_language_detected() -> None:
    agent = _make_agent(category=MessageCategory.SUPPORT_QUESTION, language="ru")
    output = await agent.process(_make_input("Как сбросить пароль?"))

    assert output.language == "ru"


# ---------------------------------------------------------------------------
# CLARIFICATION_NEEDED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_clarification_needed_no_retrieval() -> None:
    agent = _make_agent(
        category=MessageCategory.CLARIFICATION_NEEDED,
        follow_up="Which account are you referring to?",
    )
    output = await agent.process(_make_input("It doesn't work."))

    assert output.should_reply is True
    assert output.category == MessageCategory.CLARIFICATION_NEEDED
    assert output.needs_retrieval is False
    # Retriever must NOT be called for clarification
    agent._retriever.retrieve.assert_not_called()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# ESCALATION — generator decides
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_escalation_creates_ticket() -> None:
    ticket_record = MagicMock()
    ticket_record.ticket_id = "TICKET-123"

    ticket_client = MagicMock()
    ticket_client.create_ticket = AsyncMock(return_value=ticket_record)

    ticket_store = MagicMock()
    ticket_store.add = AsyncMock()

    agent = _make_agent(
        category=MessageCategory.SUPPORT_QUESTION,
        needs_escalation=True,
        ticket_client=ticket_client,
        ticket_store=ticket_store,
    )
    output = await agent.process(_make_input())

    assert output.needs_escalation is True
    assert output.ticket_id == "TICKET-123"
    assert output.category == MessageCategory.ESCALATION_REQUIRED
    ticket_client.create_ticket.assert_awaited_once()
    ticket_store.add.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_escalation_without_ticket_client() -> None:
    """Escalation without a ticket client should not raise; ticket_id stays empty."""
    agent = _make_agent(
        category=MessageCategory.SUPPORT_QUESTION,
        needs_escalation=True,
        ticket_client=None,
        ticket_store=None,
    )
    output = await agent.process(_make_input())

    assert output.needs_escalation is True
    assert output.ticket_id == ""


@pytest.mark.asyncio
async def test_process_ticket_creation_failure_is_swallowed() -> None:
    ticket_client = MagicMock()
    ticket_client.create_ticket = AsyncMock(side_effect=RuntimeError("API down"))

    ticket_store = MagicMock()
    ticket_store.add = AsyncMock()

    agent = _make_agent(
        category=MessageCategory.SUPPORT_QUESTION,
        needs_escalation=True,
        ticket_client=ticket_client,
        ticket_store=ticket_store,
    )
    # Must not raise even though create_ticket fails
    output = await agent.process(_make_input())
    assert output.ticket_id == ""


# ---------------------------------------------------------------------------
# Approved memory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_stores_approved_memory_on_resolution() -> None:
    approved_memory = MagicMock()
    approved_memory.store = AsyncMock()

    agent = _make_agent(
        category=MessageCategory.SUPPORT_QUESTION,
        store_resolution=True,
        approved_memory=approved_memory,
    )
    output = await agent.process(_make_input())

    assert output.store_resolution is True
    approved_memory.store.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_does_not_store_memory_on_escalation() -> None:
    approved_memory = MagicMock()
    approved_memory.store = AsyncMock()

    agent = _make_agent(
        category=MessageCategory.SUPPORT_QUESTION,
        store_resolution=True,
        needs_escalation=True,
        approved_memory=approved_memory,
    )
    await agent.process(_make_input())

    # When escalating, memory storage must be skipped
    approved_memory.store.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_memory_storage_failure_is_swallowed() -> None:
    approved_memory = MagicMock()
    approved_memory.store = AsyncMock(side_effect=RuntimeError("Qdrant unreachable"))

    agent = _make_agent(
        category=MessageCategory.SUPPORT_QUESTION,
        store_resolution=True,
        approved_memory=approved_memory,
    )
    # Must not raise even though memory.store() fails
    output = await agent.process(_make_input())
    assert output.should_reply is True


# ---------------------------------------------------------------------------
# Knowledge sources propagated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_propagates_knowledge_sources() -> None:
    agent = _make_agent(category=MessageCategory.SUPPORT_QUESTION)
    output = await agent.process(_make_input())

    assert len(output.knowledge_sources_used) == 1
    assert output.knowledge_sources_used[0].type == "documentation"
