#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark TeeBotus account-memory storage operations.")
    parser.add_argument("--entries", type=int, default=1000, help="Number of synthetic entries to create.")
    parser.add_argument("--select-runs", type=int, default=20, help="Number of select_structured_memory runs.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)
    if args.entries < 1:
        parser.error("--entries must be >= 1")
    if args.select_runs < 1:
        parser.error("--select-runs must be >= 1")

    result = benchmark_jsonl_backend(entries=args.entries, select_runs=args.select_runs)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"backend={result['backend']}")
        print(f"entries={result['entries']}")
        print(f"entry_bytes={result['entry_bytes']} index_bytes={result['index_bytes']}")
        print(f"append_total_ms={result['append_total_ms']:.2f}")
        print(f"append_last_ms={result['append_last_ms']:.2f}")
        print(f"select_median_ms={result['select_median_ms']:.2f}")
        print(f"select_p95_ms={result['select_p95_ms']:.2f}")
        print(f"rebuild_ms={result['rebuild_ms']:.2f}")
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


def _timed_ms(callback: Callable[[], object]) -> float:
    start = time.perf_counter()
    callback()
    return (time.perf_counter() - start) * 1000


def _p95(values: list[float]) -> float:
    if len(values) < 2:
        return values[0]
    return statistics.quantiles(values, n=20, method="inclusive")[18]


if __name__ == "__main__":
    raise SystemExit(main())
