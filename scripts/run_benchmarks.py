#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import shutil
import statistics
import sys
import tempfile
import time
import types
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
from TeeBotus import __version__ as TEEBOTUS_VERSION  # noqa: E402
from TeeBotus.ai_structures.decisions import parse_bibliothekar_query_decision  # noqa: E402
from TeeBotus.instructions import BotInstructions  # noqa: E402
from TeeBotus.llm.profiles import load_llm_profiles, load_llm_routing, select_llm_route  # noqa: E402
from TeeBotus.llm_client import LiteLLMTextClient  # noqa: E402
from TeeBotus.mcp_tools import build_readonly_mcp_registry  # noqa: E402
from TeeBotus.runtime.llm_factory import build_runtime_text_llm_client  # noqa: E402
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
from TeeBotus.runtime.postgres_memory import POSTGRES_BACKEND_ENV  # noqa: E402
from TeeBotus.runtime.sqlite_memory import SQLITE_PATH_ENV  # noqa: E402


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
    results.append(_benchmark_langgraph_linear_flow(iterations=iterations))
    results.append(_benchmark_langgraph_fake_installed_flow(iterations=iterations))
    results.append(_benchmark_mcp_tools(iterations=iterations))
    comparisons = _build_comparisons(results)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "quick": bool(quick),
        "ok": all(result.get("ok", False) or result.get("skipped", False) for result in results),
        "context": _context(),
        "results": results,
        "comparisons": comparisons,
    }


