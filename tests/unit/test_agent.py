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
    answer: str = "Here is your answer.",
    follow_up: str = "",
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
    agent = _make_agent(category=MessageCategory.SUPPORT_QUESTION, answer="Go to Settings → Reset.")
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
    # Retriever is called once for the RAG probe, but NOT for the main retrieval
    assert agent._retriever.retrieve.call_count == 1  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# ESCALATION — generator decides
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_escalation_detected() -> None:
    """When generator flags escalation, the output should reflect it."""
    agent = _make_agent(
        category=MessageCategory.SUPPORT_QUESTION,
        needs_escalation=True,
    )
    output = await agent.process(_make_input())

    assert output.needs_escalation is True
    assert output.category == MessageCategory.ESCALATION_REQUIRED


# ---------------------------------------------------------------------------
# Knowledge sources propagated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_propagates_knowledge_sources() -> None:
    agent = _make_agent(category=MessageCategory.SUPPORT_QUESTION)
    output = await agent.process(_make_input())

    assert len(output.knowledge_sources_used) == 1
    assert output.knowledge_sources_used[0].type == "documentation"
