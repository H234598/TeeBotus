#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.benchmark_memory_store import (  # noqa: E402
    benchmark_jsonl_backend,
    benchmark_postgres_backend,
    benchmark_sqlite_row_encrypted_projection,
)
from TeeBotus.core.youtube import _has_youtube_transcript_intent, _parse_youtube_local_options  # noqa: E402
from TeeBotus.instructions import BotInstructions  # noqa: E402
from TeeBotus.llm.profiles import load_llm_profiles, load_llm_routing, select_llm_route  # noqa: E402
from TeeBotus.mcp_tools import build_readonly_mcp_registry  # noqa: E402
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key  # noqa: E402
from TeeBotus.runtime.bibliothekar import BibliothekarStore  # noqa: E402
from TeeBotus.runtime.bibliothekar_service import (  # noqa: E402
    BibliothekarQuery,
    BibliothekarService,
    HaystackBibliothekarBackend,
    LocalBibliothekarBackend,
    check_bibliothekar_service,
)
from TeeBotus.runtime.graphs import run_bibliothekar_deep_query  # noqa: E402
from TeeBotus.runtime.proactive_agent import (  # noqa: E402
    due_proactive_outbox_items,
    enable_proactive_agent,
    proactive_policy_decision,
    queue_proactive_message,
)


