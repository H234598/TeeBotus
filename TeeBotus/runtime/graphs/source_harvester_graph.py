from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping, TypedDict

from TeeBotus.bibliothekar.source_harvester import SourceHarvestResult, SourceHarvester


class SourceHarvesterState(TypedDict, total=False):
    source_path: str
    metadata: dict[str, object]
    claims: list[str]
    evidence: list[str]
    route: str
    status: str
    sha256: str
    stored_path: str
    duplicate_of: str
    accepted_for_ingest: bool
    decision_status: str
    decision_reason: str
    citation_quality: str
    fallback_reason: str
    errors: list[str]


def run_source_harvester_workflow(
    harvester: SourceHarvester,
    source_path: str | Path,
    *,
    metadata: Mapping[str, object] | None = None,
    claims: Iterable[str] = (),
    evidence: Iterable[str] = (),
    prefer_langgraph: bool = True,
) -> SourceHarvesterState:
    state: SourceHarvesterState = {
        "source_path": str(source_path),
        "metadata": dict(metadata or {}),
        "claims": [str(item) for item in claims],
        "evidence": [str(item) for item in evidence],
        "errors": [],
    }
    if prefer_langgraph:
        graph = _build_langgraph_runner(harvester)
        if graph is not None:
            try:
                return _coerce_state(graph.invoke(state))
            except Exception as exc:  # noqa: BLE001 - optional graph runtime must stay non-fatal.
                return _fallback(_append_error({**state, "fallback_reason": "langgraph_error"}, f"{type(exc).__name__}: {exc}"))
    return _run_linear(harvester, state)


def _run_linear(harvester: SourceHarvester, state: SourceHarvesterState) -> SourceHarvesterState:
    for step in (_discover, lambda value: _score(harvester, value), _finalize):
        state = step(state)
    return state


def _build_langgraph_runner(harvester: SourceHarvester) -> Any | None:
    try:
        from langgraph.graph import END, StateGraph  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        graph = StateGraph(SourceHarvesterState)
        graph.add_node("discover", _discover)
        graph.add_node("score", lambda state: _score(harvester, state))
        graph.add_node("finalize", _finalize)
        graph.set_entry_point("discover")
        graph.add_edge("discover", "score")
        graph.add_edge("score", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()
    except Exception:
        return None


def _discover(state: SourceHarvesterState) -> SourceHarvesterState:
    source_path = str(state.get("source_path") or "").strip()
    if not source_path:
        return {**state, "fallback_reason": "missing_source_path"}
    if not Path(source_path).exists():
        return {**state, "fallback_reason": "source_not_found"}
    return state


def _score(harvester: SourceHarvester, state: SourceHarvesterState) -> SourceHarvesterState:
    if state.get("fallback_reason"):
        return state
    try:
        result = harvester.harvest_path(
            str(state.get("source_path") or ""),
            metadata=state.get("metadata") or {},
            claims=state.get("claims") or (),
            evidence=state.get("evidence") or (),
        )
    except Exception as exc:  # noqa: BLE001 - graph must return serializable diagnostics.
        return _append_error({**state, "fallback_reason": "harvest_error"}, f"{type(exc).__name__}: {exc}")
    return {**state, **_result_state(result)}


def _finalize(state: SourceHarvesterState) -> SourceHarvesterState:
    if state.get("fallback_reason"):
        return {**state, "status": "failed"}
    if state.get("duplicate_of"):
        return {**state, "status": "duplicate"}
    if state.get("accepted_for_ingest"):
        return {**state, "status": "ready_for_ingest"}
    route = str(state.get("route") or "")
    if route == "rejected":
        return {**state, "status": "rejected"}
    return {**state, "status": "review_required"}


def _result_state(result: SourceHarvestResult) -> SourceHarvesterState:
    return {
        "route": result.route,
        "sha256": result.sha256,
        "stored_path": str(result.stored_path or ""),
        "duplicate_of": str(result.duplicate_of or ""),
        "accepted_for_ingest": result.accepted_for_ingest,
        "decision_status": result.report.decision.status,
        "decision_reason": result.report.decision.reason,
        "citation_quality": result.report.citation_quality,
    }


def _append_error(state: SourceHarvesterState, error: str) -> SourceHarvesterState:
    errors = list(state.get("errors") or [])
    errors.append(str(error))
    return {**state, "errors": errors}


def _fallback(state: SourceHarvesterState) -> SourceHarvesterState:
    if state.get("status"):
        return state
    return {**state, "status": "failed"}


def _coerce_state(value: Any) -> SourceHarvesterState:
    if isinstance(value, dict):
        return dict(value)
    return {"source_path": "", "fallback_reason": "invalid_graph_state", "status": "failed", "errors": []}


__all__ = ["SourceHarvesterState", "run_source_harvester_workflow"]
