from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

from TeeBotus import __version__ as TEEBOTUS_VERSION
from TeeBotus.benchmarks.core import BENCHMARK_CONTEXT_DEPENDENCIES, BenchmarkResult


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
        f"- live_llm: {suite.get('live_llm', False)}",
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
    for benchmark_result in suite["results"]:
        status = "skipped" if benchmark_result.get("skipped") else ("ok" if benchmark_result.get("ok") else "failed")
        lines.append(
            "| {name} | {category} | {status} | {mode} | {iterations} | {total_ms:.3f} | {throughput:.2f} | {errors} | {payload_bytes} | {index_bytes} | {note} | {details} |".format(
                name=benchmark_result.get("name", ""),
                category=benchmark_result.get("category", ""),
                status=status,
                mode=benchmark_result.get("mode", "local"),
                iterations=int(benchmark_result.get("iterations") or 0),
                total_ms=float(benchmark_result.get("total_ms") or 0.0),
                throughput=float(benchmark_result.get("throughput_ops_s") or 0.0),
                errors=int(benchmark_result.get("errors") or 0),
                payload_bytes=int(benchmark_result.get("payload_bytes") or 0),
                index_bytes=int(benchmark_result.get("index_bytes") or 0),
                note=str(benchmark_result.get("reason") or benchmark_result.get("note") or "").replace("|", "/"),
                details=_markdown_details(benchmark_result.get("details") or {}),
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


def build_regression_report(
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


def benchmark_context() -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count() or 0,
        "dependencies": dependency_context(),
    }


def dependency_context() -> dict[str, dict[str, str]]:
    context: dict[str, dict[str, str]] = {}
    for package in BENCHMARK_CONTEXT_DEPENDENCIES:
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


def _markdown_details(details: dict[str, Any]) -> str:
    if not details:
        return ""
    rendered = json.dumps(details, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    if len(rendered) > 220:
        rendered = f"{rendered[:217]}..."
    return rendered.replace("|", "/")


__all__ = [
    "benchmark_context",
    "build_regression_report",
    "dependency_context",
    "render_markdown",
]
