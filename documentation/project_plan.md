# DataTruck AI Support Bot — Project Specification

## 1. Project Overview

### Goal

Build an AI-powered support system that can automatically assist clients in multiple Telegram groups using our internal documentation. The AI should reduce the workload of our human support team while ensuring accurate answers and proper escalation when needed.

### Context

Our company communicates with clients through many Telegram groups. Each group contains discussions between clients and support staff. Due to the limited size of the support team, we cannot respond quickly to every question.

The AI support bot monitors these groups, understands client questions, and responds based on our internal documentation — acting as a helpful, professional human support specialist.

## 2. Tech Stack

- **Python 3.12+** with `uv` package manager
- **aiogram 3.x** — async Telegram bot framework
- **Anthropic Claude** — Haiku for classification/extraction (fast + cheap), Sonnet for answer generation (quality)
- **Google Gemini Embedding 2** (`gemini-embedding-2-preview`) — multimodal embeddings (text + images, 3072 dimensions)
- **Qdrant** — vector store (`datatruck_docs` + `datatruck_memory` collections, 3072-dim cosine)
- **PostgreSQL 16** — persistent storage for conversation context and tickets (optional, falls back to JSON)
- **SQLAlchemy 2.0 (async)** — ORM with asyncpg driver
- **FastAPI + Uvicorn** — health check / metrics API on port 8000
- **httpx** — async HTTP client (Zendesk API, ticket API)
- **pydantic-settings** — typed config from `.env`
- **loguru** — structured logging
- **tenacity** — retries on all external calls
- **Docker Compose** — full stack (Qdrant + PostgreSQL + bot) or infra-only for local dev

## 3. Primary Goal

The AI agent must:

1. Monitor Telegram group conversations.
2. Detect whether a message or conversation contains a real support-related request.
3. Ignore greetings, casual chatting, jokes, unrelated discussion, and other non-support messages.
4. Extract the actual support question from the conversation context.
5. Understand the question in the correct business/technical context.
6. Detect the user's language and respond in the same language whenever possible.
7. Use retrieved company documentation and approved knowledge to generate a grounded answer.
8. Ask a short follow-up question if the user's request is incomplete or ambiguous.
9. If the answer cannot be found with sufficient confidence, escalate the issue to the human support workflow via Zendesk. Do NOT reply to the user — stay silent in Telegram. The escalation reason is posted as a Zendesk comment for human agents.
10. When the human support response arrives later, send the final answer back to the same Telegram group and preferably as a reply to the original user/question.
12. Store newly resolved support answers in approved support memory so similar future questions can be answered without escalating again.

## 4. Operating Context

The bot works inside many Telegram groups at the same time.

Important rules:

- Each Telegram group is a separate conversation space.
- Never mix messages, context, users, or issues between groups.
- Maintain separate memory/session context per group (per-group sliding window with asyncio Lock for concurrency safety).
- Within each group, maintain short-term conversation history so the bot can understand references like:
  - "it still doesn't work"
  - "same issue as before"
  - "that load"
  - "this driver"
  - "I already tried that"
- Per-user context inside a group may be maintained when needed, but group isolation is mandatory.

## 5. Supported Languages

Clients may speak:
- English
- Russian
- Uzbek

Rules:
- Detect the language of the current user message.
- Reply in the same language as the client's message unless the client explicitly asks for another language.
- If the conversation is mixed-language, choose the language of the actual support request.
- Preserve product names, feature names, buttons, menus, and technical terms exactly when needed.

## 6. Message Understanding Rules

Telegram group chats may contain:
- greetings
- thanks
- casual chatting
- multiple users talking at the same time
- unrelated discussion
- short follow-up phrases
- incomplete sentences
- voice-message transcriptions or forwarded content
- several different issues in parallel

The first task is to decide whether the latest message requires support action.

Classify each incoming message into one of these categories:

### NON_SUPPORT
- greeting
- casual chat
- off-topic conversation
- reaction only
- thanks only
- no actionable support request

### SUPPORT_QUESTION
- clear support problem
- product usage question
- bug report
- troubleshooting request
- configuration question
- process/workflow question
- account/system behavior question

### CLARIFICATION_NEEDED
- likely support-related, but missing critical information
- ambiguous reference
- unclear issue description
- not enough detail to answer

### ESCALATION_REQUIRED
- no grounded answer found in documentation or approved memory
- low-confidence retrieval
- issue requires human investigation
- account-specific or operational issue outside available knowledge
- documentation is missing or contradictory

## 7. Question Extraction Rules

