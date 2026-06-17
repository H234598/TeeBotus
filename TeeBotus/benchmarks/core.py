from __future__ import annotations

from typing import Any


BenchmarkResult = dict[str, Any]

REQUIRED_BENCHMARK_CATEGORIES = frozenset(
    {
        "account_memory",
        "bibliothekar",
        "database_fallback",
        "gemini_free_tier",
        "hf_pool",
        "langgraph_flows",
        "llm_router",
        "mcp_tools",
        "messenger_adapters",
        "proactive_agent",
        "pydantic_ai",
        "qdrant",
        "retrieval",
        "source_harvester",
        "status_doctor",
        "transcription_youtube",
    }
)
REQUIRED_BENCHMARK_NAMES = frozenset(
    {
        "memory_migration_jsonl_to_sqlite",
        "memory_jsonl",
        "memory_sqlite_projection",
        "bibliothekar_local_query",
        "bibliothekar_llamaindex_fake_query",
        "bibliothekar_haystack_fake_query",
        "hf_pool_quick_health",
        "hf_pool_eval_matrix",
        "qdrant_health_quick",
        "qdrant_memory_index_quick",
        "retrieval_embedding_reranker_matrix",
        "retrieval_backend_haystack_fake",
        "retrieval_backend_llamaindex_fake",
        "retrieval_backend_local",
        "source_harvester_quality_gate",
        "source_harvester_promote_index_flow",
        "llm_router_structured_decision",
        "decision_fake_model",
        "pydantic_structured_decisions",
        "proactive_tool_plan_due_dispatch_gates",
        "messenger_adapter_runtime_contracts",
        "youtube_parser_local",
        "youtube_local_job_queue_no_llm",
        "youtube_local_pipeline_cache_no_openai",
        "status_doctor_runtime_dependency_health",
        "database_fallback_policy",
        "gemini_free_tier_guard_cache_rotation",
        "langgraph_bibliothekar_deep_query",
        "langgraph_bibliothekar_linear",
        "langgraph_bibliothekar_fake_installed",
        "langgraph_source_harvester_workflow",
        "mcp_readonly_bibliothekar_and_memory_search",
    }
)
REQUIRED_BENCHMARK_RANKING_CATEGORIES = frozenset(
    {
        "account_memory",
        "bibliothekar",
        "langgraph_flows",
        "retrieval",
        "transcription_youtube",
    }
)
REQUIRED_BENCHMARK_MIN_RANKING_CANDIDATES = 2
STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS = frozenset(
    {"network_calls", "openai_calls", "provider_calls", "remote_calls", "llm_calls"}
)


def build_quality_gate(
    results: list[BenchmarkResult],
    *,
    comparisons: dict[str, Any],
    quick: bool,
    include_live: bool,
) -> dict[str, Any]:
    errors: list[str] = []
    categories = {
        str(item.get("category") or "")
        for item in results
        if isinstance(item, dict) and item.get("ok") and not item.get("skipped")
    }
    missing_categories = sorted(REQUIRED_BENCHMARK_CATEGORIES - categories)
    if missing_categories:
        errors.append(f"missing required benchmark categories: {', '.join(missing_categories)}")
    successful_names = {
        str(item.get("name") or "")
        for item in results
        if isinstance(item, dict) and item.get("ok") and not item.get("skipped")
    }
    missing_names = sorted(REQUIRED_BENCHMARK_NAMES - successful_names)
    if missing_names:
        errors.append(f"missing required benchmark results: {', '.join(missing_names)}")

    rankings = comparisons.get("stable_backend_rankings") if isinstance(comparisons, dict) else None
    ranking_categories = {
        str(ranking.get("category") or "")
        for ranking in rankings or []
        if isinstance(ranking, dict) and isinstance(ranking.get("candidates"), list) and ranking.get("candidates")
    }
    missing_rankings = sorted(REQUIRED_BENCHMARK_RANKING_CATEGORIES - ranking_categories)
    if missing_rankings:
        errors.append(f"missing required benchmark rankings: {', '.join(missing_rankings)}")
    for ranking in rankings or []:
        if not isinstance(ranking, dict):
            continue
        category = str(ranking.get("category") or "")
        candidates = ranking.get("candidates")
        if (
            category in REQUIRED_BENCHMARK_RANKING_CATEGORIES
            and isinstance(candidates, list)
            and len(candidates) < REQUIRED_BENCHMARK_MIN_RANKING_CANDIDATES
        ):
            errors.append(f"ranking {category} must compare at least {REQUIRED_BENCHMARK_MIN_RANKING_CANDIDATES} successful candidates")

    for index, item in enumerate(results):
        if not isinstance(item, dict):
            errors.append(f"results[{index}] is not an object")
            continue
        name = str(item.get("name") or f"results[{index}]")
        skipped = bool(item.get("skipped"))
        for key in ("name", "category", "mode", "total_ms", "throughput_ops_s", "errors", "payload_bytes", "index_bytes", "details"):
            if key not in item:
                errors.append(f"{name} missing {key}")
        for key in ("total_ms", "throughput_ops_s", "payload_bytes", "index_bytes"):
            if key in item and not _is_nonnegative_number(item.get(key)):
                errors.append(f"{name} {key} must be a non-negative number")
        if "errors" in item and not _is_nonnegative_integer(item.get("errors")):
            errors.append(f"{name} errors must be a non-negative integer")
        if skipped:
            continue
        if not item.get("ok"):
            errors.append(f"{name} is neither ok nor skipped")
        if _is_nonnegative_integer(item.get("errors")) and int(item.get("errors") or 0) != 0:
            errors.append(f"{name} errors must be 0 for ok standard benchmark results")
        if not _is_positive_integer(item.get("iterations")):
            errors.append(f"{name} iterations must be a positive integer")
        if int(item.get("payload_bytes") or 0) <= 0 and int(item.get("index_bytes") or 0) <= 0:
            errors.append(f"{name} must report payload_bytes or index_bytes")
        details = item.get("details")
        if not isinstance(details, dict) or not details:
            errors.append(f"{name} details must be a non-empty object")
        elif quick and not include_live:
            missing_counters = sorted(STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS - set(details))
            if missing_counters:
                errors.append(f"{name} details missing standard no-live counters: {', '.join(missing_counters)}")
            for key, value in _forbidden_standard_benchmark_calls(details):
                errors.append(f"{name} details.{key} must be 0 in standard quick benchmarks, got {value}")
        if quick and not include_live and str(item.get("mode") or "local").casefold() == "live":
            errors.append(f"{name} must not use live mode in standard quick benchmarks")

    return {
        "status": "ok" if not errors else "failed",
        "ok": not errors,
        "checked_results": len(results),
        "error_count": len(errors),
        "errors": errors,
    }


