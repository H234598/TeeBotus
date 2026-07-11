from __future__ import annotations

import pytest

from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, StaticSecretProvider
from TeeBotus.runtime.postgres_memory import PostgresAccountMemoryBackend, PostgresMemoryConfig
from scripts import benchmark_memory_store as memory_bench
from scripts.benchmark_memory_store import (
    benchmark_postgres_backend,
    benchmark_sqlite_row_encrypted_projection,
    main,
    postgres_account_memory_payload_sizes,
)


def test_sqlite_row_encrypted_projection_benchmark_reports_expected_shape() -> None:
    result = benchmark_sqlite_row_encrypted_projection(entries=5, select_runs=2)

    assert result["backend"] == "sqlite-row-encrypted-projection"
    assert result["entries"] == 5
    assert result["entry_bytes"] > 0
    assert result["payload_encryption"] == "AES-256-GCM-per-row"
    assert "keywords" in result["queryable_metadata"]
    assert result["append_last_ms"] >= 0
    assert result["select_median_ms"] >= 0


def test_memory_store_benchmark_can_compare_jsonl_and_sqlite(capsys) -> None:
    result = main(["--entries", "2", "--select-runs", "1", "--backend", "all"])

    assert result == 0
    output = capsys.readouterr().out
    assert "backend=encrypted-jsonl-plus-json-index" in output
    assert "backend=sqlite-row-encrypted-projection" in output
    assert "backend=postgres-row-encrypted-memory" in output
    assert "skipped=yes" in output


def test_postgres_benchmark_skips_without_dsn(monkeypatch) -> None:
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_POSTGRES_DSN", raising=False)

    result = benchmark_postgres_backend(entries=5, select_runs=2)

    assert result["backend"] == "postgres-row-encrypted-memory"
    assert result["skipped"] is True
    assert "POSTGRES_DSN" in result["reason"]


def test_postgres_benchmark_accepts_dsn_override(monkeypatch) -> None:
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_POSTGRES_DSN", raising=False)

    result = benchmark_postgres_backend(entries=1, select_runs=1, dsn="postgresql://invalid.invalid/teebotus")

    assert result["backend"] == "postgres-row-encrypted-memory"
    assert result["skipped"] is True
    assert "could not connect to PostgreSQL" in result["reason"]


def test_postgres_empty_entry_id_read_clears_previous_diagnostics() -> None:
    backend = PostgresAccountMemoryBackend(
        instance_name="Bench",
        provider=StaticSecretProvider(b"p" * 32),
        purpose="account-structured-memory-key",
        config=PostgresMemoryConfig(dsn="postgresql://unused"),
    )
    backend.last_entry_read_error = "stale error"
    backend.last_entry_skipped = 2

    assert backend.read_entries_by_ids("a" * 128, []) == []
    assert backend.last_entry_read_error == ""
    assert backend.last_entry_skipped == 0


def test_postgres_entry_id_read_chunks_large_requests(monkeypatch) -> None:
    class FakeResult:
        def __init__(self, memory_ids: tuple[str, ...]) -> None:
            self.memory_ids = memory_ids

        def fetchall(self):
            return [(memory_id, b"nonce", b"cipher") for memory_id in self.memory_ids]

    class FakeConnection:
        def __init__(self) -> None:
            self.params: list[tuple[str, ...]] = []

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def execute(self, _sql: str, params: tuple[str, ...]) -> FakeResult:
            self.params.append(params)
            return FakeResult(tuple(params[2:]))

    backend = PostgresAccountMemoryBackend(
        instance_name="Bench",
        provider=StaticSecretProvider(b"p" * 32),
        purpose="account-structured-memory-key",
        config=PostgresMemoryConfig(dsn="postgresql://unused"),
    )
    connection = FakeConnection()
    monkeypatch.setattr(backend, "_ensure_schema", lambda: None)
    monkeypatch.setattr(backend, "_connect", lambda: connection)
    monkeypatch.setattr(
        backend,
        "_decrypt_json",
        lambda _account_id, memory_id, _nonce, _ciphertext: {"id": memory_id},
    )
    requested_ids = [f"mem-{index:04d}" for index in reversed(range(1101))]

    selected = backend.read_entries_by_ids("a" * 128, requested_ids)

    assert [row["id"] for row in selected] == requested_ids
    assert [len(params) - 2 for params in connection.params] == [500, 500, 101]


