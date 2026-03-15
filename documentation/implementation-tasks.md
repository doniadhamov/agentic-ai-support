# Implementation Tasks — AI Agentic Support Bot

Breakdown of all implementation work into small, actionable tasks.
Check off each task as it is completed.

---

## Phase 1 — Project Foundation ✅

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 1.1 | `pyproject.toml` with all deps, ruff, mypy config | `pyproject.toml` | ✅ |
| 1.2 | `.env.example` with all env var placeholders | `.env.example` | ✅ |
| 1.3 | `.gitignore` (Python + .env + uv.lock) | `.gitignore` | ✅ |
| 1.4 | `docker-compose.yml` for Qdrant with health check | `docker-compose.yml` | ✅ |
| 1.5 | `Settings(BaseSettings)` with `get_settings()` | `src/config/settings.py` | ✅ |
| 1.6 | loguru setup: console + rotating file sinks | `src/utils/logging.py` | ✅ |
| 1.7 | `CLAUDE.md` with conventions, env vars, flow | `CLAUDE.md` | ✅ |
| 1.8 | All `src/**/__init__.py` stubs | (multiple) | ✅ |
| 1.9 | Language helper + fallback detection | `src/utils/language.py` | ✅ |
| 1.10 | Async retry decorator (tenacity) | `src/utils/retry.py` | ✅ |
| 1.11 | `tests/conftest.py` with env var fixtures | `tests/conftest.py` | ✅ |

---

## Phase 2 — Zendesk Ingestion Pipeline ✅

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 2.1 | Async Zendesk API client: `/categories`, `/sections`, `/articles` with pagination + retry | `src/ingestion/zendesk_client.py` | ✅ |
| 2.2 | HTML → ordered `(text_block, image_url)` pairs via BeautifulSoup | `src/ingestion/article_processor.py` | ✅ |
| 2.3 | Async image byte download with local file cache | `src/ingestion/image_downloader.py` | ✅ |
| 2.4 | Sliding-window chunker → `ArticleChunk` Pydantic model | `src/ingestion/chunker.py` | ✅ |
| 2.5 | `SyncManager`: `full_ingest()` + `delta_sync()` via `updated_at` | `src/ingestion/sync_manager.py` | ✅ |
| 2.6 | CLI script: full ingestion with `--dry-run` flag | `scripts/ingest_zendesk.py` | ✅ |
| 2.7 | Unit tests: chunker with/without images, overlap | `tests/unit/test_chunker.py` | ✅ |

---

## Phase 3 — Embedding & Vector DB ✅

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 3.1 | `GeminiEmbedder`: `embed_text()` + `embed_multimodal()` | `src/embeddings/gemini_embedder.py` | ✅ |
| 3.2 | Async Qdrant wrapper: `upsert_points()`, `search()`, `delete_by_filter()` | `src/vector_db/qdrant_client.py` | ✅ |
| 3.3 | Collection constants + `create_collections_if_not_exist()` (768-dim, cosine) | `src/vector_db/collections.py` | ✅ |
| 3.4 | `ArticleIndexer.index_chunk()`: embed → UUID5 PointStruct → upsert | `src/vector_db/indexer.py` | ✅ |
| 3.5 | CLI: print Qdrant collection stats | `scripts/check_qdrant.py` | ✅ |
| 3.6 | Integration test: ingest 3 chunks, verify retrieval | `tests/integration/test_ingestion_pipeline.py` | ✅ |

---

## Phase 4 — RAG Retrieval ✅

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 4.1 | `build_query(question, language) → str` | `src/rag/query_builder.py` | ✅ |
| 4.2 | `RAGRetriever.retrieve()`: embed text query, search both collections, merge + deduplicate | `src/rag/retriever.py` | ✅ |
| 4.3 | `ScoreThresholdFilter.filter()`: drop below `SUPPORT_MIN_CONFIDENCE_SCORE`, tag source | `src/rag/reranker.py` | ✅ |
| 4.4 | Integration test: seed Qdrant, test en/ru/uz retrieval precision | `tests/integration/test_rag_retrieval.py` | ✅ |

---

## Phase 5 — AI Agent Core ✅

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 5.1 | Pydantic schemas: `AgentInput`, `AgentOutput`, `ClassifierResult`, `ExtractorResult`, `GeneratorResult`, `KnowledgeSource` | `src/agent/schemas.py` | ✅ |
| 5.2 | Full system prompt constant (from `project-requirement.md`) | `src/agent/prompts/system_prompt.py` | ✅ |
| 5.3 | Classifier few-shot prompt (examples in en/ru/uz) | `src/agent/prompts/classifier_prompt.py` | ✅ |
| 5.4 | Extractor prompt | `src/agent/prompts/extractor_prompt.py` | ✅ |
| 5.5 | Generator prompt (grounded answer with retrieved chunks) | `src/agent/prompts/generator_prompt.py` | ✅ |
| 5.6 | `MessageClassifier.classify()` — Claude tool-use, temperature=0.0 | `src/agent/classifier.py` | ✅ |
| 5.7 | `QuestionExtractor.extract()` — Claude tool-use, temperature=0.0 | `src/agent/extractor.py` | ✅ |
| 5.8 | `AnswerGenerator.generate()` — Claude tool-use, temperature=0.2 | `src/agent/generator.py` | ✅ |
| 5.9 | `SupportAgent.process()` orchestrator | `src/agent/agent.py` | ✅ |
| 5.10 | Unit tests: all 4 classification categories, mocked Claude responses | `tests/unit/test_classifier.py`, `test_extractor.py`, `test_generator.py` | ✅ |

