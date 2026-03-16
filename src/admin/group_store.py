"""Group allowlist store with JSON file persistence and auto-reload."""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path

from loguru import logger

from src.admin.schemas import AllowedGroup
from src.config.settings import get_settings

_RELOAD_INTERVAL_SECONDS = 5


class GroupStore:
    """Manages the set of Telegram groups allowed to use the bot.

    Persists to a JSON file and automatically reloads from disk
    when the file is modified (checked at most every 30 seconds).

    Args:
        file_path: Path to the JSON persistence file. Created automatically.
    """

    def __init__(self, file_path: str | None = None) -> None:
        self._path = Path(file_path or get_settings().allowed_groups_file)
        self._groups: dict[int, AllowedGroup] = {}
        self._allowed_ids: set[int] = set()
        self._last_mtime: float = 0.0
        self._last_check: float = 0.0
        self._load_from_disk()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_group(self, group_id: int, name: str = "") -> None:
        """Add a group to the allowlist.

        Args:
            group_id: Telegram group/supergroup chat ID.
            name: Optional human-readable name.
        """
        if group_id in self._groups:
            logger.debug("GroupStore: group_id={} already in allowlist", group_id)
            return
        group = AllowedGroup(group_id=group_id, name=name)
        self._groups[group_id] = group
        self._allowed_ids.add(group_id)
        self._save_to_disk()
        logger.info("GroupStore: added group_id={} name={!r}", group_id, name)

    def remove_group(self, group_id: int) -> None:
        """Remove a group from the allowlist.

        Args:
            group_id: Telegram group/supergroup chat ID.
        """
        if group_id not in self._groups:
            logger.warning("GroupStore: remove called for unknown group_id={}", group_id)
            return
        del self._groups[group_id]
        self._allowed_ids.discard(group_id)
        self._save_to_disk()
        logger.info("GroupStore: removed group_id={}", group_id)

    def list_groups(self) -> list[AllowedGroup]:
        """Return all allowed groups, sorted by added_at descending."""
        self._maybe_reload()
        return sorted(self._groups.values(), key=lambda g: g.added_at, reverse=True)

    def is_allowed(self, group_id: int) -> bool:
        """Check if a group is in the allowlist (sync, fast).

        Automatically reloads from disk if the file changed.
        """
        self._maybe_reload()
        return group_id in self._allowed_ids

    def has_groups(self) -> bool:
        """Return True if at least one group is in the allowlist.

        When False, the bot should accept all groups (backward-compatible).
        """
        self._maybe_reload()
        return len(self._groups) > 0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _maybe_reload(self) -> None:
        """Reload from disk if the file was modified since last check."""
        now = time.monotonic()
        if now - self._last_check < _RELOAD_INTERVAL_SECONDS:
            return
        self._last_check = now
        try:
            mtime = os.path.getmtime(self._path)
        except OSError:
            return
        if mtime > self._last_mtime:
            self._load_from_disk()

    def _save_to_disk(self) -> None:
        """Serialise current state to the JSON file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [g.model_dump(mode="json") for g in self._groups.values()]
        self._path.write_text(json.dumps(data, indent=2, default=str))
        with contextlib.suppress(OSError):
            self._last_mtime = os.path.getmtime(self._path)

    def _load_from_disk(self) -> None:
        """Deserialise groups from disk."""
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            self._groups = {}
            for item in raw:
                group = AllowedGroup.model_validate(item)
                self._groups[group.group_id] = group
            self._allowed_ids = set(self._groups.keys())
            self._last_mtime = os.path.getmtime(self._path)
            logger.info("GroupStore: loaded {} group(s) from {}", len(self._groups), self._path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("GroupStore: failed to load from disk — {}", exc)


_store: GroupStore | None = None


def get_group_store() -> GroupStore:
    """Return a module-level singleton :class:`GroupStore`."""
    global _store  # noqa: PLW0603
    if _store is None:
        _store = GroupStore()
    return _store
