# CLAUDE.md — DataTruck AI Support Agent (LangGraph Redesign)

## READ THIS FIRST

This project is being **redesigned from a linear pipeline to a LangGraph state machine**.
The old orchestration layer (agent.py, classifier, extractor, thread_router, sync_service)
is being REPLACED. The infrastructure (Zendesk client, Qdrant, embeddings, database, aiogram,
formatter, preprocessor, ingestion) is being KEPT.

**Do NOT modify files listed in "KEEP AS-IS" unless explicitly told to.**
**Do NOT use the old agent.py, classifier.py, extractor.py, thread_router.py, or sync_service.py as reference for how decisions should be made. They have structural bugs that this redesign fixes.**

The fundamental change: the old system made 3-4 separate LLM calls per message (classifier, extractor, thread_router, generator) with different context, and they could contradict each other. The new system makes ONE decision call (`think` node) that sees everything — message, images, conversation history, active tickets, bot's last response, and learned decision examples — then routes accordingly.

---

## Project Purpose

AI-powered Telegram support bot that:
1. Monitors multiple Telegram groups (each = different client company)
2. Understands messages in context (conversation history, active tickets, pending follow-ups)
3. Answers support questions from documentation and learned knowledge
4. Syncs ALL messages bidirectionally with Zendesk (Telegram → Zendesk tickets, Zendesk agent responses → Telegram)
5. Escalates silently when it can't help (no Telegram reply, human agent handles in Zendesk)
6. **Gets smarter over time** — every resolved ticket teaches the system new answers, patterns, and decision examples

## Tech Stack

**Existing (keep):**
- Python 3.12+ with `uv` package manager
- aiogram 3.x — async Telegram bot framework
- Anthropic Claude — Haiku for decisions (fast + cheap), Sonnet for answer generation (quality)
- Google Gemini Embedding 2 (`gemini-embedding-2-preview`) — multimodal embeddings (3072 dimensions)
- Gemini Flash — voice message transcription
- Qdrant — vector store (`datatruck_docs` + `datatruck_memory` collections, 3072-dim cosine)
- PostgreSQL 16 — persistent storage
- SQLAlchemy 2.0 (async) — ORM with asyncpg driver
- FastAPI + Uvicorn — health check / metrics / Zendesk webhook API on port 8000
- httpx — async HTTP client (Zendesk API)
- pydantic-settings — typed config from `.env`
- loguru — structured logging
- tenacity — retries on all external calls
- Docker Compose — full stack

**New (add):**
- `langgraph>=1.0` — agent orchestration framework (state machine with checkpointing)
- `langgraph-checkpoint-postgres>=3.0` — per-group state persistence to PostgreSQL
- `langchain-core>=1.0` — base abstractions (messages, tools)
- `langchain-anthropic>=0.3` — ChatAnthropic for LangGraph nodes
- `psycopg[binary,pool]>=3.2` — required by langgraph-checkpoint-postgres

---

## FILE DISPOSITION: KEEP vs REPLACE vs NEW

### KEEP AS-IS (do not modify unless explicitly told)

```
src/config/settings.py                    — update: add database_url_psycopg, conversation_history_limit, remove group_context_window
src/database/engine.py                    — keep, may need psycopg pool for LangGraph checkpointer
src/database/models.py                    — REWRITE: clean 5-table schema (see INFRASTRUCTURE section)
src/database/repositories.py              — REWRITE: new queries for perceive/remember nodes (see INFRASTRUCTURE section)
src/embeddings/gemini_embedder.py         — keep
src/escalation/ticket_client.py           — FIX: use shared httpx client (keep "test-tg-chat:" prefix — intentional during development)
src/escalation/ticket_schemas.py          — CLEAN UP: remove TicketRecord/TicketResponse, keep Zendesk API schemas
src/escalation/ticket_store.py            — keep (ConversationThreadStore)
src/escalation/profile_service.py         — keep (ZendeskProfileService)
src/escalation/webhook_handler.py         — keep, enhance with learning trigger (see PHASE 3)
src/ingestion/*                           — keep entire module
src/memory/approved_memory.py             — FIX: use proper payload fields instead of fake article metadata
src/memory/memory_schemas.py              — keep
src/rag/retriever.py                      — keep (update RetrievedChunk to handle missing article fields)
src/rag/reranker.py                       — keep
src/rag/query_builder.py                  — keep
src/vector_db/*                           — keep entire module
src/telegram/bot.py                       — keep structure, REWRITE wiring for LangGraph (see PHASE 1)
src/telegram/formatter.py                 — keep
src/telegram/preprocessor.py              — FIX: cache Gemini client instead of creating per call
src/admin/*                               — REWRITE: 6 pages for new architecture (see ADMIN DASHBOARD section)
src/api/app.py                            — keep
src/utils/retry.py                        — FIX: use loguru lazy formatting
src/utils/logging.py                      — keep
src/utils/language.py                     — keep
scripts/*                                 — keep
docker-compose*.yml                       — keep, update image deps
Makefile                                  — FIX: remove "Redis" from infra description
Dockerfile                                — FIX: add .dockerignore, run as non-root user
```

### DELETE (after migration is complete)

```
src/agent/agent.py                        — replaced by src/agent/graph.py
src/agent/classifier.py                   — merged into src/agent/nodes/think.py
src/agent/extractor.py                    — merged into src/agent/nodes/think.py
src/agent/thread_router.py                — merged into src/agent/nodes/think.py
src/agent/generator.py                    — replaced by src/agent/nodes/generate.py
src/agent/ticket_summarizer.py            — moved to src/agent/nodes/learn.py
src/agent/prompts/classifier_prompt.py    — replaced by src/agent/prompts/think_prompt.py
src/agent/prompts/extractor_prompt.py     — merged into think_prompt.py
src/agent/prompts/thread_router_prompt.py — merged into think_prompt.py
src/agent/prompts/generator_prompt.py     — replaced by src/agent/prompts/generate_prompt.py
src/agent/prompts/system_prompt.py        — replaced by src/agent/prompts/system_prompt.py (rewritten)
src/escalation/sync_service.py            — replaced by src/agent/nodes/remember.py
src/telegram/context/context_manager.py   — replaced by LangGraph checkpointer
src/telegram/context/group_context.py     — replaced by LangGraph checkpointer
src/telegram/handlers/message_handler.py  — replaced by src/telegram/handlers/message_handler.py (rewritten, much simpler)
```

Also remove from existing files (fresh DB start):
```
src/database/models.py                    — remove TicketRow class (table dropped)
src/database/repositories.py              — remove all TicketRow queries (save_ticket, get_open_tickets, close_ticket, etc.)
src/escalation/ticket_schemas.py          — remove TicketRecord and TicketStatus (keep ZendeskTicketCreate, ZendeskComment, ZendeskTicketClosedError)
```

### CREATE NEW

```
src/agent/state.py                        — SupportState TypedDict
src/agent/graph.py                        — build_graph() → compiled StateGraph
src/agent/edges.py                        — conditional routing functions
src/agent/nodes/perceive.py               — assemble context from all 4 memory types
src/agent/nodes/think.py                  — ONE Haiku call: classify + route + extract
src/agent/nodes/retrieve.py               — RAG from docs + learned answers
src/agent/nodes/generate.py               — Sonnet: answer from retrieved docs
src/agent/nodes/respond.py                — send Telegram reply
src/agent/nodes/remember.py               — update working memory + sync to Zendesk
src/agent/nodes/learn.py                  — extract knowledge from resolved tickets
src/agent/prompts/think_prompt.py         — unified decision prompt
src/agent/prompts/generate_prompt.py      — answer generation prompt
src/agent/prompts/system_prompt.py        — rewritten system prompt
src/learning/                             — self-improvement module (PHASE 4+)
scripts/bootstrap_from_history.py         — process historical conversations
```

