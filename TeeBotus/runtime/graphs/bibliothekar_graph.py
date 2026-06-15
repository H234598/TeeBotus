from __future__ import annotations

import json
from typing import Any, Callable, Mapping, TypedDict

from TeeBotus.runtime.bibliothekar import DEFAULT_MAX_CHUNKS, DEFAULT_MAX_PROMPT_CHARS, DEFAULT_MAX_QUOTE_CHARS
from TeeBotus.runtime.bibliothekar_service import BibliothekarService


class BibliothekarDeepQueryState(TypedDict, total=False):
    query: str
    filters: dict[str, object]
    intent: str
    confidence: float
    selected_ids: list[str]
    prompt_text: str
    answer_text: str
    citation_ok: bool
    fallback_reason: str
    errors: list[str]


AnswerBuilder = Callable[[str, str], str]


def langgraph_available() -> bool:
    try:
        import langgraph.graph  # noqa: F401
    except Exception:
        return False
    return True


def run_bibliothekar_deep_query(
    service: BibliothekarService,
    query_text: str,
    *,
    max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
    max_quote_chars: int = DEFAULT_MAX_QUOTE_CHARS,
    filters: Mapping[str, object] | None = None,
    answer_builder: AnswerBuilder | None = None,
    prefer_langgraph: bool = True,
) -> BibliothekarDeepQueryState:
    state: BibliothekarDeepQueryState = {"query": str(query_text or "").strip(), "errors": []}
    if filters:
        state["filters"] = _serializable_filters(filters)
    if prefer_langgraph:
        graph = _build_langgraph_runner(service, max_prompt_chars=max_prompt_chars, max_chunks=max_chunks, max_quote_chars=max_quote_chars, answer_builder=answer_builder)
        if graph is not None:
            try:
                return _coerce_state(graph.invoke(state))
            except Exception as exc:  # noqa: BLE001 - optional graph runtime must not break the bot path.
                return _fallback(_append_error({**state, "fallback_reason": "langgraph_error"}, f"{type(exc).__name__}: {exc}"))
    return _run_linear(
        service,
        state,
        max_prompt_chars=max_prompt_chars,
        max_chunks=max_chunks,
        max_quote_chars=max_quote_chars,
        answer_builder=answer_builder,
    )


def _run_linear(
    service: BibliothekarService,
    state: BibliothekarDeepQueryState,
    *,
    max_prompt_chars: int,
    max_chunks: int,
    max_quote_chars: int,
    answer_builder: AnswerBuilder | None,
) -> BibliothekarDeepQueryState:
    for step in (
        _classify,
        lambda value: _retrieve(service, value, max_prompt_chars=max_prompt_chars, max_chunks=max_chunks, max_quote_chars=max_quote_chars),
        _rerank,
        lambda value: _answer(value, answer_builder=answer_builder),
        _citation_check,
        _fallback,
    ):
        state = step(state)
    return state


def _build_langgraph_runner(
    service: BibliothekarService,
    *,
    max_prompt_chars: int,
    max_chunks: int,
    max_quote_chars: int,
    answer_builder: AnswerBuilder | None,
) -> Any | None:
    try:
        from langgraph.graph import END, StateGraph  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        graph = StateGraph(BibliothekarDeepQueryState)
        graph.add_node("classify", _classify)
        graph.add_node(
            "retrieve",
            lambda state: _retrieve(service, state, max_prompt_chars=max_prompt_chars, max_chunks=max_chunks, max_quote_chars=max_quote_chars),
        )
        graph.add_node("rerank", _rerank)
        graph.add_node("answer", lambda state: _answer(state, answer_builder=answer_builder))
        graph.add_node("citation_check", _citation_check)
        graph.add_node("fallback", _fallback)
        graph.set_entry_point("classify")
        graph.add_edge("classify", "retrieve")
        graph.add_edge("retrieve", "rerank")
        graph.add_edge("rerank", "answer")
        graph.add_edge("answer", "citation_check")
        graph.add_edge("citation_check", "fallback")
        graph.add_edge("fallback", END)
        return graph.compile()
    except Exception:
        return None


def _classify(state: BibliothekarDeepQueryState) -> BibliothekarDeepQueryState:
    query = str(state.get("query") or "").strip()
    if not query:
        return {**state, "intent": "empty", "confidence": 0.0, "fallback_reason": "empty_query"}
    library_words = {"buch", "buecher", "bücher", "bibliothek", "quelle", "literatur", "handbuch", "text", "kapitel"}
    lowered = query.casefold()
    confidence = 0.9 if any(word in lowered for word in library_words) else 0.65
    return {**state, "intent": "bibliothekar_query", "confidence": confidence}


