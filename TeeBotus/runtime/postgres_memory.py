from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from TeeBotus.runtime.accounts import AccountStoreError, InstanceSecretProvider, utc_now

POSTGRES_BACKEND_ENV = "TEEBOTUS_ACCOUNT_MEMORY_BACKEND"
POSTGRES_DSN_ENV = "TEEBOTUS_ACCOUNT_MEMORY_POSTGRES_DSN"
POSTGRES_CONNECT_TIMEOUT_ENV = "TEEBOTUS_ACCOUNT_MEMORY_POSTGRES_CONNECT_TIMEOUT"
POSTGRES_BACKEND_TOKENS = {"postgres", "postgresql", "pg"}
LOGGER = logging.getLogger("TeeBotus")


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

    @property
    def key(self) -> bytes:
        key = self.provider.get_secret(self.instance_name, self.purpose)
        if len(key) != 32:
            raise AccountStoreError("postgres memory encryption key has invalid length")
        return key

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
                connection.execute("CREATE INDEX IF NOT EXISTS idx_teebotus_memory_keywords_lookup ON teebotus_memory_keywords(instance_name, account_id, keyword)")
                connection.execute("CREATE INDEX IF NOT EXISTS idx_teebotus_memory_rank ON teebotus_memory_entries(instance_name, account_id, salience, importance, access_count)")
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
        if index_row is None:
            return
        try:
            self._decrypt_json(account_id, "index", bytes(index_row[0]), bytes(index_row[1]))
        except AccountStoreError as exc:
            raise AccountStoreError(
                "existing PostgreSQL account memory index is not decryptable with the current key; refusing destructive write"
            ) from exc

    def _encrypt_json(self, account_id: str, memory_id: str, payload: dict[str, Any]) -> tuple[bytes, bytes]:
        import json

        nonce = os.urandom(12)
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ciphertext = AESGCM(self.key).encrypt(nonce, raw, self._aad(account_id, memory_id))
        return nonce, ciphertext

    def _decrypt_json(self, account_id: str, memory_id: str, nonce: bytes, ciphertext: bytes) -> dict[str, Any]:
        import json

        try:
            raw = AESGCM(self.key).decrypt(nonce, ciphertext, self._aad(account_id, memory_id))
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
