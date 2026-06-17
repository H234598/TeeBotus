from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
import types
from pathlib import Path
from typing import Any, Callable

from TeeBotus.benchmarks.core import BenchmarkResult, result
from TeeBotus.bibliothekar.source_harvester import SourceHarvester
from TeeBotus.runtime.bibliothekar import BibliothekarStore
from TeeBotus.runtime.bibliothekar_service import BibliothekarService, LocalBibliothekarBackend
from TeeBotus.runtime.graphs import run_bibliothekar_deep_query, run_source_harvester_workflow
from TeeBotus.runtime.source_quality import FakeNLIVerifier, SourceQualityPipeline


def benchmark_langgraph_bibliothekar_deep_query(*, iterations: int) -> BenchmarkResult:
    with _BenchmarkGraphFixture() as service:
        timings = [_timed_ms(lambda: run_bibliothekar_deep_query(service, "Bibliothek Therapie", prefer_langgraph=True)) for _ in range(iterations)]
        return result(
            name="langgraph_bibliothekar_deep_query",
            category="langgraph_flows",
            iterations=iterations,
            total_ms=sum(timings),
            payload_bytes=_bibliothekar_selection_payload_bytes(service),
            index_bytes=_bibliothekar_fixture_index_bytes(service),
            details={"median_graph_ms": statistics.median(timings), "mode": "langgraph_or_linear_fallback"},
        )


def benchmark_langgraph_bibliothekar_linear(*, iterations: int) -> BenchmarkResult:
    with _BenchmarkGraphFixture() as service:
        timings = [_timed_ms(lambda: run_bibliothekar_deep_query(service, "Bibliothek Therapie", prefer_langgraph=False)) for _ in range(iterations)]
        return result(
            name="langgraph_bibliothekar_linear",
            category="langgraph_flows",
            iterations=iterations,
            total_ms=sum(timings),
            payload_bytes=_bibliothekar_selection_payload_bytes(service),
            index_bytes=_bibliothekar_fixture_index_bytes(service),
            details={"median_graph_ms": statistics.median(timings), "mode": "linear"},
        )


def benchmark_langgraph_bibliothekar_fake_installed(*, iterations: int) -> BenchmarkResult:
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
    return result(
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


def benchmark_langgraph_source_harvester_workflow(*, iterations: int) -> BenchmarkResult:
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
        return result(
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


def _timed_ms(func: Callable[[], Any]) -> float:
    start = time.perf_counter()
    func()
    return (time.perf_counter() - start) * 1000


__all__ = [
    "benchmark_langgraph_bibliothekar_deep_query",
    "benchmark_langgraph_bibliothekar_fake_installed",
    "benchmark_langgraph_bibliothekar_linear",
    "benchmark_langgraph_source_harvester_workflow",
]
