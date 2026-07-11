from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from TeeBotus.runtime.accounts import AccountStoreError, InstanceSecretProvider, utc_now

LOGGER = logging.getLogger("TeeBotus")

SQLITE_BACKEND_ENV = "TEEBOTUS_ACCOUNT_MEMORY_BACKEND"
SQLITE_PATH_ENV = "TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH"
SQLITE_FALLBACK_PATH_ENV = "TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH"
SQLITE_BACKEND_TOKENS = {"sqlite", "sqlite3"}
SQLITE_DEFAULT_FILENAME = "Account_Memory.sqlite3"
SQLITE_DEFAULT_FALLBACK_FILENAME = "Account_Memory.backup.sqlite3"
SQLITE_REQUIRED_TABLES = (
    "memory_entries",
    "memory_keywords",
    "memory_indexes",
    "account_jsonl_collections",
)
SQLITE_REQUIRED_COLUMNS = {
    "memory_entries": (
        "instance_name",
        "account_id",
        "memory_id",
        "ordinal",
        "kind",
        "memory_type",
        "importance",
        "salience",
        "access_count",
        "created_at",
        "updated_at",
        "last_accessed_at",
        "payload_nonce",
        "payload_ciphertext",
    ),
    "memory_keywords": ("instance_name", "account_id", "keyword", "memory_id"),
    "memory_indexes": ("instance_name", "account_id", "payload_nonce", "payload_ciphertext", "updated_at"),
    "account_jsonl_collections": (
        "instance_name",
        "account_id",
        "collection",
        "ordinal",
        "item_key",
        "created_at",
        "updated_at",
        "payload_nonce",
        "payload_ciphertext",
    ),
}
SQLITE_READ_ENTRIES_BY_IDS_CHUNK_SIZE = 500


def validate_distinct_sqlite_paths(
    path: Path,
    fallback_path: Path | None,
    *,
    primary_label: str = SQLITE_PATH_ENV,
    fallback_label: str = SQLITE_FALLBACK_PATH_ENV,
) -> None:
    if fallback_path is None:
        return
    if path.resolve() == fallback_path.resolve():
        raise AccountStoreError(
            f"{primary_label} and {fallback_label} must point to different files"
        )
    if not path.exists() or not fallback_path.exists():
        return
    try:
        path_identity = path.stat()
        fallback_identity = fallback_path.stat()
    except OSError:
        return
    if (path_identity.st_dev, path_identity.st_ino) == (
        fallback_identity.st_dev,
        fallback_identity.st_ino,
    ):
        raise AccountStoreError(
            f"{primary_label} and {fallback_label} must not be hardlinks to the same file"
        )


@dataclass(frozen=True)
class SQLiteMemoryConfig:
    path: Path
    fallback_path: Path | None = None

    @classmethod
    def from_env(cls, root: Path, env: Mapping[str, str] | None = None) -> "SQLiteMemoryConfig | None":
        source = os.environ if env is None else env
        backend = str(source.get(SQLITE_BACKEND_ENV, "") or "").strip().casefold()
        if backend not in SQLITE_BACKEND_TOKENS:
            return None
        configured_path = str(source.get(SQLITE_PATH_ENV, "") or "").strip()
        fallback_path = str(source.get(SQLITE_FALLBACK_PATH_ENV, "") or "").strip()
        root_path = Path(root).expanduser()

        def resolve_configured_path(value: str, default_filename: str) -> Path:
            if not value:
                return root_path / default_filename
            configured = Path(value).expanduser()
            return configured if configured.is_absolute() else root_path / configured

        path = resolve_configured_path(configured_path, SQLITE_DEFAULT_FILENAME)
        resolved_fallback_path = resolve_configured_path(fallback_path, SQLITE_DEFAULT_FALLBACK_FILENAME)
        validate_distinct_sqlite_paths(path, resolved_fallback_path)
        return cls(path=path, fallback_path=resolved_fallback_path)


