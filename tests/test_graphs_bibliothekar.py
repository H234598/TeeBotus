from __future__ import annotations

import json
import sys
import types

from TeeBotus.bibliothekar.cli import main as bibliothekar_cli_main
from TeeBotus.runtime.bibliothekar import BibliothekarStore
from TeeBotus.runtime.bibliothekar_service import BibliothekarSelection
from TeeBotus.runtime.bibliothekar_service import BibliothekarService, LocalBibliothekarBackend
from TeeBotus.runtime.graphs import run_bibliothekar_deep_query


def test_bibliothekar_deep_query_runs_without_langgraph(tmp_path) -> None:
    service = _service_with_book(tmp_path)

    state = run_bibliothekar_deep_query(service, "Was sagt die Bibliothek zu Therapie?", prefer_langgraph=True)

    assert state["intent"] == "bibliothekar_query"
    assert state["citation_ok"] is True
    assert state["selected_ids"]
    assert "therapie.txt" in state["answer_text"]


def test_bibliothekar_deep_query_passes_metadata_filters(tmp_path) -> None:
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    (library_dir / "technik.txt").write_text("Python Software Daten System Algorithmus.", encoding="utf-8")
    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    store.rebuild()
    service = BibliothekarService(LocalBibliothekarBackend(store))

    state = run_bibliothekar_deep_query(
        service,
        "System Therapie",
        filters={"categories": ["", "technik", " "], "keywords": [" "], "account_id": "private-must-not-echo"},
        prefer_langgraph=False,
    )

    assert state["citation_ok"] is True
    assert state["filters"] == {"categories": ["technik"]}
    assert "technik.txt" in state["answer_text"]
    assert "therapie.txt" not in state["answer_text"]


def test_bibliothekar_deep_query_returns_serializable_fallback_state(tmp_path) -> None:
    service = _service_with_book(tmp_path)

    state = run_bibliothekar_deep_query(service, "", prefer_langgraph=False)

    assert state["fallback_reason"] == "empty_query"
    assert state["citation_ok"] is False
    assert "keine belastbare Quelle" in state["answer_text"]
    json.dumps(state)


def test_bibliothekar_deep_query_rejects_incomplete_provenance_payload() -> None:
    class IncompleteCitationService:
        def search(self, *_args, **_kwargs):
            return BibliothekarSelection(
                json.dumps(
                    {
                        "selected_library_chunks": [
                            {
                                "chunk_id": "chunk-1",
                                "file": "therapie.txt",
                                "locator": "Seite 1",
                                "citation_format": "[Quelle: ...]",
                            }
                        ]
                    }
                ),
                ("chunk-1",),
            )

    state = run_bibliothekar_deep_query(
        IncompleteCitationService(),  # type: ignore[arg-type]
        "Bibliothek Therapie",
        prefer_langgraph=False,
    )

    assert state["citation_ok"] is False
    assert state["fallback_reason"] == "citation_metadata_missing"
    assert "keine belastbare Quelle" in state["answer_text"]


def test_bibliothekar_deep_query_rejects_uncited_answer_text(tmp_path) -> None:
    state = run_bibliothekar_deep_query(
        _service_with_book(tmp_path),
        "Bibliothek Therapie",
        answer_builder=lambda _query, _prompt: "Therapie kann helfen, aber ohne Quellenangabe.",
        prefer_langgraph=False,
    )

    assert state["citation_ok"] is False
    assert state["fallback_reason"] == "answer_missing_citations"
    assert "keine belastbare Quelle" in state["answer_text"]


def test_bibliothekar_deep_query_accepts_answer_with_selected_chunk_id(tmp_path) -> None:
    def answer_with_chunk_id(_query: str, prompt_text: str) -> str:
        payload = json.loads(prompt_text)
        chunk_id = payload["selected_library_chunks"][0]["chunk_id"]
        return f"Therapie wird in der Bibliothek genannt. [Quelle: chunk_id={chunk_id}]"

    state = run_bibliothekar_deep_query(
        _service_with_book(tmp_path),
        "Bibliothek Therapie",
        answer_builder=answer_with_chunk_id,
        prefer_langgraph=False,
    )

    assert state["citation_ok"] is True
    assert not state.get("fallback_reason")
    assert "chunk_id=" in state["answer_text"]


