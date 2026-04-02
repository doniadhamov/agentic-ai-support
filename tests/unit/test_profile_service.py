"""Unit tests for ZendeskProfileService — display name resolution and cache behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.escalation.profile_service import ZendeskProfileService


# ---------------------------------------------------------------------------
# resolve_display_name
# ---------------------------------------------------------------------------


class TestResolveDisplayName:
    def test_first_and_last_name(self) -> None:
        assert (
            ZendeskProfileService.resolve_display_name("John", "Doe", "johndoe", 123) == "John Doe"
        )

    def test_first_name_only(self) -> None:
        assert ZendeskProfileService.resolve_display_name("John", None, "johndoe", 123) == "John"

    def test_username_fallback(self) -> None:
        assert ZendeskProfileService.resolve_display_name(None, None, "johndoe", 123) == "johndoe"

    def test_telegram_user_id_fallback(self) -> None:
        assert (
            ZendeskProfileService.resolve_display_name(None, None, None, 123) == "telegram_user_123"
        )

    def test_empty_strings_fall_through(self) -> None:
        assert ZendeskProfileService.resolve_display_name("", "", "", 42) == "telegram_user_42"

    def test_whitespace_stripped(self) -> None:
        assert ZendeskProfileService.resolve_display_name("  John  ", "  ", None, 1) == "John"


# ---------------------------------------------------------------------------
# get_or_create_zendesk_user — cache hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_returns_zendesk_user_id() -> None:
    zendesk_client = AsyncMock()
    service = ZendeskProfileService(zendesk_client=zendesk_client)

    cached = MagicMock()
    cached.zendesk_user_id = 50184591324691

    with patch(
        "src.escalation.profile_service.get_zendesk_user_by_telegram_id",
        new_callable=AsyncMock,
        return_value=cached,
    ):
        result = await service.get_or_create_zendesk_user(
            telegram_user_id=1901442684,
            display_name="Doniyor A",
        )

    assert result == 50184591324691
    zendesk_client.create_or_update_profile.assert_not_awaited()


# ---------------------------------------------------------------------------
# get_or_create_zendesk_user — cache miss
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_miss_calls_profiles_api() -> None:
    zendesk_client = AsyncMock()
    zendesk_client.create_or_update_profile = AsyncMock(
        return_value={
            "id": "01KME30Z8QWFGC5PFBC54RJ8R5",
            "user_id": "50184591324691",
            "source": "telegram",
            "type": "customer",
            "name": "Doniyor A",
        }
    )

    service = ZendeskProfileService(zendesk_client=zendesk_client)

    with (
        patch(
            "src.escalation.profile_service.get_zendesk_user_by_telegram_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.escalation.profile_service.save_zendesk_user",
            new_callable=AsyncMock,
        ) as mock_save,
    ):
        result = await service.get_or_create_zendesk_user(
            telegram_user_id=1901442684,
            display_name="Doniyor A",
        )

    assert result == 50184591324691

    zendesk_client.create_or_update_profile.assert_awaited_once_with(
        name="Doniyor A",
        identifier_value="telegram_1901442684",
    )

    mock_save.assert_awaited_once_with(
        zendesk_user_id=50184591324691,
        external_id="telegram_1901442684",
        telegram_user_id=1901442684,
        zendesk_profile_id="01KME30Z8QWFGC5PFBC54RJ8R5",
        name="Doniyor A",
        role="end-user",
    )
