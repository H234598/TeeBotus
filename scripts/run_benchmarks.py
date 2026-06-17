#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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
from TeeBotus.benchmarks.adapters import benchmark_adapter_contracts as _benchmark_adapter_contracts  # noqa: E402
from TeeBotus.benchmarks.memory import (  # noqa: E402
    benchmark_jsonl_backend,
    benchmark_memory_jsonl_to_sqlite_migration as _benchmark_memory_jsonl_to_sqlite_migration,
    benchmark_postgres_backend,
    benchmark_sqlite_row_encrypted_projection,
    memory_results as benchmark_memory_results,
)
from TeeBotus.benchmarks.bibliothekar import (  # noqa: E402
    benchmark_bibliothekar_haystack_fake_query as _benchmark_bibliothekar_haystack_fake,
    benchmark_bibliothekar_llamaindex_fake_query as _benchmark_bibliothekar_llamaindex_fake,
    benchmark_bibliothekar_local_query as _benchmark_bibliothekar,
    benchmark_retrieval_embedding_reranker_matrix as _benchmark_retrieval_embedding_reranker_matrix,
)
from TeeBotus.benchmarks.proactive import benchmark_proactive_tool_plan_due_dispatch_gates as _benchmark_proactive  # noqa: E402
from TeeBotus.benchmarks.youtube import (  # noqa: E402
    benchmark_youtube_local_job_queue as _benchmark_youtube_local_job_queue,
    benchmark_youtube_local_pipeline_cache as _benchmark_youtube_local_pipeline_cache,
    benchmark_youtube_parser as _benchmark_youtube_parser,
)
from TeeBotus.benchmarks.runtime_health import (  # noqa: E402
    benchmark_database_fallback_policy as _benchmark_database_fallback_policy,
    benchmark_status_doctor as _benchmark_status_doctor,
)
from TeeBotus.benchmarks.langgraph_flows import (  # noqa: E402
    benchmark_langgraph_bibliothekar_deep_query as _benchmark_langgraph_flow,
    benchmark_langgraph_bibliothekar_fake_installed as _benchmark_langgraph_fake_installed_flow,
    benchmark_langgraph_bibliothekar_linear as _benchmark_langgraph_linear_flow,
    benchmark_langgraph_source_harvester_workflow as _benchmark_langgraph_source_harvester_workflow,
)
from TeeBotus.benchmarks.mcp import benchmark_mcp_readonly_bibliothekar_and_memory_search as _benchmark_mcp_tools  # noqa: E402
from TeeBotus.benchmarks.reporting import (  # noqa: E402
    benchmark_context as _context,
    build_regression_report as _build_regression_report,
    dependency_context as _dependency_context,
    render_markdown,
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


def _memory_results(*, entries: int, select_runs: int, postgres_dsn: str) -> list[BenchmarkResult]:
    return benchmark_memory_results(
        entries=entries,
        select_runs=select_runs,
        postgres_dsn=postgres_dsn,
        jsonl_backend=benchmark_jsonl_backend,
        sqlite_backend=benchmark_sqlite_row_encrypted_projection,
        postgres_backend=benchmark_postgres_backend,
    )

if __name__ == "__main__":
    raise SystemExit(main())