class SQLiteAccountMemoryBackend:
    def __init__(
        self,
        *,
        instance_name: str,
        provider: InstanceSecretProvider,
        purpose: str,
        config: SQLiteMemoryConfig,
    ) -> None:
        validate_distinct_sqlite_paths(config.path, config.fallback_path)
        self.instance_name = instance_name
        self.provider = provider
        self.purpose = purpose
        self.config = config
        self._initialized = False
        self._schema_file_identity: tuple[int, int] | None = None
        self.last_entry_read_error = ""
        self.last_entry_skipped = 0
        self.last_index_read_error = ""
        self.last_collection_read_error = ""
        self.last_collection_skipped = 0
        self.last_database_missing = False
        self._cipher_key: bytes | None = None
        self._cipher: AESGCM | None = None

    def _secondary_database_exists(self) -> bool:
        fallback_path = self.config.fallback_path
        if fallback_path is None:
            return False
        try:
            return fallback_path.expanduser().resolve() != self.config.path.expanduser().resolve() and fallback_path.exists()
        except OSError:
            return fallback_path.exists()

    def _missing_table_error(self, table: str) -> AccountStoreError:
        error = AccountStoreError(
            f"SQLite account-memory schema table is missing: {table} ({self.config.path})"
        )
        LOGGER.critical("%s", error)
        return error

    @property
    def key(self) -> bytes:
        key = self.provider.get_secret(self.instance_name, self.purpose)
        if len(key) != 32:
            raise AccountStoreError("sqlite memory encryption key has invalid length")
        return key

    @property
    def cipher(self) -> AESGCM:
        key = self.key
        if self._cipher is None or self._cipher_key != key:
            self._cipher = AESGCM(key)
            self._cipher_key = key
        return self._cipher

    def read_entries(self, account_id: str) -> list[dict[str, Any]]:
        self.last_entry_read_error = ""
        self.last_entry_skipped = 0
        self.last_database_missing = False
        if not self.config.path.exists():
            self.last_database_missing = True
            self.last_entry_read_error = str(self._missing_database_error())
            return []
        with self._connect_readonly() as connection:
            if not _table_exists(connection, "memory_entries"):
                if self._secondary_database_exists():
                    self.last_entry_read_error = str(self._missing_table_error("memory_entries"))
                return []
            rows = connection.execute(
                """
                SELECT memory_id, payload_nonce, payload_ciphertext
                FROM memory_entries
                WHERE instance_name = ? AND account_id = ?
                ORDER BY ordinal ASC, created_at ASC, memory_id ASC
                """,
                (self.instance_name, account_id),
            ).fetchall()
        entries: list[dict[str, Any]] = []
        skipped = 0
        first_skipped_id = ""
        first_error = ""
        for row in rows:
            memory_id = str(row[0])
            try:
                entries.append(self._decrypt_json(account_id, memory_id, bytes(row[1]), bytes(row[2])))
            except AccountStoreError as exc:
                skipped += 1
                if not first_skipped_id:
                    first_skipped_id = memory_id
                    first_error = str(exc)
        if skipped:
            self.last_entry_read_error = first_error
            self.last_entry_skipped = skipped
            LOGGER.critical(
                "SQLite account-memory skipped corrupt rows instance=%s account=%s skipped=%s first_memory_id=%s error=%s",
                self.instance_name,
                account_id,
                skipped,
                first_skipped_id,
                first_error,
            )
        return entries

    def read_entries_by_ids(self, account_id: str, memory_ids: Iterable[str]) -> list[dict[str, Any]]:
        self.last_entry_read_error = ""
        self.last_entry_skipped = 0
        self.last_database_missing = False
        requested_ids = list(dict.fromkeys(str(memory_id or "").strip() for memory_id in memory_ids if str(memory_id or "").strip()))
        if not requested_ids:
            return []
        if not self.config.path.exists():
            self.last_database_missing = True
            self.last_entry_read_error = str(self._missing_database_error())
            return []
        with self._connect_readonly() as connection:
            if not _table_exists(connection, "memory_entries"):
                if self._secondary_database_exists():
                    self.last_entry_read_error = str(self._missing_table_error("memory_entries"))
                return []
            rows: list[tuple[Any, ...]] = []
            for offset in range(0, len(requested_ids), SQLITE_READ_ENTRIES_BY_IDS_CHUNK_SIZE):
                chunk = requested_ids[offset : offset + SQLITE_READ_ENTRIES_BY_IDS_CHUNK_SIZE]
                placeholders = ",".join("?" for _ in chunk)
                rows.extend(
                    connection.execute(
                        f"""
                        SELECT memory_id, payload_nonce, payload_ciphertext
                        FROM memory_entries
                        WHERE instance_name = ? AND account_id = ? AND memory_id IN ({placeholders})
                        ORDER BY ordinal ASC, created_at ASC, memory_id ASC
                        """,
                        (self.instance_name, account_id, *chunk),
                    ).fetchall()
                )
        entries: list[dict[str, Any]] = []
        skipped = 0
        first_skipped_id = ""
        first_error = ""
        for row in rows:
            memory_id = str(row[0])
            try:
                entries.append(self._decrypt_json(account_id, memory_id, bytes(row[1]), bytes(row[2])))
            except AccountStoreError as exc:
                skipped += 1
                if not first_skipped_id:
                    first_skipped_id = memory_id
                    first_error = str(exc)
        if skipped:
            self.last_entry_read_error = first_error
            self.last_entry_skipped = skipped
            LOGGER.critical(
                "SQLite account-memory skipped corrupt rows instance=%s account=%s skipped=%s first_memory_id=%s error=%s",
                self.instance_name,
                account_id,
                skipped,
                first_skipped_id,
                first_error,
            )
        entries_by_id = {
            str(entry.get("id") or "").strip(): entry
            for entry in entries
            if isinstance(entry, dict) and str(entry.get("id") or "").strip()
        }
        return [entries_by_id[memory_id] for memory_id in requested_ids if memory_id in entries_by_id]

    def write_entries(self, account_id: str, rows: Iterable[dict[str, Any]]) -> None:
        self._write_entries(account_id, rows, allow_incomplete_schema=False)

    def _repair_entries_from_verified_fallback(self, account_id: str, rows: Iterable[dict[str, Any]]) -> None:
        self._write_entries(account_id, rows, allow_incomplete_schema=True)

    def _write_entries(
        self,
        account_id: str,
        rows: Iterable[dict[str, Any]],
        *,
        allow_incomplete_schema: bool,
    ) -> None:
        self._ensure_schema(allow_incomplete_schema=allow_incomplete_schema)
        normalized_rows = [dict(row) for row in rows if isinstance(row, dict)]
        with self._connect() as connection:
            with connection:
                self._guard_existing_account_payloads_decryptable(connection, account_id)
                connection.execute(
                    "DELETE FROM memory_keywords WHERE instance_name = ? AND account_id = ?",
                    (self.instance_name, account_id),
                )
                connection.execute(
                    "DELETE FROM memory_entries WHERE instance_name = ? AND account_id = ?",
                    (self.instance_name, account_id),
                )
                for ordinal, row in enumerate(normalized_rows):
                    self._insert_entry(connection, account_id, row, ordinal)

    def read_index(self, account_id: str) -> dict[str, Any]:
        self.last_index_read_error = ""
        self.last_database_missing = False
        if not self.config.path.exists():
            self.last_database_missing = True
            self.last_index_read_error = str(self._missing_database_error())
            return {}
        with self._connect_readonly() as connection:
            if not _table_exists(connection, "memory_indexes"):
                if self._secondary_database_exists():
                    self.last_index_read_error = str(self._missing_table_error("memory_indexes"))
                return {}
            row = connection.execute(
                """
                SELECT payload_nonce, payload_ciphertext
                FROM memory_indexes
                WHERE instance_name = ? AND account_id = ?
                """,
                (self.instance_name, account_id),
            ).fetchone()
        if row is None:
            return {}
        try:
            return self._decrypt_json(account_id, "index", bytes(row[0]), bytes(row[1]))
        except AccountStoreError as exc:
            self.last_index_read_error = str(exc)
            LOGGER.critical(
                "SQLite account-memory index could not be decrypted and was ignored instance=%s account=%s error=%s",
                self.instance_name,
                account_id,
                exc,
            )
            return {}

    def write_index(self, account_id: str, data: dict[str, Any]) -> None:
        self._write_index(account_id, data, allow_incomplete_schema=False)

    def _repair_index_from_verified_fallback(self, account_id: str, data: dict[str, Any]) -> None:
        self._write_index(account_id, data, allow_incomplete_schema=True)

    def _write_index(
        self,
        account_id: str,
        data: dict[str, Any],
        *,
        allow_incomplete_schema: bool,
    ) -> None:
        self._ensure_schema(allow_incomplete_schema=allow_incomplete_schema)
        nonce, ciphertext = self._encrypt_json(account_id, "index", dict(data))
        with self._connect() as connection:
            with connection:
                self._guard_existing_account_payloads_decryptable(connection, account_id)
                connection.execute(
                    """
                    INSERT INTO memory_indexes(instance_name, account_id, payload_nonce, payload_ciphertext, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(instance_name, account_id)
                    DO UPDATE SET payload_nonce = excluded.payload_nonce,
                                  payload_ciphertext = excluded.payload_ciphertext,
                                  updated_at = excluded.updated_at
                    """,
                    (self.instance_name, account_id, nonce, ciphertext, utc_now()),
                )

    def read_collection(self, account_id: str, collection: str) -> list[dict[str, Any]]:
        collection_name = _normalize_collection_name(collection)
        self.last_collection_read_error = ""
        self.last_collection_skipped = 0
        self.last_database_missing = False
        if not self.config.path.exists():
            self.last_database_missing = True
            self.last_collection_read_error = str(self._missing_database_error())
            return []
        with self._connect_readonly() as connection:
            if not _table_exists(connection, "account_jsonl_collections"):
                if self._secondary_database_exists():
                    self.last_collection_read_error = str(self._missing_table_error("account_jsonl_collections"))
                return []
            rows = connection.execute(
                """
                SELECT item_key, payload_nonce, payload_ciphertext
                FROM account_jsonl_collections
                WHERE instance_name = ? AND account_id = ? AND collection = ?
                ORDER BY ordinal ASC
                """,
                (self.instance_name, account_id, collection_name),
            ).fetchall()
        items: list[dict[str, Any]] = []
        skipped = 0
        first_skipped_id = ""
        first_error = ""
        for row in rows:
            item_key = str(row[0])
            try:
                items.append(self._decrypt_json(account_id, _collection_payload_id(collection_name, item_key), bytes(row[1]), bytes(row[2])))
            except AccountStoreError as exc:
                skipped += 1
                if not first_skipped_id:
                    first_skipped_id = item_key
                    first_error = str(exc)
        if skipped:
            self.last_collection_read_error = first_error
            self.last_collection_skipped = skipped
            LOGGER.critical(
                "SQLite account-memory skipped corrupt collection rows instance=%s account=%s collection=%s skipped=%s first_item=%s error=%s",
                self.instance_name,
                account_id,
                collection_name,
                skipped,
                first_skipped_id,
                first_error,
            )
        return items

    def write_collection(self, account_id: str, collection: str, rows: Iterable[dict[str, Any]]) -> None:
        collection_name = _normalize_collection_name(collection)
        self._write_collection(account_id, collection_name, rows, allow_incomplete_schema=False)

    def _repair_collection_from_verified_fallback(
        self,
        account_id: str,
        collection: str,
        rows: Iterable[dict[str, Any]],
    ) -> None:
        self._write_collection(account_id, collection, rows, allow_incomplete_schema=True)

    def _write_collection(
        self,
        account_id: str,
        collection_name: str,
        rows: Iterable[dict[str, Any]],
        *,
        allow_incomplete_schema: bool,
    ) -> None:
        self._ensure_schema(allow_incomplete_schema=allow_incomplete_schema)
        normalized_rows = [dict(row) for row in rows if isinstance(row, dict)]
        with self._connect() as connection:
            with connection:
                self._guard_existing_account_payloads_decryptable(connection, account_id)
                connection.execute(
                    """
                    DELETE FROM account_jsonl_collections
                    WHERE instance_name = ? AND account_id = ? AND collection = ?
                    """,
                    (self.instance_name, account_id, collection_name),
                )
                for ordinal, row in enumerate(normalized_rows):
                    self._insert_collection_item(connection, account_id, collection_name, row, ordinal)

    def append_collection_items(self, account_id: str, collection: str, rows: Iterable[dict[str, Any]]) -> None:
        collection_name = _normalize_collection_name(collection)
        self._ensure_schema()
        normalized_rows = [dict(row) for row in rows if isinstance(row, dict)]
        if not normalized_rows:
            return
        with self._connect() as connection:
            with connection:
                self._guard_account_key_sample_decryptable(connection, account_id)
                start_ordinal = connection.execute(
                    """
                    SELECT COALESCE(MAX(ordinal), -1) + 1
                    FROM account_jsonl_collections
                    WHERE instance_name = ? AND account_id = ? AND collection = ?
                    """,
                    (self.instance_name, account_id, collection_name),
                ).fetchone()[0]
                for offset, row in enumerate(normalized_rows):
                    self._insert_collection_item(connection, account_id, collection_name, row, int(start_ordinal) + offset)

    def replace_collection_item(self, account_id: str, collection: str, item_key: str, row: dict[str, Any]) -> bool:
        collection_name = _normalize_collection_name(collection)
        normalized_item_key = str(item_key or "").strip()
        if not normalized_item_key or not isinstance(row, dict):
            return False
        self._ensure_schema()
        with self._connect() as connection:
            with connection:
                existing = connection.execute(
                    """
                    SELECT ordinal, payload_nonce, payload_ciphertext
                    FROM account_jsonl_collections
                    WHERE instance_name = ? AND account_id = ? AND collection = ? AND item_key = ?
                    ORDER BY ordinal ASC
                    LIMIT 1
                    """,
                    (self.instance_name, account_id, collection_name, normalized_item_key),
                ).fetchone()
                if existing is None:
                    return False
                ordinal = int(existing[0])
                self._decrypt_json(
                    account_id,
                    _collection_payload_id(collection_name, normalized_item_key),
                    bytes(existing[1]),
                    bytes(existing[2]),
                )
                nonce, ciphertext = self._encrypt_json(account_id, _collection_payload_id(collection_name, normalized_item_key), dict(row))
                updated = connection.execute(
                    """
                    UPDATE account_jsonl_collections
                    SET created_at = ?, updated_at = ?, payload_nonce = ?, payload_ciphertext = ?
                    WHERE instance_name = ? AND account_id = ? AND collection = ? AND ordinal = ?
                    """,
                    (
                        str(row.get("created_at") or ""),
                        str(row.get("updated_at") or ""),
                        nonce,
                        ciphertext,
                        self.instance_name,
                        account_id,
                        collection_name,
                        ordinal,
                    ),
                )
                return int(updated.rowcount or 0) > 0

    def read_collection_names(self, account_id: str) -> tuple[str, ...]:
        self.last_collection_read_error = ""
        self.last_collection_skipped = 0
        self.last_database_missing = False
        if not self.config.path.exists():
            self.last_database_missing = True
            raise self._missing_database_error()
        with self._connect_readonly() as connection:
            if not _table_exists(connection, "account_jsonl_collections"):
                if self._secondary_database_exists():
                    error = self._missing_table_error("account_jsonl_collections")
                    self.last_collection_read_error = str(error)
                    raise error
                return ()
            rows = connection.execute(
                """
                SELECT DISTINCT collection
                FROM account_jsonl_collections
                WHERE instance_name = ? AND account_id = ?
                ORDER BY collection ASC
                """,
                (self.instance_name, account_id),
            ).fetchall()
        return tuple(str(row[0]) for row in rows if str(row[0] or "").strip())

    def clear_account_unchecked(self, account_id: str) -> None:
        self._ensure_schema()
        with self._connect() as connection:
            with connection:
                connection.execute(
                    "DELETE FROM memory_keywords WHERE instance_name = ? AND account_id = ?",
                    (self.instance_name, account_id),
                )
                connection.execute(
                    "DELETE FROM memory_entries WHERE instance_name = ? AND account_id = ?",
                    (self.instance_name, account_id),
                )
                connection.execute(
                    "DELETE FROM memory_indexes WHERE instance_name = ? AND account_id = ?",
                    (self.instance_name, account_id),
                )
                connection.execute(
                    "DELETE FROM account_jsonl_collections WHERE instance_name = ? AND account_id = ?",
                    (self.instance_name, account_id),
                )

    def _connect(self) -> sqlite3.Connection:
        self.config.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.config.path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _connect_readonly(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"{self.config.path.resolve().as_uri()}?mode=ro", uri=True)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _missing_database_error(self) -> AccountStoreError:
        error = AccountStoreError(f"SQLite account-memory database is missing: {self.config.path}")
        LOGGER.critical("%s", error)
        return error

    def _ensure_schema(self, *, allow_incomplete_schema: bool = False) -> None:
        self.last_database_missing = False
        existing_database = self.config.path.exists()
        if not existing_database and self._secondary_database_exists() and not allow_incomplete_schema:
            self.last_database_missing = True
            raise self._missing_database_error()
        missing_table = self._missing_schema_table() if existing_database else None
        if missing_table is not None and self._secondary_database_exists() and not allow_incomplete_schema:
            if missing_table == "<unreadable>":
                error = AccountStoreError(
                    f"SQLite account-memory schema is unreadable; refusing automatic repair while fallback exists ({self.config.path})"
                )
                LOGGER.critical("%s", error)
                raise error
            if "." in missing_table:
                error = AccountStoreError(
                    f"SQLite account-memory schema column is missing: {missing_table} ({self.config.path})"
                )
                LOGGER.critical("%s", error)
                raise error
            raise self._missing_table_error(missing_table)
        current_identity = self._database_file_identity()
        if (
            self._initialized
            and current_identity == self._schema_file_identity
            and missing_table is None
        ):
            return
        self._initialized = False
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_entries (
                    instance_name TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    memory_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL DEFAULT 0,
                    kind TEXT NOT NULL DEFAULT '',
                    memory_type TEXT NOT NULL DEFAULT '',
                    importance INTEGER NOT NULL DEFAULT 3,
                    salience INTEGER NOT NULL DEFAULT 3,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    last_accessed_at TEXT NOT NULL DEFAULT '',
                    payload_nonce BLOB NOT NULL,
                    payload_ciphertext BLOB NOT NULL,
                    PRIMARY KEY (instance_name, account_id, memory_id)
                );
                CREATE TABLE IF NOT EXISTS memory_keywords (
                    instance_name TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    keyword TEXT NOT NULL,
                    memory_id TEXT NOT NULL,
                    PRIMARY KEY (instance_name, account_id, keyword, memory_id),
                    FOREIGN KEY (instance_name, account_id, memory_id)
                        REFERENCES memory_entries(instance_name, account_id, memory_id)
                        ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS memory_indexes (
                    instance_name TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    payload_nonce BLOB NOT NULL,
                    payload_ciphertext BLOB NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (instance_name, account_id)
                );
                CREATE TABLE IF NOT EXISTS account_jsonl_collections (
                    instance_name TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    collection TEXT NOT NULL,
                    ordinal INTEGER NOT NULL DEFAULT 0,
                    item_key TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    payload_nonce BLOB NOT NULL,
                    payload_ciphertext BLOB NOT NULL,
                    PRIMARY KEY (instance_name, account_id, collection, ordinal)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_keywords_lookup ON memory_keywords(instance_name, account_id, keyword);
                CREATE INDEX IF NOT EXISTS idx_memory_entries_rank ON memory_entries(instance_name, account_id, salience, importance, access_count);
                CREATE INDEX IF NOT EXISTS idx_account_jsonl_collections_lookup ON account_jsonl_collections(instance_name, account_id, collection, item_key);
                """
            )
        self._initialized = True
        self._schema_file_identity = self._database_file_identity()

    def _schema_is_complete(self) -> bool:
        return self._missing_schema_table() is None

    def _missing_schema_table(self) -> str | None:
        try:
            with self._connect_readonly() as connection:
                for table in SQLITE_REQUIRED_TABLES:
                    if not _table_exists(connection, table):
                        return table
                    columns = {
                        str(row[1])
                        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
                    }
                    for column in SQLITE_REQUIRED_COLUMNS[table]:
                        if column not in columns:
                            return f"{table}.{column}"
        except sqlite3.Error:
            return "<unreadable>"
        return None

    def _database_file_identity(self) -> tuple[int, int] | None:
        try:
            stat_result = self.config.path.stat()
        except FileNotFoundError:
            return None
        return (int(stat_result.st_dev), int(stat_result.st_ino))

    def _insert_entry(self, connection: sqlite3.Connection, account_id: str, row: dict[str, Any], ordinal: int) -> None:
        memory_id = str(row.get("id") or f"mem_{uuid.uuid4().hex}").strip()
        row["id"] = memory_id
        nonce, ciphertext = self._encrypt_json(account_id, memory_id, row)
        connection.execute(
            """
            INSERT INTO memory_entries
            (instance_name, account_id, memory_id, ordinal, kind, memory_type, importance, salience,
             access_count, created_at, updated_at, last_accessed_at, payload_nonce, payload_ciphertext)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.instance_name,
                account_id,
                memory_id,
                ordinal,
                str(row.get("kind") or ""),
                str(row.get("memory_type") or ""),
                _int_value(row.get("importance"), 3),
                _int_value(row.get("salience"), 3),
                _int_value(row.get("access_count"), 0),
                str(row.get("created_at") or ""),
                str(row.get("updated_at") or ""),
                str(row.get("last_accessed_at") or ""),
                nonce,
                ciphertext,
            ),
        )
        keywords = row.get("keywords") if isinstance(row.get("keywords"), list) else []
        if keywords:
            connection.executemany(
                """
                INSERT OR IGNORE INTO memory_keywords(instance_name, account_id, keyword, memory_id)
                VALUES (?, ?, ?, ?)
                """,
                [(self.instance_name, account_id, str(keyword), memory_id) for keyword in keywords if str(keyword or "").strip()],
            )

    def _insert_collection_item(self, connection: sqlite3.Connection, account_id: str, collection: str, row: dict[str, Any], ordinal: int) -> None:
        item_key = _collection_item_key(row, ordinal)
        nonce, ciphertext = self._encrypt_json(account_id, _collection_payload_id(collection, item_key), row)
        connection.execute(
            """
            INSERT INTO account_jsonl_collections
            (instance_name, account_id, collection, ordinal, item_key, created_at, updated_at, payload_nonce, payload_ciphertext)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.instance_name,
                account_id,
                collection,
                ordinal,
                item_key,
                str(row.get("created_at") or ""),
                str(row.get("updated_at") or ""),
                nonce,
                ciphertext,
            ),
        )

    def _guard_existing_account_payloads_decryptable(self, connection: sqlite3.Connection, account_id: str) -> None:
        entry_rows = connection.execute(
            """
            SELECT memory_id, payload_nonce, payload_ciphertext
            FROM memory_entries
            WHERE instance_name = ? AND account_id = ?
            """,
            (self.instance_name, account_id),
        ).fetchall()
        for row in entry_rows:
            memory_id = str(row[0])
            try:
                self._decrypt_json(account_id, memory_id, bytes(row[1]), bytes(row[2]))
            except AccountStoreError as exc:
                raise AccountStoreError(
                    "existing SQLite account memory entries are not decryptable with the current key; refusing destructive write"
                ) from exc
        index_row = connection.execute(
            """
            SELECT payload_nonce, payload_ciphertext
            FROM memory_indexes
            WHERE instance_name = ? AND account_id = ?
            """,
            (self.instance_name, account_id),
        ).fetchone()
        if index_row is not None:
            try:
                self._decrypt_json(account_id, "index", bytes(index_row[0]), bytes(index_row[1]))
            except AccountStoreError as exc:
                raise AccountStoreError(
                    "existing SQLite account memory index is not decryptable with the current key; refusing destructive write"
                ) from exc
        if not _table_exists(connection, "account_jsonl_collections"):
            return
        collection_rows = connection.execute(
            """
            SELECT collection, item_key, payload_nonce, payload_ciphertext
            FROM account_jsonl_collections
            WHERE instance_name = ? AND account_id = ?
            """,
            (self.instance_name, account_id),
        ).fetchall()
        for row in collection_rows:
            collection = str(row[0])
            item_key = str(row[1])
            try:
                self._decrypt_json(account_id, _collection_payload_id(collection, item_key), bytes(row[2]), bytes(row[3]))
            except AccountStoreError as exc:
                raise AccountStoreError(
                    "existing SQLite account memory collection rows are not decryptable with the current key; refusing destructive write"
                ) from exc

    def _guard_account_key_sample_decryptable(self, connection: sqlite3.Connection, account_id: str) -> None:
        entry_row = connection.execute(
            """
            SELECT memory_id, payload_nonce, payload_ciphertext
            FROM memory_entries
            WHERE instance_name = ? AND account_id = ?
            ORDER BY ordinal ASC
            LIMIT 1
            """,
            (self.instance_name, account_id),
        ).fetchone()
        if entry_row is not None:
            try:
                self._decrypt_json(account_id, str(entry_row[0]), bytes(entry_row[1]), bytes(entry_row[2]))
            except AccountStoreError as exc:
                raise AccountStoreError("existing SQLite account memory entries are not decryptable with the current key") from exc
            return
        index_row = connection.execute(
            """
            SELECT payload_nonce, payload_ciphertext
            FROM memory_indexes
            WHERE instance_name = ? AND account_id = ?
            LIMIT 1
            """,
            (self.instance_name, account_id),
        ).fetchone()
        if index_row is not None:
            try:
                self._decrypt_json(account_id, "index", bytes(index_row[0]), bytes(index_row[1]))
            except AccountStoreError as exc:
                raise AccountStoreError("existing SQLite account memory index is not decryptable with the current key") from exc
            return
        if not _table_exists(connection, "account_jsonl_collections"):
            return
        collection_row = connection.execute(
            """
            SELECT collection, item_key, payload_nonce, payload_ciphertext
            FROM account_jsonl_collections
            WHERE instance_name = ? AND account_id = ?
            ORDER BY collection ASC, ordinal ASC
            LIMIT 1
            """,
            (self.instance_name, account_id),
        ).fetchone()
        if collection_row is None:
            return
        try:
            self._decrypt_json(
                account_id,
                _collection_payload_id(str(collection_row[0]), str(collection_row[1])),
                bytes(collection_row[2]),
                bytes(collection_row[3]),
            )
        except AccountStoreError as exc:
            raise AccountStoreError("existing SQLite account memory collection rows are not decryptable with the current key") from exc

    def _encrypt_json(self, account_id: str, memory_id: str, payload: dict[str, Any]) -> tuple[bytes, bytes]:
        nonce = os.urandom(12)
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ciphertext = self.cipher.encrypt(nonce, raw, self._aad(account_id, memory_id))
        return nonce, ciphertext

    def _decrypt_json(self, account_id: str, memory_id: str, nonce: bytes, ciphertext: bytes) -> dict[str, Any]:
        try:
            raw = self.cipher.decrypt(nonce, ciphertext, self._aad(account_id, memory_id))
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise AccountStoreError("SQLite account memory payload could not be decrypted") from exc
        if not isinstance(data, dict):
            raise AccountStoreError("SQLite account memory payload must contain an object")
        return data

    def _aad(self, account_id: str, memory_id: str) -> bytes:
        return f"TeeBotus:{self.instance_name}:{self.purpose}:{account_id}:{memory_id}:sqlite:v1".encode("utf-8")


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)).fetchone() is not None


def _normalize_collection_name(collection: str) -> str:
    value = str(collection or "").strip()
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    if not value or any(char not in allowed for char in value):
        raise AccountStoreError("SQLite account memory collection name is invalid")
    return value


def _collection_item_key(row: dict[str, Any], ordinal: int) -> str:
    for key in ("id", "item_id", "event_id", "result_id"):
        value = str(row.get(key) or "").strip()
        if value:
            return value[:240]
    return f"row_{ordinal:012d}"


def _collection_payload_id(collection: str, item_key: str) -> str:
    return f"jsonl:{collection}:{item_key}"