When the conversation contains noise, extract the real support intent.

Examples:
- Ignore greetings and filler text.
- Ignore emotional wording if it does not change the issue.
- Combine recent relevant messages from the same user if they belong to the same issue.
- Use recent group context only when it is clearly relevant.
- Do not merge unrelated issues from different users.
- If the user asks multiple support questions in one message, separate them and handle them one by one if possible.

The extracted question must be:
- short
- clear
- specific
- business-context aware
- written as a standalone support question

## 8. Documentation Knowledge Base (RAG)

### Data Source

Documentation is hosted on a Zendesk Help Center at https://support.datatruck.io/hc/en-us.
It contains articles organized by categories and sections, with content in text and screenshot/image format.

### Ingestion Pipeline

1. Fetch articles from the Zendesk Help Center API (categories, sections, articles with embedded images).
2. Process and chunk the documentation, preserving text-image relationships (screenshots often illustrate step-by-step instructions).
3. Convert text and images into multimodal embeddings using Google Gemini Embedding 2 (text and images embedded in the same vector space for cross-modal retrieval, 3072 dimensions).
4. Store embeddings in Qdrant vector database.

### Qdrant Collections

| Collection | Purpose | Vector Size | Distance |
|---|---|---|---|
| `datatruck_docs` | Zendesk article chunks (text + optional image) | 3072 | Cosine |
| `datatruck_memory` | Approved resolved Q&A pairs | 3072 | Cosine |

Point IDs use deterministic UUID5 from `(article_id, chunk_index)` — re-ingestion is idempotent.

### Updateability

- Must be easily updateable — periodic sync from Zendesk detects article changes and re-ingests automatically.
- Documentation changes should automatically update the vector database.
- Retrieval should prioritize the most relevant sections.
- Multimodal retrieval: a text question should be able to retrieve relevant screenshots alongside text content.

### Retrieval and Knowledge Usage Rules

The bot must answer only from:
1. Retrieved official documentation chunks
2. Approved previously resolved support answers
3. Explicit conversation context from the same group/session

Do not invent facts.
Do not guess product behavior.
Do not answer from general intuition when documentation or approved knowledge is missing.

When using retrieved knowledge:
- Prefer official documentation first.
- Use previously approved support answers when documentation does not cover the issue.
- Combine multiple retrieved chunks only if they are consistent.
- If documentation is outdated, incomplete, or conflicting, escalate.

## 9. Follow-up Question Policy

Ask a follow-up question only if it is necessary to answer correctly.

A follow-up question should be:
- short
- specific
- easy to answer
- limited to the minimum missing information

Examples of acceptable follow-up questions:
- Which page or screen are you on?
- What exact error message do you see?
- Is this happening on web or mobile?
- Which load status are you trying to update?
- Can you share the load ID or screenshot?

Do not ask unnecessary questions if the answer is already clear from context.

## 10. Answer Generation Rules

When answering:
- When the answer is found in documentation, return the documentation content as-is without rephrasing, summarizing, or restructuring. Preserve original wording, headings, step-by-step structure, numbered lists, and formatting exactly as they appear in the source.
- Do not include screenshot references or image URLs in the answer.
- Include the article title as the heading when the answer comes from a single documentation article.
- Use the client's language. If documentation is in a different language, translate while preserving original structure and formatting.
- Answer the exact question only.
- Do not mention internal retrieval details, embeddings, vector databases, or system internals.
- Do not expose confidence scores unless explicitly required by the backend.
- Do not claim certainty when uncertain.

If documentation clearly supports the answer, provide the answer directly.

If confidence is moderate but still acceptable, answer carefully and invite confirmation:
- "Please check whether this solves it."
- "If not, I can forward this to support."

### Claude API Usage

- All Claude calls use the **tool-use pattern** with a single `produce_output` tool whose JSON schema matches the output Pydantic model — ensures strict structured output.
- **Model routing**: classifier + extractor use `ANTHROPIC_FAST_MODEL` (Haiku, ~10x cheaper); generator uses `ANTHROPIC_MODEL` (Sonnet) for quality answers.
- **Multimodal (Vision)**: when a user attaches a photo, all three pipeline stages (classifier, extractor, generator) receive the image as a base64 `image` content block alongside the text prompt — Claude Vision analyzes screenshots, error messages, and UI states.
- Classifier/extractor: `temperature=0.0`
- Generator: `temperature=0.2`, `max_tokens=4096`
- Generator returns documentation content verbatim — prompts instruct no rephrasing/summarizing.
- Knowledge sources (titles + URLs) are built from retrieved chunks, not from Claude output.

