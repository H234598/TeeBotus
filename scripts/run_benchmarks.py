#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
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

from TeeBotus import __version__ as TEEBOTUS_VERSION  # noqa: E402
from TeeBotus.bibliothekar.source_harvester import SourceHarvester  # noqa: E402
from TeeBotus.instructions import BotInstructions  # noqa: E402
from TeeBotus.llm_client import LiteLLMTextClient  # noqa: E402
from TeeBotus.mcp_tools import MCPToolPolicy, MCPToolRegistry, build_readonly_mcp_registry  # noqa: E402
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key  # noqa: E402
from TeeBotus.runtime.actions import SendText  # noqa: E402
from TeeBotus.runtime.bibliothekar import BibliothekarStore  # noqa: E402
from TeeBotus.runtime.bibliothekar_service import (  # noqa: E402
    BibliothekarService,
    LocalBibliothekarBackend,
)
from TeeBotus.runtime.graphs import run_bibliothekar_deep_query, run_source_harvester_workflow  # noqa: E402
from TeeBotus.runtime.source_quality import FakeNLIVerifier, SourceQualityPipeline  # noqa: E402
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
    return benchmark_memory_results(
        entries=entries,
        select_runs=select_runs,
        postgres_dsn=postgres_dsn,
        jsonl_backend=benchmark_jsonl_backend,
        sqlite_backend=benchmark_sqlite_row_encrypted_projection,
        postgres_backend=benchmark_postgres_backend,
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


if __name__ == "__main__":
    raise SystemExit(main())
