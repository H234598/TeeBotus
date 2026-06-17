from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from TeeBotus.benchmarks.adapters import benchmark_adapter_contracts as _benchmark_adapter_contracts
from TeeBotus.benchmarks.bibliothekar import (
    benchmark_bibliothekar_haystack_fake_query as _benchmark_bibliothekar_haystack_fake,
    benchmark_bibliothekar_llamaindex_fake_query as _benchmark_bibliothekar_llamaindex_fake,
    benchmark_bibliothekar_local_query as _benchmark_bibliothekar,
    benchmark_retrieval_embedding_reranker_matrix as _benchmark_retrieval_embedding_reranker_matrix,
)
from TeeBotus.benchmarks.core import (
    BenchmarkResult,
    REQUIRED_BENCHMARK_CATEGORIES,
    REQUIRED_BENCHMARK_NAMES,
    REQUIRED_BENCHMARK_NAME_CATEGORIES,
    REQUIRED_BENCHMARK_RANKING_CATEGORIES,
    STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS,
    build_comparisons as _build_comparisons,
    build_quality_gate as _build_quality_gate,
    result as _result,
    stable_backend_ranking as _stable_backend_ranking,
)
from TeeBotus.benchmarks.hf_pool import (
    benchmark_hf_pool_eval_matrix as _benchmark_hf_pool_eval_matrix,
    benchmark_hf_pool_live as _benchmark_hf_pool_live,
    benchmark_hf_pool_quick as _benchmark_hf_pool_quick,
)
from TeeBotus.benchmarks.langgraph_flows import (
    benchmark_langgraph_bibliothekar_deep_query as _benchmark_langgraph_flow,
    benchmark_langgraph_bibliothekar_fake_installed as _benchmark_langgraph_fake_installed_flow,
    benchmark_langgraph_bibliothekar_linear as _benchmark_langgraph_linear_flow,
    benchmark_langgraph_source_harvester_workflow as _benchmark_langgraph_source_harvester_workflow,
)
from TeeBotus.benchmarks.llm_routing import benchmark_gemini_free_tier_guard, benchmark_llm_router
from TeeBotus.benchmarks.mcp import benchmark_mcp_readonly_bibliothekar_and_memory_search as _benchmark_mcp_tools
from TeeBotus.benchmarks.memory import (
    benchmark_jsonl_backend,
    benchmark_memory_jsonl_to_sqlite_migration as _benchmark_memory_jsonl_to_sqlite_migration,
    benchmark_postgres_backend,
    benchmark_sqlite_row_encrypted_projection,
    memory_results as benchmark_memory_results,
)
from TeeBotus.benchmarks.proactive import benchmark_proactive_tool_plan_due_dispatch_gates as _benchmark_proactive
from TeeBotus.benchmarks.pydantic_ai import (
    benchmark_decision_fake_model as _benchmark_decision_fake_model,
    benchmark_pydantic_structured_decisions as _benchmark_pydantic_structured_decisions,
)
from TeeBotus.benchmarks.qdrant import (
    benchmark_qdrant_health_live as _benchmark_qdrant_health_live,
    benchmark_qdrant_health_quick as _benchmark_qdrant_health_quick,
    benchmark_qdrant_memory_index_quick as _benchmark_qdrant_memory_index_quick,
)
from TeeBotus.benchmarks.reporting import (
    benchmark_context as _context,
    build_regression_report as _build_regression_report,
    dependency_context as _dependency_context,
)
from TeeBotus.benchmarks.runtime_health import (
    benchmark_database_fallback_policy as _benchmark_database_fallback_policy,
    benchmark_status_doctor as _benchmark_status_doctor,
)
from TeeBotus.benchmarks.source_quality import (
    benchmark_source_harvester_promote_index_flow as _benchmark_source_harvester_promote_index_flow,
    benchmark_source_harvester_quality_gate as _benchmark_source_harvester_quality_gate,
)
from TeeBotus.benchmarks.youtube import (
    benchmark_youtube_local_job_queue as _benchmark_youtube_local_job_queue,
    benchmark_youtube_local_pipeline_cache as _benchmark_youtube_local_pipeline_cache,
    benchmark_youtube_parser as _benchmark_youtube_parser,
)


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
    retrieval_matrix = _benchmark_retrieval_embedding_reranker_matrix(iterations=iterations)
    results.append(retrieval_matrix)
    results.extend(_retrieval_backend_results(retrieval_matrix))
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


