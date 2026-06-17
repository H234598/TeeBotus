from __future__ import annotations

import json
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from TeeBotus.benchmarks.core import BenchmarkResult, result
from TeeBotus.mcp_tools import MCPToolPolicy, MCPToolRegistry, build_readonly_mcp_registry
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key
from TeeBotus.runtime.bibliothekar import BibliothekarStore
from TeeBotus.runtime.bibliothekar_service import BibliothekarService, LocalBibliothekarBackend


def benchmark_mcp_readonly_bibliothekar_and_memory_search(*, iterations: int) -> BenchmarkResult:
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-mcp-") as tmp:
        root = Path(tmp)
        library_dir = root / "instances" / "Bench" / "data" / "Bibliothek"
        library_dir.mkdir(parents=True)
        (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
        store = BibliothekarStore("Bench", root / "instances")
        store.rebuild()
        service = BibliothekarService(LocalBibliothekarBackend(store))
        account_store = AccountStore(root / "accounts", "Bench", StaticSecretProvider(b"m" * 32))
        account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="bench-mcp"))
        account_store.append_structured_memory_entry(
            account_id,
            {
                "id": "mem_mcp_bench",
                "kind": "preference",
                "memory_type": "semantic",
                "user_text": "Der Nutzer mag kurze Antworten zu Therapieaufgaben.",
                "bot_text": "Notiert.",
                "keywords": ["therapieaufgaben", "kurz"],
            },
        )
        tool_config = {
            "bibliothekar.search": {"enabled": True, "read_only": True},
            "memory.search": {"enabled": True, "read_only": True},
        }
        registry = build_readonly_mcp_registry(
            account_store=account_store,
            account_id=account_id,
            bibliothekar_service=service,
            tool_config=tool_config,
            private_chat=True,
        )
        group_registry = build_readonly_mcp_registry(
            account_store=account_store,
            account_id=account_id,
            bibliothekar_service=service,
            tool_config=tool_config,
            private_chat=False,
        )
        calls: list[Any] = []
        timings = [
            _timed_ms(
                lambda: calls.append(
                    (
                        registry.call("bibliothekar.search", {"query": "Therapie", "top_k": 1}),
                        registry.call("memory.search", {"query": "Therapieaufgaben"}),
                    )
                )
            )
            for _ in range(iterations)
        ]
        latest_library = calls[-1][0] if calls else {}
        latest_memory = calls[-1][1] if calls else {}
        group_blocks_memory = "memory.search" not in group_registry.tool_names
        unknown_registry = MCPToolRegistry(
            {"shell.exec": MCPToolPolicy(enabled=True, read_only=True)},
            {"shell.exec": lambda _arguments: {"stdout": "would run"}},
        )
        unknown_tool_blocked = "shell.exec" not in unknown_registry.tool_names and not unknown_registry.policy("shell.exec").enabled
        ok = (
            bool(latest_library.get("selected_ids"))
            and latest_memory.get("selected_ids") == ["mem_mcp_bench"]
            and group_blocks_memory
            and unknown_tool_blocked
        )
        return result(
            name="mcp_readonly_bibliothekar_and_memory_search",
            category="mcp_tools",
            iterations=iterations * 2,
            total_ms=sum(timings),
            ok=ok,
            errors=0 if ok else 1,
            payload_bytes=len(json.dumps(calls[-1] if calls else {}, ensure_ascii=False).encode("utf-8")),
            index_bytes=store.index_path.stat().st_size if store.index_path.exists() else 0,
            details={
                "tool_names": registry.tool_names,
                "group_tool_names": group_registry.tool_names,
                "library_selected": len(latest_library.get("selected_ids") or []),
                "memory_selected": len(latest_memory.get("selected_ids") or []),
                "group_blocks_memory": group_blocks_memory,
                "unknown_tool_blocked": unknown_tool_blocked,
                "network_calls": 0,
                "median_tool_pair_ms": statistics.median(timings),
            },
        )


def _timed_ms(func: Callable[[], Any]) -> float:
    start = time.perf_counter()
    func()
    return (time.perf_counter() - start) * 1000


__all__ = ["benchmark_mcp_readonly_bibliothekar_and_memory_search"]
