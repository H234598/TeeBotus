from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import TeeBotus.runtime.bibliothekar_service as bibliothekar_service_module
from TeeBotus.bibliothekar.cli import main as bibliothekar_cli_main
from TeeBotus.bibliothekar.source_harvester import SourceHarvester
from TeeBotus.instructions import BotInstructions, parse_instructions
from TeeBotus.openai_client import OpenAIResponse
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, telegram_identity_key
from TeeBotus.runtime.actions import SendText
from TeeBotus.runtime.bibliothekar import BibliothekarStore, LIBRARY_SCHEMA_VERSION, _is_allowed_library_source_path
from TeeBotus.runtime.bibliothekar_service import (
    BibliothekarQuery,
    BibliothekarService,
    HaystackBibliothekarBackend,
    LlamaIndexBibliothekarBackend,
    LocalBibliothekarBackend,
    check_bibliothekar_service,
)
from TeeBotus.runtime.engine import TeeBotusEngine
from TeeBotus.runtime.events import IncomingEvent
from TeeBotus.runtime.qdrant import QDRANT_BIBLIOTHEKAR_COLLECTION
from TeeBotus.runtime.source_quality import FakeNLIVerifier, SourceQualityPipeline


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
    assert document["author"] == ""
    assert document["language"] == "de"
    assert document["embedding_model"] == "intfloat/multilingual-e5-small"
    assert chunk["source_id"] == document["source_id"]
    assert chunk["file_sha256"] == document["file_sha256"]
    assert chunk["file_type"] == "txt"
    assert chunk["author"] == ""
    assert chunk["chunk_index"] == 1
    assert chunk["section"] == "Zeilen 1-1"
    assert chunk["license"] == "private"
    assert chunk["source_quality"] == "unreviewed"
    assert chunk["citation_quality"] == "unreviewed"
    assert chunk["source_harvest_route"] == "manual"
    assert prompt_chunk["source_id"] == document["source_id"]
    assert prompt_chunk["file_path"] == document["file_path"]
    assert prompt_chunk["file_sha256"] == document["file_sha256"]
    assert prompt_chunk["file_type"] == "txt"
    assert prompt_chunk["author"] == ""
    assert prompt_chunk["language"] == "de"
    assert prompt_chunk["license"] == "private"
    assert prompt_chunk["source_quality"] == "unreviewed"
    assert prompt_chunk["citation_quality"] == "unreviewed"
    assert prompt_chunk["source_harvest_route"] == "manual"
    assert prompt_chunk["ingested_at"] == chunk["ingested_at"]
    assert prompt_chunk["chunk_index"] == 1
    assert prompt_chunk["embedding_model"] == "intfloat/multilingual-e5-small"


