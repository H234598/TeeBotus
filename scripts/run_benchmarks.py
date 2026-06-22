#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TeeBotus.benchmarks.reporting import render_markdown  # noqa: E402
from TeeBotus.artifact_outputs import obsidian_incoming_path  # noqa: E402
from TeeBotus.benchmarks.suite import (  # noqa: E402,F401
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
    _benchmark_codex_history_collector_timer_render,
    _benchmark_codex_history_session_importer,
    _benchmark_codex_history_watcher_poll_loop,
    _benchmark_mcp_tools,
    benchmark_jsonl_backend,
    _benchmark_memory_jsonl_to_sqlite_migration,
    benchmark_postgres_backend,
    _benchmark_proactive,
    _benchmark_pydantic_structured_decisions,
    _benchmark_qdrant_health_live,
    _benchmark_qdrant_health_quick,
    _benchmark_qdrant_memory_index_quick,
    _benchmark_qdrant_usermemory_1024d_side_index_quick,
    _benchmark_qdrant_usermemory_384d_side_index_quick,
    _benchmark_qdrant_vector_dimensions_quantization_quick,
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
    benchmark_live_llm_message_latency_paths,
    benchmark_llm_decision_qdrant_path_matrix,
    benchmark_llm_message_latency_paths,
    benchmark_llm_router,
    benchmark_memory_results,
    run_benchmarks,
)
from TeeBotus.runtime.admin_accounts import (  # noqa: E402
    format_admin_notification_result_lines,
    notify_benchmark_admin_accounts,
)
from TeeBotus.runtime.config import resolve_instances_dir  # noqa: E402

DEFAULT_OBSIDIAN_BENCHMARK_MD = "teebotus-benchmarks-latest.md"
DEFAULT_OBSIDIAN_BENCHMARK_JSON = "teebotus-benchmarks-latest.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic TeeBotus benchmark suite.")
    parser.add_argument("--quick", action="store_true", help="Run only local deterministic quick benchmarks.")
    parser.add_argument("--entries", type=int, default=50, help="Synthetic memory entries for quick storage benchmarks.")
    parser.add_argument("--iterations", type=int, default=50, help="Iterations for light CPU-only benchmark loops.")
    parser.add_argument("--output", default="", help="Markdown output path.")
    parser.add_argument("--json-output", default="", help="JSON output path.")
    parser.add_argument("--obsidian-dir", default="", help="Obsidian incoming directory for default quick benchmark artifacts.")
    parser.add_argument("--no-obsidian", action="store_true", help="Do not write default quick benchmark artifacts to Obsidian.")
    parser.add_argument("--notify-admins", action="store_true", help="Send the benchmark markdown to configured admin accounts.")
    parser.add_argument("--no-admin-notify", action="store_true", help="Do not send quick benchmark markdown to admin accounts.")
    parser.add_argument("--baseline-json", default="", help="Optional previous benchmark JSON for regression comparison.")
    parser.add_argument("--postgres-dsn", default="", help="Optional PostgreSQL DSN for live PostgreSQL memory benchmark.")
    parser.add_argument("--include-live", action="store_true", help="Allow explicitly configured live benchmarks such as PostgreSQL.")
    parser.add_argument("--live-hf", action="store_true", help="Run one explicit live hf_pool target check when configured.")
    parser.add_argument("--live-qdrant", action="store_true", help="Run one explicit live Qdrant health check against the configured/default URL.")
    parser.add_argument(
        "--emergency-live-llm",
        action="store_true",
        help=(
            "EMERGENCY ONLY: run real LLM provider/API latency checks. Also requires "
            "TEEBOTUS_EMERGENCY_LIVE_LLM_BENCHMARK=NOTFALL_KOSTEN_AKZEPTIERT."
        ),
    )
    parser.add_argument("--emergency-live-llm-max-calls", type=int, default=3, help="Hard cap for emergency live LLM provider calls.")
    parser.add_argument("--profile", default="", help="Optional LLM profile context for live HF benchmarks, e.g. hf_pool_default.")
    args = parser.parse_args(argv)
    if args.entries < 1:
        parser.error("--entries must be >= 1")
    if args.iterations < 1:
        parser.error("--iterations must be >= 1")
    if args.notify_admins and args.no_admin_notify:
        parser.error("--notify-admins and --no-admin-notify are mutually exclusive")

    suite = run_benchmarks(
        entries=args.entries,
        iterations=args.iterations,
        postgres_dsn=args.postgres_dsn,
        quick=bool(args.quick),
        include_live=bool(args.include_live),
        live_hf=bool(args.live_hf),
        live_qdrant=bool(args.live_qdrant),
        live_llm=bool(args.emergency_live_llm),
        live_llm_max_calls=max(1, int(args.emergency_live_llm_max_calls or 1)),
        profile=str(args.profile or ""),
        baseline_json=Path(args.baseline_json) if args.baseline_json else None,
    )
    markdown = render_markdown(suite)
    suite_json = json.dumps(suite, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(markdown, encoding="utf-8")
    else:
        print(markdown)
    if args.json_output:
        Path(args.json_output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_output).write_text(suite_json, encoding="utf-8")
    obsidian_json_path: Path | str = Path(args.json_output) if args.json_output else ""
    if args.quick and not args.no_obsidian:
        obsidian_dir = Path(args.obsidian_dir).expanduser() if args.obsidian_dir else obsidian_incoming_path()
        obsidian_dir.mkdir(parents=True, exist_ok=True)
        obsidian_markdown_path = obsidian_dir / DEFAULT_OBSIDIAN_BENCHMARK_MD
        obsidian_json_path = obsidian_dir / DEFAULT_OBSIDIAN_BENCHMARK_JSON
        obsidian_markdown_path.write_text(markdown, encoding="utf-8")
        obsidian_json_path.write_text(suite_json, encoding="utf-8")
        print(f"benchmark_obsidian=written markdown={obsidian_markdown_path} json={obsidian_json_path}", file=sys.stderr)
    if args.notify_admins or (args.quick and not args.no_admin_notify):
        notify_env = _env_with_dotenv_defaults(os.environ, REPO_ROOT / ".env")
        instances_dir = _resolved_instances_dir(notify_env)
        notify_results = asyncio.run(
            notify_benchmark_admin_accounts(
                instances_dir=instances_dir,
                markdown_document=markdown,
                markdown_filename=DEFAULT_OBSIDIAN_BENCHMARK_MD,
                json_artifact_path=obsidian_json_path,
                benchmark_suite=suite,
                env=notify_env,
            )
        )
        for line in format_admin_notification_result_lines(notify_results):
            print(line, file=sys.stderr)
    return 0 if suite["ok"] else 1


def _resolved_instances_dir(env: Mapping[str, str]) -> Path:
    instances_dir = resolve_instances_dir(env).expanduser()
    if instances_dir.is_absolute():
        return instances_dir
    return REPO_ROOT / instances_dir


def _env_with_dotenv_defaults(env: Mapping[str, str], path: Path) -> dict[str, str]:
    merged = dict(env)
    if not path.exists():
        return merged
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in merged:
            continue
        merged[key] = _clean_dotenv_value(value.strip())
    return merged


def _clean_dotenv_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