def test_bibliothekar_deep_query_rejects_empty_answer_text(tmp_path) -> None:
    state = run_bibliothekar_deep_query(
        _service_with_book(tmp_path),
        "Bibliothek Therapie",
        answer_builder=lambda _query, _prompt: "",
        prefer_langgraph=False,
    )

    assert state["citation_ok"] is False
    assert state["fallback_reason"] == "answer_empty"
    assert "keine belastbare Quelle" in state["answer_text"]


def test_bibliothekar_deep_query_can_use_langgraph_when_available(tmp_path, monkeypatch) -> None:
    calls = []

    class FakeCompiledGraph:
        def __init__(self, nodes, edges, entry):
            self.nodes = nodes
            self.edges = edges
            self.entry = entry

        def invoke(self, state):
            current = self.entry
            while current != "__end__":
                calls.append(current)
                state = self.nodes[current](state)
                current = self.edges[current]
            return state

    class FakeStateGraph:
        def __init__(self, _state_type):
            self.nodes = {}
            self.edges = {}
            self.entry = ""

        def add_node(self, name, func):
            self.nodes[name] = func

        def set_entry_point(self, name):
            self.entry = name

        def add_edge(self, source, target):
            self.edges[source] = target

        def compile(self):
            return FakeCompiledGraph(self.nodes, self.edges, self.entry)

    fake_package = types.ModuleType("langgraph")
    fake_graph = types.ModuleType("langgraph.graph")
    fake_graph.END = "__end__"
    fake_graph.StateGraph = FakeStateGraph
    monkeypatch.setitem(sys.modules, "langgraph", fake_package)
    monkeypatch.setitem(sys.modules, "langgraph.graph", fake_graph)
    service = _service_with_book(tmp_path)

    state = run_bibliothekar_deep_query(service, "Bibliothek Therapie", prefer_langgraph=True)

    assert calls == ["classify", "retrieve", "rerank", "answer", "citation_check", "fallback"]
    assert state["citation_ok"] is True


def test_bibliothekar_deep_query_falls_back_when_langgraph_compile_fails(tmp_path, monkeypatch) -> None:
    class BrokenStateGraph:
        def __init__(self, _state_type):
            pass

        def add_node(self, *_args, **_kwargs):
            return None

        def set_entry_point(self, *_args, **_kwargs):
            return None

        def add_edge(self, *_args, **_kwargs):
            return None

        def compile(self):
            raise RuntimeError("compile exploded")

    fake_package = types.ModuleType("langgraph")
    fake_graph = types.ModuleType("langgraph.graph")
    fake_graph.END = "__end__"
    fake_graph.StateGraph = BrokenStateGraph
    monkeypatch.setitem(sys.modules, "langgraph", fake_package)
    monkeypatch.setitem(sys.modules, "langgraph.graph", fake_graph)
    service = _service_with_book(tmp_path)

    state = run_bibliothekar_deep_query(service, "Bibliothek Therapie", prefer_langgraph=True)

    assert state["citation_ok"] is True
    assert not state.get("fallback_reason")
    assert "therapie.txt" in state["answer_text"]


def test_bibliothekar_deep_query_returns_serializable_state_when_langgraph_invoke_fails(tmp_path, monkeypatch) -> None:
    class BrokenCompiledGraph:
        def invoke(self, _state):
            raise RuntimeError("invoke exploded")

    class FakeStateGraph:
        def __init__(self, _state_type):
            pass

        def add_node(self, *_args, **_kwargs):
            return None

        def set_entry_point(self, *_args, **_kwargs):
            return None

        def add_edge(self, *_args, **_kwargs):
            return None

        def compile(self):
            return BrokenCompiledGraph()

    fake_package = types.ModuleType("langgraph")
    fake_graph = types.ModuleType("langgraph.graph")
    fake_graph.END = "__end__"
    fake_graph.StateGraph = FakeStateGraph
    monkeypatch.setitem(sys.modules, "langgraph", fake_package)
    monkeypatch.setitem(sys.modules, "langgraph.graph", fake_graph)
    service = _service_with_book(tmp_path)

    state = run_bibliothekar_deep_query(service, "Bibliothek Therapie", prefer_langgraph=True)

    assert state["fallback_reason"] == "langgraph_error"
    assert state["citation_ok"] is False
    assert state["errors"] == ["RuntimeError: invoke exploded"]
    assert "keine belastbare Quelle" in state["answer_text"]
    json.dumps(state)