def test_postgres_collection_name_read_clears_previous_diagnostics(monkeypatch) -> None:
    class FakeResult:
        def fetchall(self):
            return [("proactive_outbox",)]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def execute(self, _sql: str, _params: tuple[str, ...]) -> FakeResult:
            return FakeResult()

    backend = PostgresAccountMemoryBackend(
        instance_name="Bench",
        provider=StaticSecretProvider(b"p" * 32),
        purpose="account-structured-memory-key",
        config=PostgresMemoryConfig(dsn="postgresql://unused"),
    )
    backend.last_collection_read_error = "stale error"
    backend.last_collection_skipped = 2
    monkeypatch.setattr(backend, "_ensure_schema", lambda: None)
    monkeypatch.setattr(backend, "_connect", lambda: FakeConnection())

    assert backend.read_collection_names("a" * 128) == ("proactive_outbox",)
    assert backend.last_collection_read_error == ""
    assert backend.last_collection_skipped == 0


def test_postgres_benchmark_success_path_uses_cleaned_tempdir(monkeypatch, tmp_path) -> None:
    entered: list[str] = []
    exited: list[str] = []

    class FakeTemporaryDirectory:
        def __init__(self, prefix: str) -> None:
            self.path = tmp_path / f"{prefix}fake"

        def __enter__(self) -> str:
            self.path.mkdir()
            entered.append(str(self.path))
            return str(self.path)

        def __exit__(self, *_args) -> None:
            exited.append(str(self.path))
            self.path.rmdir()

    class FakeAccountStore:
        account_memory_backend = object()

        def __init__(self, root, instance_name, provider) -> None:  # noqa: ANN001
            assert str(root).startswith(entered[0])
            assert instance_name.startswith("Bench_")
            assert provider is not None
            self.entries: list[dict[str, object]] = []

        def resolve_or_create_account(self, _identity_key: str) -> str:
            return "a" * 128

        def append_structured_memory_entry(self, _account_id: str, entry: dict[str, object]) -> str:
            self.entries.append(entry)
            return str(entry["id"])

        def select_structured_memory(self, _account_id: str, **_kwargs) -> list[dict[str, object]]:
            return self.entries[:1]

        def rebuild_structured_memory_index(self, _account_id: str) -> dict[str, object]:
            return {"index": {"scope": "account"}}

    monkeypatch.setattr(memory_bench.tempfile, "TemporaryDirectory", FakeTemporaryDirectory)
    monkeypatch.setattr(memory_bench.tempfile, "mkdtemp", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("mkdtemp must not be used")))
    monkeypatch.setattr(memory_bench, "AccountStore", FakeAccountStore)
    monkeypatch.setattr(
        memory_bench,
        "postgres_account_memory_payload_sizes",
        lambda _backend, _account_id: {"entry_bytes": 512, "index_bytes": 128, "entry_rows": 2, "keyword_rows": 6, "index_rows": 1},
    )

    result = benchmark_postgres_backend(entries=2, select_runs=1, dsn="postgresql://bench")

    assert result["backend"] == "postgres-row-encrypted-memory"
    assert result["entry_bytes"] == 512
    assert result["row_counts"] == {"entries": 2, "keywords": 6, "indexes": 1}
    assert entered == exited
    assert not (tmp_path / "teebotus-memory-postgres-bench-fake").exists()


def test_postgres_payload_size_metrics_include_entries_keywords_and_index() -> None:
    class FakeResult:
        def __init__(self, row: tuple[int, int]) -> None:
            self.row = row

        def fetchone(self) -> tuple[int, int]:
            return self.row

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def execute(self, sql: str, params: tuple[str, str]) -> FakeResult:
            assert params == ("Bench", "a" * 128)
            if "teebotus_memory_entries" in sql:
                return FakeResult((512, 4))
            if "teebotus_memory_keywords" in sql:
                return FakeResult((128, 12))
            if "teebotus_memory_indexes" in sql:
                return FakeResult((96, 1))
            raise AssertionError(sql)

    class FakeBackend:
        instance_name = "Bench"

        def _connect(self) -> FakeConnection:
            return FakeConnection()

    sizes = postgres_account_memory_payload_sizes(FakeBackend(), "a" * 128)

    assert sizes == {
        "entry_bytes": 512,
        "index_bytes": 224,
        "entry_rows": 4,
        "keyword_rows": 12,
        "index_rows": 1,
    }


def test_account_store_postgres_backend_requires_dsn(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "postgres")
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_POSTGRES_DSN", raising=False)
    store = AccountStore(tmp_path / "accounts", "Demo", StaticSecretProvider(b"p" * 32))

    with pytest.raises(AccountStoreError, match="POSTGRES_DSN"):
        store.read_memory_entries("a" * 128)


