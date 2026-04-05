"""Zendesk Profiles API integration — maps Telegram users to Zendesk identities."""

from __future__ import annotations

from loguru import logger

from src.config.settings import get_settings
from src.database.repositories import (
    get_zendesk_user_by_telegram_id,
    save_zendesk_user,
    update_zendesk_user_name,
)
from src.escalation.ticket_client import ZendeskTicketClient


class ZendeskProfileService:
    """Resolves Telegram users to Zendesk user IDs via the Profiles API.

    Caches the mapping in the ``zendesk_users`` table to avoid redundant API calls.
    """

    def __init__(self, zendesk_client: ZendeskTicketClient) -> None:
        self._zendesk = zendesk_client
        # In-memory cache: telegram_user_id → (zendesk_user_id, name, external_id)
        self._cache: dict[int, tuple[int, str, str]] = {}

    @staticmethod
    def resolve_display_name(
        first_name: str | None,
        last_name: str | None,
        username: str | None,
        user_id: int,
    ) -> str:
        """Build a display name from Telegram user fields.

        Priority: "first_name last_name" → username → "telegram_user_{user_id}"
        """
        full = f"{first_name or ''} {last_name or ''}".strip()
        if full:
            return full
        if username:
            return username
        return f"telegram_user_{user_id}"

    async def get_or_create_zendesk_user(
        self,
        telegram_user_id: int,
        display_name: str,
    ) -> int:
        """Return the Zendesk user ID for a Telegram user, creating if needed.

        1. Check local DB cache
        2. If cached → return zendesk_user_id
        3. Call Zendesk Profiles API to create/update
        4. Cache locally
        5. Return zendesk_user_id
        """
        # 1. Check in-memory cache (no DB or API call)
        if telegram_user_id in self._cache:
            zendesk_id, cached_name, external_id = self._cache[telegram_user_id]
            if cached_name != display_name:
                await self._zendesk.create_or_update_profile(
                    name=display_name,
                    identifier_value=external_id,
                )
                await update_zendesk_user_name(zendesk_id, display_name)
                self._cache[telegram_user_id] = (zendesk_id, display_name, external_id)
                logger.info(
                    "ProfileService: updated name tg_user={} '{}' → '{}'",
                    telegram_user_id,
                    cached_name,
                    display_name,
                )
            return zendesk_id

        # 2. Check DB cache (first message from this user since bot started)
        cached = await get_zendesk_user_by_telegram_id(telegram_user_id)
        if cached:
            # Sync name if user changed their Telegram display name
            if cached.name != display_name:
                await self._zendesk.create_or_update_profile(
                    name=display_name,
                    identifier_value=cached.external_id,
                )
                await update_zendesk_user_name(cached.zendesk_user_id, display_name)
                logger.info(
                    "ProfileService: updated name tg_user={} '{}' → '{}'",
                    telegram_user_id,
                    cached.name,
                    display_name,
                )
            self._cache[telegram_user_id] = (
                cached.zendesk_user_id,
                display_name,
                cached.external_id,
            )
            return cached.zendesk_user_id

        # 3. Build external_id and call Zendesk Profiles API
        external_id = f"telegram_{telegram_user_id}"
        profile = await self._zendesk.create_or_update_profile(
            name=display_name,
            identifier_value=external_id,
        )

        # 4. Extract IDs from response
        zendesk_user_id = int(profile["user_id"])
        zendesk_profile_id = profile.get("id")

        # 5. Cache in DB
        await save_zendesk_user(
            zendesk_user_id=zendesk_user_id,
            external_id=external_id,
            telegram_user_id=telegram_user_id,
            zendesk_profile_id=zendesk_profile_id,
            name=display_name,
            role="end-user",
        )

        self._cache[telegram_user_id] = (zendesk_user_id, display_name, external_id)

        logger.info(
            "ProfileService: created mapping tg_user={} → zd_user={} profile={}",
            telegram_user_id,
            zendesk_user_id,
            zendesk_profile_id,
        )
        return zendesk_user_id

    async def resolve_bot_zendesk_user_id(
        self,
        bot_telegram_id: int,
        bot_name: str,
    ) -> int:
        """Resolve the Zendesk user ID for the Telegram bot itself.

        Resolution order:
        1. ``ZENDESK_BOT_USER_ID`` env var (if non-zero)
        2. Local DB cache (``zendesk_users`` table by bot's Telegram ID)
        3. Create via Zendesk Profiles API and cache in DB

        Returns:
            The bot's Zendesk user ID.
        """
        # 1. Check env var
        settings = get_settings()
        if settings.zendesk_bot_user_id:
            logger.info(
                "ProfileService: bot Zendesk user ID from env → {}",
                settings.zendesk_bot_user_id,
            )
            return settings.zendesk_bot_user_id

        # 2. Check DB cache
        cached = await get_zendesk_user_by_telegram_id(bot_telegram_id)
        if cached:
            logger.info(
                "ProfileService: bot Zendesk user ID from DB → {}",
                cached.zendesk_user_id,
            )
            return cached.zendesk_user_id

        # 3. Create via Profiles API
        external_id = f"telegram_{bot_telegram_id}"
        profile = await self._zendesk.create_or_update_profile(
            name=bot_name,
            identifier_value=external_id,
        )

        zendesk_user_id = int(profile["user_id"])
        zendesk_profile_id = profile.get("id")

        await save_zendesk_user(
            zendesk_user_id=zendesk_user_id,
            external_id=external_id,
            telegram_user_id=bot_telegram_id,
            zendesk_profile_id=zendesk_profile_id,
            name=bot_name,
            role="bot",
        )

        logger.info(
            "ProfileService: created bot Zendesk profile tg_bot={} → zd_user={} profile={}",
            bot_telegram_id,
            zendesk_user_id,
            zendesk_profile_id,
        )
        return zendesk_user_id