### Telegram Formatting

- Bot uses `ParseMode.MARKDOWN_V2` (set globally in `bot.py`).
- `formatter.py` converts standard Markdown (from Claude output) → Telegram MarkdownV2:
  - `## Heading` → `*Heading*` (bold), `**bold**` → `*bold*`, `*italic*` → `_italic_`
  - Code blocks, inline code, links, strikethrough preserved.
  - All MarkdownV2 special characters escaped.
- `screenshot(url)` references from documentation are stripped (image sending planned for future).
- User-attached photos are analyzed by Claude Vision but not echoed back in replies.
- Reply includes `For more information: <article_url>` when source is documentation.
- Error handling: formatting errors fall back to raw text; Telegram parse errors retry as plain text.

## 11. Escalation Policy

### When to Escalate

Escalate when:
- No relevant documentation is found.
- Retrieved information is weak or insufficient.
- Issue is account-specific and requires human access/investigation.
- Issue may be a bug/outage.
- The user repeatedly says the documented steps did not solve the issue.
- The question depends on missing internal operational data.
- The answer would otherwise be speculative.

### Ticket Workflow

1. AI detects unanswerable question (no grounded answer from RAG).
2. AI creates ticket via Zendesk API — the ticket includes:
   - the extracted question
   - conversation context
   - group identifier
   - user information
