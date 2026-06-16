from __future__ import annotations

import json
import zipfile

from TeeBotus.instructions import BotInstructions, parse_instructions
from TeeBotus.openai_client import OpenAIResponse
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, telegram_identity_key
from TeeBotus.runtime.actions import SendText
from TeeBotus.runtime.bibliothekar import BibliothekarStore, LIBRARY_SCHEMA_VERSION
from TeeBotus.bibliothekar.cli import main as bibliothekar_cli_main
from TeeBotus.runtime.bibliothekar_service import BibliothekarQuery, BibliothekarService, HaystackBibliothekarBackend, LocalBibliothekarBackend, check_bibliothekar_service
from TeeBotus.runtime.engine import TeeBotusEngine
from TeeBotus.runtime.events import IncomingEvent


def test_bibliothekar_indexes_txt_epub_docx_and_retrieves_cited_chunks(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "depression.txt").write_text(
        "Depression Therapie Schlaf Aktivierung Tagesstruktur.\n"
        "Bei depressiver Erschoepfung helfen kleine Aufgaben und regelmaessige Ruhezeiten.\n",
        encoding="utf-8",
    )
    _write_docx(library_dir / "notizen.docx", ["Kognitive Therapie nutzt Gedankenprotokolle.", "Schlafhygiene bleibt wichtig."])
    _write_epub(library_dir / "handbuch.epub", "<html><body><p>Angst und Depression brauchen sanfte Planung.</p></body></html>")

    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    index = store.rebuild()
    selection = store.select("Was steht zur Depression Therapie und Schlaf?", max_chunks=3)
    payload = json.loads(selection.prompt_text)

    assert index["chunk_count"] >= 3
    assert payload["scope"] == "instance_library"
    assert payload["selected_library_chunks"]
    assert all("chunk_id" in chunk for chunk in payload["selected_library_chunks"])
    assert all("file" in chunk and "locator" in chunk for chunk in payload["selected_library_chunks"])
    assert "genaue Quelle" in " ".join(payload["citation_rules"])


def test_bibliothekar_indexes_plan2_source_metadata_and_prompt_payload(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    source = library_dir / "therapie.txt"
    source.write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")

    index = store.rebuild()
    chunks = [json.loads(line) for line in store.chunks_path.read_text(encoding="utf-8").splitlines()]
    selection = store.select("Therapie", max_chunks=1)
    payload = json.loads(selection.prompt_text)
    document = next(iter(index["documents"].values()))
    chunk = chunks[0]
    prompt_chunk = payload["selected_library_chunks"][0]

    assert index["schema_version"] == LIBRARY_SCHEMA_VERSION
    assert document["source_id"].startswith("sha256:")
    assert document["file_sha256"] == document["source_id"].removeprefix("sha256:")
    assert document["file_type"] == "txt"
    assert document["file_path"] == "therapie.txt"
    assert document["language"] == "de"
    assert document["embedding_model"] == "intfloat/multilingual-e5-small"
    assert chunk["source_id"] == document["source_id"]
    assert chunk["file_sha256"] == document["file_sha256"]
    assert chunk["file_type"] == "txt"
    assert chunk["chunk_index"] == 1
    assert chunk["section"] == "Zeilen 1-1"
    assert chunk["license"] == "private"
    assert prompt_chunk["source_id"] == document["source_id"]
    assert prompt_chunk["file_sha256"] == document["file_sha256"]
    assert prompt_chunk["file_type"] == "txt"
    assert prompt_chunk["language"] == "de"
    assert prompt_chunk["chunk_index"] == 1
    assert prompt_chunk["embedding_model"] == "intfloat/multilingual-e5-small"


def test_bibliothekar_rebuilds_legacy_schema_without_plan2_metadata(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    index = store.rebuild()
    index["schema_version"] = 1
    store.index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    selection = store.select("Therapie", max_chunks=1)
    payload = json.loads(selection.prompt_text)
    rebuilt = json.loads(store.index_path.read_text(encoding="utf-8"))

    assert rebuilt["schema_version"] == LIBRARY_SCHEMA_VERSION
    assert payload["selected_library_chunks"][0]["source_id"].startswith("sha256:")


def test_bibliothekar_context_is_added_to_engine_openai_prompt(tmp_path):
    instances_dir = tmp_path / "instances"
    library_dir = instances_dir / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    store = BibliothekarStore("Depressionsbot", instances_dir)
    store.rebuild()

    class FakeOpenAIClient:
        prompt = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.prompt = user_text
            return OpenAIResponse("Antwort.", "resp-library", None)

    account_store = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"b" * 32))
    account_id = account_store.resolve_or_create_account(telegram_identity_key(1), display_label="Alice")
    fake_client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True),
        openai_client=fake_client,
        bibliothekar_store=store,
    )
    event = IncomingEvent(
        event_id="telegram:1",
        instance="Depressionsbot",
        channel="telegram",
        adapter_slot=1,
        account_id=account_id,
        identity_key=telegram_identity_key(1),
        chat_id="1",
        chat_type="private",
        sender_id="1",
        sender_name="Alice",
        text="Was sagt die Bibliothek zu Therapie?",
        message_ref="1",
    )

    actions = engine._openai_actions(event, account_id, BotInstructions(openai_enabled=True))

    assert isinstance(actions[1], SendText)
    assert "Bibliothekar-Quellenkontext" in fake_client.prompt
    assert "chunk_id" in fake_client.prompt
    assert "therapie.txt" in fake_client.prompt
    assert "genaue Quelle" in fake_client.prompt


