from __future__ import annotations

import json
from typing import Any, Callable, Mapping, TypedDict

from TeeBotus.runtime.bibliothekar import DEFAULT_MAX_CHUNKS, DEFAULT_MAX_PROMPT_CHARS, DEFAULT_MAX_QUOTE_CHARS
from TeeBotus.runtime.bibliothekar_service import CHUNK_FILTER_KEYS, BibliothekarService

REQUIRED_CITATION_FIELDS = frozenset(
    {
        "chunk_id",
        "source_id",
        "file",
        "file_path",
        "file_sha256",
        "file_type",
        "language",
        "locator",
        "license",
        "ingested_at",
        "chunk_index",
        "embedding_model",
        "citation_format",
    }
)


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
                return _finalize_external_state(_coerce_state(graph.invoke(state)))
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
    answer_text = str(state.get("answer_text") or "").strip()
    try:
        payload = json.loads(prompt_text)
    except json.JSONDecodeError:
        return {**state, "citation_ok": False, "fallback_reason": "invalid_source_payload"}
    chunks = payload.get("selected_library_chunks") if isinstance(payload, Mapping) else None
    if not isinstance(chunks, list) or not chunks:
        return {**state, "answer_text": "", "citation_ok": False, "fallback_reason": "no_citable_chunks"}
    if not _selected_ids_match_chunks(state.get("selected_ids"), chunks):
        return {**state, "answer_text": "", "citation_ok": False, "fallback_reason": "selected_ids_mismatch"}
    citation_ok = all(_chunk_has_required_citation_fields(chunk) for chunk in chunks)
    if not citation_ok:
        return {**state, "answer_text": "", "citation_ok": False, "fallback_reason": "citation_metadata_missing"}
    if not answer_text:
        return {**state, "answer_text": "", "citation_ok": False, "fallback_reason": "answer_empty"}
    if not _answer_mentions_selected_citation(answer_text, chunks):
        return {**state, "answer_text": "", "citation_ok": False, "fallback_reason": "answer_missing_citations"}
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


def _chunk_has_required_citation_fields(chunk: object) -> bool:
    if not isinstance(chunk, Mapping):
        return False
    return all(field in chunk and chunk.get(field) not in ("", None) for field in REQUIRED_CITATION_FIELDS)


def _answer_mentions_selected_citation(answer_text: str, chunks: list[object]) -> bool:
    folded = answer_text.casefold()
    for chunk in chunks:
        if not isinstance(chunk, Mapping):
            continue
        for field in ("chunk_id", "source_id"):
            value = str(chunk.get(field) or "").strip()
            if value and value.casefold() in folded:
                return True
    return False


def _selected_ids_match_chunks(selected_ids: object, chunks: list[object]) -> bool:
    if not isinstance(selected_ids, list) or not selected_ids:
        return False
    chunk_ids = {str(chunk.get("chunk_id") or "").strip() for chunk in chunks if isinstance(chunk, Mapping)}
    chunk_ids.discard("")
    selected = {str(item or "").strip() for item in selected_ids}
    selected.discard("")
    return bool(selected) and selected == chunk_ids


def _serializable_filters(filters: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in filters.items():
        normalized_key = str(key).strip().casefold()
        if not normalized_key:
            continue
        if normalized_key not in CHUNK_FILTER_KEYS:
            continue
        if isinstance(value, (list, tuple, set, frozenset)):
            values: list[str] = []
            seen: set[str] = set()
            for item in value:
                text = str(item or "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                values.append(text)
            if values:
                result[normalized_key] = values
        elif value is not None and str(value).strip():
            result[normalized_key] = str(value).strip()
    return result


def _coerce_state(value: object) -> BibliothekarDeepQueryState:
    if not isinstance(value, Mapping):
        return {"query": "", "fallback_reason": "invalid_graph_state", "answer_text": "Der Bibliothekar-Graph lieferte keinen gueltigen State.", "citation_ok": False, "errors": []}
    result: BibliothekarDeepQueryState = {}
    for key, item in value.items():
        if key in {"query", "intent", "prompt_text", "answer_text", "fallback_reason"}:
            text = str(item or "").strip()
            if text:
                result[str(key)] = text  # type: ignore[literal-required]
        elif key == "confidence":
            confidence = _coerce_float(item)
            if confidence is not None:
                result["confidence"] = confidence
        elif key == "citation_ok":
            result["citation_ok"] = _coerce_bool(item)
        elif key == "filters" and isinstance(item, Mapping):
            result["filters"] = _serializable_filters(item)
        elif key == "selected_ids" and isinstance(item, (list, tuple, set, frozenset)):
            result["selected_ids"] = _coerce_string_list(item)
        elif key == "errors" and isinstance(item, (list, tuple, set, frozenset)):
            result["errors"] = _coerce_string_list(item, max_items=20, max_chars=500)
    return result


def _finalize_external_state(state: BibliothekarDeepQueryState) -> BibliothekarDeepQueryState:
    if state.get("fallback_reason"):
        return _fallback({**state, "answer_text": "", "citation_ok": False})
    if state.get("citation_ok") is not True:
        return _fallback(
            {
                **state,
                "answer_text": "",
                "citation_ok": False,
                "fallback_reason": "external_unverified_state",
            }
        )
    return _fallback(_citation_check(state))


def _coerce_float(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return None
    if parsed < 0.0 or parsed > 1.0:
        return None
    return parsed


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().casefold()
    if text in {"1", "true", "yes", "on", "ja", "wahr"}:
        return True
    if text in {"0", "false", "no", "off", "nein", "falsch", ""}:
        return False
    return False


def _coerce_string_list(values: object, *, max_items: int = 100, max_chars: int = 200) -> list[str]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()[:max_chars]
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= max_items:
            break
    return result
