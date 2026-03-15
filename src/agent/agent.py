"""SupportAgent orchestrator: ties classifier → extractor → retriever → generator together."""

from __future__ import annotations

import anthropic
from loguru import logger

from src.agent.classifier import MessageClassifier
from src.agent.extractor import QuestionExtractor
from src.agent.generator import AnswerGenerator
from src.agent.schemas import AgentInput, AgentOutput, MessageCategory
from src.embeddings.gemini_embedder import GeminiEmbedder
from src.rag.reranker import ScoreThresholdFilter
from src.rag.retriever import RAGRetriever
from src.vector_db.qdrant_client import QdrantWrapper


class SupportAgent:
    """Orchestrates the full support-agent decision flow for a single incoming message.

    Decision flow::

        incoming message
          → classify (NON_SUPPORT | SUPPORT_QUESTION | CLARIFICATION_NEEDED | ESCALATION_REQUIRED)
          → extract standalone question + language
          → retrieve + filter chunks from Qdrant
          → generate grounded answer or escalation decision
          → return AgentOutput
    """

    def __init__(
        self,
        classifier: MessageClassifier,
        extractor: QuestionExtractor,
        retriever: RAGRetriever,
        reranker: ScoreThresholdFilter,
        generator: AnswerGenerator,
    ) -> None:
        self._classifier = classifier
        self._extractor = extractor
        self._retriever = retriever
        self._reranker = reranker
        self._generator = generator

    async def process(self, agent_input: AgentInput) -> AgentOutput:
        """Process a single incoming Telegram message end-to-end.

        Args:
            agent_input: Structured input with message text, IDs, and context window.

        Returns:
            :class:`AgentOutput` ready for consumption by the Telegram handler.
        """
        log_ctx = {
            "group_id": agent_input.group_id,
            "user_id": agent_input.user_id,
            "message_id": agent_input.message_id,
        }
        logger.bind(**log_ctx).info("Processing message")

        # --- Step 1: Classify -------------------------------------------------
        classification = await self._classifier.classify(
            message_text=agent_input.message_text,
            conversation_context=agent_input.conversation_context,
        )
        logger.bind(**log_ctx).info(
            "category={} language={}", classification.category.value, classification.language
        )

        # --- Step 2: NON_SUPPORT — nothing to do ------------------------------
        if classification.category == MessageCategory.NON_SUPPORT:
            return AgentOutput(
                category=MessageCategory.NON_SUPPORT,
                language=classification.language,
                should_reply=False,
            )

        # --- Step 3: Extract standalone question ------------------------------
        extraction = await self._extractor.extract(
            message_text=agent_input.message_text,
            conversation_context=agent_input.conversation_context,
        )
        language = extraction.language

        # --- Step 4: CLARIFICATION_NEEDED — no retrieval yet ------------------
        if classification.category == MessageCategory.CLARIFICATION_NEEDED:
            generation = await self._generator.generate(
                question=extraction.extracted_question,
                chunks=[],
                language=language,
            )
            return AgentOutput(
                category=MessageCategory.CLARIFICATION_NEEDED,
                language=language,
                should_reply=True,
                extracted_question=extraction.extracted_question,
                answer=generation.follow_up_question or generation.answer,
                follow_up_question=generation.follow_up_question,
                needs_retrieval=False,
                conversation_summary=extraction.conversation_summary,
            )

        # --- Step 5: Retrieve and filter knowledge chunks ---------------------
        raw_chunks = await self._retriever.retrieve(
            question=extraction.extracted_question,
            language=language,
        )
        filtered_chunks = self._reranker.filter(raw_chunks)

        logger.bind(**log_ctx).info(
            "Retrieval: {}/{} chunk(s) passed threshold",
            len(filtered_chunks),
            len(raw_chunks),
        )

        # --- Step 6: Generate answer ------------------------------------------
        generation = await self._generator.generate(
            question=extraction.extracted_question,
            chunks=filtered_chunks,
            language=language,
        )

        # Determine final category: generator may override to ESCALATION_REQUIRED
        final_category = (
            MessageCategory.ESCALATION_REQUIRED
            if generation.needs_escalation
            else classification.category
        )

        return AgentOutput(
            category=final_category,
            language=language,
            should_reply=True,
            extracted_question=extraction.extracted_question,
            answer=generation.answer,
            follow_up_question=generation.follow_up_question,
            needs_retrieval=True,
            needs_escalation=generation.needs_escalation,
            escalation_reason=generation.escalation_reason,
            conversation_summary=extraction.conversation_summary,
            knowledge_sources_used=generation.knowledge_sources_used,
            store_resolution=generation.store_resolution,
        )


def create_support_agent(anthropic_client: anthropic.AsyncAnthropic | None = None) -> SupportAgent:
    """Factory: build a :class:`SupportAgent` wired to live Qdrant and Gemini.

    Args:
        anthropic_client: Optional shared Anthropic async client.

    Returns:
        A fully configured :class:`SupportAgent`.
    """
    from src.embeddings.gemini_embedder import GeminiEmbedder
    from src.vector_db.qdrant_client import get_qdrant_client

    embedder = GeminiEmbedder()
    qdrant = get_qdrant_client()
    classifier = MessageClassifier(client=anthropic_client)
    extractor = QuestionExtractor(client=anthropic_client)
    retriever = RAGRetriever(embedder=embedder, qdrant=qdrant)
    reranker = ScoreThresholdFilter()
    generator = AnswerGenerator(client=anthropic_client)

    return SupportAgent(
        classifier=classifier,
        extractor=extractor,
        retriever=retriever,
        reranker=reranker,
        generator=generator,
    )
