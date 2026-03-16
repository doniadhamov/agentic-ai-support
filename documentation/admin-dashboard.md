# Admin Dashboard — Implementation Summary

## Overview

Streamlit-based admin dashboard for the DataTruck Telegram support bot. Provides group security management, knowledge base browsing, file upload ingestion, and escalated ticket visibility — all without requiring CLI access.

## Architecture

- **Streamlit** talks directly to Qdrant, JSON files, and the ingestion pipeline (no FastAPI middleman)
- **Bot and dashboard** share state via a JSON file (`data/allowed_groups.json`) for the group allowlist
- Dashboard runs as a separate process (or Docker container) on port **8501**
- Auth via `ADMIN_PASSWORD` env var (empty = no auth in dev mode)
- Custom CSS applied globally — gradient sidebar, styled metric cards, status badges, hover effects

## Pages

### Home (`app.py`)

Landing page with:
- **Gradient welcome banner**
- **4 live metric cards** — Active Groups, Ingested Articles, Memory Entries, Open Tickets (pulled from Qdrant + `data/tickets.json` on every load)
- **Navigation cards** for each section with live status/count summaries

### 1. Groups (`pages/1_Groups.py`)

Manage the Telegram group allowlist:
- Status metrics (total groups, allowlist active/inactive, mode)
- Add group form (Group ID + display name)
- Searchable/filterable groups table with delete buttons
- Changes take effect in the bot within 5 seconds (auto-reload via mtime check)

**Allowlist behaviour:** when the list is empty the bot accepts all groups (backward-compatible).

### 2. Knowledge Base (`pages/2_Knowledge_Base.py`)

Browse and manage Qdrant vector collections:
- **Tabbed interface** — `datatruck_docs` and `datatruck_memory` collections
- **4 metrics per tab** — Total Points, Vector Dimensions, Distance Metric, Status
- **Graceful empty state** — if a collection does not exist yet, shows a warning + "Create Collection" button instead of an error
- **Zendesk Sync section** (docs collection only):
  - **Delta Sync (24h)** — re-ingests only articles updated in the last 24 hours
  - **Full Re-ingest** — re-ingests all Zendesk articles; requires confirmation; auto-creates collections if missing
  - Both sync buttons call `create_collections_if_not_exist()` before indexing
- **Browse Points** — paginated table (20/page) with ID, title, chunk index, text preview, language, source
- **Delete Point** — expander with UUID input to remove individual vectors

### 3. Upload (`pages/3_Upload.py`)

Ingest custom documents into the knowledge base:
- Supported formats: `.pdf`, `.docx`, `.txt`, `.md`
- File info metrics (name, size, format)
- Expandable text preview (first 3,000 chars) + block/character count
- "Ingest into Knowledge Base" button — parse → chunk → embed (Gemini) → index (Qdrant)
- Article IDs for uploaded files start at 10,000,000+ to avoid collision with Zendesk IDs
- Re-uploading the same file overwrites existing chunks (idempotent via deterministic UUID5 point IDs)

### 4. Tickets (`pages/4_Tickets.py`)

Read-only view of escalated support tickets:
- **4 status metric cards** — Total, Open, Answered, Closed
- Combined filter row — status dropdown + free-text search by question content
- Status indicators (🔵 open, 🟢 answered, ⚪ closed) in the table
- Detail view — metadata row + full question + answer text areas

## New Dependencies

| Package | Purpose |
|---------|---------|
| `pymupdf>=1.24.0` | PDF text extraction |
| `python-docx>=1.1.0` | DOCX text extraction |
| `streamlit>=1.37.0` | Admin dashboard UI (optional dep) |

## Files

### Created

