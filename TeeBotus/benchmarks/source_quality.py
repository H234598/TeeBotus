from __future__ import annotations

import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from TeeBotus.benchmarks.core import BenchmarkResult, result
from TeeBotus.bibliothekar.source_harvester import SourceHarvester
from TeeBotus.runtime.bibliothekar import BibliothekarStore
from TeeBotus.runtime.source_quality import FakeNLIVerifier, SourceQualityPipeline


def benchmark_source_harvester_quality_gate(*, iterations: int) -> BenchmarkResult:
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-harvester-") as tmp:
        root = Path(tmp)
        source_dir = root / "incoming"
        source_dir.mkdir(parents=True)
        harvester = SourceHarvester(
            root / "library",
            quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.9)),
        )
        harvest_results = []

        def harvest_once(index: int) -> None:
            source = source_dir / f"quelle-{index}.pdf"
            source.write_text(f"Therapie Schlaf Aktivierung {index}.", encoding="utf-8")
            harvest_results.append(
                harvester.harvest_path(
                    source,
                    metadata={"title": f"Quelle {index}", "license": "private"},
                    claims=("Schlafhygiene ist relevant.",),
                    evidence=("Therapie Schlaf Aktivierung.",),
                )
            )

        timings = [_timed_ms(lambda index=index: harvest_once(index)) for index in range(iterations)]
        route_counts: dict[str, int] = {}
        for harvest_result in harvest_results:
            route_counts[harvest_result.route] = route_counts.get(harvest_result.route, 0) + 1
        accepted_dir = root / "library" / "accepted"
        accepted_bytes = sum(path.stat().st_size for path in accepted_dir.glob("*") if path.is_file())
        manifest_bytes = harvester.manifest_path.stat().st_size if harvester.manifest_path.exists() else 0
        return result(
            name="source_harvester_quality_gate",
            category="source_harvester",
            iterations=iterations,
            total_ms=sum(timings),
            payload_bytes=accepted_bytes,
            index_bytes=manifest_bytes,
            details={
                "median_harvest_ms": statistics.median(timings),
                "routes": route_counts,
                "accepted_for_ingest": sum(1 for harvest_result in harvest_results if harvest_result.accepted_for_ingest),
                "manifest_rows": len(harvest_results),
                "duplicate_count": sum(1 for harvest_result in harvest_results if harvest_result.duplicate_of is not None),
            },
        )


def benchmark_source_harvester_promote_index_flow(*, iterations: int) -> BenchmarkResult:
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-harvester-promote-") as tmp:
        root = Path(tmp)
        instances_dir = root / "instances"
        source_dir = root / "incoming"
        source_dir.mkdir(parents=True)
        store = BibliothekarStore("Bench", instances_dir)
        harvester = SourceHarvester(
            store.library_dir,
            quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91)),
        )
        promoted_paths: list[Path] = []
        timings: list[float] = []
        pre_promote_chunk_counts: list[int] = []
        post_promote_chunk_counts: list[int] = []

        for index in range(iterations):
            source = source_dir / f"promote-{index}.txt"
            marker = f"PROMOTE_BENCH_MARKER_{index}"
            source.write_text(f"Therapie Schlaf Aktivierung {marker}.", encoding="utf-8")

            def run_flow() -> None:
                harvest = harvester.harvest_path(
                    source,
                    metadata={"title": f"Promote {index}", "license": "private"},
                    claims=("Schlafhygiene ist relevant.",),
                    evidence=("Therapie Schlaf Aktivierung.",),
                )
                pre_promote_chunk_counts.append(int(store.rebuild().get("chunk_count") or 0))
                promoted = harvester.promote_accepted(harvest.stored_path)
                promoted_paths.append(promoted.promoted_path)
                post_promote_chunk_counts.append(int(store.rebuild().get("chunk_count") or 0))

            timings.append(_timed_ms(run_flow))

        manifest_bytes = harvester.manifest_path.stat().st_size if harvester.manifest_path.exists() else 0
        index_bytes = store.index_path.stat().st_size if store.index_path.exists() else 0
        chunks_bytes = store.chunks_path.stat().st_size if store.chunks_path.exists() else 0
        ok = (
            len(promoted_paths) == iterations
            and all(path.exists() and path.parent == store.library_dir / "books" for path in promoted_paths)
            and pre_promote_chunk_counts
            and post_promote_chunk_counts
            and pre_promote_chunk_counts == list(range(iterations))
            and post_promote_chunk_counts[-1] == iterations
        )
        return result(
            name="source_harvester_promote_index_flow",
            category="source_harvester",
            iterations=iterations,
            total_ms=sum(timings),
            ok=ok,
            errors=0 if ok else 1,
            payload_bytes=sum(path.stat().st_size for path in promoted_paths if path.exists()),
            index_bytes=index_bytes + chunks_bytes + manifest_bytes,
            note="harvest_promote_index_no_blind_ingest",
            details={
                "median_flow_ms": statistics.median(timings),
                "promoted": len(promoted_paths),
                "pre_promote_chunk_counts": pre_promote_chunk_counts,
                "post_promote_final_chunks": post_promote_chunk_counts[-1] if post_promote_chunk_counts else 0,
                "manifest_bytes": manifest_bytes,
                "promoted_dir": "books",
            },
        )


def _timed_ms(func: Callable[[], Any]) -> float:
    start = time.perf_counter()
    func()
    return (time.perf_counter() - start) * 1000


__all__ = [
    "benchmark_source_harvester_promote_index_flow",
    "benchmark_source_harvester_quality_gate",
]
