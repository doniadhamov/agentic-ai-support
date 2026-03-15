# Improvement Tasks — AI Agentic Support Bot

Current tasks to implement now.
Deferred tasks (error handling, image sending, webhook hardening, Docker, observability, escalation flow) are in `deferred-tasks.md`.

---

## Phase 1 — Code Quality & Bug Fixes

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 1.1 | Fix 30 auto-fixable ruff lint errors (`ruff check --fix .`) | (multiple) | ✅ |
| 1.2 | Fix 6 remaining manual ruff lint errors (unsorted imports, unused vars) | `src/telegram/bot.py`, `src/ingestion/zendesk_client.py`, `tests/unit/test_approved_memory.py`, `tests/unit/test_agent.py`, `tests/unit/test_qdrant_client.py` | ✅ |
| 1.3 | Fix `test_multiple_images_in_article` — chunker loses first image when article has multiple images across sections | `src/ingestion/chunker.py` | ✅ |
| 1.4 | Migrate `MessageCategory(str, Enum)` → `StrEnum` | `src/agent/schemas.py` | ✅ |
| 1.5 | Migrate `TicketStatus(str, Enum)` → `StrEnum` | `src/escalation/ticket_schemas.py` | ✅ |

---

## Phase 2 — Test Coverage

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 2.1 | Unit test: `format_reply()` — MarkdownV2 conversion, screenshot stripping, source links, 4096-char truncation, plain-text fallback | `tests/unit/test_formatter.py` | ⬜ |
| 2.2 | Unit test: `ScoreThresholdFilter` — filter by score, source tagging | `tests/unit/test_reranker.py` | ⬜ |
| 2.3 | Unit test: `build_query()` — query construction for en/ru/uz | `tests/unit/test_query_builder.py` | ⬜ |
| 2.4 | Unit test: `ArticleProcessor` — HTML to content blocks, image extraction | `tests/unit/test_article_processor.py` | ⬜ |
| 2.5 | Unit test: `MessageHandler` — full handler flow with mocked agent, reply sending, plain-text fallback | `tests/unit/test_message_handler.py` | ⬜ |
| 2.6 | Unit test: `language.py` — detection, normalization, BCP-47 tags, fallback to English | `tests/unit/test_language.py` | ⬜ |

---

## Phase 3 — Formatter Edge Cases

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 3.1 | Handle nested Markdown formatting (`***bold+italic***`) | `src/telegram/formatter.py` | ⬜ |
| 3.2 | Handle code blocks with language identifiers (` ```python `) | `src/telegram/formatter.py` | ⬜ |
| 3.3 | Handle links with special characters in URLs | `src/telegram/formatter.py` | ⬜ |
| 3.4 | Improve truncation — cut at sentence/paragraph boundary instead of mid-word | `src/telegram/formatter.py` | ⬜ |

---

## Dependency Map

```
Phase 1 (Code Quality)
  └─► Phase 2 (Test Coverage)
        └─► Phase 3 (Formatter Edge Cases)
```
