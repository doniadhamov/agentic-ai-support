"""Unit tests for GroupStore — add/remove/list/is_allowed, persistence, reload."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.admin.group_store import GroupStore


@pytest.fixture
def store(tmp_path: Path) -> GroupStore:
    """Create a GroupStore backed by a temp JSON file."""
    return GroupStore(file_path=str(tmp_path / "groups.json"))


@pytest.fixture
def json_path(store: GroupStore) -> Path:
    return store._path


class TestGroupStore:
    def test_empty_store_has_no_groups(self, store: GroupStore) -> None:
        assert store.has_groups() is False
        assert store.list_groups() == []

    def test_add_group(self, store: GroupStore) -> None:
        store.add_group(-100123, "Test Group")
        assert store.has_groups() is True
        assert store.is_allowed(-100123) is True
        assert store.is_allowed(-999) is False

    def test_add_duplicate_group_is_noop(self, store: GroupStore) -> None:
        store.add_group(-100123, "Test Group")
        store.add_group(-100123, "Test Group Duplicate")
        assert len(store.list_groups()) == 1

    def test_remove_group(self, store: GroupStore) -> None:
        store.add_group(-100123, "Test Group")
        store.remove_group(-100123)
        assert store.has_groups() is False
        assert store.is_allowed(-100123) is False

    def test_remove_unknown_group_is_noop(self, store: GroupStore) -> None:
        store.remove_group(-999)  # should not raise

    def test_list_groups_sorted_by_added_at_desc(self, store: GroupStore) -> None:
        store.add_group(-1, "First")
        store.add_group(-2, "Second")
        groups = store.list_groups()
        assert len(groups) == 2
        # Most recently added should come first
        assert groups[0].group_id == -2

    def test_persistence_to_disk(self, store: GroupStore, json_path: Path) -> None:
        store.add_group(-100123, "Persisted Group")
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert len(data) == 1
        assert data[0]["group_id"] == -100123

    def test_load_from_disk(self, tmp_path: Path) -> None:
        json_file = tmp_path / "groups.json"
        data = [{"group_id": -100456, "name": "Loaded Group", "added_at": "2025-01-01T00:00:00"}]
        json_file.write_text(json.dumps(data))

        store = GroupStore(file_path=str(json_file))
        assert store.has_groups() is True
        assert store.is_allowed(-100456) is True

    def test_reload_picks_up_external_changes(self, tmp_path: Path) -> None:
        json_file = tmp_path / "groups.json"
        store = GroupStore(file_path=str(json_file))
        store.add_group(-1, "Original")

        # Simulate external write (e.g., from another process)
        data = [
            {"group_id": -1, "name": "Original", "added_at": "2025-01-01T00:00:00"},
            {"group_id": -2, "name": "Added Externally", "added_at": "2025-01-02T00:00:00"},
        ]
        json_file.write_text(json.dumps(data))

        # Force reload by resetting the check timer and mtime
        store._last_check = 0.0
        store._last_mtime = 0.0
        assert store.is_allowed(-2) is True

    def test_is_allowed_returns_false_for_unlisted_group(self, store: GroupStore) -> None:
        store.add_group(-100123, "Listed")
        assert store.is_allowed(-999999) is False

    def test_backward_compatible_when_empty(self, store: GroupStore) -> None:
        """When no groups are configured, has_groups() returns False."""
        assert store.has_groups() is False