def _retrieve(
    service: BibliothekarService,
    state: BibliothekarDeepQueryState,
    *,
    max_prompt_chars: int,
    max_chunks: int,
    max_quote_chars: int,
) -> BibliothekarDeepQueryState:
    if state.get("fallback_reason"):
        return state
    try:
        selection = service.search(
            str(state.get("query") or ""),
            filters=state.get("filters"),
            max_prompt_chars=max_prompt_chars,
            max_chunks=max_chunks,
            max_quote_chars=max_quote_chars,
        )
    except Exception as exc:  # noqa: BLE001 - graph must return a serializable failed state.
        return _append_error({**state, "fallback_reason": "retrieve_error"}, f"{type(exc).__name__}: {exc}")
    return {**state, "selected_ids": list(selection.selected_ids), "prompt_text": selection.prompt_text}


def _rerank(state: BibliothekarDeepQueryState) -> BibliothekarDeepQueryState:
    if state.get("fallback_reason"):
        return state
    if not state.get("selected_ids") or not state.get("prompt_text"):
        return {**state, "fallback_reason": "no_sources"}
    return state


def _answer(state: BibliothekarDeepQueryState, *, answer_builder: AnswerBuilder | None) -> BibliothekarDeepQueryState:
    if state.get("fallback_reason"):
        return state
    prompt_text = str(state.get("prompt_text") or "")
    query = str(state.get("query") or "")
    if answer_builder is None:
        answer_text = prompt_text
    else:
        try:
            answer_text = str(answer_builder(query, prompt_text) or "").strip()
        except Exception as exc:  # noqa: BLE001 - failed answer generation must not hide retrieved sources.
            return _append_error({**state, "fallback_reason": "answer_error"}, f"{type(exc).__name__}: {exc}")
    return {**state, "answer_text": answer_text}


def _citation_check(state: BibliothekarDeepQueryState) -> BibliothekarDeepQueryState:
    if state.get("fallback_reason"):
        return state
    prompt_text = str(state.get("prompt_text") or "")
    try:
        payload = json.loads(prompt_text)
    except json.JSONDecodeError:
        return {**state, "citation_ok": False, "fallback_reason": "invalid_source_payload"}
    chunks = payload.get("selected_library_chunks") if isinstance(payload, Mapping) else None
    if not isinstance(chunks, list) or not chunks:
        return {**state, "citation_ok": False, "fallback_reason": "no_citable_chunks"}
    required = {"chunk_id", "file", "locator", "citation_format"}
    citation_ok = all(isinstance(chunk, Mapping) and required.issubset(chunk.keys()) for chunk in chunks)
    if not citation_ok:
        return {**state, "citation_ok": False, "fallback_reason": "citation_metadata_missing"}
    return {**state, "citation_ok": True}


def _fallback(state: BibliothekarDeepQueryState) -> BibliothekarDeepQueryState:
    if not state.get("fallback_reason"):
        return state
    if not state.get("answer_text"):
        return {
            **state,
            "answer_text": "Ich habe in der Bibliothek gerade keine belastbare Quelle fuer diese Frage gefunden.",
            "citation_ok": False,
        }
    return state


def _append_error(state: BibliothekarDeepQueryState, error: str) -> BibliothekarDeepQueryState:
    errors = list(state.get("errors") or [])
    errors.append(str(error)[:500])
    return {**state, "errors": errors}


def _serializable_filters(filters: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in filters.items():
        normalized_key = str(key).strip()
        if not normalized_key:
            continue
        if isinstance(value, (list, tuple, set, frozenset)):
            result[normalized_key] = [str(item) for item in value if str(item).strip()]
        elif value is not None and str(value).strip():
            result[normalized_key] = str(value)
    return result


def _coerce_state(value: object) -> BibliothekarDeepQueryState:
    if not isinstance(value, Mapping):
        return {"query": "", "fallback_reason": "invalid_graph_state", "answer_text": "Der Bibliothekar-Graph lieferte keinen gueltigen State.", "citation_ok": False, "errors": []}
    result: BibliothekarDeepQueryState = {}
    for key, item in value.items():
        if key in {"query", "intent", "prompt_text", "answer_text", "fallback_reason"}:
            result[str(key)] = str(item)  # type: ignore[literal-required]
        elif key == "confidence":
            result["confidence"] = float(item)
        elif key == "citation_ok":
            result["citation_ok"] = bool(item)
        elif key == "filters" and isinstance(item, Mapping):
            result["filters"] = _serializable_filters(item)
        elif key in {"selected_ids", "errors"} and isinstance(item, list):
            result[str(key)] = [str(entry) for entry in item]  # type: ignore[literal-required]
    return result
