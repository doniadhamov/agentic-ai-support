"""SupportAgent orchestrator: ties classifier → extractor → retriever → generator together."""

from __future__ import annotations

import anthropic
from loguru import logger

from src.agent.classifier import MessageClassifier
from src.agent.extractor import QuestionExtractor
from src.agent.generator import AnswerGenerator
from src.agent.schemas import AgentInput, AgentOutput, MessageCategory
from src.config.settings import get_settings
from src.escalation.ticket_client import TicketAPIClient
from src.escalation.ticket_schemas import TicketCreate
from src.escalation.ticket_store import TicketStore
from src.memory.approved_memory import ApprovedMemory
from src.rag.reranker import ScoreThresholdFilter
from src.rag.retriever import RAGRetriever


class SupportAgent:
    """Orchestrates the full support-agent decision flow for a single incoming message.

    Decision flow::

        incoming message
          → RAG probe (embed + Qdrant top-3) — fast & cheap
          → if strong match (≥ RAG_OVERRIDE_MIN_SCORE): treat as SUPPORT_QUESTION directly
          → if no match: classify (NON_SUPPORT | SUPPORT_QUESTION | CLARIFICATION_NEEDED | ESCALATION_REQUIRED)
          → extract standalone question + language
          → retrieve + filter chunks from Qdrant
          → generate grounded answer or escalation decision
          → if escalated: create ticket via TicketAPIClient, persist in TicketStore
          → return AgentOutput
    """

    def __init__(
        self,
        classifier: MessageClassifier,
        extractor: QuestionExtractor,
        retriever: RAGRetriever,
        reranker: ScoreThresholdFilter,
        generator: AnswerGenerator,
        ticket_client: TicketAPIClient | None = None,
        ticket_store: TicketStore | None = None,
        approved_memory: ApprovedMemory | None = None,
    ) -> None:
        self._classifier = classifier
        self._extractor = extractor
        self._retriever = retriever
        self._reranker = reranker
        self._generator = generator
        self._ticket_client = ticket_client
        self._ticket_store = ticket_store
        self._approved_memory = approved_memory

    async def process(self, agent_input: AgentInput) -> AgentOutput:
        """Process a single incoming Telegram message end-to-end.

        Args:
            agent_input: Structured input with message text, IDs, and context window.

        Returns:
            :class:`AgentOutput` ready for consumption by the Telegram handler.
        """
        settings = get_settings()
        log_ctx = {
            "group_id": agent_input.group_id,
            "user_id": agent_input.user_id,
            "message_id": agent_input.message_id,
        }
        logger.bind(**log_ctx).info("Processing message")

        # --- Step 1: RAG probe (fast & cheap — embedding + Qdrant) ------------
        # Skip RAG probe only when text is completely empty (e.g., photo-only)
        message_text = agent_input.message_text.strip()
        if message_text:
            probe_chunks = await self._retriever.retrieve(
                question=message_text,
                language="en",  # language unknown yet, "en" is fine for embedding
                top_k=3,
            )
            best_score = max((c.score for c in probe_chunks), default=0.0)
        else:
            probe_chunks = []
            best_score = 0.0

        logger.bind(**log_ctx).info(
            "RAG probe: best_score={:.3f} (threshold={:.3f}, text_len={})",
            best_score,
            settings.rag_override_min_score,
            len(message_text),
        )

        # --- Step 2: Decide path based on RAG probe result --------------------
        if best_score >= settings.rag_override_min_score:
            # Strong documentation match — skip classifier, treat as SUPPORT_QUESTION
            logger.bind(**log_ctx).info("RAG fast-path: strong doc match, skipping classifier")
            category = MessageCategory.SUPPORT_QUESTION
        else:
            # No strong match — run classifier for NON_SUPPORT / CLARIFICATION / ESCALATION
            classification = await self._classifier.classify(
                message_text=agent_input.message_text,
                conversation_context=agent_input.conversation_context,
                images=agent_input.images or None,
            )
            category = classification.category
            logger.bind(**log_ctx).info(
                "Classified: category={} language={}",
                category.value,
                classification.language,
            )

            # Images attached in a support group are almost always screenshots of a
            # problem — override NON_SUPPORT so the pipeline runs normally.
            # If there is no accompanying text, ask for clarification instead of
            # guessing what the user needs.
            if category == MessageCategory.NON_SUPPORT and agent_input.images:
                if message_text:
                    logger.bind(**log_ctx).info(
                        "Classifier returned NON_SUPPORT but message has images + text — overriding to SUPPORT_QUESTION"
                    )
                    category = MessageCategory.SUPPORT_QUESTION
                else:
                    logger.bind(**log_ctx).info(
                        "Classifier returned NON_SUPPORT but message has images without text — overriding to CLARIFICATION_NEEDED"
                    )
                    category = MessageCategory.CLARIFICATION_NEEDED

            # NON_SUPPORT — nothing to do
            if category == MessageCategory.NON_SUPPORT:
                return AgentOutput(
                    category=MessageCategory.NON_SUPPORT,
                    language=classification.language,
                    should_reply=False,
                )

        log_ctx["category"] = category.value

        # --- Step 3: Extract information from message -------------------------
        extraction = await self._extractor.extract(
            message_text=agent_input.message_text,
            conversation_context=agent_input.conversation_context,
            images=agent_input.images or None,
        )
        language = extraction.language

        # --- Step 4: CLARIFICATION_NEEDED — no retrieval yet ------------------
        if category == MessageCategory.CLARIFICATION_NEEDED:
            generation = await self._generator.generate(
                question=extraction.extracted_question,
                chunks=[],
                language=language,
                images=agent_input.images or None,
            )
            return AgentOutput(
                category=MessageCategory.CLARIFICATION_NEEDED,
                language=language,
                should_reply=True,
                extracted_question=extraction.extracted_question,
                answer="",
                follow_up_question=generation.follow_up_question or generation.answer,
                needs_retrieval=False,
                conversation_summary=extraction.conversation_summary,
            )

        # --- Step 5: Retrieve and filter knowledge chunks ---------------------
        # Always runs on the extractor's output — this is the real retrieval
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
            images=agent_input.images or None,
        )

        # Determine final category: generator may override to ESCALATION_REQUIRED
        final_category = (
            MessageCategory.ESCALATION_REQUIRED if generation.needs_escalation else category
        )

        # --- Step 7: Create escalation ticket if needed -----------------------
        ticket_id = ""
        if generation.needs_escalation and self._ticket_client and self._ticket_store:
            try:
                ticket_payload = TicketCreate(
                    group_id=agent_input.group_id,
                    user_id=agent_input.user_id,
                    message_id=agent_input.message_id,
                    language=language,
                    question=extraction.extracted_question,
                    conversation_summary=extraction.conversation_summary,
                )
                ticket_record = await self._ticket_client.create_ticket(ticket_payload)
                await self._ticket_store.add(ticket_record)
                ticket_id = ticket_record.ticket_id
                log_ctx["ticket_id"] = ticket_id
                logger.bind(**log_ctx).info("Escalation ticket created ticket_id={}", ticket_id)
            except Exception as exc:  # noqa: BLE001
                logger.bind(**log_ctx).error("Failed to create escalation ticket — {}", exc)

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
            ticket_id=ticket_id,
            conversation_summary=extraction.conversation_summary,
            knowledge_sources_used=generation.knowledge_sources_used,
        )


