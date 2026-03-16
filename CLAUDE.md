# CLAUDE.md — AI Support Bot for DataTruck

## Project Purpose

AI-powered Telegram support bot: monitors multiple Telegram groups, classifies messages,
answers support questions via multimodal RAG (Zendesk docs + Gemini Embedding 2 + Qdrant),
and escalates unanswerable questions to human support via an external ticket API.

## Tech Stack

- **Python 3.12+** with `uv` package manager
- **aiogram 3.x** — async Telegram bot framework
- **Anthropic claude-sonnet-4-6** — classification, extraction, answer generation
- **Google Gemini Embedding 2** (`gemini-embedding-2-preview`) — multimodal embeddings (text + images)
- **Qdrant** — vector store (`datatruck_docs` + `datatruck_memory` collections, 3072-dim cosine)
- **httpx** — async HTTP client (Zendesk API, ticket API)
- **pydantic-settings** — typed config from `.env`
- **loguru** — structured logging
- **tenacity** — retries on all external calls
- **Docker Compose** — full stack (Qdrant + bot) or Qdrant-only for local dev

## Project Layout

```
src/
  config/         — settings.py (all env vars as pydantic BaseSettings, get_settings())
  telegram/       — bot.py, handlers/, formatter.py, context/ (per-group sliding window + asyncio Lock)
  agent/          — agent.py (orchestrator), classifier, extractor, generator, prompts/, schemas.py
  rag/            — retriever.py, reranker.py, query_builder.py
  ingestion/      — zendesk_client.py, article_processor.py, image_downloader.py, chunker.py, sync_manager.py, file_parser.py
  vector_db/      — qdrant_client.py, collections.py, indexer.py
  embeddings/     — gemini_embedder.py
  escalation/     — ticket_client.py, ticket_store.py, poller.py, ticket_schemas.py
  memory/         — approved_memory.py, memory_schemas.py
  admin/          — group_store.py, file_ingest.py, schemas.py, dashboard/ (Streamlit admin UI)
  utils/          — logging.py, language.py, retry.py
scripts/          — ingest_zendesk.py, sync_zendesk.py, check_qdrant.py
tests/            — unit/ + integration/
```

## Compose Files

| File | Purpose |
|---|---|
| `docker-compose.yml` | Full stack — Qdrant + ingestion job + bot + admin dashboard |
| `docker-compose.qdrant.yml` | Qdrant only — for local development (bot runs on host) |

## Running Locally (host machine, Qdrant in Docker)

```bash
cp .env.example .env        # fill in all API keys
make qdrant-only            # starts Qdrant on localhost:6333
uv sync                     # install dependencies
uv run python scripts/ingest_zendesk.py   # initial doc ingestion
uv run python -m src.telegram.bot         # start bot (long-polling)
```

## Running Fully in Docker

`docker-compose.yml` runs **everything** (Qdrant + ingestion + bot) inside Docker.

### Step 1 — Prepare your `.env`

```bash
cp .env.example .env
# Edit .env and fill in all API keys
```

> `QDRANT_URL` in `.env` can stay `http://localhost:6333` — the compose file overrides it
> to `http://qdrant:6333` (internal Docker network) automatically.

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
| `make up` | Start Qdrant + bot (detached) |
| `make down` | Stop all services |
| `make down-v` | Stop all services and wipe volumes |
| `make ingest` | One-shot Zendesk ingestion |
| `make sync` | One-shot Zendesk sync |
| `make restart` | Restart bot container |
| `make logs` | Follow bot logs |
| `make qdrant-only` | Start Qdrant only (local dev) |
| `make dashboard` | Start admin dashboard (Docker) |
| `make dashboard-local` | Start admin dashboard locally |
| `make dashboard-logs` | Follow dashboard logs |
| `make lint` | Run ruff check + format |
| `make test` | Run all tests |
| `make test-unit` | Unit tests only |
| `make test-int` | Integration tests (requires Qdrant) |

Open Qdrant dashboard: `http://localhost:6333/dashboard`
Open Admin dashboard: `http://localhost:8501`

