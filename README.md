# DataTruck AI Support Bot

AI-powered Telegram support bot that monitors group chats, answers support questions
using multimodal RAG over Zendesk documentation, and provides bidirectional
Telegram ↔ Zendesk sync so human support agents can respond from Zendesk while
users stay in Telegram.

## Architecture Overview

```
Telegram Group Message (text / photo / voice / audio / image document)
        │
        ▼
  Preprocessor  ──► text: as-is
                ──► photo: download bytes → images[]
                ──► voice/audio: download → Gemini Flash transcription → text
                ──► document(image/*): download → images[]
        │
        ▼ (store ALL messages in PostgreSQL)
  RAG Probe (embed text + Qdrant top-3)  ──── score ≥ threshold ──► SUPPORT_QUESTION (skip classifier)
        │                                      (fast & cheap)
        ▼ no strong match
  MessageClassifier  ──── NON_SUPPORT ──► (ignore — no further API calls)
  (Claude Vision)    ──── CLARIFICATION_NEEDED ──► ask follow-up
        │                  (sees images + text + conversation history)
        ▼ SUPPORT_QUESTION / ESCALATION_REQUIRED
  QuestionExtractor  (extracted information + language; describes images, voice, text)
  (Claude Vision)
        │
        ▼
  RAGRetriever  ──► datatruck_docs  (Zendesk articles)
                ──► datatruck_memory (approved Q&A pairs from closed tickets)
        │
        ▼
  ScoreThresholdFilter  (drop chunks below MIN_CONFIDENCE_SCORE)
        │
        ▼
  AnswerGenerator  ──► grounded answer  ──► format_reply() ──► Telegram + Zendesk
  (Claude Vision)  ──► clarification   ──► follow-up question ──► Telegram + Zendesk
                   ──► needs_escalation ──► silent (no Telegram reply) + escalation notice ──► Zendesk only
        │
        ▼
  ZendeskSyncService
        │
        ├── ThreadRouter (Claude Haiku) analyzes message + active tickets + history
        │     ├── route_to_existing  ──► add comment to existing Zendesk ticket
        │     ├── create_new         ──► create new Zendesk ticket + add comment
        │     └── skip_zendesk       ──► store in DB only (no Zendesk sync)
        │
        └── Upload photos/attachments to Zendesk Attachments API
                (two-step: upload → get token → reference in comment)

Zendesk Agent Responds
        │
        ▼
  POST /api/zendesk/events  (Zendesk trigger sends comment JSON)
        │
        ├── Look up ConversationThread → find Telegram group_id
        ├── Store agent message in DB (source="zendesk")
        ├── Send message to Telegram group
        └── If ticket solved/closed:
              ├── Close conversation thread
              ├── TicketSummarizer: summarize → generalized Q&A (de-identified)
              └── Store in datatruck_memory for future RAG retrieval
```

### Key Components

| Module | Purpose |
|---|---|
| `src/agent/` | Orchestrator, classifier (Haiku Vision), extractor (Haiku Vision), generator (Sonnet Vision), thread router (Haiku), ticket summarizer, prompts |
| `src/rag/` | Query builder, retriever (Qdrant), score-threshold reranker |
| `src/ingestion/` | Zendesk Help Center API client (read-only), HTML processor, chunker, sync manager |
| `src/vector_db/` | Qdrant async wrapper, collection setup, article indexer |
| `src/embeddings/` | Gemini Embedding 2 (`gemini-embedding-2-preview`) |
| `src/escalation/` | `ZendeskTicketClient` (Support API v2), `ConversationThreadStore`, `ZendeskSyncService`, Zendesk→Telegram webhook handler |
| `src/database/` | SQLAlchemy 2.0 async engine, ORM models (`MessageRow`, `ConversationThread`, `TicketRow`), repository helpers |
| `src/api/` | FastAPI health check, metrics, and Zendesk webhook endpoints (port 8000) |
| `src/memory/` | Approved-answer store (resolved Q&A from closed tickets back into Qdrant) |
| `src/telegram/` | aiogram bot, per-group context manager, message handler (text + photo + voice) |

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

> **PostgreSQL is required** for conversation message storage and Zendesk ticket sync.

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

