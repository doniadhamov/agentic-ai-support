.PHONY: help build up down logs restart ingest sync lint test test-unit test-integration qdrant-only infra dashboard dashboard-local dashboard-logs

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "Docker (full stack):"
	@echo "  build          Build the bot Docker image"
	@echo "  up             Start all services (detached)"
	@echo "  down           Stop all services"
	@echo "  down-v         Stop all services and remove volumes"
	@echo "  logs           Follow bot logs"
	@echo "  restart        Restart the bot service"
	@echo "  ingest         Run one-shot Zendesk ingestion"
	@echo "  sync           Run one-shot Zendesk sync"
	@echo ""
	@echo "Admin dashboard:"
	@echo "  dashboard      Start admin dashboard (Docker)"
	@echo "  dashboard-local  Start admin dashboard locally"
	@echo "  dashboard-logs Follow dashboard logs"
	@echo ""
	@echo "Local development:"
	@echo "  qdrant-only    Start only Qdrant (for local dev)"
	@echo "  infra          Start Qdrant + PostgreSQL (for local dev)"
	@echo ""
	@echo "Code quality:"
	@echo "  lint           Run ruff check + format"
	@echo "  test           Run all tests"
	@echo "  test-unit      Run unit tests only"
	@echo "  test-int       Run integration tests (requires Qdrant)"

# ── Docker (full stack) ────────────────────────────────────────────────────────

build:
	docker compose build

up:
	docker compose up -d qdrant postgres bot dashboard

down:
	docker compose down

down-v:
	docker compose down -v

logs:
	docker compose logs -f bot

restart:
	docker compose restart bot

ingest:
	docker compose run --rm ingest

sync:
	docker compose run --rm ingest uv run python scripts/sync_zendesk.py

# ── Admin dashboard ───────────────────────────────────────────────────────────

dashboard:
	docker compose up -d dashboard

dashboard-local:
	uv run streamlit run src/admin/dashboard/app.py

dashboard-logs:
	docker compose logs -f dashboard

# ── Local development ──────────────────────────────────────────────────────────

qdrant-only:
	docker compose -f docker-compose.qdrant.yml up -d qdrant

infra:
	docker compose -f docker-compose.qdrant.yml up -d

# ── Code quality ───────────────────────────────────────────────────────────────

lint:
	uv run ruff check . && uv run ruff format .

test:
	uv run pytest

test-unit:
	uv run pytest tests/unit/

test-int:
	uv run pytest tests/integration/