BenchmarkResult = dict[str, Any]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic TeeBotus benchmark suite.")
    parser.add_argument("--quick", action="store_true", help="Run only local deterministic quick benchmarks.")
    parser.add_argument("--entries", type=int, default=50, help="Synthetic memory entries for quick storage benchmarks.")
    parser.add_argument("--iterations", type=int, default=50, help="Iterations for light CPU-only benchmark loops.")
    parser.add_argument("--output", default="", help="Markdown output path.")
    parser.add_argument("--json-output", default="", help="JSON output path.")
    parser.add_argument("--postgres-dsn", default="", help="Optional PostgreSQL DSN for live PostgreSQL memory benchmark.")
    args = parser.parse_args(argv)
    if args.entries < 1:
        parser.error("--entries must be >= 1")
    if args.iterations < 1:
        parser.error("--iterations must be >= 1")

    suite = run_benchmarks(entries=args.entries, iterations=args.iterations, postgres_dsn=args.postgres_dsn, quick=bool(args.quick))
    markdown = render_markdown(suite)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(markdown, encoding="utf-8")
    else:
        print(markdown)
    if args.json_output:
        Path(args.json_output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_output).write_text(json.dumps(suite, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if suite["ok"] else 1


def run_benchmarks(*, entries: int = 50, iterations: int = 50, postgres_dsn: str = "", quick: bool = True) -> dict[str, Any]:
    results: list[BenchmarkResult] = []
    results.extend(_memory_results(entries=entries, select_runs=max(1, min(5, iterations)), postgres_dsn=postgres_dsn))
    results.append(_benchmark_bibliothekar(iterations=iterations))
    results.append(_benchmark_bibliothekar_haystack_fake(iterations=iterations))
    results.append(_benchmark_llm_router(iterations=iterations))
    results.append(_benchmark_proactive(iterations=iterations))
    results.append(_benchmark_adapter_contracts(iterations=iterations))
    results.append(_benchmark_youtube_parser(iterations=iterations))
    results.append(_benchmark_status_doctor(iterations=iterations))
    results.append(_benchmark_database_fallback_policy(iterations=iterations))
    results.append(_benchmark_langgraph_flow(iterations=iterations))
    results.append(_benchmark_mcp_tools(iterations=iterations))
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "quick": bool(quick),
        "ok": all(result.get("ok", False) or result.get("skipped", False) for result in results),
        "context": _context(),
        "results": results,
    }


def render_markdown(suite: dict[str, Any]) -> str:
    lines = [
        "# TeeBotus Benchmarks",
        "",
        f"- generated_at: {suite['generated_at']}",
        f"- python: {suite['context']['python']}",
        f"- platform: {suite['context']['platform']}",
        f"- quick: {suite['quick']}",
        "",
        "| name | category | status | iterations | total_ms | throughput_ops_s | errors | payload_bytes | index_bytes | note |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for result in suite["results"]:
        status = "skipped" if result.get("skipped") else ("ok" if result.get("ok") else "failed")
        lines.append(
            "| {name} | {category} | {status} | {iterations} | {total_ms:.3f} | {throughput:.2f} | {errors} | {payload_bytes} | {index_bytes} | {note} |".format(
                name=result.get("name", ""),
                category=result.get("category", ""),
                status=status,
                iterations=int(result.get("iterations") or 0),
                total_ms=float(result.get("total_ms") or 0.0),
                throughput=float(result.get("throughput_ops_s") or 0.0),
                errors=int(result.get("errors") or 0),
                payload_bytes=int(result.get("payload_bytes") or 0),
                index_bytes=int(result.get("index_bytes") or 0),
                note=str(result.get("reason") or result.get("note") or "").replace("|", "/"),
            )
        )
    lines.append("")
    lines.append("Standard-Benchmarks nutzen keine echten Provider-Calls und keine Netzsendung.")
    return "\n".join(lines) + "\n"


def _memory_results(*, entries: int, select_runs: int, postgres_dsn: str) -> list[BenchmarkResult]:
    results = []
    for name, func in (
        ("memory_jsonl", lambda: benchmark_jsonl_backend(entries=entries, select_runs=select_runs)),
        ("memory_sqlite_projection", lambda: benchmark_sqlite_row_encrypted_projection(entries=entries, select_runs=select_runs)),
        ("memory_postgres", lambda: benchmark_postgres_backend(entries=entries, select_runs=select_runs, dsn=postgres_dsn)),
    ):
        raw = func()
        skipped = bool(raw.get("skipped"))
        total_ms = float(raw.get("append_total_ms") or 0.0) + float(raw.get("rebuild_ms") or 0.0) + float(raw.get("select_median_ms") or 0.0) * select_runs
        results.append(
            _result(
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
            )
        )
    return results


def _benchmark_bibliothekar(*, iterations: int) -> BenchmarkResult:
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-library-") as tmp:
        root = Path(tmp)
        library_dir = root / "instances" / "Bench" / "data" / "Bibliothek"
        library_dir.mkdir(parents=True)
        for index in range(3):
            (library_dir / f"therapie_{index}.txt").write_text(
                f"Depression Therapie Aktivierung Schlaf Tagesstruktur Quelle {index}.",
                encoding="utf-8",
            )
        store = BibliothekarStore("Bench", root / "instances")
        rebuild_ms = _timed_ms(store.rebuild)
        service = BibliothekarService(LocalBibliothekarBackend(store))
        timings = [_timed_ms(lambda: service.search("Therapie Schlaf", max_chunks=2)) for _ in range(iterations)]
        index = json.loads(store.index_path.read_text(encoding="utf-8"))
        return _result(
            name="bibliothekar_local_query",
            category="bibliothekar",
            iterations=iterations,
            total_ms=rebuild_ms + sum(timings),
            payload_bytes=store.chunks_path.stat().st_size,
            index_bytes=store.index_path.stat().st_size,
            details={"documents": len(index.get("documents", {})), "chunks": int(index.get("chunk_count") or 0), "median_query_ms": statistics.median(timings)},
        )


def _benchmark_bibliothekar_haystack_fake(*, iterations: int) -> BenchmarkResult:
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-haystack-") as tmp:
        root = Path(tmp)
        library_dir = root / "instances" / "Bench" / "data" / "Bibliothek"
        library_dir.mkdir(parents=True)
        for index in range(3):
            (library_dir / f"therapie_{index}.txt").write_text(
                f"Depression Therapie Aktivierung Schlaf Tagesstruktur Haystack Quelle {index}.",
                encoding="utf-8",
            )
        document_store = _BenchmarkDocumentStore()
        backend = HaystackBibliothekarBackend(
            instance_name="Bench",
            instances_dir=root / "instances",
            collection="bench_books",
            document_store_factory=lambda: document_store,
            document_class=_BenchmarkDocument,
        )
        rebuild_ms = _timed_ms(backend.rebuild)
        timings = [
            _timed_ms(
                lambda: backend.search(
                    BibliothekarQuery(
                        text="Therapie Schlaf",
                        max_chunks=2,
                        max_prompt_chars=5000,
                        max_quote_chars=500,
                    )
                )
            )
            for _ in range(iterations)
        ]
        fallback_store = backend.fallback_store
        index = json.loads(fallback_store.index_path.read_text(encoding="utf-8"))
        return _result(
            name="bibliothekar_haystack_fake_query",
            category="bibliothekar",
            iterations=iterations,
            total_ms=rebuild_ms + sum(timings),
            payload_bytes=fallback_store.chunks_path.stat().st_size,
            index_bytes=fallback_store.index_path.stat().st_size,
            note="fake_haystack_document_store",
            details={
                "documents": len(index.get("documents", {})),
                "chunks": int(index.get("chunk_count") or 0),
                "document_store_documents": len(document_store.documents),
                "median_query_ms": statistics.median(timings),
            },
        )


def _benchmark_llm_router(*, iterations: int) -> BenchmarkResult:
    profiles = load_llm_profiles()
    _default_profile, routing = load_llm_routing()
    timings = [_timed_ms(lambda: select_llm_route("structured_decision", profiles=profiles, routing=routing)) for _ in range(iterations)]
    return _result(
        name="llm_router_structured_decision",
        category="llm_router",
        iterations=iterations,
        total_ms=sum(timings),
        details={"median_route_ms": statistics.median(timings), "profile_count": len(profiles), "route_count": len(routing)},
    )


def _benchmark_proactive(*, iterations: int) -> BenchmarkResult:
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-proactive-") as tmp:
        store = AccountStore(Path(tmp) / "accounts", "Bench", StaticSecretProvider(b"p" * 32))
        identity = signal_identity_key(source_uuid="bench")
        account_id = store.resolve_or_create_account(identity)
        store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
        enable_proactive_agent(store, account_id, categories=("reminder",))
        due_at = "2026-06-16T10:00:00+00:00"
        queue_proactive_message(store, account_id, category="reminder", intent="bench", message_text="Bench", due_at=due_at)
        timings = [_timed_ms(lambda: due_proactive_outbox_items(store, account_id)) for _ in range(iterations)]
        policy_ms = _timed_ms(lambda: proactive_policy_decision(store, account_id, category="reminder"))
        return _result(
            name="proactive_due_selection",
            category="proactive_agent",
            iterations=iterations + 1,
            total_ms=sum(timings) + policy_ms,
            payload_bytes=sum(len(json.dumps(item, ensure_ascii=False)) for item in store.read_proactive_outbox(account_id)),
            details={"queued": len(store.read_proactive_outbox(account_id)), "median_due_ms": statistics.median(timings), "policy_ms": policy_ms},
        )


def _benchmark_adapter_contracts(*, iterations: int) -> BenchmarkResult:
    packages = ("signalbot", "nio-bot", "matrix-nio")

    def check() -> list[str]:
        return [importlib.metadata.version(package) for package in packages]

    errors = 0
    timings = []
    versions: list[str] = []
    for _ in range(iterations):
        try:
            timings.append(_timed_ms(lambda: versions.extend(check())))
        except importlib.metadata.PackageNotFoundError:
            errors += 1
    return _result(
        name="messenger_adapter_package_contracts",
        category="messenger_adapters",
        iterations=iterations,
        total_ms=sum(timings),
        ok=errors == 0,
        errors=errors,
        details={"packages": packages, "version_reads": len(versions)},
    )


def _benchmark_youtube_parser(*, iterations: int) -> BenchmarkResult:
    samples = [
        "transkribiere dieses Video: https://youtu.be/dQw4w9WgXcQ",
        "/youtube_transcript https://youtube.com/watch?v=dQw4w9WgXcQ",
        "yt output bitte, live off llm off https://youtu.be/dQw4w9WgXcQ",
    ]

    def parse_all() -> int:
        hits = 0
        for sample in samples:
            hits += int(_has_youtube_transcript_intent(sample))
            _parse_youtube_local_options(sample)
        return hits

    hit_count = 0
    timings = []
    for _ in range(iterations):
        start = time.perf_counter()
        hit_count += parse_all()
        timings.append((time.perf_counter() - start) * 1000)
    return _result(
        name="youtube_parser_local",
        category="transcription_youtube",
        iterations=iterations * len(samples),
        total_ms=sum(timings),
        details={"intent_hits": hit_count, "sample_count": len(samples), "median_batch_ms": statistics.median(timings)},
    )


def _benchmark_status_doctor(*, iterations: int) -> BenchmarkResult:
    instructions = BotInstructions(bibliothekar_backend="local")
    timings = [_timed_ms(lambda: check_bibliothekar_service("Bench", Path("instances"), instructions)) for _ in range(iterations)]
    return _result(
        name="status_doctor_bibliothekar_health",
        category="status_doctor",
        iterations=iterations,
        total_ms=sum(timings),
        details={"median_health_ms": statistics.median(timings)},
    )


def _benchmark_database_fallback_policy(*, iterations: int) -> BenchmarkResult:
    primary = {"name": "postgres", "ok": False}
    secondary = {"name": "sqlite", "ok": True}

    def choose_backend() -> str:
        return primary["name"] if primary["ok"] else secondary["name"]

    timings = [_timed_ms(choose_backend) for _ in range(iterations)]
    return _result(
        name="database_fallback_policy",
        category="database_fallback",
        iterations=iterations,
        total_ms=sum(timings),
        details={"primary": primary, "secondary": secondary, "selected": choose_backend()},
    )


def _benchmark_langgraph_flow(*, iterations: int) -> BenchmarkResult:
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-graph-") as tmp:
        root = Path(tmp)
        library_dir = root / "instances" / "Bench" / "data" / "Bibliothek"
        library_dir.mkdir(parents=True)
        (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
        store = BibliothekarStore("Bench", root / "instances")
        store.rebuild()
        service = BibliothekarService(LocalBibliothekarBackend(store))
        timings = [_timed_ms(lambda: run_bibliothekar_deep_query(service, "Bibliothek Therapie", prefer_langgraph=True)) for _ in range(iterations)]
        return _result(
            name="langgraph_bibliothekar_deep_query",
            category="langgraph_flows",
            iterations=iterations,
            total_ms=sum(timings),
            details={"median_graph_ms": statistics.median(timings), "mode": "langgraph_or_linear_fallback"},
        )


def _benchmark_mcp_tools(*, iterations: int) -> BenchmarkResult:
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-mcp-") as tmp:
        root = Path(tmp)
        library_dir = root / "instances" / "Bench" / "data" / "Bibliothek"
        library_dir.mkdir(parents=True)
        (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
        store = BibliothekarStore("Bench", root / "instances")
        store.rebuild()
        service = BibliothekarService(LocalBibliothekarBackend(store))
        registry = build_readonly_mcp_registry(bibliothekar_service=service)
        timings = [_timed_ms(lambda: registry.call("bibliothekar.search", {"query": "Therapie", "top_k": 1})) for _ in range(iterations)]
        return _result(
            name="mcp_readonly_bibliothekar_search",
            category="mcp_tools",
            iterations=iterations,
            total_ms=sum(timings),
            details={"tool_names": registry.tool_names, "median_tool_ms": statistics.median(timings)},
        )


def _result(
    *,
    name: str,
    category: str,
    iterations: int,
    total_ms: float,
    ok: bool = True,
    skipped: bool = False,
    errors: int = 0,
    payload_bytes: int = 0,
    index_bytes: int = 0,
    note: str = "",
    reason: str = "",
    details: dict[str, Any] | None = None,
) -> BenchmarkResult:
    throughput = (iterations / (total_ms / 1000)) if total_ms > 0 and iterations > 0 else 0.0
    return {
        "name": name,
        "category": category,
        "ok": bool(ok),
        "skipped": bool(skipped),
        "iterations": int(iterations),
        "total_ms": float(total_ms),
        "throughput_ops_s": float(throughput),
        "errors": int(errors),
        "payload_bytes": int(payload_bytes),
        "index_bytes": int(index_bytes),
        "note": str(note or ""),
        "reason": str(reason or ""),
        "details": details or {},
    }


def _timed_ms(func: Callable[[], Any]) -> float:
    start = time.perf_counter()
    func()
    return (time.perf_counter() - start) * 1000


def _context() -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }


class _BenchmarkDocument:
    def __init__(self, *, content: str, meta: dict[str, Any], id: str | None = None) -> None:
        self.content = content
        self.meta = meta
        self.id = id or str(meta.get("chunk_id", ""))


class _BenchmarkDocumentStore:
    def __init__(self) -> None:
        self.documents: list[_BenchmarkDocument] = []

    def write_documents(self, documents: list[_BenchmarkDocument], **_kwargs: Any) -> None:
        by_id = {document.id: document for document in self.documents}
        for document in documents:
            by_id[document.id] = document
        self.documents = list(by_id.values())

    def filter_documents(self, **_kwargs: Any) -> list[_BenchmarkDocument]:
        return list(self.documents)


if __name__ == "__main__":
    raise SystemExit(main())