---

## INFRASTRUCTURE: Fresh Start Database Schema

Since we're starting with a **fresh database**, we can design the schema cleanly.
Drop the old `tickets` table entirely (redundant with `conversation_threads`).
Rename `telegram_messages` → `messages` (it stores messages from all sources).

### Database Tables (6 tables — clean and minimal)

```python
# src/database/models.py — REWRITE for fresh start

from __future__ import annotations
from datetime import UTC, datetime
from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TelegramUser(Base):
    """One row per Telegram person."""
    __tablename__ = "telegram_users"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ZendeskUser(Base):
    """Zendesk identity linked to a Telegram user via Profiles API."""
    __tablename__ = "zendesk_users"

    zendesk_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    external_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    zendesk_profile_id: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TelegramGroup(Base):
    """One row per Telegram group (each group = one client company)."""
    __tablename__ = "telegram_groups"

    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str | None] = mapped_column(String(255))
    zendesk_organization_id: Mapped[int | None] = mapped_column(BigInteger)
    zendesk_group_id: Mapped[int | None] = mapped_column(BigInteger)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Message(Base):
    """Every message from any source: Telegram users, bot, Zendesk agents."""
    __tablename__ = "messages"
    __table_args__ = (
        # Prevent duplicate saves
        Index("uq_chat_message", "chat_id", "message_id", unique=True),
        # perceive: load recent conversation history
        Index("idx_msg_chat_created", "chat_id", "created_at"),
        # perceive: find bot's last response in this group
        Index("idx_msg_chat_source_created", "chat_id", "source", "created_at"),
        # remember: find message by Telegram reply-to
        Index("idx_msg_chat_msgid", "chat_id", "message_id"),
        # webhook: find all messages for a ticket
        Index("idx_msg_ticket", "zendesk_ticket_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="telegram")
    # source values: "telegram" (user), "bot" (our bot), "zendesk" (human agent)
    reply_to_message_id: Mapped[int | None] = mapped_column(BigInteger)
    file_id: Mapped[str | None] = mapped_column(String(255))
    # Telegram file_id — permanent reference to download the file via bot.download()
    file_type: Mapped[str | None] = mapped_column(String(20))
    # "photo", "voice", "document", or None for text-only messages
    file_description: Mapped[str | None] = mapped_column(Text)
    # AI-generated description of file content — photos, voice, documents
    # (set by remember after think analyzes with Vision)
    zendesk_ticket_id: Mapped[int | None] = mapped_column(BigInteger)
    zendesk_comment_id: Mapped[int | None] = mapped_column(BigInteger)
    link_type: Mapped[str | None] = mapped_column(String(20))
    # link_type values: "root" (first msg that created ticket), "reply" (subsequent), "mirror" (from Zendesk)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConversationThread(Base):
    """Maps a Telegram user's conversation in a group to a Zendesk ticket.

    One user in one group can have at most one OPEN thread at a time.
    When a ticket is solved/closed, the thread is closed and a new one
    can be created for the next conversation.
    """
    __tablename__ = "conversation_threads"
    __table_args__ = (
        # perceive: "does this user have an active ticket in this group?"
        Index("idx_thread_group_user_status", "group_id", "user_id", "status"),
        # perceive: "all active tickets in this group"
        Index("idx_thread_group_status", "group_id", "status"),
        # webhook: find thread by Zendesk ticket ID
        Index("idx_thread_ticket", "zendesk_ticket_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    zendesk_ticket_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    # status values: "open", "pending", "solved", "closed"
    urgency: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    # urgency values: "normal", "high", "critical"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(tz=UTC))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(tz=UTC))
```

### What Changed From Old Schema

| Change | Why |
|---|---|
| **Dropped `tickets` table** | Redundant with `conversation_threads`. Q&A pairs now stored in Qdrant memory via learn node, not SQL. |
| **Renamed `telegram_messages` → `messages`** | Table stores messages from ALL sources (telegram, bot, zendesk), not just Telegram. |
| **`TelegramUser` primary key = `telegram_user_id`** | Removed unnecessary surrogate `id` column. Telegram user ID is already unique and stable. |
| **`ZendeskUser` primary key = `zendesk_user_id`** | Same — removed surrogate `id`. |
| **`TelegramGroup` primary key = `telegram_chat_id`** | Same — removed surrogate `id`. |
| **Added composite indexes** | perceive node needs fast `(group_id, user_id, status)` and `(chat_id, source, created_at)` lookups. |
| **Added `urgency` to `ConversationThread`** | think node sets urgency (normal/high/critical) and it needs to persist on the ticket. |
| **Added UNIQUE index on `(chat_id, message_id)`** | Prevents duplicate message saves. |
| **Documented `source` and `link_type` values** | Inline comments so developers know valid values. |

### Repositories (`src/database/repositories.py`) — REWRITE

Since tables changed, rewrite repositories. Key queries needed by the new design:

```python
# ── For perceive node (all ISOLATED by group_id) ──

async def get_recent_messages(chat_id: int, limit: int = 30) -> list[dict]:
    """Recent messages in this group, oldest first.
    Returns: {message_id, user_id, username, text, source, file_id, file_type,
              file_description, created_at}
    file_description is included so conversation_history has meaningful
    context for photos/documents. Voice messages have text (transcription)
    so file_description is null for them."""

async def get_active_threads_in_group(group_id: int) -> list[ConversationThread]:
    """All open/pending threads in this group."""

async def get_active_thread(group_id: int, user_id: int) -> ConversationThread | None:
    """This user's open thread in this group (if any)."""

async def get_bot_last_response(chat_id: int) -> dict | None:
    """Most recent bot message in this group. Returns {text, created_at, user_id_responded_to}."""

async def get_recently_solved_threads(group_id: int, days: int = 7) -> list[dict]:
    """Recently solved/closed threads in this group (for follow-up detection)."""

async def get_message_by_telegram_id(chat_id: int, message_id: int) -> Message | None:
    """Look up a message for reply-to ticket resolution."""

# ── For remember node ──

async def save_message(..., file_id=None, file_type=None) -> None:
    """Insert message. ON CONFLICT (chat_id, message_id) DO NOTHING."""

async def update_message_file_description(chat_id, message_id, file_description) -> None:
    """Set file_description on a message row (called by remember after think analyzes)."""

async def update_message_zendesk_ids(chat_id, message_id, ticket_id, comment_id, link_type) -> None:
    """Set Zendesk IDs on a message row after sync."""

async def create_thread(group_id, user_id, zendesk_ticket_id, subject, urgency) -> ConversationThread:
    """Create a new conversation thread."""

async def touch_thread(thread_id: int) -> None:
    """Update last_message_at to now."""

# ── For webhook handler ──

async def get_thread_by_zendesk_ticket_id(ticket_id: int) -> ConversationThread | None:
async def close_thread(thread_id: int) -> None:
async def update_thread_status(zendesk_ticket_id: int, status: str) -> None:
async def get_root_message_id(zendesk_ticket_id: int, chat_id: int) -> int | None:
async def get_messages_by_ticket_id(zendesk_ticket_id: int) -> list[dict]:

# ── For admin dashboard ──

async def get_or_create_telegram_user(telegram_user_id, display_name) -> TelegramUser:
async def get_or_create_telegram_group(telegram_chat_id, title) -> TelegramGroup:
async def get_all_telegram_groups() -> list[TelegramGroup]:
async def set_group_active(telegram_chat_id, active) -> None:
```