def test_bibliothekar_deep_query_coerces_graph_state_conservatively(tmp_path, monkeypatch) -> None:
    class FakeCompiledGraph:
        def invoke(self, _state):
            return {
                "query": "Therapie",
                "filters": {"topics": [" python ", "", "python"], "keywords": [" "], "account_id": "private"},
                "confidence": "2.0",
                "citation_ok": "false",
                "fallback_reason": None,
                "selected_ids": ("", None, "mem_1", "mem_1"),
                "errors": ("x" * 700,),
            }

    class FakeStateGraph:
        def __init__(self, _state_type):
            pass

        def add_node(self, *_args, **_kwargs):
            return None

        def set_entry_point(self, *_args, **_kwargs):
            return None

        def add_edge(self, *_args, **_kwargs):
            return None

        def compile(self):
            return FakeCompiledGraph()

    fake_package = types.ModuleType("langgraph")
    fake_graph = types.ModuleType("langgraph.graph")
    fake_graph.END = "__end__"
    fake_graph.StateGraph = FakeStateGraph
    monkeypatch.setitem(sys.modules, "langgraph", fake_package)
    monkeypatch.setitem(sys.modules, "langgraph.graph", fake_graph)

    state = run_bibliothekar_deep_query(_service_with_book(tmp_path), "Therapie", prefer_langgraph=True)

    assert state["citation_ok"] is False
    assert state["fallback_reason"] == "external_unverified_state"
    assert "confidence" not in state
    assert state["filters"] == {"topics": ["python"]}
    assert state["selected_ids"] == ["mem_1"]
    assert state["errors"] == ["x" * 500]
    assert "keine belastbare Quelle" in state["answer_text"]
    json.dumps(state, allow_nan=False)


def test_bibliothekar_deep_query_finalizes_external_fallback_state(tmp_path, monkeypatch) -> None:
    class FakeCompiledGraph:
        def invoke(self, _state):
            return {"query": "Therapie", "fallback_reason": "external_no_sources", "citation_ok": False}

    class FakeStateGraph:
        def __init__(self, _state_type):
            pass

        def add_node(self, *_args, **_kwargs):
            return None

        def set_entry_point(self, *_args, **_kwargs):
            return None

        def add_edge(self, *_args, **_kwargs):
            return None

        def compile(self):
            return FakeCompiledGraph()

    fake_package = types.ModuleType("langgraph")
    fake_graph = types.ModuleType("langgraph.graph")
    fake_graph.END = "__end__"
    fake_graph.StateGraph = FakeStateGraph
    monkeypatch.setitem(sys.modules, "langgraph", fake_package)
    monkeypatch.setitem(sys.modules, "langgraph.graph", fake_graph)

    state = run_bibliothekar_deep_query(_service_with_book(tmp_path), "Therapie", prefer_langgraph=True)

    assert state["fallback_reason"] == "external_no_sources"
    assert state["citation_ok"] is False
    assert "keine belastbare Quelle" in state["answer_text"]
    json.dumps(state, allow_nan=False)


def test_bibliothekar_deep_query_revalidates_external_citation_ok_state(tmp_path, monkeypatch) -> None:
    service = _service_with_book(tmp_path)
    prompt_text = service.search("Therapie").prompt_text
    payload = json.loads(prompt_text)
    selected_ids = [payload["selected_library_chunks"][0]["chunk_id"]]

    class FakeCompiledGraph:
        def invoke(self, _state):
            return {
                "query": "Therapie",
                "selected_ids": selected_ids,
                "prompt_text": prompt_text,
                "answer_text": "Therapie kann helfen, aber ohne Quellenangabe.",
                "citation_ok": True,
            }

    class FakeStateGraph:
        def __init__(self, _state_type):
            pass

        def add_node(self, *_args, **_kwargs):
            return None

        def set_entry_point(self, *_args, **_kwargs):
            return None

        def add_edge(self, *_args, **_kwargs):
            return None

        def compile(self):
            return FakeCompiledGraph()

    fake_package = types.ModuleType("langgraph")
    fake_graph = types.ModuleType("langgraph.graph")
    fake_graph.END = "__end__"
    fake_graph.StateGraph = FakeStateGraph
    monkeypatch.setitem(sys.modules, "langgraph", fake_package)
    monkeypatch.setitem(sys.modules, "langgraph.graph", fake_graph)

    state = run_bibliothekar_deep_query(service, "Therapie", prefer_langgraph=True)

    assert state["citation_ok"] is False
    assert state["fallback_reason"] == "answer_missing_citations"
    assert "keine belastbare Quelle" in state["answer_text"]


