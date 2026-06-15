from __future__ import annotations

import re

from TeeBotus import __version__
from TeeBotus.instructions import BotInstructions
from TeeBotus.openai_client import OpenAIAPIError, OpenAIResponse
from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, StaticSecretProvider, signal_identity_key, telegram_identity_key
from TeeBotus.runtime.actions import DeleteTrackedMessages, SendTyping
from TeeBotus.runtime.engine import TeeBotusEngine
from TeeBotus.runtime.events import IncomingAttachment, IncomingEvent


def store(tmp_path):
    return AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"e" * 32))


def event(identity_key: str, text: str, *, channel: str = "telegram", attachments: tuple[IncomingAttachment, ...] = ()) -> IncomingEvent:
    return IncomingEvent(
        event_id=f"{channel}:1",
        instance="Depressionsbot",
        channel=channel,  # type: ignore[arg-type]
        adapter_slot=1,
        account_id="",
        identity_key=identity_key,
        chat_id="chat-1",
        chat_type="private",
        sender_id=identity_key,
        sender_name=identity_key,
        text=text,
        message_ref="1",
        attachments=attachments,
    )


def _tokens(text: str) -> list[str]:
    return re.findall(r"\b[0-9a-f]{128}\b", text)


def test_wtf_can_be_confirmed_by_any_existing_identity_after_multi_identity_link(tmp_path):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    first = engine.process_identity_flows(event(telegram_identity_key(1), "/register"))
    account_id, secret = _tokens(first.actions[0].text)
    old_signal = signal_identity_key(source_uuid="old")
    new_signal = signal_identity_key(source_uuid="new")

    engine.process_identity_flows(event(old_signal, f"/login {account_id} {secret}", channel="signal"))
    engine.process_identity_flows(event(new_signal, f"/login {account_id} {secret}", channel="signal"))
    wtf_from_first_telegram = engine.process_identity_flows(event(telegram_identity_key(1), "WTF?"))

    assert "Secret wurde rotiert" in wtf_from_first_telegram.actions[0].text
    assert account_store.get_account_for_identity(new_signal) is None
    assert account_store.get_account_for_identity(old_signal) == account_id


def test_new_identity_cannot_use_wtf_notification_for_itself(tmp_path):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    registered = engine.process_identity_flows(event(telegram_identity_key(1), "/register"))
    account_id, secret = _tokens(registered.actions[0].text)
    new_signal = signal_identity_key(source_uuid="new")

    engine.process_identity_flows(event(new_signal, f"/login {account_id} {secret}", channel="signal"))
    result = engine.process_identity_flows(event(new_signal, "WTF?", channel="signal"))

    assert result.handled is True
    assert "bereits bestehenden Kommunikationsweg" in result.actions[0].text
    assert account_store.get_account_for_identity(new_signal) == account_id


def test_cleanup_requires_exact_command_and_valid_count(tmp_path):
    engine = TeeBotusEngine(account_store=store(tmp_path))

    unknown = engine.process(event(telegram_identity_key(1), "/cleanupfoo"))
    bad = engine.process(event(telegram_identity_key(1), "/cleanup banana"))
    good = engine.process(event(telegram_identity_key(1), "/cleanup 2"))

    assert "Diesen Befehl kenne ich nicht" in unknown[0].text
    assert "Nutzung:" in bad[0].text
    assert isinstance(good[0], DeleteTrackedMessages)
    assert good[0].count == 2


def test_engine_handles_default_builtin_reply_after_identity_flows(tmp_path):
    engine = TeeBotusEngine(account_store=store(tmp_path))

    actions = engine.process(event(telegram_identity_key(1), "/ping"))

    assert len(actions) == 1
    assert actions[0].text == "pong"


def test_engine_uses_configured_builtin_reply_after_identity_flows(tmp_path):
    instructions = BotInstructions(commands={"/custom": "Hallo {first_name}."})
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions)

    actions = engine.process(event(telegram_identity_key(1), "/custom"))

    assert len(actions) == 1
    assert actions[0].text == "Hallo telegram:user:1."


def test_engine_status_uses_core_status_before_configured_commands(tmp_path):
    instructions = BotInstructions(commands={"/status": "Configured status."})
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, project_root=tmp_path)

    actions = engine.process(event(telegram_identity_key(1), "/status"))

    assert len(actions) == 1
    assert "TeeBotus Status" in actions[0].text
    assert f"- Version: {__version__}" in actions[0].text
    assert "Commits: https://github.com/H234598/TeeBotus/commits/main" in actions[0].text
    assert "Configured status." not in actions[0].text