Drop all old `TicketRow`-related queries (`save_ticket`, `get_open_tickets`, `close_ticket`, etc.)
and the `TicketRecord` / `TicketStatus` imports from `ticket_schemas.py`.

### Settings (`src/config/settings.py`) — Updates

```python
class Settings(BaseSettings):
    # ... existing fields ...

    # REPLACE group_context_window with:
    conversation_history_limit: int = Field(default=30, ge=1, le=100,
        description="Number of recent messages loaded by perceive node per group")

    # REMOVE: group_context_window (no longer used — no in-memory deque)

    # KEEP: support_min_confidence_score (used by reranker in retrieve node)
    # KEEP: rag_top_k (used by retrieve node)
    # REMOVE: rag_override_min_score (was for old RAG probe in classifier — no longer used)

    @property
    def database_url_psycopg(self) -> str:
        """Convert asyncpg DATABASE_URL to psycopg format for LangGraph checkpointer."""
        url = self.database_url
        if url.startswith("postgresql+asyncpg://"):
            return url.replace("postgresql+asyncpg://", "postgresql://", 1)
        return url
```

### TicketStore (`src/escalation/ticket_store.py`) — Minor Update

The `ConversationThreadStore` class is fine, but its `get_or_create_thread` method
uses `get_active_thread` which returns the existing thread only for the same user.
This is correct behavior — keep it. Just make sure all repository calls it uses
reference the renamed `Message` model (not `MessageRow`).

### Ticket Schemas (`src/escalation/ticket_schemas.py`) — Cleanup

Remove `TicketRecord` and `TicketStatus` classes — they were for the dropped `tickets` table.
Keep `ZendeskTicketCreate`, `ZendeskComment`, `ZendeskTicketClosedError` — these are for the
Zendesk API client and are still needed.

### Things That Are Fine (NO CHANGES needed)

- **Chunker** (`src/ingestion/chunker.py`) — chunk_size=1000, overlap=200 are good defaults
- **Qdrant collections** (`src/vector_db/collections.py`) — `datatruck_docs` + `datatruck_memory`, 3072-dim cosine
- **Qdrant wrapper** (`src/vector_db/qdrant_client.py`) — clean async wrapper with retries
- **RAG retriever** (`src/rag/retriever.py`) — sibling expansion is smart, keep it
- **Reranker** (`src/rag/reranker.py`) — simple score threshold, fine
- **Query builder** (`src/rag/query_builder.py`) — just strips whitespace, fine for Gemini
- **Gemini embedder** (`src/embeddings/gemini_embedder.py`) — clean, proper task types
- **Formatter** (`src/telegram/formatter.py`) — keep
- **Ingestion pipeline** (`src/ingestion/*`) — keep entire module
- **Profile service** (`src/escalation/profile_service.py`) — clean, keep
- **FastAPI app** (`src/api/app.py`) — keep
- **Admin dashboard** (`src/admin/*`) — keep (update ticket page to use conversation_threads)

### Bugs and Improvements to Fix (Fresh Start)

**1. INEFFICIENCY: New HTTP client per request** (`src/escalation/ticket_client.py`)

`_client()` creates a new `httpx.AsyncClient` on every API call — new TCP connection every time.

```python
# FIX: use a shared client with lifecycle management
class ZendeskTicketClient:
    def __init__(self, ...):
        self._http = httpx.AsyncClient(
            base_url=self._base_url, auth=self._auth,
            timeout=30.0, headers={"Content-Type": "application/json"},
        )

    async def close(self) -> None:
        await self._http.aclose()
```

Call `await zendesk_client.close()` on bot shutdown.

**2. INEFFICIENCY: New Gemini client per voice transcription** (`src/telegram/preprocessor.py` line 254)

Every voice message creates a new `genai.Client`. Cache it at module level or inject as dependency.

**3. CODE SMELL: Fake article metadata in approved memory** (`src/memory/approved_memory.py`)

Memory entries pretend to be articles (`article_title: "Approved Answer"`, `article_url: ""`) so the
retriever doesn't break. Fix: make `article_title`/`article_url` truly optional in `RetrievedChunk`
and use `source_type: "learned"` vs `"documentation"` in payloads.

**4. INCONSISTENCY: f-string in loguru** (`src/utils/retry.py` line 36)

```python
# FIX: use loguru's lazy formatting
logger.warning("Retrying {} (attempt {}/{}): {}", func.__name__, attempt_number, max_attempts, e)
```

**5. CLEANUP: ticket_schemas.py** — Remove `TicketRecord` and `TicketResponse` (dead code from dropped
`tickets` table). Keep `TicketStatus`, `ZendeskTicketClosedError`, `ZendeskTicketCreate`, `ZendeskComment`.

**6. CLEANUP: Makefile** — `infra` target description says "Redis" but there's no Redis. Fix description.

**7. MISSING: .dockerignore** — Create it (excludes .git, .venv, .env, tests, docs, __pycache__, .telegram_chat_history).

**8. IMPROVEMENT: Dockerfile** — Run as non-root user (add `useradd appuser` + `USER appuser`).

**9. SETTINGS CLEANUP** — Remove `group_context_window` (replaced by `conversation_history_limit`).
Remove `rag_override_min_score` (was for old RAG probe shortcut — no longer used).

---

## ARCHITECTURE: LangGraph STATE MACHINE

### State Schema (`src/agent/state.py`)

```python
from typing import TypedDict, Literal

class SupportState(TypedDict):
    # ── Input (set by handler before graph invocation) ──
    raw_text: str                        # preprocessed message text
    images: list[bytes]                  # photo/document bytes
    sender_id: str                       # Telegram user ID (as string)
    sender_name: str                     # display name
    group_id: str                        # Telegram chat ID (= LangGraph thread_id)
    group_name: str                      # Telegram group title
    telegram_message_id: int             # for reply_to
    reply_to_message_id: int | None      # if user replied to a specific message

    # ── Context (set by perceive node) ──
    conversation_history: list[dict]     # last 30 messages in this group
    active_tickets: list[dict]           # all open tickets in this group
    user_active_ticket: dict | None      # this user's current open ticket in THIS group
    recently_solved_tickets: list[dict]  # solved/closed tickets in last 7 days (for follow_up)
    bot_last_response: str | None        # what bot last said to THIS USER in this group
    reply_to_ticket_id: int | None       # Zendesk ticket of the replied-to message
    reply_to_text: str | None            # text of the replied-to message
    relevant_episodes: list[dict]        # past conversation trajectories (episodic memory)
    decision_examples: list[dict]        # few-shot examples from procedural memory

    # ── Decision (set by think node) ──
    action: Literal["answer", "ignore", "wait", "escalate"]
    urgency: Literal["normal", "high", "critical"]
    ticket_action: Literal["route_existing", "create_new", "skip", "follow_up"]
    target_ticket_id: int | None         # existing ticket to route to
    follow_up_source_id: int | None      # solved ticket to create follow-up from
    extracted_question: str | None        # clean standalone question (enriched with image descriptions)
    language: str                         # en / ru / uz
    decision_reasoning: str               # LLM's reasoning (for debugging/logging)
    file_description: str | None         # AI description of current message's image(s) (set by think)

    # ── Retrieval (set by retrieve node) ──
    retrieved_docs: list[dict]           # RAG results with scores
    retrieval_confidence: float          # best chunk score
    recent_image_bytes: list[bytes]      # images downloaded from recent file_ids (for generate)

    # ── Generation (set by generate node) ──
    answer_text: str | None              # bot's response
    follow_up_question: str | None       # if bot needs more info
    needs_escalation: bool               # generator couldn't produce grounded answer
    escalation_reason: str
    knowledge_sources: list[dict]        # article titles + URLs for "For more info"

    # ── Sync tracking (set by respond/remember nodes) ──
    bot_response_text: str | None        # final composed text sent to Telegram (set by respond)
    bot_response_message_id: int | None  # Telegram message_id of bot's reply (set by respond)
    synced_ticket_id: int | None
    synced_comment_id: int | None
```