def test_postgres_backend_inserts_keywords_with_cursor_executemany() -> None:
    class FakeCursor:
        def __init__(self) -> None:
            self.batches: list[list[tuple[str, str, str, str]]] = []

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def executemany(self, _sql: str, params: list[tuple[str, str, str, str]]) -> None:
            self.batches.append(params)

    class FakeConnection:
        def __init__(self) -> None:
            self.executed: list[tuple[str, tuple]] = []
            self.cursor_obj = FakeCursor()

        def execute(self, sql: str, params: tuple) -> None:
            self.executed.append((sql, params))

        def cursor(self) -> FakeCursor:
            return self.cursor_obj

    backend = PostgresAccountMemoryBackend(
        instance_name="Bench",
        provider=StaticSecretProvider(b"p" * 32),
        purpose="account-structured-memory-key",
        config=PostgresMemoryConfig(dsn="postgresql://unused"),
    )
    connection = FakeConnection()

    backend._insert_entry(
        connection,
        "a" * 128,
        {"id": "mem_1", "keywords": ["spaziergang", "kaffee"], "user_text": "Hallo"},
        0,
    )

    assert len(connection.executed) == 1
    assert connection.cursor_obj.batches == [[("Bench", "a" * 128, "spaziergang", "mem_1"), ("Bench", "a" * 128, "kaffee", "mem_1")]]


def test_postgres_backend_skips_corrupt_rows_like_sqlite(monkeypatch, caplog) -> None:
    class FakeResult:
        def fetchall(self):
            return [("mem_ok", b"nonce", b"cipher"), ("mem_bad", b"nonce", b"cipher")]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def execute(self, _sql: str, _params: tuple) -> FakeResult:
            return FakeResult()

    backend = PostgresAccountMemoryBackend(
        instance_name="Bench",
        provider=StaticSecretProvider(b"p" * 32),
        purpose="account-structured-memory-key",
        config=PostgresMemoryConfig(dsn="postgresql://unused"),
    )
    monkeypatch.setattr(backend, "_ensure_schema", lambda: None)
    monkeypatch.setattr(backend, "_connect", lambda: FakeConnection())

    def fake_decrypt(_account_id: str, memory_id: str, _nonce: bytes, _ciphertext: bytes) -> dict[str, str]:
        if memory_id == "mem_bad":
            raise AccountStoreError("broken row")
        return {"id": memory_id}

    monkeypatch.setattr(backend, "_decrypt_json", fake_decrypt)

    with caplog.at_level("CRITICAL", logger="TeeBotus"):
        entries = backend.read_entries("a" * 128)

    assert entries == [{"id": "mem_ok"}]
    assert "PostgreSQL account-memory skipped corrupt rows" in caplog.text
    assert "first_memory_id=mem_bad" in caplog.text


def test_postgres_backend_rebuilds_schema_after_missing_relation(monkeypatch) -> None:
    class MissingRelationError(Exception):
        sqlstate = "42P01"

    class FakeResult:
        def fetchall(self):
            return [("mem_retry", b"nonce", b"cipher")]

    class FakeTransaction:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    class FakeConnection:
        def __init__(self) -> None:
            self.fail_read_once = True
            self.executed: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def transaction(self) -> FakeTransaction:
            return FakeTransaction()

        def execute(self, sql: str, _params=()):
            self.executed.append(sql)
            if "SELECT memory_id" in sql and self.fail_read_once:
                self.fail_read_once = False
                raise MissingRelationError("relation does not exist")
            return FakeResult()

    backend = PostgresAccountMemoryBackend(
        instance_name="Bench",
        provider=StaticSecretProvider(b"p" * 32),
        purpose="account-structured-memory-key",
        config=PostgresMemoryConfig(dsn="postgresql://unused"),
    )
    backend._initialized = True
    connection = FakeConnection()
    monkeypatch.setattr(backend, "_connect", lambda: connection)
    monkeypatch.setattr(backend, "_decrypt_json", lambda _account_id, memory_id, _nonce, _ciphertext: {"id": memory_id})

    assert backend.read_entries("a" * 128) == [{"id": "mem_retry"}]
    assert any("CREATE TABLE IF NOT EXISTS teebotus_memory_entries" in sql for sql in connection.executed)


def test_postgres_backend_ignores_corrupt_index_like_sqlite(monkeypatch, caplog) -> None:
    class FakeResult:
        def fetchone(self):
            return (b"nonce", b"cipher")

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def execute(self, _sql: str, _params: tuple) -> FakeResult:
            return FakeResult()

    backend = PostgresAccountMemoryBackend(
        instance_name="Bench",
        provider=StaticSecretProvider(b"p" * 32),
        purpose="account-structured-memory-key",
        config=PostgresMemoryConfig(dsn="postgresql://unused"),
    )
    monkeypatch.setattr(backend, "_ensure_schema", lambda: None)
    monkeypatch.setattr(backend, "_connect", lambda: FakeConnection())
    monkeypatch.setattr(
        backend,
        "_decrypt_json",
        lambda *_args: (_ for _ in ()).throw(AccountStoreError("broken index")),
    )

    with caplog.at_level("CRITICAL", logger="TeeBotus"):
        index = backend.read_index("a" * 128)

    assert index == {}
    assert "PostgreSQL account-memory index could not be decrypted and was ignored" in caplog.text
