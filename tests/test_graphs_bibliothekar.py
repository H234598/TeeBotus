from __future__ import annotations

import json
import sys
import types

from TeeBotus.bibliothekar.cli import main as bibliothekar_cli_main
from TeeBotus.runtime.bibliothekar import BibliothekarStore
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
        filters={"categories": ["technik"]},
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