### Graph Definition (`src/agent/graph.py`)

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

def build_graph():
    graph = StateGraph(SupportState)

    # Add nodes
    graph.add_node("perceive", perceive_node)
    graph.add_node("think", think_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)
    graph.add_node("respond", respond_node)
    graph.add_node("remember", remember_node)

    # Entry point
    graph.set_entry_point("perceive")

    # perceive → think (always)
    graph.add_edge("perceive", "think")

    # think → conditional routing
    graph.add_conditional_edges("think", route_after_think, {
        "answer": "retrieve",
        "ignore": "remember",
        "wait": "remember",
        "escalate": "remember",
    })

    # retrieve → generate (always)
    graph.add_edge("retrieve", "generate")

    # generate → conditional: has answer or needs escalation?
    graph.add_conditional_edges("generate", route_after_generate, {
        "respond": "respond",
        "escalate": "remember",
    })

    # respond → remember (always)
    graph.add_edge("respond", "remember")

    # remember → END
    graph.add_edge("remember", END)

    return graph
```

### Conditional Edge Functions (`src/agent/edges.py`)

```python
def route_after_think(state: SupportState) -> str:
    return state["action"]  # "answer" | "ignore" | "wait" | "escalate"

def route_after_generate(state: SupportState) -> str:
    if state["needs_escalation"]:
        return "escalate"
    return "respond"
```

---

## NODE SPECIFICATIONS

### `perceive` node — assemble complete context

**No LLM call.** Pure data queries. Enforces group isolation.

```
Input: raw_text, images, sender_id, group_id, reply_to_message_id
Output: conversation_history, active_tickets, user_active_ticket,
        recently_solved_tickets, bot_last_response, reply_to_ticket_id,
        reply_to_text, relevant_episodes, decision_examples

Logic:
1. Load conversation_history from DB: get_recent_messages(group_id=group_id, limit=30)
   CRITICAL: always filter by group_id
   Each message in history includes file_description if present.
   Format for think's prompt (based on file_type):

   ```python
   for msg in messages:
       if msg.file_type == "photo" and msg.file_description:
           line = f"{msg.username}: [Photo: {msg.file_description}]"
           if msg.text:
               line += f" {msg.text}"  # caption
       elif msg.file_type == "voice":
           line = f"{msg.username}: [Voice] {msg.text}"  # transcription
       elif msg.file_type == "document" and msg.file_description:
           line = f"{msg.username}: [File: {msg.file_description}]"
           if msg.text:
               line += f" {msg.text}"  # caption
       elif msg.source == "bot":
           line = f"Bot: {msg.text}"
       else:
           line = f"{msg.username}: {msg.text}"
   ```

   Examples:
     - Text message: "Adam: How do I change load status?"
     - Photo with caption: "Adam: [Photo: Screenshot of Loads page with Error 500] How do I fix this?"
     - Photo without caption: "Adam: [Photo: Screenshot of Loads page with Error 500]"
     - Voice message: "Adam: [Voice] load statusni qanday o'zgartiraman?"
     - File with caption: "Adam: [File: PDF invoice for March deliveries] Check this"
     - File without caption: "Adam: [File: PDF invoice for March deliveries]"
     - Bot response: "Bot: To change load status, go to Settings..."

   Note: voice messages already have text (transcription from preprocessor).
   file_description is only needed for photos and documents where text="" (no caption).
   The file_description field makes non-text messages meaningful in conversation context.

2. Load active_tickets from DB: get_active_threads_in_group(group_id=group_id)
   Returns list of {ticket_id, subject, user_id, status, last_message_at}
3. Load user_active_ticket from DB: get_active_thread(group_id=group_id, user_id=sender_id)
   This user's open ticket in THIS group only
4. Load recently_solved_tickets from DB: get_recently_solved_threads(group_id=group_id, days=7)
   Needed by think for follow_up detection — "is this about a recently solved issue?"
5. Load bot_last_response: last bot message in this group that was in response to THIS USER
   (not bot responses to other users — that would confuse think)
   Query: last message where source="bot" that immediately follows a message from sender_id
6. If reply_to_message_id: look up that message in DB to get reply_to_ticket_id and reply_to_text
7. Episodic memory search: find 1-2 relevant past episodes from LangGraph Store
   (PHASE 4 — return empty list initially)
8. Procedural memory: load dynamically selected few-shot decision examples
   (PHASE 4 — use hardcoded examples initially)

NO pending_followup field — think infers this from conversation_history.
If the last bot message was a question ("Which page are you on?") and now
the user responds, think sees both messages in history and understands the
user is answering the bot's follow-up. No explicit flag needed.

NO RAG PROBE HERE. Retrieval only happens in the retrieve node AFTER think
decides action="answer". This avoids wasting embedding calls on greetings,
thanks, call requests, and other non-answerable messages (~94% of traffic).
```

### `think` node — ONE decision call

**One Claude Haiku call.** Replaces classifier + extractor + thread_router.

```
Input: everything from perceive + raw_text + images
Output: action, urgency, ticket_action, target_ticket_id,
        follow_up_source_id, extracted_question, language,
        decision_reasoning, file_description

Model: ANTHROPIC_FAST_MODEL (Haiku), temperature=0.0
Pattern: tool-use with produce_output tool

Tool schema:
{
  "action": "answer | ignore | wait | escalate",
  "urgency": "normal | high | critical",
  "ticket_action": "route_existing | create_new | skip | follow_up",
  "ticket_id": int | null,
  "follow_up_source_id": int | null,
  "extracted_question": string | null,
  "language": "en | ru | uz",
  "reasoning": string,
  "file_description": string | null
}

file_description: if the current message has photos or documents, think describes what it sees
in 1-2 sentences. Example: "Screenshot of Loads page showing HTTP 500 error with
red banner." This is stored in DB by remember node and becomes part of
conversation_history for future messages.
Set to null if: no files, or file_type="voice" (voice already has text from transcription).

extracted_question: when images have descriptions from conversation_history,
think merges them into the question. Example: user sent 3 error screenshots
then typed "All three pages show errors" → extracted_question becomes
"Multiple pages (Loads, Settings, Reports) showing Error 500 — how to fix?"

The prompt includes:
- System prompt (DataTruck support agent identity)
- Current message + base64 images (if any)
- Conversation history (last 30 messages, formatted as "username: text")
- Active tickets in this group (id, subject, user, status)
- User's active ticket (if any)
- Recently solved tickets in this group (last 7 days — for follow_up detection)
- Bot's last response to this user
- Reply-to context (text + ticket_id of replied-to message)
- Few-shot decision examples (from procedural memory or hardcoded initially)

Note: no explicit "pending_followup" field. Think infers follow-up context from
conversation_history — if the last bot message was a question and the user is now
responding, think sees both messages and understands the context.

See THINK PROMPT section below for the full prompt.
```

### `retrieve` node — RAG search + image download

```
Input: extracted_question, language, images (from current message),
       conversation_history (has file_ids for recent photos)
Output: retrieved_docs, retrieval_confidence, recent_image_bytes