def _memory_results(*, entries: int, select_runs: int, postgres_dsn: str) -> list[BenchmarkResult]:
    return benchmark_memory_results(
        entries=entries,
        select_runs=select_runs,
        postgres_dsn=postgres_dsn,
        jsonl_backend=benchmark_jsonl_backend,
        sqlite_backend=benchmark_sqlite_row_encrypted_projection,
        postgres_backend=benchmark_postgres_backend,
    )


def _retrieval_backend_results(matrix: BenchmarkResult) -> list[BenchmarkResult]:
    details = matrix.get("details")
    if not isinstance(details, dict):
        return []
    backend_total_ms = details.get("backend_total_ms")
    backend_selected = details.get("backend_selected")
    if not isinstance(backend_total_ms, dict) or not isinstance(backend_selected, dict):
        return []
    iterations = int(details.get("backend_iterations") or 1)
    payload_bytes = int(matrix.get("payload_bytes") or 0)
    index_bytes = int(matrix.get("index_bytes") or 0)
    results: list[BenchmarkResult] = []
    for backend in ("local", "llamaindex_fake", "haystack_fake"):
        total_ms = backend_total_ms.get(backend)
        selected = backend_selected.get(backend)
        ok = (
            isinstance(total_ms, (int, float))
            and not isinstance(total_ms, bool)
            and total_ms >= 0
            and isinstance(selected, int)
            and selected > 0
        )
        results.append(
            _result(
                name=f"retrieval_backend_{backend}",
                category="retrieval",
                iterations=iterations,
                total_ms=float(total_ms or 0.0),
                ok=ok,
                errors=0 if ok else 1,
                payload_bytes=payload_bytes,
                index_bytes=index_bytes,
                note="derived_from=retrieval_embedding_reranker_matrix",
                mode=backend,
                details={
                    "source_benchmark": "retrieval_embedding_reranker_matrix",
                    "backend": backend,
                    "selected_chunks": int(selected or 0),
                },
            )
        )
    return results


__all__ = [
    "BenchmarkResult",
    "REQUIRED_BENCHMARK_CATEGORIES",
    "REQUIRED_BENCHMARK_NAMES",
    "REQUIRED_BENCHMARK_NAME_CATEGORIES",
    "REQUIRED_BENCHMARK_RANKING_CATEGORIES",
    "STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS",
    "_benchmark_adapter_contracts",
    "_benchmark_bibliothekar",
    "_benchmark_bibliothekar_haystack_fake",
    "_benchmark_bibliothekar_llamaindex_fake",
    "_benchmark_database_fallback_policy",
    "_benchmark_decision_fake_model",
    "_benchmark_hf_pool_eval_matrix",
    "_benchmark_hf_pool_live",
    "_benchmark_hf_pool_quick",
    "_benchmark_langgraph_fake_installed_flow",
    "_benchmark_langgraph_flow",
    "_benchmark_langgraph_linear_flow",
    "_benchmark_langgraph_source_harvester_workflow",
    "_benchmark_mcp_tools",
    "_benchmark_memory_jsonl_to_sqlite_migration",
    "_benchmark_proactive",
    "_benchmark_pydantic_structured_decisions",
    "_benchmark_qdrant_health_live",
    "_benchmark_qdrant_health_quick",
    "_benchmark_qdrant_memory_index_quick",
    "_benchmark_retrieval_embedding_reranker_matrix",
    "_benchmark_source_harvester_promote_index_flow",
    "_benchmark_source_harvester_quality_gate",
    "_benchmark_status_doctor",
    "_benchmark_youtube_local_job_queue",
    "_benchmark_youtube_local_pipeline_cache",
    "_benchmark_youtube_parser",
    "_build_comparisons",
    "_build_quality_gate",
    "_build_regression_report",
    "_context",
    "_dependency_context",
    "_memory_results",
    "_retrieval_backend_results",
    "_result",
    "_stable_backend_ranking",
    "benchmark_gemini_free_tier_guard",
    "benchmark_jsonl_backend",
    "benchmark_llm_router",
    "benchmark_memory_results",
    "benchmark_postgres_backend",
    "benchmark_sqlite_row_encrypted_projection",
    "run_benchmarks",
]