def test_bibliothekar_library_source_path_rejects_terminal_traversal_segments(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"

    assert _is_allowed_library_source_path(library_dir / "books" / "therapie.txt", library_dir) is True
    assert _is_allowed_library_source_path(library_dir / "..", library_dir) is False
    assert _is_allowed_library_source_path(library_dir / "books" / "..", library_dir) is False


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


def test_bibliothekar_rebuilds_local_chunk_store_without_citation_metadata(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    store.rebuild()
    uncited_marker = "UNCITED_LOCAL_CHUNK_MARKER_43A1"
    store.chunks_path.write_text(
        json.dumps(
            {
                "chunk_id": "legacy_uncited_chunk",
                "title": "Legacy",
                "text": f"Therapie ohne belastbare Quelle {uncited_marker}",
                "topics": ["therapie"],
                "categories": ["psychologie"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    selection = store.select("Therapie", max_chunks=1)
    payload = json.loads(selection.prompt_text)
    selected = payload["selected_library_chunks"][0]

    assert uncited_marker not in selection.prompt_text
    assert selected["file"] == "therapie.txt"
    assert selected["source_id"].startswith("sha256:")
    assert selected["locator"]
    assert "legacy_uncited_chunk" not in store.chunks_path.read_text(encoding="utf-8")


def test_bibliothekar_rebuilds_local_chunk_store_with_empty_text_citation_chunk(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    store.rebuild()
    valid_chunk = json.loads(store.chunks_path.read_text(encoding="utf-8").splitlines()[0])
    empty_text_marker = "EMPTY_TEXT_CITATION_CHUNK_MARKER"
    store.chunks_path.write_text(
        json.dumps(
            {
                **valid_chunk,
                "chunk_id": "empty_text_citation_chunk",
                "text": "",
                "topics": ["therapie"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    selection = store.select(f"Therapie {empty_text_marker}", max_chunks=1)
    payload = json.loads(selection.prompt_text)
    selected = payload["selected_library_chunks"][0]

    assert selected["file"] == "therapie.txt"
    assert selected["quote"]
    assert selected["chunk_id"] != "empty_text_citation_chunk"
    assert "empty_text_citation_chunk" not in store.chunks_path.read_text(encoding="utf-8")


def test_bibliothekar_rebuilds_when_harvest_manifest_quality_changes(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    book_dir = library_dir / "books"
    book_dir.mkdir(parents=True)
    source = book_dir / "therapie.txt"
    source.write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    accepted_path = library_dir / "accepted" / "therapie.txt"
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest_path = library_dir / "harvest_manifest.jsonl"

    def write_manifest(status: str, reason: str) -> None:
        rows = [
            {
                "accepted_for_ingest": True,
                "decision": {
                    "confidence": 0.8,
                    "reason": reason,
                    "requires_human_review": status != "usable",
                    "status": status,
                },
                "route": "accepted",
                "sha256": sha256,
                "source": {"metadata": {"license": "private", "title": "Therapiequelle"}},
                "source_path": "/tmp/original-therapie.txt",
                "stored_path": str(accepted_path),
            },
            {
                "accepted_for_ingest": False,
                "event": "promoted",
                "route": "promoted",
                "sha256": sha256,
                "source_path": str(accepted_path),
                "stored_path": str(source),
            },
        ]
        manifest_path.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")

    write_manifest("usable", "initial usable source")
    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    store.rebuild()
    first_payload = json.loads(store.select("Therapie", max_chunks=1).prompt_text)
    assert first_payload["selected_library_chunks"][0]["source_quality"] == "usable"

    write_manifest("weak", "manual review downgraded source")
    second_payload = json.loads(store.select("Therapie", max_chunks=1).prompt_text)

    assert second_payload["selected_library_chunks"][0]["source_quality"] == "weak"
    assert second_payload["selected_library_chunks"][0]["citation_quality"] == "weak"
    assert second_payload["selected_library_chunks"][0]["source_quality_reason"] == "manual review downgraded source"


def test_bibliothekar_harvest_manifest_hash_fallback_uses_latest_accepted_review(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    book_dir = library_dir / "books"
    book_dir.mkdir(parents=True)
    source = book_dir / "therapie.txt"
    source.write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest_path = library_dir / "harvest_manifest.jsonl"
    rows = [
        {
            "accepted_for_ingest": True,
            "decision": {
                "confidence": 0.8,
                "reason": "older usable review",
                "requires_human_review": False,
                "status": "usable",
            },
            "route": "accepted",
            "sha256": sha256,
            "source": {"metadata": {"license": "private", "title": "Aeltere Therapiequelle"}},
            "source_path": "/tmp/original-therapie.txt",
            "stored_path": str(library_dir / "accepted" / "old-therapie.txt"),
        },
        {
            "accepted_for_ingest": True,
            "decision": {
                "confidence": 0.7,
                "reason": "newer weak review",
                "requires_human_review": True,
                "status": "weak",
            },
            "route": "accepted",
            "sha256": sha256,
            "source": {"metadata": {"license": "private", "title": "Neuere Therapiequelle"}},
            "source_path": "/tmp/original-therapie.txt",
            "stored_path": str(library_dir / "accepted" / "new-therapie.txt"),
        },
        {
            "accepted_for_ingest": False,
            "event": "promoted",
            "route": "promoted",
            "sha256": sha256,
            "source_path": str(library_dir / "accepted" / "path-mismatch.txt"),
            "stored_path": str(source),
        },
    ]
    manifest_path.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")

    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    store.rebuild()
    payload = json.loads(store.select("Therapie", max_chunks=1).prompt_text)
    chunk = payload["selected_library_chunks"][0]

    assert chunk["title"] == "Neuere Therapiequelle"
    assert chunk["source_quality"] == "weak"
    assert chunk["source_quality_reason"] == "newer weak review"


def test_bibliothekar_harvest_manifest_string_bool_flags(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    book_dir = library_dir / "books"
    book_dir.mkdir(parents=True)
    source = book_dir / "therapie.txt"
    source.write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    accepted_path = library_dir / "accepted" / "therapie.txt"
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest_path = library_dir / "harvest_manifest.jsonl"
    rows = [
        {
            "accepted_for_ingest": "true",
            "decision": {
                "confidence": 0.8,
                "reason": "usable source",
                "requires_human_review": "false",
                "status": "usable",
            },
            "route": "accepted",
            "sha256": sha256,
            "source": {"metadata": {"license": "private", "title": "Therapiequelle"}},
            "source_path": "/tmp/original-therapie.txt",
            "stored_path": str(accepted_path),
        },
        {
            "accepted_for_ingest": False,
            "event": "promoted",
            "route": "promoted",
            "sha256": sha256,
            "source_path": str(accepted_path),
            "stored_path": str(source),
        },
    ]
    manifest_path.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")

    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    store.rebuild()
    payload = json.loads(store.select("Therapie", max_chunks=1).prompt_text)

    assert payload["selected_library_chunks"][0]["title"] == "Therapiequelle"
    assert payload["selected_library_chunks"][0]["source_requires_human_review"] is False


def test_bibliothekar_harvest_manifest_normalizes_source_quality_status(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    book_dir = library_dir / "books"
    book_dir.mkdir(parents=True)
    source = book_dir / "therapie.txt"
    source.write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    accepted_path = library_dir / "accepted" / "therapie.txt"
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest_path = library_dir / "harvest_manifest.jsonl"
    rows = [
        {
            "accepted_for_ingest": True,
            "decision": {
                "confidence": 0.8,
                "reason": "imported uppercase source status",
                "requires_human_review": False,
                "status": "USABLE",
            },
            "route": "accepted",
            "sha256": sha256,
            "source": {"metadata": {"license": "private", "title": "Therapiequelle"}},
            "source_path": "/tmp/original-therapie.txt",
            "stored_path": str(accepted_path),
        },
        {
            "accepted_for_ingest": False,
            "event": "promoted",
            "route": "promoted",
            "sha256": sha256,
            "source_path": str(accepted_path),
            "stored_path": str(source),
        },
    ]
    manifest_path.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")

    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    store.rebuild()
    payload = json.loads(store.select("Therapie", max_chunks=1).prompt_text)
    chunk = payload["selected_library_chunks"][0]

    assert chunk["source_quality"] == "usable"
    assert chunk["citation_quality"] == "usable"


def test_bibliothekar_harvest_manifest_relative_paths_survive_cwd_change(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    download_dir = workspace / "download"
    download_dir.mkdir()
    source = download_dir / "therapie.txt"
    source.write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    relative_instances = Path("instances")
    monkeypatch.chdir(workspace)
    store = BibliothekarStore("Depressionsbot", relative_instances)

    harvester = SourceHarvester(
        store.library_dir,
        quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91)),
    )
    harvest = harvester.harvest_path(
        source,
        metadata={"title": "Relative Therapiequelle", "license": "private"},
        claims=("Aktivierung ist relevant.",),
        evidence=("Depression Therapie Aktivierung.",),
    )
    assert harvest.stored_path is not None
    assert not harvest.stored_path.is_absolute()
    harvester.promote_accepted(harvest.stored_path)
    other_cwd = tmp_path / "other-cwd"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    absolute_store = BibliothekarStore("Depressionsbot", workspace / "instances")
    absolute_store.rebuild()
    payload = json.loads(absolute_store.select("Therapie", max_chunks=1).prompt_text)
    chunk = payload["selected_library_chunks"][0]

    assert chunk["title"] == "Relative Therapiequelle"
    assert chunk["source_quality"] == "trusted"
    assert chunk["source_harvest_route"] == "accepted"


def test_bibliothekar_harvest_manifest_ignores_nonaccepted_ingest_rows(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    book_dir = library_dir / "books"
    book_dir.mkdir(parents=True)
    source = book_dir / "therapie.txt"
    source.write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    staged_path = library_dir / "quarantine" / "therapie.txt"
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest_path = library_dir / "harvest_manifest.jsonl"
    rows = [
        {
            "accepted_for_ingest": "true",
            "decision": {
                "confidence": 0.8,
                "reason": "should stay quarantined",
                "requires_human_review": True,
                "status": "weak",
            },
            "route": "quarantine",
            "sha256": sha256,
            "source": {"metadata": {"license": "private", "title": "Quarantined Therapy Source"}},
            "source_path": "/tmp/original-therapie.txt",
            "stored_path": str(staged_path),
        },
        {
            "accepted_for_ingest": False,
            "event": "promoted",
            "route": "promoted",
            "sha256": sha256,
            "source_path": str(staged_path),
            "stored_path": str(source),
        },
    ]
    manifest_path.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")

    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    store.rebuild()
    payload = json.loads(store.select("Therapie", max_chunks=1).prompt_text)
    chunk = payload["selected_library_chunks"][0]

    assert chunk["title"] == "therapie"
    assert chunk["source_quality"] == "unreviewed"
    assert chunk["source_harvest_route"] == "manual"
    assert "Quarantined Therapy Source" not in json.dumps(payload, ensure_ascii=False)


def test_bibliothekar_harvest_manifest_ignores_external_accepted_metadata(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    book_dir = library_dir / "books"
    book_dir.mkdir(parents=True)
    source = book_dir / "therapie.txt"
    source.write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    external_accepted = tmp_path / "outside-accepted.txt"
    external_accepted.write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest_path = library_dir / "harvest_manifest.jsonl"
    rows = [
        {
            "accepted_for_ingest": True,
            "decision": {
                "confidence": 0.8,
                "reason": "external accepted path should be ignored",
                "requires_human_review": False,
                "status": "usable",
            },
            "route": "accepted",
            "sha256": sha256,
            "source": {"metadata": {"license": "private", "title": "External Therapy Source"}},
            "source_path": "/tmp/original-therapie.txt",
            "stored_path": str(external_accepted),
        },
        {
            "accepted_for_ingest": False,
            "event": "promoted",
            "route": "promoted",
            "sha256": sha256,
            "source_path": str(external_accepted),
            "stored_path": str(source),
        },
    ]
    manifest_path.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")

    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    store.rebuild()
    payload = json.loads(store.select("Therapie", max_chunks=1).prompt_text)
    chunk = payload["selected_library_chunks"][0]

    assert chunk["title"] == "therapie"
    assert chunk["source_quality"] == "unreviewed"
    assert chunk["source_harvest_route"] == "manual"
    assert "External Therapy Source" not in json.dumps(payload, ensure_ascii=False)


def test_bibliothekar_harvest_manifest_rejects_traversal_accepted_metadata_path(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    book_dir = library_dir / "books"
    book_dir.mkdir(parents=True)
    source = book_dir / "therapie.txt"
    source.write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    accepted_path = library_dir / "accepted" / "therapie.txt"
    accepted_path.parent.mkdir(parents=True)
    accepted_path.write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    traversal_accepted_path = library_dir / "books" / ".." / "accepted" / "therapie.txt"
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest_path = library_dir / "harvest_manifest.jsonl"
    rows = [
        {
            "accepted_for_ingest": True,
            "decision": {
                "confidence": 0.8,
                "reason": "traversal accepted path should be ignored",
                "requires_human_review": False,
                "status": "usable",
            },
            "route": "accepted",
            "sha256": sha256,
            "source": {"metadata": {"license": "private", "title": "Traversal Therapy Source"}},
            "source_path": "/tmp/original-therapie.txt",
            "stored_path": str(traversal_accepted_path),
        },
        {
            "accepted_for_ingest": False,
            "event": "promoted",
            "route": "promoted",
            "sha256": sha256,
            "source_path": str(traversal_accepted_path),
            "stored_path": str(source),
        },
    ]
    manifest_path.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")

    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    store.rebuild()
    payload = json.loads(store.select("Therapie", max_chunks=1).prompt_text)
    chunk = payload["selected_library_chunks"][0]

    assert chunk["title"] == "therapie"
    assert chunk["source_quality"] == "unreviewed"
    assert chunk["source_harvest_route"] == "manual"
    assert "Traversal Therapy Source" not in json.dumps(payload, ensure_ascii=False)


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
        BotInstructions(
            bibliothekar_backend="qdrant",
            bibliothekar_collection="therapy_books",
            bibliothekar_qdrant_url="http://localhost:6334",
        ),
    )
    llamaindex = BibliothekarService.from_instructions(
        "Depressionsbot",
        tmp_path / "instances",
        BotInstructions(bibliothekar_backend="llamaindex"),
    )

    assert isinstance(local.backend, LocalBibliothekarBackend)
    assert isinstance(haystack.backend, HaystackBibliothekarBackend)
    assert isinstance(qdrant.backend, HaystackBibliothekarBackend)
    assert isinstance(llamaindex.backend, LlamaIndexBibliothekarBackend)
    assert haystack.collection == "therapy_books"
    assert qdrant.collection == "therapy_books"
    assert qdrant.backend.qdrant_url == "http://localhost:6334"


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
    assert meta["author"] == ""
    assert meta["language"] == "de"
    assert meta["chunk_index"] == 1
    assert meta["embedding_model"] == "intfloat/multilingual-e5-small"
    assert prompt_chunk["source_id"] == meta["source_id"]
    assert prompt_chunk["file_path"] == meta["file_path"]
    assert prompt_chunk["file_sha256"] == meta["file_sha256"]
    assert prompt_chunk["file_type"] == "txt"
    assert prompt_chunk["author"] == ""
    assert prompt_chunk["language"] == "de"
    assert prompt_chunk["license"] == "private"
    assert prompt_chunk["ingested_at"] == meta["ingested_at"]
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


def test_haystack_backend_rebuild_removes_stale_chunks_when_instance_filter_returns_empty(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    therapy = library_dir / "therapie.txt"
    technique = library_dir / "technik.txt"
    therapy.write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    technique.write_text("Python Software Daten System Algorithmus.", encoding="utf-8")
    document_store = EmptyFilteredDocumentStore()
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        document_store_factory=lambda: document_store,
        document_class=FakeDocument,
    )

    first_index = backend.rebuild()
    stale_technique_id = next(
        document.id for document in document_store.documents if document.meta["relative_path"] == "technik.txt"
    )
    technique.unlink()
    document_store.filtered_calls = 0
    document_store.unfiltered_calls = 0
    second_index = backend.rebuild()
    selection = backend.search(BibliothekarQuery(text="System Therapie", max_chunks=3))

    assert first_index["chunk_count"] == 2
    assert second_index["chunk_count"] == 1
    assert stale_technique_id in document_store.deleted_document_ids
    assert document_store.filtered_calls >= 1
    assert document_store.unfiltered_calls >= 1
    assert [document.meta["relative_path"] for document in document_store.documents] == ["therapie.txt"]
    assert "technik.txt" not in selection.prompt_text
    assert "therapie.txt" in selection.prompt_text


def test_haystack_backend_preserves_source_quality_metadata(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    book_dir = library_dir / "books"
    book_dir.mkdir(parents=True)
    source = book_dir / "therapie.txt"
    source.write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    accepted_path = library_dir / "accepted" / "therapie.txt"
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest_path = library_dir / "harvest_manifest.jsonl"
    rows = [
        {
            "accepted_for_ingest": True,
            "decision": {
                "confidence": 0.8,
                "reason": "manual review downgraded source",
                "requires_human_review": True,
                "status": "weak",
            },
            "route": "accepted",
            "sha256": sha256,
            "source": {"metadata": {"license": "private", "title": "Therapiequelle"}},
            "source_path": "/tmp/original-therapie.txt",
            "stored_path": str(accepted_path),
        },
        {
            "accepted_for_ingest": False,
            "event": "promoted",
            "route": "promoted",
            "sha256": sha256,
            "source_path": str(accepted_path),
            "stored_path": str(source),
        },
    ]
    manifest_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
    fallback_store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    document_store = FakeDocumentStore()
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        fallback_store=fallback_store,
        document_store_factory=lambda: document_store,
        document_class=FakeDocument,
    )

    backend.rebuild()
    selection = backend.search(BibliothekarQuery(text="Therapie", max_chunks=1))
    payload = json.loads(selection.prompt_text)
    prompt_chunk = payload["selected_library_chunks"][0]

    assert document_store.documents[0].meta["source_quality"] == "weak"
    assert prompt_chunk["source_quality"] == "weak"
    assert prompt_chunk["citation_quality"] == "weak"
    assert prompt_chunk["source_quality_reason"] == "manual review downgraded source"
    assert prompt_chunk["source_requires_human_review"] is True
    assert prompt_chunk["source_harvest_route"] == "accepted"


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


def test_bibliothekar_service_normalizes_extension_suffix_and_file_type_filters(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    (library_dir / "notizen.md").write_text("Markdown Notizen ueber Aktivierung und Planung.", encoding="utf-8")
    service = BibliothekarService.local("Depressionsbot", tmp_path / "instances")
    service.rebuild()

    for filters in ({"extension": "md"}, {"extension": ".md"}, {"suffix": "md"}, {"suffix": ".md"}, {"file_type": "md"}):
        selection = service.search("Aktivierung Planung", filters=filters, max_chunks=3)
        payload = json.loads(selection.prompt_text)

        assert [chunk["file"] for chunk in payload["selected_library_chunks"]] == ["notizen.md"]
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
            filters={"topics": ["python"], "relative_path": "technik.txt", "extension": ".txt"},
            max_chunks=3,
        )
    )
    payload = json.loads(selection.prompt_text)

    assert document_store.filter_calls[-1]["filters"] == {
        "operator": "AND",
        "conditions": [
            {"field": "meta.instance_name", "operator": "in", "value": ["Depressionsbot"]},
            {"field": "meta.topics", "operator": "in", "value": ["python"]},
            {"field": "meta.relative_path", "operator": "in", "value": ["technik.txt"]},
            {"field": "meta.file_type", "operator": "in", "value": ["txt"]},
        ],
    }
    assert [chunk["file"] for chunk in payload["selected_library_chunks"]] == ["technik.txt"]
    assert "therapie.txt" not in selection.prompt_text


def test_haystack_backend_keeps_partial_file_filters_via_local_fallback(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    (library_dir / "technik.txt").write_text("Python Software Daten System Algorithmus.", encoding="utf-8")
    document_store = EmptyFilteredDocumentStore()
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        document_store_factory=lambda: document_store,
        document_class=FakeDocument,
    )
    backend.rebuild()
    document_store.filtered_calls = 0
    document_store.unfiltered_calls = 0

    selection = backend.search(
        BibliothekarQuery(
            text="System Therapie",
            filters={"file": "technik"},
            max_chunks=3,
        )
    )
    payload = json.loads(selection.prompt_text)

    assert document_store.filter_calls[-2]["filters"] == {
        "operator": "AND",
        "conditions": [
            {"field": "meta.instance_name", "operator": "in", "value": ["Depressionsbot"]},
            {"field": "meta.relative_path", "operator": "in", "value": ["technik"]},
        ],
    }
    assert document_store.filtered_calls >= 1
    assert document_store.unfiltered_calls >= 1
    assert [chunk["file"] for chunk in payload["selected_library_chunks"]] == ["technik.txt"]
    assert "therapie.txt" not in selection.prompt_text


def test_haystack_backend_applies_local_only_filters_after_document_store_read(tmp_path):
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
            filters={"title": "technik"},
            max_chunks=3,
        )
    )
    payload = json.loads(selection.prompt_text)

    assert document_store.filter_calls[-1]["filters"] == {
        "operator": "AND",
        "conditions": [{"field": "meta.instance_name", "operator": "in", "value": ["Depressionsbot"]}],
    }
    assert [chunk["file"] for chunk in payload["selected_library_chunks"]] == ["technik.txt"]
    assert "therapie.txt" not in selection.prompt_text


def test_haystack_backend_does_not_push_private_account_filters_to_document_store(tmp_path):
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
            filters={
                "topics": ["python"],
                "account_id": "private-account-id",
                "identity_key": "telegram:user:1",
                "instance": "AndereInstanz",
                "instance_name": "AndereInstanz",
                "memory_id": "mem_private",
            },
            max_chunks=3,
        )
    )
    payload = json.loads(selection.prompt_text)

    assert document_store.filter_calls[-1]["filters"] == {
        "operator": "AND",
        "conditions": [
            {"field": "meta.instance_name", "operator": "in", "value": ["Depressionsbot"]},
            {"field": "meta.topics", "operator": "in", "value": ["python"]},
        ],
    }
    assert [chunk["file"] for chunk in payload["selected_library_chunks"]] == ["technik.txt"]
    assert "private-account-id" not in selection.prompt_text
    assert "telegram:user:1" not in selection.prompt_text
    assert "AndereInstanz" not in selection.prompt_text
    assert "mem_private" not in selection.prompt_text


def test_haystack_backend_isolates_search_results_by_instance(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    fallback_store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    fallback_store.rebuild()
    document_store = FakeDocumentStore()
    document_store.documents = [
        FakeDocument(
            content="Depression Therapie Aktivierung Schlaf.",
            id="own_chunk",
            meta={
                **_plan2_chunk_meta(chunk_id="own_chunk", relative_path="therapie.txt", locator="Seite 1"),
                "instance_name": "Depressionsbot",
                "topics": ["therapie"],
                "categories": ["psychologie"],
            },
        ),
        FakeDocument(
            content="Fremde Instanz Therapie darf nicht auftauchen.",
            id="foreign_chunk",
            meta={
                "chunk_id": "foreign_chunk",
                "instance_name": "AndereInstanz",
                "relative_path": "fremd.txt",
                "topics": ["therapie"],
                "categories": ["psychologie"],
            },
        ),
    ]
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        fallback_store=fallback_store,
        document_store_factory=lambda: document_store,
        document_class=FakeDocument,
    )

    selection = backend.search(BibliothekarQuery(text="Therapie", max_chunks=3))
    payload = json.loads(selection.prompt_text)

    assert document_store.filter_calls[-1]["filters"] == {
        "operator": "AND",
        "conditions": [{"field": "meta.instance_name", "operator": "in", "value": ["Depressionsbot"]}],
    }
    assert [chunk["chunk_id"] for chunk in payload["selected_library_chunks"]] == ["own_chunk"]
    assert "Fremde Instanz" not in selection.prompt_text


def test_haystack_backend_rejects_uncitable_document_store_chunks(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    fallback_store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    fallback_store.rebuild()
    document_store = FakeDocumentStore()
    document_store.documents = [
        FakeDocument(
            content="Depression Therapie ohne zitierbaren Locator.",
            id="uncitable_chunk",
            meta={
                "chunk_id": "uncitable_chunk",
                "instance_name": "Depressionsbot",
                "relative_path": "therapie.txt",
                "topics": ["therapie"],
                "categories": ["psychologie"],
            },
        )
    ]
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        fallback_store=fallback_store,
        document_store_factory=lambda: document_store,
        document_class=FakeDocument,
    )

    selection = backend.search(BibliothekarQuery(text="Therapie", max_chunks=3))
    payload = json.loads(selection.prompt_text)

    assert "uncitable_chunk" not in selection.selected_ids
    assert [chunk["file"] for chunk in payload["selected_library_chunks"]] == ["therapie.txt"]
    assert all(chunk["locator"] for chunk in payload["selected_library_chunks"])


def test_bibliothekar_rebuilds_contaminated_local_chunk_store_with_account_memory_paths(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    index = store.rebuild()
    account_marker = "ACCOUNT_MEMORY_CONTAMINATED_LOCAL_CHUNK"
    contaminated_chunk = {
        **_plan2_chunk_meta(
            chunk_id="contaminated_account_memory",
            relative_path="data/accounts/account/User_Memory_Entries.jsonl",
            locator="Zeile 1",
        ),
        "instance_name": "Depressionsbot",
        "topics": ["therapie"],
        "categories": ["psychologie"],
        "text": f"Diese Account-Memory darf nicht in Quellenkontext: {account_marker}",
    }
    index["chunk_count"] = int(index["chunk_count"]) + 1
    store.index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    with store.chunks_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(contaminated_chunk, ensure_ascii=False, sort_keys=True) + "\n")

    selection = store.select("Therapie", max_chunks=3)
    payload = json.loads(selection.prompt_text)

    assert account_marker not in selection.prompt_text
    assert "data/accounts" not in selection.prompt_text
    assert [chunk["file"] for chunk in payload["selected_library_chunks"]] == ["therapie.txt"]


def test_bibliothekar_rejects_absolute_or_uri_chunk_source_paths(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    index = store.rebuild()
    path_markers = {
        "absolute_windows": "C:/Users/teladi/private/therapie.txt",
        "absolute_uri": "file:///home/teladi/private/therapie.txt",
    }
    index["chunk_count"] = int(index["chunk_count"]) + len(path_markers)
    store.index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    with store.chunks_path.open("a", encoding="utf-8") as file:
        for chunk_id, source_path in path_markers.items():
            file.write(
                json.dumps(
                    {
                        **_plan2_chunk_meta(
                            chunk_id=chunk_id,
                            relative_path=source_path,
                            locator="Seite 1",
                        ),
                        "instance_name": "Depressionsbot",
                        "topics": ["therapie"],
                        "categories": ["psychologie"],
                        "text": f"Privater Hostpfad darf nicht in Quellenkontext: {source_path}",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )

    selection = store.select("Therapie", max_chunks=3)
    payload = json.loads(selection.prompt_text)

    assert "C:/Users" not in selection.prompt_text
    assert "file:///home" not in selection.prompt_text
    assert [chunk["file"] for chunk in payload["selected_library_chunks"]] == ["therapie.txt"]


def test_bibliothekar_rebuilds_traversal_chunk_source_paths(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    index = store.rebuild()
    path_markers = {
        "parent_exact": "..",
        "parent_terminal": "books/..",
    }
    index["chunk_count"] = int(index["chunk_count"]) + len(path_markers)
    store.index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    with store.chunks_path.open("a", encoding="utf-8") as file:
        for chunk_id, source_path in path_markers.items():
            file.write(
                json.dumps(
                    {
                        **_plan2_chunk_meta(
                            chunk_id=chunk_id,
                            relative_path=source_path,
                            locator="Seite 1",
                        ),
                        "file_type": "txt",
                        "suffix": ".txt",
                        "instance_name": "Depressionsbot",
                        "topics": ["therapie"],
                        "categories": ["psychologie"],
                        "text": f"Traversal-Pfad darf nicht in Quellenkontext: {source_path}",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )

    selection = store.select("Therapie", max_chunks=3)
    payload = json.loads(selection.prompt_text)

    assert "Traversal-Pfad" not in selection.prompt_text
    assert '".."' not in selection.prompt_text
    assert "books/.." not in selection.prompt_text
    assert [chunk["file"] for chunk in payload["selected_library_chunks"]] == ["therapie.txt"]


def test_haystack_backend_rejects_contaminated_document_store_chunks_with_account_memory_paths(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    fallback_store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    fallback_store.rebuild()
    account_marker = "ACCOUNT_MEMORY_CONTAMINATED_HAYSTACK_CHUNK"
    document_store = FakeDocumentStore()
    document_store.documents = [
        FakeDocument(
            content=f"Diese Account-Memory darf nicht in Haystack-Kontext: {account_marker}",
            id="contaminated_account_memory",
            meta={
                **_plan2_chunk_meta(
                    chunk_id="contaminated_account_memory",
                    relative_path="data/accounts/account/User_Memory_Entries.jsonl",
                    locator="Zeile 1",
                ),
                "instance_name": "Depressionsbot",
                "topics": ["therapie"],
                "categories": ["psychologie"],
            },
        )
    ]
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        fallback_store=fallback_store,
        document_store_factory=lambda: document_store,
        document_class=FakeDocument,
    )

    selection = backend.search(BibliothekarQuery(text="Therapie", max_chunks=3))
    payload = json.loads(selection.prompt_text)

    assert account_marker not in selection.prompt_text
    assert "data/accounts" not in selection.prompt_text
    assert [chunk["file"] for chunk in payload["selected_library_chunks"]] == ["therapie.txt"]


def test_haystack_backend_rejects_absolute_or_uri_source_paths(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    fallback_store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    fallback_store.rebuild()
    document_store = FakeDocumentStore()
    document_store.documents = [
        FakeDocument(
            content="Privater Hostpfad darf nicht in Haystack-Kontext.",
            id="absolute_windows",
            meta={
                **_plan2_chunk_meta(
                    chunk_id="absolute_windows",
                    relative_path="C:/Users/teladi/private/therapie.txt",
                    locator="Seite 1",
                ),
                "instance_name": "Depressionsbot",
                "topics": ["therapie"],
                "categories": ["psychologie"],
            },
        ),
        FakeDocument(
            content="Privater URI-Pfad darf nicht in Haystack-Kontext.",
            id="absolute_uri",
            meta={
                **_plan2_chunk_meta(
                    chunk_id="absolute_uri",
                    relative_path="file:///home/teladi/private/therapie.txt",
                    locator="Seite 1",
                ),
                "instance_name": "Depressionsbot",
                "topics": ["therapie"],
                "categories": ["psychologie"],
            },
        ),
    ]
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        fallback_store=fallback_store,
        document_store_factory=lambda: document_store,
        document_class=FakeDocument,
    )

    selection = backend.search(BibliothekarQuery(text="Therapie", max_chunks=3))
    payload = json.loads(selection.prompt_text)

    assert "C:/Users" not in selection.prompt_text
    assert "file:///home" not in selection.prompt_text
    assert [chunk["file"] for chunk in payload["selected_library_chunks"]] == ["therapie.txt"]


def test_haystack_backend_rejects_traversal_source_paths(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    fallback_store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    fallback_store.rebuild()
    document_store = FakeDocumentStore()
    document_store.documents = [
        FakeDocument(
            content="Traversal-Pfad darf nicht in Haystack-Kontext: parent exact.",
            id="parent_exact",
            meta={
                **_plan2_chunk_meta(
                    chunk_id="parent_exact",
                    relative_path="..",
                    locator="Seite 1",
                ),
                "file_type": "txt",
                "suffix": ".txt",
                "instance_name": "Depressionsbot",
                "topics": ["therapie"],
                "categories": ["psychologie"],
            },
        ),
        FakeDocument(
            content="Traversal-Pfad darf nicht in Haystack-Kontext: parent terminal.",
            id="parent_terminal",
            meta={
                **_plan2_chunk_meta(
                    chunk_id="parent_terminal",
                    relative_path="books/..",
                    locator="Seite 1",
                ),
                "file_type": "txt",
                "suffix": ".txt",
                "instance_name": "Depressionsbot",
                "topics": ["therapie"],
                "categories": ["psychologie"],
            },
        ),
    ]
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        fallback_store=fallback_store,
        document_store_factory=lambda: document_store,
        document_class=FakeDocument,
    )

    selection = backend.search(BibliothekarQuery(text="Therapie", max_chunks=3))
    payload = json.loads(selection.prompt_text)

    assert "Traversal-Pfad" not in selection.prompt_text
    assert '".."' not in selection.prompt_text
    assert "books/.." not in selection.prompt_text
    assert [chunk["file"] for chunk in payload["selected_library_chunks"]] == ["therapie.txt"]


def test_haystack_rebuild_does_not_delete_other_instance_documents(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    fallback_store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    document_store = FakeDocumentStore()
    document_store.documents = [
        FakeDocument(
            content="Alter eigener Chunk",
            id="stale_own_chunk",
            meta={"chunk_id": "stale_own_chunk", "instance_name": "Depressionsbot"},
        ),
        FakeDocument(
            content="Andere Instanz",
            id="foreign_chunk",
            meta={"chunk_id": "foreign_chunk", "instance_name": "AndereInstanz"},
        ),
    ]
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        fallback_store=fallback_store,
        document_store_factory=lambda: document_store,
        document_class=FakeDocument,
    )

    backend.rebuild()

    assert "stale_own_chunk" in document_store.deleted_document_ids
    assert "foreign_chunk" not in document_store.deleted_document_ids
    assert any(document.id == "foreign_chunk" for document in document_store.documents)
    assert all(
        document.meta.get("instance_name") == "Depressionsbot"
        for document in document_store.documents
        if str(document.id).startswith("lib_")
    )


def test_bibliothekar_ignores_private_only_filters_instead_of_emptying_results(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    store.rebuild()
    service = BibliothekarService(LocalBibliothekarBackend(store))

    selection = service.search(
        "Therapie",
        filters={"account_id": "private-account-id", "memory_id": "mem_private"},
        max_chunks=1,
    )
    payload = json.loads(selection.prompt_text)

    assert selection.selected_ids
    assert payload["selected_library_chunks"][0]["file"] == "therapie.txt"
    assert "private-account-id" not in selection.prompt_text
    assert "mem_private" not in selection.prompt_text


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
    document_store.rejected_filter_calls = 0
    document_store.unfiltered_calls = 0

    selection = backend.search(BibliothekarQuery(text="System Therapie", filters={"topics": ["python"]}, max_chunks=3))
    payload = json.loads(selection.prompt_text)

    assert document_store.rejected_filter_calls == 1
    assert document_store.unfiltered_calls >= 1
    assert [chunk["file"] for chunk in payload["selected_library_chunks"]] == ["technik.txt"]
    assert "therapie.txt" not in selection.prompt_text


def test_haystack_backend_retries_unfiltered_store_when_filter_pushdown_returns_empty(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    (library_dir / "technik.txt").write_text("Python Software Daten System Algorithmus.", encoding="utf-8")
    document_store = EmptyFilteredDocumentStore()
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        document_store_factory=lambda: document_store,
        document_class=FakeDocument,
    )
    backend.rebuild()
    document_store.filtered_calls = 0
    document_store.unfiltered_calls = 0
    document_store.write_attempts = 0

    selection = backend.search(BibliothekarQuery(text="System Therapie", filters={"topics": ["python"]}, max_chunks=3))
    payload = json.loads(selection.prompt_text)

    assert document_store.filtered_calls == 1
    assert document_store.unfiltered_calls >= 1
    assert document_store.write_attempts == 0
    assert [chunk["file"] for chunk in payload["selected_library_chunks"]] == ["technik.txt"]
    assert "therapie.txt" not in selection.prompt_text


def test_haystack_backend_retries_empty_instance_filter_pushdown_without_rebuild(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    fallback_store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    fallback_store.rebuild()
    document_store = EmptyFilteredDocumentStore()
    document_store.documents = [
        FakeDocument(
            content="Depression Therapie Aktivierung Schlaf.",
            id="own_chunk",
            meta={
                **_plan2_chunk_meta(chunk_id="own_chunk", relative_path="therapie.txt", locator="Seite 1"),
                "instance_name": "Depressionsbot",
                "topics": ["therapie"],
                "categories": ["psychologie"],
            },
        ),
        FakeDocument(
            content="Fremde Instanz Therapie darf nicht auftauchen.",
            id="foreign_chunk",
            meta={
                **_plan2_chunk_meta(chunk_id="foreign_chunk", relative_path="fremd.txt", locator="Seite 1"),
                "instance_name": "AndereInstanz",
                "topics": ["therapie"],
                "categories": ["psychologie"],
            },
        ),
    ]
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        fallback_store=fallback_store,
        document_store_factory=lambda: document_store,
        document_class=FakeDocument,
    )

    selection = backend.search(BibliothekarQuery(text="Therapie", max_chunks=3))
    payload = json.loads(selection.prompt_text)

    assert document_store.filtered_calls == 1
    assert document_store.unfiltered_calls >= 1
    assert document_store.write_attempts == 0
    assert [chunk["chunk_id"] for chunk in payload["selected_library_chunks"]] == ["own_chunk"]
    assert "Fremde Instanz" not in selection.prompt_text


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


def test_bibliothekar_rebuild_skips_sensitive_files_copied_into_library(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    sensitive_dir = library_dir / "data" / "accounts" / ("a" * 128)
    sensitive_dir.mkdir(parents=True)
    safe_marker = "SAFE_LIBRARY_MARKER_E431"
    sensitive_marker = "SENSITIVE_LIBRARY_MARKER_8B2A"
    (library_dir / "therapie.txt").write_text(
        f"Depression Therapie Aktivierung Schlaf {safe_marker}.",
        encoding="utf-8",
    )
    (sensitive_dir / "User_Habbits_and_behave.md").write_text(
        f"Private Account-Notiz darf nie in den Bibliothekar-Index: {sensitive_marker}",
        encoding="utf-8",
    )

    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    index = store.rebuild()
    chunks_text = store.chunks_path.read_text(encoding="utf-8")
    index_text = json.dumps(index, ensure_ascii=False, sort_keys=True)
    selection = store.select("Therapie Private", max_chunks=3)

    assert index["chunk_count"] == 1
    assert safe_marker in chunks_text
    assert sensitive_marker not in chunks_text
    assert sensitive_marker not in index_text
    assert sensitive_marker not in selection.prompt_text
    assert "data/accounts" not in chunks_text
    assert "User_Habbits_and_behave.md" not in index_text


def test_bibliothekar_rebuild_skips_source_harvester_staging_dirs(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    safe_marker = "SAFE_LIBRARY_MARKER_C734"
    staged_markers = {
        "accepted": "STAGED_ACCEPTED_MARKER_115B",
        "quarantine": "STAGED_QUARANTINE_MARKER_4EA1",
        "rejected": "STAGED_REJECTED_MARKER_37A9",
        "inbox": "STAGED_INBOX_MARKER_D9C2",
    }
    (library_dir / "therapie.txt").write_text(
        f"Depression Therapie Aktivierung Schlaf {safe_marker}.",
        encoding="utf-8",
    )
    for dirname, marker in staged_markers.items():
        staged_dir = library_dir / dirname
        staged_dir.mkdir()
        (staged_dir / f"{dirname}.txt").write_text(
            f"Diese Harvest-Staging-Datei darf nicht blind indexiert werden: {marker}.",
            encoding="utf-8",
        )

    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    index = store.rebuild()
    chunks_text = store.chunks_path.read_text(encoding="utf-8")
    index_text = json.dumps(index, ensure_ascii=False, sort_keys=True)

    assert index["chunk_count"] == 1
    assert safe_marker in chunks_text
    for dirname, marker in staged_markers.items():
        assert marker not in chunks_text
        assert marker not in index_text
        assert f"{dirname}.txt" not in index_text


def test_bibliothekar_rebuild_skips_symlinked_library_files(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    outside_secret = tmp_path / "outside-secret.txt"
    outside_secret.write_text("PRIVATE HOST SECRET MUST NOT BE INDEXED", encoding="utf-8")
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    (library_dir / "linked-secret.txt").symlink_to(outside_secret)

    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    index = store.rebuild()
    chunks_text = store.chunks_path.read_text(encoding="utf-8")

    assert index["chunk_count"] == 1
    assert "therapie.txt" in chunks_text
    assert "linked-secret.txt" not in chunks_text
    assert "PRIVATE HOST SECRET" not in chunks_text


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


def test_haystack_backend_search_falls_back_to_local_store_when_document_store_stays_empty(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    document_store = NonPersistingDocumentStore()
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        document_store_factory=lambda: document_store,
        document_class=FakeDocument,
    )

    selection = backend.search(BibliothekarQuery(text="Therapie", filters={"topics": ["therapie"]}, max_chunks=1))
    payload = json.loads(selection.prompt_text)

    assert document_store.write_attempts == 1
    assert selection.selected_ids
    assert payload["selected_library_chunks"][0]["file"] == "therapie.txt"
    assert payload["selected_library_chunks"][0]["citation_format"].startswith("[Quelle:")


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


def test_llamaindex_backend_uses_fake_query_engine_chunks(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")

    class FakeQueryEngine:
        def __init__(self, store):
            store.rebuild()
            self.chunks = [json.loads(line) for line in store.chunks_path.read_text(encoding="utf-8").splitlines()]
            self.queries = []

        def search(self, query_text):
            self.queries.append(query_text)
            return self.chunks

    created = []

    def factory(store):
        engine = FakeQueryEngine(store)
        created.append(engine)
        return engine

    backend = LlamaIndexBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        query_engine_factory=factory,
    )

    selection = backend.search(BibliothekarQuery(text="Therapie", max_chunks=1))
    payload = json.loads(selection.prompt_text)

    assert selection.selected_ids
    assert payload["selected_library_chunks"][0]["file"] == "therapie.txt"
    assert created[0].queries == ["Therapie"]


def test_llamaindex_backend_caches_factory_engine_after_factory_rebuild(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")

    class FakeQueryEngine:
        def __init__(self, store):
            store.rebuild()
            self.chunks = [json.loads(line) for line in store.chunks_path.read_text(encoding="utf-8").splitlines()]
            self.queries = []

        def search(self, query_text):
            self.queries.append(query_text)
            return self.chunks

    created = []

    def factory(store):
        engine = FakeQueryEngine(store)
        created.append(engine)
        return engine

    backend = LlamaIndexBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        query_engine_factory=factory,
    )

    first = backend.search(BibliothekarQuery(text="Therapie", max_chunks=1))
    second = backend.search(BibliothekarQuery(text="Schlaf", max_chunks=1))

    assert first.selected_ids
    assert second.selected_ids
    assert len(created) == 1
    assert created[0].queries == ["Therapie", "Schlaf"]


def test_llamaindex_backend_filters_foreign_instance_chunks(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")

    class FakeQueryEngine:
        def __init__(self, store):
            store.rebuild()
            own_chunk = json.loads(store.chunks_path.read_text(encoding="utf-8").splitlines()[0])
            own_chunk["instance_name"] = "Depressionsbot"
            foreign_chunk = {
                **own_chunk,
                "chunk_id": "foreign_chunk",
                "instance_name": "AndereInstanz",
                "relative_path": "fremd.txt",
                "file_path": "fremd.txt",
                "title": "Fremde Quelle",
                "text": "Fremde Instanz Therapie darf nicht auftauchen.",
            }
            self.chunks = [foreign_chunk, own_chunk]

        def search(self, _query_text):
            return self.chunks

    backend = LlamaIndexBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        query_engine_factory=FakeQueryEngine,
    )

    selection = backend.search(BibliothekarQuery(text="Therapie", max_chunks=2))
    payload = json.loads(selection.prompt_text)

    assert [chunk["file"] for chunk in payload["selected_library_chunks"]] == ["therapie.txt"]
    assert selection.selected_ids == (payload["selected_library_chunks"][0]["chunk_id"],)
    assert "Fremde Instanz" not in selection.prompt_text


def test_llamaindex_backend_refreshes_cached_query_engine_after_library_change(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")

    class FakeQueryEngine:
        def __init__(self, store):
            self.chunks = [json.loads(line) for line in store.chunks_path.read_text(encoding="utf-8").splitlines()]
            self.queries = []

        def search(self, query_text):
            self.queries.append(query_text)
            return self.chunks

    created = []

    def factory(store):
        engine = FakeQueryEngine(store)
        created.append(engine)
        return engine

    backend = LlamaIndexBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        query_engine_factory=factory,
    )

    first = backend.search(BibliothekarQuery(text="Therapie", max_chunks=1))
    (library_dir / "achtsamkeit.txt").write_text("Achtsamkeit Atmung Gegenwart Koerper.", encoding="utf-8")
    second = backend.search(BibliothekarQuery(text="Achtsamkeit", max_chunks=1))
    second_payload = json.loads(second.prompt_text)

    assert first.selected_ids
    assert len(created) == 2
    assert created[0].queries == ["Therapie"]
    assert created[1].queries == ["Achtsamkeit"]
    assert second_payload["selected_library_chunks"][0]["file"] == "achtsamkeit.txt"


def test_llamaindex_backend_accepts_chat_engine_source_nodes(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")

    class FakeNode:
        def __init__(self, chunk):
            self.text = chunk["text"]
            self.metadata = {key: value for key, value in chunk.items() if key != "text"}

    class FakeSourceNode:
        def __init__(self, chunk):
            self.node = FakeNode(chunk)

    class FakeChatResponse:
        def __init__(self, chunks):
            self.source_nodes = [FakeSourceNode(chunk) for chunk in chunks]

    class FakeChatEngine:
        def __init__(self, store):
            store.rebuild()
            self.chunks = [json.loads(line) for line in store.chunks_path.read_text(encoding="utf-8").splitlines()]
            self.queries = []

        def chat(self, query_text):
            self.queries.append(query_text)
            return FakeChatResponse(self.chunks)

    created = []

    def factory(store):
        engine = FakeChatEngine(store)
        created.append(engine)
        return engine

    backend = LlamaIndexBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        query_engine_factory=factory,
    )

    selection = backend.search(BibliothekarQuery(text="Therapie", max_chunks=1))
    payload = json.loads(selection.prompt_text)

    assert selection.selected_ids
    assert payload["selected_library_chunks"][0]["file"] == "therapie.txt"
    assert created[0].queries == ["Therapie"]


def test_llamaindex_backend_rejects_source_nodes_without_text_and_uses_local_fallback(tmp_path):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")

    class FakeNode:
        def __init__(self, chunk):
            self.text = ""
            self.metadata = {key: value for key, value in chunk.items() if key != "text"}

    class FakeSourceNode:
        def __init__(self, chunk):
            self.node = FakeNode(chunk)

    class FakeResponse:
        def __init__(self, chunks):
            self.source_nodes = [FakeSourceNode(chunk) for chunk in chunks]

    class FakeQueryEngine:
        def __init__(self, store):
            store.rebuild()
            self.chunks = [json.loads(line) for line in store.chunks_path.read_text(encoding="utf-8").splitlines()]

        def query(self, _query_text):
            return FakeResponse(self.chunks)

    backend = LlamaIndexBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        query_engine_factory=FakeQueryEngine,
    )

    selection = backend.search(BibliothekarQuery(text="Therapie", max_chunks=1))
    payload = json.loads(selection.prompt_text)

    assert selection.selected_ids
    assert "Therapie" in payload["selected_library_chunks"][0]["quote"]


def test_llamaindex_backend_falls_back_to_local_when_optional_dependency_missing(tmp_path, monkeypatch):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    monkeypatch.setattr("TeeBotus.runtime.bibliothekar_service._module_available", lambda _name: False)
    backend = LlamaIndexBibliothekarBackend(instance_name="Depressionsbot", instances_dir=tmp_path / "instances")

    selection = backend.search(BibliothekarQuery(text="Therapie", max_chunks=1))
    payload = json.loads(selection.prompt_text)

    assert selection.selected_ids
    assert payload["selected_library_chunks"][0]["file"] == "therapie.txt"


def test_llamaindex_backend_without_dependency_uses_local_fallback(tmp_path, monkeypatch):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    monkeypatch.setattr("TeeBotus.runtime.bibliothekar_service._module_available", lambda _name: False)
    backend = LlamaIndexBibliothekarBackend(instance_name="Depressionsbot", instances_dir=tmp_path / "instances")

    selection = backend.search(BibliothekarQuery(text="Therapie", max_chunks=1))
    payload = json.loads(selection.prompt_text)

    assert backend.available is False
    assert selection.selected_ids
    assert payload["selected_library_chunks"][0]["file"] == "therapie.txt"


def test_llamaindex_backend_without_query_engine_factory_builds_default_local_retriever(tmp_path, monkeypatch):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    monkeypatch.setattr("TeeBotus.runtime.bibliothekar_service._module_available", lambda name: name == "llama_index.core")
    created = []

    class FakeDefaultRetriever:
        def __init__(self, store, max_chunks):
            store.rebuild()
            self.max_chunks = max_chunks
            self.chunks = [json.loads(line) for line in store.chunks_path.read_text(encoding="utf-8").splitlines()]
            self.queries = []

        def retrieve(self, query_text):
            self.queries.append(query_text)
            return self.chunks

    def fake_build_default(self, max_chunks=bibliothekar_service_module.DEFAULT_MAX_CHUNKS):
        engine = FakeDefaultRetriever(self.fallback_store, max_chunks)
        created.append(engine)
        return engine

    monkeypatch.setattr(LlamaIndexBibliothekarBackend, "_build_default_query_engine", fake_build_default)
    backend = LlamaIndexBibliothekarBackend(instance_name="Depressionsbot", instances_dir=tmp_path / "instances")

    selection = backend.search(BibliothekarQuery(text="Therapie", max_chunks=1))
    payload = json.loads(selection.prompt_text)

    assert backend.available is True
    assert selection.selected_ids
    assert payload["selected_library_chunks"][0]["file"] == "therapie.txt"
    assert created[0].queries == ["Therapie"]
    assert created[0].max_chunks == 1


def test_llamaindex_backend_default_retriever_uses_query_max_chunks(tmp_path, monkeypatch):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    for index in range(9):
        (library_dir / f"therapie-{index}.txt").write_text(
            f"Depression Therapie Aktivierung Schlaf Nummer {index}.",
            encoding="utf-8",
        )
    monkeypatch.setattr("TeeBotus.runtime.bibliothekar_service._module_available", lambda name: name == "llama_index.core")
    created_max_chunks = []

    class FakeDefaultRetriever:
        def __init__(self, store, max_chunks):
            store.rebuild()
            created_max_chunks.append(max_chunks)
            self.chunks = [json.loads(line) for line in store.chunks_path.read_text(encoding="utf-8").splitlines()]

        def retrieve(self, _query_text):
            return self.chunks

    def fake_build_default(self, max_chunks=bibliothekar_service_module.DEFAULT_MAX_CHUNKS):
        return FakeDefaultRetriever(self.fallback_store, max_chunks)

    monkeypatch.setattr(LlamaIndexBibliothekarBackend, "_build_default_query_engine", fake_build_default)
    backend = LlamaIndexBibliothekarBackend(instance_name="Depressionsbot", instances_dir=tmp_path / "instances")

    selection = backend.search(BibliothekarQuery(text="Therapie", max_chunks=9, max_prompt_chars=20000))
    payload = json.loads(selection.prompt_text)

    assert created_max_chunks == [9]
    assert len(payload["selected_library_chunks"]) == 9
    assert len(selection.selected_ids) == 9


def test_llamaindex_health_reports_missing_dependency_as_unavailable_without_crashing(tmp_path, monkeypatch):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    monkeypatch.setattr("TeeBotus.runtime.bibliothekar_service._module_available", lambda _name: False)

    health = check_bibliothekar_service(
        "Depressionsbot",
        tmp_path / "instances",
        BotInstructions(bibliothekar_backend="llamaindex"),
    )

    assert health.backend == "llamaindex"
    assert health.status == "unavailable"
    assert health.store == "json"
    assert "missing optional dependency" in health.error
    assert health.documents == 1
    assert health.chunks == 1


def test_llamaindex_health_reports_default_local_retriever_as_ready(tmp_path, monkeypatch):
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    monkeypatch.setattr("TeeBotus.runtime.bibliothekar_service._module_available", lambda name: name == "llama_index.core")
    monkeypatch.setattr(LlamaIndexBibliothekarBackend, "_build_default_query_engine", lambda self, max_chunks=bibliothekar_service_module.DEFAULT_MAX_CHUNKS: object())

    health = check_bibliothekar_service(
        "Depressionsbot",
        tmp_path / "instances",
        BotInstructions(bibliothekar_backend="llamaindex"),
    )

    assert health.backend == "llamaindex"
    assert health.status == "ready"
    assert health.store == "llamaindex"
    assert health.target == "local_in_memory"
    assert health.error == ""
    assert health.documents == 1
    assert health.chunks == 1


def test_llamaindex_vector_index_builder_never_falls_back_without_explicit_local_embedding():
    calls = []

    class RejectingVectorStoreIndex:
        @classmethod
        def from_documents(cls, _documents, **kwargs):
            calls.append(dict(kwargs))
            raise TypeError("unsupported kwargs")

    try:
        bibliothekar_service_module._llamaindex_vector_index_from_documents(
            RejectingVectorStoreIndex,
            [object()],
            embed_model="local-mock-embedding",
        )
    except RuntimeError as exc:
        assert "explicit local embed_model" in str(exc)
    else:  # pragma: no cover - defensive assertion for the no-remote invariant.
        raise AssertionError("LlamaIndex builder must not fall back without explicit local embedding")

    assert calls == [
        {"embed_model": "local-mock-embedding", "show_progress": False},
        {"embed_model": "local-mock-embedding"},
    ]


def test_llamaindex_vector_index_builder_uses_second_explicit_embedding_signature():
    calls = []

    class AcceptingVectorStoreIndex:
        @classmethod
        def from_documents(cls, _documents, **kwargs):
            calls.append(dict(kwargs))
            if "show_progress" in kwargs:
                raise TypeError("show_progress unsupported")
            return "index"

    index = bibliothekar_service_module._llamaindex_vector_index_from_documents(
        AcceptingVectorStoreIndex,
        [object()],
        embed_model="local-mock-embedding",
    )

    assert index == "index"
    assert calls == [
        {"embed_model": "local-mock-embedding", "show_progress": False},
        {"embed_model": "local-mock-embedding"},
    ]


def test_haystack_backend_detects_installed_qdrant_haystack_integration(tmp_path):
    backend = HaystackBibliothekarBackend(
        instance_name="Depressionsbot",
        instances_dir=tmp_path / "instances",
        collection="therapy_books",
    )

    assert backend.available is True


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
    assert health.target == "http://127.0.0.1:6333"
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
        BotInstructions(
            bibliothekar_backend="haystack",
            bibliothekar_collection="therapy_books",
            bibliothekar_qdrant_url="http://localhost:6334/",
        ),
    )

    assert health.backend == "haystack"
    assert health.store == "qdrant"
    assert health.status == "reachable"
    assert health.collection == "therapy_books"
    assert health.target == "http://localhost:6334"
    assert health.documents == 1
    assert health.chunks == 1


def test_haystack_status_rejects_nonlocal_qdrant_url(tmp_path, monkeypatch):
    monkeypatch.setattr("TeeBotus.runtime.bibliothekar_service._module_available", lambda _name: True)

    health = check_bibliothekar_service(
        "Depressionsbot",
        tmp_path / "instances",
        BotInstructions(
            bibliothekar_backend="haystack",
            bibliothekar_collection="therapy_books",
            bibliothekar_qdrant_url="http://qdrant.example:6333",
        ),
    )

    assert health.backend == "haystack"
    assert health.store == "qdrant"
    assert health.status == "unavailable"
    assert "must stay local" in health.error


def test_haystack_status_rejects_qdrant_url_query_fragment_path_or_missing_port(tmp_path, monkeypatch):
    monkeypatch.setattr("TeeBotus.runtime.bibliothekar_service._module_available", lambda _name: True)

    cases = (
        ("http://127.0.0.1:6333?api_key=plain-secret", "must not contain query parameters or fragments"),
        ("http://127.0.0.1:6333#token", "must not contain query parameters or fragments"),
        ("http://127.0.0.1:6333/collections", "must be a base URL without a path"),
        ("http://127.0.0.1:99999", "must include a valid port"),
        ("http://127.0.0.1:0", "must include a valid port"),
        ("http://127.0.0.1:bad", "must include a valid port"),
        ("http://127.0.0.1", "must include an explicit port"),
        ("http://[::1", "must be a valid URL"),
    )
    for url, expected_error in cases:
        health = check_bibliothekar_service(
            "Depressionsbot",
            tmp_path / "instances",
            BotInstructions(
                bibliothekar_backend="haystack",
                bibliothekar_collection="therapy_books",
                bibliothekar_qdrant_url=url,
            ),
        )

        assert health.backend == "haystack"
        assert health.store == "qdrant"
        assert health.status == "unavailable"
        assert expected_error in health.error


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


def test_engine_bibliothekar_context_honors_optional_citation_requirement(tmp_path):
    class FakeBibliothekarService:
        def search(self, query_text, **kwargs):
            return SimpleSelection('{"selected_library_chunks":[{"file":"service.txt","chunk_id":"chunk-1"}]}')

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
    fake_client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, bibliothekar_enabled=True),
        openai_client=fake_client,
        bibliothekar_store=FakeBibliothekarService(),
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

    engine._openai_actions(
        event,
        account_id,
        BotInstructions(openai_enabled=True, bibliothekar_enabled=True, bibliothekar_require_citations=False),
    )

    assert "fuer reine Hintergrundnutzung reicht Paraphrase" in fake_client.prompt
    assert "konkrete Aussagen daraus ableitest" not in fake_client.prompt


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
            "filters": {"file": ["schlaf.txt"], "topic": ["Depression", "Schlaf"]},
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
    assert service.calls[0][1]["filters"] == {"file": ["schlaf.txt"], "topic": ["Depression", "Schlaf"]}
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
        - qdrant_url: http://localhost:6334
        - max_prompt_chars: 2222
        - max_chunks: 2
        - max_quote_chars: 333
        - require_citations: nein
        """
    )

    assert instructions.bibliothekar_enabled is False
    assert instructions.bibliothekar_backend == "haystack"
    assert instructions.bibliothekar_collection == "therapie_buecher"
    assert instructions.bibliothekar_qdrant_url == "http://localhost:6334"
    assert instructions.bibliothekar_max_prompt_chars == 2222
    assert instructions.bibliothekar_max_chunks == 2
    assert instructions.bibliothekar_max_quote_chars == 333
    assert instructions.bibliothekar_require_citations is False


def test_bibliothekar_default_collection_matches_plan3_qdrant_collection():
    instructions = parse_instructions("")

    assert instructions.bibliothekar_collection == QDRANT_BIBLIOTHEKAR_COLLECTION
    assert instructions.bibliothekar_collection == "teebotus_bibliothekar_chunks"


def test_bibliothekar_llamaindex_backend_setting_is_parsed():
    instructions = parse_instructions(
        """
        ## Bibliothekar
        - backend: llama-index
        """
    )

    assert instructions.bibliothekar_backend == "llamaindex"


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
    assert "Depressionsbot: backend=local store=json collection=teebotus_bibliothekar_chunks status=ready documents=1 chunks=1" in status_output
    assert "target=" not in status_output

    assert bibliothekar_cli_main(["--instances-dir", str(instances_dir), "--instance", "Depressionsbot", "query", "Therapie", "--top-k", "1"]) == 0
    query_output = capsys.readouterr().out
    assert "Depressionsbot: backend=local selected=1" in query_output
    assert "therapie.txt" in query_output


def test_bibliothekar_cli_index_source_can_point_to_existing_library(tmp_path, capsys):
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    library_dir = instance_dir / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## Bibliothekar\n- backend: local\n", encoding="utf-8")
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung.", encoding="utf-8")

    assert (
        bibliothekar_cli_main(
            [
                "--instances-dir",
                str(instances_dir),
                "--instance",
                "Depressionsbot",
                "index",
                "--source",
                str(library_dir),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "Depressionsbot: 1 Dokumente, 1 Chunks, dry_run=False" in output


def test_bibliothekar_cli_harvest_gates_source_before_ingest(tmp_path, capsys):
    source = tmp_path / "quelle.txt"
    source.write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## Bibliothekar\n- backend: local\n", encoding="utf-8")

    assert (
        bibliothekar_cli_main(
            [
                "--instances-dir",
                str(instances_dir),
                "--instance",
                "Depressionsbot",
                "--json",
                "harvest",
                str(source),
                "--title",
                "Therapiequelle",
                "--license",
                "private",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    row = payload["results"][0]
    stored_path = Path(row["stored_path"])
    assert row["route"] == "accepted"
    assert row["accepted_for_ingest"] is True
    assert stored_path.parent.name == "accepted"
    assert stored_path.exists()
    assert source.exists()

    assert bibliothekar_cli_main(["--instances-dir", str(instances_dir), "--instance", "Depressionsbot", "--json", "promote", str(stored_path)]) == 0
    promote_payload = json.loads(capsys.readouterr().out)
    promoted_path = Path(promote_payload["results"][0]["promoted_path"])
    assert promoted_path.parent.name == "books"
    assert promoted_path.exists()

    assert bibliothekar_cli_main(["--instances-dir", str(instances_dir), "--instance", "Depressionsbot", "index"]) == 0
    index_output = capsys.readouterr().out
    assert "Depressionsbot: 1 Dokumente, 1 Chunks, dry_run=False" in index_output

    assert bibliothekar_cli_main(["--instances-dir", str(instances_dir), "--instance", "Depressionsbot", "--json", "query", "Therapie", "--top-k", "1"]) == 0
    query_payload = json.loads(capsys.readouterr().out)
    prompt_payload = json.loads(query_payload["results"][0]["prompt_text"])
    prompt_chunk = prompt_payload["selected_library_chunks"][0]
    assert prompt_chunk["title"] == "Therapiequelle"
    assert prompt_chunk["license"] == "private"
    assert prompt_chunk["source_quality"] == "usable"
    assert prompt_chunk["citation_quality"] == "usable"
    assert prompt_chunk["source_harvest_route"] == "accepted"


def test_bibliothekar_cli_status_reports_haystack_target_in_text_and_json(tmp_path, capsys, monkeypatch):
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    library_dir = instance_dir / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text(
        "## Bibliothekar\n- backend: haystack\n- collection: therapy_books\n- qdrant_url: http://localhost:6334\n",
        encoding="utf-8",
    )
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")

    class EmptyDocumentStore:
        def filter_documents(self, **_kwargs):
            return []

    monkeypatch.setattr("TeeBotus.runtime.bibliothekar_service._module_available", lambda _name: True)
    monkeypatch.setattr(
        "TeeBotus.runtime.bibliothekar_service.HaystackBibliothekarBackend._document_store",
        lambda _self: EmptyDocumentStore(),
    )

    assert bibliothekar_cli_main(["--instances-dir", str(instances_dir), "--instance", "Depressionsbot", "status"]) == 0
    text_output = capsys.readouterr().out
    assert (
        "Depressionsbot: backend=haystack store=qdrant collection=therapy_books "
        "target=http://localhost:6334 status=reachable documents=1 chunks=1"
    ) in text_output

    assert bibliothekar_cli_main(["--instances-dir", str(instances_dir), "--instance", "Depressionsbot", "--json", "status"]) == 0
    json_output = capsys.readouterr().out
    payload = json.loads(json_output)
    assert payload["results"][0]["target"] == "http://localhost:6334"


def test_bibliothekar_cli_status_reports_llamaindex_ready_in_text_and_json(tmp_path, capsys, monkeypatch):
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    library_dir = instance_dir / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text(
        "## Bibliothekar\n- backend: llamaindex\n",
        encoding="utf-8",
    )
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung Schlaf.", encoding="utf-8")
    monkeypatch.setattr("TeeBotus.runtime.bibliothekar_service._module_available", lambda name: name == "llama_index.core")
    monkeypatch.setattr(
        LlamaIndexBibliothekarBackend,
        "_build_default_query_engine",
        lambda self, max_chunks=bibliothekar_service_module.DEFAULT_MAX_CHUNKS: object(),
    )

    assert bibliothekar_cli_main(["--instances-dir", str(instances_dir), "--instance", "Depressionsbot", "status"]) == 0
    text_output = capsys.readouterr().out
    assert (
        "Depressionsbot: backend=llamaindex store=llamaindex collection=teebotus_bibliothekar_chunks "
        "target=local_in_memory status=ready documents=1 chunks=1"
    ) in text_output

    assert bibliothekar_cli_main(["--instances-dir", str(instances_dir), "--instance", "Depressionsbot", "--json", "status"]) == 0
    json_output = capsys.readouterr().out
    row = json.loads(json_output)["results"][0]
    assert row["backend"] == "llamaindex"
    assert row["store"] == "llamaindex"
    assert row["target"] == "local_in_memory"
    assert row["status"] == "ready"


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
                "--keyword",
                "python",
                "--relative-path",
                "technik",
                "--extension",
                "txt",
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


def test_bibliothekar_cli_accepts_json_after_status_subcommand(tmp_path, capsys):
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## Bibliothekar\n- backend: local\n", encoding="utf-8")

    assert bibliothekar_cli_main(["--instances-dir", str(instances_dir), "--instance", "Depressionsbot", "status", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["instance"] == "Depressionsbot"
    assert payload["results"][0]["backend"] == "local"


def test_bibliothekar_cli_accepts_json_after_query_subcommand(tmp_path, capsys):
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## Bibliothekar\n- backend: local\n", encoding="utf-8")

    assert (
        bibliothekar_cli_main(
            [
                "--instances-dir",
                str(instances_dir),
                "--instance",
                "Depressionsbot",
                "query",
                "Schlafhygiene",
                "--source",
                "tests/fixtures/books",
                "--top-k",
                "1",
                "--json",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["instance"] == "Depressionsbot"
    assert payload["results"][0]["backend"] == "local"
    assert payload["results"][0]["selected_ids"]


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


def _plan2_chunk_meta(*, chunk_id="chunk", relative_path="quelle.txt", locator="Seite 1"):
    return {
        "chunk_id": chunk_id,
        "document_id": "doc_test",
        "source_id": "sha256:" + "a" * 64,
        "title": "Quelle",
        "author": "",
        "relative_path": relative_path,
        "file_path": relative_path,
        "file_sha256": "a" * 64,
        "file_type": relative_path.rsplit(".", 1)[-1],
        "language": "de",
        "locator": locator,
        "suffix": "." + relative_path.rsplit(".", 1)[-1],
        "page_start": 1,
        "page_end": 1,
        "chapter": "",
        "section": locator,
        "license": "private",
        "ingested_at": "2026-06-15T12:00:00+00:00",
        "chunk_index": 1,
        "embedding_model": "intfloat/multilingual-e5-small",
    }


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


class EmptyFilteredDocumentStore(FakeDocumentStore):
    def __init__(self):
        super().__init__()
        self.filtered_calls = 0
        self.unfiltered_calls = 0
        self.write_attempts = 0

    def write_documents(self, documents, **kwargs):
        self.write_attempts += 1
        super().write_documents(documents, **kwargs)

    def filter_documents(self, **kwargs):
        self.filter_calls.append(kwargs)
        if kwargs.get("filters"):
            self.filtered_calls += 1
            return []
        self.unfiltered_calls += 1
        return list(self.documents)


class NonPersistingDocumentStore(FakeDocumentStore):
    def __init__(self):
        super().__init__()
        self.write_attempts = 0

    def write_documents(self, documents, **_kwargs):
        self.write_attempts += 1
