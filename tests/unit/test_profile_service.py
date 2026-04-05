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
# get_or_create_zendesk_user — in-memory cache hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_cache_hit_skips_db() -> None:
    zendesk_client = AsyncMock()
    service = ZendeskProfileService(zendesk_client=zendesk_client)
    service._cache[100001] = (99900001, "Alice Smith", "telegram_100001")

    with patch(
        "src.escalation.profile_service.get_zendesk_user_by_telegram_id",
        new_callable=AsyncMock,
    ) as mock_db:
        result = await service.get_or_create_zendesk_user(
            telegram_user_id=100001,
            display_name="Alice Smith",
        )

    assert result == 99900001
    mock_db.assert_not_awaited()
    zendesk_client.create_or_update_profile.assert_not_awaited()


@pytest.mark.asyncio
async def test_memory_cache_hit_syncs_changed_name() -> None:
    zendesk_client = AsyncMock()
    service = ZendeskProfileService(zendesk_client=zendesk_client)
    service._cache[100001] = (99900001, "Alice Smith", "telegram_100001")

    with patch(
        "src.escalation.profile_service.update_zendesk_user_name",
        new_callable=AsyncMock,
    ) as mock_update_name:
        result = await service.get_or_create_zendesk_user(
            telegram_user_id=100001,
            display_name="Alice Johnson",
        )

    assert result == 99900001
    zendesk_client.create_or_update_profile.assert_awaited_once_with(
        name="Alice Johnson",
        identifier_value="telegram_100001",
    )
    mock_update_name.assert_awaited_once_with(99900001, "Alice Johnson")
    # Verify in-memory cache was updated
    assert service._cache[100001] == (99900001, "Alice Johnson", "telegram_100001")


# ---------------------------------------------------------------------------
# get_or_create_zendesk_user — DB cache hit (populates in-memory cache)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_cache_hit_populates_memory_cache() -> None:
    zendesk_client = AsyncMock()
    service = ZendeskProfileService(zendesk_client=zendesk_client)

    cached = MagicMock()
    cached.zendesk_user_id = 99900001
    cached.name = "Alice Smith"
    cached.external_id = "telegram_100001"

    with patch(
        "src.escalation.profile_service.get_zendesk_user_by_telegram_id",
        new_callable=AsyncMock,
        return_value=cached,
    ):
        result = await service.get_or_create_zendesk_user(
            telegram_user_id=100001,
            display_name="Alice Smith",
        )

    assert result == 99900001
    assert service._cache[100001] == (99900001, "Alice Smith", "telegram_100001")
    zendesk_client.create_or_update_profile.assert_not_awaited()


@pytest.mark.asyncio
async def test_db_cache_hit_syncs_changed_name() -> None:
    zendesk_client = AsyncMock()
    service = ZendeskProfileService(zendesk_client=zendesk_client)

    cached = MagicMock()
    cached.zendesk_user_id = 99900001
    cached.name = "Alice Smith"
    cached.external_id = "telegram_100001"

    with (
        patch(
            "src.escalation.profile_service.get_zendesk_user_by_telegram_id",
            new_callable=AsyncMock,
            return_value=cached,
        ),
        patch(
            "src.escalation.profile_service.update_zendesk_user_name",
            new_callable=AsyncMock,
        ) as mock_update_name,
    ):
        result = await service.get_or_create_zendesk_user(
            telegram_user_id=100001,
            display_name="Alice Johnson",
        )

    assert result == 99900001
    zendesk_client.create_or_update_profile.assert_awaited_once_with(
        name="Alice Johnson",
        identifier_value="telegram_100001",
    )
    mock_update_name.assert_awaited_once_with(99900001, "Alice Johnson")
    # In-memory cache stores the NEW name
    assert service._cache[100001] == (99900001, "Alice Johnson", "telegram_100001")


# ---------------------------------------------------------------------------
# get_or_create_zendesk_user — cache miss
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_miss_calls_profiles_api() -> None:
    zendesk_client = AsyncMock()
    zendesk_client.create_or_update_profile = AsyncMock(
        return_value={
            "id": "fake_profile_id_001",
            "user_id": "99900002",
            "source": "telegram",
            "type": "customer",
            "name": "Bob Wilson",
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
            telegram_user_id=100002,
            display_name="Bob Wilson",
        )

    assert result == 99900002

    zendesk_client.create_or_update_profile.assert_awaited_once_with(
        name="Bob Wilson",
        identifier_value="telegram_100002",
    )

    mock_save.assert_awaited_once_with(
        zendesk_user_id=99900002,
        external_id="telegram_100002",
        telegram_user_id=100002,
        zendesk_profile_id="fake_profile_id_001",
        name="Bob Wilson",
        role="end-user",
    )

    # Verify in-memory cache was populated
    assert service._cache[100002] == (99900002, "Bob Wilson", "telegram_100002")