def test_bibliothekar_rebuilds_when_chunk_store_is_missing(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    store.rebuild()
    store.chunks_path.unlink()

    selection = store.select("Therapie", max_chunks=1)

    payload = json.loads(selection.prompt_text)
    assert store.chunks_path.exists()
    assert payload["selected_library_chunks"][0]["file"] == "therapie.txt"


def test_bibliothekar_service_wraps_existing_local_store(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    store.rebuild()
    service = BibliothekarService(LocalBibliothekarBackend(store))

    selection = service.search("Therapie", max_chunks=1)
    payload = json.loads(selection.prompt_text)

    assert service.backend_name == "local"
    assert selection.selected_ids
    assert payload["selected_library_chunks"][0]["file"] == "therapie.txt"


def test_bibliothekar_service_factory_uses_instruction_backend(tmp_path):
    local = BibliothekarService.from_instructions(
        "Depressionsbot",
        tmp_path / "instances",
        BotInstructions(bibliothekar_backend="local"),
    )
    haystack = BibliothekarService.from_instructions(
        "Depressionsbot",
        tmp_path / "instances",
        BotInstructions(bibliothekar_backend="haystack", bibliothekar_collection="therapy_books"),
    )
    qdrant = BibliothekarService.from_instructions(
        "Depressionsbot",
        tmp_path / "instances",
        BotInstructions(bibliothekar_backend="qdrant", bibliothekar_collection="therapy_books"),
    )

    assert isinstance(local.backend, LocalBibliothekarBackend)
    assert isinstance(haystack.backend, HaystackBibliothekarBackend)
    assert isinstance(qdrant.backend, HaystackBibliothekarBackend)
    assert haystack.collection == "therapy_books"
    assert qdrant.collection == "therapy_books"


def test_haystack_backend_rebuilds_document_store_and_searches_from_it(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    document_store = FakeDocumentStore()
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        collection="therapy_books",
        document_store_factory=lambda: document_store,
        document_class=FakeDocument,
    )

    index = backend.rebuild()
    selection = backend.search(
        BibliothekarQuery(
            text="Therapie Schlaf",
            max_chunks=1,
            max_prompt_chars=5000,
            max_quote_chars=300,
        )
    )
    payload = json.loads(selection.prompt_text)

    assert index["chunk_count"] == 1
    assert len(document_store.documents) == 1
    assert selection.selected_ids == (document_store.documents[0].id,)
    assert payload["selected_library_chunks"][0]["file"] == "therapie.txt"
    assert payload["selected_library_chunks"][0]["citation_format"].startswith("[Quelle:")


def test_haystack_backend_preserves_plan2_metadata_roundtrip(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    document_store = FakeDocumentStore()
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        collection="therapy_books",
        document_store_factory=lambda: document_store,
        document_class=FakeDocument,
    )

    backend.rebuild()
    selection = backend.search(BibliothekarQuery(text="Therapie", max_chunks=1))
    payload = json.loads(selection.prompt_text)
    meta = document_store.documents[0].meta
    prompt_chunk = payload["selected_library_chunks"][0]

    assert meta["source_id"].startswith("sha256:")
    assert meta["file_sha256"] == meta["source_id"].removeprefix("sha256:")
    assert meta["file_type"] == "txt"
    assert meta["language"] == "de"
    assert meta["chunk_index"] == 1
    assert meta["embedding_model"] == "intfloat/multilingual-e5-small"
    assert prompt_chunk["source_id"] == meta["source_id"]
    assert prompt_chunk["file_sha256"] == meta["file_sha256"]
    assert prompt_chunk["file_type"] == "txt"
    assert prompt_chunk["language"] == "de"
    assert prompt_chunk["chunk_index"] == 1


def test_haystack_backend_rebuild_removes_stale_document_store_chunks(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    therapy = library_dir / "therapie.txt"
    technique = library_dir / "technik.txt"
    therapy.write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    technique.write_text("Python Software Daten System Algorithmus.", encoding="utf-8")
    document_store = FakeDocumentStore()
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        collection="therapy_books",
        document_store_factory=lambda: document_store,
        document_class=FakeDocument,
    )

    first_index = backend.rebuild()
    technique.unlink()
    second_index = backend.rebuild()
    selection = backend.search(BibliothekarQuery(text="System Therapie", max_chunks=3))

    assert first_index["chunk_count"] == 2
    assert second_index["chunk_count"] == 1
    assert [document.meta["relative_path"] for document in document_store.documents] == ["therapie.txt"]
    assert document_store.deleted_document_ids
    assert "technik.txt" not in selection.prompt_text
    assert "therapie.txt" in selection.prompt_text


def test_bibliothekar_service_applies_local_metadata_filters(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    (library_dir / "technik.txt").write_text("Python Software Daten System Algorithmus.", encoding="utf-8")
    service = BibliothekarService.local("Depressionsbot", tmp_path / "instances")
    service.rebuild()

    selection = service.search("System Therapie", filters={"categories": ["technik"]}, max_chunks=3)
    payload = json.loads(selection.prompt_text)

    assert selection.selected_ids
    assert [chunk["file"] for chunk in payload["selected_library_chunks"]] == ["technik.txt"]
    assert "therapie.txt" not in selection.prompt_text


def test_haystack_backend_applies_same_metadata_filters_as_local_backend(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    (library_dir / "technik.txt").write_text("Python Software Daten System Algorithmus.", encoding="utf-8")
    document_store = FakeDocumentStore()
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        document_store_factory=lambda: document_store,
        document_class=FakeDocument,
    )
    backend.rebuild()

    selection = backend.search(BibliothekarQuery(text="System Therapie", filters={"topics": ["python"]}, max_chunks=3))
    payload = json.loads(selection.prompt_text)

    assert selection.selected_ids
    assert [chunk["file"] for chunk in payload["selected_library_chunks"]] == ["technik.txt"]
    assert "therapie.txt" not in selection.prompt_text


def test_haystack_backend_pushes_supported_metadata_filters_to_document_store(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    (library_dir / "technik.txt").write_text("Python Software Daten System Algorithmus.", encoding="utf-8")
    document_store = FakeDocumentStore()
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        document_store_factory=lambda: document_store,
        document_class=FakeDocument,
    )
    backend.rebuild()

    selection = backend.search(
        BibliothekarQuery(
            text="System Therapie",
            filters={"topics": ["python"], "file": "technik.txt"},
            max_chunks=3,
        )
    )
    payload = json.loads(selection.prompt_text)

    assert document_store.filter_calls[-1]["filters"] == {
        "operator": "AND",
        "conditions": [{"field": "meta.topics", "operator": "in", "value": ["python"]}],
    }
    assert [chunk["file"] for chunk in payload["selected_library_chunks"]] == ["technik.txt"]
    assert "therapie.txt" not in selection.prompt_text


def test_haystack_backend_keeps_backend_when_filter_pushdown_is_rejected(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    (library_dir / "technik.txt").write_text("Python Software Daten System Algorithmus.", encoding="utf-8")
    document_store = FilterRejectingDocumentStore()
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        document_store_factory=lambda: document_store,
        document_class=FakeDocument,
    )
    backend.rebuild()

    selection = backend.search(BibliothekarQuery(text="System Therapie", filters={"topics": ["python"]}, max_chunks=3))
    payload = json.loads(selection.prompt_text)

    assert document_store.rejected_filter_calls == 1
    assert document_store.unfiltered_calls >= 1
    assert [chunk["file"] for chunk in payload["selected_library_chunks"]] == ["technik.txt"]
    assert "therapie.txt" not in selection.prompt_text


def test_bibliothekar_indexes_only_explicit_library_not_account_memory(tmp_path):
    instance_dir = tmp_path / "instances" / "Depressionsbot"
    library_dir = instance_dir / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    account_store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", StaticSecretProvider(b"b" * 32))
    account_id = account_store.resolve_or_create_account(telegram_identity_key(1), display_label="Alice")
    account_marker = "ACCOUNT_MEMORY_ONLY_MARKER_7B3F"
    legacy_marker = "LEGACY_ACCOUNT_MEMORY_CANARY_91C2"
    account_store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_account_only",
            "memory_type": "semantic",
            "user_text": f"Diese echte Account-Memory darf nie in den Bibliothekar-Index: {account_marker}",
            "bot_text": "Notiert.",
            "keywords": ["account", "memory", account_marker.casefold()],
        },
    )
    account_memory_dir = account_store.account_dir(account_id)
    (account_memory_dir / "Legacy_User_Memory_Entries.jsonl").write_text(
        json.dumps({"id": "legacy_canary", "user_text": legacy_marker}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    document_store = FakeDocumentStore()

    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    index = store.rebuild()
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        collection="therapy_books",
        fallback_store=store,
        document_store_factory=lambda: document_store,
        document_class=FakeDocument,
    )
    backend.rebuild()

    local_chunks = store.chunks_path.read_text(encoding="utf-8")
    haystack_payload = "\n".join(
        f"{document.content}\n{json.dumps(document.meta, ensure_ascii=False, sort_keys=True)}"
        for document in document_store.documents
    )
    assert index["chunk_count"] == 1
    assert account_marker not in local_chunks
    assert legacy_marker not in local_chunks
    assert "data/accounts" not in local_chunks
    assert account_marker not in haystack_payload
    assert legacy_marker not in haystack_payload
    assert "data/accounts" not in haystack_payload
    assert "therapie.txt" in local_chunks


def test_haystack_backend_search_falls_back_to_local_store_when_qdrant_is_down(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        collection="therapy_books",
        document_store_factory=lambda: BrokenDocumentStore(),
        document_class=FakeDocument,
    )

    selection = backend.search(BibliothekarQuery(text="Therapie", max_chunks=1))
    payload = json.loads(selection.prompt_text)

    assert selection.selected_ids
    assert payload["selected_library_chunks"][0]["file"] == "therapie.txt"


def test_haystack_backend_search_falls_back_to_local_store_when_optional_dependencies_are_missing(tmp_path, monkeypatch):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    monkeypatch.setattr("TeeBotus.runtime.bibliothekar_service._module_available", lambda _name: False)
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        collection="therapy_books",
    )

    selection = backend.search(BibliothekarQuery(text="Therapie", max_chunks=1))
    payload = json.loads(selection.prompt_text)

    assert selection.selected_ids
    assert payload["selected_library_chunks"][0]["file"] == "therapie.txt"


def test_haystack_status_reports_unreachable_qdrant_when_dependencies_exist(tmp_path, monkeypatch):
    monkeypatch.setattr("TeeBotus.runtime.bibliothekar_service._module_available", lambda _name: True)
    monkeypatch.setattr(
        "TeeBotus.runtime.bibliothekar_service.HaystackBibliothekarBackend._document_store",
        lambda _self: BrokenDocumentStore(),
    )

    health = check_bibliothekar_service(
        "Depressionsbot",
        tmp_path / "instances",
        BotInstructions(bibliothekar_backend="haystack", bibliothekar_collection="therapy_books"),
    )

    assert health.backend == "haystack"
    assert health.store == "qdrant"
    assert health.status == "unreachable"
    assert "RuntimeError: qdrant unavailable" in health.error


def test_qdrant_backend_alias_uses_haystack_status_path(tmp_path, monkeypatch):
    monkeypatch.setattr("TeeBotus.runtime.bibliothekar_service._module_available", lambda _name: True)
    monkeypatch.setattr(
        "TeeBotus.runtime.bibliothekar_service.HaystackBibliothekarBackend._document_store",
        lambda _self: BrokenDocumentStore(),
    )

    health = check_bibliothekar_service(
        "Depressionsbot",
        tmp_path / "instances",
        BotInstructions(bibliothekar_backend="qdrant", bibliothekar_collection="therapy_books"),
    )

    assert health.backend == "haystack"
    assert health.store == "qdrant"
    assert health.status == "unreachable"


def test_haystack_status_reports_reachable_qdrant_with_local_index_counts(tmp_path, monkeypatch):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    BibliothekarStore("Depressionsbot", tmp_path / "instances").rebuild()
    monkeypatch.setattr("TeeBotus.runtime.bibliothekar_service._module_available", lambda _name: True)
    monkeypatch.setattr(
        "TeeBotus.runtime.bibliothekar_service.HaystackBibliothekarBackend._document_store",
        lambda _self: FakeDocumentStore(),
    )

    health = check_bibliothekar_service(
        "Depressionsbot",
        tmp_path / "instances",
        BotInstructions(bibliothekar_backend="haystack", bibliothekar_collection="therapy_books"),
    )

    assert health.backend == "haystack"
    assert health.store == "qdrant"
    assert health.status == "reachable"
    assert health.collection == "therapy_books"
    assert health.documents == 1
    assert health.chunks == 1


def test_bibliothekar_service_rebuild_delegates_to_backend(tmp_path):
    class FakeBackend:
        backend_name = "fake"

        def __init__(self):
            self.rebuilt = False

        def search(self, _query):
            return SimpleSelection("")

        def rebuild(self):
            self.rebuilt = True
            return {"chunk_count": 2}

    backend = FakeBackend()
    service = BibliothekarService(backend)

    assert service.rebuild() == {"chunk_count": 2}
    assert backend.rebuilt is True


def test_engine_bibliothekar_context_uses_service_search(tmp_path):
    class FakeBibliothekarService:
        calls = []

        def search(self, query_text, **kwargs):
            self.calls.append((query_text, kwargs))
            return SimpleSelection('{"selected_library_chunks":[{"file":"service.txt"}]}')

    class SimpleSelection:
        def __init__(self, prompt_text):
            self.prompt_text = prompt_text
            self.selected_ids = ("chunk_service",)

    class FakeOpenAIClient:
        prompt = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.prompt = user_text
            return OpenAIResponse("Antwort.", "resp-service", None)

    account_store = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"b" * 32))
    account_id = account_store.resolve_or_create_account(telegram_identity_key(1), display_label="Alice")
    service = FakeBibliothekarService()
    fake_client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, bibliothekar_enabled=True),
        openai_client=fake_client,
        bibliothekar_store=service,
    )
    event = IncomingEvent(
        event_id="telegram:1",
        instance="Depressionsbot",
        channel="telegram",
        adapter_slot=1,
        account_id=account_id,
        identity_key=telegram_identity_key(1),
        chat_id="1",
        chat_type="private",
        sender_id="1",
        sender_name="Alice",
        text="Was sagt die Bibliothek?",
        message_ref="1",
    )

    engine._openai_actions(event, account_id, BotInstructions(openai_enabled=True, bibliothekar_enabled=True))

    assert service.calls == [
        (
            "Was sagt die Bibliothek?",
            {"max_prompt_chars": 5000, "max_chunks": 5, "max_quote_chars": 900},
        )
    ]
    assert "service.txt" in fake_client.prompt