The FastAPI server runs alongside the bot on port **8000**:
- `GET /health` — liveness probe
- `GET /health/ready` — readiness probe (checks Qdrant + PostgreSQL + Zendesk)
- `GET /metrics` — operational metrics (doc/memory counts, open tickets, active threads)
- `POST /api/zendesk/events` — receives Zendesk agent comments for delivery to Telegram

### 6. Configure Zendesk webhook

In your Zendesk admin, create a **Trigger** that fires when an agent adds a public comment:
- **Action**: Notify webhook → `POST https://<your-bot-host>:8000/api/zendesk/events`
- **Payload** (JSON):
  ```json
  {
    "ticket_id": {{ticket.id}},
    "comment_body": {{ticket.latest_comment}},
    "author_id": {{current_user.id}},
    "ticket_status": "{{ticket.status}}"
  }
  ```

Set `ZENDESK_ADMIN_USER_ID` in `.env` to the Zendesk user ID of the API token owner (admin account). The webhook handler uses `detail.actor_id` to skip all API-originated comments (user messages synced from Telegram, bot replies). `ZENDESK_BOT_USER_ID` is auto-resolved at startup (env → DB → create via Profiles API) and used as `author_id` for bot-authored comments.

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | Bot token from BotFather |
| `ANTHROPIC_API_KEY` | ✅ | — | Anthropic API key |
| `GOOGLE_API_KEY` | ✅ | — | Google API key for Gemini Embedding 2 |
| `ZENDESK_API_TOKEN` | ✅ | — | Zendesk API token |
| `ZENDESK_EMAIL` | ✅ | — | Zendesk account email |
| `DATABASE_URL` | ✅ | — | PostgreSQL async URL (required for Zendesk ticket sync) |
| `ANTHROPIC_MODEL` | | `claude-sonnet-4-6` | Sonnet model for answer generation |
| `ANTHROPIC_FAST_MODEL` | | `claude-haiku-4-5` | Haiku model for classification/extraction/thread routing |
| `QDRANT_URL` | | `http://localhost:6333` | Qdrant instance URL |
| `QDRANT_API_KEY` | | `` | Qdrant API key (if using Qdrant Cloud) |
| `ZENDESK_HELP_CENTER_SUBDOMAIN` | | `support.datatruck.io` | Zendesk Help Center subdomain |
| `ZENDESK_API_SUBDOMAIN` | | `` | Zendesk Support Tickets API subdomain (falls back to Help Center) |
| `ZENDESK_BOT_USER_ID` | | `0` | Zendesk user ID of the bot (auto-resolved at startup if not set) |
| `ZENDESK_ADMIN_USER_ID` | ✅ | — | Zendesk user ID of the API token owner (filters API-originated webhook comments) |
| `SUPPORT_MIN_CONFIDENCE_SCORE` | | `0.70` | Minimum Qdrant cosine score to accept a chunk |
| `RAG_OVERRIDE_MIN_SCORE` | | `0.75` | Min RAG score to skip classifier (fast-path to SUPPORT_QUESTION) |
| `GROUP_CONTEXT_WINDOW` | | `20` | Recent messages to retain per group |
| `RAG_TOP_K` | | `5` | Number of chunks to retrieve |
| `ZENDESK_SYNC_INTERVAL_HOURS` | | `6` | Auto-sync interval for Zendesk articles (0 = disabled) |
| `GEMINI_EMBEDDING_MODEL` | | `models/gemini-embedding-2-preview` | Gemini embedding model |
| `GEMINI_EMBEDDING_DIMENSIONS` | | `3072` | Embedding output dimensionality |
| `GEMINI_FLASH_MODEL` | | `gemini-2.0-flash` | Gemini Flash model for voice transcription |
| `MAX_VOICE_DURATION_SECONDS` | | `120` | Max voice message duration to transcribe |
| `TELEGRAM_WEBHOOK_URL` | | `` | Webhook base URL (empty = long-polling) |
| `ADMIN_PASSWORD` | | `` | Admin dashboard password (empty = no auth) |
| `ZENDESK_TELEGRAM_CHAT_ID_FIELD_ID` | | `` | Zendesk custom field ID for Telegram chat ID |
| `LOG_LEVEL` | | `INFO` | Logging level |
| `LOG_FILE` | | `logs/app.log` | Log file path |

## Docker Compose

