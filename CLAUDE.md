# CLAUDE.md — AI Support Bot for DataTruck

## Project Purpose

AI-powered Telegram support bot: monitors multiple Telegram groups, classifies messages,
answers support questions via multimodal RAG (Zendesk docs + Gemini Embedding 2 + Qdrant),
and escalates unanswerable questions to human support. Bidirectional Telegram ↔ Zendesk sync:
every Telegram message is synced to a Zendesk ticket, and every Zendesk agent response is
delivered back to the Telegram group. Users never need to sign in to Zendesk.

## Tech Stack

- **Python 3.12+** with `uv` package manager
- **aiogram 3.x** — async Telegram bot framework
- **Anthropic Claude** — Haiku for classification/extraction/thread routing (fast + cheap), Sonnet for answer generation (quality)
- **Google Gemini Embedding 2** (`gemini-embedding-2-preview`) — multimodal embeddings (text + images)
- **Qdrant** — vector store (`datatruck_docs` + `datatruck_memory` collections, 3072-dim cosine)
- **PostgreSQL 16** — persistent storage for conversation messages, threads, and tickets (required)
- **SQLAlchemy 2.0 (async)** — ORM with asyncpg driver
- **FastAPI + Uvicorn** — health check / metrics / Zendesk webhook API on port 8000
- **httpx** — async HTTP client (Zendesk Support API, Help Center API)
- **pydantic-settings** — typed config from `.env`
- **loguru** — structured logging
- **tenacity** — retries on all external calls
- **Docker Compose** — full stack (Qdrant + PostgreSQL + bot) or infra-only for local dev

## Project Layout

```
src/
  config/         — settings.py (all env vars as pydantic BaseSettings, get_settings())
  telegram/       — bot.py, handlers/, formatter.py, preprocessor.py, context/ (per-group sliding window + asyncio Lock)
  agent/          — agent.py (orchestrator), classifier, extractor, generator, thread_router.py, ticket_summarizer.py, prompts/, schemas.py
  rag/            — retriever.py, reranker.py, query_builder.py
  ingestion/      — zendesk_client.py (read-only Help Center), article_processor.py, image_downloader.py, chunker.py, sync_manager.py, file_parser.py
  vector_db/      — qdrant_client.py, collections.py, indexer.py
  embeddings/     — gemini_embedder.py
  escalation/     — ticket_client.py (ZendeskTicketClient), ticket_store.py (ConversationThreadStore), sync_service.py (ZendeskSyncService), webhook_handler.py (Zendesk→Telegram), ticket_schemas.py
  database/       — engine.py, models.py (MessageRow, ConversationThread, TicketRow), repositories.py
  api/            — app.py (FastAPI health/metrics/webhook endpoints)
  memory/         — approved_memory.py, memory_schemas.py
  admin/          — group_store.py, file_ingest.py, schemas.py, dashboard/ (Streamlit admin UI)
  utils/          — logging.py, language.py, retry.py
scripts/          — ingest_zendesk.py, sync_zendesk.py, check_qdrant.py
tests/            — unit/ + integration/
```

## Compose Files

| File | Purpose |
|---|---|
| `docker-compose.yml` | Full stack — Qdrant + PostgreSQL + ingestion job + bot + admin dashboard |
| `docker-compose.qdrant.yml` | Qdrant + PostgreSQL — for local development (bot runs on host) |

## Running Locally (host machine, Qdrant in Docker)

```bash
cp .env.example .env        # fill in all API keys
make infra                  # starts Qdrant + PostgreSQL
uv sync                     # install dependencies
uv run python scripts/ingest_zendesk.py   # initial doc ingestion
uv run python -m src.telegram.bot         # start bot (long-polling + API on :8000)
```

## Running Fully in Docker

`docker-compose.yml` runs **everything** (Qdrant + PostgreSQL + ingestion + bot) inside Docker.

### Step 1 — Prepare your `.env`

```bash
cp .env.example .env
# Edit .env and fill in all API keys
```

> `QDRANT_URL` and `DATABASE_URL` in `.env` can stay as localhost values — the compose file
> overrides them to internal Docker network addresses automatically.

### Step 2 — Build the image

```bash
make build
```

### Step 3 — Run ingestion (first time only)

```bash
make ingest
```

Re-run any time to re-sync Zendesk content (idempotent).

### Step 4 — Start the bot

```bash
make up
```

### Step 5 — Check logs

```bash
make logs
```

### Useful make targets

| Target | What it does |
|---|---|
| `make build` | Build the bot Docker image |
| `make up` | Start Qdrant + PostgreSQL + bot + dashboard (detached) |
| `make down` | Stop all services |
| `make down-v` | Stop all services and wipe volumes |
| `make ingest` | One-shot Zendesk ingestion |
| `make sync` | One-shot Zendesk sync |
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

Open Qdrant dashboard: `http://localhost:6333/dashboard`
Open Admin dashboard: `http://localhost:8501`
Open API health check: `http://localhost:8000/health`