def test_engine_bibliothekar_context_uses_structured_query_decision(tmp_path):
    class FakeBibliothekarService:
        calls = []

        def search(self, query_text, **kwargs):
            self.calls.append((query_text, kwargs))
            return SimpleSelection('{"selected_library_chunks":[{"file":"schlaf.txt"}]}')

    class SimpleSelection:
        def __init__(self, prompt_text):
            self.prompt_text = prompt_text
            self.selected_ids = ("chunk_sleep",)

    class FakeOpenAIClient:
        prompt = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.prompt = user_text
            return OpenAIResponse("Antwort.", "resp-service", None)

    def structured_runner(_prompt, schema):
        return {
            "should_search": True,
            "query": "Schlafhygiene Depression",
            "confidence": 0.93,
            "reason_short": "normalized",
            "source": "model",
        }

    account_store = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"b" * 32))
    account_id = account_store.resolve_or_create_account(telegram_identity_key(1), display_label="Alice")
    service = FakeBibliothekarService()
    fake_client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, bibliothekar_enabled=True),
        openai_client=fake_client,
        bibliothekar_store=service,
        structured_decision_runner=structured_runner,
    )
    event = IncomingEvent(
        event_id="telegram:1",
        instance="Depressionsbot",
        channel="telegram",
        adapter_slot=1,
        account_id=account_id,
        identity_key=telegram_identity_key(1),
        chat_id="1",
        chat_type="private",
        sender_id="1",
        sender_name="Alice",
        text="Was steht in meinen Unterlagen zu Schlaf?",
        message_ref="1",
    )

    engine._openai_actions(event, account_id, BotInstructions(openai_enabled=True, bibliothekar_enabled=True))

    assert service.calls[0][0] == "Schlafhygiene Depression"
    assert "schlaf.txt" in fake_client.prompt