def render_markdown(suite: dict[str, Any]) -> str:
    lines = [
        "# TeeBotus Benchmarks",
        "",
        f"- generated_at: {suite['generated_at']}",
        f"- python: {suite['context']['python']}",
        f"- platform: {suite['context']['platform']}",
        f"- machine: {suite['context']['machine']}",
        f"- cpu_count: {suite['context']['cpu_count']}",
        f"- quick: {suite['quick']}",
        "",
        "## Dependencies",
        "",
        "| package | version | status |",
        "| --- | --- | --- |",
    ]
    for name, info in suite["context"]["dependencies"].items():
        lines.append(f"| {name} | {info['version']} | {info['status']} |")
    lines.extend(
        [
            "",
            "## Results",
            "",
        "| name | category | status | mode | iterations | total_ms | throughput_ops_s | errors | payload_bytes | index_bytes | note | details |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for result in suite["results"]:
        status = "skipped" if result.get("skipped") else ("ok" if result.get("ok") else "failed")
        lines.append(
            "| {name} | {category} | {status} | {mode} | {iterations} | {total_ms:.3f} | {throughput:.2f} | {errors} | {payload_bytes} | {index_bytes} | {note} | {details} |".format(
                name=result.get("name", ""),
                category=result.get("category", ""),
                status=status,
                mode=result.get("mode", "local"),
                iterations=int(result.get("iterations") or 0),
                total_ms=float(result.get("total_ms") or 0.0),
                throughput=float(result.get("throughput_ops_s") or 0.0),
                errors=int(result.get("errors") or 0),
                payload_bytes=int(result.get("payload_bytes") or 0),
                index_bytes=int(result.get("index_bytes") or 0),
                note=str(result.get("reason") or result.get("note") or "").replace("|", "/"),
                details=_markdown_details(result.get("details") or {}),
            )
        )
    comparisons = suite.get("comparisons") or {}
    stable_rankings = comparisons.get("stable_backend_rankings") if isinstance(comparisons, dict) else None
    if isinstance(stable_rankings, list) and stable_rankings:
        lines.extend(
            [
                "",
                "## Stable Backend Rankings",
                "",
                "| category | rank | name | mode | throughput_ops_s | total_ms | errors | note |",
                "| --- | ---: | --- | --- | ---: | ---: | ---: | --- |",
            ]
        )
        for ranking in stable_rankings:
            if not isinstance(ranking, dict):
                continue
            for candidate in ranking.get("candidates", []):
                if not isinstance(candidate, dict):
                    continue
                lines.append(
                    "| {category} | {rank} | {name} | {mode} | {throughput:.2f} | {total_ms:.3f} | {errors} | {note} |".format(
                        category=ranking.get("category", ""),
                        rank=int(candidate.get("rank") or 0),
                        name=candidate.get("name", ""),
                        mode=candidate.get("mode", ""),
                        throughput=float(candidate.get("throughput_ops_s") or 0.0),
                        total_ms=float(candidate.get("total_ms") or 0.0),
                        errors=int(candidate.get("errors") or 0),
                        note=str(candidate.get("note") or "").replace("|", "/"),
                    )
                )
        lines.append("")
        lines.append("Die Rangliste dokumentiert Messwerte nur; sie schaltet keine Runtime-Backends automatisch um.")
    lines.append("")
    lines.append("Standard-Benchmarks nutzen keine echten Provider-Calls und keine Netzsendung.")
    return "\n".join(lines) + "\n"


def _markdown_details(details: dict[str, Any]) -> str:
    if not details:
        return ""
    rendered = json.dumps(details, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    if len(rendered) > 220:
        rendered = f"{rendered[:217]}..."
    return rendered.replace("|", "/")


def _build_comparisons(results: list[BenchmarkResult]) -> dict[str, Any]:
    categories = {
        "account_memory": {"memory_jsonl", "memory_sqlite_projection", "memory_postgres"},
        "bibliothekar": {"bibliothekar_local_query", "bibliothekar_haystack_fake_query"},
        "langgraph_flows": {
            "langgraph_bibliothekar_deep_query",
            "langgraph_bibliothekar_linear",
            "langgraph_bibliothekar_fake_installed",
        },
    }
    rankings = []
    for category, names in categories.items():
        ranking = _stable_backend_ranking(category=category, results=results, names=names)
        if ranking:
            rankings.append(ranking)
    return {
        "auto_switching": False,
        "selection_policy": "document_fastest_stable_backend_only",
        "stable_backend_rankings": rankings,
    }


def _stable_backend_ranking(*, category: str, results: list[BenchmarkResult], names: set[str]) -> dict[str, Any] | None:
    candidates = [
        result
        for result in results
        if result.get("name") in names and result.get("category") == category and result.get("ok") and not result.get("skipped")
    ]
    skipped = [
        {
            "name": str(result.get("name") or ""),
            "mode": str(result.get("mode") or ""),
            "reason": str(result.get("reason") or ""),
        }
        for result in results
        if result.get("name") in names and result.get("skipped")
    ]
    if not candidates and not skipped:
        return None
    ranked = sorted(
        candidates,
        key=lambda result: (
            int(result.get("errors") or 0),
            -float(result.get("throughput_ops_s") or 0.0),
            float(result.get("total_ms") or 0.0),
            str(result.get("name") or ""),
        ),
    )
    return {
        "category": category,
        "fastest_stable": str(ranked[0].get("name") or "") if ranked else "",
        "candidates": [
            {
                "rank": index,
                "name": str(result.get("name") or ""),
                "mode": str(result.get("mode") or ""),
                "throughput_ops_s": float(result.get("throughput_ops_s") or 0.0),
                "total_ms": float(result.get("total_ms") or 0.0),
                "errors": int(result.get("errors") or 0),
                "payload_bytes": int(result.get("payload_bytes") or 0),
                "index_bytes": int(result.get("index_bytes") or 0),
                "note": str(result.get("note") or ""),
            }
            for index, result in enumerate(ranked, start=1)
        ],
        "skipped": skipped,
    }


def _memory_results(*, entries: int, select_runs: int, postgres_dsn: str) -> list[BenchmarkResult]:
    results = []
    results.append(_benchmark_memory_jsonl_to_sqlite_migration(entries=entries))
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
                mode="live" if name == "memory_postgres" and not skipped else ("live_optional" if name == "memory_postgres" else "local"),
            )
        )
    return results


def _benchmark_memory_jsonl_to_sqlite_migration(*, entries: int) -> BenchmarkResult:
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
            return _result(
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


def _benchmark_bibliothekar(*, iterations: int) -> BenchmarkResult:
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-library-") as tmp:
        root = Path(tmp)
        library_dir = root / "instances" / "Bench" / "data" / "Bibliothek"
        _copy_benchmark_books(library_dir)
        store = BibliothekarStore("Bench", root / "instances")
        rebuild_ms = _timed_ms(store.rebuild)
        service = BibliothekarService(LocalBibliothekarBackend(store))
        timings = [_timed_ms(lambda: service.search("Therapie Schlaf", max_chunks=2)) for _ in range(iterations)]
        selection = service.search("Therapie Schlaf", max_chunks=2)
        index = json.loads(store.index_path.read_text(encoding="utf-8"))
        return _result(
            name="bibliothekar_local_query",
            category="bibliothekar",
            iterations=iterations,
            total_ms=rebuild_ms + sum(timings),
            payload_bytes=store.chunks_path.stat().st_size,
            index_bytes=store.index_path.stat().st_size,
            details={
                "fixture": "tests/fixtures/books",
                "documents": len(index.get("documents", {})),
                "chunks": int(index.get("chunk_count") or 0),
                "median_query_ms": statistics.median(timings),
                **_bibliothekar_payload_details(selection.prompt_text),
            },
        )


def _benchmark_bibliothekar_haystack_fake(*, iterations: int) -> BenchmarkResult:
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-haystack-") as tmp:
        root = Path(tmp)
        library_dir = root / "instances" / "Bench" / "data" / "Bibliothek"
        _copy_benchmark_books(library_dir)
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
        selection = backend.search(
            BibliothekarQuery(
                text="Therapie Schlaf",
                max_chunks=2,
                max_prompt_chars=5000,
                max_quote_chars=500,
            )
        )
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
                "fixture": "tests/fixtures/books",
                "document_store_documents": len(document_store.documents),
                "median_query_ms": statistics.median(timings),
                **_bibliothekar_payload_details(selection.prompt_text),
            },
        )


