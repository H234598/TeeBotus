from __future__ import annotations

import pytest

from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, StaticSecretProvider
from scripts.benchmark_memory_store import benchmark_postgres_backend, benchmark_sqlite_row_encrypted_projection, main


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


def test_account_store_postgres_backend_requires_dsn(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "postgres")
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_POSTGRES_DSN", raising=False)
    store = AccountStore(tmp_path / "accounts", "Demo", StaticSecretProvider(b"p" * 32))

    with pytest.raises(AccountStoreError, match="POSTGRES_DSN"):
        store.read_memory_entries("a" * 128)
