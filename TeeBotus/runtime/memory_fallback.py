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
        self._stale_fallback_entries: set[str] = set()
        self._stale_fallback_indexes: set[str] = set()
        self.last_entry_read_error = ""
        self.last_entry_skipped = 0
        self.last_index_read_error = ""
        self.last_fallback_sync_error = ""

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
            self._copy_diagnostics(self.primary)
            if self._read_diagnostic_failed(operation):
                return self._recover_read_from_fallback(operation, account_id, callback)
            self._clear_recovered_if_clean(operation)
            return result
        except Exception as exc:  # noqa: BLE001
            self._fallback_active = True
            self._warn(operation, exc)
            result = callback(self.fallback)
            self._copy_diagnostics(self.fallback)
            return result

    def _write(self, operation: str, account_id: str, callback: Callable[[Any], Any], dirty_set: set[str]) -> None:
        try:
            callback(self.primary)
            self._copy_diagnostics(self.primary)
            dirty_set.discard(account_id)
            self._mirror_write(operation, account_id, callback)
            self._clear_recovered_if_clean(operation)
        except Exception as exc:  # noqa: BLE001
            self._fallback_active = True
            self._warn(operation, exc)
            callback(self.fallback)
            self._copy_diagnostics(self.fallback)
            dirty_set.add(account_id)
            self._fallback_stale_set(operation).discard(account_id)

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

    def _recover_read_from_fallback(self, operation: str, account_id: str, callback: Callable[[Any], Any]) -> Any:
        self._fallback_active = True
        self._warn(operation, RuntimeError(self._diagnostic_error_text(operation)))
        primary_entry_read_error = self.last_entry_read_error
        primary_entry_skipped = self.last_entry_skipped
        primary_index_read_error = self.last_index_read_error
        result = callback(self.fallback)
        self._copy_diagnostics(self.fallback)
        if self._fallback_result_is_empty_for_failed_read(operation, result, primary_entry_skipped, primary_index_read_error):
            self.last_entry_read_error = primary_entry_read_error
            self.last_entry_skipped = primary_entry_skipped
            self.last_index_read_error = primary_index_read_error
            self._fallback_stale_set(operation).add(account_id)
            self.last_fallback_sync_error = f"{operation}: fallback has no recoverable data"
            return result
        if not self._read_diagnostic_failed(operation):
            try:
                if operation == "read_entries":
                    self.primary.write_entries(account_id, result)
                    self._dirty_entries.discard(account_id)
                    self._stale_fallback_entries.discard(account_id)
                elif operation == "read_index":
                    self.primary.write_index(account_id, result)
                    self._dirty_indexes.discard(account_id)
                    self._stale_fallback_indexes.discard(account_id)
            except Exception as exc:  # noqa: BLE001
                self._fallback_stale_set(operation).add(account_id)
                self.last_fallback_sync_error = f"{operation}: primary repair failed: {exc}"
                LOGGER.critical(
                    "ACCOUNT MEMORY PRIMARY DATABASE REPAIR FROM FALLBACK FAILED. label=%s operation=%s account_id=%s error=%s.",
                    self.label,
                    operation,
                    account_id,
                    exc,
                )
            self._clear_recovered_if_clean(operation)
        return result

    def _fallback_result_is_empty_for_failed_read(
        self,
        operation: str,
        result: Any,
        primary_entry_skipped: int,
        primary_index_read_error: str,
    ) -> bool:
        if operation == "read_entries":
            return bool(primary_entry_skipped) and result == []
        if operation == "read_index":
            return bool(primary_index_read_error) and result == {}
        return False

    def _account_is_dirty(self, operation: str, account_id: str) -> bool:
        if operation == "read_entries":
            return account_id in self._dirty_entries
        if operation == "read_index":
            return account_id in self._dirty_indexes
        return False

    def _read_diagnostic_failed(self, operation: str) -> bool:
        if operation == "read_entries":
            return bool(self.last_entry_read_error or self.last_entry_skipped)
        if operation == "read_index":
            return bool(self.last_index_read_error)
        return False

    def _diagnostic_error_text(self, operation: str) -> str:
        if operation == "read_entries":
            return self.last_entry_read_error or f"skipped={self.last_entry_skipped}"
        if operation == "read_index":
            return self.last_index_read_error
        return "read diagnostic failed"

    def _clear_recovered_if_clean(self, operation: str) -> None:
        if self._dirty_entries or self._dirty_indexes:
            return
        if self._fallback_active:
            LOGGER.critical("Account-Memory primary backend recovered label=%s operation=%s. Fallback warning cleared.", self.label, operation)
        self._fallback_active = False

    def _mirror_write(self, operation: str, account_id: str, callback: Callable[[Any], Any]) -> None:
        stale_set = self._fallback_stale_set(operation)
        try:
            callback(self.fallback)
        except Exception as exc:  # noqa: BLE001
            stale_set.add(account_id)
            self.last_fallback_sync_error = f"{operation}: {exc}"
            LOGGER.critical(
                "ACCOUNT MEMORY FALLBACK DATABASE SYNC FAILED. PRIMARY DATABASE IS ACTIVE BUT FALLBACK MAY BE STALE. "
                "label=%s operation=%s account_id=%s error=%s.",
                self.label,
                operation,
                account_id,
                exc,
            )
            return
        stale_set.discard(account_id)
        if not self._stale_fallback_entries and not self._stale_fallback_indexes:
            self.last_fallback_sync_error = ""

    def _fallback_stale_set(self, operation: str) -> set[str]:
        if operation in {"write_entries", "read_entries"}:
            return self._stale_fallback_entries
        if operation in {"write_index", "read_index"}:
            return self._stale_fallback_indexes
        return set()

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

    def _copy_diagnostics(self, backend: Any) -> None:
        self.last_entry_read_error = str(getattr(backend, "last_entry_read_error", "") or "")
        self.last_entry_skipped = int(getattr(backend, "last_entry_skipped", 0) or 0)
        self.last_index_read_error = str(getattr(backend, "last_index_read_error", "") or "")

    @property
    def stale_fallback_entry_account_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._stale_fallback_entries))

    @property
    def stale_fallback_index_account_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._stale_fallback_indexes))
