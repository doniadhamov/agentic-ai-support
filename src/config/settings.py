from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- Telegram ---
    telegram_bot_token: str = Field(..., description="Telegram bot token from BotFather")
    telegram_webhook_url: str = Field(
        default="", description="Webhook URL; empty = use long-polling"
    )

    # --- Anthropic ---
    anthropic_api_key: str = Field(..., description="Anthropic API key")
    anthropic_model: str = Field(default="claude-sonnet-4-6")
    anthropic_fast_model: str = Field(
        default="claude-haiku-4-5",
        description="Cheaper/faster model for classification and extraction",
    )

    # --- Google Gemini ---
    google_api_key: str = Field(..., description="Google API key for Gemini embeddings")
    gemini_embedding_model: str = Field(default="models/gemini-embedding-2-preview")
    gemini_embedding_dimensions: int = Field(
        default=3072, description="Output dimensionality for embeddings"
    )
    gemini_flash_model: str = Field(
        default="gemini-2.0-flash",
        description="Gemini Flash model for voice transcription",
    )
    max_voice_duration_seconds: int = Field(
        default=120,
        ge=1,
        le=600,
        description="Max voice message duration to transcribe (seconds)",
    )

    # --- PostgreSQL (optional — falls back to JSON/in-memory if empty) ---
    database_url: str = Field(
        default="",
        description="PostgreSQL async URL; empty = use JSON file fallback",
    )

    # --- Qdrant ---
    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_api_key: str = Field(default="")

    # --- Zendesk ---
    zendesk_subdomain: str = Field(default="support.datatruck.io")
    zendesk_api_token: str = Field(default="")
    zendesk_email: str = Field(default="")

    # --- Support Ticket API ---
    support_api_base_url: str = Field(default="")
    support_api_key: str = Field(default="")
    ticket_callback_mode: str = Field(default="poll", pattern="^(poll|webhook)$")
    ticket_poll_interval_seconds: int = Field(default=60, ge=10)

    # --- Agent Behaviour ---
    support_min_confidence_score: float = Field(default=0.75, ge=0.0, le=1.0)
    group_context_window: int = Field(default=20, ge=1, le=100)
    message_debounce_seconds: float = Field(
        default=3.0,
        ge=0.0,
        le=30.0,
        description="Base seconds to wait for additional messages from the same user",
    )
    message_debounce_max_seconds: float = Field(
        default=10.0,
        ge=0.0,
        le=60.0,
        description="Maximum total debounce wait when messages look incomplete",
    )
    rag_top_k: int = Field(default=5, ge=1, le=20)
    rag_override_min_score: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
        description="Min RAG score to override NON_SUPPORT → SUPPORT_QUESTION",
    )
    zendesk_sync_interval_hours: int = Field(default=6, ge=0)

    # --- Admin Dashboard ---
    admin_password: str = Field(default="", description="Dashboard password; empty = no auth")
    allowed_groups_file: str = Field(
        default="data/allowed_groups.json", description="Path to group allowlist JSON"
    )

    # --- Logging ---
    log_level: str = Field(default="INFO")
    log_file: str = Field(default="logs/app.log")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