## Environment Variables (see .env.example for full list)

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `ANTHROPIC_MODEL` | Sonnet model for answer generation (default: `claude-sonnet-4-6`) |
| `ANTHROPIC_FAST_MODEL` | Haiku model for classification/extraction/thread routing (default: `claude-haiku-4-5`) |
| `GOOGLE_API_KEY` | Google API key for Gemini embeddings |
| `DATABASE_URL` | PostgreSQL async URL (required for Zendesk ticket sync) |
| `QDRANT_URL` | Qdrant URL (default: `http://localhost:6333`) |
| `ZENDESK_SUBDOMAIN` | Zendesk subdomain (default: `support.datatruck.io`) |
| `ZENDESK_API_TOKEN` | Zendesk API token (required) |
| `ZENDESK_EMAIL` | Zendesk account email (required) |
| `ZENDESK_BOT_USER_ID` | Zendesk user ID of the bot, for filtering own webhook comments (default: `0`) |
| `GEMINI_EMBEDDING_MODEL` | Gemini embedding model (default: `models/gemini-embedding-2-preview`) |
| `GEMINI_EMBEDDING_DIMENSIONS` | Embedding output dimensions (default: `3072`) |
| `GEMINI_FLASH_MODEL` | Gemini Flash model for voice transcription (default: `gemini-2.0-flash`) |
| `MAX_VOICE_DURATION_SECONDS` | Max voice message duration to transcribe (default: `120`) |
| `SUPPORT_MIN_CONFIDENCE_SCORE` | Min Qdrant score to accept chunk (default: `0.70`) |
| `RAG_OVERRIDE_MIN_SCORE` | Min RAG score to override NON_SUPPORT → SUPPORT_QUESTION (default: `0.75`) |
| `GROUP_CONTEXT_WINDOW` | Recent messages to keep per group (default: `20`) |
| `RAG_TOP_K` | Number of top chunks to retrieve from Qdrant (default: `5`) |
| `ZENDESK_SYNC_INTERVAL_HOURS` | Hours between automatic Zendesk article sync (default: `6`, 0 = disabled) |
| `ADMIN_PASSWORD` | Admin dashboard password (default: empty = no auth) |
| `ALLOWED_GROUPS_FILE` | Path to group allowlist JSON (default: `data/allowed_groups.json`) |
| `LOG_LEVEL` | Log level (default: `INFO`) |

## Code Conventions

- **All I/O is async** — asyncio, aiogram, httpx async, qdrant-client async
- **Pydantic models for ALL inter-module data** — no raw dicts passed between modules
- **loguru for all logging** — never use `print()`
- **tenacity retries on every external API call** — Anthropic, Gemini, Qdrant, Zendesk
- **Type annotations on every function signature**
- **ruff** for linting and formatting (`uv run ruff check . && uv run ruff format .`)

## Message Flow (Bidirectional Telegram ↔ Zendesk)

```
incoming Telegram group message (text, photo, voice, audio, or image document)
  → GroupStore.is_allowed(group_id) — skip if group not in allowlist
  → preprocessor.py — normalize message:
       text → as-is
       photo → download largest size (up to 5 MB) → images list
       voice/audio → download → transcribe via Gemini Flash → text
       document(image/*) → download → images list
  → Store in DB (ALL messages, regardless of category)
  → GroupContext.add_message() — records has_image, has_voice, media_description
  → RAG probe (embed message text + Qdrant top-3) — fast & cheap, no Claude API call
       if best score ≥ RAG_OVERRIDE_MIN_SCORE → fast-path as SUPPORT_QUESTION (skip classifier)
       if no strong match → classifier.py (Claude Haiku Vision):
         NON_SUPPORT → ignore (no further API calls)
         CLARIFICATION_NEEDED → ask follow-up
         ESCALATION_REQUIRED / SUPPORT_QUESTION → continue pipeline
  → extractor.py   →  extracted information + language
  → retriever.py   →  top-k chunks from datatruck_docs + datatruck_memory
  → reranker.py    →  filter below SUPPORT_MIN_CONFIDENCE_SCORE
  → generator.py   →  grounded answer OR escalation decision
  → ZendeskSyncService.sync_message():
       ThreadRouter (Claude Haiku) analyzes message + active tickets + conversation history
       → route_to_existing: post comment to existing Zendesk ticket
       → create_new: create new Zendesk ticket + post comment
       → skip_zendesk: skip (non-support, no active ticket)
       Upload photos/attachments to Zendesk if any
  → if AI replies:
       Send reply to Telegram
       Post AI reply as Zendesk comment on the same ticket
  → if escalated:
       Post escalation comment to Zendesk ticket
       Send notification to Telegram group

Zendesk agent responds (webhook):
  → POST /api/zendesk/webhook receives comment JSON
  → Look up ConversationThread by zendesk_ticket_id → find group_id
  → Store agent message in DB (source="zendesk")
  → Send message to Telegram group
  → If ticket solved/closed:
       Close conversation thread
       TicketSummarizer: summarize conversation → generalized Q&A (de-identified)
       Store in datatruck_memory for future RAG
```

