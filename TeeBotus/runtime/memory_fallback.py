from __future__ import annotations

import logging
import time
from typing import Any, Callable

LOGGER = logging.getLogger("TeeBotus")
FALLBACK_WARNING_INTERVAL_SECONDS = 300


class WarningFallbackAccountMemoryBackend:
    def __init__(self, primary: Any, fallback: Any, *, label: str) -> None:
        self.primary = primary
        self.fallback = fallback
        self.label = label
        self._fallback_active = False
        self._last_warning_at = 0.0
        self._dirty_entries: set[str] = set()
        self._dirty_indexes: set[str] = set()

    def read_entries(self, account_id: str) -> list[dict[str, Any]]:
        return self._read(
            "read_entries",
            account_id,
            lambda backend: backend.read_entries(account_id),
            self._sync_entries_from_fallback,
        )

    def write_entries(self, account_id: str, rows: list[dict[str, Any]]) -> None:
        self._write(
            "write_entries",
            account_id,
            lambda backend: backend.write_entries(account_id, rows),
            self._dirty_entries,
        )

    def read_index(self, account_id: str) -> dict[str, Any]:
        return self._read(
            "read_index",
            account_id,
            lambda backend: backend.read_index(account_id),
            self._sync_index_from_fallback,
        )

    def write_index(self, account_id: str, data: dict[str, Any]) -> None:
        self._write(
            "write_index",
            account_id,
            lambda backend: backend.write_index(account_id, data),
            self._dirty_indexes,
        )

    def _read(self, operation: str, account_id: str, callback: Callable[[Any], Any], sync_callback: Callable[[str], Any]) -> Any:
        try:
            if self._account_is_dirty(operation, account_id):
                sync_callback(account_id)
            result = callback(self.primary)
            self._clear_recovered_if_clean(operation)
            return result
        except Exception as exc:  # noqa: BLE001
            self._fallback_active = True
            self._warn(operation, exc)
            return callback(self.fallback)

    def _write(self, operation: str, account_id: str, callback: Callable[[Any], Any], dirty_set: set[str]) -> None:
        try:
            callback(self.primary)
            dirty_set.discard(account_id)
            self._clear_recovered_if_clean(operation)
        except Exception as exc:  # noqa: BLE001
            self._fallback_active = True
            self._warn(operation, exc)
            callback(self.fallback)
            dirty_set.add(account_id)

    def _sync_entries_from_fallback(self, account_id: str) -> None:
        if account_id not in self._dirty_entries:
            return
        rows = self.fallback.read_entries(account_id)
        self.primary.write_entries(account_id, rows)
        self._dirty_entries.discard(account_id)

    def _sync_index_from_fallback(self, account_id: str) -> None:
        if account_id not in self._dirty_indexes:
            return
        data = self.fallback.read_index(account_id)
        self.primary.write_index(account_id, data)
        self._dirty_indexes.discard(account_id)

    def _account_is_dirty(self, operation: str, account_id: str) -> bool:
        if operation == "read_entries":
            return account_id in self._dirty_entries
        if operation == "read_index":
            return account_id in self._dirty_indexes
        return False

    def _clear_recovered_if_clean(self, operation: str) -> None:
        if self._dirty_entries or self._dirty_indexes:
            return
        if self._fallback_active:
            LOGGER.critical("Account-Memory primary backend recovered label=%s operation=%s. Fallback warning cleared.", self.label, operation)
        self._fallback_active = False

    def _warn(self, operation: str, exc: Exception) -> None:
        now = time.monotonic()
        if now - self._last_warning_at < FALLBACK_WARNING_INTERVAL_SECONDS:
            return
        self._last_warning_at = now
        LOGGER.critical(
            "ACCOUNT MEMORY PRIMARY DATABASE FAILED. USING FALLBACK DATABASE. label=%s operation=%s error=%s. "
            "Datenbank-Normalitaet ist NICHT hergestellt; diese Warnung wiederholt sich periodisch, bis der Primary-Backend wieder funktioniert.",
            self.label,
            operation,
            exc,
        )
