from __future__ import annotations

import logging
import time
from typing import Any, Callable

from TeeBotus.runtime.accounts import AccountStoreError

LOGGER = logging.getLogger("TeeBotus")
FALLBACK_WARNING_INTERVAL_SECONDS = 300


class WarningFallbackAccountMemoryBackend:
    def __init__(self, primary: Any, fallback: Any, *, label: str) -> None:
        self.primary = primary
        self.fallback = fallback
        self.label = label
        self._fallback_active = False
        # ``time.monotonic()`` can be below the warning interval on a fresh
        # CI/container boot. Start far enough in the past that the first
        # primary-backend failure is never silently suppressed.
        self._last_warning_at = -FALLBACK_WARNING_INTERVAL_SECONDS
        self._dirty_entries: set[str] = set()
        self._dirty_indexes: set[str] = set()
        self._dirty_collections: set[tuple[str, str]] = set()
        self._stale_fallback_entries: set[str] = set()
        self._stale_fallback_indexes: set[str] = set()
        self._stale_fallback_collections: set[tuple[str, str]] = set()
        self._fallback_sync_failed_entries: set[str] = set()
        self._fallback_sync_failed_indexes: set[str] = set()
        self._fallback_sync_failed_collections: set[tuple[str, str]] = set()
        self._unrecoverable_fallback_entries: set[str] = set()
        self._unrecoverable_fallback_indexes: set[str] = set()
        self._unrecoverable_fallback_collections: set[tuple[str, str]] = set()
        self.last_entry_read_error = ""
        self.last_entry_skipped = 0
        self.last_index_read_error = ""
        self.last_collection_read_error = ""
        self.last_collection_skipped = 0
        self.last_fallback_sync_error = ""

    def read_entries(self, account_id: str) -> list[dict[str, Any]]:
        return self._read(
            "read_entries",
            account_id,
            lambda backend: backend.read_entries(account_id),
            self._sync_entries_from_fallback,
        )

    def read_entries_by_ids(self, account_id: str, memory_ids: list[str]) -> list[dict[str, Any]]:
        requested_ids = list(dict.fromkeys(str(memory_id or "").strip() for memory_id in memory_ids if str(memory_id or "").strip()))
        if not requested_ids:
            return []

        def callback(backend: Any) -> list[dict[str, Any]]:
            read_by_ids = getattr(backend, "read_entries_by_ids", None)
            if callable(read_by_ids):
                rows = read_by_ids(account_id, requested_ids)
            else:
                rows = backend.read_entries(account_id)
            entries_by_id = {
                str(row.get("id") or "").strip(): row
                for row in rows
                if isinstance(row, dict) and str(row.get("id") or "").strip()
            }
            return [entries_by_id[memory_id] for memory_id in requested_ids if memory_id in entries_by_id]

        def full_reader(backend: Any) -> list[dict[str, Any]]:
            return [dict(row) for row in backend.read_entries(account_id)]

        return self._read(
            "read_entries",
            account_id,
            callback,
            self._sync_entries_from_fallback,
            read_full_for_repair=full_reader,
            partial_result=True,
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

    def read_collection(self, account_id: str, collection: str) -> list[dict[str, Any]]:
        collection_name = str(collection or "").strip()
        return self._read(
            f"read_collection:{collection_name}",
            account_id,
            lambda backend: backend.read_collection(account_id, collection_name),
            lambda resolved_account_id: self._sync_collection_from_fallback(resolved_account_id, collection_name),
        )

    def write_collection(self, account_id: str, collection: str, rows: list[dict[str, Any]]) -> None:
        collection_name = str(collection or "").strip()
        self._write(
            f"write_collection:{collection_name}",
            account_id,
            lambda backend: backend.write_collection(account_id, collection_name, rows),
            self._dirty_collections,
            dirty_key=(account_id, collection_name),
        )

    def append_collection_items(self, account_id: str, collection: str, rows: list[dict[str, Any]]) -> None:
        collection_name = str(collection or "").strip()
        normalized_rows = [dict(row) for row in rows if isinstance(row, dict)]
        if not normalized_rows:
            return
        self._write(
            f"write_collection:{collection_name}",
            account_id,
            lambda backend: self._append_collection_items_on_backend(backend, account_id, collection_name, normalized_rows),
            self._dirty_collections,
            dirty_key=(account_id, collection_name),
        )

    def replace_collection_item(self, account_id: str, collection: str, item_key: str, row: dict[str, Any]) -> bool:
        collection_name = str(collection or "").strip()
        normalized_item_key = str(item_key or "").strip()
        if not collection_name or not normalized_item_key or not isinstance(row, dict):
            return False
        primary_result = {"replaced": False}

        def callback(backend: Any) -> None:
            replaced = self._replace_collection_item_on_backend(backend, account_id, collection_name, normalized_item_key, dict(row))
            if backend is self.primary:
                primary_result["replaced"] = bool(replaced)

        self._write(
            f"write_collection:{collection_name}",
            account_id,
            callback,
            self._dirty_collections,
            dirty_key=(account_id, collection_name),
        )
        return bool(primary_result["replaced"])

    def read_collection_names(self, account_id: str) -> tuple[str, ...]:
        try:
            if any(key[0] == account_id for key in self._dirty_collections):
                primary_names = set(getattr(self.primary, "read_collection_names")(account_id))
                fallback_names = set(getattr(self.fallback, "read_collection_names")(account_id))
                for collection in sorted(fallback_names - primary_names):
                    self._sync_collection_from_fallback(account_id, collection)
            names = tuple(getattr(self.primary, "read_collection_names")(account_id))
            self._repair_cleared_fallback_account(account_id)
            self._warn_if_fallback_repair_pending("read_collection:*", account_id)
            self._clear_recovered_if_clean("read_collection_names")
            return names
        except Exception as exc:  # noqa: BLE001
            self._fallback_active = True
            self._warn("read_collection_names", exc)
            if self._account_has_unsafe_fallback(account_id):
                self.last_fallback_sync_error = (
                    "read_collection_names: read blocked because primary is unavailable and fallback may be stale or unrecoverable"
                )
                LOGGER.critical(
                    "ACCOUNT MEMORY COLLECTION NAME READ BLOCKED. PRIMARY DATABASE IS UNAVAILABLE AND FALLBACK MAY BE STALE OR UNRECOVERABLE. "
                    "label=%s account_id=%s.",
                    self.label,
                    account_id,
                )
                raise AccountStoreError(self.last_fallback_sync_error) from exc
            return tuple(getattr(self.fallback, "read_collection_names")(account_id))

    def clear_account_unchecked(self, account_id: str) -> None:
        primary_clear = getattr(self.primary, "clear_account_unchecked", None)
        fallback_clear = getattr(self.fallback, "clear_account_unchecked", None)
        if not callable(primary_clear):
            raise AttributeError(f"{type(self.primary).__name__} has no clear_account_unchecked")
        if not callable(fallback_clear):
            raise AttributeError(f"{type(self.fallback).__name__} has no clear_account_unchecked")
        primary_clear(account_id)
        try:
            fallback_clear(account_id)
        except Exception as exc:  # noqa: BLE001 - a cleared primary must never fail over to uncleared data.
            self._fallback_active = True
            self._stale_fallback_entries.add(account_id)
            self._stale_fallback_indexes.add(account_id)
            self._stale_fallback_collections.add((account_id, "*"))
            self._fallback_sync_failed_entries.add(account_id)
            self._fallback_sync_failed_indexes.add(account_id)
            self._fallback_sync_failed_collections.add((account_id, "*"))
            self.last_fallback_sync_error = f"clear_account_unchecked: {exc}"
            LOGGER.critical(
                "ACCOUNT MEMORY FALLBACK CLEAR FAILED AFTER PRIMARY CLEAR. "
                "FAILOVER IS BLOCKED TO PROTECT DELETED DATA. label=%s account_id=%s error=%s.",
                self.label,
                account_id,
                exc,
            )
            raise
        self._dirty_entries.discard(account_id)
        self._dirty_indexes.discard(account_id)
        self._dirty_collections = {key for key in self._dirty_collections if key[0] != account_id}
        self._stale_fallback_entries.discard(account_id)
        self._stale_fallback_indexes.discard(account_id)
        self._stale_fallback_collections = {key for key in self._stale_fallback_collections if key[0] != account_id}
        self._fallback_sync_failed_entries.discard(account_id)
        self._fallback_sync_failed_indexes.discard(account_id)
        self._fallback_sync_failed_collections = {key for key in self._fallback_sync_failed_collections if key[0] != account_id}
        self._unrecoverable_fallback_entries.discard(account_id)
        self._unrecoverable_fallback_indexes.discard(account_id)
        self._unrecoverable_fallback_collections = {key for key in self._unrecoverable_fallback_collections if key[0] != account_id}
        self.last_entry_read_error = ""
        self.last_entry_skipped = 0
        self.last_index_read_error = ""
        self.last_collection_read_error = ""
        self.last_collection_skipped = 0
        self.last_fallback_sync_error = ""
        self._fallback_active = False

    def _read(
        self,
        operation: str,
        account_id: str,
        callback: Callable[[Any], Any],
        sync_callback: Callable[[str], Any],
        *,
        read_full_for_repair: Callable[[Any], Any] | None = None,
        partial_result: bool = False,
    ) -> Any:
        try:
            if self._account_is_dirty(operation, account_id):
                sync_callback(account_id)
            result = callback(self.primary)
            self._copy_diagnostics(self.primary)
            if self._read_diagnostic_failed(operation):
                fallback_result = callback(self.fallback)
                if read_full_for_repair is not None:
                    repair_data = read_full_for_repair(self.fallback)
                else:
                    repair_data = fallback_result
                return self._recover_read_from_fallback(
                    operation,
                    account_id,
                    fallback_result,
                    repair_data,
                    partial_result=partial_result,
                )
            if read_full_for_repair is not None:
                if self._fallback_repair_pending(operation, account_id):
                    repair_data = read_full_for_repair(self.primary)
                    self._repair_unrecoverable_fallback_from_primary(operation, account_id, repair_data)
            else:
                self._repair_unrecoverable_fallback_from_primary(operation, account_id, result)
            self._warn_if_fallback_repair_pending(operation, account_id)
            self._clear_recovered_if_clean(operation)
            return result
        except Exception as exc:  # noqa: BLE001
            self._fallback_active = True
            self._warn(operation, exc)
            if self._operation_has_unsafe_fallback(operation, account_id):
                self.last_fallback_sync_error = (
                    f"{operation}: read blocked because primary is unavailable and fallback may be stale or unrecoverable"
                )
                LOGGER.critical(
                    "ACCOUNT MEMORY READ BLOCKED. PRIMARY DATABASE IS UNAVAILABLE AND FALLBACK MAY BE STALE OR UNRECOVERABLE. "
                    "label=%s operation=%s account_id=%s.",
                    self.label,
                    operation,
                    account_id,
                )
                raise AccountStoreError(self.last_fallback_sync_error) from exc
            result = callback(self.fallback)
            self._copy_diagnostics(self.fallback)
            if self._fallback_result_is_empty_after_primary_exception(operation, result, partial_result):
                stale_key = self._operation_stale_key(operation, account_id)
                self._fallback_stale_set(operation).add(stale_key)
                self._unrecoverable_fallback_set(operation).add(stale_key)
                self.last_fallback_sync_error = f"{operation}: fallback has no recoverable data"
                return result
            if read_full_for_repair is not None:
                recover_data = read_full_for_repair(self.fallback)
            else:
                recover_data = result
            return self._recover_read_from_fallback(
                operation,
                account_id,
                result,
                recover_data,
                partial_result=partial_result,
            )

    def _write(
        self,
        operation: str,
        account_id: str,
        callback: Callable[[Any], Any],
        dirty_set: set[Any],
        *,
        dirty_key: Any | None = None,
    ) -> None:
        resolved_dirty_key = account_id if dirty_key is None else dirty_key
        if self._collection_clear_pending(account_id):
            self._repair_cleared_fallback_account(account_id)
            if self._collection_clear_pending(account_id):
                self._fallback_active = True
                self.last_fallback_sync_error = (
                    f"{operation}: write blocked because fallback account clear is pending"
                )
                LOGGER.critical(
                    "ACCOUNT MEMORY WRITE BLOCKED. FALLBACK ACCOUNT CLEAR IS PENDING; NEW DATA MUST NOT BE WRITTEN "
                    "UNTIL THE SECONDARY RESET IS COMPLETE. label=%s operation=%s account_id=%s.",
                    self.label,
                    operation,
                    account_id,
                )
                raise AccountStoreError(self.last_fallback_sync_error)
        if self._account_has_unrecoverable_fallback(account_id):
            self._fallback_active = True
            self.last_fallback_sync_error = (
                f"{operation}: write blocked because primary is unreadable and fallback has no recoverable data"
            )
            LOGGER.critical(
                "ACCOUNT MEMORY WRITE BLOCKED. PRIMARY DATABASE IS UNREADABLE AND FALLBACK HAS NO RECOVERABLE DATA. "
                "label=%s operation=%s account_id=%s.",
                self.label,
                operation,
                account_id,
            )
            raise AccountStoreError(self.last_fallback_sync_error)
        try:
            callback(self.primary)
            self._copy_diagnostics(self.primary)
            dirty_set.discard(resolved_dirty_key)
            self._mirror_write(operation, account_id, callback)
            self._clear_recovered_if_clean(operation)
        except Exception as exc:  # noqa: BLE001
            self._fallback_active = True
            self._warn(operation, exc)
            if self._account_has_unsafe_fallback(account_id):
                self.last_fallback_sync_error = (
                    f"{operation}: write blocked because primary is unavailable and fallback may be stale or unrecoverable"
                )
                LOGGER.critical(
                    "ACCOUNT MEMORY WRITE BLOCKED. PRIMARY DATABASE IS UNAVAILABLE AND FALLBACK MAY BE STALE OR UNRECOVERABLE. "
                    "label=%s operation=%s account_id=%s.",
                    self.label,
                    operation,
                    account_id,
                )
                raise AccountStoreError(self.last_fallback_sync_error) from exc
            callback(self.fallback)
            self._copy_diagnostics(self.fallback)
            dirty_set.add(resolved_dirty_key)
            self._fallback_stale_set(operation).discard(resolved_dirty_key)
            self._fallback_sync_failed_set(operation).discard(resolved_dirty_key)

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

    def _sync_collection_from_fallback(self, account_id: str, collection: str) -> None:
        key = (account_id, collection)
        if key not in self._dirty_collections:
            return
        rows = self.fallback.read_collection(account_id, collection)
        self.primary.write_collection(account_id, collection, rows)
        self._dirty_collections.discard(key)

    def _recover_read_from_fallback(
        self,
        operation: str,
        account_id: str,
        result: Any,
        repair_data: Any,
        partial_result: bool = False,
    ) -> Any:
        self._fallback_active = True
        self._warn(operation, RuntimeError(self._diagnostic_error_text(operation)))
        primary_entry_read_error = self.last_entry_read_error
        primary_entry_skipped = self.last_entry_skipped
        primary_index_read_error = self.last_index_read_error
        primary_collection_read_error = self.last_collection_read_error
        primary_collection_skipped = self.last_collection_skipped
        self._copy_diagnostics(self.fallback)
        if self._fallback_result_is_empty_for_failed_read(
            operation,
            result,
            primary_entry_skipped,
            primary_index_read_error,
            primary_collection_skipped,
            partial_result=partial_result,
        ):
            self.last_entry_read_error = primary_entry_read_error
            self.last_entry_skipped = primary_entry_skipped
            self.last_index_read_error = primary_index_read_error
            self.last_collection_read_error = primary_collection_read_error
            self.last_collection_skipped = primary_collection_skipped
            stale_key = self._operation_stale_key(operation, account_id)
            self._fallback_stale_set(operation).add(stale_key)
            self._unrecoverable_fallback_set(operation).add(stale_key)
            self.last_fallback_sync_error = f"{operation}: fallback has no recoverable data"
            return result
        if not self._read_diagnostic_failed(operation):
            try:
                if operation == "read_entries":
                    self.primary.write_entries(account_id, repair_data)
                    self._dirty_entries.discard(account_id)
                    self._stale_fallback_entries.discard(account_id)
                    self._fallback_sync_failed_entries.discard(account_id)
                    self._unrecoverable_fallback_entries.discard(account_id)
                elif operation == "read_index":
                    self.primary.write_index(account_id, repair_data)
                    self._dirty_indexes.discard(account_id)
                    self._stale_fallback_indexes.discard(account_id)
                    self._fallback_sync_failed_indexes.discard(account_id)
                    self._unrecoverable_fallback_indexes.discard(account_id)
                elif operation.startswith("read_collection:"):
                    collection = self._operation_collection(operation)
                    key = (account_id, collection)
                    self.primary.write_collection(account_id, collection, repair_data)
                    self._dirty_collections.discard(key)
                    self._stale_fallback_collections.discard(key)
                    self._fallback_sync_failed_collections.discard(key)
                    self._unrecoverable_fallback_collections.discard(key)
            except Exception as exc:  # noqa: BLE001
                self._fallback_stale_set(operation).add(self._operation_stale_key(operation, account_id))
                self.last_fallback_sync_error = f"{operation}: primary repair failed: {exc}"
                LOGGER.critical(
                    "ACCOUNT MEMORY PRIMARY DATABASE REPAIR FROM FALLBACK FAILED. "
                    "ACCOUNT MEMORY PRIMARY DATABASE FAILED. label=%s operation=%s account_id=%s error=%s.",
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
        primary_collection_skipped: int,
        partial_result: bool = False,
    ) -> bool:
        if operation == "read_entries":
            return bool(primary_entry_skipped) and result == [] and not partial_result
        if operation == "read_index":
            return bool(primary_index_read_error) and result == {}
        if operation.startswith("read_collection:"):
            return bool(primary_collection_skipped) and result == []
        return False

    def _fallback_result_is_empty_after_primary_exception(
        self,
        operation: str,
        result: Any,
        partial_result: bool = False,
    ) -> bool:
        if operation == "read_entries":
            return result == [] and not partial_result
        if operation == "read_index":
            return result == {}
        if operation.startswith("read_collection:"):
            return result == []
        return False

    def _repair_unrecoverable_fallback_from_primary(self, operation: str, account_id: str, result: Any) -> None:
        if self._collection_clear_pending(account_id):
            self._repair_cleared_fallback_account(account_id)
            return
        stale_key = self._operation_stale_key(operation, account_id)
        stale_set = self._fallback_stale_set(operation)
        sync_failed_set = self._fallback_sync_failed_set(operation)
        unrecoverable_set = self._unrecoverable_fallback_set(operation)
        if stale_key not in stale_set and stale_key not in sync_failed_set and stale_key not in unrecoverable_set:
            return
        try:
            if operation == "read_entries":
                self.fallback.write_entries(account_id, result)
            elif operation == "read_index":
                self.fallback.write_index(account_id, result)
            elif operation.startswith("read_collection:"):
                collection = self._operation_collection(operation)
                self.fallback.write_collection(account_id, collection, result)
            else:
                return
        except Exception as exc:  # noqa: BLE001
            self._fallback_stale_set(operation).add(stale_key)
            self._fallback_sync_failed_set(operation).add(stale_key)
            self.last_fallback_sync_error = f"{operation}: fallback repair failed: {exc}"
            LOGGER.critical(
                "ACCOUNT MEMORY FALLBACK DATABASE REPAIR FROM PRIMARY FAILED. label=%s operation=%s account_id=%s error=%s.",
                self.label,
                operation,
                account_id,
                exc,
            )
            return
        self._fallback_stale_set(operation).discard(stale_key)
        self._fallback_sync_failed_set(operation).discard(stale_key)
        unrecoverable_set.discard(stale_key)

    def _collection_clear_pending(self, account_id: str) -> bool:
        wildcard_key = (account_id, "*")
        return (
            wildcard_key in self._stale_fallback_collections
            or wildcard_key in self._fallback_sync_failed_collections
            or wildcard_key in self._unrecoverable_fallback_collections
        )

    def _repair_cleared_fallback_account(self, account_id: str) -> None:
        if not self._collection_clear_pending(account_id):
            return
        fallback_clear = getattr(self.fallback, "clear_account_unchecked", None)
        try:
            if not callable(fallback_clear):
                raise AttributeError(f"{type(self.fallback).__name__} has no clear_account_unchecked")
            fallback_clear(account_id)
        except Exception as exc:  # noqa: BLE001 - reset must remain fail-closed.
            self._fallback_active = True
            wildcard_key = (account_id, "*")
            self._stale_fallback_collections.add(wildcard_key)
            self._fallback_sync_failed_collections.add(wildcard_key)
            self.last_fallback_sync_error = f"clear_account_unchecked: {exc}"
            LOGGER.critical(
                "ACCOUNT MEMORY FALLBACK CLEAR RETRY FAILED. FAILOVER REMAINS BLOCKED TO PROTECT DELETED DATA. "
                "label=%s account_id=%s error=%s.",
                self.label,
                account_id,
                exc,
            )
            return
        self._dirty_entries.discard(account_id)
        self._dirty_indexes.discard(account_id)
        self._dirty_collections = {key for key in self._dirty_collections if key[0] != account_id}
        self._stale_fallback_entries.discard(account_id)
        self._stale_fallback_indexes.discard(account_id)
        self._stale_fallback_collections = {key for key in self._stale_fallback_collections if key[0] != account_id}
        self._fallback_sync_failed_entries.discard(account_id)
        self._fallback_sync_failed_indexes.discard(account_id)
        self._fallback_sync_failed_collections = {key for key in self._fallback_sync_failed_collections if key[0] != account_id}
        self._unrecoverable_fallback_entries.discard(account_id)
        self._unrecoverable_fallback_indexes.discard(account_id)
        self._unrecoverable_fallback_collections = {key for key in self._unrecoverable_fallback_collections if key[0] != account_id}

    def _fallback_repair_pending(self, operation: str, account_id: str) -> bool:
        stale_key = self._operation_stale_key(operation, account_id)
        return self._collection_clear_pending(account_id) or (
            stale_key in self._fallback_stale_set(operation)
            or stale_key in self._fallback_sync_failed_set(operation)
            or stale_key in self._unrecoverable_fallback_set(operation)
        )

    def _warn_if_fallback_repair_pending(self, operation: str, account_id: str) -> None:
        if not self._fallback_repair_pending(operation, account_id):
            return
        now = time.monotonic()
        if now - self._last_warning_at < FALLBACK_WARNING_INTERVAL_SECONDS:
            return
        self._last_warning_at = now
        LOGGER.critical(
            "ACCOUNT MEMORY FALLBACK DATABASE STILL STALE. PRIMARY DATABASE IS AVAILABLE BUT SECONDARY REPAIR IS PENDING. "
            "label=%s operation=%s account_id=%s error=%s. "
            "Diese Warnung wiederholt sich periodisch, bis der Fallback wieder synchron ist.",
            self.label,
            operation,
            account_id,
            self.last_fallback_sync_error or "repair pending",
        )

    def _account_is_dirty(self, operation: str, account_id: str) -> bool:
        if operation == "read_entries":
            return account_id in self._dirty_entries
        if operation == "read_index":
            return account_id in self._dirty_indexes
        if operation.startswith("read_collection:"):
            return (account_id, self._operation_collection(operation)) in self._dirty_collections
        return False

    def _account_has_unrecoverable_fallback(self, account_id: str) -> bool:
        return (
            account_id in self._unrecoverable_fallback_entries
            or account_id in self._unrecoverable_fallback_indexes
            or any(key[0] == account_id for key in self._unrecoverable_fallback_collections)
        )

    def _account_has_unsafe_fallback(self, account_id: str) -> bool:
        return (
            self._account_has_unrecoverable_fallback(account_id)
            or account_id in self._fallback_sync_failed_entries
            or account_id in self._fallback_sync_failed_indexes
            or any(key[0] == account_id for key in self._fallback_sync_failed_collections)
        )

    def _operation_has_unsafe_fallback(self, operation: str, account_id: str) -> bool:
        stale_key = self._operation_stale_key(operation, account_id)
        sync_failed = self._fallback_sync_failed_set(operation)
        unrecoverable = self._unrecoverable_fallback_set(operation)
        if stale_key in sync_failed or stale_key in unrecoverable:
            return True
        if operation.startswith("read_collection:"):
            wildcard_key = (account_id, "*")
            return wildcard_key in sync_failed or wildcard_key in unrecoverable
        return False

    def _read_diagnostic_failed(self, operation: str) -> bool:
        if operation == "read_entries":
            return bool(self.last_entry_read_error or self.last_entry_skipped)
        if operation == "read_index":
            return bool(self.last_index_read_error)
        if operation.startswith("read_collection:"):
            return bool(self.last_collection_read_error or self.last_collection_skipped)
        return False

    def _diagnostic_error_text(self, operation: str) -> str:
        if operation == "read_entries":
            return self.last_entry_read_error or f"skipped={self.last_entry_skipped}"
        if operation == "read_index":
            return self.last_index_read_error
        if operation.startswith("read_collection:"):
            return self.last_collection_read_error or f"skipped={self.last_collection_skipped}"
        return "read diagnostic failed"

    def _clear_recovered_if_clean(self, operation: str) -> None:
        if (
            self._dirty_entries
            or self._dirty_indexes
            or self._dirty_collections
            or self._stale_fallback_entries
            or self._stale_fallback_indexes
            or self._stale_fallback_collections
            or self._fallback_sync_failed_entries
            or self._fallback_sync_failed_indexes
            or self._fallback_sync_failed_collections
            or self._unrecoverable_fallback_entries
            or self._unrecoverable_fallback_indexes
            or self._unrecoverable_fallback_collections
        ):
            return
        if self._fallback_active:
            LOGGER.critical(
                "ACCOUNT MEMORY PRIMARY DATABASE FAILED earlier; Account-Memory primary backend recovered "
                "label=%s operation=%s. Fallback warning cleared.",
                self.label,
                operation,
            )
        self.last_fallback_sync_error = ""
        self._fallback_active = False

    def _mirror_write(self, operation: str, account_id: str, callback: Callable[[Any], Any]) -> None:
        stale_set = self._fallback_stale_set(operation)
        sync_failed_set = self._fallback_sync_failed_set(operation)
        stale_key = self._operation_stale_key(operation, account_id)
        try:
            callback(self.fallback)
        except Exception as exc:  # noqa: BLE001
            stale_set.add(stale_key)
            sync_failed_set.add(stale_key)
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
        stale_set.discard(stale_key)
        sync_failed_set.discard(stale_key)
        if not self._stale_fallback_entries and not self._stale_fallback_indexes and not self._stale_fallback_collections:
            self.last_fallback_sync_error = ""

    def _append_collection_items_on_backend(
        self,
        backend: Any,
        account_id: str,
        collection: str,
        rows: list[dict[str, Any]],
    ) -> None:
        stale_key = (account_id, collection)
        if backend is self.fallback and (
            stale_key in self._stale_fallback_collections or stale_key in self._fallback_sync_failed_collections
        ):
            self.fallback.write_collection(account_id, collection, list(self.primary.read_collection(account_id, collection)))
            return
        append_collection_items = getattr(backend, "append_collection_items", None)
        if callable(append_collection_items):
            append_collection_items(account_id, collection, rows)
            return
        existing_rows = list(backend.read_collection(account_id, collection))
        backend.write_collection(account_id, collection, existing_rows + [dict(row) for row in rows])

    def _replace_collection_item_on_backend(
        self,
        backend: Any,
        account_id: str,
        collection: str,
        item_key: str,
        row: dict[str, Any],
    ) -> bool:
        stale_key = (account_id, collection)
        if backend is self.fallback and (
            stale_key in self._stale_fallback_collections or stale_key in self._fallback_sync_failed_collections
        ):
            self.fallback.write_collection(account_id, collection, list(self.primary.read_collection(account_id, collection)))
            return True
        replace_collection_item = getattr(backend, "replace_collection_item", None)
        if callable(replace_collection_item):
            return bool(replace_collection_item(account_id, collection, item_key, row))
        existing_rows = list(backend.read_collection(account_id, collection))
        replaced = False
        for index, existing in enumerate(existing_rows):
            if not isinstance(existing, dict):
                continue
            if str(existing.get("id") or "").strip() != item_key:
                continue
            existing_rows[index] = dict(row)
            replaced = True
            break
        if replaced:
            backend.write_collection(account_id, collection, existing_rows)
        return replaced

    def _fallback_stale_set(self, operation: str) -> set[Any]:
        if operation in {"write_entries", "read_entries"}:
            return self._stale_fallback_entries
        if operation in {"write_index", "read_index"}:
            return self._stale_fallback_indexes
        if operation.startswith("write_collection:") or operation.startswith("read_collection:"):
            return self._stale_fallback_collections
        return set()

    def _fallback_sync_failed_set(self, operation: str) -> set[Any]:
        if operation in {"write_entries", "read_entries"}:
            return self._fallback_sync_failed_entries
        if operation in {"write_index", "read_index"}:
            return self._fallback_sync_failed_indexes
        if operation.startswith("write_collection:") or operation.startswith("read_collection:"):
            return self._fallback_sync_failed_collections
        return set()

    def _unrecoverable_fallback_set(self, operation: str) -> set[Any]:
        if operation in {"write_entries", "read_entries"}:
            return self._unrecoverable_fallback_entries
        if operation in {"write_index", "read_index"}:
            return self._unrecoverable_fallback_indexes
        if operation.startswith("write_collection:") or operation.startswith("read_collection:"):
            return self._unrecoverable_fallback_collections
        return set()

    def _operation_collection(self, operation: str) -> str:
        return operation.split(":", 1)[1] if ":" in operation else ""

    def _operation_stale_key(self, operation: str, account_id: str) -> Any:
        if operation.startswith("write_collection:") or operation.startswith("read_collection:"):
            return (account_id, self._operation_collection(operation))
        return account_id

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
        self.last_collection_read_error = str(getattr(backend, "last_collection_read_error", "") or "")
        self.last_collection_skipped = int(getattr(backend, "last_collection_skipped", 0) or 0)

    @property
    def stale_fallback_entry_account_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._stale_fallback_entries))

    @property
    def stale_fallback_index_account_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._stale_fallback_indexes))

    @property
    def stale_fallback_collection_account_ids(self) -> tuple[str, ...]:
        return tuple(sorted({account_id for account_id, _collection in self._stale_fallback_collections}))