def test_engine_bibliothekar_context_can_skip_irrelevant_queries(tmp_path):
    class FakeBibliothekarService:
        calls = []

        def search(self, query_text, **kwargs):
            self.calls.append((query_text, kwargs))
            return SimpleSelection("should not be used")

    class SimpleSelection:
        def __init__(self, prompt_text):
            self.prompt_text = prompt_text
            self.selected_ids = ()

    class FakeOpenAIClient:
        prompt = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.prompt = user_text
            return OpenAIResponse("Antwort.", "resp-service", None)

    def structured_runner(_prompt, schema):
        return {"should_search": False, "query": "", "confidence": 0.95, "reason_short": "smalltalk", "source": "model"}

    account_store = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"b" * 32))
    account_id = account_store.resolve_or_create_account(telegram_identity_key(1), display_label="Alice")
    service = FakeBibliothekarService()
    fake_client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, bibliothekar_enabled=True),
        openai_client=fake_client,
        bibliothekar_store=service,
        structured_decision_runner=structured_runner,
    )
    event = IncomingEvent(
        event_id="telegram:1",
        instance="Depressionsbot",
        channel="telegram",
        adapter_slot=1,
        account_id=account_id,
        identity_key=telegram_identity_key(1),
        chat_id="1",
        chat_type="private",
        sender_id="1",
        sender_name="Alice",
        text="Wie geht es dir?",
        message_ref="1",
    )

    engine._openai_actions(event, account_id, BotInstructions(openai_enabled=True, bibliothekar_enabled=True))

    assert service.calls == []
    assert "Bibliothekar-Quellenkontext" not in fake_client.prompt