def _bibliothekar_payload_details(prompt_text: str) -> dict[str, Any]:
    try:
        payload = json.loads(prompt_text)
    except json.JSONDecodeError:
        return {
            "citation_payload_bytes": len(prompt_text.encode("utf-8")),
            "selected_chunks": 0,
            "has_citation_format": False,
        }
    chunks = payload.get("selected_library_chunks") if isinstance(payload, dict) else None
    selected_chunks = chunks if isinstance(chunks, list) else []
    return {
        "citation_payload_bytes": len(prompt_text.encode("utf-8")),
        "selected_chunks": len(selected_chunks),
        "has_citation_format": all(bool(chunk.get("citation_format")) for chunk in selected_chunks if isinstance(chunk, dict)),
    }


def _benchmark_llm_router(*, iterations: int) -> BenchmarkResult:
    profiles = load_llm_profiles()
    _default_profile, routing = load_llm_routing()
    route_timings = [_timed_ms(lambda: select_llm_route("structured_decision", profiles=profiles, routing=routing)) for _ in range(iterations)]
    runtime_timings = [
        _timed_ms(
            lambda: build_runtime_text_llm_client(
                instructions=BotInstructions(),
                openai_client=None,
                purpose="structured_decision",
                allow_remote_fallback=True,
            )
        )
        for _ in range(iterations)
    ]
    decision_payload = {
        "should_search": True,
        "query": "Therapie Schlaf Tagesstruktur",
        "confidence": 0.91,
        "reason_short": "benchmark fake structured decision",
        "source": "model",
    }
    decision_timings = [_timed_ms(lambda: parse_bibliothekar_query_decision(decision_payload)) for _ in range(iterations)]
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        purpose="structured_decision",
        allow_remote_fallback=True,
    )
    fallback_route = select_llm_route("structured_decision", profiles=profiles, routing=routing, allow_remote_fallback=True)
    return _result(
        name="llm_router_structured_decision",
        category="llm_router",
        iterations=iterations * 3,
        total_ms=sum(route_timings) + sum(runtime_timings) + sum(decision_timings),
        details={
            "median_route_ms": statistics.median(route_timings),
            "median_runtime_client_ms": statistics.median(runtime_timings),
            "median_structured_decision_ms": statistics.median(decision_timings),
            "profile_count": len(profiles),
            "route_count": len(routing),
            "runtime_client": type(client).__name__,
            "runtime_provider": client.provider if isinstance(client, LiteLLMTextClient) else "",
            "runtime_model": client.model if isinstance(client, LiteLLMTextClient) else "",
            "fallback_models": list(fallback_route.fallback_models),
            "network_calls": 0,
        },
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
    with _BenchmarkGraphFixture() as service:
        timings = [_timed_ms(lambda: run_bibliothekar_deep_query(service, "Bibliothek Therapie", prefer_langgraph=True)) for _ in range(iterations)]
        return _result(
            name="langgraph_bibliothekar_deep_query",
            category="langgraph_flows",
            iterations=iterations,
            total_ms=sum(timings),
            details={"median_graph_ms": statistics.median(timings), "mode": "langgraph_or_linear_fallback"},
        )


def _benchmark_langgraph_linear_flow(*, iterations: int) -> BenchmarkResult:
    with _BenchmarkGraphFixture() as service:
        timings = [_timed_ms(lambda: run_bibliothekar_deep_query(service, "Bibliothek Therapie", prefer_langgraph=False)) for _ in range(iterations)]
        return _result(
            name="langgraph_bibliothekar_linear",
            category="langgraph_flows",
            iterations=iterations,
            total_ms=sum(timings),
            details={"median_graph_ms": statistics.median(timings), "mode": "linear"},
        )


def _benchmark_langgraph_fake_installed_flow(*, iterations: int) -> BenchmarkResult:
    previous_langgraph = sys.modules.get("langgraph")
    previous_graph = sys.modules.get("langgraph.graph")
    calls: list[str] = []

    class FakeCompiledGraph:
        def __init__(self, nodes: dict[str, Callable[[Any], Any]], edges: dict[str, str], entry: str) -> None:
            self.nodes = nodes
            self.edges = edges
            self.entry = entry

        def invoke(self, state: Any) -> Any:
            current = self.entry
            while current != "__end__":
                calls.append(current)
                state = self.nodes[current](state)
                current = self.edges[current]
            return state

    class FakeStateGraph:
        def __init__(self, _state_type: Any) -> None:
            self.nodes: dict[str, Callable[[Any], Any]] = {}
            self.edges: dict[str, str] = {}
            self.entry = ""

        def add_node(self, name: str, func: Callable[[Any], Any]) -> None:
            self.nodes[name] = func

        def set_entry_point(self, name: str) -> None:
            self.entry = name

        def add_edge(self, source: str, target: str) -> None:
            self.edges[source] = target

        def compile(self) -> FakeCompiledGraph:
            return FakeCompiledGraph(self.nodes, self.edges, self.entry)

    try:
        fake_package = types.ModuleType("langgraph")
        fake_graph = types.ModuleType("langgraph.graph")
        fake_graph.END = "__end__"
        fake_graph.StateGraph = FakeStateGraph
        sys.modules["langgraph"] = fake_package
        sys.modules["langgraph.graph"] = fake_graph
        with _BenchmarkGraphFixture() as service:
            timings = [_timed_ms(lambda: run_bibliothekar_deep_query(service, "Bibliothek Therapie", prefer_langgraph=True)) for _ in range(iterations)]
    finally:
        if previous_langgraph is None:
            sys.modules.pop("langgraph", None)
        else:
            sys.modules["langgraph"] = previous_langgraph
        if previous_graph is None:
            sys.modules.pop("langgraph.graph", None)
        else:
            sys.modules["langgraph.graph"] = previous_graph
    return _result(
        name="langgraph_bibliothekar_fake_installed",
        category="langgraph_flows",
        iterations=iterations,
        total_ms=sum(timings),
        details={
            "median_graph_ms": statistics.median(timings),
            "mode": "fake_installed_langgraph",
            "node_calls": len(calls),
            "node_sequence": calls[:6],
        },
    )


class _BenchmarkGraphFixture:
    def __enter__(self) -> BibliothekarService:
        self._tmp = tempfile.TemporaryDirectory(prefix="teebotus-bench-graph-")
        root = Path(self._tmp.name)
        library_dir = root / "instances" / "Bench" / "data" / "Bibliothek"
        library_dir.mkdir(parents=True)
        (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
        store = BibliothekarStore("Bench", root / "instances")
        store.rebuild()
        return BibliothekarService(LocalBibliothekarBackend(store))

    def __exit__(self, *_args: Any) -> None:
        self._tmp.cleanup()


def _copy_benchmark_books(destination: Path) -> None:
    source = REPO_ROOT / "tests" / "fixtures" / "books"
    if not source.exists():
        raise FileNotFoundError(f"benchmark fixture directory is missing: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        if path.is_file():
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


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
    mode: str = "local",
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
        "mode": str(mode or "local"),
        "live": str(mode or "").startswith("live"),
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
        "cpu_count": os.cpu_count() or 0,
        "dependencies": _dependency_context(),
    }


def _dependency_context() -> dict[str, dict[str, str]]:
    packages = (
        "teebotus",
        "litellm",
        "signalbot",
        "nio-bot",
        "matrix-nio",
        "faster-whisper",
        "pydantic-ai",
        "langgraph",
        "haystack-ai",
        "qdrant-haystack",
        "fastmcp",
    )
    context: dict[str, dict[str, str]] = {}
    for package in packages:
        if package == "teebotus":
            context[package] = {"version": TEEBOTUS_VERSION, "status": "worktree"}
            continue
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            context[package] = {"version": "", "status": "missing"}
        else:
            context[package] = {"version": version, "status": "installed"}
    return context


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
