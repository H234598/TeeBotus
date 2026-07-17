from __future__ import annotations

import logging
import threading
import time
from functools import wraps
from typing import Any, Callable

from TeeBotus.runtime.accounts import AccountStoreError

LOGGER = logging.getLogger("TeeBotus")
FALLBACK_WARNING_INTERVAL_SECONDS = 300


class _FallbackReadFailure(AccountStoreError):
    """Preserve a secondary-read failure across the outer primary error handler."""


def _serialize_fallback_operation(method):  # noqa: ANN001
    @wraps(method)
    def wrapped(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        with self._operation_lock:
            return method(self, *args, **kwargs)

    return wrapped


class WarningFallbackAccountMemoryBackend:
    def __init__(self, primary: Any, fallback: Any, *, label: str) -> None:
        self.primary = primary
        self.fallback = fallback
        self.label = label
        # SQLite/PostgreSQL backends expose read diagnostics as mutable fields.
        # Keep callback, diagnostic capture, and failover decision together.
        self._operation_lock = threading.RLock()
        self._fallback_active = False
        # Keep warning timestamps per account and operation so one failing
        # account cannot suppress the first warning for another account.
        self._last_warning_at: dict[tuple[str, str, str], float] = {}
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
        self._failed_collection_name_reads: set[str] = set()
        self.last_entry_read_error = ""
        self.last_entry_skipped = 0
        self.last_index_read_error = ""
        self.last_collection_read_error = ""
        self.last_collection_skipped = 0
        self.last_database_missing = False
        self.last_fallback_sync_error = ""
        self._fallback_sync_errors: dict[Any, str] = {}

    def read_entries(self, account_id: str) -> list[dict[str, Any]]:
        return self._read(
            "read_entries",
            account_id,
            lambda backend: backend.read_entries(account_id),
            self._sync_entries_from_fallback,
        )

    def read_entries_readonly(self, account_id: str) -> list[dict[str, Any]]:
        return self._read_readonly(
            "read_entries",
            account_id,
            lambda backend: self._read_backend_readonly(backend, "read_entries", account_id),
        )

    @_serialize_fallback_operation
    def read_entries_by_ids(self, account_id: str, memory_ids: list[str]) -> list[dict[str, Any]]:
        requested_ids = list(dict.fromkeys(str(memory_id or "").strip() for memory_id in memory_ids if str(memory_id or "").strip()))
        if not requested_ids:
            self.last_entry_read_error = ""
            self.last_entry_skipped = 0
            self.last_database_missing = False
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

    def read_index_readonly(self, account_id: str) -> dict[str, Any]:
        return self._read_readonly(
            "read_index",
            account_id,
            lambda backend: self._read_backend_readonly(backend, "read_index", account_id),
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
        replace_result = {"replaced": False, "primary_completed": False}

        def callback(backend: Any) -> None:
            stale_key = (account_id, collection_name)
            if (
                backend is self.fallback
                and replace_result["primary_completed"]
                and not replace_result["replaced"]
                and stale_key not in self._stale_fallback_collections
                and stale_key not in self._fallback_sync_failed_collections
            ):
                fallback_rows = self._read_clean_collection_for_mirror(self.fallback, account_id, collection_name)
                if any(str(existing.get("id") or "").strip() == normalized_item_key for existing in fallback_rows):
                    raise AccountStoreError(
                        f"write_collection:{collection_name}: fallback item {normalized_item_key!r} exists although "
                        "primary replacement was not found"
                    )
                return
            replaced = self._replace_collection_item_on_backend(backend, account_id, collection_name, normalized_item_key, dict(row))
            if backend is self.primary:
                replace_result["replaced"] = bool(replaced)
                replace_result["primary_completed"] = True
            else:
                if replace_result["primary_completed"] and replace_result["replaced"] and not replaced:
                    raise AccountStoreError(
                        f"write_collection:{collection_name}: fallback item {normalized_item_key!r} missing after primary replacement"
                    )
                if not replace_result["primary_completed"]:
                    replace_result["replaced"] = bool(replaced)

        self._write(
            f"write_collection:{collection_name}",
            account_id,
            callback,
            self._dirty_collections,
            dirty_key=(account_id, collection_name),
        )
        return bool(replace_result["replaced"])

    @_serialize_fallback_operation
    def read_collection_names(self, account_id: str) -> tuple[str, ...]:
        try:
            self._repair_cleared_fallback_account(account_id)
            if self._collection_clear_pending(account_id):
                self._fallback_active = True
                if not self.fallback_sync_error_for_account(account_id):
                    self._set_fallback_sync_error(
                        "read_collection_names",
                        account_id,
                        "read_collection_names: read blocked because fallback account clear is pending",
                    )
                raise AccountStoreError(self.fallback_sync_error_for_account(account_id) or self.last_fallback_sync_error)
            dirty_collection_names = {
                collection for item_account_id, collection in self._dirty_collections if item_account_id == account_id
            }
            name_read_repair_pending = account_id in self._failed_collection_name_reads
            name_repair_failed = False
            if dirty_collection_names or name_read_repair_pending:
                primary_names = set(getattr(self.primary, "read_collection_names")(account_id))
                fallback_names = set(getattr(self.fallback, "read_collection_names")(account_id))
                collections_to_sync = set(dirty_collection_names)
                if dirty_collection_names or name_read_repair_pending:
                    collections_to_sync.update(fallback_names - primary_names)
                for collection in sorted(collections_to_sync):
                    self._sync_collection_from_fallback(account_id, collection, force=True)
                for collection in sorted((primary_names - fallback_names) | dirty_collection_names):
                    if not self._sync_collection_to_fallback_from_primary(account_id, collection):
                        name_repair_failed = True
            names = tuple(getattr(self.primary, "read_collection_names")(account_id))
            self._copy_diagnostics(self.primary)
            if name_read_repair_pending and not name_repair_failed:
                self._failed_collection_name_reads.discard(account_id)
            self._warn_if_fallback_repair_pending("read_collection:*", account_id)
            self._clear_recovered_if_clean("read_collection_names", account_id)
            return names
        except _FallbackReadFailure:
            raise
        except Exception as exc:  # noqa: BLE001
            self._fallback_active = True
            self._warn("read_collection_names", account_id, exc)
            if self._account_has_unsafe_fallback(account_id):
                self._set_fallback_sync_error(
                    "read_collection_names",
                    account_id,
                    "read_collection_names: read blocked because primary is unavailable and fallback may be stale or unrecoverable",
                )
                LOGGER.critical(
                    "ACCOUNT MEMORY COLLECTION NAME READ BLOCKED. PRIMARY DATABASE IS UNAVAILABLE AND FALLBACK MAY BE STALE OR UNRECOVERABLE. "
                    "label=%s account_id=%s.",
                    self.label,
                    account_id,
                )
                raise AccountStoreError(self.fallback_sync_error_for_account(account_id) or self.last_fallback_sync_error) from exc
            try:
                names = tuple(getattr(self.fallback, "read_collection_names")(account_id))
                self._copy_diagnostics(self.fallback)
                can_repair_collections = callable(getattr(self.fallback, "read_collection", None)) and (
                    callable(getattr(self.primary, "_repair_collection_from_verified_fallback", None))
                    or callable(getattr(self.primary, "write_collection", None))
                )
                if not names and not name_read_repair_pending and not dirty_collection_names:
                    if can_repair_collections:
                        self._failed_collection_name_reads.add(account_id)
                        self._set_fallback_sync_error(
                            "read_collection_names",
                            account_id,
                            "read_collection_names: empty fallback collection list requires repair",
                        )
                    return names
                if can_repair_collections:
                    self._failed_collection_name_reads.add(account_id)
                    self._set_fallback_sync_error(
                        "read_collection_names",
                        account_id,
                        "read_collection_names: primary unavailable; fallback collection list requires repair",
                    )
                return names
            except Exception as fallback_exc:
                if self._backend_database_missing(self.fallback):
                    if self._backend_database_missing(self.primary):
                        self.last_database_missing = True
                        self._set_fallback_sync_error(
                            "read_collection_names",
                            account_id,
                            "read_collection_names: primary and fallback databases are not initialized",
                        )
                    else:
                        self.last_database_missing = False
                        self._set_fallback_sync_error(
                            "read_collection_names",
                            account_id,
                            "read_collection_names: fallback database is missing; no secondary data available",
                        )
                        raise _FallbackReadFailure(
                            self.fallback_sync_error_for_account(account_id) or self.last_fallback_sync_error
                        ) from fallback_exc
                    return ()
                self._failed_collection_name_reads.add(account_id)
                self._set_fallback_sync_error(
                    "read_collection_names",
                    account_id,
                    f"read_collection_names: fallback read failed: {fallback_exc}",
                )
                LOGGER.critical(
                    "ACCOUNT MEMORY FALLBACK COLLECTION-NAME READ FAILED AFTER PRIMARY FAILURE. "
                    "FAILOVER IS BLOCKED UNTIL THE SECONDARY RECOVERS. label=%s account_id=%s error=%s.",
                    self.label,
                    account_id,
                    fallback_exc,
                )
                raise _FallbackReadFailure(self.fallback_sync_error_for_account(account_id) or self.last_fallback_sync_error) from fallback_exc

    @_serialize_fallback_operation
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
            self._set_fallback_sync_error("clear_account_unchecked", account_id, f"clear_account_unchecked: {exc}")
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
        self._clear_fallback_sync_errors_for_account(account_id)
        self._failed_collection_name_reads.discard(account_id)
        self.last_entry_read_error = ""
        self.last_entry_skipped = 0
        self.last_index_read_error = ""
        self.last_collection_read_error = ""
        self.last_collection_skipped = 0
        self._clear_recovered_if_clean("clear_account_unchecked", account_id)

    @_serialize_fallback_operation
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
                try:
                    fallback_result = callback(self.fallback)
                    if read_full_for_repair is not None:
                        repair_data = read_full_for_repair(self.fallback)
                    else:
                        repair_data = fallback_result
                except Exception as fallback_exc:  # noqa: BLE001
                    self._copy_diagnostics(self.fallback)
                    stale_key = self._operation_stale_key(operation, account_id)
                    self._fallback_stale_set(operation).add(stale_key)
                    self._fallback_sync_failed_set(operation).add(stale_key)
                    self._set_fallback_sync_error(operation, account_id, f"{operation}: fallback read failed: {fallback_exc}")
                    LOGGER.critical(
                        "ACCOUNT MEMORY FALLBACK READ FAILED AFTER PRIMARY DIAGNOSTIC FAILURE. "
                        "FAILOVER IS BLOCKED UNTIL THE SECONDARY RECOVERS. label=%s operation=%s account_id=%s error=%s.",
                        self.label,
                        operation,
                        account_id,
                        fallback_exc,
                    )
                    raise _FallbackReadFailure(self.fallback_sync_error_for_account(account_id) or self.last_fallback_sync_error) from fallback_exc
                return self._recover_read_from_fallback(
                    operation,
                    account_id,
                    fallback_result,
                    repair_data,
                    partial_result=partial_result,
                )
            if read_full_for_repair is not None:
                if self._fallback_repair_pending(operation, account_id):
                    try:
                        repair_data = read_full_for_repair(self.primary)
                    except Exception as exc:  # noqa: BLE001 - do not overwrite verified fallback with a failed full read.
                        self._mark_primary_repair_read_failed(operation, account_id, str(exc))
                    else:
                        self._copy_diagnostics(self.primary)
                        if self._read_diagnostic_failed(operation):
                            self._mark_primary_repair_read_failed(operation, account_id, self._diagnostic_error_text(operation))
                        else:
                            self._repair_unrecoverable_fallback_from_primary(operation, account_id, repair_data)
            else:
                self._repair_unrecoverable_fallback_from_primary(operation, account_id, result)
            self._warn_if_fallback_repair_pending(operation, account_id)
            self._clear_recovered_if_clean(operation, account_id)
            return result
        except _FallbackReadFailure:
            raise
        except Exception as exc:  # noqa: BLE001
            self._fallback_active = True
            self._warn(operation, account_id, exc)
            if self._operation_has_unsafe_fallback(operation, account_id):
                self._set_fallback_sync_error(
                    operation,
                    account_id,
                    f"{operation}: read blocked because primary is unavailable and fallback may be stale or unrecoverable",
                )
                LOGGER.critical(
                    "ACCOUNT MEMORY READ BLOCKED. PRIMARY DATABASE IS UNAVAILABLE AND FALLBACK MAY BE STALE OR UNRECOVERABLE. "
                    "label=%s operation=%s account_id=%s.",
                    self.label,
                    operation,
                    account_id,
                )
                raise AccountStoreError(self.fallback_sync_error_for_account(account_id) or self.last_fallback_sync_error) from exc
            try:
                result = callback(self.fallback)
                self._copy_diagnostics(self.fallback)
                if self._fallback_result_is_empty_after_primary_exception(operation, result, partial_result):
                    stale_key = self._operation_stale_key(operation, account_id)
                    self._fallback_stale_set(operation).add(stale_key)
                    self._unrecoverable_fallback_set(operation).add(stale_key)
                    self._set_fallback_sync_error(operation, account_id, f"{operation}: fallback has no recoverable data")
                    return result
                if read_full_for_repair is not None:
                    recover_data = read_full_for_repair(self.fallback)
                else:
                    recover_data = result
            except Exception as fallback_exc:  # noqa: BLE001
                self._copy_diagnostics(self.fallback)
                stale_key = self._operation_stale_key(operation, account_id)
                self._fallback_stale_set(operation).add(stale_key)
                self._fallback_sync_failed_set(operation).add(stale_key)
                self._set_fallback_sync_error(operation, account_id, f"{operation}: fallback read failed: {fallback_exc}")
                LOGGER.critical(
                    "ACCOUNT MEMORY FALLBACK READ FAILED AFTER PRIMARY EXCEPTION. "
                    "FAILOVER IS BLOCKED UNTIL THE SECONDARY RECOVERS. label=%s operation=%s account_id=%s error=%s.",
                    self.label,
                    operation,
                    account_id,
                    fallback_exc,
                )
                raise AccountStoreError(self.fallback_sync_error_for_account(account_id) or self.last_fallback_sync_error) from fallback_exc
            return self._recover_read_from_fallback(
                operation,
                account_id,
                result,
                recover_data,
                partial_result=partial_result,
            )

    @staticmethod
    def _read_backend_readonly(backend: Any, operation: str, account_id: str) -> Any:
        readonly_reader = getattr(backend, f"{operation}_readonly", None)
        if callable(readonly_reader):
            return readonly_reader(account_id)
        return getattr(backend, operation)(account_id)

    @_serialize_fallback_operation
    def _read_readonly(
        self,
        operation: str,
        account_id: str,
        callback: Callable[[Any], Any],
    ) -> Any:
        try:
            result = callback(self.primary)
            self._copy_diagnostics(self.primary)
            if not self._read_diagnostic_failed(operation):
                return result
            primary_error = self._diagnostic_error_text(operation)
        except Exception as exc:  # noqa: BLE001 - status must diagnose primary failure without repairing it.
            self._copy_diagnostics(self.primary)
            self._set_readonly_primary_failure(operation, exc)
            primary_error = self._diagnostic_error_text(operation)
        self._fallback_active = True
        try:
            result = callback(self.fallback)
        except Exception as fallback_exc:  # noqa: BLE001 - preserve fail-closed fallback diagnostics.
            self._copy_diagnostics(self.fallback)
            self._fallback_stale_set(operation).add(account_id)
            self._fallback_sync_failed_set(operation).add(account_id)
            self._set_fallback_sync_error(operation, account_id, f"{operation}: fallback read failed: {fallback_exc}")
            raise AccountStoreError(self.fallback_sync_error_for_account(account_id)) from fallback_exc
        self._copy_diagnostics(self.fallback)
        if self._read_diagnostic_failed(operation):
            raise self._fallback_diagnostics_error(operation, account_id)
        self._copy_diagnostics(self.primary)
        self._set_readonly_primary_failure(operation, AccountStoreError(primary_error))
        self._fallback_stale_set(operation).add(account_id)
        self._set_fallback_sync_error(
            operation,
            account_id,
            f"{operation}: primary read failed; read-only fallback used; repair deferred: {primary_error}",
        )
        return result

    def _set_readonly_primary_failure(self, operation: str, exc: Exception) -> None:
        detail = f"{type(exc).__name__}: {exc}"
        if operation == "read_entries":
            self.last_entry_read_error = self.last_entry_read_error or detail
            self.last_entry_skipped = max(self.last_entry_skipped, 1)
        elif operation == "read_index":
            self.last_index_read_error = self.last_index_read_error or detail

    @_serialize_fallback_operation
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
                self._set_fallback_sync_error(
                    operation,
                    account_id,
                    f"{operation}: write blocked because fallback account clear is pending",
                )
                LOGGER.critical(
                    "ACCOUNT MEMORY WRITE BLOCKED. FALLBACK ACCOUNT CLEAR IS PENDING; NEW DATA MUST NOT BE WRITTEN "
                    "UNTIL THE SECONDARY RESET IS COMPLETE. label=%s operation=%s account_id=%s.",
                    self.label,
                    operation,
                    account_id,
                )
                raise AccountStoreError(self.fallback_sync_error_for_account(account_id) or self.last_fallback_sync_error)
        if self._account_has_unrecoverable_fallback(account_id):
            self._fallback_active = True
            self._set_fallback_sync_error(
                operation,
                account_id,
                f"{operation}: write blocked because primary is unreadable and fallback has no recoverable data",
            )
            LOGGER.critical(
                "ACCOUNT MEMORY WRITE BLOCKED. PRIMARY DATABASE IS UNREADABLE AND FALLBACK HAS NO RECOVERABLE DATA. "
                "label=%s operation=%s account_id=%s.",
                self.label,
                operation,
                account_id,
            )
            raise AccountStoreError(self.fallback_sync_error_for_account(account_id) or self.last_fallback_sync_error)
        try:
            callback(self.primary)
            self._copy_diagnostics(self.primary)
            dirty_set.discard(resolved_dirty_key)
            self._mirror_write(operation, account_id, callback)
            self._clear_write_diagnostics(operation)
            self._clear_recovered_if_clean(operation, account_id)
        except Exception as exc:  # noqa: BLE001
            self._fallback_active = True
            self._warn(operation, account_id, exc)
            if self._account_has_unsafe_fallback(account_id):
                self._set_fallback_sync_error(
                    operation,
                    account_id,
                    f"{operation}: write blocked because primary is unavailable and fallback may be stale or unrecoverable",
                )
                LOGGER.critical(
                    "ACCOUNT MEMORY WRITE BLOCKED. PRIMARY DATABASE IS UNAVAILABLE AND FALLBACK MAY BE STALE OR UNRECOVERABLE. "
                    "label=%s operation=%s account_id=%s.",
                    self.label,
                    operation,
                    account_id,
                )
                raise AccountStoreError(self.fallback_sync_error_for_account(account_id) or self.last_fallback_sync_error) from exc
            try:
                callback(self.fallback)
            except Exception as fallback_exc:  # noqa: BLE001
                self._copy_diagnostics(self.fallback)
                stale_set = self._fallback_stale_set(operation)
                sync_failed_set = self._fallback_sync_failed_set(operation)
                stale_set.add(resolved_dirty_key)
                sync_failed_set.add(resolved_dirty_key)
                self._set_fallback_sync_error(operation, account_id, f"{operation}: fallback write failed: {fallback_exc}")
                LOGGER.critical(
                    "ACCOUNT MEMORY FALLBACK WRITE FAILED AFTER PRIMARY FAILURE. "
                    "FAILOVER IS BLOCKED UNTIL THE SECONDARY RECOVERS. label=%s operation=%s account_id=%s error=%s.",
                    self.label,
                    operation,
                    account_id,
                    fallback_exc,
                )
                raise AccountStoreError(self.fallback_sync_error_for_account(account_id) or self.last_fallback_sync_error) from fallback_exc
            self._copy_diagnostics(self.fallback)
            self._clear_write_diagnostics(operation)
            dirty_set.add(resolved_dirty_key)
            self._fallback_stale_set(operation).discard(resolved_dirty_key)
            self._fallback_sync_failed_set(operation).discard(resolved_dirty_key)

    def _sync_entries_from_fallback(self, account_id: str) -> None:
        if account_id not in self._dirty_entries:
            return
        rows = self.fallback.read_entries(account_id)
        self._ensure_clean_fallback_read("read_entries", account_id)
        self._repair_primary_from_verified_fallback("read_entries", account_id, rows)
        self._dirty_entries.discard(account_id)

    def _sync_index_from_fallback(self, account_id: str) -> None:
        if account_id not in self._dirty_indexes:
            return
        data = self.fallback.read_index(account_id)
        self._ensure_clean_fallback_read("read_index", account_id)
        self._repair_primary_from_verified_fallback("read_index", account_id, data)
        self._dirty_indexes.discard(account_id)

    def _sync_collection_from_fallback(self, account_id: str, collection: str, *, force: bool = False) -> None:
        key = (account_id, collection)
        if not force and key not in self._dirty_collections:
            return
        rows = self.fallback.read_collection(account_id, collection)
        self._ensure_clean_fallback_read(f"read_collection:{collection}", account_id)
        self._repair_primary_from_verified_fallback(f"read_collection:{collection}", account_id, rows, collection=collection)
        self._dirty_collections.discard(key)

    def _sync_collection_to_fallback_from_primary(self, account_id: str, collection: str) -> bool:
        stale_key = (account_id, collection)
        try:
            rows = self._read_clean_collection_for_mirror(self.primary, account_id, collection)
            self.fallback.write_collection(account_id, collection, rows)
        except Exception as exc:  # noqa: BLE001 - keep primary result usable while repair remains pending.
            self._copy_diagnostics(self.fallback)
            self._stale_fallback_collections.add(stale_key)
            self._fallback_sync_failed_collections.add(stale_key)
            self._set_fallback_sync_error(
                "read_collection_names",
                account_id,
                f"read_collection_names: fallback collection repair failed: {exc}",
            )
            LOGGER.critical(
                "ACCOUNT MEMORY FALLBACK COLLECTION REPAIR FROM PRIMARY FAILED. "
                "FALLBACK REMAINS STALE UNTIL A CLEAN PRIMARY COLLECTION READ AND WRITE SUCCEEDS. "
                "label=%s account_id=%s collection=%s error=%s.",
                self.label,
                account_id,
                collection,
                exc,
            )
            return False
        self._copy_diagnostics(self.fallback)
        self._dirty_collections.discard(stale_key)
        self._stale_fallback_collections.discard(stale_key)
        self._fallback_sync_failed_collections.discard(stale_key)
        self._unrecoverable_fallback_collections.discard(stale_key)
        return True

    def _repair_primary_from_verified_fallback(
        self,
        operation: str,
        account_id: str,
        data: Any,
        *,
        collection: str | None = None,
    ) -> None:
        if operation == "read_entries":
            repair = getattr(self.primary, "_repair_entries_from_verified_fallback", None)
            if callable(repair):
                repair(account_id, data)
            else:
                self.primary.write_entries(account_id, data)
            return
        if operation == "read_index":
            repair = getattr(self.primary, "_repair_index_from_verified_fallback", None)
            if callable(repair):
                repair(account_id, data)
            else:
                self.primary.write_index(account_id, data)
            return
        if operation.startswith("read_collection:"):
            if collection is None:
                collection = self._operation_collection(operation)
            repair = getattr(self.primary, "_repair_collection_from_verified_fallback", None)
            if callable(repair):
                repair(account_id, collection, data)
            else:
                self.primary.write_collection(account_id, collection, data)

    def _ensure_clean_fallback_read(self, operation: str, account_id: str) -> None:
        self._copy_diagnostics(self.fallback)
        if not self._read_diagnostic_failed(operation):
            return
        raise self._fallback_diagnostics_error(operation, account_id)

    def _fallback_diagnostics_error(self, operation: str, account_id: str) -> AccountStoreError:
        stale_key = self._operation_stale_key(operation, account_id)
        self._fallback_stale_set(operation).add(stale_key)
        self._unrecoverable_fallback_set(operation).add(stale_key)
        self._set_fallback_sync_error(
            operation,
            account_id,
            f"{operation}: fallback data has read diagnostics; primary sync blocked",
        )
        LOGGER.critical(
            "ACCOUNT MEMORY FALLBACK DATA IS NOT CLEAN. PRIMARY PROMOTION IS BLOCKED TO PROTECT EXISTING DATA. "
            "label=%s operation=%s account_id=%s error=%s.",
            self.label,
            operation,
            account_id,
            self._diagnostic_error_text(operation),
        )
        return AccountStoreError(self.last_fallback_sync_error)

    def _recover_read_from_fallback(
        self,
        operation: str,
        account_id: str,
        result: Any,
        repair_data: Any,
        partial_result: bool = False,
    ) -> Any:
        self._fallback_active = True
        self._warn(operation, account_id, RuntimeError(self._diagnostic_error_text(operation)))
        primary_entry_read_error = self.last_entry_read_error
        primary_entry_skipped = self.last_entry_skipped
        primary_index_read_error = self.last_index_read_error
        primary_collection_read_error = self.last_collection_read_error
        primary_collection_skipped = self.last_collection_skipped
        primary_database_missing = self._backend_database_missing(self.primary)
        self._copy_diagnostics(self.fallback)
        if self._backend_database_missing(self.fallback):
            self.last_entry_read_error = primary_entry_read_error
            self.last_entry_skipped = primary_entry_skipped
            self.last_index_read_error = primary_index_read_error
            self.last_collection_read_error = primary_collection_read_error
            self.last_collection_skipped = primary_collection_skipped
            self.last_database_missing = primary_database_missing
            if primary_database_missing:
                self._clear_read_diagnostics(operation)
                self._set_fallback_sync_error(
                    operation,
                    account_id,
                    f"{operation}: primary and fallback databases are not initialized",
                )
            else:
                self._set_fallback_sync_error(
                    operation,
                    account_id,
                    f"{operation}: fallback database is missing; no secondary data available",
                )
            return result
        if self._fallback_result_is_empty_for_failed_read(
            operation,
            repair_data,
            primary_entry_read_error,
            primary_entry_skipped,
            primary_index_read_error,
            primary_collection_read_error,
            primary_collection_skipped,
        ):
            self.last_entry_read_error = primary_entry_read_error
            self.last_entry_skipped = primary_entry_skipped
            self.last_index_read_error = primary_index_read_error
            self.last_collection_read_error = primary_collection_read_error
            self.last_collection_skipped = primary_collection_skipped
            self.last_database_missing = primary_database_missing
            stale_key = self._operation_stale_key(operation, account_id)
            self._fallback_stale_set(operation).add(stale_key)
            self._unrecoverable_fallback_set(operation).add(stale_key)
            self._set_fallback_sync_error(operation, account_id, f"{operation}: fallback has no recoverable data")
            return result
        if partial_result and repair_data == []:
            stale_key = self._operation_stale_key(operation, account_id)
            self._fallback_stale_set(operation).add(stale_key)
            self._unrecoverable_fallback_set(operation).add(stale_key)
            self._set_fallback_sync_error(operation, account_id, f"{operation}: fallback has no recoverable data")
            return result
        if self._read_diagnostic_failed(operation):
            raise self._fallback_diagnostics_error(operation, account_id)
        try:
            if operation == "read_entries":
                self._repair_primary_from_verified_fallback(operation, account_id, repair_data)
                self._dirty_entries.discard(account_id)
                self._stale_fallback_entries.discard(account_id)
                self._fallback_sync_failed_entries.discard(account_id)
                self._unrecoverable_fallback_entries.discard(account_id)
            elif operation == "read_index":
                self._repair_primary_from_verified_fallback(operation, account_id, repair_data)
                self._dirty_indexes.discard(account_id)
                self._stale_fallback_indexes.discard(account_id)
                self._fallback_sync_failed_indexes.discard(account_id)
                self._unrecoverable_fallback_indexes.discard(account_id)
            elif operation.startswith("read_collection:"):
                collection = self._operation_collection(operation)
                key = (account_id, collection)
                self._repair_primary_from_verified_fallback(operation, account_id, repair_data, collection=collection)
                self._dirty_collections.discard(key)
                self._stale_fallback_collections.discard(key)
                self._fallback_sync_failed_collections.discard(key)
                self._unrecoverable_fallback_collections.discard(key)
        except Exception as exc:  # noqa: BLE001
            stale_key = self._operation_stale_key(operation, account_id)
            self._fallback_stale_set(operation).add(stale_key)
            self._fallback_sync_failed_set(operation).add(stale_key)
            self._set_fallback_sync_error(operation, account_id, f"{operation}: primary repair failed: {exc}")
            LOGGER.critical(
                "ACCOUNT MEMORY PRIMARY DATABASE REPAIR FROM FALLBACK FAILED. "
                "ACCOUNT MEMORY PRIMARY DATABASE FAILED. label=%s operation=%s account_id=%s error=%s.",
                self.label,
                operation,
                account_id,
                exc,
            )
        self._clear_recovered_if_clean(operation, account_id)
        return result

    def _fallback_result_is_empty_for_failed_read(
        self,
        operation: str,
        fallback_result: Any,
        primary_entry_read_error: str,
        primary_entry_skipped: int,
        primary_index_read_error: str,
        primary_collection_read_error: str,
        primary_collection_skipped: int,
    ) -> bool:
        if operation == "read_entries":
            return bool(primary_entry_read_error or primary_entry_skipped) and fallback_result == []
        if operation == "read_index":
            return bool(primary_index_read_error) and fallback_result == {}
        if operation.startswith("read_collection:"):
            return bool(primary_collection_read_error or primary_collection_skipped) and fallback_result == []
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
            self._set_fallback_sync_error(operation, account_id, f"{operation}: fallback repair failed: {exc}")
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

    def _mark_primary_repair_read_failed(self, operation: str, account_id: str, detail: str) -> None:
        stale_key = self._operation_stale_key(operation, account_id)
        self._fallback_active = True
        self._fallback_stale_set(operation).add(stale_key)
        self._fallback_sync_failed_set(operation).add(stale_key)
        self._set_fallback_sync_error(operation, account_id, f"{operation}: primary repair read failed: {detail}")
        LOGGER.critical(
            "ACCOUNT MEMORY FALLBACK REPAIR READ FAILED. FALLBACK REMAINS STALE UNTIL A CLEAN PRIMARY FULL READ "
            "SUCCEEDS. label=%s operation=%s account_id=%s error=%s.",
            self.label,
            operation,
            account_id,
            detail,
        )

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
            self._set_fallback_sync_error("clear_account_unchecked", account_id, f"clear_account_unchecked: {exc}")
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
        self._failed_collection_name_reads.discard(account_id)

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
        if not self._warning_due("repair", operation, account_id):
            return
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
            or account_id in self._failed_collection_name_reads
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

    def _clear_recovered_if_clean(self, operation: str, account_id: str | None = None) -> None:
        if account_id is not None:
            account_has_pending_state = self._account_has_pending_state(account_id)
            if not account_has_pending_state:
                warning_keys = [key for key in self._last_warning_at if key[2] == account_id]
                for key in warning_keys:
                    self._last_warning_at.pop(key, None)
                self._clear_fallback_sync_errors_for_account(account_id)
            elif not self._operation_has_pending_state(operation, account_id):
                self._clear_fallback_sync_error(operation, account_id)
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
            or self._failed_collection_name_reads
        ):
            return
        if self._fallback_active:
            LOGGER.critical(
                "ACCOUNT MEMORY PRIMARY DATABASE FAILED earlier; Account-Memory primary backend recovered "
                "label=%s operation=%s. Fallback warning cleared.",
                self.label,
                operation,
            )
        self._refresh_last_fallback_sync_error()
        self._fallback_active = False

    def _operation_has_pending_state(self, operation: str, account_id: str) -> bool:
        stale_key = self._operation_stale_key(operation, account_id)
        if self._account_is_dirty(operation, account_id):
            return True
        if (
            stale_key in self._fallback_stale_set(operation)
            or stale_key in self._fallback_sync_failed_set(operation)
            or stale_key in self._unrecoverable_fallback_set(operation)
        ):
            return True
        return operation == "read_collection_names" and account_id in self._failed_collection_name_reads

    def _mirror_write(self, operation: str, account_id: str, callback: Callable[[Any], Any]) -> None:
        stale_set = self._fallback_stale_set(operation)
        sync_failed_set = self._fallback_sync_failed_set(operation)
        stale_key = self._operation_stale_key(operation, account_id)
        try:
            callback(self.fallback)
        except Exception as exc:  # noqa: BLE001
            stale_set.add(stale_key)
            sync_failed_set.add(stale_key)
            self._set_fallback_sync_error(operation, account_id, f"{operation}: {exc}")
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
            self._refresh_last_fallback_sync_error()

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
            primary_rows = self._read_clean_collection_for_mirror(self.primary, account_id, collection)
            self.fallback.write_collection(account_id, collection, primary_rows)
            return
        append_collection_items = getattr(backend, "append_collection_items", None)
        if callable(append_collection_items):
            append_collection_items(account_id, collection, rows)
            return
        existing_rows = self._read_clean_collection_for_mirror(backend, account_id, collection)
        backend.write_collection(account_id, collection, existing_rows + [dict(row) for row in rows])

    def _read_clean_collection_for_mirror(self, backend: Any, account_id: str, collection: str) -> list[dict[str, Any]]:
        rows = list(backend.read_collection(account_id, collection))
        self._copy_diagnostics(backend)
        operation = f"read_collection:{collection}"
        if self._read_diagnostic_failed(operation):
            raise AccountStoreError(
                f"{operation}: source collection read has diagnostics; fallback mirror blocked: "
                f"{self._diagnostic_error_text(operation)}"
            )
        return rows

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
            primary_rows = self._read_clean_collection_for_mirror(self.primary, account_id, collection)
            self.fallback.write_collection(account_id, collection, primary_rows)
            return True
        replace_collection_item = getattr(backend, "replace_collection_item", None)
        if callable(replace_collection_item):
            return bool(replace_collection_item(account_id, collection, item_key, row))
        existing_rows = self._read_clean_collection_for_mirror(backend, account_id, collection)
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

    def _set_fallback_sync_error(self, operation: str, account_id: str, message: str) -> None:
        normalized_message = str(message or "")
        key = self._fallback_sync_error_key(operation, account_id)
        self._fallback_sync_errors[key] = normalized_message
        self.last_fallback_sync_error = normalized_message

    def _fallback_sync_error_key(self, operation: str, account_id: str) -> tuple[str, Any]:
        return operation, self._operation_stale_key(operation, account_id)

    def _refresh_last_fallback_sync_error(self) -> None:
        if self._fallback_sync_errors:
            self.last_fallback_sync_error = next(reversed(self._fallback_sync_errors.values()))
        elif not self._has_any_pending_state():
            self.last_fallback_sync_error = ""

    def _has_any_pending_state(self) -> bool:
        return bool(
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
            or self._failed_collection_name_reads
        )

    def _account_has_pending_state(self, account_id: str) -> bool:
        return bool(
            account_id in self._dirty_entries
            or account_id in self._dirty_indexes
            or account_id in self._stale_fallback_entries
            or account_id in self._stale_fallback_indexes
            or account_id in self._fallback_sync_failed_entries
            or account_id in self._fallback_sync_failed_indexes
            or account_id in self._unrecoverable_fallback_entries
            or account_id in self._unrecoverable_fallback_indexes
            or account_id in self._failed_collection_name_reads
            or any(key[0] == account_id for key in self._dirty_collections)
            or any(key[0] == account_id for key in self._stale_fallback_collections)
            or any(key[0] == account_id for key in self._fallback_sync_failed_collections)
            or any(key[0] == account_id for key in self._unrecoverable_fallback_collections)
        )

    def _clear_fallback_sync_error(self, operation: str, account_id: str) -> None:
        self._fallback_sync_errors.pop(self._fallback_sync_error_key(operation, account_id), None)
        self._refresh_last_fallback_sync_error()

    def _clear_fallback_sync_errors_for_account(self, account_id: str) -> None:
        for _operation, state_key in list(self._fallback_sync_errors):
            if state_key == account_id or (isinstance(state_key, tuple) and state_key and state_key[0] == account_id):
                self._fallback_sync_errors.pop((_operation, state_key), None)
        self._refresh_last_fallback_sync_error()

    def fallback_diagnostics_for_account(self, account_id: str) -> dict[str, Any]:
        with self._operation_lock:
            return {
                "entries": account_id in self._stale_fallback_entries,
                "index": account_id in self._stale_fallback_indexes,
                "collections": bool(
                    account_id in self._failed_collection_name_reads
                    or any(key[0] == account_id for key in self._stale_fallback_collections)
                ),
                "error": self.fallback_sync_error_for_account(account_id),
            }

    @_serialize_fallback_operation
    def fallback_sync_error_for_account(self, account_id: str) -> str:
        messages: list[str] = []
        for (_operation, state_key), message in self._fallback_sync_errors.items():
            if state_key != account_id and not (isinstance(state_key, tuple) and state_key and state_key[0] == account_id):
                continue
            if message and message not in messages:
                messages.append(message)
        if messages:
            return "; ".join(messages)
        # Keep compatibility with callers/tests that set the legacy public
        # attribute directly instead of going through the state machine.
        if not self._fallback_sync_errors and not self._has_any_pending_state():
            return self.last_fallback_sync_error
        return ""

    def _warn(self, operation: str, account_id: str, exc: Exception) -> None:
        if not self._warning_due("primary", operation, account_id):
            return
        LOGGER.critical(
            "ACCOUNT MEMORY PRIMARY DATABASE FAILED. USING FALLBACK DATABASE. label=%s operation=%s error=%s. "
            "Datenbank-Normalitaet ist NICHT hergestellt; diese Warnung wiederholt sich periodisch, bis der Primary-Backend wieder funktioniert.",
            self.label,
            operation,
            exc,
        )

    def _warning_due(self, category: str, operation: str, account_id: str) -> bool:
        now = time.monotonic()
        key = (category, operation, account_id)
        last_warning_at = self._last_warning_at.get(key, -FALLBACK_WARNING_INTERVAL_SECONDS)
        if now - last_warning_at < FALLBACK_WARNING_INTERVAL_SECONDS:
            return False
        self._last_warning_at[key] = now
        return True

    def _copy_diagnostics(self, backend: Any) -> None:
        self.last_entry_read_error = str(getattr(backend, "last_entry_read_error", "") or "")
        self.last_entry_skipped = int(getattr(backend, "last_entry_skipped", 0) or 0)
        self.last_index_read_error = str(getattr(backend, "last_index_read_error", "") or "")
        self.last_collection_read_error = str(getattr(backend, "last_collection_read_error", "") or "")
        self.last_collection_skipped = int(getattr(backend, "last_collection_skipped", 0) or 0)
        self.last_database_missing = bool(getattr(backend, "last_database_missing", False))

    def _backend_database_missing(self, backend: Any) -> bool:
        return bool(getattr(backend, "last_database_missing", False))

    def _clear_read_diagnostics(self, operation: str) -> None:
        if operation == "read_entries":
            self.last_entry_read_error = ""
            self.last_entry_skipped = 0
        elif operation == "read_index":
            self.last_index_read_error = ""
        elif operation.startswith("read_collection:"):
            self.last_collection_read_error = ""
            self.last_collection_skipped = 0

    def _clear_write_diagnostics(self, operation: str) -> None:
        self.last_database_missing = False
        if operation == "write_entries":
            self._clear_read_diagnostics("read_entries")
        elif operation == "write_index":
            self._clear_read_diagnostics("read_index")
        elif operation.startswith("write_collection:"):
            self._clear_read_diagnostics(operation.replace("write_", "read_", 1))

    @property
    @_serialize_fallback_operation
    def stale_fallback_entry_account_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._stale_fallback_entries))

    @property
    @_serialize_fallback_operation
    def stale_fallback_index_account_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._stale_fallback_indexes))

    @property
    @_serialize_fallback_operation
    def stale_fallback_collection_account_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {account_id for account_id, _collection in self._stale_fallback_collections}
                | self._failed_collection_name_reads
            )
        )
