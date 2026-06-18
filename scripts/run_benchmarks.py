#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TeeBotus.benchmarks.reporting import render_markdown  # noqa: E402
from TeeBotus.benchmarks.suite import (  # noqa: E402
    BENCHMARK_CONTEXT_DEPENDENCIES,
    BENCHMARK_RANKING_NAME_SETS,
    BenchmarkResult,
    REQUIRED_BENCHMARK_CATEGORIES,
    REQUIRED_BENCHMARK_NAMES,
    REQUIRED_BENCHMARK_NAME_CATEGORIES,
    REQUIRED_BENCHMARK_RANKING_CATEGORIES,
    STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS,
    _benchmark_adapter_contracts,
    _benchmark_bibliothekar,
    _benchmark_bibliothekar_haystack_fake,
    _benchmark_bibliothekar_llamaindex_fake,
    _benchmark_database_fallback_policy,
    _benchmark_decision_fake_model,
    _benchmark_hf_pool_eval_matrix,
    _benchmark_hf_pool_live,
    _benchmark_hf_pool_quick,
    _benchmark_langgraph_fake_installed_flow,
    _benchmark_langgraph_flow,
    _benchmark_langgraph_linear_flow,
    _benchmark_langgraph_source_harvester_workflow,
    _benchmark_mcp_tools,
    benchmark_jsonl_backend,
    _benchmark_memory_jsonl_to_sqlite_migration,
    benchmark_postgres_backend,
    _benchmark_proactive,
    _benchmark_pydantic_structured_decisions,
    _benchmark_qdrant_health_live,
    _benchmark_qdrant_health_quick,
    _benchmark_qdrant_memory_index_quick,
    _benchmark_retrieval_embedding_reranker_matrix,
    _benchmark_source_harvester_promote_index_flow,
    _benchmark_source_harvester_quality_gate,
    _benchmark_status_doctor,
    benchmark_sqlite_row_encrypted_projection,
    _benchmark_youtube_local_job_queue,
    _benchmark_youtube_local_pipeline_cache,
    _benchmark_youtube_parser,
    _build_comparisons,
    _build_quality_gate,
    _build_regression_report,
    _context,
    _dependency_context,
    _memory_results,
    _result,
    _stable_backend_ranking,
    benchmark_gemini_free_tier_guard,
    benchmark_llm_message_latency_paths,
    benchmark_llm_router,
    benchmark_memory_results,
    run_benchmarks,
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


if __name__ == "__main__":
    raise SystemExit(main())