def test_engine_bibliothekar_context_ignores_low_confidence_model_search(tmp_path):
    class FakeBibliothekarService:
        calls = []

        def search(self, query_text, **kwargs):
            self.calls.append((query_text, kwargs))
            return SimpleSelection("should not be used")

    class SimpleSelection:
        def __init__(self, prompt_text):
            self.prompt_text = prompt_text
            self.selected_ids = ()

    class FakeOpenAIClient:
        prompt = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.prompt = user_text
            return OpenAIResponse("Antwort.", "resp-service", None)

    def structured_runner(_prompt, schema):
        return {
            "should_search": True,
            "query": "unsichere Bibliothekarfrage",
            "confidence": 0.42,
            "reason_short": "too uncertain",
            "source": "model",
        }

    account_store = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"b" * 32))
    account_id = account_store.resolve_or_create_account(telegram_identity_key(1), display_label="Alice")
    service = FakeBibliothekarService()
    fake_client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, bibliothekar_enabled=True),
        openai_client=fake_client,
        bibliothekar_store=service,
        structured_decision_runner=structured_runner,
    )
    event = IncomingEvent(
        event_id="telegram:1",
        instance="Depressionsbot",
        channel="telegram",
        adapter_slot=1,
        account_id=account_id,
        identity_key=telegram_identity_key(1),
        chat_id="1",
        chat_type="private",
        sender_id="1",
        sender_name="Alice",
        text="Vielleicht steht irgendwo etwas dazu?",
        message_ref="1",
    )

    engine._openai_actions(event, account_id, BotInstructions(openai_enabled=True, bibliothekar_enabled=True))

    assert service.calls == []
    assert "Bibliothekar-Quellenkontext" not in fake_client.prompt


