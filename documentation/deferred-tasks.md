# Deferred Tasks — AI Agentic Support Bot

Tasks to implement later. Separated from the main improvement backlog.

---

## Group A — Error Handling & Resilience

| # | Task | File(s) | Status |
|---|------|---------|--------|
| A.1 | Validate `SUPPORT_API_BASE_URL` format in settings (non-empty, valid URL) | `src/config/settings.py` | ⬜ |
| A.2 | Add graceful shutdown handling for ticket poller and sync tasks | `src/telegram/bot.py` | ⬜ |
| A.3 | Add timeout configuration for individual API calls (Anthropic, Gemini, Qdrant) | `src/config/settings.py` | ⬜ |

---

## Group B — Telegram Image Sending

| # | Task | File(s) | Status |
|---|------|---------|--------|
| B.1 | Design image delivery: extract image URLs from chunks, send as Telegram photo after text reply | — | ⬜ |
| B.2 | Update `AgentOutput` or `GeneratorResult` to carry image URLs for the reply | `src/agent/schemas.py` | ⬜ |
| B.3 | Update generator to preserve image references (currently stripped) and pass them through | `src/agent/generator.py`, `src/agent/prompts/generator_prompt.py` | ⬜ |
| B.4 | Implement image sending in message handler — `bot.send_photo()` after text reply | `src/telegram/handlers/message_handler.py` | ⬜ |
| B.5 | Update formatter to strip screenshot markers from text but return image URLs separately | `src/telegram/formatter.py` | ⬜ |
| B.6 | Unit + integration test for image delivery flow | `tests/unit/test_message_handler.py` | ⬜ |

---

## Group C — Webhook & Polling Hardening

| # | Task | File(s) | Status |
|---|------|---------|--------|
| C.1 | Check `TICKET_CALLBACK_MODE` in poller — disable polling when mode is `webhook` | `src/escalation/poller.py` | ⬜ |
| C.2 | Improve webhook error responses — return 400 for bad payloads, 200 for success (not 500 on Telegram failures) | `src/telegram/handlers/webhook_handler.py` | ⬜ |
| C.3 | Add webhook signature verification or shared secret for callback security | `src/telegram/handlers/webhook_handler.py` | ⬜ |
| C.4 | Wire approved memory storage into webhook callback flow (currently only in poller) | `src/telegram/handlers/webhook_handler.py` | ⬜ |

---

## Group D — Docker & Deployment

| # | Task | File(s) | Status |
|---|------|---------|--------|
| D.1 | Add `.dockerignore` (exclude `.git`, `.env`, `__pycache__`, `tests/`, `.venv/`) | `.dockerignore` | ⬜ |
| D.2 | Run container as non-root user in Dockerfile | `Dockerfile` | ⬜ |
| D.3 | Optimize Dockerfile layer caching — copy `pyproject.toml` + `uv.lock` before source code | `Dockerfile` | ⬜ |
| D.4 | Add resource limits (CPU/memory) to docker-compose.yml services | `docker-compose.yml` | ⬜ |
| D.5 | Add restart policies for bot and Qdrant services | `docker-compose.yml` | ⬜ |

---

## Group E — Observability & Monitoring

| # | Task | File(s) | Status |
|---|------|---------|--------|
| E.1 | Add structured JSON logging option for production (`LOG_FORMAT=json` setting) | `src/utils/logging.py`, `src/config/settings.py` | ⬜ |
| E.2 | Add request ID tracking across async agent pipeline steps | `src/agent/agent.py` | ⬜ |
| E.3 | Add latency logging per pipeline step (classify, extract, retrieve, generate) | `src/agent/agent.py` | ⬜ |
| E.4 | Add inactive group context cleanup (remove contexts for groups with no messages in N hours) | `src/telegram/context/context_manager.py` | ⬜ |

---

## Group F — Escalation, Ticket Return & Approved Memory

| # | Task | File(s) | Status |
|---|------|---------|--------|
| F.1 | Add null check on ticket API response (`data["ticket_id"]` may be missing) | `src/escalation/ticket_client.py` | ⬜ |
| F.2 | Handle empty answer in ANSWERED tickets — poller should skip or re-poll | `src/escalation/poller.py` | ⬜ |
| F.3 | Add idempotency guard: if Telegram send succeeds but `ApprovedMemory.store()` fails, retry memory storage on next poll | `src/escalation/poller.py` | ⬜ |
| F.4 | Unit test: `TicketPoller` — poll loop, Telegram reply delivery, approved memory storage, ticket closure | `tests/unit/test_poller.py` | ⬜ |
| F.5 | Unit test: `TicketAPIClient` — create ticket, get status, retry on failure, auth header | `tests/unit/test_ticket_client.py` | ⬜ |
| F.6 | Unit test: `TicketStore` — add, get open tickets, close, JSON file persistence | `tests/unit/test_ticket_store.py` | ⬜ |
| F.7 | Integration test: webhook callback handler — POST payload validation, Telegram reply delivery | `tests/integration/test_webhook_handler.py` | ⬜ |
