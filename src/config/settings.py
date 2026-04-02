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

    # --- PostgreSQL (required for conversation thread storage) ---
    database_url: str = Field(
        default="",
        description="PostgreSQL async URL (required for Zendesk ticket sync)",
    )

    # --- Qdrant ---
    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_api_key: str = Field(default="")

    # --- Zendesk ---
    zendesk_help_center_subdomain: str = Field(default="support.datatruck.io")
    zendesk_api_subdomain: str = Field(
        default="",
        description="Zendesk subdomain for Support Tickets API (if different from Help Center)",
    )
    zendesk_api_token: str = Field(..., description="Zendesk API token (required for ticket sync)")
    zendesk_email: str = Field(..., description="Zendesk account email (required for ticket sync)")
    zendesk_bot_user_id: int = Field(
        default=0,
        description="Zendesk user ID of the bot — used as author_id for bot comments and to filter own comments in webhook",
    )
    zendesk_admin_user_id: int = Field(
        default=0,
        description="Zendesk user ID of the API token owner — used to filter API-originated webhook comments via actor_id",
    )
    zendesk_telegram_chat_id_field_id: str = Field(
        default="",
        description="Zendesk custom field ID for storing Telegram chat ID on tickets",
    )

    # --- Agent Behaviour ---
    support_min_confidence_score: float = Field(default=0.70, ge=0.0, le=1.0)
    conversation_history_limit: int = Field(
        default=30,
        ge=1,
        le=100,
        description="Number of recent messages loaded by perceive node per group",
    )
    rag_top_k: int = Field(default=5, ge=1, le=20)
    zendesk_sync_interval_hours: int = Field(default=48, ge=0)

    @property
    def database_url_psycopg(self) -> str:
        """Convert asyncpg DATABASE_URL to psycopg format for LangGraph checkpointer."""
        url = self.database_url
        if url.startswith("postgresql+asyncpg://"):
            return url.replace("postgresql+asyncpg://", "postgresql://", 1)
        return url

    # --- Admin Dashboard ---
    admin_password: str = Field(default="", description="Dashboard password; empty = no auth")

    # --- Logging ---
    log_level: str = Field(default="INFO")
    log_file: str = Field(default="logs/app.log")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