| File | Purpose |
|---|---|
| `docker-compose.yml` | Full stack — Qdrant + PostgreSQL + ingestion job + bot + admin dashboard |
| `docker-compose.qdrant.yml` | Qdrant + PostgreSQL — for local development (bot runs on host) |

### Run fully in Docker

```bash
cp .env.example .env        # fill in all API keys
make build                   # build the bot Docker image
make ingest                  # one-shot Zendesk article ingestion
make up                      # start everything
make logs                    # follow bot logs
```

### Make targets

| Target | What it does |
|---|---|
| `make build` | Build the bot Docker image |
| `make up` | Start Qdrant + PostgreSQL + bot + dashboard (detached) |
| `make down` | Stop all services |
| `make down-v` | Stop all services and wipe volumes |
| `make ingest` | One-shot Zendesk ingestion |
| `make sync` | One-shot Zendesk delta sync |
| `make restart` | Restart bot container |
| `make logs` | Follow bot logs |
| `make qdrant-only` | Start Qdrant only (local dev) |
| `make infra` | Start Qdrant + PostgreSQL (local dev) |
| `make dashboard` | Start admin dashboard (Docker) |
| `make dashboard-local` | Start admin dashboard locally |
| `make dashboard-logs` | Follow dashboard logs |
| `make lint` | Run ruff check + format |
| `make test` | Run all tests |
| `make test-unit` | Unit tests only |
| `make test-int` | Integration tests (requires Qdrant) |

## CLI Scripts

```bash
# Full Zendesk ingestion
uv run python scripts/ingest_zendesk.py [--dry-run]

# Delta sync (articles updated in the last N hours)
uv run python scripts/sync_zendesk.py [--hours N] [--dry-run]

# Inspect Qdrant collection stats
uv run python scripts/check_qdrant.py
```

## Admin Dashboard

Streamlit-based admin UI at `http://localhost:8501`:

- **Home** — live metrics (active groups, ingested articles, memory entries, open tickets)
- **Groups** — manage Telegram group allowlist (add/remove, search)
- **Knowledge Base** — browse `datatruck_docs` / `datatruck_memory`; Delta Sync and Full Re-ingest
- **Upload** — ingest PDF/DOCX/TXT/MD files into the knowledge base
- **Tickets** — conversation threads with Zendesk ticket links, status metrics, search

## Testing

```bash
# All tests
make test

# Unit tests only (no external services required)
make test-unit

# Integration tests (requires local Qdrant: make infra)
make test-int
```

## Linting and Formatting

```bash
make lint
# or manually:
uv run ruff check .
uv run ruff format .
```

## Qdrant Collections

| Collection | Purpose | Dimensions | Distance |
|---|---|---|---|
| `datatruck_docs` | Zendesk article chunks | 3072 | Cosine |
| `datatruck_memory` | Approved resolved Q&A pairs (from closed tickets) | 3072 | Cosine |

Point IDs are deterministic UUID5 derived from `(article_id, chunk_index)` so that
re-ingestion is idempotent.

## Bidirectional Zendesk Sync

The bot syncs every Telegram group conversation to Zendesk tickets:

1. **Telegram → Zendesk**: Every message is analyzed by the AI ThreadRouter to determine which Zendesk ticket it belongs to. Photos are uploaded via the Zendesk Attachments API. AI responses and clarification follow-ups are posted as Zendesk comments (authored by the bot's Zendesk user). When escalating (no RAG answer), the bot stays silent in Telegram and posts the escalation reason as a Zendesk comment for human agents.

2. **Zendesk → Telegram**: When a support agent responds in Zendesk, a webhook trigger sends the comment to the bot's `/api/zendesk/events` endpoint, which delivers it to the correct Telegram group.

3. **Ticket closure**: When a ticket is solved/closed in Zendesk, the TicketSummarizer generates a de-identified Q&A summary and stores it in `datatruck_memory` for future RAG retrieval.

### Thread Routing

The `ThreadRouter` (Claude Haiku) intelligently routes messages:
- Follow-ups go to the existing ticket
- New topics create new tickets
- If User B has the same problem as User A's active ticket, the message routes to User A's ticket (avoiding duplicates)
- A Telegram reply doesn't automatically route to the replied-to message's ticket — the AI analyzes whether the content matches
- Non-support messages (e.g. "thanks") are routed to an active ticket if contextually related