## AI-Powered Thread Router

The `ThreadRouter` (Claude Haiku, `src/agent/thread_router.py`) analyzes each message to determine
which Zendesk ticket it belongs to. Input: message text, category, reply context, active tickets,
recent group history. Output: `route_to_existing` / `create_new` / `skip_zendesk`.

Key routing rules:
- User B's message goes to User A's ticket if it's about the same problem (avoids duplicate tickets)
- A Telegram reply doesn't automatically route to the replied-to message's ticket — the AI analyzes
  whether the reply is about the same topic or a new question
- NON_SUPPORT messages are routed to an active ticket if contextually related (e.g. "thanks", "+1")

## Claude API Usage

- All Claude calls use the **tool-use pattern** with a single `produce_output` tool whose
  JSON schema matches the output Pydantic model — ensures strict structured output
- **Model routing**: classifier + extractor + thread router + ticket summarizer use `ANTHROPIC_FAST_MODEL` (Haiku, ~10x cheaper);
  generator uses `ANTHROPIC_MODEL` (Sonnet) for quality answers
- **Multimodal (Vision)**: when a user attaches a photo, all three pipeline stages
  (classifier, extractor, generator) receive the image as a base64 `image` content block
  alongside the text prompt — Claude Vision analyzes screenshots, error messages, and UI states
- Classifier/extractor/thread router: `temperature=0.0`
- Generator: `temperature=0.2`, `max_tokens=4096`
- Generator returns documentation content verbatim — prompts instruct no rephrasing/summarizing
- Knowledge sources (titles + URLs) are built from retrieved chunks, not from Claude output

## Admin Dashboard

Streamlit-based admin UI at port 8501 with four pages:

- **Home** — live metrics (active groups, ingested articles, memory entries, open tickets) + navigation cards
- **Groups** — manage Telegram group allowlist (add/remove, search, runtime changes take effect within 5s)
- **Knowledge Base** — tabbed browser for `datatruck_docs` / `datatruck_memory`; Delta Sync (24h) and Full Re-ingest buttons; auto-creates collections if missing; paginated point table; delete by UUID
- **Upload** — ingest PDF/DOCX/TXT/MD files into `datatruck_docs` (parse → chunk → embed → index pipeline)
- **Tickets** — conversation threads view with Zendesk ticket links, status metrics, search, and detail view

Group allowlist is shared between bot and dashboard via `data/allowed_groups.json`.
When the allowlist is empty, the bot accepts all groups (backward-compatible).
File upload uses deterministic article IDs (offset from 10,000,000) to avoid collision with Zendesk IDs.
Full Re-ingest from the dashboard is equivalent to running `scripts/ingest_zendesk.py`.

## PostgreSQL Persistence (required)

The bot requires `DATABASE_URL` for:
- **Conversation messages** — ALL messages stored (both Telegram and Zendesk directions)
- **Conversation threads** — maps Telegram groups to Zendesk tickets
- **Escalation tickets** — ticket metadata and status

Tables are auto-created on startup (`Base.metadata.create_all`). No migrations needed for initial setup.

## FastAPI API

The bot runs a FastAPI server on port **8000** alongside the Telegram bot with:
- `GET /health` — liveness probe (always 200)
- `GET /health/ready` — readiness probe (checks Qdrant + PostgreSQL + Zendesk connectivity)
- `GET /metrics` — operational metrics (doc/memory points, open tickets, active threads)
- `POST /api/zendesk/webhook` — receives Zendesk agent comments for delivery to Telegram

## Qdrant Collections

| Collection | Purpose | Vector size | Distance |
|---|---|---|---|
| `datatruck_docs` | Zendesk article chunks (text + optional image) | 3072 | Cosine |
| `datatruck_memory` | Approved resolved Q&A pairs (from closed tickets) | 3072 | Cosine |

Point IDs use deterministic UUID5 from `(article_id, chunk_index)` — re-ingestion is idempotent.

## Telegram Formatting

- Bot uses `ParseMode.MARKDOWN_V2` (set globally in `bot.py`)
- `formatter.py` converts standard Markdown (from Claude output) → Telegram MarkdownV2:
  - `## Heading` → `*Heading*` (bold), `**bold**` → `*bold*`, `*italic*` → `_italic_`
  - Code blocks, inline code, links, strikethrough preserved
  - All MarkdownV2 special characters escaped
- `screenshot(url)` references from documentation are stripped (image sending planned for future)
- User-attached photos are analyzed by Claude Vision but not echoed back in replies
- Reply includes `For more information: <article_url>` when source is documentation
- Error handling: formatting errors fall back to raw text; Telegram parse errors retry as plain text

## Testing

```bash
uv run pytest                          # all tests
uv run pytest tests/unit/              # unit tests only
uv run pytest tests/integration/       # integration tests (requires local Qdrant)
```

- Mock all external HTTP with `respx`
- Mock Claude responses in unit tests via `pytest-mock`
- Integration tests require local Qdrant running (`make qdrant-only`)

## Commit Style

Conventional commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`
