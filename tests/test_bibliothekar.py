from __future__ import annotations

import json
import zipfile

from TeeBotus.instructions import BotInstructions, parse_instructions
from TeeBotus.openai_client import OpenAIResponse
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, telegram_identity_key
from TeeBotus.runtime.actions import SendText
from TeeBotus.runtime.bibliothekar import BibliothekarStore
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