Logic:
1. Use existing RAGRetriever.retrieve(question=extracted_question, language=language, top_k=5)
2. Use existing ScoreThresholdFilter.filter(chunks)
3. Set retrieval_confidence = max score of filtered chunks (or 0.0 if none)
4. Return filtered chunks as retrieved_docs
5. Collect images for generate:
   a. Start with images from current message (already in state as bytes)
   b. Scan conversation_history for recent messages from this user with file_ids
      (last 5 minutes, file_type="photo") — no extra DB query needed
   c. Download those images via bot.download(file_id)
   d. Combine into recent_image_bytes (max 5 images to control Sonnet cost)
   This ensures generate sees all relevant screenshots, not just the current message's.
```

### `generate` node — answer from docs

**One Claude Sonnet call.**

```
Input: extracted_question, retrieved_docs, language, recent_image_bytes
Output: answer_text, follow_up_question, needs_escalation,
        escalation_reason, knowledge_sources

Model: ANTHROPIC_MODEL (Sonnet), temperature=0.2, max_tokens=4096
Pattern: tool-use with produce_output tool

Logic:
- If retrieved_docs is empty or retrieval_confidence < threshold:
  → needs_escalation = true, answer_text = ""
- Otherwise: generate answer from docs in the user's language
- Pass recent_image_bytes as base64 image content blocks to Sonnet Vision
  (Sonnet sees the actual screenshots alongside the documentation — produces
  contextual answers like "I can see Error 500 on your Loads page...")
- If answer is possible but ambiguous: set follow_up_question
- Return documentation content as-is (no rephrasing/summarizing)
- Build knowledge_sources from chunk metadata (title, URL)

See GENERATE PROMPT section below.
```

### `respond` node — send Telegram reply

```
Input: answer_text, follow_up_question, knowledge_sources, telegram_message_id, group_id
Output: bot_response_text, bot_response_message_id

Logic:
1. Build response text:
   - If answer_text and follow_up_question: concatenate (answer + "\n\n" + follow_up)
   - If answer_text only: use answer_text
   - If follow_up_question only: use follow_up_question
   - If neither: this node should not run (route_after_generate sends to remember)
2. Save composed text to state → bot_response_text
   (remember node uses this for Zendesk — no recomputation, no mismatch)
3. Format using existing formatter.format_reply()
4. Send via bot.send_message(chat_id=group_id, text=formatted, reply_to_message_id=telegram_message_id)
5. Fallback to plain text on MarkdownV2 parse errors (existing pattern)
6. Save the sent message's Telegram message_id to state → bot_response_message_id
```

### `remember` node — update state + sync Zendesk

**No LLM call.** Database + Zendesk API calls.

This runs on ALL paths (answer, ignore, wait, escalate).

```
Input: everything from think + bot_response_text + bot_response_message_id
Output: synced_ticket_id, synced_comment_id