| File | Purpose |
|------|---------|
| `src/admin/__init__.py` | Package init |
| `src/admin/schemas.py` | AllowedGroup, IngestResult models |
| `src/admin/group_store.py` | Group allowlist persistence + singleton |
| `src/admin/file_ingest.py` | File upload → chunker → indexer orchestrator |
| `src/ingestion/file_parser.py` | PDF/DOCX/TXT → ContentBlock parsers |
| `src/admin/dashboard/__init__.py` | Package init |
| `src/admin/dashboard/app.py` | Streamlit main app + auth gate + home page |
| `src/admin/dashboard/utils.py` | `run_async()` helper — bridges sync Streamlit with async code |
| `src/admin/dashboard/pages/1_Groups.py` | Group management page |
| `src/admin/dashboard/pages/2_Knowledge_Base.py` | Knowledge base browser + sync page |
| `src/admin/dashboard/pages/3_Upload.py` | File upload & ingestion page |
| `src/admin/dashboard/pages/4_Tickets.py` | Escalated tickets viewer |
| `tests/unit/test_group_store.py` | 11 tests for GroupStore |
| `tests/unit/test_file_parser.py` | 10 tests for file parsers |
| `tests/unit/test_file_ingest.py` | 6 tests for ingestion orchestrator |

### Modified

| File | Change |
|------|--------|
| `src/config/settings.py` | Added `admin_password`, `allowed_groups_file` fields |
| `src/telegram/handlers/message_handler.py` | Added group allowlist guard |
| `src/vector_db/qdrant_client.py` | Added `get_collection_info`, `scroll_points`, `count_points`, `delete_points_by_ids` |
| `pyproject.toml` | Added `pymupdf`, `python-docx`, streamlit optional dep group |
| `docker-compose.yml` | Added `dashboard` service + shared `data` volume |
| `Makefile` | Added `dashboard`, `dashboard-local`, `dashboard-logs` targets |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_PASSWORD` | `""` (no auth) | Dashboard login password |
| `ALLOWED_GROUPS_FILE` | `data/allowed_groups.json` | Path to group allowlist |

## How to Run

### Local Development

```bash
uv sync --extra admin          # install streamlit + PDF/DOCX deps
make qdrant-only               # start Qdrant
make dashboard-local           # starts Streamlit at http://localhost:8501
```

### Docker

```bash
make build                     # build image
make dashboard                 # start dashboard container
make dashboard-logs            # follow logs
# Access at http://localhost:8501
```

### Full Stack (Qdrant + Bot + Dashboard)

```bash
make build
docker compose up -d qdrant bot dashboard
```

## Initial Knowledge Base Setup

The dashboard can fully replace the CLI ingestion script:

1. Open **Knowledge Base** → `datatruck_docs` tab
2. Click **Full Re-ingest** → confirm → wait (collections are created automatically if missing)
3. Done — equivalent to `uv run python scripts/ingest_zendesk.py`

For ongoing sync, use **Delta Sync (24h)** to pick up Zendesk article changes daily.

## How to Test

### Unit Tests

```bash
uv run pytest tests/unit/test_group_store.py -v     # 11 tests — group allowlist
uv run pytest tests/unit/test_file_parser.py -v      # 10 tests — PDF/DOCX/TXT parsing
uv run pytest tests/unit/test_file_ingest.py -v      # 6 tests — ingestion orchestrator
uv run pytest tests/unit/ -v                         # all unit tests
```

### Manual Testing

1. **Groups:** Add a group → verify "Allowlist ACTIVE". Remove all → bot accepts all groups again.
2. **Knowledge Base:** Run Full Re-ingest → verify article/chunk counts. Browse points table. Delete a point.
3. **Upload:** Upload PDF/DOCX/TXT → preview text → ingest → verify new points appear in Knowledge Base.
4. **Tickets:** Verify table, status filter, search, and detail view work against `data/tickets.json`.

## Future Improvements

- Full ticket management backend (close, reassign, reply from dashboard)
- Image extraction from PDFs for multimodal embeddings
- Bulk file upload
- Search/filter points by text content in Knowledge Base
- Activity stats per group (message count, escalations)
- Audit log for admin actions
