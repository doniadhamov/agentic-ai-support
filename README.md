# DataTruck AI Support Bot

AI-powered Telegram support bot that monitors group chats, answers support questions
using multimodal RAG over Zendesk documentation, and escalates unanswerable issues to
human agents via an external ticket API.

## Architecture Overview

```
Telegram Group Message
        │
        ▼
  MessageClassifier  ──── NON_SUPPORT ──► (ignore)
  (Claude tool-use)  ──── CLARIFICATION_NEEDED ──► ask follow-up
        │
        ▼ SUPPORT_QUESTION / ESCALATION_REQUIRED
  QuestionExtractor  (clean standalone question + language)
        │
        ▼
  RAGRetriever  ──► datatruck_docs  (Zendesk articles)
                ──► datatruck_memory (approved Q&A pairs)
        │
        ▼
  ScoreThresholdFilter  (drop chunks below MIN_CONFIDENCE_SCORE)
        │
        ▼
  AnswerGenerator  ──► grounded answer  ──► format_reply() ──► Telegram
  (Claude tool-use) ──► needs_escalation ──► TicketAPIClient ──► human agent
                                             TicketPoller polls for resolution
```

### Key Components

| Module | Purpose |
|---|---|
| `src/agent/` | Orchestrator, classifier (Haiku), extractor (Haiku), generator (Sonnet), prompts |
| `src/rag/` | Query builder, retriever (Qdrant), score-threshold reranker |
| `src/ingestion/` | Zendesk API client, HTML processor, chunker, sync manager |
| `src/vector_db/` | Qdrant async wrapper, collection setup, article indexer |
| `src/embeddings/` | Gemini Embedding 2 (`gemini-embedding-2-preview`) |
| `src/escalation/` | Ticket API client, ticket store (PostgreSQL or JSON fallback), background poller |
| `src/database/` | SQLAlchemy 2.0 async engine, ORM models, repository helpers |
| `src/api/` | FastAPI health check and metrics endpoints (port 8000) |
| `src/memory/` | Approved-answer store (resolved Q&A back into Qdrant) |
| `src/telegram/` | aiogram bot, per-group context manager, message/webhook handlers |

## Quickstart

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- Docker + Docker Compose

### 1. Clone and configure

```bash
git clone <repo-url>
cd agentic-ai-support
cp .env.example .env
# Edit .env and fill in all required API keys (see Environment Variables below)
```

### 2. Start infrastructure

```bash
make infra
# Qdrant available at http://localhost:6333
# PostgreSQL available at localhost:5432
```

> PostgreSQL is optional — if `DATABASE_URL` is left empty, the bot falls back to
> in-memory context and JSON file storage for tickets.

### 3. Install dependencies

```bash
uv sync
```

### 4. Ingest Zendesk documentation

```bash
# Full ingestion (first run)
uv run python scripts/ingest_zendesk.py

# Dry-run (validate articles without writing to Qdrant)
uv run python scripts/ingest_zendesk.py --dry-run
```

### 5. Start the bot

```bash
uv run python -m src.telegram.bot
```

The bot starts in long-polling mode by default. Set `TELEGRAM_WEBHOOK_URL` to switch to
webhook mode (the server listens on `:8080`).

