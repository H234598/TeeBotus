from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from scripts.benchmark_memory_store import (
    benchmark_jsonl_backend,
    benchmark_postgres_backend,
    benchmark_sqlite_row_encrypted_projection,
)
from TeeBotus.benchmarks.core import BenchmarkResult, result
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key
from TeeBotus.runtime.postgres_memory import POSTGRES_BACKEND_ENV
from TeeBotus.runtime.sqlite_memory import SQLITE_PATH_ENV


MemoryBackendBenchmark = Callable[..., dict[str, Any]]


def memory_results(
    *,
    entries: int,
    select_runs: int,
    postgres_dsn: str,
    jsonl_backend: MemoryBackendBenchmark = benchmark_jsonl_backend,
    sqlite_backend: MemoryBackendBenchmark = benchmark_sqlite_row_encrypted_projection,
    postgres_backend: MemoryBackendBenchmark = benchmark_postgres_backend,
) -> list[BenchmarkResult]:
    results = [benchmark_memory_jsonl_to_sqlite_migration(entries=entries)]
    for name, func in (
        ("memory_jsonl", lambda: jsonl_backend(entries=entries, select_runs=select_runs)),
        ("memory_sqlite_projection", lambda: sqlite_backend(entries=entries, select_runs=select_runs)),
        ("memory_postgres", lambda: postgres_backend(entries=entries, select_runs=select_runs, dsn=postgres_dsn)),
    ):
        raw = func()
        skipped = bool(raw.get("skipped"))
        total_ms = float(raw.get("append_total_ms") or 0.0) + float(raw.get("rebuild_ms") or 0.0) + float(raw.get("select_median_ms") or 0.0) * select_runs
        results.append(
            result(
                name=name,
                category="account_memory",
                iterations=entries + select_runs + 1 if not skipped else 0,
                total_ms=total_ms,
                ok=not skipped,
                skipped=skipped,
                errors=0,
                payload_bytes=int(raw.get("entry_bytes") or 0),
                index_bytes=int(raw.get("index_bytes") or 0),
                note=raw.get("backend", ""),
                reason=raw.get("reason", ""),
                details=raw,
                mode="live" if name == "memory_postgres" and not skipped else ("live_optional" if name == "memory_postgres" else "local"),
            )
        )
    return results


def benchmark_memory_jsonl_to_sqlite_migration(*, entries: int) -> BenchmarkResult:
    previous_backend = os.environ.get(POSTGRES_BACKEND_ENV)
    previous_sqlite_path = os.environ.get(SQLITE_PATH_ENV)
    try:
        os.environ.pop(POSTGRES_BACKEND_ENV, None)
        os.environ.pop(SQLITE_PATH_ENV, None)
        with tempfile.TemporaryDirectory(prefix="teebotus-memory-migration-bench-") as tmp:
            root = Path(tmp)
            provider = StaticSecretProvider(b"m" * 32)
            source = AccountStore(root / "accounts", "Bench", provider)
            account_id = source.resolve_or_create_account(signal_identity_key(source_uuid="bench-migration"))
            for index in range(entries):
                source.append_structured_memory_entry(
                    account_id,
                    {
                        "id": f"mem_migrate_{index:06d}",
                        "kind": "observation",
                        "memory_type": "episodic",
                        "user_text": f"Migration Spaziergang Kaffee {index}",
                        "bot_text": "Notiert.",
                        "keywords": ["migration", "spaziergang", str(index)],
                    },
                )
            read_ms = _timed_ms(lambda: (source.read_memory_entries(account_id), source.read_memory_index(account_id)))
            entries_payload = source.read_memory_entries(account_id)
            index_payload = source.read_memory_index(account_id)
            sqlite_path = root / "migrated.sqlite3"
            os.environ[POSTGRES_BACKEND_ENV] = "sqlite"
            os.environ[SQLITE_PATH_ENV] = str(sqlite_path)
            target = AccountStore(root / "accounts", "Bench", provider)
            write_ms = _timed_ms(lambda: (target.write_memory_entries(account_id, entries_payload), target.write_memory_index(account_id, index_payload)))
            verify_ms = _timed_ms(lambda: (target.read_memory_entries(account_id), target.read_memory_index(account_id)))
            verified = target.read_memory_entries(account_id) == entries_payload and target.read_memory_index(account_id) == index_payload
            return result(
                name="memory_migration_jsonl_to_sqlite",
                category="account_memory",
                iterations=entries + 3,
                total_ms=read_ms + write_ms + verify_ms,
                ok=verified,
                errors=0 if verified else 1,
                payload_bytes=sqlite_path.stat().st_size if sqlite_path.exists() else 0,
                index_bytes=0,
                note="jsonl_to_sqlite_verified",
                details={
                    "entries": entries,
                    "read_source_ms": read_ms,
                    "write_target_ms": write_ms,
                    "verify_target_ms": verify_ms,
                    "verified": verified,
                },
            )
    finally:
        if previous_backend is None:
            os.environ.pop(POSTGRES_BACKEND_ENV, None)
        else:
            os.environ[POSTGRES_BACKEND_ENV] = previous_backend
        if previous_sqlite_path is None:
            os.environ.pop(SQLITE_PATH_ENV, None)
        else:
            os.environ[SQLITE_PATH_ENV] = previous_sqlite_path


def _timed_ms(func: Callable[[], Any]) -> float:
    start = time.perf_counter()
    func()
    return (time.perf_counter() - start) * 1000


__all__ = [
    "benchmark_jsonl_backend",
    "benchmark_memory_jsonl_to_sqlite_migration",
    "benchmark_postgres_backend",
    "benchmark_sqlite_row_encrypted_projection",
    "memory_results",
]
