#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key  # noqa: E402
from TeeBotus.runtime.accounts import AccountStoreError  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark TeeBotus account-memory storage operations.")
    parser.add_argument("--entries", type=int, default=1000, help="Number of synthetic entries to create.")
    parser.add_argument("--select-runs", type=int, default=20, help="Number of select_structured_memory runs.")
    parser.add_argument(
        "--backend",
        choices=("jsonl", "sqlite", "postgres", "all"),
        default="jsonl",
        help="Storage backend candidate to benchmark.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--postgres-dsn", default="", help="Override TEEBOTUS_ACCOUNT_MEMORY_POSTGRES_DSN for PostgreSQL benchmark runs.")
    parser.add_argument("--require-postgres", action="store_true", help="Fail when PostgreSQL benchmark cannot run.")
    args = parser.parse_args(argv)
    if args.entries < 1:
        parser.error("--entries must be >= 1")
    if args.select_runs < 1:
        parser.error("--select-runs must be >= 1")

    if args.backend == "jsonl":
        result = benchmark_jsonl_backend(entries=args.entries, select_runs=args.select_runs)
    elif args.backend == "sqlite":
        result = benchmark_sqlite_row_encrypted_projection(entries=args.entries, select_runs=args.select_runs)
    elif args.backend == "postgres":
        result = benchmark_postgres_backend(entries=args.entries, select_runs=args.select_runs, dsn=args.postgres_dsn)
    else:
        result = {
            "backend": "comparison",
            "results": [
                benchmark_jsonl_backend(entries=args.entries, select_runs=args.select_runs),
                benchmark_sqlite_row_encrypted_projection(entries=args.entries, select_runs=args.select_runs),
                benchmark_postgres_backend(entries=args.entries, select_runs=args.select_runs, dsn=args.postgres_dsn),
            ],
        }
    if args.require_postgres and _postgres_skipped(result):
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            for item in result.get("results", [result]):
                _print_result(item)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for item in result.get("results", [result]):
            _print_result(item)
    return 0


def benchmark_jsonl_backend(*, entries: int, select_runs: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="teebotus-memory-bench-") as tmp:
        root = Path(tmp)
        store = AccountStore(root / "accounts", "Bench", StaticSecretProvider(b"b" * 32))
        account_id = store.resolve_or_create_account(signal_identity_key(source_uuid="bench"))
        append_timings = []
        total_start = time.perf_counter()
        for index in range(entries):
            append_timings.append(
                _timed_ms(
                    lambda index=index: store.append_structured_memory_entry(
                        account_id,
                        {
                            "id": f"mem_{index:06d}",
                            "kind": "observation",
                            "memory_type": "episodic",
                            "user_text": f"Spaziergang Kaffee Druck Mond Eintrag {index}",
                            "bot_text": "Notiert.",
                            "keywords": ["spaziergang", "kaffee", "druck", "mond", str(index)],
                        },
                    )
                )
            )
        append_total_ms = (time.perf_counter() - total_start) * 1000

        select_timings = [
            _timed_ms(
                lambda: store.select_structured_memory(
                    account_id,
                    query_text="spaziergang kaffee",
                    max_prompt_chars=12000,
                    max_entry_chars=2000,
                )
            )
            for _ in range(select_runs)
        ]
        rebuild_ms = _timed_ms(lambda: store.rebuild_structured_memory_index(account_id))
        account_dir = store.account_dir(account_id)
        entries_path = account_dir / "User_Memory_Entries.jsonl"
        index_path = account_dir / "User_Memory_Index.json"
        return {
            "backend": "encrypted-jsonl-plus-json-index",
            "entries": entries,
            "entry_bytes": entries_path.stat().st_size if entries_path.exists() else 0,
            "index_bytes": index_path.stat().st_size if index_path.exists() else 0,
            "append_total_ms": append_total_ms,
            "append_last_ms": append_timings[-1],
            "append_median_ms": statistics.median(append_timings),
            "select_median_ms": statistics.median(select_timings),
            "select_p95_ms": _p95(select_timings),
            "rebuild_ms": rebuild_ms,
        }


