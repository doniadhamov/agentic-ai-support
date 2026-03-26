"""Zendesk Profiles API integration — maps Telegram users to Zendesk identities."""

from __future__ import annotations

from loguru import logger

from src.database.repositories import get_zendesk_user_by_telegram_id, save_zendesk_user
from src.escalation.ticket_client import ZendeskTicketClient


class ZendeskProfileService:
    """Resolves Telegram users to Zendesk user IDs via the Profiles API.

    Caches the mapping in the ``zendesk_users`` table to avoid redundant API calls.
    """

    def __init__(self, zendesk_client: ZendeskTicketClient) -> None:
        self._zendesk = zendesk_client

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
        # 1. Check local cache
        cached = await get_zendesk_user_by_telegram_id(telegram_user_id)
        if cached:
            logger.debug(
                "ProfileService: cache hit tg_user={} → zd_user={}",
                telegram_user_id,
                cached.zendesk_user_id,
            )
            return cached.zendesk_user_id

        # 2. Build external_id and call Zendesk
        external_id = f"telegram_{telegram_user_id}"
        profile = await self._zendesk.create_or_update_profile(
            name=display_name,
            identifier_value=external_id,
        )

        # 3. Extract IDs from response
        zendesk_user_id = int(profile["user_id"])
        zendesk_profile_id = profile.get("id")

        # 4. Cache in DB
        await save_zendesk_user(
            zendesk_user_id=zendesk_user_id,
            external_id=external_id,
            telegram_user_id=telegram_user_id,
            zendesk_profile_id=zendesk_profile_id,
            name=display_name,
            role="end-user",
        )

        logger.info(
            "ProfileService: created mapping tg_user={} → zd_user={} profile={}",
            telegram_user_id,
            zendesk_user_id,
            zendesk_profile_id,
        )
        return zendesk_user_id