Logic:
1. ZENDESK SYNC (user's message):
   a. If ticket_action == "skip": do nothing
   b. If ticket_action == "route_existing":
      - Post user's message as comment on target_ticket_id
      - If add_comment returns 422 (ticket closed):
        → Close stale thread → set ticket_action = "create_new" → retry
      - Set urgency on ticket if high/critical
   c. If ticket_action == "create_new":
      - Resolve Zendesk user via profile_service
      - Create ticket: subject = extracted_question or raw_text[:80]
        body = raw_text, requester = Zendesk user, custom_fields = [telegram_chat_id]
      - Create conversation_thread in DB
   d. If ticket_action == "follow_up":
      - Create follow-up ticket linked to follow_up_source_id
      - Create conversation_thread in DB

2. Upload images as Zendesk attachments (if any)

3. ZENDESK SYNC (bot's response):
   If bot_response_text is not empty:
     - Post bot_response_text as comment on the same ticket
     - author_id = bot's Zendesk user ID
   (bot_response_text is set by respond node — same text user sees in Telegram.
    If respond never ran (escalation), bot_response_text is None → nothing posted.)

4. Update user's message row in DB:
   - Set zendesk_ticket_id, zendesk_comment_id, link_type
   - Set file_description from think (only if file_type is "photo" or "document" — 
     voice messages don't need it, their text field already has the transcription)
   This is critical: the file_description becomes part of conversation_history
   for future messages. Without it, photos/documents show as empty text in context.

5. SAVE BOT MESSAGE TO DB (only if bot responded in Telegram):
   If bot_response_message_id is not None:
     - save_message(
         chat_id=group_id,
         message_id=bot_response_message_id,
         user_id=bot_telegram_user_id,
         username="DataTruck Support",
         text=bot_response_text,
         source="bot",
         reply_to_message_id=telegram_message_id,
         zendesk_ticket_id=synced_ticket_id,
       )
   This ensures the next invocation's perceive sees the bot's response in conversation_history.

6. LOG DECISION (for dashboard analytics and review):
   Save one row to bot_decisions table with:
   - group_id, user_id, message_id, message_text, file_description
   - action, urgency, ticket_action, target_ticket_id, extracted_question
   - language, reasoning (from think)
   - answer_text, retrieval_confidence, needs_escalation (from generate, if ran)
   - perceive_ms, think_ms, retrieve_ms, generate_ms, total_ms (timing)
   This powers the Performance and Decision Review dashboard pages.
```

### `learn` node — triggered by Zendesk webhook, NOT part of the main graph

```
Trigger: ZendeskWebhookHandler receives ticket.status_changed → solved/closed

Logic:
1. Get all messages for this ticket from DB
2. Use TicketSummarizer (Haiku) to extract Q&A pair
3. Store Q&A in Qdrant datatruck_memory (existing ApprovedMemory)
4. PHASE 4: Store full conversation trajectory in LangGraph Store (episodic memory)
5. PHASE 4: Extract decision examples for procedural memory
```

---

## THINK PROMPT (`src/agent/prompts/think_prompt.py`)

```python
THINK_PROMPT = """\
You are a routing and classification agent for DataTruck's Telegram support system.
Analyze the incoming message with FULL context and make ONE unified decision.

## YOUR DECISIONS

1. ACTION — what happens in Telegram:
   - "answer": clear support question that the bot should try to answer from docs
   - "ignore": greeting, thanks, casual chat, off-topic, confirmation after bot answered
   - "wait": user signaled they have more to say but haven't asked the actual question yet
     (e.g. "I have more questions", "one more thing", "also...")
   - "escalate": bot cannot help — account-specific action, phone call request,
     reported that documented solution didn't work, system outage, or needs human investigation

2. URGENCY — for Zendesk prioritization:
   - "normal": standard support request
   - "high": user explicitly says urgent/asap, or repeated unanswered requests
   - "critical": system outage (multiple users reporting), data loss risk

3. TICKET_ACTION — what happens in Zendesk:
   - "route_existing": message belongs to an existing active ticket (set ticket_id)
   - "create_new": new support topic, no matching active ticket
   - "follow_up": relates to a recently solved ticket (set follow_up_source_id)
   - "skip": not related to any ticket (e.g. casual greeting with no active support context)

4. EXTRACTED_QUESTION — if action is "answer", extract a clean standalone question.
   Merge with conversation context when the user is continuing a thread.

5. LANGUAGE — detect: "en", "ru", or "uz"

## CRITICAL RULES

- If user has an ACTIVE TICKET and says something vague ("ok", "thanks",
  "I have more questions", "one more thing"):
  → ticket_action = route_existing. NEVER create_new for continuation signals.

- If user has an ACTIVE TICKET and says "that didn't work" / "still broken":
  → action = escalate, ticket_action = route_existing.

- If user @mentions a SPECIFIC HUMAN AGENT (like @Xojiakbar_CS_DataTruck, @Datatruck_support,
  @mr_mamur, or any other person):
  → action = ignore (bot stays silent — user wants that person, not the bot).
  → ticket_action = route_existing or create_new as appropriate.
  Note: the bot's own username is @datatrucksupportbot. Do NOT confuse @Datatruck_support
  (a human agent) with the bot.

- If user requests a phone call ("call me", "tel qiling"):
  → action = escalate (bot can't make calls).

- If user asks for an account action ("add driver", "remove company", "migrate data"):
  → action = escalate (requires admin access).

- "Thank you" / "rahmat" / "thanks" after bot or agent answered:
  → action = ignore, ticket_action = route_existing (post to ticket for history).

- Multiple users in the same group with different issues → each gets own ticket.

- If message is a Telegram REPLY to a specific message, check reply_to_ticket_id
  to determine if it belongs to that ticket. But analyze CONTENT — a user may reply
  to someone's message but ask a completely different question → create_new.

- User B's message goes to User A's ticket ONLY if it's clearly about the same problem.
  Different issues = different tickets, even in the same group.

- If user mentions an issue that matches a RECENTLY SOLVED TICKET (shown in context),
  and their message suggests the solution didn't fully work or the issue returned:
  → ticket_action = follow_up, set follow_up_source_id to the solved ticket's ID.
  Example: ticket #200 "GPS sync issue" was solved 2 days ago. User: "GPS still not syncing"
  → follow_up, source_id=200.

- If user sends a PHOTO WITHOUT TEXT, analyze the image content to decide action.
  Screenshots showing errors = likely support question (action=answer or escalate).
  Random photos with no support context = action=ignore.

## EXAMPLES

{decision_examples}

Now analyze the following message.
"""
```

The `{decision_examples}` placeholder is filled with dynamically retrieved examples in PHASE 4.
Initially, use hardcoded examples similar to the ones in the old classifier_prompt.py and
thread_router_prompt.py — but combined into ONE format that shows action + ticket_action together.

---

## GENERATE PROMPT (`src/agent/prompts/generate_prompt.py`)

Keep the existing generator prompt logic from `src/agent/prompts/generator_prompt.py` but update
to match the new schema. Key rules remain:
- Return documentation content as-is (no rephrasing)
- Include article title as heading
- Respond in the user's language
- Do not mention internal retrieval details
- Set needs_escalation=true if no grounded answer possible

---

## GROUP ISOLATION RULES

Each Telegram group = different client company. Same user may be in multiple groups.

**ISOLATED per group (always filter by group_id):**
- conversation_history
- active_tickets
- user_active_ticket
- recently_solved_tickets
- bot_last_response
- conversation_threads

**SHARED across all groups (product knowledge):**
- Qdrant docs and learned Q&A
- Episodic memory (past resolution trajectories)
- Procedural memory (decision examples)

Every DB query in perceive node and remember node MUST include `group_id` filter
for conversation data. Never load another group's tickets, messages, or threads.

---

## ZENDESK SYNC ORDER

For every message path, the order is always:
1. User's message → create ticket or post as comment (the question comes first)
2. Bot's response → post as second comment on the same ticket (only if bot replied — answer or follow-up question)

This ensures human agents always see: what the user asked, then what the bot said.

---

## MESSAGE HANDLER (rewritten `src/telegram/handlers/message_handler.py`)

The handler becomes thin — it preprocesses and invokes the graph:

```python
@router.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_group_message(message: Message, graph, bot: Bot):
    if not message.from_user:
        return
    if not _has_supported_content(message):
        return

    # Check group is active
    group = await get_or_create_telegram_group(message.chat.id, title=message.chat.title)
    if not group.active:
        return

    # Upsert user
    await get_or_create_telegram_user(message.from_user.id, display_name=...)

    # Preprocess
    pp = await preprocess(message, bot)
    if not pp.is_supported:
        return

    # Store ALL messages in DB (before graph — ensures complete history)
    # Extract file_id for photos/voice/documents (for future image download)
    file_id = None
    file_type = None
    if message.photo:
        file_id = message.photo[-1].file_id  # largest size
        file_type = "photo"
    elif message.voice:
        file_id = message.voice.file_id
        file_type = "voice"
    elif message.audio:
        file_id = message.audio.file_id
        file_type = "voice"
    elif message.document:
        file_id = message.document.file_id
        file_type = "document"

    await save_message(
        chat_id=message.chat.id,
        message_id=message.message_id,
        user_id=message.from_user.id,
        username=message.from_user.full_name,
        text=pp.text or message.text or message.caption or "",
        source="telegram",
        reply_to_message_id=message.reply_to_message.message_id if message.reply_to_message else None,
        file_id=file_id,
        file_type=file_type,
    )

    # Invoke graph — thread_id = group chat ID for isolation
    config = {"configurable": {"thread_id": str(message.chat.id)}}
    await graph.ainvoke({
        "raw_text": pp.text or message.text or message.caption or "",
        "images": pp.images[:5] if pp.images else [],
        "sender_id": str(message.from_user.id),
        "sender_name": message.from_user.full_name or str(message.from_user.id),
        "group_id": str(message.chat.id),
        "group_name": message.chat.title or str(message.chat.id),
        "telegram_message_id": message.message_id,
        "reply_to_message_id": message.reply_to_message.message_id if message.reply_to_message else None,
    }, config=config)
```

---

## BOT STARTUP (updated `src/telegram/bot.py`)

Add LangGraph checkpointer initialization:

```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from src.agent.graph import build_graph

# At startup:
checkpointer = AsyncPostgresSaver.from_conn_string(settings.database_url_psycopg)
await checkpointer.setup()
graph = build_graph()
compiled_graph = graph.compile(checkpointer=checkpointer)

# Pass compiled_graph to handlers via aiogram middleware or dependency injection
```

Note: LangGraph checkpointer uses psycopg (not asyncpg). Add a `database_url_psycopg` property
to settings that converts the asyncpg URL to psycopg format:
`postgresql+asyncpg://` → `postgresql://`

---

## ADMIN DASHBOARD (Streamlit — rewrite for new architecture)

Keep Streamlit — it's Python-native, fast to iterate, and perfect for an internal tool.
Rewrite the current 4-page dashboard into 6 pages aligned with the new architecture.

### Page 1: Overview (Home)

Top-level health check. Should answer: "Is the bot working? How well?"

```
┌─────────────────────────────────────────────────────────────┐
│ DataTruck Support Agent Dashboard                           │
├──────────┬──────────┬──────────┬──────────┬────────────────┤
│ Messages │ Answered │ Escalated│ Learned  │ Active Groups  │
│ Today    │ Today    │ Today    │ Q&A Total│                │
│ 47       │ 8 (17%)  │ 12 (26%)│ 142      │ 4              │
└──────────┴──────────┴──────────┴──────────┴────────────────┘

Action distribution (today):        Trend (last 30 days):
 answer: ████████ 17%               [line chart: answer% going up,
 ignore: ████████████████ 34%         escalate% going down]
 wait:   ████ 9%
 escalate: ████████████ 26%
 skip:   ███████ 14%

Recent bot activity (last 10 decisions):
 [table: timestamp, group, user, message_preview, action, ticket]
```

Data sources:
- Messages table: COUNT(*) WHERE created_at > today, GROUP BY source
- Conversation threads: COUNT(*) WHERE status = 'open'
- Qdrant datatruck_memory: point count
- Need new table or log: `bot_decisions` (see below)

### Page 2: Performance

Detailed analytics. Should answer: "Is the bot getting smarter over time?"

```
Date range picker: [Last 7 days ▼]

Metrics over time (line charts):
- Answer rate: % of messages where action="answer" (should increase)
- Escalation rate: % where action="escalate" (should decrease)
- Learned Q&A count: cumulative growth

Top escalated questions (what docs are missing?):
 [table: extracted_question, count, groups_affected, last_seen]
 → These are questions the bot couldn't answer. Write docs for them!

Top answered questions (what's working?):
 [table: extracted_question, count, avg_retrieval_confidence]

Response time breakdown:
 [bar chart: perceive_ms, think_ms, retrieve_ms, generate_ms, respond_ms, remember_ms]
```

Data source: need a `bot_decisions` log table (see below).

### Page 3: Knowledge Base

Manage documentation, learned knowledge, and import new knowledge from multiple sources.
Replaces current Knowledge Base + Upload pages.

```
Tabs: [Documentation] [Learned Q&A] [Quick Add] [Import from Zendesk] [Upload]

─── Documentation tab ───
  Stats: X articles, Y chunks in datatruck_docs
  [Delta Sync] [Full Re-ingest] buttons
  Search box → searches Qdrant by text
  Paginated table: article_title, chunk_count, language, last_updated
  Click article → shows all chunks with text preview

─── Learned Q&A tab ───
  Stats: X entries in datatruck_memory
  Paginated table: question, answer_preview, source, language, created_at
  Source column shows: "manual" / "zendesk_import" / "file_import" / "auto_learned"
  Click entry → full Q&A, source details
  [Delete] button per entry (for incorrect learnings)
  Search box → searches by question text

─── Quick Add tab ───
  Simple form for manually adding Q&A pairs:
    Question: [text input]
    Answer:   [text area]
    Language: [en ▼] / [ru] / [uz]
    [Save to Memory]
  Saved directly to Qdrant datatruck_memory (no review step — you wrote it yourself).
  Source tag: "manual"
  Use case: you read a ticket and spot a good Q&A to add. 30 seconds per entry.

─── Import from Zendesk tab ───
  Three import modes:
    [Single ticket] Enter ticket ID: [________] [Fetch]
    [Range]         From: [______] To: [______] [Fetch]
    [Date range]    From: [date picker] To: [date picker]
                    Status filter: [Solved ▼] [Fetch]

  After fetch:
    Shows ticket list with subject, status, comment count
    [Select All] / individual checkboxes
    [Extract Q&A from selected] → Haiku reads each conversation → extracts Q&A pairs

    ═══ Review Screen ═══
    For each extracted Q&A pair:
    ┌──────────────────────────────────────────────────┐
    │ Ticket #456: "Load stuck in pending"             │
    │                                                  │
    │ Q: How to change load status from pending        │
    │    to dispatched?                                │
    │ A: Go to Settings > Load Management > select     │
    │    the load > click "Change Status" > choose     │
    │    "Dispatched" from the dropdown.               │
    │                                                  │
    │ Language: [en ▼]                                 │
    │ [✓ Approve]  [Edit]  [✗ Reject]                 │
    └──────────────────────────────────────────────────┘

    [Edit] opens inline editing — you can fix the question or answer before saving.
    [Approve] saves to Qdrant datatruck_memory with source tag "zendesk_import".
    [Reject] skips this pair.
    [Approve All Remaining] for bulk processing.

  This is the most powerful import method — your Zendesk already has hundreds of
  solved tickets. Fetch → extract → review → save. No manual export needed.

─── Upload tab ───
  Two sections:

  Documentation upload (existing):
    Drag & drop PDF/DOCX/TXT/MD files → ingested into datatruck_docs
    (existing upload functionality — keep as-is)

  Conversation file upload (new):
    Drag & drop PDF/DOC of a ticket conversation (from non-Zendesk sources)
    → Haiku reads the document → extracts Q&A pairs
    → Same Review Screen as Zendesk import
    → Approved pairs saved to datatruck_memory with source tag "file_import"

  Use case: conversations from email, WhatsApp, or other channels not in Zendesk.
```

Data sources: Qdrant collections, ZendeskTicketClient.get_ticket_comments(),
upload pipeline (existing for docs), Haiku for Q&A extraction.

Implementation priority:
1. Quick Add — simplest, build first
2. Import from Zendesk — highest impact for bootstrapping, build second
3. Conversation file upload — build last, for non-Zendesk sources

### Page 4: Decision Review

Review and correct bot decisions. Should answer: "Did the bot make the right call?"

```
Filters: [Group ▼] [Action ▼] [Date range] [Search message text]

Decision log table:
  timestamp | group | user | message_preview | action | ticket_action | ticket_id | reasoning

Click a row → expands to show:
  - Full message text
  - File description (if photo/document)
  - Conversation history at time of decision (what think saw)
  - Active tickets at time of decision
  - Think's reasoning
  - If action="answer": retrieved docs, answer text, retrieval confidence
  - Zendesk ticket link

Correction buttons:
  [✓ Correct] [✗ Wrong — should have been: answer/ignore/escalate]

Wrong decisions feed into procedural memory (Phase 4):
  - "This message was classified as X but should have been Y"
  - Becomes a few-shot example for future think decisions
```

Data source: `bot_decisions` log table.

### Page 5: Conversations

Monitor live conversations across all groups.

```
Group selector: [All Groups ▼] or [Artel] [Mir] [KGStar] [UGL]

Conversation view (per group):
  [chat-like display showing recent messages]
  Each message shows: timestamp, username, text, source badge (telegram/bot/zendesk)
  Photo messages show: [Photo: file_description]
  Voice messages show: [Voice] transcription text

  Active tickets sidebar:
  - Ticket #456: "Load pending" (Adam, open, 2h ago)
  - Ticket #457: "GPS sync issue" (Mike, open, 30m ago)

  Click ticket → opens in Zendesk (external link)
```

Data sources: messages table, conversation_threads table.

### Page 6: Groups

Manage Telegram groups. Keep existing functionality, minor refresh.

```
Active groups table: chat_id, title, active, message_count_today, open_tickets
Toggle active/inactive
Add group by chat_id
Remove group
```

Data sources: telegram_groups table, messages table (existing).

### New Table: `bot_decisions` (for Performance + Decision Review)

The think node produces a decision for every message. Store it for analytics:

```python
class BotDecision(Base):
    """Log of every bot decision — for performance analytics and decision review."""
    __tablename__ = "bot_decisions"
    __table_args__ = (
        Index("idx_decision_created", "created_at"),
        Index("idx_decision_group_created", "group_id", "created_at"),
        Index("idx_decision_action", "action", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    file_description: Mapped[str | None] = mapped_column(Text)

    # Think node output
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    urgency: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    ticket_action: Mapped[str] = mapped_column(String(20), nullable=False)
    target_ticket_id: Mapped[int | None] = mapped_column(BigInteger)
    extracted_question: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Generate node output (if action="answer")
    answer_text: Mapped[str | None] = mapped_column(Text)
    retrieval_confidence: Mapped[float | None] = mapped_column(nullable=True)
    needs_escalation: Mapped[bool] = mapped_column(Boolean, default=False)

    # Timing (milliseconds)
    perceive_ms: Mapped[int | None] = mapped_column(Integer)
    think_ms: Mapped[int | None] = mapped_column(Integer)
    retrieve_ms: Mapped[int | None] = mapped_column(Integer)
    generate_ms: Mapped[int | None] = mapped_column(Integer)
    total_ms: Mapped[int | None] = mapped_column(Integer)

    # Correction (set by admin in Decision Review page)
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    correct_action: Mapped[str | None] = mapped_column(String(20))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

The remember node saves one row to `bot_decisions` for every message processed.
This gives the dashboard everything it needs for analytics and decision review.

---

## PHASED IMPLEMENTATION PLAN

### PHASE 1: Core Graph (do this first)

1. **Fresh start cleanup** (from INFRASTRUCTURE section above):
   a. Rewrite `src/database/models.py` with clean schema (6 tables: telegram_users, zendesk_users, telegram_groups, messages, conversation_threads, bot_decisions)
   b. Rewrite `src/database/repositories.py` with all queries needed by new design
   c. Update `src/config/settings.py` — add `database_url_psycopg`, `conversation_history_limit`, remove `group_context_window`
   d. Clean up `src/escalation/ticket_schemas.py` — remove TicketRecord/TicketResponse
   e. Fix `src/escalation/ticket_client.py` — use shared httpx client (do NOT remove "test-tg-chat:" prefix — intentional during dev)
   f. Fix `src/telegram/preprocessor.py` — cache Gemini client instead of creating per call
   g. Fix `src/memory/approved_memory.py` — use proper payload fields instead of fake article metadata
   h. Fix `src/utils/retry.py` — use loguru lazy formatting
   i. Create `.dockerignore`, update Dockerfile to run as non-root
   j. Fix Makefile — remove "Redis" from infra description
   k. Update admin dashboard ticket page to use conversation_threads

2. Add new dependencies to `pyproject.toml`:
   `langgraph`, `langgraph-checkpoint-postgres`, `langchain-core`, `langchain-anthropic`, `psycopg[binary,pool]`

3. Create `src/agent/state.py` with SupportState TypedDict

4. Create `src/agent/nodes/perceive.py`:
   - Load conversation history from DB (use existing repositories)
   - Load active tickets from DB (use existing repositories)
   - Load user's active ticket
   - Load bot's last response
   - Load reply-to context (if message is a reply)
   - NO RAG probe — retrieval only happens in retrieve node after think decides
   - Return empty lists for episodic/procedural memory (PHASE 4)

5. Create `src/agent/nodes/think.py`:
   - Implement unified decision call using Claude Haiku tool-use pattern
   - Use hardcoded few-shot examples initially (combine examples from old classifier_prompt.py
     and thread_router_prompt.py into unified format)
   - Include ALL context in the prompt: message, images, history, tickets, bot state
   - Return action + ticket_action + extracted_question + language

6. Create `src/agent/edges.py` with routing functions

7. Create `src/agent/graph.py` with build_graph()

8. Create stub nodes:
   - `src/agent/nodes/retrieve.py` — call existing RAGRetriever
   - `src/agent/nodes/generate.py` — call Claude Sonnet (port from old generator.py)
   - `src/agent/nodes/respond.py` — send Telegram message (port from old handler)
   - `src/agent/nodes/remember.py` — stub that just logs

9. Update `src/telegram/bot.py` to initialize LangGraph checkpointer and graph

10. Rewrite `src/telegram/handlers/message_handler.py` to invoke graph

11. TEST: Send messages to bot → verify think node makes correct decisions

### PHASE 2: Zendesk Sync (remember node)

1. Implement full `remember` node:
   - Port Zendesk sync logic from old sync_service.py
   - Use think node's ticket_action and target_ticket_id (no separate thread router call!)
   - Handle 422 closed-ticket recovery
   - Sync bot's response as second comment
   - Update DB with zendesk_ticket_id

2. Remove old `src/escalation/sync_service.py`

3. TEST: Verify messages appear in correct Zendesk tickets

### PHASE 3: Learning (learn node)

1. Enhance `src/escalation/webhook_handler.py`:
   - On ticket solved: call learn logic
   - Extract Q&A pair via TicketSummarizer
   - Store in Qdrant datatruck_memory (existing ApprovedMemory)

2. Create `src/agent/nodes/learn.py` for the summarization + storage logic

3. TEST: Resolve a ticket in Zendesk → verify Q&A appears in datatruck_memory

### PHASE 4: Self-Improvement (episodic + procedural memory)

1. Create `src/learning/episode_recorder.py`:
   - Save full conversation trajectories to LangGraph Store
   - Namespace: ("episodes", topic_category)

2. Create `src/learning/example_selector.py`:
   - Dynamically retrieve relevant few-shot examples from LangGraph Store
   - Namespace: ("procedural", "decision_examples")

3. Update `perceive` node to query episodic and procedural memory

4. Update `think` prompt to use dynamic examples instead of hardcoded

5. Create `scripts/bootstrap_from_history.py`:
   - Process .telegram_chat_history/*.docx files
   - Extract Q&A pairs → Qdrant learned collection
   - Extract decision examples → LangGraph Store procedural memory
   - Extract conversation episodes → LangGraph Store episodic memory

6. TEST: Bootstrap from history → verify bot answers questions it couldn't before

### PHASE 5: Cleanup

1. Delete old files (classifier.py, extractor.py, thread_router.py, etc.)
2. Delete old context manager (context_manager.py, group_context.py)
3. Update tests

### PHASE 6: Admin Dashboard

1. Create `bot_decisions` table in models.py
2. Add decision logging to remember node (step 6 in remember spec)
3. Add timing instrumentation to each graph node (measure ms per node)
4. Rewrite dashboard Home page — performance metrics from bot_decisions table
5. Create Performance page — trends over time, top escalated/answered questions
6. Create Knowledge Base page with 5 tabs:
   a. Documentation tab (existing browse + sync)
   b. Learned Q&A tab (browse + delete)
   c. Quick Add tab — manual Q&A form → saves directly to Qdrant memory
   d. Import from Zendesk tab — fetch by ID/range/date → Haiku extracts Q&A → review screen
   e. Upload tab — docs upload (existing) + conversation file upload (new) → extract Q&A → review
7. Build the shared Review Screen component (approve/edit/reject Q&A pairs)
8. Create Decision Review page — filterable log with correction buttons
9. Create Conversations page — per-group chat view with active tickets sidebar
10. Update Groups page — add message_count_today, open_tickets columns

---

## CODE CONVENTIONS

- All I/O is async — asyncio, aiogram, httpx async, qdrant-client async
- Pydantic models for all inter-module data — no raw dicts between modules
- loguru for all logging — never use `print()`
- tenacity retries on every external API call (Anthropic, Gemini, Qdrant, Zendesk)
- Type annotations everywhere
- All Claude calls use tool-use pattern with `produce_output` tool
- Run `ruff check` and `ruff format` before committing
- Conventional commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`

## TESTING

```bash
uv run pytest                          # all tests
uv run pytest tests/unit/              # unit tests only
uv run pytest tests/integration/       # integration tests (requires Qdrant)
```

- Mock all external HTTP with `respx`
- Mock Claude responses in unit tests via `pytest-mock`
- Test think node with various state inputs to verify correct action + ticket_action
- Test graph end-to-end with mocked LLM and DB

## ENVIRONMENT VARIABLES (new additions)

```
# LangGraph checkpointer uses psycopg, not asyncpg
# The bot derives this automatically from DATABASE_URL by replacing the driver prefix
```

No new env vars needed — LangGraph uses the same PostgreSQL database.

## KEY PRINCIPLE

The bot speaks only when it has a confident, grounded answer from documentation or learned memory.
Otherwise it works invisibly — routing messages to the correct Zendesk ticket, recognizing urgency,
and getting smarter with every resolved ticket. When a user @mentions a specific human agent,
the bot stays completely silent — the user wants that person, not a bot.