def create_support_agent(
    anthropic_client: anthropic.AsyncAnthropic | None = None,
    ticket_client: TicketAPIClient | None = None,
    ticket_store: TicketStore | None = None,
) -> SupportAgent:
    """Factory: build a :class:`SupportAgent` wired to live Qdrant and Gemini.

    Args:
        anthropic_client: Optional shared Anthropic async client.
        ticket_client: Optional :class:`TicketAPIClient` for escalation.
        ticket_store: Optional :class:`TicketStore` for escalation persistence.

    Returns:
        A fully configured :class:`SupportAgent`.
    """
    from src.embeddings.gemini_embedder import GeminiEmbedder
    from src.memory.approved_memory import ApprovedMemory
    from src.vector_db.qdrant_client import get_qdrant_client

    embedder = GeminiEmbedder()
    qdrant = get_qdrant_client()
    classifier = MessageClassifier(client=anthropic_client)
    extractor = QuestionExtractor(client=anthropic_client)
    retriever = RAGRetriever(embedder=embedder, qdrant=qdrant)
    reranker = ScoreThresholdFilter()
    generator = AnswerGenerator(client=anthropic_client)
    memory = ApprovedMemory(embedder=embedder, qdrant=qdrant)

    return SupportAgent(
        classifier=classifier,
        extractor=extractor,
        retriever=retriever,
        reranker=reranker,
        generator=generator,
        ticket_client=ticket_client,
        ticket_store=ticket_store,
        approved_memory=memory,
    )
