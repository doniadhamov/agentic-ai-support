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

    # --- Google Gemini ---
    google_api_key: str = Field(..., description="Google API key for Gemini embeddings")
    gemini_embedding_model: str = Field(default="models/text-embedding-004")

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
    rag_top_k: int = Field(default=5, ge=1, le=20)
    zendesk_sync_interval_hours: int = Field(default=6, ge=0)

    # --- Logging ---
    log_level: str = Field(default="INFO")
    log_file: str = Field(default="logs/app.log")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