The FastAPI health/metrics server runs alongside the bot on port **8000**:
- `GET /health` — liveness probe
- `GET /health/ready` — readiness probe (checks Qdrant + PostgreSQL)
- `GET /metrics` — operational metrics (doc/memory counts, open tickets)

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | Bot token from BotFather |
| `ANTHROPIC_API_KEY` | ✅ | — | Anthropic API key |
| `GOOGLE_API_KEY` | ✅ | — | Google API key for Gemini Embedding 2 |
| `ANTHROPIC_MODEL` | | `claude-sonnet-4-6` | Sonnet model for answer generation |
| `ANTHROPIC_FAST_MODEL` | | `claude-haiku-4-5` | Haiku model for classification/extraction (~10x cheaper) |
| `DATABASE_URL` | | `` | PostgreSQL async URL (empty = JSON/in-memory fallback) |
| `QDRANT_URL` | | `http://localhost:6333` | Qdrant instance URL |
| `QDRANT_API_KEY` | | `` | Qdrant API key (if using Qdrant Cloud) |
| `ZENDESK_SUBDOMAIN` | | `support.datatruck.io` | Zendesk subdomain |
| `ZENDESK_API_TOKEN` | | `` | Zendesk API token |
| `ZENDESK_EMAIL` | | `` | Zendesk account email |
| `SUPPORT_API_BASE_URL` | | `` | External ticket API base URL |
| `SUPPORT_API_KEY` | | `` | External ticket API key |
| `TICKET_CALLBACK_MODE` | | `poll` | `poll` or `webhook` |
| `TICKET_POLL_INTERVAL_SECONDS` | | `60` | Ticket polling interval |
| `SUPPORT_MIN_CONFIDENCE_SCORE` | | `0.75` | Minimum Qdrant cosine score to accept a chunk |
| `GROUP_CONTEXT_WINDOW` | | `20` | Recent messages to retain per group |
| `RAG_TOP_K` | | `5` | Number of chunks to retrieve |
| `ZENDESK_SYNC_INTERVAL_HOURS` | | `6` | Auto-sync interval (0 = disabled) |
| `GEMINI_EMBEDDING_MODEL` | | `models/gemini-embedding-2-preview` | Gemini embedding model |
| `GEMINI_EMBEDDING_DIMENSIONS` | | `3072` | Embedding output dimensionality |
| `TELEGRAM_WEBHOOK_URL` | | `` | Webhook base URL (empty = long-polling) |
| `LOG_LEVEL` | | `INFO` | Logging level |
| `LOG_FILE` | | `logs/app.log` | Log file path |

## CLI Scripts

```bash
# Full Zendesk ingestion
uv run python scripts/ingest_zendesk.py [--dry-run]

# Delta sync (articles updated in the last N hours)
uv run python scripts/sync_zendesk.py [--hours N] [--dry-run]

# Inspect Qdrant collection stats
uv run python scripts/check_qdrant.py
```

## Testing

```bash
# All tests
uv run pytest

# Unit tests only (no external services required)
uv run pytest tests/unit/

# Integration tests (requires local Qdrant: docker compose up -d)
uv run pytest tests/integration/
```

### Test coverage

| Suite | Tests | Description |
|---|---|---|
| `tests/unit/test_classifier.py` | 7 | All 4 categories, 3 languages, error handling |
| `tests/unit/test_extractor.py` | 6 | Question extraction, language detection |
| `tests/unit/test_generator.py` | 7 | Answer generation, escalation decision |
| `tests/unit/test_agent.py` | 9 | Full orchestrator — mocked sub-components |
| `tests/unit/test_group_context.py` | 10 | Sliding window, ticket tracking, concurrency |
| `tests/unit/test_chunker.py` | 12 | Chunking, overlap, image association |
| `tests/unit/test_approved_memory.py` | 8 | Memory storage, retrieval, threshold |
| `tests/integration/test_ingestion_pipeline.py` | 2 | Ingest → Qdrant → verify |
| `tests/integration/test_rag_retrieval.py` | 8 | en/ru/uz retrieval, dedup, threshold |
| `tests/integration/test_escalation_flow.py` | 9 | Ticket create/poll/close cycle + approved memory |
| `tests/integration/test_e2e.py` | 3 | Full agent flow: seed → classify → retrieve → answer |

## Linting and Formatting

```bash
uv run ruff check .
uv run ruff format .
```

## Qdrant Collections

| Collection | Purpose | Dimensions | Distance |
|---|---|---|---|
| `datatruck_docs` | Zendesk article chunks | 3072 | Cosine |
| `datatruck_memory` | Approved resolved Q&A pairs | 3072 | Cosine |

Point IDs are deterministic UUID5 derived from `(article_id, chunk_index)` so that
re-ingestion is idempotent.
