from __future__ import annotations

import json
import zipfile

from TeeBotus.instructions import BotInstructions, parse_instructions
from TeeBotus.openai_client import OpenAIResponse
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, telegram_identity_key
from TeeBotus.runtime.actions import SendText
from TeeBotus.runtime.bibliothekar import BibliothekarStore
from TeeBotus.bibliothekar.cli import main as bibliothekar_cli_main
from TeeBotus.runtime.bibliothekar_service import BibliothekarService, HaystackBibliothekarBackend, LocalBibliothekarBackend
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

    assert isinstance(local.backend, LocalBibliothekarBackend)
    assert isinstance(haystack.backend, HaystackBibliothekarBackend)
    assert haystack.collection == "therapy_books"


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