def benchmark_sqlite_row_encrypted_projection(*, entries: int, select_runs: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="teebotus-memory-sqlite-bench-") as tmp:
        root = Path(tmp)
        db_path = root / "User_Memory.sqlite3"
        key = AESGCM.generate_key(bit_length=256)
        cipher = AESGCM(key)
        connection = sqlite3.connect(db_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        _init_sqlite_projection(connection)
        append_timings = []
        total_start = time.perf_counter()
        for index in range(entries):
            entry = {
                "id": f"mem_{index:06d}",
                "kind": "observation",
                "memory_type": "episodic",
                "importance": 3,
                "salience": 3,
                "access_count": 0,
                "user_text": f"Spaziergang Kaffee Druck Mond Eintrag {index}",
                "bot_text": "Notiert.",
                "keywords": ["spaziergang", "kaffee", "druck", "mond", str(index)],
            }
            append_timings.append(_timed_ms(lambda entry=entry: _insert_sqlite_projection_entry(connection, cipher, entry)))
        append_total_ms = (time.perf_counter() - total_start) * 1000

        select_timings = [
            _timed_ms(lambda: _select_sqlite_projection_entries(connection, ["spaziergang", "kaffee"], limit=32))
            for _ in range(select_runs)
        ]
        rebuild_ms = _timed_ms(lambda: _rebuild_sqlite_projection_indexes(connection))
        connection.close()
        return {
            "backend": "sqlite-row-encrypted-projection",
            "entries": entries,
            "entry_bytes": db_path.stat().st_size if db_path.exists() else 0,
            "index_bytes": 0,
            "append_total_ms": append_total_ms,
            "append_last_ms": append_timings[-1],
            "append_median_ms": statistics.median(append_timings),
            "select_median_ms": statistics.median(select_timings),
            "select_p95_ms": _p95(select_timings),
            "rebuild_ms": rebuild_ms,
            "payload_encryption": "AES-256-GCM-per-row",
            "queryable_metadata": ["id", "kind", "memory_type", "importance", "salience", "access_count", "keywords"],
        }


def benchmark_postgres_backend(*, entries: int, select_runs: int, dsn: str = "") -> dict[str, Any]:
    from TeeBotus.runtime.postgres_memory import POSTGRES_BACKEND_ENV, POSTGRES_DSN_ENV

    resolved_dsn = str(dsn or os.environ.get(POSTGRES_DSN_ENV) or "").strip()
    if not resolved_dsn:
        return {
            "backend": "postgres-row-encrypted-memory",
            "entries": entries,
            "skipped": True,
            "reason": f"{POSTGRES_DSN_ENV} is not set",
        }
    previous_backend = os.environ.get(POSTGRES_BACKEND_ENV)
    previous_dsn = os.environ.get(POSTGRES_DSN_ENV)
    os.environ[POSTGRES_BACKEND_ENV] = "postgres"
    os.environ[POSTGRES_DSN_ENV] = resolved_dsn
    try:
        root = Path(tempfile.mkdtemp(prefix="teebotus-memory-postgres-bench-"))
        store = AccountStore(root / "accounts", f"Bench_{os.getpid()}_{time.time_ns()}", StaticSecretProvider(b"b" * 32))
        account_id = store.resolve_or_create_account(signal_identity_key(source_uuid=f"bench-{time.time_ns()}"))
        append_timings = []
        total_start = time.perf_counter()
        for index in range(entries):
            append_timings.append(
                _timed_ms(
                    lambda index=index: store.append_structured_memory_entry(
                        account_id,
                        {
                            "id": f"mem_{index:06d}",
                            "kind": "observation",
                            "memory_type": "episodic",
                            "user_text": f"Spaziergang Kaffee Druck Mond Eintrag {index}",
                            "bot_text": "Notiert.",
                            "keywords": ["spaziergang", "kaffee", "druck", "mond", str(index)],
                        },
                    )
                )
            )
        append_total_ms = (time.perf_counter() - total_start) * 1000
        select_timings = [
            _timed_ms(
                lambda: store.select_structured_memory(
                    account_id,
                    query_text="spaziergang kaffee",
                    max_prompt_chars=12000,
                    max_entry_chars=2000,
                )
            )
            for _ in range(select_runs)
        ]
        rebuild_ms = _timed_ms(lambda: store.rebuild_structured_memory_index(account_id))
        return {
            "backend": "postgres-row-encrypted-memory",
            "entries": entries,
            "entry_bytes": 0,
            "index_bytes": 0,
            "append_total_ms": append_total_ms,
            "append_last_ms": append_timings[-1],
            "append_median_ms": statistics.median(append_timings),
            "select_median_ms": statistics.median(select_timings),
            "select_p95_ms": _p95(select_timings),
            "rebuild_ms": rebuild_ms,
            "payload_encryption": "AES-256-GCM-per-row",
            "queryable_metadata": ["id", "kind", "memory_type", "importance", "salience", "access_count", "keywords"],
        }
    except AccountStoreError as exc:
        return {
            "backend": "postgres-row-encrypted-memory",
            "entries": entries,
            "skipped": True,
            "reason": str(exc),
        }
    finally:
        if previous_backend is None:
            os.environ.pop(POSTGRES_BACKEND_ENV, None)
        else:
            os.environ[POSTGRES_BACKEND_ENV] = previous_backend
        if previous_dsn is None:
            os.environ.pop(POSTGRES_DSN_ENV, None)
        else:
            os.environ[POSTGRES_DSN_ENV] = previous_dsn


def _init_sqlite_projection(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS memory_entries (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            memory_type TEXT NOT NULL,
            importance INTEGER NOT NULL,
            salience INTEGER NOT NULL,
            access_count INTEGER NOT NULL,
            nonce TEXT NOT NULL,
            payload_ciphertext BLOB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memory_keywords (
            keyword TEXT NOT NULL,
            memory_id TEXT NOT NULL,
            PRIMARY KEY (keyword, memory_id),
            FOREIGN KEY (memory_id) REFERENCES memory_entries(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_memory_keywords_keyword ON memory_keywords(keyword);
        CREATE INDEX IF NOT EXISTS idx_memory_entries_rank ON memory_entries(salience, importance, access_count);
        """
    )


def _insert_sqlite_projection_entry(connection: sqlite3.Connection, cipher: AESGCM, entry: dict[str, Any]) -> None:
    nonce = os.urandom(12)
    payload = json.dumps(entry, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ciphertext = cipher.encrypt(nonce, payload, str(entry["id"]).encode("utf-8"))
    with connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO memory_entries
            (id, kind, memory_type, importance, salience, access_count, nonce, payload_ciphertext)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry["id"],
                entry["kind"],
                entry["memory_type"],
                int(entry["importance"]),
                int(entry["salience"]),
                int(entry["access_count"]),
                base64.b64encode(nonce).decode("ascii"),
                ciphertext,
            ),
        )
        connection.execute("DELETE FROM memory_keywords WHERE memory_id = ?", (entry["id"],))
        connection.executemany(
            "INSERT OR IGNORE INTO memory_keywords(keyword, memory_id) VALUES (?, ?)",
            [(str(keyword), entry["id"]) for keyword in entry.get("keywords", [])],
        )


def _select_sqlite_projection_entries(connection: sqlite3.Connection, keywords: list[str], *, limit: int) -> list[str]:
    placeholders = ",".join("?" for _ in keywords)
    rows = connection.execute(
        f"""
        SELECT e.id
        FROM memory_entries e
        LEFT JOIN memory_keywords k ON k.memory_id = e.id AND k.keyword IN ({placeholders})
        GROUP BY e.id
        ORDER BY COUNT(k.keyword) DESC, e.salience DESC, e.importance DESC, e.access_count DESC, e.id DESC
        LIMIT ?
        """,
        [*keywords, limit],
    ).fetchall()
    return [str(row[0]) for row in rows]


def _rebuild_sqlite_projection_indexes(connection: sqlite3.Connection) -> None:
    with connection:
        connection.execute("REINDEX")
        connection.execute("ANALYZE")


def _print_result(result: dict[str, Any]) -> None:
    print(f"backend={result['backend']}")
    if result.get("skipped"):
        print(f"skipped=yes reason={result.get('reason', '')}")
        return
    print(f"entries={result['entries']}")
    print(f"entry_bytes={result['entry_bytes']} index_bytes={result['index_bytes']}")
    print(f"append_total_ms={result['append_total_ms']:.2f}")
    print(f"append_last_ms={result['append_last_ms']:.2f}")
    print(f"append_median_ms={result['append_median_ms']:.2f}")
    print(f"select_median_ms={result['select_median_ms']:.2f}")
    print(f"select_p95_ms={result['select_p95_ms']:.2f}")
    print(f"rebuild_ms={result['rebuild_ms']:.2f}")


def _timed_ms(callback: Callable[[], object]) -> float:
    start = time.perf_counter()
    callback()
    return (time.perf_counter() - start) * 1000


def _p95(values: list[float]) -> float:
    if len(values) < 2:
        return values[0]
    return statistics.quantiles(values, n=20, method="inclusive")[18]


def _postgres_skipped(result: dict[str, Any]) -> bool:
    items = result.get("results")
    if isinstance(items, list):
        return any(isinstance(item, dict) and item.get("backend") == "postgres-row-encrypted-memory" and item.get("skipped") for item in items)
    return result.get("backend") == "postgres-row-encrypted-memory" and bool(result.get("skipped"))


if __name__ == "__main__":
    raise SystemExit(main())