def test_bibliothekar_openai_settings_are_parsed():
    instructions = parse_instructions(
        """
        ## OpenAI
        - bibliothekar_enabled: nein
        - bibliothekar_max_prompt_chars: 2222
        - bibliothekar_max_chunks: 2
        - bibliothekar_max_quote_chars: 333
        """
    )

    assert instructions.bibliothekar_enabled is False
    assert instructions.bibliothekar_max_prompt_chars == 2222
    assert instructions.bibliothekar_max_chunks == 2
    assert instructions.bibliothekar_max_quote_chars == 333


def test_bibliothekar_section_settings_are_parsed():
    instructions = parse_instructions(
        """
        ## Bibliothekar
        - enabled: nein
        - backend: qdrant
        - collection: therapie_buecher
        - max_prompt_chars: 2222
        - max_chunks: 2
        - max_quote_chars: 333
        - require_citations: nein
        """
    )

    assert instructions.bibliothekar_enabled is False
    assert instructions.bibliothekar_backend == "haystack"
    assert instructions.bibliothekar_collection == "therapie_buecher"
    assert instructions.bibliothekar_max_prompt_chars == 2222
    assert instructions.bibliothekar_max_chunks == 2
    assert instructions.bibliothekar_max_quote_chars == 333
    assert instructions.bibliothekar_require_citations is False