def test_bibliothekar_deep_query_rejects_external_false_citation_ok_partial_answer(tmp_path, monkeypatch) -> None:
    service = _service_with_book(tmp_path)
    prompt_text = service.search("Therapie").prompt_text
    payload = json.loads(prompt_text)
    chunk_id = payload["selected_library_chunks"][0]["chunk_id"]

    class FakeCompiledGraph:
        def invoke(self, _state):
            return {
                "query": "Therapie",
                "selected_ids": [chunk_id],
                "prompt_text": prompt_text,
                "answer_text": f"Therapie wird genannt. [Quelle: chunk_id={chunk_id}]",
                "citation_ok": False,
            }

    class FakeStateGraph:
        def __init__(self, _state_type):
            pass

        def add_node(self, *_args, **_kwargs):
            return None

        def set_entry_point(self, *_args, **_kwargs):
            return None

        def add_edge(self, *_args, **_kwargs):
            return None

        def compile(self):
            return FakeCompiledGraph()

    fake_package = types.ModuleType("langgraph")
    fake_graph = types.ModuleType("langgraph.graph")
    fake_graph.END = "__end__"
    fake_graph.StateGraph = FakeStateGraph
    monkeypatch.setitem(sys.modules, "langgraph", fake_package)
    monkeypatch.setitem(sys.modules, "langgraph.graph", fake_graph)

    state = run_bibliothekar_deep_query(service, "Therapie", prefer_langgraph=True)

    assert state["citation_ok"] is False
    assert state["fallback_reason"] == "external_unverified_state"
    assert "keine belastbare Quelle" in state["answer_text"]


def test_bibliothekar_deep_query_rejects_external_missing_citation_ok_partial_answer(tmp_path, monkeypatch) -> None:
    service = _service_with_book(tmp_path)
    prompt_text = service.search("Therapie").prompt_text
    payload = json.loads(prompt_text)
    chunk_id = payload["selected_library_chunks"][0]["chunk_id"]

    class FakeCompiledGraph:
        def invoke(self, _state):
            return {
                "query": "Therapie",
                "selected_ids": [chunk_id],
                "prompt_text": prompt_text,
                "answer_text": f"Therapie wird genannt. [Quelle: chunk_id={chunk_id}]",
            }

    class FakeStateGraph:
        def __init__(self, _state_type):
            pass

        def add_node(self, *_args, **_kwargs):
            return None

        def set_entry_point(self, *_args, **_kwargs):
            return None

        def add_edge(self, *_args, **_kwargs):
            return None

        def compile(self):
            return FakeCompiledGraph()

    fake_package = types.ModuleType("langgraph")
    fake_graph = types.ModuleType("langgraph.graph")
    fake_graph.END = "__end__"
    fake_graph.StateGraph = FakeStateGraph
    monkeypatch.setitem(sys.modules, "langgraph", fake_package)
    monkeypatch.setitem(sys.modules, "langgraph.graph", fake_graph)

    state = run_bibliothekar_deep_query(service, "Therapie", prefer_langgraph=True)

    assert state["citation_ok"] is False
    assert state["fallback_reason"] == "external_unverified_state"
    assert "keine belastbare Quelle" in state["answer_text"]


def test_bibliothekar_deep_query_rejects_external_selected_id_mismatch(tmp_path, monkeypatch) -> None:
    service = _service_with_book(tmp_path)
    prompt_text = service.search("Therapie").prompt_text
    payload = json.loads(prompt_text)
    chunk_id = payload["selected_library_chunks"][0]["chunk_id"]

    class FakeCompiledGraph:
        def invoke(self, _state):
            return {
                "query": "Therapie",
                "selected_ids": ["missing-chunk"],
                "prompt_text": prompt_text,
                "answer_text": f"Therapie wird genannt. [Quelle: chunk_id={chunk_id}]",
                "citation_ok": True,
            }

    class FakeStateGraph:
        def __init__(self, _state_type):
            pass

        def add_node(self, *_args, **_kwargs):
            return None

        def set_entry_point(self, *_args, **_kwargs):
            return None

        def add_edge(self, *_args, **_kwargs):
            return None

        def compile(self):
            return FakeCompiledGraph()

    fake_package = types.ModuleType("langgraph")
    fake_graph = types.ModuleType("langgraph.graph")
    fake_graph.END = "__end__"
    fake_graph.StateGraph = FakeStateGraph
    monkeypatch.setitem(sys.modules, "langgraph", fake_package)
    monkeypatch.setitem(sys.modules, "langgraph.graph", fake_graph)

    state = run_bibliothekar_deep_query(service, "Therapie", prefer_langgraph=True)

    assert state["citation_ok"] is False
    assert state["fallback_reason"] == "selected_ids_mismatch"
    assert "keine belastbare Quelle" in state["answer_text"]