## Environment Variables (see .env.example for full list)

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `GOOGLE_API_KEY` | Google API key for Gemini embeddings |
| `QDRANT_URL` | Qdrant URL (default: `http://localhost:6333`) |
| `ZENDESK_SUBDOMAIN` | Zendesk subdomain (default: `support.datatruck.io`) |
| `SUPPORT_API_BASE_URL` | External ticket API base URL |
| `SUPPORT_API_KEY` | External ticket API key |
| `GEMINI_EMBEDDING_MODEL` | Gemini embedding model (default: `models/gemini-embedding-2-preview`) |
| `GEMINI_EMBEDDING_DIMENSIONS` | Embedding output dimensions (default: `3072`) |
| `SUPPORT_MIN_CONFIDENCE_SCORE` | Min Qdrant score to accept chunk (default: `0.75`) |
| `GROUP_CONTEXT_WINDOW` | Recent messages to keep per group (default: `20`) |
| `TICKET_POLL_INTERVAL_SECONDS` | Ticket polling interval (default: `60`) |
| `ADMIN_PASSWORD` | Admin dashboard password (default: empty = no auth) |
| `ALLOWED_GROUPS_FILE` | Path to group allowlist JSON (default: `data/allowed_groups.json`) |
| `LOG_LEVEL` | Log level (default: `INFO`) |

## Code Conventions

- **All I/O is async** — asyncio, aiogram, httpx async, qdrant-client async
- **Pydantic models for ALL inter-module data** — no raw dicts passed between modules
- **loguru for all logging** — never use `print()`
- **tenacity retries on every external API call** — Anthropic, Gemini, Qdrant, Zendesk, ticket API
- **Type annotations on every function signature**
- **ruff** for linting and formatting (`uv run ruff check . && uv run ruff format .`)

## Agent Decision Flow

```
incoming Telegram group message
  → GroupStore.is_allowed(group_id) — skip if group not in allowlist
  → GroupContext.add_message()
  → classifier.py  →  NON_SUPPORT | SUPPORT_QUESTION | CLARIFICATION_NEEDED | ESCALATION_REQUIRED
  → extractor.py   →  clean standalone question + language
  → retriever.py   →  top-k chunks from datatruck_docs + datatruck_memory
  → reranker.py    →  filter below SUPPORT_MIN_CONFIDENCE_SCORE
  → generator.py   →  grounded answer OR escalation decision
  → if escalated: ticket_client.create_ticket() + notify user
  → if resolved:  format_reply() → MarkdownV2 conversion + bot.send_message(reply_to=original_message_id)
     - answer returned verbatim from documentation (not rephrased)
     - screenshot references stripped (image support planned)
     - "For more information: <article_url>" appended from chunk metadata
     - MarkdownV2 formatting with plain-text fallback on parse errors

human support answers escalated ticket
  → TicketPoller detects answered ticket
  → delivers answer to Telegram group (reply to original message)
  → stores approved Q&A in datatruck_memory via ApprovedMemory
  → closes ticket in TicketStore
```

## Claude API Usage

- All Claude calls use the **tool-use pattern** with a single `produce_output` tool whose
  JSON schema matches the output Pydantic model — ensures strict structured output
- Classifier/extractor: `temperature=0.0`
- Generator: `temperature=0.2`, `max_tokens=4096`
- Generator returns documentation content verbatim — prompts instruct no rephrasing/summarizing
- Knowledge sources (titles + URLs) are built from retrieved chunks, not from Claude output
- Model: `claude-sonnet-4-6` (configurable via `ANTHROPIC_MODEL`)

## Admin Dashboard

Streamlit-based admin UI at port 8501 with four pages:

- **Groups** — manage Telegram group allowlist (add/remove, runtime changes take effect within 5s)
- **Knowledge Base** — browse Qdrant collections, view points, trigger Zendesk sync
- **Upload** — ingest PDF/DOCX/TXT files into `datatruck_docs` (reuses chunker + embedder + indexer pipeline)
- **Tickets** — read-only view of escalated tickets from `data/tickets.json`

Group allowlist is shared between bot and dashboard via `data/allowed_groups.json`.
When the allowlist is empty, the bot accepts all groups (backward-compatible).
File upload uses deterministic article IDs (offset from 10,000,000) to avoid collision with Zendesk IDs.

## Qdrant Collections

| Collection | Purpose | Vector size | Distance |
|---|---|---|---|
| `datatruck_docs` | Zendesk article chunks (text + optional image) | 3072 | Cosine |
| `datatruck_memory` | Approved resolved Q&A pairs | 3072 | Cosine |

Point IDs use deterministic UUID5 from `(article_id, chunk_index)` — re-ingestion is idempotent.

## Telegram Formatting

- Bot uses `ParseMode.MARKDOWN_V2` (set globally in `bot.py`)
- `formatter.py` converts standard Markdown (from Claude output) → Telegram MarkdownV2:
  - `## Heading` → `*Heading*` (bold), `**bold**` → `*bold*`, `*italic*` → `_italic_`
  - Code blocks, inline code, links, strikethrough preserved
  - All MarkdownV2 special characters escaped
- `screenshot(url)` references are stripped (image sending planned for future)
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