def test_bibliothekar_cli_status_index_dry_run_and_query(tmp_path, capsys):
    source = tmp_path / "books"
    source.mkdir()
    (source / "therapie.txt").write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## Bibliothekar\n- backend: local\n", encoding="utf-8")

    assert bibliothekar_cli_main(["--instances-dir", str(instances_dir), "--instance", "Depressionsbot", "index", "--source", str(source), "--dry-run"]) == 0
    dry_run_output = capsys.readouterr().out
    assert "Depressionsbot: 1 Dokumente, 1 Chunks, dry_run=True" in dry_run_output
    assert not (instance_dir / "data" / "Bibliothek" / "therapie.txt").exists()

    assert bibliothekar_cli_main(["--instances-dir", str(instances_dir), "--instance", "Depressionsbot", "index", "--source", str(source)]) == 0
    index_output = capsys.readouterr().out
    assert "Depressionsbot: 1 Dokumente, 1 Chunks, dry_run=False" in index_output

    assert bibliothekar_cli_main(["--instances-dir", str(instances_dir), "--instance", "Depressionsbot", "status"]) == 0
    status_output = capsys.readouterr().out
    assert "Depressionsbot: backend=local store=json collection=teebotus_books status=ready documents=1 chunks=1" in status_output

    assert bibliothekar_cli_main(["--instances-dir", str(instances_dir), "--instance", "Depressionsbot", "query", "Therapie", "--top-k", "1"]) == 0
    query_output = capsys.readouterr().out
    assert "Depressionsbot: backend=local selected=1" in query_output
    assert "therapie.txt" in query_output


