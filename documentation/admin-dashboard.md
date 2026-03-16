# Admin Dashboard — Implementation Summary

## Overview

Streamlit-based admin dashboard for the DataTruck Telegram support bot. Provides group security management, knowledge base browsing, file upload ingestion, and escalated ticket visibility — all without requiring CLI access.

## Architecture

- **Streamlit** talks directly to Qdrant, JSON files, and the ingestion pipeline (no FastAPI middleman)
- **Bot and dashboard** share state via a JSON file (`data/allowed_groups.json`) for the group allowlist
- Dashboard runs as a separate process (or Docker container) on port **8501**
- Auth via `ADMIN_PASSWORD` env var (empty = no auth in dev mode)

## What Was Implemented

### 1. Group Allowlist (Security)

**Problem:** The bot previously accepted messages from ANY Telegram group — no access control.

**Solution:**
- `src/admin/group_store.py` — JSON-backed store with auto-reload every 5s
- `src/telegram/handlers/message_handler.py` — guard that silently drops messages from non-allowed groups
- Backward-compatible: when the allowlist is empty, the bot accepts all groups (existing behavior)
- Dashboard page: add/remove groups, see status indicator

**Files:**
- `src/admin/group_store.py` — GroupStore class (add, remove, list, is_allowed, has_groups)
- `src/admin/schemas.py` — AllowedGroup, IngestResult Pydantic models
- `src/config/settings.py` — added `admin_password`, `allowed_groups_file` settings

### 2. Knowledge Base Browser

**Dashboard page** (`src/admin/dashboard/pages/2_Knowledge_Base.py`):
- Browse `datatruck_docs` and `datatruck_memory` collections
- View collection stats (point count, vector size, status)
- Paginated point table with title, chunk index, text preview, language
- "Delta Sync" button — syncs articles updated in last 24h
- "Full Re-ingest" button — full Zendesk re-ingestion (with confirmation)
- Delete individual points by UUID

**Backend:**
- `src/vector_db/qdrant_client.py` — extended with `get_collection_info`, `scroll_points`, `count_points`, `delete_points_by_ids`

### 3. File Upload & Ingestion

**Problem:** Only Zendesk articles could be ingested. No way to add PDF/DOCX/TXT documents.

**Solution:**
- `src/ingestion/file_parser.py` — parsers for PDF (pymupdf), DOCX (python-docx), TXT/MD
- `src/admin/file_ingest.py` — orchestrator that wires parsing into the existing chunker + embedder + indexer pipeline
- Dashboard page with file upload, text preview, and ingest button
- Article IDs for uploaded files start at 10,000,000+ to avoid collision with Zendesk IDs
- Re-uploading the same file overwrites existing chunks (idempotent via deterministic UUID5 point IDs)

**Supported formats:** `.pdf`, `.docx`, `.txt`, `.md`

### 4. Tickets (Read-Only Placeholder)

**Dashboard page** (`src/admin/dashboard/pages/4_Tickets.py`):
- Reads `data/tickets.json` directly
- Table with ticket ID, group ID, question, status, created date
- Filter by status (OPEN / ANSWERED / CLOSED)
- Detail view with full question and answer text
- Backend management (close, reassign, etc.) planned for future update

## New Dependencies

| Package | Purpose |
|---------|---------|
| `pymupdf>=1.24.0` | PDF text extraction |
| `python-docx>=1.1.0` | DOCX text extraction |
| `streamlit>=1.37.0` | Admin dashboard UI (optional dep) |

## Files Created

| File | Purpose |
|------|---------|
| `src/admin/__init__.py` | Package init |
| `src/admin/schemas.py` | AllowedGroup, IngestResult models |
| `src/admin/group_store.py` | Group allowlist persistence + singleton |
| `src/admin/file_ingest.py` | File upload → chunker → indexer orchestrator |
| `src/ingestion/file_parser.py` | PDF/DOCX/TXT → ContentBlock parsers |
| `src/admin/dashboard/__init__.py` | Package init |
| `src/admin/dashboard/app.py` | Streamlit main app + auth gate |
| `src/admin/dashboard/utils.py` | Async runner helper for Streamlit |
| `src/admin/dashboard/pages/1_Groups.py` | Group management page |
| `src/admin/dashboard/pages/2_Knowledge_Base.py` | Knowledge base browser page |
| `src/admin/dashboard/pages/3_Upload.py` | File upload page |
| `src/admin/dashboard/pages/4_Tickets.py` | Tickets placeholder page |
| `tests/unit/test_group_store.py` | 11 tests for GroupStore |
| `tests/unit/test_file_parser.py` | 10 tests for file parsers |
| `tests/unit/test_file_ingest.py` | 6 tests for ingestion orchestrator |

## Files Modified

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
uv sync --extra admin          # install streamlit
make qdrant-only               # start Qdrant
make dashboard-local           # starts Streamlit at http://localhost:8501
```

### Docker

```bash
make build                     # build image
make dashboard                 # start dashboard container
# Access at http://localhost:8501
make dashboard-logs            # follow logs
```

### Full Stack (Qdrant + Bot + Dashboard)

```bash
make build
docker compose up -d qdrant bot dashboard
```

## How to Test

### Unit Tests

```bash
uv run pytest tests/unit/test_group_store.py -v     # 11 tests — group allowlist
uv run pytest tests/unit/test_file_parser.py -v      # 10 tests — PDF/DOCX/TXT parsing
uv run pytest tests/unit/test_file_ingest.py -v      # 6 tests — ingestion orchestrator
uv run pytest tests/unit/ -v                         # all 180 unit tests
```

### Manual Testing

1. **Group allowlist:**
   - Open dashboard → Groups page
   - Add a group ID → verify "Allowlist ACTIVE" indicator
   - Send a message from a non-listed group → verify bot ignores it
   - Remove all groups → verify bot responds to all groups again

2. **Knowledge base:**
   - Open dashboard → Knowledge Base page
   - Verify point counts match Qdrant dashboard at `http://localhost:6333/dashboard`
   - Click "Delta Sync" → verify new articles appear
   - Delete a point → verify it disappears from the table

3. **File upload:**
   - Open dashboard → Upload page
   - Upload a test PDF/DOCX/TXT file
   - Verify text preview is shown
   - Click "Ingest" → verify success message with chunk count
   - Check Knowledge Base page → verify new points appear in `datatruck_docs`

4. **Tickets:**
   - Open dashboard → Tickets page
   - If `data/tickets.json` exists, verify tickets are displayed
   - Test status filter dropdown
   - Click a ticket to see detail view

## Future Improvements

- Full ticket management backend (close, reassign, reply from dashboard)
- Image extraction from PDFs for multimodal embeddings
- Bulk file upload
- Search/filter points by text content in Knowledge Base page
- Activity stats per group (message count, escalations)
- Audit log for admin actions