def build_comparisons(results: list[BenchmarkResult]) -> dict[str, Any]:
    categories = {
        "account_memory": {"memory_jsonl", "memory_sqlite_projection", "memory_postgres"},
        "bibliothekar": {"bibliothekar_local_query", "bibliothekar_llamaindex_fake_query", "bibliothekar_haystack_fake_query"},
        "langgraph_flows": {
            "langgraph_bibliothekar_deep_query",
            "langgraph_bibliothekar_linear",
            "langgraph_bibliothekar_fake_installed",
            "langgraph_source_harvester_workflow",
        },
        "retrieval": {
            "retrieval_backend_haystack_fake",
            "retrieval_backend_llamaindex_fake",
            "retrieval_backend_local",
        },
        "transcription_youtube": {
            "youtube_parser_local",
            "youtube_local_job_queue_no_llm",
            "youtube_local_pipeline_cache_no_openai",
        },
    }
    rankings = []
    for category, names in categories.items():
        ranking = stable_backend_ranking(category=category, results=results, names=names)
        if ranking:
            rankings.append(ranking)
    return {
        "auto_switching": False,
        "selection_policy": "document_fastest_stable_backend_only",
        "stable_backend_rankings": rankings,
    }


def stable_backend_ranking(*, category: str, results: list[BenchmarkResult], names: set[str]) -> dict[str, Any] | None:
    candidates = [
        item
        for item in results
        if item.get("name") in names
        and item.get("category") == category
        and item.get("ok")
        and not item.get("skipped")
        and _is_nonnegative_integer(item.get("errors"))
        and int(item.get("errors") or 0) == 0
    ]
    skipped = [
        {
            "name": str(item.get("name") or ""),
            "mode": str(item.get("mode") or ""),
            "reason": str(item.get("reason") or ""),
        }
        for item in results
        if item.get("name") in names and item.get("skipped")
    ]
    if not candidates and not skipped:
        return None
    ranked = sorted(
        candidates,
        key=lambda item: (
            int(item.get("errors") or 0),
            -float(item.get("throughput_ops_s") or 0.0),
            float(item.get("total_ms") or 0.0),
            str(item.get("name") or ""),
        ),
    )
    return {
        "category": category,
        "fastest_stable": str(ranked[0].get("name") or "") if ranked else "",
        "candidates": [
            {
                "rank": index,
                "name": str(item.get("name") or ""),
                "mode": str(item.get("mode") or ""),
                "throughput_ops_s": float(item.get("throughput_ops_s") or 0.0),
                "total_ms": float(item.get("total_ms") or 0.0),
                "errors": int(item.get("errors") or 0),
                "payload_bytes": int(item.get("payload_bytes") or 0),
                "index_bytes": int(item.get("index_bytes") or 0),
                "note": str(item.get("note") or ""),
            }
            for index, item in enumerate(ranked, start=1)
        ],
        "skipped": skipped,
    }


def result(
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
    normalized_details = {key: 0 for key in STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS}
    normalized_details.update(details or {})
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
        "details": normalized_details,
    }


def _is_nonnegative_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def _is_nonnegative_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _forbidden_standard_benchmark_calls(details: dict[str, Any]) -> list[tuple[str, int | float]]:
    forbidden: list[tuple[str, int | float]] = []
    for key, value in details.items():
        key_text = str(key)
        if isinstance(value, dict):
            forbidden.extend((f"{key_text}.{nested_key}", nested_value) for nested_key, nested_value in _forbidden_standard_benchmark_calls(value))
            continue
        if key_text not in STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if value > 0:
            forbidden.append((key_text, value))
    return forbidden


__all__ = [
    "BenchmarkResult",
    "REQUIRED_BENCHMARK_CATEGORIES",
    "REQUIRED_BENCHMARK_MIN_RANKING_CANDIDATES",
    "REQUIRED_BENCHMARK_NAMES",
    "REQUIRED_BENCHMARK_RANKING_CATEGORIES",
    "STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS",
    "build_comparisons",
    "build_quality_gate",
    "result",
    "stable_backend_ranking",
]