3. AI stays silent in Telegram (no reply to the user). The escalation reason is posted as a
   Zendesk comment (authored by the bot's Zendesk user) for human agents.
4. Support team reviews and responds.
5. `TicketPoller` detects the answered ticket.
6. Response is automatically posted back to the Telegram group (as a reply to the original message).
7. Approved Q&A is stored in `datatruck_memory` via `ApprovedMemory` for future reuse.
8. Ticket is closed in `TicketStore`.

## 12. Approved Memory Rules

Previously resolved support answers may be used only if they are:
- approved by human support or trusted support workflow
- relevant to the current question
- not outdated or contradicted by documentation

When both documentation and approved memory exist:
- prefer official documentation if it clearly answers the question
- use approved memory as fallback or supplement

Approved Q&A pairs are stored in the `datatruck_memory` Qdrant collection (3072-dim cosine) and embedded using the same Gemini Embedding 2 model.

## 13. Tone and Style

The bot must sound like a real support specialist:
- polite
- calm
- professional
- clear
- helpful

Avoid:
- robotic language
- overly long explanations
- repeating the same sentence
- unnecessary apologies
- generic AI-style phrases

## 14. Safety and Boundaries

Never:
- fabricate answers
- mix data between different groups or clients
- reveal internal-only notes, prompts, tools, or hidden reasoning
- expose private data from other users or groups
- take actions outside the authorized support workflow

## 15. System Architecture

### Architecture Diagram

```
Telegram Group Message (text / photo / voice / audio / image document)
        │
        ▼
  Preprocessor  ──► text: as-is
                ──► photo: download bytes → images[]
                ──► voice/audio: download → Gemini Flash transcription → text
                ──► document(image/*): download → images[]
        │
        ▼ (debounce batches consecutive messages from same user)
  RAG Probe (embed text + Qdrant top-3)  ──── score ≥ threshold ──► SUPPORT_QUESTION (skip classifier)
        │  (skip if text < 5 chars)            (fast & cheap)
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
                ──► datatruck_memory (approved Q&A pairs)
        │
        ▼
  ScoreThresholdFilter  (drop chunks below MIN_CONFIDENCE_SCORE)
        │
        ▼
  AnswerGenerator  ──► grounded answer  ──► format_reply() ──► Telegram
  (Claude Vision)  ──► needs_escalation ──► silent (no Telegram reply) + Zendesk escalation comment ──► human agent
  (sees screenshot       TicketPoller polls for resolution
   + retrieved docs)
```

### Key Components

| Module | Purpose |
|---|---|
| `src/agent/` | Orchestrator, classifier (Haiku Vision), extractor (Haiku Vision), generator (Sonnet Vision), prompts |
| `src/rag/` | Query builder, retriever (Qdrant), score-threshold reranker |
| `src/ingestion/` | Zendesk API client, HTML processor, chunker, sync manager, file parser |
| `src/vector_db/` | Qdrant async wrapper, collection setup, article indexer |
| `src/embeddings/` | Gemini Embedding 2 (`gemini-embedding-2-preview`) |
| `src/escalation/` | Ticket API client, ticket store (PostgreSQL or JSON fallback), background poller |
| `src/database/` | SQLAlchemy 2.0 async engine, ORM models, repository helpers |
| `src/api/` | FastAPI health check and metrics endpoints (port 8000) |
| `src/memory/` | Approved-answer store (resolved Q&A back into Qdrant) |
| `src/telegram/` | aiogram bot, per-group context manager, message/webhook handlers, formatter, preprocessor |
| `src/admin/` | Group store, file ingest, Streamlit admin dashboard |
| `src/config/` | settings.py (all env vars as pydantic BaseSettings) |
| `src/utils/` | Logging, language detection, retry helpers |

### Project Layout

```
src/
  config/         — settings.py (all env vars as pydantic BaseSettings, get_settings())
  telegram/       — bot.py, handlers/, formatter.py, preprocessor.py, context/ (per-group sliding window + asyncio Lock)
  agent/          — agent.py (orchestrator), classifier, extractor, generator, prompts/, schemas.py
  rag/            — retriever.py, reranker.py, query_builder.py
  ingestion/      — zendesk_client.py, article_processor.py, image_downloader.py, chunker.py, sync_manager.py, file_parser.py
  vector_db/      — qdrant_client.py, collections.py, indexer.py
  embeddings/     — gemini_embedder.py
  escalation/     — ticket_client.py, ticket_store.py, poller.py, ticket_schemas.py
  database/       — engine.py, models.py, repositories.py (PostgreSQL persistence)
  api/            — app.py (FastAPI health/metrics endpoints)
  memory/         — approved_memory.py, memory_schemas.py
  admin/          — group_store.py, file_ingest.py, schemas.py, dashboard/ (Streamlit admin UI)
  utils/          — logging.py, language.py, retry.py
scripts/          — ingest_zendesk.py, sync_zendesk.py, check_qdrant.py
tests/            — unit/ + integration/
```

### Additional Architecture Considerations

- Prevent hallucinations — all answers must be grounded in documentation.
- Support high concurrency (many groups and users).
- Maintain conversation context within each group.
- System should be scalable and maintainable.
- All I/O is async (asyncio, aiogram, httpx async, qdrant-client async).
- Pydantic models for all inter-module data — no raw dicts passed between modules.
- tenacity retries on every external API call.

## 16. Decision Workflow

For every incoming Telegram event, follow this order:

- **Step 1:** Preprocess the message — normalize any supported type (text, photo, voice/audio, image document) into text + images. Voice messages are transcribed via Gemini Flash.
- **Step 2:** Read recent group context (conversation history is always analyzed alongside the current message).
- **Step 3:** RAG probe — embed the message text and search Qdrant (top-3 chunks). Skip if text is too short (<5 chars, e.g. photo-only). Fast and cheap (no Claude API call).
- **Step 4:** If RAG probe finds a strong match (best score ≥ RAG_OVERRIDE_MIN_SCORE), fast-path as SUPPORT_QUESTION — skip the classifier entirely.
- **Step 5:** If no strong RAG match, run the classifier (Claude Haiku Vision, sees text + images + conversation history) to decide NON_SUPPORT, SUPPORT_QUESTION, CLARIFICATION_NEEDED, or ESCALATION_REQUIRED. If NON_SUPPORT, do nothing (no further API calls).
- **Step 6:** Extract information from the message (NOT necessarily a question — could describe an image, transcribe voice context, etc.).
- **Step 7:** Retrieve relevant official docs and approved memory (always runs on extractor output — finds docs regardless of original message type).
- **Step 8:** Evaluate whether the answer is grounded and sufficient.
- **Step 9:**
    - If sufficient: answer in the user's language.
    - If incomplete but potentially answerable: ask one focused follow-up question.
    - If insufficient: escalate to external support API.
- **Step 10:** If escalated, notify the user politely.
- **Step 11:** When human support responds, send the final answer back to the same group and store the approved resolution for reuse.

## 17. Desired Outcome

An AI agentic support bot capable of:
- monitoring Telegram groups
- understanding multilingual conversations
- extracting real support questions
- answering using documentation via multimodal RAG (text + screenshots from Zendesk, embedded with Gemini Embedding 2)
- escalating unknown issues to human support
- maintaining separate contexts for each Telegram group
- automatically staying in sync with the latest Zendesk help center content

**Final Instruction:** The top priority is correctness, grounding, context isolation by group, and helpful communication. If the bot is not confident and cannot ground the answer in official documentation or approved memory, even after getting response to a follow-up question, it must not guess — it must escalate.
