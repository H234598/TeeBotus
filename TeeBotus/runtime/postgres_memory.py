from __future__ import annotations

import logging
import os
import threading
import uuid
from dataclasses import dataclass
from functools import wraps
from typing import Any, Iterable, Mapping

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from TeeBotus.runtime.accounts import AccountStoreError, InstanceSecretProvider, utc_now

POSTGRES_BACKEND_ENV = "TEEBOTUS_ACCOUNT_MEMORY_BACKEND"
POSTGRES_DSN_ENV = "TEEBOTUS_ACCOUNT_MEMORY_POSTGRES_DSN"
POSTGRES_CONNECT_TIMEOUT_ENV = "TEEBOTUS_ACCOUNT_MEMORY_POSTGRES_CONNECT_TIMEOUT"
POSTGRES_BACKEND_TOKENS = {"postgres", "postgresql", "pg"}
POSTGRES_READ_ENTRIES_BY_IDS_CHUNK_SIZE = 500
LOGGER = logging.getLogger("TeeBotus")
_SCHEMA_INIT_LOCK = threading.RLock()


def _retry_after_missing_schema(method):  # noqa: ANN001
    @wraps(method)
    def wrapped(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            if not _is_missing_postgres_relation(exc):
                raise
            with _SCHEMA_INIT_LOCK:
                if not self._initialized:
                    raise
                self._initialized = False
                return method(self, *args, **kwargs)

    return wrapped


def _is_missing_postgres_relation(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if str(getattr(current, "sqlstate", "") or "") == "42P01":
            return True
        current = current.__cause__ or current.__context__
    return False


@dataclass(frozen=True)
class PostgresMemoryConfig:
    dsn: str
    connect_timeout: int = 5

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "PostgresMemoryConfig | None":
        source = os.environ if env is None else env
        backend = str(source.get(POSTGRES_BACKEND_ENV, "") or "").strip().casefold()
        if backend not in POSTGRES_BACKEND_TOKENS:
            return None
        dsn = str(source.get(POSTGRES_DSN_ENV, "") or "").strip()
        if not dsn:
            raise AccountStoreError(f"{POSTGRES_DSN_ENV} must be set when {POSTGRES_BACKEND_ENV}=postgres")
        try:
            timeout = int(str(source.get(POSTGRES_CONNECT_TIMEOUT_ENV, "5") or "5"))
        except ValueError:
            timeout = 5
        return cls(dsn=dsn, connect_timeout=max(1, min(timeout, 60)))


class PostgresAccountMemoryBackend:
    def __init__(
        self,
        *,
        instance_name: str,
        provider: InstanceSecretProvider,
        purpose: str,
        config: PostgresMemoryConfig,
    ) -> None:
        self.instance_name = instance_name
        self.provider = provider
        self.purpose = purpose
        self.config = config
        self._initialized = False
        self.last_entry_read_error = ""
        self.last_entry_skipped = 0
        self.last_index_read_error = ""
        self.last_collection_read_error = ""
        self.last_collection_skipped = 0
        self.last_database_missing = False
        self._cipher_key: bytes | None = None
        self._cipher: AESGCM | None = None

    def _clear_write_diagnostics(self, kind: str) -> None:
        database_was_missing = self.last_database_missing
        self.last_database_missing = False
        if database_was_missing:
            self.last_entry_read_error = ""
            self.last_entry_skipped = 0
            self.last_index_read_error = ""
            self.last_collection_read_error = ""
            self.last_collection_skipped = 0
            return
        if kind == "entries":
            self.last_entry_read_error = ""
            self.last_entry_skipped = 0
        elif kind == "index":
            self.last_index_read_error = ""
        elif kind == "collection":
            self.last_collection_read_error = ""
            self.last_collection_skipped = 0

    @property
    def key(self) -> bytes:
        key = self.provider.get_secret(self.instance_name, self.purpose)
        if len(key) != 32:
            raise AccountStoreError("postgres memory encryption key has invalid length")
        return key

    @property
    def cipher(self) -> AESGCM:
        key = self.key
        if self._cipher is None or self._cipher_key != key:
            self._cipher = AESGCM(key)
            self._cipher_key = key
        return self._cipher

    @_retry_after_missing_schema
    def read_entries(self, account_id: str) -> list[dict[str, Any]]:
        self.last_entry_read_error = ""
        self.last_entry_skipped = 0
        self._ensure_schema()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT memory_id, payload_nonce, payload_ciphertext
                FROM teebotus_memory_entries
                WHERE instance_name = %s AND account_id = %s
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
                "PostgreSQL account-memory skipped corrupt rows instance=%s account=%s skipped=%s first_memory_id=%s error=%s",
                self.instance_name,
                account_id,
                skipped,
                first_skipped_id,
                first_error,
            )
        return entries

    @_retry_after_missing_schema
    def read_entries_by_ids(self, account_id: str, memory_ids: Iterable[str]) -> list[dict[str, Any]]:
        self.last_entry_read_error = ""
        self.last_entry_skipped = 0
        requested_ids = list(dict.fromkeys(str(memory_id or "").strip() for memory_id in memory_ids if str(memory_id or "").strip()))
        if not requested_ids:
            return []
        self._ensure_schema()
        rows: list[tuple[Any, ...]] = []
        with self._connect() as connection:
            for offset in range(0, len(requested_ids), POSTGRES_READ_ENTRIES_BY_IDS_CHUNK_SIZE):
                chunk = requested_ids[offset : offset + POSTGRES_READ_ENTRIES_BY_IDS_CHUNK_SIZE]
                placeholders = ",".join("%s" for _ in chunk)
                rows.extend(
                    connection.execute(
                        f"""
                        SELECT memory_id, payload_nonce, payload_ciphertext
                        FROM teebotus_memory_entries
                        WHERE instance_name = %s AND account_id = %s AND memory_id IN ({placeholders})
                        ORDER BY ordinal ASC, created_at ASC, memory_id ASC
                        """,
                        (self.instance_name, account_id, *chunk),
                    ).fetchall()
                )
            found_ids = {str(row[0]).strip() for row in rows}
            missing_ids = [memory_id for memory_id in requested_ids if memory_id not in found_ids]
            for offset in range(0, len(missing_ids), POSTGRES_READ_ENTRIES_BY_IDS_CHUNK_SIZE):
                chunk = missing_ids[offset : offset + POSTGRES_READ_ENTRIES_BY_IDS_CHUNK_SIZE]
                placeholders = ",".join("%s" for _ in chunk)
                rows.extend(
                    connection.execute(
                        f"""
                        SELECT memory_id, payload_nonce, payload_ciphertext
                        FROM teebotus_memory_entries
                        WHERE instance_name = %s AND account_id = %s AND BTRIM(memory_id) IN ({placeholders})
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
                "PostgreSQL account-memory skipped corrupt rows instance=%s account=%s skipped=%s first_memory_id=%s error=%s",
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

    @_retry_after_missing_schema
    def write_entries(self, account_id: str, rows: Iterable[dict[str, Any]]) -> None:
        self._ensure_schema()
        normalized_rows = [dict(row) for row in rows if isinstance(row, dict)]
        with self._connect() as connection:
            with connection.transaction():
                self._guard_existing_account_payloads_decryptable(connection, account_id)
                connection.execute(
                    "DELETE FROM teebotus_memory_keywords WHERE instance_name = %s AND account_id = %s",
                    (self.instance_name, account_id),
                )
                connection.execute(
                    "DELETE FROM teebotus_memory_entries WHERE instance_name = %s AND account_id = %s",
                    (self.instance_name, account_id),
                )
                for ordinal, row in enumerate(normalized_rows):
                    self._insert_entry(connection, account_id, row, ordinal)
        self._clear_write_diagnostics("entries")

    @_retry_after_missing_schema
    def read_index(self, account_id: str) -> dict[str, Any]:
        self.last_index_read_error = ""
        self._ensure_schema()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_nonce, payload_ciphertext
                FROM teebotus_memory_indexes
                WHERE instance_name = %s AND account_id = %s
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
                "PostgreSQL account-memory index could not be decrypted and was ignored instance=%s account=%s error=%s",
                self.instance_name,
                account_id,
                exc,
            )
            return {}

    @_retry_after_missing_schema
    def write_index(self, account_id: str, data: dict[str, Any]) -> None:
        self._ensure_schema()
        nonce, ciphertext = self._encrypt_json(account_id, "index", dict(data))
        with self._connect() as connection:
            with connection.transaction():
                self._guard_existing_account_payloads_decryptable(connection, account_id)
                connection.execute(
                    """
                    INSERT INTO teebotus_memory_indexes
                    (instance_name, account_id, payload_nonce, payload_ciphertext, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (instance_name, account_id)
                    DO UPDATE SET payload_nonce = EXCLUDED.payload_nonce,
                                  payload_ciphertext = EXCLUDED.payload_ciphertext,
                                  updated_at = EXCLUDED.updated_at
                    """,
                    (self.instance_name, account_id, nonce, ciphertext, utc_now()),
                )
        self._clear_write_diagnostics("index")

    @_retry_after_missing_schema
    def read_collection(self, account_id: str, collection: str) -> list[dict[str, Any]]:
        collection_name = _normalize_collection_name(collection)
        self.last_collection_read_error = ""
        self.last_collection_skipped = 0
        self._ensure_schema()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT item_key, payload_nonce, payload_ciphertext
                FROM teebotus_account_jsonl_collections
                WHERE instance_name = %s AND account_id = %s AND collection = %s
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
                "PostgreSQL account-memory skipped corrupt collection rows instance=%s account=%s collection=%s skipped=%s first_item=%s error=%s",
                self.instance_name,
                account_id,
                collection_name,
                skipped,
                first_skipped_id,
                first_error,
            )
        return items

    @_retry_after_missing_schema
    def write_collection(self, account_id: str, collection: str, rows: Iterable[dict[str, Any]]) -> None:
        collection_name = _normalize_collection_name(collection)
        self._ensure_schema()
        normalized_rows = [dict(row) for row in rows if isinstance(row, dict)]
        with self._connect() as connection:
            with connection.transaction():
                self._guard_existing_account_payloads_decryptable(connection, account_id)
                connection.execute(
                    """
                    DELETE FROM teebotus_account_jsonl_collections
                    WHERE instance_name = %s AND account_id = %s AND collection = %s
                    """,
                    (self.instance_name, account_id, collection_name),
                )
                for ordinal, row in enumerate(normalized_rows):
                    self._insert_collection_item(connection, account_id, collection_name, row, ordinal)
        self._clear_write_diagnostics("collection")

    @_retry_after_missing_schema
    def append_collection_items(self, account_id: str, collection: str, rows: Iterable[dict[str, Any]]) -> None:
        collection_name = _normalize_collection_name(collection)
        self._ensure_schema()
        normalized_rows = [dict(row) for row in rows if isinstance(row, dict)]
        if not normalized_rows:
            return
        with self._connect() as connection:
            with connection.transaction():
                self._guard_account_key_sample_decryptable(connection, account_id)
                start_ordinal = connection.execute(
                    """
                    SELECT COALESCE(MAX(ordinal), -1) + 1
                    FROM teebotus_account_jsonl_collections
                    WHERE instance_name = %s AND account_id = %s AND collection = %s
                    """,
                    (self.instance_name, account_id, collection_name),
                ).fetchone()[0]
                for offset, row in enumerate(normalized_rows):
                    self._insert_collection_item(connection, account_id, collection_name, row, int(start_ordinal) + offset)
        self._clear_write_diagnostics("collection")

    @_retry_after_missing_schema
    def replace_collection_item(self, account_id: str, collection: str, item_key: str, row: dict[str, Any]) -> bool:
        collection_name = _normalize_collection_name(collection)
        normalized_item_key = str(item_key or "").strip()
        if not normalized_item_key or not isinstance(row, dict):
            return False
        self._ensure_schema()
        with self._connect() as connection:
            with connection.transaction():
                existing = connection.execute(
                    """
                    SELECT ordinal, payload_nonce, payload_ciphertext
                    FROM teebotus_account_jsonl_collections
                    WHERE instance_name = %s AND account_id = %s AND collection = %s AND item_key = %s
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
                    UPDATE teebotus_account_jsonl_collections
                    SET created_at = %s, updated_at = %s, payload_nonce = %s, payload_ciphertext = %s
                    WHERE instance_name = %s AND account_id = %s AND collection = %s AND ordinal = %s
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
                replaced = int(updated.rowcount or 0) > 0
        if replaced:
            self._clear_write_diagnostics("collection")
        return replaced

    @_retry_after_missing_schema
    def read_collection_names(self, account_id: str) -> tuple[str, ...]:
        self.last_collection_read_error = ""
        self.last_collection_skipped = 0
        self._ensure_schema()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT collection
                FROM teebotus_account_jsonl_collections
                WHERE instance_name = %s AND account_id = %s
                ORDER BY collection ASC
                """,
                (self.instance_name, account_id),
            ).fetchall()
        return tuple(str(row[0]) for row in rows if str(row[0] or "").strip())

    @_retry_after_missing_schema
    def clear_account_unchecked(self, account_id: str) -> None:
        self._ensure_schema()
        with self._connect() as connection:
            with connection.transaction():
                connection.execute(
                    "DELETE FROM teebotus_memory_keywords WHERE instance_name = %s AND account_id = %s",
                    (self.instance_name, account_id),
                )
                connection.execute(
                    "DELETE FROM teebotus_memory_entries WHERE instance_name = %s AND account_id = %s",
                    (self.instance_name, account_id),
                )
                connection.execute(
                    "DELETE FROM teebotus_memory_indexes WHERE instance_name = %s AND account_id = %s",
                    (self.instance_name, account_id),
                )
                connection.execute(
                    "DELETE FROM teebotus_account_jsonl_collections WHERE instance_name = %s AND account_id = %s",
                    (self.instance_name, account_id),
                )

    def _connect(self) -> Any:
        try:
            import psycopg
        except ModuleNotFoundError as exc:
            raise AccountStoreError("psycopg is required for PostgreSQL account memory; install psycopg[binary]==3.3.4") from exc
        try:
            return psycopg.connect(self.config.dsn, connect_timeout=self.config.connect_timeout)
        except Exception as exc:  # noqa: BLE001
            raise AccountStoreError(f"could not connect to PostgreSQL account memory backend: {exc}") from exc

    def _ensure_schema(self) -> None:
        with _SCHEMA_INIT_LOCK:
            self._ensure_schema_locked()

    def _ensure_schema_locked(self) -> None:
        if self._initialized:
            return
        with self._connect() as connection:
            with connection.transaction():
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS teebotus_memory_entries (
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
                        payload_nonce BYTEA NOT NULL,
                        payload_ciphertext BYTEA NOT NULL,
                        PRIMARY KEY (instance_name, account_id, memory_id)
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS teebotus_memory_keywords (
                        instance_name TEXT NOT NULL,
                        account_id TEXT NOT NULL,
                        keyword TEXT NOT NULL,
                        memory_id TEXT NOT NULL,
                        PRIMARY KEY (instance_name, account_id, keyword, memory_id),
                        FOREIGN KEY (instance_name, account_id, memory_id)
                            REFERENCES teebotus_memory_entries(instance_name, account_id, memory_id)
                            ON DELETE CASCADE
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS teebotus_memory_indexes (
                        instance_name TEXT NOT NULL,
                        account_id TEXT NOT NULL,
                        payload_nonce BYTEA NOT NULL,
                        payload_ciphertext BYTEA NOT NULL,
                        updated_at TEXT NOT NULL DEFAULT '',
                        PRIMARY KEY (instance_name, account_id)
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS teebotus_account_jsonl_collections (
                        instance_name TEXT NOT NULL,
                        account_id TEXT NOT NULL,
                        collection TEXT NOT NULL,
                        ordinal INTEGER NOT NULL DEFAULT 0,
                        item_key TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL DEFAULT '',
                        updated_at TEXT NOT NULL DEFAULT '',
                        payload_nonce BYTEA NOT NULL,
                        payload_ciphertext BYTEA NOT NULL,
                        PRIMARY KEY (instance_name, account_id, collection, ordinal)
                    )
                    """
                )
                connection.execute("CREATE INDEX IF NOT EXISTS idx_teebotus_memory_keywords_lookup ON teebotus_memory_keywords(instance_name, account_id, keyword)")
                connection.execute("CREATE INDEX IF NOT EXISTS idx_teebotus_memory_rank ON teebotus_memory_entries(instance_name, account_id, salience, importance, access_count)")
                connection.execute("CREATE INDEX IF NOT EXISTS idx_teebotus_account_jsonl_collections_lookup ON teebotus_account_jsonl_collections(instance_name, account_id, collection, item_key)")
        self._initialized = True

    def _insert_entry(self, connection: Any, account_id: str, row: dict[str, Any], ordinal: int) -> None:
        memory_id = str(row.get("id") or f"mem_{uuid.uuid4().hex}").strip()
        row["id"] = memory_id
        nonce, ciphertext = self._encrypt_json(account_id, memory_id, row)
        connection.execute(
            """
            INSERT INTO teebotus_memory_entries
            (instance_name, account_id, memory_id, ordinal, kind, memory_type, importance, salience,
             access_count, created_at, updated_at, last_accessed_at, payload_nonce, payload_ciphertext)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO teebotus_memory_keywords(instance_name, account_id, keyword, memory_id)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    [(self.instance_name, account_id, str(keyword), memory_id) for keyword in keywords if str(keyword or "").strip()],
                )

    def _insert_collection_item(self, connection: Any, account_id: str, collection: str, row: dict[str, Any], ordinal: int) -> None:
        item_key = _collection_item_key(row, ordinal)
        nonce, ciphertext = self._encrypt_json(account_id, _collection_payload_id(collection, item_key), row)
        connection.execute(
            """
            INSERT INTO teebotus_account_jsonl_collections
            (instance_name, account_id, collection, ordinal, item_key, created_at, updated_at, payload_nonce, payload_ciphertext)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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

    def _guard_existing_account_payloads_decryptable(self, connection: Any, account_id: str) -> None:
        entry_rows = connection.execute(
            """
            SELECT memory_id, payload_nonce, payload_ciphertext
            FROM teebotus_memory_entries
            WHERE instance_name = %s AND account_id = %s
            """,
            (self.instance_name, account_id),
        ).fetchall()
        for row in entry_rows:
            memory_id = str(row[0])
            try:
                self._decrypt_json(account_id, memory_id, bytes(row[1]), bytes(row[2]))
            except AccountStoreError as exc:
                raise AccountStoreError(
                    "existing PostgreSQL account memory entries are not decryptable with the current key; refusing destructive write"
                ) from exc
        index_row = connection.execute(
            """
            SELECT payload_nonce, payload_ciphertext
            FROM teebotus_memory_indexes
            WHERE instance_name = %s AND account_id = %s
            """,
            (self.instance_name, account_id),
        ).fetchone()
        if index_row is not None:
            try:
                self._decrypt_json(account_id, "index", bytes(index_row[0]), bytes(index_row[1]))
            except AccountStoreError as exc:
                raise AccountStoreError(
                    "existing PostgreSQL account memory index is not decryptable with the current key; refusing destructive write"
                ) from exc
        collection_rows = connection.execute(
            """
            SELECT collection, item_key, payload_nonce, payload_ciphertext
            FROM teebotus_account_jsonl_collections
            WHERE instance_name = %s AND account_id = %s
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
                    "existing PostgreSQL account memory collection rows are not decryptable with the current key; refusing destructive write"
                ) from exc

    def _guard_account_key_sample_decryptable(self, connection: Any, account_id: str) -> None:
        entry_row = connection.execute(
            """
            SELECT memory_id, payload_nonce, payload_ciphertext
            FROM teebotus_memory_entries
            WHERE instance_name = %s AND account_id = %s
            ORDER BY ordinal ASC
            LIMIT 1
            """,
            (self.instance_name, account_id),
        ).fetchone()
        if entry_row is not None:
            try:
                self._decrypt_json(account_id, str(entry_row[0]), bytes(entry_row[1]), bytes(entry_row[2]))
            except AccountStoreError as exc:
                raise AccountStoreError("existing PostgreSQL account memory entries are not decryptable with the current key") from exc
            return
        index_row = connection.execute(
            """
            SELECT payload_nonce, payload_ciphertext
            FROM teebotus_memory_indexes
            WHERE instance_name = %s AND account_id = %s
            LIMIT 1
            """,
            (self.instance_name, account_id),
        ).fetchone()
        if index_row is not None:
            try:
                self._decrypt_json(account_id, "index", bytes(index_row[0]), bytes(index_row[1]))
            except AccountStoreError as exc:
                raise AccountStoreError("existing PostgreSQL account memory index is not decryptable with the current key") from exc
            return
        collection_row = connection.execute(
            """
            SELECT collection, item_key, payload_nonce, payload_ciphertext
            FROM teebotus_account_jsonl_collections
            WHERE instance_name = %s AND account_id = %s
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
            raise AccountStoreError("existing PostgreSQL account memory collection rows are not decryptable with the current key") from exc

    def _encrypt_json(self, account_id: str, memory_id: str, payload: dict[str, Any]) -> tuple[bytes, bytes]:
        import json

        nonce = os.urandom(12)
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ciphertext = self.cipher.encrypt(nonce, raw, self._aad(account_id, memory_id))
        return nonce, ciphertext

    def _decrypt_json(self, account_id: str, memory_id: str, nonce: bytes, ciphertext: bytes) -> dict[str, Any]:
        import json

        try:
            raw = self.cipher.decrypt(nonce, ciphertext, self._aad(account_id, memory_id))
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise AccountStoreError("PostgreSQL account memory payload could not be decrypted") from exc
        if not isinstance(data, dict):
            raise AccountStoreError("PostgreSQL account memory payload must contain an object")
        return data

    def _aad(self, account_id: str, memory_id: str) -> bytes:
        return f"TeeBotus:{self.instance_name}:{self.purpose}:{account_id}:{memory_id}:postgres:v1".encode("utf-8")


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_collection_name(collection: str) -> str:
    value = str(collection or "").strip()
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    if not value or any(char not in allowed for char in value):
        raise AccountStoreError("PostgreSQL account memory collection name is invalid")
    return value


def _collection_item_key(row: dict[str, Any], ordinal: int) -> str:
    for key in ("id", "item_id", "event_id", "result_id"):
        value = str(row.get(key) or "").strip()
        if value:
            return value[:240]
    return f"row_{ordinal:012d}"


def _collection_payload_id(collection: str, item_key: str) -> str:
    return f"jsonl:{collection}:{item_key}"
