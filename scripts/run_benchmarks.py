#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import logging
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
from scripts.check_adapter_deps import (  # noqa: E402
    LOCKFILE,
    _check_litellm_supply_chain_guard,
    _check_pyproject_plan2_contract,
    _read_pins,
)
from TeeBotus.core.youtube import YouTubeTranscriptError, _has_youtube_transcript_intent, _parse_youtube_local_options  # noqa: E402
import TeeBotus.core.youtube as youtube_module  # noqa: E402
from TeeBotus import __version__ as TEEBOTUS_VERSION  # noqa: E402
from TeeBotus.decisions import (  # noqa: E402
    ProactiveToolCallDecision,
)
from TeeBotus.embedding import FakeEmbeddingProvider, KeywordRerankerProvider  # noqa: E402
from TeeBotus.bibliothekar.source_harvester import SourceHarvester  # noqa: E402
from TeeBotus.instructions import BotInstructions  # noqa: E402
from TeeBotus.llm.profiles import select_llm_route  # noqa: E402
from TeeBotus.llm_client import LiteLLMTextClient  # noqa: E402
from TeeBotus.mcp_tools import MCPToolPolicy, MCPToolRegistry, build_readonly_mcp_registry  # noqa: E402
from TeeBotus.adapters.matrix import matrix_message_to_event, send_matrix_actions  # noqa: E402
from TeeBotus.adapters.signal import send_signal_actions, signal_message_to_event  # noqa: E402
from TeeBotus.adapters.telegram import send_telegram_actions, telegram_message_to_event  # noqa: E402
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key  # noqa: E402
from TeeBotus.runtime.actions import SendText  # noqa: E402
from TeeBotus.runtime.bibliothekar import BibliothekarStore  # noqa: E402
from TeeBotus.runtime.bibliothekar_service import (  # noqa: E402
    BibliothekarQuery,
    BibliothekarService,
    HaystackBibliothekarBackend,
    LlamaIndexBibliothekarBackend,
    LocalBibliothekarBackend,
    check_bibliothekar_service,
)
from TeeBotus.runtime.config import build_runtime_config  # noqa: E402
from TeeBotus.runtime.graphs import run_bibliothekar_deep_query, run_source_harvester_workflow  # noqa: E402
from TeeBotus.runtime.proactive_agent import (  # noqa: E402
    apply_proactive_agent_tool_calls,
    check_proactive_agent_account,
    dispatch_due_proactive_outbox_items,
    due_proactive_outbox_items,
    enable_proactive_agent,
    proactive_policy_decision,
)
from TeeBotus.runtime.postgres_memory import POSTGRES_BACKEND_ENV  # noqa: E402
from TeeBotus.runtime.sqlite_memory import SQLITE_PATH_ENV  # noqa: E402
from TeeBotus.runtime.source_quality import FakeNLIVerifier, SourceQualityPipeline  # noqa: E402
from TeeBotus.runtime.memory_fallback import WarningFallbackAccountMemoryBackend  # noqa: E402
from TeeBotus.runtime.engine import TeeBotusEngine  # noqa: E402
from TeeBotus.runtime.events import IncomingEvent  # noqa: E402
import TeeBotus.runtime.engine as engine_module  # noqa: E402
from TeeBotus.benchmarks.core import (  # noqa: E402
    BenchmarkResult,
    REQUIRED_BENCHMARK_CATEGORIES,
    REQUIRED_BENCHMARK_NAMES,
    REQUIRED_BENCHMARK_RANKING_CATEGORIES,
    STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS,
    build_comparisons as _build_comparisons,
    build_quality_gate as _build_quality_gate,
    result as _result,
    stable_backend_ranking as _stable_backend_ranking,
)
from TeeBotus.benchmarks.llm_routing import (  # noqa: E402
    benchmark_gemini_free_tier_guard,
    benchmark_llm_router,
)
from TeeBotus.benchmarks.hf_pool import (  # noqa: E402
    benchmark_hf_pool_eval_matrix as _benchmark_hf_pool_eval_matrix,
    benchmark_hf_pool_live as _benchmark_hf_pool_live,
    benchmark_hf_pool_quick as _benchmark_hf_pool_quick,
)
from TeeBotus.benchmarks.qdrant import (  # noqa: E402
    benchmark_qdrant_health_live as _benchmark_qdrant_health_live,
    benchmark_qdrant_health_quick as _benchmark_qdrant_health_quick,
    benchmark_qdrant_memory_index_quick as _benchmark_qdrant_memory_index_quick,
)
from TeeBotus.benchmarks.pydantic_ai import (  # noqa: E402
    benchmark_decision_fake_model as _benchmark_decision_fake_model,
    benchmark_pydantic_structured_decisions as _benchmark_pydantic_structured_decisions,
)
from TeeBotus.benchmarks.source_quality import (  # noqa: E402
    benchmark_source_harvester_promote_index_flow as _benchmark_source_harvester_promote_index_flow,
    benchmark_source_harvester_quality_gate as _benchmark_source_harvester_quality_gate,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic TeeBotus benchmark suite.")
    parser.add_argument("--quick", action="store_true", help="Run only local deterministic quick benchmarks.")
    parser.add_argument("--entries", type=int, default=50, help="Synthetic memory entries for quick storage benchmarks.")
    parser.add_argument("--iterations", type=int, default=50, help="Iterations for light CPU-only benchmark loops.")
    parser.add_argument("--output", default="", help="Markdown output path.")
    parser.add_argument("--json-output", default="", help="JSON output path.")
    parser.add_argument("--baseline-json", default="", help="Optional previous benchmark JSON for regression comparison.")
    parser.add_argument("--postgres-dsn", default="", help="Optional PostgreSQL DSN for live PostgreSQL memory benchmark.")
    parser.add_argument("--include-live", action="store_true", help="Allow explicitly configured live benchmarks such as PostgreSQL.")
    parser.add_argument("--live-hf", action="store_true", help="Run one explicit live hf_pool target check when configured.")
    parser.add_argument("--live-qdrant", action="store_true", help="Run one explicit live Qdrant health check against the configured/default URL.")
    parser.add_argument("--profile", default="", help="Optional LLM profile context for live HF benchmarks, e.g. hf_pool_default.")
    args = parser.parse_args(argv)
    if args.entries < 1:
        parser.error("--entries must be >= 1")
    if args.iterations < 1:
        parser.error("--iterations must be >= 1")

    suite = run_benchmarks(
        entries=args.entries,
        iterations=args.iterations,
        postgres_dsn=args.postgres_dsn,
        quick=bool(args.quick),
        include_live=bool(args.include_live),
        live_hf=bool(args.live_hf),
        live_qdrant=bool(args.live_qdrant),
        profile=str(args.profile or ""),
        baseline_json=Path(args.baseline_json) if args.baseline_json else None,
    )
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


def run_benchmarks(
    *,
    entries: int = 50,
    iterations: int = 50,
    postgres_dsn: str = "",
    quick: bool = True,
    include_live: bool = False,
    live_hf: bool = False,
    live_qdrant: bool = False,
    profile: str = "",
    baseline_json: Path | None = None,
) -> dict[str, Any]:
    results: list[BenchmarkResult] = []
    results.extend(_memory_results(entries=entries, select_runs=max(1, min(5, iterations)), postgres_dsn=postgres_dsn if include_live else ""))
    results.append(_benchmark_bibliothekar(iterations=iterations))
    results.append(_benchmark_bibliothekar_llamaindex_fake(iterations=iterations))
    results.append(_benchmark_bibliothekar_haystack_fake(iterations=iterations))
    results.append(_benchmark_retrieval_embedding_reranker_matrix(iterations=iterations))
    results.append(_benchmark_source_harvester_quality_gate(iterations=iterations))
    results.append(_benchmark_source_harvester_promote_index_flow(iterations=iterations))
    results.append(benchmark_llm_router(iterations=iterations))
    results.append(benchmark_gemini_free_tier_guard(iterations=iterations))
    results.append(_benchmark_hf_pool_quick(iterations=iterations))
    results.append(_benchmark_hf_pool_eval_matrix(iterations=iterations))
    if live_hf:
        results.append(_benchmark_hf_pool_live(profile=profile))
    results.append(_benchmark_qdrant_health_quick(iterations=iterations))
    if live_qdrant:
        results.append(_benchmark_qdrant_health_live())
    results.append(_benchmark_qdrant_memory_index_quick(iterations=iterations))
    results.append(_benchmark_decision_fake_model(iterations=iterations))
    results.append(_benchmark_pydantic_structured_decisions(iterations=iterations))
    results.append(_benchmark_proactive(iterations=iterations))
    results.append(_benchmark_adapter_contracts(iterations=iterations))
    results.append(_benchmark_youtube_parser(iterations=iterations))
    results.append(_benchmark_youtube_local_job_queue(iterations=iterations))
    results.append(_benchmark_youtube_local_pipeline_cache(iterations=iterations))
    results.append(_benchmark_status_doctor(iterations=iterations))
    results.append(_benchmark_database_fallback_policy(iterations=iterations))
    results.append(_benchmark_langgraph_flow(iterations=iterations))
    results.append(_benchmark_langgraph_linear_flow(iterations=iterations))
    results.append(_benchmark_langgraph_fake_installed_flow(iterations=iterations))
    results.append(_benchmark_langgraph_source_harvester_workflow(iterations=iterations))
    results.append(_benchmark_mcp_tools(iterations=iterations))
    comparisons = _build_comparisons(results)
    regression = _build_regression_report(results, baseline_json=baseline_json)
    live_requested = bool(include_live or live_hf or live_qdrant)
    quality_gate = _build_quality_gate(results, comparisons=comparisons, quick=quick, include_live=live_requested)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "quick": bool(quick),
        "include_live": live_requested,
        "live_hf": bool(live_hf),
        "live_qdrant": bool(live_qdrant),
        "profile": str(profile or ""),
        "ok": all(result.get("ok", False) or result.get("skipped", False) for result in results) and quality_gate["ok"] and not regression["failed"],
        "context": _context(),
        "results": results,
        "comparisons": comparisons,
        "quality_gate": quality_gate,
        "regression": regression,
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
        f"- include_live: {suite.get('include_live', False)}",
        f"- live_hf: {suite.get('live_hf', False)}",
        f"- live_qdrant: {suite.get('live_qdrant', False)}",
        f"- profile: {suite.get('profile', '')}",
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
    quality_gate = suite.get("quality_gate") if isinstance(suite.get("quality_gate"), dict) else {}
    lines.extend(["", "## Quality Gate", ""])
    lines.append(f"- status: {quality_gate.get('status', 'unknown')}")
    lines.append(f"- checked_results: {quality_gate.get('checked_results', 0)}")
    lines.append(f"- error_count: {quality_gate.get('error_count', 0)}")
    quality_errors = quality_gate.get("errors") if isinstance(quality_gate.get("errors"), list) else []
    if quality_errors:
        lines.append("")
        for error in quality_errors:
            lines.append(f"- {str(error).replace('|', '/')}")
    regression = suite.get("regression") if isinstance(suite.get("regression"), dict) else {}
    lines.extend(["", "## Regression Check", ""])
    lines.append(f"- status: {regression.get('status', 'unknown')}")
    lines.append(f"- baseline_json: {regression.get('baseline_json', '')}")
    lines.append(f"- max_total_ms_factor: {regression.get('max_total_ms_factor', '')}")
    lines.append(f"- min_throughput_factor: {regression.get('min_throughput_factor', '')}")
    entries = regression.get("entries") if isinstance(regression.get("entries"), list) else []
    if entries:
        lines.extend(
            [
                "",
                "| name | status | previous_total_ms | current_total_ms | total_ms_factor | previous_throughput | current_throughput | throughput_factor |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            lines.append(
                "| {name} | {status} | {previous_total_ms:.3f} | {current_total_ms:.3f} | {total_ms_factor:.3f} | {previous_throughput:.2f} | {current_throughput:.2f} | {throughput_factor:.3f} |".format(
                    name=entry.get("name", ""),
                    status=entry.get("status", ""),
                    previous_total_ms=float(entry.get("previous_total_ms") or 0.0),
                    current_total_ms=float(entry.get("current_total_ms") or 0.0),
                    total_ms_factor=float(entry.get("total_ms_factor") or 0.0),
                    previous_throughput=float(entry.get("previous_throughput_ops_s") or 0.0),
                    current_throughput=float(entry.get("current_throughput_ops_s") or 0.0),
                    throughput_factor=float(entry.get("throughput_factor") or 0.0),
                )
            )
    lines.append("")
    lines.append("Standard-Benchmarks nutzen keine echten Provider-Calls und keine Netzsendung.")
    return "\n".join(lines) + "\n"


def _build_regression_report(
    results: list[BenchmarkResult],
    *,
    baseline_json: Path | None,
    max_total_ms_factor: float = 2.0,
    min_throughput_factor: float = 0.5,
) -> dict[str, Any]:
    base = {
        "status": "not_configured",
        "baseline_json": str(baseline_json or ""),
        "max_total_ms_factor": max_total_ms_factor,
        "min_throughput_factor": min_throughput_factor,
        "failed": False,
        "entries": [],
    }
    if baseline_json is None:
        return base
    if not baseline_json.exists():
        return {**base, "status": "baseline_missing", "failed": True, "error": "baseline file does not exist"}
    try:
        baseline = json.loads(baseline_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {**base, "status": "baseline_unreadable", "failed": True, "error": str(exc)}
    previous_by_name = {
        str(result.get("name") or ""): result
        for result in baseline.get("results", [])
        if isinstance(result, dict) and result.get("ok") and not result.get("skipped") and str(result.get("name") or "")
    }
    entries = []
    failed = False
    for current in results:
        name = str(current.get("name") or "")
        if not name or current.get("skipped") or not current.get("ok"):
            continue
        previous = previous_by_name.get(name)
        if not previous:
            continue
        previous_total = float(previous.get("total_ms") or 0.0)
        current_total = float(current.get("total_ms") or 0.0)
        previous_throughput = float(previous.get("throughput_ops_s") or 0.0)
        current_throughput = float(current.get("throughput_ops_s") or 0.0)
        total_factor = current_total / previous_total if previous_total > 0 else 0.0
        throughput_factor = current_throughput / previous_throughput if previous_throughput > 0 else 0.0
        status = "ok"
        if previous_total > 0 and total_factor > max_total_ms_factor:
            status = "regressed"
        if previous_throughput > 0 and throughput_factor < min_throughput_factor:
            status = "regressed"
        if status == "regressed":
            failed = True
        entries.append(
            {
                "name": name,
                "status": status,
                "previous_total_ms": previous_total,
                "current_total_ms": current_total,
                "total_ms_factor": total_factor,
                "previous_throughput_ops_s": previous_throughput,
                "current_throughput_ops_s": current_throughput,
                "throughput_factor": throughput_factor,
            }
        )
    return {
        **base,
        "status": "failed" if failed else "ok",
        "failed": failed,
        "matched_results": len(entries),
        "entries": entries,
    }


def _markdown_details(details: dict[str, Any]) -> str:
    if not details:
        return ""
    rendered = json.dumps(details, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    if len(rendered) > 220:
        rendered = f"{rendered[:217]}..."
    return rendered.replace("|", "/")


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


def _benchmark_bibliothekar_llamaindex_fake(*, iterations: int) -> BenchmarkResult:
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-llamaindex-") as tmp:
        root = Path(tmp)
        library_dir = root / "instances" / "Bench" / "data" / "Bibliothek"
        _copy_benchmark_books(library_dir)
        backend = LlamaIndexBibliothekarBackend(
            instance_name="Bench",
            instances_dir=root / "instances",
            query_engine_factory=lambda source_store: _BenchmarkLlamaIndexQueryEngine(source_store),
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
        private_filter_selection = backend.search(
            BibliothekarQuery(
                text="Therapie Schlaf",
                filters={"account_id": "private-account-id", "memory_id": "mem_private"},
                max_chunks=2,
                max_prompt_chars=5000,
                max_quote_chars=500,
            )
        )
        fallback_store = backend.fallback_store
        index = json.loads(fallback_store.index_path.read_text(encoding="utf-8"))
        private_filter_prompt = private_filter_selection.prompt_text
        return _result(
            name="bibliothekar_llamaindex_fake_query",
            category="bibliothekar",
            iterations=iterations,
            total_ms=rebuild_ms + sum(timings),
            payload_bytes=fallback_store.chunks_path.stat().st_size,
            index_bytes=fallback_store.index_path.stat().st_size,
            note="fake_llamaindex_query_engine",
            details={
                "documents": len(index.get("documents", {})),
                "chunks": int(index.get("chunk_count") or 0),
                "fixture": "tests/fixtures/books",
                "query_engine": "fake_llamaindex_chunks",
                "median_query_ms": statistics.median(timings),
                "private_filter_selected_chunks": len(private_filter_selection.selected_ids),
                "private_filter_payload_leaked": any(marker in private_filter_prompt for marker in ("private-account-id", "mem_private")),
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
        private_filter_selection = backend.search(
            BibliothekarQuery(
                text="Therapie Schlaf",
                filters={"account_id": "private-account-id", "memory_id": "mem_private"},
                max_chunks=2,
                max_prompt_chars=5000,
                max_quote_chars=500,
            )
        )
        fallback_store = backend.fallback_store
        index = json.loads(fallback_store.index_path.read_text(encoding="utf-8"))
        private_filter_prompt = private_filter_selection.prompt_text
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
                "private_filter_selected_chunks": len(private_filter_selection.selected_ids),
                "private_filter_payload_leaked": any(marker in private_filter_prompt for marker in ("private-account-id", "mem_private")),
                **_bibliothekar_payload_details(selection.prompt_text),
            },
        )


def _benchmark_retrieval_embedding_reranker_matrix(*, iterations: int) -> BenchmarkResult:
    documents = [
        "Schlafhygiene und Tagesstruktur helfen bei depressiver Erschoepfung.",
        "Kaffee und Wetter sind Smalltalk und keine Therapiequelle.",
        "Aktivierung und kurze Spaziergaenge koennen stabilisieren.",
    ]
    query = "Schlaf Therapie Tagesstruktur"
    embedding_providers = [
        FakeEmbeddingProvider(model_name="intfloat/multilingual-e5-small", dimensions=16),
        FakeEmbeddingProvider(model_name="intfloat/multilingual-e5-base", dimensions=16),
        FakeEmbeddingProvider(model_name="BAAI/bge-m3", dimensions=16),
    ]
    embedding_timings: list[float] = []
    model_rankings: dict[str, list[int]] = {}
    for provider in embedding_providers:
        def run_provider(provider=provider) -> None:
            query_vector = provider.embed_text(query)
            doc_vectors = provider.embed_texts(documents, purpose="retrieval_benchmark")
            ranked = sorted(range(len(documents)), key=lambda index: _vector_cosine(query_vector, doc_vectors[index]), reverse=True)
            model_rankings[provider.model_name] = ranked

        embedding_timings.extend(_timed_ms(run_provider) for _ in range(iterations))

    reranker = KeywordRerankerProvider(model_name="BAAI/bge-reranker-v2-m3")
    reranker_timings = [_timed_ms(lambda: reranker.rerank(query, documents, top_k=2)) for _ in range(iterations)]
    reranked = reranker.rerank(query, documents, top_k=2)
    without_reranker_top = model_rankings.get("BAAI/bge-m3", [])[:2]
    with_reranker_top = [item.index for item in reranked]

    backend_timings: dict[str, float] = {}
    backend_selected: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-retrieval-") as tmp:
        root = Path(tmp)
        library_dir = root / "instances" / "Bench" / "data" / "Bibliothek"
        _copy_benchmark_books(library_dir)
        store = BibliothekarStore("Bench", root / "instances")
        local_backend = LocalBibliothekarBackend(store)
        local_backend.rebuild()
        backend_timings["local"] = sum(_timed_ms(lambda: local_backend.search(BibliothekarQuery(text=query, max_chunks=2))) for _ in range(iterations))
        backend_selected["local"] = len(local_backend.search(BibliothekarQuery(text=query, max_chunks=2)).selected_ids)

        document_store = _BenchmarkDocumentStore()
        haystack_backend = HaystackBibliothekarBackend(
            instance_name="Bench",
            instances_dir=root / "instances",
            collection="bench_books",
            document_store_factory=lambda: document_store,
            document_class=_BenchmarkDocument,
        )
        haystack_backend.rebuild()
        backend_timings["haystack_fake"] = sum(_timed_ms(lambda: haystack_backend.search(BibliothekarQuery(text=query, max_chunks=2))) for _ in range(iterations))
        backend_selected["haystack_fake"] = len(haystack_backend.search(BibliothekarQuery(text=query, max_chunks=2)).selected_ids)

        llama_backend = LlamaIndexBibliothekarBackend(
            instance_name="Bench",
            instances_dir=root / "instances",
            query_engine_factory=lambda source_store: _BenchmarkLlamaIndexQueryEngine(source_store),
        )
        backend_timings["llamaindex_fake"] = sum(_timed_ms(lambda: llama_backend.search(BibliothekarQuery(text=query, max_chunks=2))) for _ in range(iterations))
        backend_selected["llamaindex_fake"] = len(llama_backend.search(BibliothekarQuery(text=query, max_chunks=2)).selected_ids)

        payload_bytes = store.chunks_path.stat().st_size
        index_bytes = store.index_path.stat().st_size

    ok = (
        {"intfloat/multilingual-e5-small", "intfloat/multilingual-e5-base", "BAAI/bge-m3"}.issubset(model_rankings)
        and reranked
        and all(count >= 1 for count in backend_selected.values())
    )
    return _result(
        name="retrieval_embedding_reranker_matrix",
        category="retrieval",
        iterations=iterations * (len(embedding_providers) + 1 + len(backend_timings)),
        total_ms=sum(embedding_timings) + sum(reranker_timings) + sum(backend_timings.values()),
        ok=ok,
        errors=0 if ok else 1,
        payload_bytes=payload_bytes,
        index_bytes=index_bytes,
        note="local_embedding_reranker_backend_matrix",
        details={
            "usermemory_models": ["intfloat/multilingual-e5-small", "intfloat/multilingual-e5-base"],
            "book_models": ["BAAI/bge-m3", "intfloat/multilingual-e5-base"],
            "model_rankings": model_rankings,
            "reranker": reranker.model_name,
            "reranker_backend": "keyword_overlap_fake",
            "reranker_comparison": {
                "without_reranker_model": "BAAI/bge-m3",
                "without_reranker_top": without_reranker_top,
                "with_reranker_model": reranker.model_name,
                "with_reranker_top": with_reranker_top,
                "changed_order": without_reranker_top != with_reranker_top,
            },
            "reranked_top": with_reranker_top,
            "backend_modes": ["local", "llamaindex_fake", "haystack_fake"],
            "backend_selected": backend_selected,
            "backend_total_ms": backend_timings,
            "network_calls": 0,
            "provider_calls": 0,
        },
    )


def _bibliothekar_payload_details(prompt_text: str) -> dict[str, Any]:
    required_fields = {
        "chunk_id",
        "source_id",
        "file",
        "file_path",
        "file_sha256",
        "file_type",
        "language",
        "locator",
        "license",
        "source_quality",
        "citation_quality",
        "ingested_at",
        "chunk_index",
        "embedding_model",
        "citation_format",
    }
    try:
        payload = json.loads(prompt_text)
    except json.JSONDecodeError:
        return {
            "citation_payload_bytes": len(prompt_text.encode("utf-8")),
            "selected_chunks": 0,
            "has_citation_format": False,
            "citation_required_fields": sorted(required_fields),
            "citation_missing_fields": sorted(required_fields),
            "provenance_fields_complete": False,
        }
    chunks = payload.get("selected_library_chunks") if isinstance(payload, dict) else None
    selected_chunks = chunks if isinstance(chunks, list) else []
    missing_fields = sorted(
        {
            field
            for chunk in selected_chunks
            if isinstance(chunk, dict)
            for field in required_fields
            if field not in chunk or chunk.get(field) in ("", None)
        }
    )
    return {
        "citation_payload_bytes": len(prompt_text.encode("utf-8")),
        "selected_chunks": len(selected_chunks),
        "has_citation_format": all(bool(chunk.get("citation_format")) for chunk in selected_chunks if isinstance(chunk, dict)),
        "citation_required_fields": sorted(required_fields),
        "citation_missing_fields": missing_fields,
        "provenance_fields_complete": bool(selected_chunks) and not missing_fields,
    }


def _vector_cosine(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    numerator = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = sum(float(value) * float(value) for value in left) ** 0.5
    right_norm = sum(float(value) * float(value) for value in right) ** 0.5
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _benchmark_proactive(*, iterations: int) -> BenchmarkResult:
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-proactive-") as tmp:
        store = AccountStore(Path(tmp) / "accounts", "Bench", StaticSecretProvider(b"p" * 32))
        identity = signal_identity_key(source_uuid="bench")
        account_id = store.resolve_or_create_account(identity)
        store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
        enable_proactive_agent(store, account_id, categories=("reminder", "analysis"))
        store.append_structured_memory_entry(
            account_id,
            {
                "id": "mem_bench_goal",
                "kind": "therapy_goal",
                "user_text": "Der Nutzer moechte morgens kurz an den Spaziergang erinnert werden.",
                "created_at": "2026-06-16T07:30:00+00:00",
                "updated_at": "2026-06-16T07:30:00+00:00",
            },
        )
        now = datetime(2026, 6, 16, 10, 30, tzinfo=timezone.utc)
        safe_tool = {
            "name": "proactive_queue_message",
            "arguments": {
                "category": "reminder",
                "intent": "bench_follow_up",
                "message_text": "Benchmark: Magst du kurz berichten, ob der Spaziergang geklappt hat?",
                "reason_memory_ids": ["mem_bench_goal"],
                "risk_gate": "none",
                "due_at": "2026-06-16T10:00:00+00:00",
            },
        }
        review_tool = {
            "name": "proactive_queue_message",
            "arguments": {
                "category": "analysis",
                "intent": "bench_review_only",
                "message_text": "Benchmark: Analysevorschlag nur nach Review.",
                "reason_memory_ids": ["mem_bench_goal"],
                "risk_gate": "needs_review",
                "due_at": "2026-06-16T10:00:00+00:00",
            },
        }
        validation_timings = [
            _timed_ms(lambda: (ProactiveToolCallDecision.model_validate(safe_tool), ProactiveToolCallDecision.model_validate(review_tool)))
            for _ in range(iterations)
        ]
        planning_results = []
        planning_ms = _timed_ms(
            lambda: planning_results.append(
                apply_proactive_agent_tool_calls(store, account_id, (safe_tool, review_tool), now=now)
            )
        )
        timings = [_timed_ms(lambda: due_proactive_outbox_items(store, account_id, now=now)) for _ in range(iterations)]
        policy_results = []
        policy_ms = _timed_ms(lambda: policy_results.append(proactive_policy_decision(store, account_id, category="reminder", now=now)))
        sent_actions: list[str] = []

        def fake_sender(_route: dict[str, Any], action: Any, _item: dict[str, Any]) -> str:
            sent_actions.append(str(getattr(action, "text", "")))
            return "bench-sent-ref"

        dispatch_results = []
        dispatch_ms = _timed_ms(
            lambda: dispatch_results.extend(
                asyncio.run(
                    dispatch_due_proactive_outbox_items(
                        store,
                        account_id,
                        senders={"signal": fake_sender},
                        now=now,
                        instance_name="Bench",
                    )
                )
            )
        )
        health = check_proactive_agent_account(store, account_id)
        planning_result = planning_results[0] if planning_results else None
        queued_items = store.read_proactive_outbox(account_id)
        sent_count = sum(1 for item in queued_items if str(item.get("status") or "") == "sent")
        review_pending_count = sum(1 for item in queued_items if str(item.get("status") or "") == "review_pending")
        ok = (
            planning_result is not None
            and not planning_result.errors
            and len(planning_result.queued_item_ids) == 2
            and len(dispatch_results) == 1
            and dispatch_results[0].status == "sent"
            and sent_count == 1
            and review_pending_count == 1
            and health.review_pending_count == 1
            and len(sent_actions) == 1
        )
        return _result(
            name="proactive_tool_plan_due_dispatch_gates",
            category="proactive_agent",
            iterations=iterations * 2 + 3,
            total_ms=sum(validation_timings) + planning_ms + sum(timings) + policy_ms + dispatch_ms,
            ok=ok,
            errors=0 if ok else 1,
            payload_bytes=sum(len(json.dumps(item, ensure_ascii=False)) for item in queued_items),
            details={
                "tool_schema_validated": True,
                "tool_plan_errors": list(planning_result.errors) if planning_result else ["missing_planning_result"],
                "tool_queued_item_ids": list(planning_result.queued_item_ids) if planning_result else [],
                "queued": len(queued_items),
                "sent": sent_count,
                "review_pending": review_pending_count,
                "due_after_review_gate": len(due_proactive_outbox_items(store, account_id, now=now)),
                "dispatch_simulated": len(dispatch_results),
                "dispatch_statuses": [result.status for result in dispatch_results],
                "policy_allowed": policy_results[0].allowed if policy_results else False,
                "health_ok_with_review_pending": health.ok,
                "health_review_pending": health.review_pending_count,
                "median_tool_validation_ms": statistics.median(validation_timings),
                "planning_ms": planning_ms,
                "median_due_ms": statistics.median(timings),
                "policy_ms": policy_ms,
                "dispatch_ms": dispatch_ms,
                "network_calls": 0,
            },
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
    runtime_timings = []
    runtime_checks: list[dict[str, Any]] = []
    for _ in range(iterations):
        runtime_timings.append(_timed_ms(lambda: runtime_checks.append(_messenger_adapter_runtime_contract())))
    runtime_errors = sum(1 for check_result in runtime_checks if not check_result.get("ok"))
    latest_runtime = runtime_checks[-1] if runtime_checks else {}
    return _result(
        name="messenger_adapter_runtime_contracts",
        category="messenger_adapters",
        iterations=iterations * 2,
        total_ms=sum(timings) + sum(runtime_timings),
        ok=errors == 0 and runtime_errors == 0,
        errors=errors + runtime_errors,
        payload_bytes=int(latest_runtime.get("payload_bytes") or 0),
        index_bytes=len(json.dumps({"packages": packages}, ensure_ascii=False).encode("utf-8")),
        details={
            "packages": packages,
            "version_reads": len(versions),
            "channels": ["telegram", "signal", "matrix"],
            "event_contracts": latest_runtime.get("event_contracts", {}),
            "send_contracts": latest_runtime.get("send_contracts", {}),
            "fake_network_sends": latest_runtime.get("fake_network_sends", 0),
            "network_calls": 0,
            "median_runtime_contract_ms": statistics.median(runtime_timings) if runtime_timings else 0.0,
        },
    )


def _messenger_adapter_runtime_contract() -> dict[str, Any]:
    telegram_api = _FakeTelegramAPI()
    telegram_event = telegram_message_to_event(
        {
            "message_id": 42,
            "chat": {"id": 1001, "type": "private"},
            "from": {"id": 2002, "first_name": "Ada", "username": "ada"},
            "text": "Hallo TeeBotus",
        },
        instance="Bench",
        adapter_slot=1,
    )
    telegram_refs = send_telegram_actions(telegram_api, [SendText("1001", "Telegram OK")])

    signal_message = _FakeSignalMessage()
    signal_event = signal_message_to_event(signal_message, instance="Bench", adapter_slot=1)
    signal_context = _FakeSignalContext(signal_message)
    signal_refs = asyncio.run(send_signal_actions(signal_context, [SendText("+491", "Signal OK")]))

    matrix_room = _FakeMatrixRoom()
    matrix_message = _FakeMatrixMessage()
    matrix_event = matrix_message_to_event(matrix_room, matrix_message, instance="Bench", adapter_slot=1)
    matrix_client = _FakeMatrixClient()
    matrix_refs = asyncio.run(send_matrix_actions(matrix_client, [SendText("!room:example", "Matrix OK")]))

    event_contracts = {
        "telegram": _adapter_event_contract(telegram_event, channel="telegram", chat_id="1001"),
        "signal": _adapter_event_contract(signal_event, channel="signal", chat_id="+491"),
        "matrix": _adapter_event_contract(matrix_event, channel="matrix", chat_id="!room:example"),
    }
    send_contracts = {
        "telegram": telegram_refs == [10001] and telegram_api.sent == [("1001", "Telegram OK")],
        "signal": signal_refs == [20001] and signal_context.sent == ["Signal OK"],
        "matrix": matrix_refs == ["$bench"] and matrix_client.sent_texts == [("!room:example", "Matrix OK")],
    }
    payload_texts = [
        telegram_event.text if telegram_event else "",
        signal_event.text if signal_event else "",
        matrix_event.text if matrix_event else "",
        *[text for _chat_id, text in telegram_api.sent],
        *signal_context.sent,
        *[text for _room_id, text in matrix_client.sent_texts],
    ]
    return {
        "ok": all(event_contracts.values()) and all(send_contracts.values()),
        "event_contracts": event_contracts,
        "send_contracts": send_contracts,
        "fake_network_sends": len(telegram_api.sent) + len(signal_context.sent) + len(matrix_client.sent_texts),
        "payload_bytes": sum(len(text.encode("utf-8")) for text in payload_texts),
    }


def _adapter_event_contract(event: Any, *, channel: str, chat_id: str) -> bool:
    return (
        event is not None
        and getattr(event, "channel", "") == channel
        and str(getattr(event, "chat_id", "")) == chat_id
        and bool(str(getattr(event, "identity_key", "")).strip())
        and bool(str(getattr(event, "text", "")).strip())
    )


class _FakeTelegramAPI:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_message(self, chat_id: Any, text: str) -> int:
        self.sent.append((str(chat_id), str(text)))
        return 10001


class _FakeSignalMessage:
    source_uuid = "signal-source-uuid"
    source_number = "+492"
    source = "+492"
    text = "Hallo Signal"
    timestamp = 123456789
    group = None
    attachments_local_filenames: list[str] = []
    base64_attachments: list[str] = []
    view_once = False

    def recipient(self) -> str:
        return "+491"


class _FakeSignalContext:
    def __init__(self, message: _FakeSignalMessage) -> None:
        self.message = message
        self.sent: list[str] = []

    async def send(self, text: str, **_kwargs: Any) -> int:
        self.sent.append(str(text))
        return 20001


class _FakeMatrixRoom:
    room_id = "!room:example"
    joined_count = 2
    invited_count = 0


class _FakeMatrixMessage:
    sender = "@ada:example"
    event_id = "$incoming"
    body = "Hallo Matrix"
    formatted_body = ""
    source = {"content": {"body": "Hallo Matrix", "msgtype": "m.text"}}


class _FakeMatrixResponse:
    event_id = "$bench"


class _FakeMatrixClient:
    def __init__(self) -> None:
        self.sent_texts: list[tuple[str, str]] = []

    async def send_message(self, room_id: str, text: str, **_kwargs: Any) -> _FakeMatrixResponse:
        self.sent_texts.append((str(room_id), str(text)))
        return _FakeMatrixResponse()

    async def room_send(self, *, room_id: str, content: dict[str, Any], **_kwargs: Any) -> _FakeMatrixResponse:
        self.sent_texts.append((str(room_id), str(content.get("body") or "")))
        return _FakeMatrixResponse()


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
        payload_bytes=sum(len(sample.encode("utf-8")) for sample in samples),
        index_bytes=len(json.dumps({"samples": len(samples)}, ensure_ascii=False).encode("utf-8")),
        details={"intent_hits": hit_count, "sample_count": len(samples), "median_batch_ms": statistics.median(timings)},
    )


def _benchmark_youtube_local_job_queue(*, iterations: int) -> BenchmarkResult:
    original_transcribe = engine_module.transcribe_youtube_video
    transcribe_calls: list[dict[str, Any]] = []
    dispatched_texts: list[str] = []
    started_jobs = 0

    class FakeRunner:
        def submit(self, callback: Callable[[], Any]) -> object:
            nonlocal started_jobs
            started_jobs += 1
            callback()
            return object()

    class CountingLLMClient:
        def __init__(self) -> None:
            self.calls = 0

        def create_reply(self, *_args: Any, **_kwargs: Any) -> Any:
            self.calls += 1
            raise AssertionError("benchmark must not call LLM")

    def fake_transcribe(_url: str, **kwargs: Any) -> tuple[str, str]:
        transcribe_calls.append(dict(kwargs))
        if kwargs.get("local_allowed") is False:
            raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True)
        return "Lokales Benchmark-Transkript.", "lokales Whisper"

    try:
        engine_module.transcribe_youtube_video = fake_transcribe
        with tempfile.TemporaryDirectory(prefix="teebotus-bench-youtube-engine-") as tmp:
            store = AccountStore(Path(tmp) / "accounts", "Bench", StaticSecretProvider(b"y" * 32))
            identity = signal_identity_key(source_uuid="bench-youtube")
            client = CountingLLMClient()
            engine = TeeBotusEngine(
                account_store=store,
                instructions=BotInstructions(openai_enabled=True, youtube_option_llm_fallback=False),
                openai_client=client,
                youtube_job_runner=FakeRunner(),
                background_action_dispatcher=lambda _event, actions: dispatched_texts.extend(
                    str(getattr(action, "text", "")) for action in actions if getattr(action, "text", "")
                ),
            )

            def run_once(index: int) -> None:
                event = IncomingEvent(
                    event_id=f"signal:{index}",
                    instance="Bench",
                    channel="signal",
                    adapter_slot=1,
                    account_id="",
                    identity_key=identity,
                    chat_id="chat-1",
                    chat_type="private",
                    sender_id=identity,
                    sender_name=identity,
                    text="/youtube_transcript https://youtu.be/dQw4w9WgXcQ mach bitte die passende variante",
                    message_ref=str(index),
                )
                engine.process(event)

            timings = [_timed_ms(lambda index=index: run_once(index)) for index in range(iterations)]
            expected_transcribe_calls = iterations * 2
            errors = 0
            if client.calls:
                errors += client.calls
            if len(transcribe_calls) != expected_transcribe_calls:
                errors += 1
            if started_jobs != iterations:
                errors += 1
            if len(dispatched_texts) != iterations:
                errors += 1
            if not all("Lokales Benchmark-Transkript." in text for text in dispatched_texts):
                errors += 1
            return _result(
                name="youtube_local_job_queue_no_llm",
                category="transcription_youtube",
                iterations=iterations,
                total_ms=sum(timings),
                ok=errors == 0,
                errors=errors,
                payload_bytes=sum(len(text.encode("utf-8")) for text in dispatched_texts),
                note="fake_local_transcription_no_provider_calls",
                details={
                    "started_jobs": started_jobs,
                    "background_dispatches": len(dispatched_texts),
                    "transcribe_calls": len(transcribe_calls),
                    "llm_calls": client.calls,
                    "median_engine_ms": statistics.median(timings),
                    "network_calls": 0,
                },
            )
    finally:
        engine_module.transcribe_youtube_video = original_transcribe


def _benchmark_youtube_local_pipeline_cache(*, iterations: int) -> BenchmarkResult:
    original_which = youtube_module.shutil.which
    original_download_subtitles = youtube_module._download_youtube_subtitles
    original_transcribe_whisper = youtube_module._transcribe_youtube_audio_with_whisper
    original_runtime_dir = youtube_module.runtime_dir
    subtitle_calls = 0
    whisper_calls = 0
    live_chunks = 0
    transcripts: list[str] = []
    sources: list[str] = []

    def fake_which(command: str) -> str | None:
        if command == "yt-dlp":
            return "/usr/bin/yt-dlp"
        return original_which(command)

    def fake_download_subtitles(_url: str, _workdir: Path, instance_name: str = "") -> str:
        nonlocal subtitle_calls
        subtitle_calls += 1
        return ""

    def fake_transcribe_whisper(_url: str, _workdir: Path, live_callback=None, instance_name: str = "") -> str:
        nonlocal whisper_calls, live_chunks
        whisper_calls += 1
        if callable(live_callback):
            live_callback(f"Benchmark-Chunk {whisper_calls}")
            live_chunks += 1
        return f"Lokales Whisper Benchmark Transkript {whisper_calls}."

    try:
        with tempfile.TemporaryDirectory(prefix="teebotus-bench-youtube-pipeline-") as tmp:
            root = Path(tmp)
            youtube_module.shutil.which = fake_which
            youtube_module._download_youtube_subtitles = fake_download_subtitles
            youtube_module._transcribe_youtube_audio_with_whisper = fake_transcribe_whisper
            youtube_module.runtime_dir = lambda: root / "runtime"
            live_events: list[str] = []
            pipeline_timings = []
            cache_timings = []
            for index in range(iterations):
                url = f"https://youtube.com/watch?v=bench{index:04d}"
                pipeline_timings.append(
                    _timed_ms(
                        lambda url=url: _collect_youtube_transcript(
                            url,
                            transcripts=transcripts,
                            sources=sources,
                            live_events=live_events,
                        )
                    )
                )
                cache_timings.append(
                    _timed_ms(
                        lambda url=url: _collect_youtube_transcript(
                            url,
                            transcripts=transcripts,
                            sources=sources,
                            live_events=live_events,
                        )
                    )
                )
            cache_dir = root / "runtime" / "youtube_transcripts"
            cache_files = sorted(cache_dir.glob("*.txt")) if cache_dir.exists() else []
            cache_bytes = sum(path.stat().st_size for path in cache_files)
            whisper_sources = sources[0::2]
            cache_sources = sources[1::2]
            errors = 0
            if subtitle_calls != iterations:
                errors += 1
            if whisper_calls != iterations:
                errors += 1
            if len(cache_files) != iterations:
                errors += 1
            if whisper_sources != ["lokales Whisper"] * iterations:
                errors += 1
            if cache_sources != ["Cache"] * iterations:
                errors += 1
            if live_chunks != iterations or len(live_events) != iterations:
                errors += 1
            return _result(
                name="youtube_local_pipeline_cache_no_openai",
                category="transcription_youtube",
                iterations=iterations * 2,
                total_ms=sum(pipeline_timings) + sum(cache_timings),
                ok=errors == 0,
                errors=errors,
                payload_bytes=sum(len(text.encode("utf-8")) for text in transcripts),
                index_bytes=cache_bytes,
                note="fake_yt_dlp_and_whisper_cache_no_provider_calls",
                details={
                    "subtitle_attempts": subtitle_calls,
                    "whisper_calls": whisper_calls,
                    "cache_reads": cache_sources.count("Cache"),
                    "cache_files": len(cache_files),
                    "live_chunks": live_chunks,
                    "median_pipeline_ms": statistics.median(pipeline_timings) if pipeline_timings else 0.0,
                    "median_cache_ms": statistics.median(cache_timings) if cache_timings else 0.0,
                    "openai_calls": 0,
                    "network_calls": 0,
                },
            )
    finally:
        youtube_module.shutil.which = original_which
        youtube_module._download_youtube_subtitles = original_download_subtitles
        youtube_module._transcribe_youtube_audio_with_whisper = original_transcribe_whisper
        youtube_module.runtime_dir = original_runtime_dir


def _collect_youtube_transcript(url: str, *, transcripts: list[str], sources: list[str], live_events: list[str]) -> None:
    transcript, source = youtube_module.transcribe_youtube_video(
        url,
        local_allowed=True,
        live_callback=lambda chunk: live_events.append(str(chunk)),
        instance_name="Bench",
    )
    transcripts.append(transcript)
    sources.append(source)


def _benchmark_status_doctor(*, iterations: int) -> BenchmarkResult:
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-status-") as tmp:
        root = Path(tmp)
        instances_dir = root / "instances"
        instance_dir = instances_dir / "Bench"
        instance_dir.mkdir(parents=True)
        (instance_dir / "Bot_Verhalten.md").write_text(
            "## LLM\n- enabled: true\n- profile: local_ollama\n\n## Bibliothekar\n- enabled: true\n- backend: local\n",
            encoding="utf-8",
        )
        env = {
            "TEEBOTUS_INSTANCES_DIR": str(instances_dir),
            "TEEBOTUS_INSTANCE": "Bench",
            "TELEGRAM_BOT_TOKEN_BENCH": "telegram-token",
            "SIGNAL_BOT_SERVICE_BENCH": "http://127.0.0.1:8080",
            "SIGNAL_BOT_PHONE_NUMBER_BENCH": "+491",
            "MATRIX_BOT_HOMESERVER_BENCH": "https://matrix.example",
            "MATRIX_BOT_USER_ID_BENCH": "@bench:example",
            "MATRIX_BOT_ACCESS_TOKEN_BENCH": "matrix-token",
            "TEEBOTUS_LLM_PROFILE_BENCH": "local_ollama",
        }
        instructions = BotInstructions(bibliothekar_backend="local")
        health_timings = [_timed_ms(lambda: check_bibliothekar_service("Bench", instances_dir, instructions)) for _ in range(iterations)]
        config_results = []
        config_timings = [
            _timed_ms(lambda: config_results.append(build_runtime_config(env=env, cli_channels="telegram,signal,matrix")))
            for _ in range(iterations)
        ]
        pins = _read_pins(LOCKFILE)
        dependency_checks = []
        dependency_timings = [
            _timed_ms(
                lambda: dependency_checks.extend(
                    [
                        _check_pyproject_plan2_contract(),
                        _check_litellm_supply_chain_guard(pins["litellm"]),
                    ]
                )
            )
            for _ in range(iterations)
        ]
        latest_config = config_results[-1] if config_results else None
        latest_health = check_bibliothekar_service("Bench", instances_dir, instructions)
        latest_dependency_checks = dependency_checks[-2:] if len(dependency_checks) >= 2 else dependency_checks
        dependency_ok = all(ok for ok, _message in latest_dependency_checks)
        runtime_channels = list(latest_config.channels) if latest_config is not None else []
        runtime_accounts = sum(len(instance.accounts) for instance in latest_config.instances) if latest_config is not None else 0
        decision_route = select_llm_route("structured_decision")
        from TeeBotus.runtime.crew_pilots import crew_pilot_status_lines

        crew_lines = crew_pilot_status_lines(dependency_available=False)
        ok = (
            latest_config is not None
            and runtime_channels == ["telegram", "signal", "matrix"]
            and runtime_accounts == 3
            and latest_health.status == "ready"
            and decision_route.provider == "hf_pool"
            and bool(crew_lines)
            and dependency_ok
        )
        return _result(
            name="status_doctor_runtime_dependency_health",
            category="status_doctor",
            iterations=iterations * 3,
            total_ms=sum(health_timings) + sum(config_timings) + sum(dependency_timings),
            ok=ok,
            errors=0 if ok else 1,
            payload_bytes=len(json.dumps(env, ensure_ascii=False).encode("utf-8")),
            index_bytes=LOCKFILE.stat().st_size if LOCKFILE.exists() else 0,
            details={
                "runtime_instances": list(latest_config.selected_instances) if latest_config is not None else [],
                "runtime_channels": runtime_channels,
                "runtime_accounts": runtime_accounts,
                "bibliothekar_status": latest_health.status,
                "bibliothekar_backend": latest_health.backend,
                "decision_provider": decision_route.provider,
                "decision_model": decision_route.model,
                "decision_profile": decision_route.profile_name,
                "crew_pilot_lines": len(crew_lines),
                "dependency_checks": [message for _ok, message in latest_dependency_checks],
                "dependency_ok": dependency_ok,
                "median_runtime_config_ms": statistics.median(config_timings),
                "median_backend_health_ms": statistics.median(health_timings),
                "median_dependency_check_ms": statistics.median(dependency_timings),
            },
        )


def _benchmark_database_fallback_policy(*, iterations: int) -> BenchmarkResult:
    class Backend:
        def __init__(self, *, fail_write: bool = False) -> None:
            self.fail_write = fail_write
            self.entries: dict[str, list[dict[str, str]]] = {}
            self.indexes: dict[str, dict[str, Any]] = {}
            self.write_entries_count = 0
            self.write_index_count = 0

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            self.write_entries_count += 1
            if self.fail_write:
                raise OSError("primary unavailable")
            self.entries[account_id] = [dict(row) for row in rows]

        def read_index(self, account_id: str) -> dict[str, Any]:
            return dict(self.indexes.get(account_id, {}))

        def write_index(self, account_id: str, data: dict[str, Any]) -> None:
            self.write_index_count += 1
            if self.fail_write:
                raise OSError("primary unavailable")
            self.indexes[account_id] = dict(data)

    class CountingCriticalHandler(logging.Handler):
        def __init__(self) -> None:
            super().__init__(level=logging.CRITICAL)
            self.messages: list[str] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.messages.append(record.getMessage())

    primary = Backend(fail_write=True)
    secondary = Backend()
    backend = WarningFallbackAccountMemoryBackend(primary, secondary, label="Bench:sqlite")
    account_id = "b" * 128
    handler = CountingCriticalHandler()
    logger = logging.getLogger("TeeBotus")
    logger.addHandler(handler)
    previous_level = logger.level
    logger.setLevel(min(previous_level, logging.CRITICAL) if previous_level else logging.CRITICAL)
    try:
        timings = []
        for index in range(iterations):
            entry = {"id": f"mem_fallback_{index:06d}", "user_text": "Fallback Benchmark"}
            timings.append(_timed_ms(lambda entry=entry: backend.write_entries(account_id, [entry])))
            timings.append(
                _timed_ms(
                    lambda index=index: backend.write_index(
                        account_id,
                        {
                            "scope": "account",
                            "index": {"entries": {f"mem_fallback_{index:06d}": {}}},
                        },
                    )
                )
            )
        primary.fail_write = False
        timings.append(_timed_ms(lambda: backend.read_entries(account_id)))
        timings.append(_timed_ms(lambda: backend.read_index(account_id)))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
    synced_entries = primary.entries.get(account_id) == secondary.entries.get(account_id)
    synced_index = primary.indexes.get(account_id) == secondary.indexes.get(account_id)
    warning_count = sum(1 for message in handler.messages if "ACCOUNT MEMORY PRIMARY DATABASE FAILED" in message)
    recovery_count = sum(1 for message in handler.messages if "primary backend recovered" in message)
    errors = 0
    if not synced_entries:
        errors += 1
    if not synced_index:
        errors += 1
    if warning_count < 1:
        errors += 1
    if recovery_count < 1:
        errors += 1
    return _result(
        name="database_fallback_policy",
        category="database_fallback",
        iterations=iterations * 2 + 2,
        total_ms=sum(timings),
        ok=errors == 0,
        errors=errors,
        payload_bytes=sum(len(json.dumps(row, ensure_ascii=False)) for row in primary.entries.get(account_id, [])),
        note="primary_failure_secondary_sync_recovery_warning",
        details={
            "primary": "sqlite-primary",
            "secondary": "sqlite-fallback",
            "fallback_warnings": warning_count,
            "recovery_warnings": recovery_count,
            "synced_entries": synced_entries,
            "synced_index": synced_index,
            "primary_entry_writes": primary.write_entries_count,
            "secondary_entry_writes": secondary.write_entries_count,
            "primary_index_writes": primary.write_index_count,
            "secondary_index_writes": secondary.write_index_count,
            "median_operation_ms": statistics.median(timings),
        },
    )


def _benchmark_langgraph_flow(*, iterations: int) -> BenchmarkResult:
    with _BenchmarkGraphFixture() as service:
        timings = [_timed_ms(lambda: run_bibliothekar_deep_query(service, "Bibliothek Therapie", prefer_langgraph=True)) for _ in range(iterations)]
        return _result(
            name="langgraph_bibliothekar_deep_query",
            category="langgraph_flows",
            iterations=iterations,
            total_ms=sum(timings),
            payload_bytes=_bibliothekar_selection_payload_bytes(service),
            index_bytes=_bibliothekar_fixture_index_bytes(service),
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
            payload_bytes=_bibliothekar_selection_payload_bytes(service),
            index_bytes=_bibliothekar_fixture_index_bytes(service),
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
        payload_bytes=sum(len(name.encode("utf-8")) for name in calls),
        index_bytes=len(json.dumps({"node_sequence": calls[:6]}, ensure_ascii=False).encode("utf-8")),
        details={
            "median_graph_ms": statistics.median(timings),
            "mode": "fake_installed_langgraph",
            "node_calls": len(calls),
            "node_sequence": calls[:6],
        },
    )


def _benchmark_langgraph_source_harvester_workflow(*, iterations: int) -> BenchmarkResult:
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-harvester-graph-") as tmp:
        root = Path(tmp)
        incoming = root / "incoming"
        incoming.mkdir(parents=True)
        harvester = SourceHarvester(
            root / "library",
            quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.9)),
        )
        states = []

        def run_once(index: int) -> None:
            source = incoming / f"workflow-{index}.pdf"
            source.write_text(f"Therapie Schlaf Workflow {index}.", encoding="utf-8")
            states.append(
                run_source_harvester_workflow(
                    harvester,
                    source,
                    metadata={"title": f"Workflow {index}", "license": "private"},
                    claims=("Schlafhygiene ist relevant.",),
                    evidence=("Therapie Schlaf Workflow.",),
                    prefer_langgraph=True,
                )
            )

        timings = [_timed_ms(lambda index=index: run_once(index)) for index in range(iterations)]
        status_counts: dict[str, int] = {}
        for state in states:
            status = str(state.get("status") or "")
            status_counts[status] = status_counts.get(status, 0) + 1
        accepted_dir = root / "library" / "accepted"
        accepted_bytes = sum(path.stat().st_size for path in accepted_dir.glob("*") if path.is_file())
        manifest_path = root / "library" / "harvest_manifest.jsonl"
        return _result(
            name="langgraph_source_harvester_workflow",
            category="langgraph_flows",
            iterations=iterations,
            total_ms=sum(timings),
            payload_bytes=accepted_bytes,
            index_bytes=manifest_path.stat().st_size if manifest_path.exists() else 0,
            details={
                "median_graph_ms": statistics.median(timings),
                "mode": "langgraph_or_linear_fallback",
                "statuses": status_counts,
                "ready_for_ingest": status_counts.get("ready_for_ingest", 0),
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


def _bibliothekar_selection_payload_bytes(service: BibliothekarService) -> int:
    selection = service.search("Bibliothek Therapie", max_chunks=2)
    return len(selection.prompt_text.encode("utf-8"))


def _bibliothekar_fixture_index_bytes(service: BibliothekarService) -> int:
    backend = getattr(service, "backend", None)
    store = getattr(backend, "store", None)
    index_path = getattr(store, "index_path", None)
    if isinstance(index_path, Path) and index_path.exists():
        return index_path.stat().st_size
    return len(json.dumps({"backend": service.backend_name, "collection": service.collection}, ensure_ascii=False).encode("utf-8"))


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
        return _result(
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
        "pydantic-ai-slim",
        "langgraph",
        "haystack-ai",
        "llama-index-core",
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


class _BenchmarkLlamaIndexQueryEngine:
    def __init__(self, source_store: BibliothekarStore) -> None:
        source_store.ensure_current()
        self.chunks = [json.loads(line) for line in source_store.chunks_path.read_text(encoding="utf-8").splitlines()]
        self.queries: list[str] = []

    def search(self, query_text: str) -> list[dict[str, Any]]:
        self.queries.append(query_text)
        return list(self.chunks)


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