def test_bibliothekar_deep_query_rejects_external_selected_id_subset(tmp_path, monkeypatch) -> None:
    service = _service_with_books(tmp_path)
    prompt_text = service.search("Therapie Schlaf").prompt_text
    payload = json.loads(prompt_text)
    chunks = payload["selected_library_chunks"]
    assert len(chunks) >= 2
    selected_chunk = chunks[0]["chunk_id"]

    class FakeCompiledGraph:
        def invoke(self, _state):
            return {
                "query": "Therapie Schlaf",
                "selected_ids": [selected_chunk],
                "prompt_text": prompt_text,
                "answer_text": f"Therapie wird genannt. [Quelle: chunk_id={selected_chunk}]",
                "citation_ok": True,
            }

    class FakeStateGraph:
        def __init__(self, _state_type):
            pass

        def add_node(self, *_args, **_kwargs):
            return None

        def set_entry_point(self, *_args, **_kwargs):
            return None

        def add_edge(self, *_args, **_kwargs):
            return None

        def compile(self):
            return FakeCompiledGraph()

    fake_package = types.ModuleType("langgraph")
    fake_graph = types.ModuleType("langgraph.graph")
    fake_graph.END = "__end__"
    fake_graph.StateGraph = FakeStateGraph
    monkeypatch.setitem(sys.modules, "langgraph", fake_package)
    monkeypatch.setitem(sys.modules, "langgraph.graph", fake_graph)

    state = run_bibliothekar_deep_query(service, "Therapie Schlaf", prefer_langgraph=True)

    assert state["citation_ok"] is False
    assert state["fallback_reason"] == "selected_ids_mismatch"
    assert "keine belastbare Quelle" in state["answer_text"]


def test_bibliothekar_deep_query_external_fallback_overrides_partial_answer(tmp_path, monkeypatch) -> None:
    class FakeCompiledGraph:
        def invoke(self, _state):
            return {
                "query": "Therapie",
                "fallback_reason": "external_no_sources",
                "answer_text": "Teilantwort ohne belastbare Quelle.",
                "citation_ok": True,
            }

    class FakeStateGraph:
        def __init__(self, _state_type):
            pass

        def add_node(self, *_args, **_kwargs):
            return None

        def set_entry_point(self, *_args, **_kwargs):
            return None

        def add_edge(self, *_args, **_kwargs):
            return None

        def compile(self):
            return FakeCompiledGraph()

    fake_package = types.ModuleType("langgraph")
    fake_graph = types.ModuleType("langgraph.graph")
    fake_graph.END = "__end__"
    fake_graph.StateGraph = FakeStateGraph
    monkeypatch.setitem(sys.modules, "langgraph", fake_package)
    monkeypatch.setitem(sys.modules, "langgraph.graph", fake_graph)

    state = run_bibliothekar_deep_query(_service_with_book(tmp_path), "Therapie", prefer_langgraph=True)

    assert state["fallback_reason"] == "external_no_sources"
    assert state["citation_ok"] is False
    assert state["answer_text"] == "Ich habe in der Bibliothek gerade keine belastbare Quelle fuer diese Frage gefunden."


def test_bibliothekar_cli_query_deep_uses_graph(tmp_path, capsys) -> None:
    instances_dir = tmp_path / "instances"
    library_dir = instances_dir / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    (instances_dir / "Depressionsbot" / "Bot_Verhalten.md").write_text("## Bibliothekar\n- backend: local\n", encoding="utf-8")
    BibliothekarStore("Depressionsbot", instances_dir).rebuild()

    assert bibliothekar_cli_main(["--instances-dir", str(instances_dir), "--instance", "Depressionsbot", "query", "Therapie", "--deep"]) == 0
    output = capsys.readouterr().out

    assert "Depressionsbot: backend=local selected=1" in output
    assert "therapie.txt" in output


def _service_with_book(tmp_path) -> BibliothekarService:
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    store.rebuild()
    return BibliothekarService(LocalBibliothekarBackend(store))


def _service_with_books(tmp_path) -> BibliothekarService:
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    (library_dir / "schlaf.txt").write_text("Schlaf Hygiene Rhythmus Ruhe.", encoding="utf-8")
    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    store.rebuild()
    return BibliothekarService(LocalBibliothekarBackend(store))