def test_bibliothekar_cli_query_applies_metadata_filters(tmp_path, capsys):
    source = tmp_path / "books"
    source.mkdir()
    (source / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    (source / "technik.txt").write_text("Python Software Daten System Algorithmus.", encoding="utf-8")
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## Bibliothekar\n- backend: local\n", encoding="utf-8")

    assert bibliothekar_cli_main(["--instances-dir", str(instances_dir), "--instance", "Depressionsbot", "index", "--source", str(source)]) == 0
    capsys.readouterr()

    assert (
        bibliothekar_cli_main(
            [
                "--instances-dir",
                str(instances_dir),
                "--instance",
                "Depressionsbot",
                "query",
                "System Therapie",
                "--category",
                "technik",
                "--top-k",
                "3",
            ]
        )
        == 0
    )
    query_output = capsys.readouterr().out

    assert "selected=1" in query_output
    assert "technik.txt" in query_output
    assert "therapie.txt" not in query_output


def test_bibliothekar_cli_default_status_ignores_data_only_directories(tmp_path, capsys):
    instances_dir = tmp_path / "instances"
    configured = instances_dir / "Depressionsbot"
    configured.mkdir(parents=True)
    (configured / "Bot_Verhalten.md").write_text("## Bibliothekar\n- backend: local\n", encoding="utf-8")
    (instances_dir / "Bench" / "data").mkdir(parents=True)

    assert bibliothekar_cli_main(["--instances-dir", str(instances_dir), "status"]) == 0

    output = capsys.readouterr().out
    assert "Depressionsbot: backend=local" in output
    assert "Bench:" not in output

    assert bibliothekar_cli_main(["--instances-dir", str(instances_dir), "--instance", "Bench", "status"]) == 0
    explicit_output = capsys.readouterr().out
    assert "Bench: backend=local" in explicit_output


def _write_docx(path, paragraphs):
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(f"<w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>" for paragraph in paragraphs)
        + "</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)


def _write_epub(path, body):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("OPS/chapter.xhtml", body)


class FakeDocument:
    def __init__(self, *, content, meta, id=None):
        self.content = content
        self.meta = meta
        self.id = id or meta.get("chunk_id", "")


class FakeDocumentStore:
    def __init__(self):
        self.documents = []
        self.filter_calls = []
        self.deleted_document_ids = []

    def write_documents(self, documents, **_kwargs):
        by_id = {document.id: document for document in self.documents}
        for document in documents:
            by_id[document.id] = document
        self.documents = list(by_id.values())

    def filter_documents(self, **kwargs):
        self.filter_calls.append(kwargs)
        return list(self.documents)

    def delete_documents(self, document_ids):
        ids = {str(document_id) for document_id in document_ids}
        self.deleted_document_ids.extend(sorted(ids))
        self.documents = [document for document in self.documents if str(document.id) not in ids]


class BrokenDocumentStore:
    def filter_documents(self, **_kwargs):
        raise RuntimeError("qdrant unavailable")


class FilterRejectingDocumentStore(FakeDocumentStore):
    def __init__(self):
        super().__init__()
        self.rejected_filter_calls = 0
        self.unfiltered_calls = 0

    def filter_documents(self, **kwargs):
        self.filter_calls.append(kwargs)
        if kwargs.get("filters"):
            self.rejected_filter_calls += 1
            raise ValueError("unsupported filter syntax")
        self.unfiltered_calls += 1
        return list(self.documents)