def test_engine_reports_missing_openai_key_for_free_text_when_openai_enabled(tmp_path):
    instructions = BotInstructions(openai_enabled=True, openai_missing_key="Key fehlt.")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions)

    actions = engine.process(event(telegram_identity_key(1), "Hallo"))

    assert len(actions) == 1
    assert actions[0].text == "Key fehlt."


def test_engine_uses_openai_client_for_free_text_when_enabled(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.calls.append((user_text, previous_response_id))
            return OpenAIResponse("Antwort.", "resp-1", "flex")

    client = FakeOpenAIClient()
    instructions = BotInstructions(openai_enabled=True)
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=client)

    actions = engine.process(event(telegram_identity_key(1), "Hallo"))

    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "Antwort."
    assert "Telegram-Kontext:" in client.calls[0][0]
    assert "Nachricht:\nHallo" in client.calls[0][0]
    assert client.calls[0][1] is None


def test_engine_passes_previous_openai_response_id_per_account(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.previous_ids: list[str | None] = []

        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            self.previous_ids.append(previous_response_id)
            return OpenAIResponse("Antwort.", f"resp-{len(self.previous_ids)}", None)

    client = FakeOpenAIClient()
    instructions = BotInstructions(openai_enabled=True)
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=client)
    identity = telegram_identity_key(1)

    engine.process(event(identity, "Hallo"))
    engine.process(event(identity, "Noch mal"))

    assert client.previous_ids == [None, "resp-1"]


def test_engine_reports_openai_error_for_api_failure(tmp_path):
    class FakeOpenAIClient:
        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            raise OpenAIAPIError("boom")

    instructions = BotInstructions(openai_enabled=True, openai_error="OpenAI kaputt.")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=FakeOpenAIClient())

    actions = engine.process(event(telegram_identity_key(1), "Hallo"))

    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "OpenAI kaputt."


def test_engine_transcribes_audio_attachment_for_openai_input(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""
            self.transcriptions: list[tuple[bytes, str]] = []

        def transcribe_audio(self, audio, filename, _instructions, model=None):
            self.transcriptions.append((audio, filename))
            return "Gesprochener Inhalt."

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort auf Audio.", "resp-audio", None)

    client = FakeOpenAIClient()
    instructions = BotInstructions(openai_enabled=True)
    attachment = IncomingAttachment(data=b"audio", filename="voice.ogg", content_type="audio/ogg")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=client)

    actions = engine.process(event(telegram_identity_key(1), "", attachments=(attachment,)))

    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "Antwort auf Audio."
    assert client.transcriptions == [(b"audio", "voice.ogg")]
    assert "- attachments: 1" in client.user_text
    assert "Transkript: Gesprochener Inhalt." in client.user_text
    assert "Nachricht:\n<leer>" in client.user_text


def test_engine_includes_non_audio_attachment_metadata_for_openai_input(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort auf Datei.", "resp-file", None)

    client = FakeOpenAIClient()
    instructions = BotInstructions(openai_enabled=True)
    attachment = IncomingAttachment(data=b"pdf", filename="report.pdf", content_type="application/pdf")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=client)

    actions = engine.process(event(telegram_identity_key(1), "Bitte ansehen", attachments=(attachment,)))

    assert actions[1].text == "Antwort auf Datei."
    assert "filename=report.pdf content_type=application/pdf bytes=3" in client.user_text
    assert "Nachricht:\nBitte ansehen" in client.user_text


def test_engine_reports_missing_openai_key_for_attachment_only_message(tmp_path):
    instructions = BotInstructions(openai_enabled=True, openai_missing_key="Key fehlt.")
    attachment = IncomingAttachment(data=b"audio", filename="voice.ogg", content_type="audio/ogg")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions)

    actions = engine.process(event(telegram_identity_key(1), "", attachments=(attachment,)))

    assert len(actions) == 1
    assert actions[0].text == "Key fehlt."


def test_account_edit_sets_pending_flow(tmp_path):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    result = engine.process_identity_flows(event(identity, "/account_edit"))
    account_id = account_store.get_account_for_identity(identity)

    assert result.handled is True
    assert account_id is not None
    assert engine.state.get_pending_flow("Depressionsbot", account_id, "account_edit") == {"step": "start"}


def test_register_reports_real_store_error_separately_from_existing_secret():
    class Store:
        def register_account(self, account_id):
            raise AccountStoreError("secret backend unavailable")

    text = TeeBotusEngine(account_store=Store())._register_text("a" * 128)  # type: ignore[arg-type]

    assert "Store-/Crypto-Fehlers" in text
    assert "existiert bereits" not in text