---

## Phase 6 — Telegram Integration ✅

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 6.1 | `GroupContext`: `deque[MessageRecord]`, asyncio Lock, `open_tickets` | `src/telegram/context/group_context.py` | ✅ |
| 6.2 | `ContextManager` singleton: `get_or_create(chat_id)` | `src/telegram/context/context_manager.py` | ✅ |
| 6.3 | `format_reply(AgentOutput) → str`: Telegram Markdown, 4096-char limit | `src/telegram/formatter.py` | ✅ |
| 6.4 | aiogram Router: group/supergroup message handler, `reply_to_message_id` | `src/telegram/handlers/message_handler.py` | ✅ |
| 6.5 | Optional webhook handler for ticket push callbacks | `src/telegram/handlers/webhook_handler.py` | ✅ |
| 6.6 | `create_bot()`: Bot + Dispatcher, register handlers, start poller background task, long-poll/webhook toggle | `src/telegram/bot.py` | ✅ |
| 6.7 | Unit test: `GroupContext` sliding window, lock behaviour | `tests/unit/test_group_context.py` | ✅ |

---

## Phase 7 — Escalation Workflow ✅

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 7.1 | `TicketCreate`, `TicketRecord`, `TicketResponse` Pydantic models | `src/escalation/ticket_schemas.py` | ✅ |
| 7.2 | `TicketAPIClient`: `create_ticket()`, `get_ticket_status()`, tenacity retry | `src/escalation/ticket_client.py` | ✅ |
| 7.3 | `TicketStore`: in-memory + JSON file persistence, `add()`, `get_open_tickets()`, `close()` | `src/escalation/ticket_store.py` | ✅ |
| 7.4 | `TicketPoller.run()`: poll loop → send Telegram reply → store approved Q&A in `datatruck_memory` → close ticket | `src/escalation/poller.py` | ✅ |
| 7.5 | Wire escalation into `agent.py` | `src/agent/agent.py` | ✅ |
| 7.6 | Integration test: mock ticket API, verify create payload + response delivery | `tests/integration/test_escalation_flow.py` | ✅ |

---

## Phase 8 — Approved Memory ✅

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 8.1 | `ApprovedAnswer` Pydantic model | `src/memory/memory_schemas.py` | ✅ |
| 8.2 | `ApprovedMemory.store()`: embed question → upsert `datatruck_memory` | `src/memory/approved_memory.py` | ✅ |
| 8.3 | Verify `RAGRetriever` searches both collections + tags source type | `src/rag/retriever.py` | ✅ |
| 8.4 | Verify `generator.py` prefers docs over memory (per spec) | `src/agent/generator.py` | ✅ |
| 8.5 | Unit test: store answer, retrieve, verify above threshold | `tests/unit/test_approved_memory.py` | ✅ |

---

## Phase 9 — Testing, Monitoring & Hardening ✅

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 9.1 | Complete unit test coverage for all agent components | `tests/unit/test_agent.py` | ✅ |
| 9.2 | Full E2E integration test: seed Qdrant → mock Telegram message → verify output | `tests/integration/test_e2e.py` | ✅ |
| 9.3 | Structured loguru logs with `group_id`, `user_id`, `category`, `language`, `ticket_id` on every agent decision | `src/agent/agent.py` | ✅ |
| 9.4 | Verify tenacity retries consistently on all external calls | (multiple) | ✅ |
| 9.5 | Scheduled Zendesk sync inside bot process (`ZENDESK_SYNC_INTERVAL_HOURS`) | `src/telegram/bot.py` | ✅ |
| 9.6 | CLI: `scripts/sync_zendesk.py` delta sync | `scripts/sync_zendesk.py` | ✅ |
| 9.7 | README: quickstart, env var reference, architecture overview | `README.md` | ✅ |

---

## Dependency Map

```
Phase 1 (Foundation)
  └─► Phase 2 (Zendesk Ingestion)
        └─► Phase 3 (Embedding + Qdrant)
              └─► Phase 4 (RAG Retrieval)
                    └─► Phase 5 (Agent Core)
                          ├─► Phase 6 (Telegram)   ← depends on 5
                          ├─► Phase 7 (Escalation) ← depends on 5, 6
                          └─► Phase 8 (Memory)     ← depends on 3, 7
                                └─► Phase 9 (Testing + Hardening)
```

Phases 2 and 3 can be partially parallelized (share only the `ArticleChunk` schema).
Phases 7 and 8 can be developed in parallel once Phase 5 is done.
