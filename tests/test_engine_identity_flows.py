from __future__ import annotations

import re

import pytest

from TeeBotus import __version__
from TeeBotus.core.status import build_status_reply
from TeeBotus.core.youtube import _has_youtube_transcript_intent
from TeeBotus.instructions import BotInstructions
from TeeBotus.openai_client import OpenAIAPIError, OpenAIResponse
from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, StaticSecretProvider, signal_identity_key, telegram_identity_key
from TeeBotus.runtime.actions import DeleteTrackedMessages, ExportFile, SendAttachment, SendTyping
from TeeBotus.runtime.engine import MEMORY_PAGE_LIMIT_NOTE, TeeBotusEngine, should_ignore_event_without_account
from TeeBotus.runtime.events import IncomingAttachment, IncomingEvent, IncomingLinkPreview
from TeeBotus.runtime.state import RuntimeStateStore
from TeeBotus.runtime.working_memory import WorkingMemoryStore


def store(tmp_path):
    return AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"e" * 32))


def event(
    identity_key: str,
    text: str,
    *,
    channel: str = "telegram",
    attachments: tuple[IncomingAttachment, ...] = (),
    link_previews: tuple[IncomingLinkPreview, ...] = (),
) -> IncomingEvent:
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
        link_previews=link_previews,
    )


def matrix_group_event(text: str, raw: object) -> IncomingEvent:
    return IncomingEvent(
        event_id="matrix:$event",
        instance="Depressionsbot",
        channel="matrix",
        adapter_slot=1,
        account_id="",
        identity_key="matrix:user:@alice:example",
        chat_id="!room:example",
        chat_type="group",
        sender_id="@alice:example",
        sender_name="@alice:example",
        text=text,
        message_ref="$event",
        raw=raw,
    )


def signal_group_event(text: str, raw: object) -> IncomingEvent:
    return IncomingEvent(
        event_id="signal:1",
        instance="Depressionsbot",
        channel="signal",
        adapter_slot=1,
        account_id="",
        identity_key="signal:uuid:alice",
        chat_id="group-1",
        chat_type="group",
        sender_id="alice",
        sender_name="Alice",
        text=text,
        message_ref="1",
        raw=raw,
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


def test_matrix_group_event_with_structured_bot_mention_is_not_ignored() -> None:
    class Raw:
        source = {"content": {"m.mentions": {"user_ids": ["@bot:example"]}}}

    ignored = should_ignore_event_without_account(
        matrix_group_event("Kannst du helfen?", Raw()),
        bot_address_names=("@bot:example", "bot"),
    )

    assert ignored is False


def test_matrix_group_event_with_structured_other_mention_is_ignored() -> None:
    class Raw:
        source = {"content": {"m.mentions": {"user_ids": ["@other:example"]}}}

    ignored = should_ignore_event_without_account(
        matrix_group_event("Kannst du helfen?", Raw()),
        bot_address_names=("@bot:example", "bot"),
    )

    assert ignored is True


def test_signal_group_event_with_dict_bot_mention_is_not_ignored() -> None:
    class Raw:
        mentions = [{"uuid": "bot-uuid", "start": 0, "length": 4}]

    ignored = should_ignore_event_without_account(
        signal_group_event("Hallo", Raw()),
        bot_address_names=("bot-uuid",),
    )

    assert ignored is False


def test_signal_group_event_with_dict_other_mention_is_ignored() -> None:
    class Raw:
        mentions = [{"uuid": "other-uuid", "start": 0, "length": 4}]

    ignored = should_ignore_event_without_account(
        signal_group_event("Hallo", Raw()),
        bot_address_names=("bot-uuid",),
    )

    assert ignored is True


def test_engine_group_event_with_persistent_bot_alias_is_not_ignored(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = matrix_group_event("Mondhase, kannst du helfen?", raw=None).identity_key
    account_id = account_store.resolve_or_create_account(identity)
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_bot_alias", "user_text": "Ich nenne dich ab jetzt Mondhase.", "bot_text": "Okay."},
    )
    engine = TeeBotusEngine(account_store=account_store, bot_address_names=("@bot:example", "bot"))

    ignored = engine.should_ignore_without_account(matrix_group_event("Mondhase, kannst du helfen?", raw=None))

    assert ignored is False


def test_engine_group_event_with_persistent_bot_abbreviation_is_not_ignored(tmp_path) -> None:
    account_store = store(tmp_path)
    incoming = signal_group_event("MH hilf mal kurz", raw=None)
    account_id = account_store.resolve_or_create_account(incoming.identity_key)
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_bot_abbrev", "user_text": "Deine Abkürzung ist MH.", "bot_text": "Okay."},
    )
    engine = TeeBotusEngine(account_store=account_store, bot_address_names=("signal:1",))

    assert engine.should_ignore_without_account(incoming) is False


def test_engine_group_event_with_generated_bot_initials_is_not_ignored(tmp_path) -> None:
    engine = TeeBotusEngine(account_store=store(tmp_path), bot_address_names=("Bote der Wahrheit",))

    ignored = engine.should_ignore_without_account(matrix_group_event("BdW, kannst du helfen?", raw=None))

    assert ignored is False


def test_engine_group_event_with_generated_two_letter_per_word_alias_is_not_ignored(tmp_path) -> None:
    engine = TeeBotusEngine(account_store=store(tmp_path), bot_address_names=("Bote der Wahrheit",))

    ignored = engine.should_ignore_without_account(matrix_group_event("BoDeWa, kannst du helfen?", raw=None))

    assert ignored is False


def test_engine_unknown_group_sender_with_alias_text_is_still_ignored(tmp_path) -> None:
    engine = TeeBotusEngine(account_store=store(tmp_path), bot_address_names=("@bot:example", "bot"))

    ignored = engine.should_ignore_without_account(matrix_group_event("Mondhase, kannst du helfen?", raw=None))

    assert ignored is True


def test_matrix_command_targeting_bot_full_user_id_is_not_ignored() -> None:
    ignored = should_ignore_event_without_account(
        matrix_group_event("/ping@bot:example", raw=None),
        bot_address_names=("@bot:example", "bot"),
    )

    assert ignored is False


def test_matrix_command_targeting_generated_initials_is_not_ignored() -> None:
    ignored = should_ignore_event_without_account(
        matrix_group_event("/ping@BdW", raw=None),
        bot_address_names=("Bote der Wahrheit",),
    )

    assert ignored is False


def test_matrix_command_targeting_other_full_user_id_is_ignored() -> None:
    ignored = should_ignore_event_without_account(
        matrix_group_event("/ping@other:example", raw=None),
        bot_address_names=("@bot:example", "bot"),
    )

    assert ignored is True


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


def test_engine_status_uses_core_status_before_configured_commands(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", "Depressionsbot")
    instructions = BotInstructions(commands={"/status": "Configured status."})
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(telegram_identity_key(1))
    account_store.write_agent_state(
        account_id,
        {
            "schema_version": 1,
            "proactive": {"enabled": True, "paused": False},
            "consent": {"categories": ["reminder"]},
        },
    )
    account_store.append_proactive_outbox_item(account_id, {"status": "queued", "category": "reminder", "message_text": "Ping"})
    account_store.append_proactive_outbox_item(account_id, {"status": "review_pending", "category": "reminder", "message_text": "Review"})
    engine = TeeBotusEngine(account_store=account_store, instructions=instructions, project_root=tmp_path)

    actions = engine.process(event(telegram_identity_key(1), "/status"))

    assert len(actions) == 1
    assert "Depressionsbot Status:" in actions[0].text
    assert f"- Version: {__version__} Wirt Commits https://github.com/H234598/TeeBotus/commits/main" in actions[0].text
    assert "Commits:" not in actions[0].text
    assert "Proactive Agent" in actions[0].text
    assert "- Agent enabled: ja" in actions[0].text
    assert "- Outbox queued: 1" in actions[0].text
    assert "- Review pending: 1" in actions[0].text
    assert "- Scheduler enabled: ja" in actions[0].text
    assert "- Model planner: tool" in actions[0].text
    assert "Configured status." not in actions[0].text


def test_engine_info_alias_uses_core_status_before_configured_commands(tmp_path):
    instructions = BotInstructions(commands={"/info": "Configured info."})
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, project_root=tmp_path)

    actions = engine.process(event(telegram_identity_key(1), "/info"))

    assert len(actions) == 1
    assert "Depressionsbot Status:" in actions[0].text
    assert "Configured info." not in actions[0].text


def test_engine_status_reports_unmapped_account_instead_of_zero_memory(tmp_path):
    account_store = store(tmp_path)
    existing_account_id = "a" * 128
    account_dir = account_store.account_dir(existing_account_id)
    account_dir.mkdir(parents=True, exist_ok=True)
    (account_dir / "User_Memory_Index.json").write_text('{"entries": ["mem_1"]}\n', encoding="utf-8")

    text = build_status_reply(
        sender_id="1",
        instance_name="Depressionsbot",
        project_root=tmp_path,
        account_store=account_store,
    )

    assert "- Nutzermemory: Account nicht zugeordnet" in text
    assert "- Nutzermemory: 0 B" not in text


def test_status_uses_account_memory_backend_payload_size(tmp_path):
    class Backend:
        def read_entries(self, _account_id):
            return [{"id": "mem_db", "user_text": "Mond aus der Datenbank"}]

        def read_index(self, _account_id):
            return {"index": {"entries": {"mem_db": {"kind": "observation"}}}}

        def write_entries(self, _account_id, _rows):
            return None

        def write_index(self, _account_id, _data):
            return None

    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(telegram_identity_key(1))
    account_store._account_memory_backend = Backend()
    text = build_status_reply(
        account_id=account_id,
        instance_name="Depressionsbot",
        project_root=tmp_path,
        account_store=account_store,
    )

    assert "- Nutzermemory: 0 B" not in text
    assert "- Nutzermemory:" in text
    assert "- Userfiles: Datenbank-Backend, Payloads verschluesselt" in text


def test_engine_proactive_command_requires_instance_enablement(tmp_path, monkeypatch):
    monkeypatch.delenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", raising=False)
    monkeypatch.delenv("TEEBOTUS_PROACTIVE_AGENT_DEPRESSIONSBOT", raising=False)
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)

    actions = engine.process(event(telegram_identity_key(1), "/proactive on"))

    account_id = account_store.get_account_for_identity(telegram_identity_key(1))
    assert account_id is not None
    assert "nicht freigeschaltet" in actions[0].text
    assert account_store.read_agent_state(account_id) == {}


def test_engine_proactive_command_enables_private_account_agent_when_instance_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", "Depressionsbot")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)

    actions = engine.process(event(telegram_identity_key(1), "/proactive on"))

    account_id = account_store.get_account_for_identity(telegram_identity_key(1))
    assert account_id is not None
    assert "aktiviert" in actions[0].text
    assert account_store.read_agent_state(account_id)["proactive"]["enabled"] is True


def test_engine_proactive_policy_commands_update_account_state(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", "Depressionsbot")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)

    engine.process(event(telegram_identity_key(1), "/proactive on"))
    category_reply = engine.process(event(telegram_identity_key(1), "/proactive category on analysis"))[0].text
    quiet_reply = engine.process(event(telegram_identity_key(1), "/proactive quiet 22 8"))[0].text
    interval_reply = engine.process(event(telegram_identity_key(1), "/proactive interval 180"))[0].text
    pause_reply = engine.process(event(telegram_identity_key(1), "/proactive pause"))[0].text
    status_reply = engine.process(event(telegram_identity_key(1), "/proactive status"))[0].text

    account_id = account_store.get_account_for_identity(telegram_identity_key(1))
    assert account_id is not None
    state = account_store.read_agent_state(account_id)
    assert "analysis" in state["consent"]["categories"]
    assert state["policy"]["allowed_hours"] == [8, 22]
    assert state["policy"]["min_minutes_between_messages"] == 180
    assert state["proactive"]["paused"] is True
    assert "Kategorien aktualisiert" in category_reply
    assert "Erlaubtes Zeitfenster: 8-22 Uhr" in quiet_reply
    assert "180 Minuten" in interval_reply
    assert "pausiert" in pause_reply
    assert "- pausiert: ja" in status_reply
    assert "- review_pending_items: 0" in status_reply


def test_engine_proactive_command_is_private_only(tmp_path):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    group = event(telegram_identity_key(1), "/proactive on")
    group = IncomingEvent(
        event_id=group.event_id,
        instance=group.instance,
        channel=group.channel,
        adapter_slot=group.adapter_slot,
        account_id=group.account_id,
        identity_key=group.identity_key,
        chat_id="group-1",
        chat_type="group",
        sender_id=group.sender_id,
        sender_name=group.sender_name,
        text=group.text,
        message_ref=group.message_ref,
    )

    actions = engine.process(group)

    account_id = account_store.get_account_for_identity(telegram_identity_key(1))
    assert account_id is not None
    assert actions[0].text == "Bitte privat."
    assert account_store.read_agent_state(account_id) == {}


def test_engine_natural_reminder_queues_private_proactive_message(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", "Depressionsbot")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="chat-1", chat_type="private", adapter_slot=1)

    actions = engine.process(event(identity, "Erinnere mich morgen um 9 an den Termin"))

    assert "Okay, ich erinnere dich" in actions[0].text
    state = account_store.read_agent_state(account_id)
    assert state["proactive"]["enabled"] is True
    assert state["consent"]["categories"] == ["reminder"]
    rows = account_store.read_proactive_outbox(account_id)
    assert len(rows) == 1
    assert rows[0]["category"] == "reminder"
    assert rows[0]["intent"] == "user_requested_reminder"
    assert rows[0]["message_text"] == "Du wolltest erinnert werden: den Termin"
    assert rows[0]["route"]["channel"] == "telegram"
    assert rows[0]["route"]["chat_id"] == "chat-1"


def test_engine_natural_reminder_requires_instance_enablement(tmp_path, monkeypatch):
    monkeypatch.delenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", raising=False)
    monkeypatch.delenv("TEEBOTUS_PROACTIVE_AGENT_DEPRESSIONSBOT", raising=False)
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    actions = engine.process(event(identity, "Erinnere mich morgen um 9 an den Termin"))

    account_id = account_store.get_account_for_identity(identity)
    assert account_id is not None
    assert "nicht freigeschaltet" in actions[0].text
    assert account_store.read_agent_state(account_id) == {}
    assert account_store.read_proactive_outbox(account_id) == []


def test_engine_natural_reminder_requires_private_route(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", "Depressionsbot")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="group-1", chat_type="group", adapter_slot=1)

    actions = engine.process(event(identity, "Erinnere mich morgen um 9 an den Termin"))

    assert "privaten Chat" in actions[0].text
    assert account_store.read_proactive_outbox(account_id) == []


def test_engine_export_account_data_as_json(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="export")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.write_memory_entries(account_id, [{"id": "mem_export", "user_text": "Exportiere mich."}])
    engine = TeeBotusEngine(account_store=account_store)

    actions = engine.process(event(identity, "/export", channel="signal"))

    assert len(actions) == 1
    assert isinstance(actions[0], ExportFile)
    assert actions[0].filename.startswith("TeeBotus_account_")
    assert actions[0].filename.endswith(".json")
    assert actions[0].content_type == "application/json"
    assert b"Exportiere mich." in actions[0].data
    assert b"TMBMAP1" not in actions[0].data


def test_engine_export_account_data_respects_format_argument(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="export-md")
    account_store.resolve_or_create_account(identity)
    engine = TeeBotusEngine(account_store=account_store)

    actions = engine.process(event(identity, "/account_export md", channel="matrix"))

    assert isinstance(actions[0], ExportFile)
    assert actions[0].filename.endswith(".md")
    assert actions[0].content_type == "text/markdown"


def test_engine_export_account_data_requires_private_chat(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="export-group")
    engine = TeeBotusEngine(account_store=account_store)
    incoming = IncomingEvent(
        event_id="signal:1",
        instance="Depressionsbot",
        channel="signal",
        adapter_slot=1,
        identity_key=identity,
        chat_id="group-chat",
        chat_type="group",
        sender_id=identity,
        sender_name=identity,
        text="/export",
        message_ref="1",
    )

    actions = engine.process(incoming)

    assert actions[0].text == "Bitte privat."


def test_engine_export_account_data_rejects_unknown_format(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="export-bad")
    engine = TeeBotusEngine(account_store=account_store)

    actions = engine.process(event(identity, "/export exe", channel="signal"))

    assert "Nutzung:" in actions[0].text


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


def test_engine_prefers_llm_client_for_free_text_when_configured(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.calls = 0

        def create_reply(self, *_args, **_kwargs):
            self.calls += 1
            return OpenAIResponse("OpenAI.", "resp-openai", "flex")

    class FakeLLMClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.calls.append(user_text)
            return OpenAIResponse("LiteLLM.", None, None)

    openai_client = FakeOpenAIClient()
    llm_client = FakeLLMClient()
    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(openai_enabled=True),
        openai_client=openai_client,
        llm_client=llm_client,
    )

    actions = engine.process(event(telegram_identity_key(1), "Hallo"))

    assert actions[1].text == "LiteLLM."
    assert llm_client.calls
    assert openai_client.calls == 0


def test_engine_turns_openai_file_block_into_attachment(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse(
                'Hier ist die Kalenderdatei.\n[[TEE_FILE filename="termin.ics" content_type="text/calendar" caption="Termin"]]\nBEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n[[/TEE_FILE]]',
                "resp-file",
                None,
            )

    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(openai_enabled=True),
        openai_client=client,
    )

    actions = engine.process(event(telegram_identity_key(1), "Mach mir bitte eine ICS Datei fuer morgen."))

    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "Hier ist die Kalenderdatei."
    assert isinstance(actions[2], SendAttachment)
    assert actions[2].filename == "termin.ics"
    assert actions[2].content_type == "text/calendar"
    assert actions[2].data.startswith(b"BEGIN:VCALENDAR")
    assert "Dateiausgabe:" in client.user_text


def test_engine_turns_openai_image_block_into_generated_attachment(tmp_path):
    class FakeImage:
        data = b"png-bytes"
        filename = "wetter.png"
        content_type = "image/png"

    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.prompt = ""

        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse(
                'Das Wetter ist grau, hier ist ein kleines Bild dazu.\n'
                '[[TEE_IMAGE filename="wetter.png" caption="Ein ruhiger Wetterimpuls" purpose="weather_encouragement"]]\n'
                "Ein warmes, freundliches Bild: Regen am Fenster, Tee, weiches Morgenlicht.\n"
                "[[/TEE_IMAGE]]",
                "resp-image",
                None,
            )

        def generate_image(self, prompt, _instructions, *, filename="bild.png"):
            self.prompt = prompt
            return FakeImage()

    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(openai_enabled=True, openai_image_enabled=True),
        openai_client=client,
    )

    actions = engine.process(event(telegram_identity_key(1), "Wie ist die Stimmung bei Regen?"))

    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "Das Wetter ist grau, hier ist ein kleines Bild dazu."
    assert isinstance(actions[2], SendAttachment)
    assert actions[2].filename == "wetter.png"
    assert actions[2].content_type == "image/png"
    assert actions[2].data == b"png-bytes"
    assert actions[2].caption == "Ein ruhiger Wetterimpuls"
    assert "Regen am Fenster" in client.prompt


def test_engine_rate_limits_repeated_openai_image_generation(tmp_path):
    class FakeImage:
        data = b"png-bytes"
        filename = "bild.png"
        content_type = "image/png"

    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.generate_calls = 0

        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse(
                'Kurz dazu.\n[[TEE_IMAGE filename="bild.png" caption="Bild"]]\nEin freundliches Bild.\n[[/TEE_IMAGE]]',
                f"resp-{self.generate_calls}",
                None,
            )

        def generate_image(self, _prompt, _instructions, *, filename="bild.png"):
            self.generate_calls += 1
            return FakeImage()

    client = FakeOpenAIClient()
    instructions = BotInstructions(
        openai_enabled=True,
        openai_image_enabled=True,
        openai_image_min_interval_minutes=30,
        openai_image_rate_limited="Heute keine weiteren Bilder.",
    )
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=client)
    identity = telegram_identity_key(1)

    first_actions = engine.process(event(identity, "Mach ein Wetterbild."))
    second_actions = engine.process(event(identity, "Noch ein Bild bitte."))

    assert client.generate_calls == 1
    assert isinstance(first_actions[2], SendAttachment)
    assert len(second_actions) == 2
    assert second_actions[1].text == "Kurz dazu.\nHeute keine weiteren Bilder."


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


def test_engine_restores_previous_openai_response_id_from_persistent_state(tmp_path):
    class FakeOpenAIClient:
        def __init__(self, response_id: str) -> None:
            self.response_id = response_id
            self.previous_ids: list[str | None] = []

        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            self.previous_ids.append(previous_response_id)
            return OpenAIResponse("Antwort.", self.response_id, None)

    provider = StaticSecretProvider(b"e" * 32)
    data_dir = tmp_path / "Depressionsbot" / "data"
    account_store = AccountStore(data_dir / "accounts", "Depressionsbot", provider)
    instructions = BotInstructions(openai_enabled=True)
    identity = telegram_identity_key(1)
    first_client = FakeOpenAIClient("resp-1")
    first_engine = TeeBotusEngine(
        account_store=account_store,
        state=RuntimeStateStore(data_dir, instance_name="Depressionsbot", secret_provider=provider),
        instructions=instructions,
        openai_client=first_client,
    )

    first_engine.process(event(identity, "Hallo"))
    second_client = FakeOpenAIClient("resp-2")
    second_engine = TeeBotusEngine(
        account_store=AccountStore(data_dir / "accounts", "Depressionsbot", provider),
        state=RuntimeStateStore(data_dir, instance_name="Depressionsbot", secret_provider=provider),
        instructions=instructions,
        openai_client=second_client,
    )
    second_engine.process(event(identity, "Noch mal"))

    assert first_client.previous_ids == [None]
    assert second_client.previous_ids == ["resp-1"]


def test_engine_reset_clears_previous_openai_response_id(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.previous_ids: list[str | None] = []

        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            self.previous_ids.append(previous_response_id)
            return OpenAIResponse("Antwort.", "resp-1", None)

    client = FakeOpenAIClient()
    instructions = BotInstructions(openai_enabled=True, openai_reset="Kontext geloescht.")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=client)
    identity = telegram_identity_key(1)

    engine.process(event(identity, "Hallo"))
    reset_actions = engine.process(event(identity, "/reset"))
    engine.process(event(identity, "Neu"))

    assert reset_actions[0].text == "Kontext geloescht."
    assert client.previous_ids == [None, None]


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
            return "Aehm also ich weiss nicht, ich bin nervoes und rede sehr schnell."

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort auf Audio.", "resp-audio", None)

    client = FakeOpenAIClient()
    instructions = BotInstructions(openai_enabled=True)
    attachment = IncomingAttachment(data=b"audio", filename="voice.ogg", content_type="audio/ogg")
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    engine = TeeBotusEngine(account_store=account_store, instructions=instructions, openai_client=client)

    actions = engine.process(event(identity, "", attachments=(attachment,)))
    account_id = account_store.get_account_for_identity(identity)
    state = account_store.read_agent_state(account_id or "")

    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "Antwort auf Audio."
    assert client.transcriptions == [(b"audio", "voice.ogg")]
    assert "- attachments: 1" in client.user_text
    assert "Transkript: Aehm also ich weiss nicht" in client.user_text
    assert "Nachricht:\n<leer>" in client.user_text
    assert "tts_mimic_voice" in state
    assert "wirkt sprachlich leicht unsicher oder aengstlich" in str(state)
    assert "ich weiss nicht" not in str(state)


def test_engine_can_transcribe_audio_attachment_with_local_backend(tmp_path, monkeypatch):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""
            self.transcriptions: list[tuple[bytes, str]] = []

        def transcribe_audio(self, audio, filename, _instructions, model=None):
            self.transcriptions.append((audio, filename))
            return "Soll nicht genutzt werden."

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort auf lokales Audio.", "resp-audio", None)

    local_calls: list[tuple[bytes, str, str]] = []

    def fake_local_transcribe(audio, filename, *, model, language, instance_name=""):
        local_calls.append((audio, filename, model))
        return "Lokales Whisper Transkript."

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_local_audio", fake_local_transcribe)
    client = FakeOpenAIClient()
    instructions = BotInstructions(openai_enabled=True, openai_transcription_backend="local", local_transcription_model="tiny")
    attachment = IncomingAttachment(data=b"audio", filename="voice.ogg", content_type="audio/ogg")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=client)

    actions = engine.process(event(telegram_identity_key(1), "", attachments=(attachment,)))

    assert actions[1].text == "Antwort auf lokales Audio."
    assert local_calls == [(b"audio", "voice.ogg", "tiny")]
    assert client.transcriptions == []
    assert "Transkript: Lokales Whisper Transkript." in client.user_text


def test_engine_respects_disabled_transcription_for_audio_attachment(tmp_path, monkeypatch):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""
            self.transcriptions: list[tuple[bytes, str]] = []

        def transcribe_audio(self, audio, filename, _instructions, model=None):
            self.transcriptions.append((audio, filename))
            return "Soll nicht genutzt werden."

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort ohne Transkript.", "resp-audio-disabled", None)

    def fake_local_transcribe(*_args, **_kwargs):
        raise AssertionError("local transcription must not run when transcription is disabled")

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_local_audio", fake_local_transcribe)
    client = FakeOpenAIClient()
    instructions = BotInstructions(
        openai_enabled=True,
        openai_transcription_enabled=False,
        openai_transcription_backend="local",
    )
    attachment = IncomingAttachment(data=b"audio", filename="voice.ogg", content_type="audio/ogg")
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    engine = TeeBotusEngine(account_store=account_store, instructions=instructions, openai_client=client)

    actions = engine.process(event(identity, "", attachments=(attachment,)))
    account_id = account_store.get_account_for_identity(identity)
    state = account_store.read_agent_state(account_id or "")

    assert actions[1].text == "Antwort ohne Transkript."
    assert client.transcriptions == []
    assert "Transkript: <Transkription deaktiviert>" in client.user_text
    assert "tts_mimic_voice" not in state


def test_engine_does_not_transcribe_view_once_audio_attachment(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""
            self.transcriptions: list[tuple[bytes, str]] = []

        def transcribe_audio(self, audio, filename, _instructions, model=None):
            self.transcriptions.append((audio, filename))
            return "Soll nicht passieren."

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort ohne View-once-Transkript.", "resp-view-once", None)

    client = FakeOpenAIClient()
    instructions = BotInstructions(openai_enabled=True)
    attachment = IncomingAttachment(data=b"audio", filename="voice.ogg", content_type="audio/ogg", view_once=True)
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=client)

    actions = engine.process(event(telegram_identity_key(1), "", attachments=(attachment,)))

    assert actions[1].text == "Antwort ohne View-once-Transkript."
    assert client.transcriptions == []
    assert "filename=voice.ogg content_type=audio/ogg bytes=5 view_once=true" in client.user_text
    assert "Transkript: <view-once nicht verarbeitet>" in client.user_text
    assert "Soll nicht passieren" not in client.user_text


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


def test_engine_includes_link_preview_metadata_for_openai_input(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort auf Link.", "resp-link", None)

    client = FakeOpenAIClient()
    instructions = BotInstructions(openai_enabled=True)
    preview = IncomingLinkPreview(
        title="TeeBotus",
        url="https://example.test/tee",
        description="Botlink",
        base64_thumbnail="aW1hZ2U=",
        id="preview-thumb",
    )
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=client)

    actions = engine.process(event(telegram_identity_key(1), "Sieh mal", link_previews=(preview,)))

    assert actions[1].text == "Antwort auf Link."
    assert "- link_previews: 1" in client.user_text
    assert "Linkpreviews:" in client.user_text
    assert "title=TeeBotus" in client.user_text
    assert "url=https://example.test/tee" in client.user_text
    assert "thumbnail=yes" in client.user_text
    assert "Nachricht:\nSieh mal" in client.user_text


def test_engine_includes_reply_context_in_openai_input(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort.", "resp-reply", None)

    client = FakeOpenAIClient()
    instructions = BotInstructions(openai_enabled=True)
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=client)
    incoming = event(telegram_identity_key(1), "Darauf antworte ich")
    incoming = IncomingEvent(
        event_id=incoming.event_id,
        instance=incoming.instance,
        channel=incoming.channel,
        adapter_slot=incoming.adapter_slot,
        account_id=incoming.account_id,
        identity_key=incoming.identity_key,
        chat_id=incoming.chat_id,
        chat_type=incoming.chat_type,
        sender_id=incoming.sender_id,
        sender_name=incoming.sender_name,
        sender_username=incoming.sender_username,
        sender_number=incoming.sender_number,
        text=incoming.text,
        message_ref=incoming.message_ref,
        reply_to_text="Vorherige Nachricht",
    )

    engine.process(incoming)

    assert "- reply_to_text: Vorherige Nachricht" in client.user_text


def test_engine_includes_account_memory_in_openai_input(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort.", "resp-memory", None)

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="mem")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.write_memory_entries(
        account_id,
        [
            {
                "id": "mem_old",
                "created_at": "2026-01-01T00:00:00+00:00",
                "channel": "signal",
                "keywords": ["mond"],
                "user_text": "Mein Lieblingswort ist Mond.",
                "bot_text": "Gemerkt.",
            }
        ],
    )
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True),
        openai_client=client,
    )

    engine.process(event(identity, "Was weisst du noch?", channel="signal"))

    assert "Persistentes Account-Memory:" in client.user_text
    assert '"selected_memory_ids": [' in client.user_text
    assert '"mem_old"' in client.user_text
    assert "Mein Lieblingswort ist Mond." in client.user_text


def test_engine_includes_account_habits_in_openai_input_without_filename(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort.", "resp-habits", None)

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="habits")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.write_account_text(account_id, "User_Habbits_and_behave.md", "Ada mag knappe Antworten.")
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True),
        openai_client=client,
    )

    engine.process(event(identity, "Wie sollst du antworten?", channel="signal"))

    assert "Persistentes Account-Memory:" in client.user_text
    assert "Interne, admingepflegte Zusatzhinweise fuer diesen Account:" in client.user_text
    assert "Ada mag knappe Antworten." in client.user_text
    assert "User_Habbits_and_behave" not in client.user_text


def test_engine_prefers_keyword_matched_account_memory_over_recent(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort.", "resp-memory", None)

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="memory-ranking")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.write_memory_entries(
        account_id,
        [
            {
                "id": "mem_moon",
                "created_at": "2026-01-01T00:00:00+00:00",
                "channel": "signal",
                "keywords": ["mond"],
                "user_text": "Mein Lieblingswort ist Mond.",
                "bot_text": "Gemerkt.",
            },
            {
                "id": "mem_tea",
                "created_at": "2026-01-02T00:00:00+00:00",
                "channel": "matrix",
                "keywords": ["tee"],
                "user_text": "Ich trinke gerne Tee.",
                "bot_text": "Gemerkt.",
            },
        ],
    )
    account_store.write_memory_index(
        account_id,
        {
            "keywords": {"mond": ["mem_moon"], "tee": ["mem_tea"]},
            "recent_ids": ["mem_moon", "mem_tea"],
        },
    )
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True),
        openai_client=client,
    )

    engine.process(event(identity, "Was weisst du ueber Mond?", channel="signal"))

    assert '"id": "mem_moon"' in client.user_text
    assert '"id": "mem_tea"' in client.user_text
    assert client.user_text.index('"id": "mem_moon"') < client.user_text.index('"id": "mem_tea"')
    assert '"selected_memory_ids": [\n    "mem_moon",\n    "mem_tea"\n  ]' in client.user_text


def test_engine_pages_account_memory_when_model_requests_it(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.calls.append((user_text, previous_response_id))
            if len(self.calls) == 1:
                return OpenAIResponse('[[TEE_MEMORY_PAGE query="kaffee" exclude="mem_moon"]]', "resp-page-request", None)
            return OpenAIResponse("Kaffee ist nachgeladen.", "resp-final", None)

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="memory-paging")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_moon", "keywords": ["mond"], "user_text": "Mein Lieblingswort ist Mond.", "bot_text": "Gemerkt."},
    )
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_coffee", "keywords": ["kaffee"], "user_text": "Kaffee beruhigt beim Sortieren.", "bot_text": "Gemerkt."},
    )
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True, user_memory_max_prompt_chars=1200),
        openai_client=client,
    )

    actions = engine.process(event(identity, "Was weisst du ueber Mond?", channel="signal"))

    assert len(client.calls) == 2
    assert "Persistentes Account-Memory:" in client.calls[0][0]
    assert '[[TEE_MEMORY_PAGE query="kurze Suchphrase" exclude="id1,id2"]]' in client.calls[0][0]
    assert client.calls[1][1] == "resp-page-request"
    assert "Aktive Account-Memory-Page:" in client.calls[1][0]
    assert '"id": "mem_coffee"' in client.calls[1][0]
    assert '"id": "mem_moon"' not in client.calls[1][0]
    assert actions[-1].text == "Kaffee ist nachgeladen."


def test_engine_does_not_leak_repeated_memory_page_request(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.calls = 0

        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            self.calls += 1
            if self.calls == 1:
                return OpenAIResponse('[[TEE_MEMORY_PAGE query="kaffee" exclude="mem_moon"]]', "resp-page-request", None)
            return OpenAIResponse('[[TEE_MEMORY_PAGE query="noch mehr" exclude="mem_coffee"]]', "resp-repeated-page", None)

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="memory-paging-repeat")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.append_structured_memory_entry(account_id, {"id": "mem_moon", "keywords": ["mond"], "user_text": "Mond", "bot_text": "Gemerkt."})
    account_store.append_structured_memory_entry(account_id, {"id": "mem_coffee", "keywords": ["kaffee"], "user_text": "Kaffee", "bot_text": "Gemerkt."})
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True, user_memory_max_prompt_chars=1200),
        openai_client=FakeOpenAIClient(),
    )

    actions = engine.process(event(identity, "Was weisst du ueber Mond?", channel="signal"))

    assert actions[-1].text == MEMORY_PAGE_LIMIT_NOTE
    assert "TEE_MEMORY_PAGE" not in actions[-1].text


def test_engine_does_not_leak_unexpected_memory_page_request(tmp_path):
    class FakeOpenAIClient:
        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse('[[TEE_MEMORY_PAGE query="kaffee" exclude="mem_moon"]]', "resp-unexpected-page", None)

    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=False),
        openai_client=FakeOpenAIClient(),
    )

    actions = engine.process(event(signal_identity_key(source_uuid="unexpected-page"), "Hallo", channel="signal"))

    assert actions[-1].text == MEMORY_PAGE_LIMIT_NOTE
    assert "TEE_MEMORY_PAGE" not in actions[-1].text


def test_engine_includes_working_memory_in_openai_input_without_auto_writes(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort.", "resp-working-memory", None)

    instances_dir = tmp_path / "instances"
    working_store = WorkingMemoryStore("Depressionsbot", instances_dir)
    working_store.append_manual("Allgemeine Instanzregel: bei Architekturfragen erst kurz strukturieren.")
    entries_path = instances_dir / "Depressionsbot" / "data" / "Working_Memorys.entries.jsonl"
    before = entries_path.read_text(encoding="utf-8")
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(openai_enabled=True),
        openai_client=client,
        working_memory_store=working_store,
    )

    engine.process(event(signal_identity_key(source_uuid="working-memory"), "Bitte eine Architekturfrage strukturieren.", channel="signal"))

    assert "Instanz-Arbeitsgedaechtnis:" in client.user_text
    assert "Allgemeine Instanzregel" in client.user_text
    assert "Persistentes Account-Memory:" not in client.user_text
    assert entries_path.read_text(encoding="utf-8") == before


def test_engine_appends_account_memory_after_openai_reply(tmp_path):
    class FakeOpenAIClient:
        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse("Antwort mit Mond.", "resp-memory", None)

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="write-memory")
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True),
        openai_client=FakeOpenAIClient(),
    )

    engine.process(event(identity, "Merke Mond.", channel="signal"))
    account_id = account_store.get_account_for_identity(identity)

    assert account_id is not None
    entries = account_store.read_memory_entries(account_id)
    assert entries[-1]["channel"] == "signal"
    assert entries[-1]["user_text"] == "Merke Mond."
    assert entries[-1]["bot_text"] == "Antwort mit Mond."
    index = account_store.read_memory_index(account_id)
    assert entries[-1]["id"] in index["index"]["recent_ids"]
    assert "mond" in index["index"]["keywords"]


def test_engine_does_not_write_account_memory_when_disabled(tmp_path):
    class FakeOpenAIClient:
        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse("Antwort.", "resp-memory", None)

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="no-memory")
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=False),
        openai_client=FakeOpenAIClient(),
    )

    engine.process(event(identity, "Nicht speichern.", channel="signal"))
    account_id = account_store.get_account_for_identity(identity)

    assert account_id is not None
    assert account_store.read_memory_entries(account_id) == []


def test_engine_account_memory_reset_requires_confirmation_and_resets_structured_memory(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="reset-memory")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.write_memory_index(account_id, {"keywords": {"mond": ["mem_old"]}})
    account_store.write_memory_entries(account_id, [{"id": "mem_old", "user_text": "Mond"}])
    account_store.write_account_text(account_id, "User_Habbits_and_behave.md", "Adminhinweis bleibt.")
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(user_memory_enabled=True))

    confirm_actions = engine.process(event(identity, "/reset_memorys", channel="signal"))
    done_actions = engine.process(event(identity, "ja", channel="signal"))

    assert confirm_actions[0].text == BotInstructions().user_memory_reset_confirm
    assert done_actions[0].text == BotInstructions().user_memory_reset_success
    assert account_store.read_memory_index(account_id) == {}
    assert account_store.read_memory_entries(account_id) == []
    assert account_store.read_account_text(account_id, "User_Habbits_and_behave.md") == "Adminhinweis bleibt."


def test_engine_privacy_confirmation_is_persistent_until_memory_reset(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="privacy")
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(user_memory_enabled=True))

    confirmed = engine.process(event(identity, "Datenschutz bestätigt", channel="signal"))
    account_id = account_store.get_account_for_identity(identity)

    assert account_id is not None
    assert confirmed[0].text.startswith("Datenschutz ist bestätigt.")
    assert account_store.has_privacy_confirmation(account_id) is True

    engine.process(event(identity, "/reset_memorys", channel="signal"))
    reset_done = engine.process(event(identity, "ja", channel="signal"))

    assert reset_done[0].text == BotInstructions().user_memory_reset_success
    assert account_store.has_privacy_confirmation(account_id) is False


def test_engine_account_memory_reset_can_be_cancelled(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="cancel-memory")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.write_memory_entries(account_id, [{"id": "mem_old", "user_text": "Mond"}])
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(user_memory_enabled=True))

    engine.process(event(identity, "/reset_memorys", channel="signal"))
    actions = engine.process(event(identity, "nein", channel="signal"))

    assert actions[0].text == BotInstructions().user_memory_reset_cancelled
    assert account_store.read_memory_entries(account_id) == [{"id": "mem_old", "user_text": "Mond"}]


def test_engine_account_memory_reset_reports_unavailable_when_disabled(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="disabled-memory")
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(user_memory_enabled=False))

    actions = engine.process(event(identity, "/reset_memorys", channel="signal"))

    assert actions[0].text == BotInstructions().user_memory_reset_unavailable
    account_id = account_store.get_account_for_identity(identity)
    assert account_id is not None
    assert engine.state.get_pending_flow("Depressionsbot", account_id, "memory_reset") is None


def test_engine_account_memory_reset_confirmation_is_scoped_to_chat(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="scoped-memory")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.write_memory_entries(account_id, [{"id": "mem_old", "user_text": "Mond"}])
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(user_memory_enabled=True))
    first_chat = event(identity, "/reset_memorys", channel="signal")
    other_chat = IncomingEvent(
        event_id="signal:2",
        instance="Depressionsbot",
        channel="signal",
        adapter_slot=1,
        identity_key=identity,
        chat_id="other-chat",
        chat_type="private",
        sender_id=identity,
        sender_name=identity,
        text="ja",
        message_ref="2",
    )

    engine.process(first_chat)
    actions = engine.process(other_chat)

    assert actions == []
    assert account_store.read_memory_entries(account_id) == [{"id": "mem_old", "user_text": "Mond"}]


def test_engine_account_memory_reset_refuses_global_targets(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="global-memory")
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(user_memory_enabled=True))

    actions = engine.process(event(identity, "loesche alle user memorys", channel="signal"))

    assert actions[0].text == BotInstructions().user_memory_reset_only_own


def test_engine_reports_missing_openai_key_for_attachment_only_message(tmp_path):
    instructions = BotInstructions(openai_enabled=True, openai_missing_key="Key fehlt.")
    attachment = IncomingAttachment(data=b"audio", filename="voice.ogg", content_type="audio/ogg")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions)

    actions = engine.process(event(telegram_identity_key(1), "", attachments=(attachment,)))

    assert len(actions) == 1
    assert actions[0].text == "Key fehlt."


def test_engine_voice_command_sends_generated_attachment(tmp_path):
    class FakeVoice:
        audio = b"voice-bytes"
        filename = "voice.opus"
        content_type = "audio/ogg"

    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.voice_texts: list[str] = []

        def create_voice(self, text, _instructions):
            self.voice_texts.append(text)
            return FakeVoice()

    client = FakeOpenAIClient()
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions(), openai_client=client)

    actions = engine.process(event(telegram_identity_key(1), "/voice Hallo Welt", channel="signal"))

    assert client.voice_texts == ["Hallo Welt"]
    assert isinstance(actions[0], SendTyping)
    assert isinstance(actions[1], SendAttachment)
    assert actions[1].data == b"voice-bytes"
    assert actions[1].filename == "voice.opus"
    assert actions[1].content_type == "audio/ogg"


def test_engine_voice_command_uses_account_tts_dialect(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.voice_instructions: list[str] = []

        def create_voice(self, _text, instructions):
            self.voice_instructions.append(instructions.openai_voice_instructions)
            return type("Voice", (), {"audio": b"voice", "filename": "voice.ogg", "content_type": "audio/ogg"})()

    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_voice_instructions="Basisstimme."),
        openai_client=FakeOpenAIClient(),
    )

    engine.process(event(identity, "Ich bin in Nürnberg geboren.", channel="signal"))
    engine.process(event(identity, "/voice Hallo", channel="signal"))

    client = engine.openai_client
    assert client is not None
    assert "Basisstimme." in client.voice_instructions[0]
    assert "Nürnberg" in client.voice_instructions[0]


def test_engine_voice_model_command_persists_openai_voice_alias(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.voice_names: list[str] = []

        def create_voice(self, _text, instructions):
            self.voice_names.append(instructions.openai_voice)
            return type("Voice", (), {"audio": b"voice", "filename": "voice.ogg", "content_type": "audio/ogg"})()

    account_store = store(tmp_path)
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(), openai_client=client)
    identity = signal_identity_key(source_uuid="voice-model")

    set_actions = engine.process(event(identity, "/voicemodel onys", channel="signal"))
    voice_actions = engine.process(event(identity, "/voice Hallo", channel="signal"))

    assert "OpenAI-Stimme onyx" in set_actions[0].text
    assert "https://platform.openai.com/docs/guides/text-to-speech#voice-options" in set_actions[0].text
    assert client.voice_names == ["onyx"]
    assert isinstance(voice_actions[1], SendAttachment)


def test_engine_voice_model_command_lists_openai_voices(tmp_path):
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions())

    actions = engine.process(event(telegram_identity_key(1), "/voicemodel", channel="matrix"))

    assert "Aktuelle Stimme:" in actions[0].text
    assert "onyx" in actions[0].text
    assert "https://platform.openai.com/docs/guides/text-to-speech#voice-options" in actions[0].text


def test_engine_mimic_voice_command_controls_voice_instruction_order(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.voice_instructions: list[str] = []

        def create_voice(self, _text, instructions):
            self.voice_instructions.append(instructions.openai_voice_instructions)
            return type("Voice", (), {"audio": b"voice", "filename": "voice.ogg", "content_type": "audio/ogg"})()

    from TeeBotus.runtime.tts_dialect import record_tts_voice_style_observation

    account_store = store(tmp_path)
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_voice_instructions="Basisstimme."),
        openai_client=client,
    )
    identity = signal_identity_key(source_uuid="mimic-engine")
    account_id = account_store.resolve_or_create_account(identity)

    engine.process(event(identity, "Ich bin in Dresden geboren.", channel="signal"))
    record_tts_voice_style_observation(
        account_store,
        account_id,
        "Aehm also isch rede sehr schnell und bin nervoes.",
        duration_seconds=3,
    )
    set_actions = engine.process(event(identity, "/mimic_voice before", channel="signal"))
    voice_actions = engine.process(event(identity, "/voice Hallo", channel="signal"))

    assert "vor dem Dialekt" in set_actions[0].text
    assert client.voice_instructions[0].index("beobachtete Sprechweise") < client.voice_instructions[0].index("Dresden")
    assert isinstance(voice_actions[1], SendAttachment)


def test_engine_voice_command_uses_reply_text(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.voice_texts: list[str] = []

        def create_voice(self, text, _instructions):
            self.voice_texts.append(text)
            return type("Voice", (), {"audio": b"voice", "filename": "voice.ogg", "content_type": "audio/ogg"})()

    client = FakeOpenAIClient()
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions(), openai_client=client)
    incoming = event(telegram_identity_key(1), "/voice", channel="matrix")
    incoming = IncomingEvent(
        event_id=incoming.event_id,
        instance=incoming.instance,
        channel=incoming.channel,
        adapter_slot=incoming.adapter_slot,
        account_id=incoming.account_id,
        identity_key=incoming.identity_key,
        chat_id=incoming.chat_id,
        chat_type=incoming.chat_type,
        sender_id=incoming.sender_id,
        sender_name=incoming.sender_name,
        sender_username=incoming.sender_username,
        sender_number=incoming.sender_number,
        text=incoming.text,
        message_ref=incoming.message_ref,
        reply_to_text="Aus Reply",
    )

    actions = engine.process(incoming)

    assert client.voice_texts == ["Aus Reply"]
    assert isinstance(actions[1], SendAttachment)


def test_engine_voice_command_requires_openai_client(tmp_path):
    instructions = BotInstructions(openai_missing_key="Key fehlt.")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions)

    actions = engine.process(event(telegram_identity_key(1), "/voice Hallo"))

    assert actions[0].text == "Key fehlt."


def test_engine_voice_command_requires_text(tmp_path):
    class FakeOpenAIClient:
        def create_voice(self, _text, _instructions):
            raise AssertionError("create_voice must not be called")

    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions(), openai_client=FakeOpenAIClient())

    actions = engine.process(event(telegram_identity_key(1), "/voice"))

    assert actions[0].text == "Nutzung: /voice Text fuer die Sprachnachricht"


def test_engine_voice_command_respects_disabled_voice(tmp_path):
    class FakeOpenAIClient:
        def create_voice(self, _text, _instructions):
            raise AssertionError("create_voice must not be called")

    instructions = BotInstructions(openai_voice_enabled=False, openai_voice_error="Voice aus.")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=FakeOpenAIClient())

    actions = engine.process(event(telegram_identity_key(1), "/voice Hallo"))

    assert actions[0].text == "Voice aus."


def test_engine_voice_command_rejects_too_long_text(tmp_path):
    class FakeOpenAIClient:
        def create_voice(self, _text, _instructions):
            raise AssertionError("create_voice must not be called")

    instructions = BotInstructions(openai_voice_max_input_chars=5)
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=FakeOpenAIClient())

    actions = engine.process(event(telegram_identity_key(1), "/voice zu lang"))

    assert actions[0].text == "Der Text ist zu lang fuer eine Sprachnachricht. Maximum: 5 Zeichen."


def test_engine_voice_command_reports_openai_error(tmp_path):
    class FakeOpenAIClient:
        def create_voice(self, _text, _instructions):
            raise OpenAIAPIError("boom")

    instructions = BotInstructions(openai_voice_error="Voice kaputt.")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=FakeOpenAIClient())

    actions = engine.process(event(telegram_identity_key(1), "/voice Hallo"))

    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "Voice kaputt."


def test_engine_youtube_transcript_command_sends_transcript(monkeypatch, tmp_path):
    calls = []

    def fake_transcribe(url, **kwargs):
        calls.append((url, kwargs))
        return "Transcript text.", "YouTube-Untertitel"

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions())

    actions = engine.process(event(telegram_identity_key(1), "/youtube_transcript https://youtu.be/abc123", channel="signal"))

    assert calls == [("https://youtu.be/abc123", {"local_allowed": False, "instance_name": "Depressionsbot"})]
    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "YouTube-Transkript (YouTube-Untertitel):\n\nTranscript text."


def test_engine_youtube_transcript_command_records_account_memory(monkeypatch, tmp_path):
    def fake_transcribe(_url, **_kwargs):
        return "Transcript text.", "YouTube-Untertitel"

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(user_memory_enabled=True),
    )

    engine.process(event(identity, "/youtube_transcript https://youtu.be/abc123", channel="signal"))

    entries = account_store.read_memory_entries(account_id)
    assert len(entries) == 1
    assert entries[0]["channel"] == "signal"
    assert entries[0]["user_text"] == "/youtube_transcript https://youtu.be/abc123"
    assert entries[0]["bot_text"] == "YouTube-Transkript (YouTube-Untertitel):\n\nTranscript text."


def test_engine_youtube_transcript_natural_request_uses_openai_pipeline(monkeypatch, tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.reply_inputs: list[str] = []

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.reply_inputs.append(user_text)
            return OpenAIResponse("AI summary.", "resp-youtube", None)

    monkeypatch.setattr(
        "TeeBotus.runtime.engine.transcribe_youtube_video",
        lambda _url, **_kwargs: ("Transcript text.", "YouTube-Untertitel"),
    )
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions(openai_enabled=True), openai_client=client)

    actions = engine.process(event(telegram_identity_key(1), "Bitte transkribiere dieses YouTube Video https://youtu.be/abc123", channel="matrix"))

    assert "YouTube-Transkript:" in client.reply_inputs[0]
    assert "Transcript text." in client.reply_inputs[0]
    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "AI summary."


def test_engine_youtube_openai_pipeline_includes_working_memory(monkeypatch, tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.reply_inputs: list[str] = []

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.reply_inputs.append(user_text)
            return OpenAIResponse("AI summary.", "resp-youtube", None)

    monkeypatch.setattr(
        "TeeBotus.runtime.engine.transcribe_youtube_video",
        lambda _url, **_kwargs: ("Architektur Transcript.", "YouTube-Untertitel"),
    )
    instances_dir = tmp_path / "instances"
    working_store = WorkingMemoryStore("Depressionsbot", instances_dir)
    working_store.append_manual("Architekturfragen zuerst kurz strukturieren.")
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(openai_enabled=True),
        openai_client=client,
        working_memory_store=working_store,
    )

    engine.process(event(telegram_identity_key(1), "/youtube_transcript https://youtu.be/abc123 Architektur", channel="matrix"))

    assert "Instanz-Arbeitsgedaechtnis:" in client.reply_inputs[0]
    assert "Architekturfragen zuerst kurz strukturieren" in client.reply_inputs[0]
    assert "YouTube-Transkript:" in client.reply_inputs[0]


def test_engine_youtube_openai_pipeline_includes_account_weather_and_library_context(monkeypatch, tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.reply_inputs: list[str] = []

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.reply_inputs.append(user_text)
            return OpenAIResponse("AI summary.", "resp-youtube", None)

    class FakeBibliothekarStore:
        def select(self, query_text, **_kwargs):
            assert "YouTube-Transkript:" in query_text
            return type("Selection", (), {"prompt_text": "Quelle: therapie.txt chunk_id=chunk-1"})()

    monkeypatch.setattr(
        "TeeBotus.runtime.engine.transcribe_youtube_video",
        lambda _url, **_kwargs: ("Therapie Transcript.", "YouTube-Untertitel"),
    )
    monkeypatch.setattr("TeeBotus.runtime.engine.weather_context_text", lambda _store, _account_id: "Berlin: 12 C")
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_therapy", "keywords": ["therapie"], "user_text": "Therapie lieber strukturiert.", "bot_text": "Gemerkt."},
    )
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True, bibliothekar_enabled=True),
        openai_client=client,
        bibliothekar_store=FakeBibliothekarStore(),
    )

    engine.process(event(identity, "/youtube_transcript https://youtu.be/abc123 Therapie", channel="signal"))

    assert "Persistentes Account-Memory:" in client.reply_inputs[0]
    assert "Therapie lieber strukturiert." in client.reply_inputs[0]
    assert "Lokaler Wetterkontext:" in client.reply_inputs[0]
    assert "Berlin: 12 C" in client.reply_inputs[0]
    assert "Bibliothekar-Quellenkontext:" in client.reply_inputs[0]
    assert "therapie.txt" in client.reply_inputs[0]


def test_engine_youtube_openai_pipeline_supports_active_memory_page(monkeypatch, tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.calls.append((user_text, previous_response_id))
            if len(self.calls) == 1:
                return OpenAIResponse('[[TEE_MEMORY_PAGE query="kaffee" exclude="mem_moon"]]', "resp-page-request", None)
            return OpenAIResponse("Kaffee ist nachgeladen.", "resp-final", None)

    monkeypatch.setattr(
        "TeeBotus.runtime.engine.transcribe_youtube_video",
        lambda _url, **_kwargs: ("Mond Transcript.", "YouTube-Untertitel"),
    )
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_moon", "keywords": ["mond"], "user_text": "Mein Lieblingswort ist Mond.", "bot_text": "Gemerkt."},
    )
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_coffee", "keywords": ["kaffee"], "user_text": "Kaffee beruhigt beim Sortieren.", "bot_text": "Gemerkt."},
    )
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True, user_memory_max_prompt_chars=1200),
        openai_client=client,
    )

    actions = engine.process(event(identity, "/youtube_transcript https://youtu.be/abc123 Mond", channel="matrix"))

    assert len(client.calls) == 2
    assert "Persistentes Account-Memory:" in client.calls[0][0]
    assert '[[TEE_MEMORY_PAGE query="kurze Suchphrase" exclude="id1,id2"]]' in client.calls[0][0]
    assert client.calls[1][1] == "resp-page-request"
    assert "Aktive Account-Memory-Page:" in client.calls[1][0]
    assert '"id": "mem_coffee"' in client.calls[1][0]
    assert '"id": "mem_moon"' not in client.calls[1][0]
    assert "YouTube-Transkript:" in client.calls[1][0]
    assert actions[-1].text == "Kaffee ist nachgeladen."


def test_engine_youtube_transcript_requires_link(tmp_path):
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions())

    actions = engine.process(event(telegram_identity_key(1), "/youtube_transcript"))

    assert actions[0].text == "Schick mir bitte den YouTube-Link, den ich transkribieren soll."


@pytest.mark.parametrize(
    "text",
    [
        "alter mach aus dem Video text!",
        "digga das yt, texte!",
        "VERDAMMT TRANSKRIBIER DIESES VIDEO!",
        "digga, video: output!",
        "DeDeWa! Moege das Orm dir die Beine wegaetzen. Transkribier diesen Scheiss! : zeit: 0 - letzte Minute nein.",
        "transcribiere dieses Video:",
        "transcribiere das video:",
    ],
)
def test_engine_youtube_transcript_freeform_phrases_request_link(tmp_path, text):
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions())

    actions = engine.process(event(telegram_identity_key(1), text))

    assert actions[0].text == "Schick mir bitte den YouTube-Link, den ich transkribieren soll."


def test_youtube_transcript_intent_does_not_trigger_on_plain_transcript_noun():
    assert _has_youtube_transcript_intent("das Transkript ist gut, danke") is False
    assert _has_youtube_transcript_intent("ich lese das Transcript nachher") is False
    assert _has_youtube_transcript_intent("den Untertitel finde ich komisch") is False
    assert _has_youtube_transcript_intent("transkribier das bitte") is True


def test_engine_youtube_transcript_uses_pending_link_followup(monkeypatch, tmp_path):
    calls = []

    def fake_transcribe(url, **kwargs):
        calls.append((url, kwargs))
        return "Transcript text.", "YouTube-Untertitel"

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions())
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)

    first = engine.process(event(identity, "/youtube_transcript", channel="signal"))
    second = engine.process(event(identity, "https://youtu.be/abc123", channel="signal"))

    assert first[0].text == "Schick mir bitte den YouTube-Link, den ich transkribieren soll."
    assert calls == [("https://youtu.be/abc123", {"local_allowed": False, "instance_name": "Depressionsbot"})]
    assert isinstance(second[0], SendTyping)
    assert second[1].text == "YouTube-Transkript (YouTube-Untertitel):\n\nTranscript text."
    assert engine.state.get_pending_flow("Depressionsbot", account_id, "youtube_link") is None


def test_engine_youtube_transcript_starts_local_by_default_when_no_subtitles(monkeypatch, tmp_path):
    from TeeBotus.core.youtube import YouTubeTranscriptError

    calls = []

    def fake_transcribe(url, **kwargs):
        calls.append((url, kwargs))
        if kwargs.get("local_allowed") is False:
            raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True)
        return "Local transcript.", "lokales Whisper"

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions(openai_model="gpt-test"))

    actions = engine.process(event(telegram_identity_key(1), "/youtube_transcript https://youtu.be/abc123"))

    assert calls == [
        ("https://youtu.be/abc123", {"local_allowed": False, "instance_name": "Depressionsbot"}),
        ("https://youtu.be/abc123", {"local_allowed": True, "live_callback": None, "instance_name": "Depressionsbot"}),
    ]
    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "YouTube-Transkript (lokales Whisper):\n\nLocal transcript."


def test_engine_youtube_transcript_uses_pending_local_options_followup(monkeypatch, tmp_path):
    from TeeBotus.core.youtube import YouTubeTranscriptError

    calls = []

    def fake_transcribe(url, **kwargs):
        calls.append((url, kwargs))
        if kwargs.get("local_allowed") is False:
            raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True)
        return "Local transcript.", "lokales Whisper"

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions())
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)

    engine.state.set_pending_flow(
        "Depressionsbot",
        account_id,
        "youtube_options",
        {
            "chat_id": "chat-1",
            "channel": "matrix",
            "url": "https://youtu.be/abc123",
            "original_text": "/youtube_transcript https://youtu.be/abc123",
        },
    )
    second = engine.process(event(identity, "live nein, llm nein", channel="matrix"))

    assert calls == [
        ("https://youtu.be/abc123", {"local_allowed": True, "live_callback": None, "instance_name": "Depressionsbot"}),
    ]
    assert isinstance(second[0], SendTyping)
    assert second[1].text == "YouTube-Transkript (lokales Whisper):\n\nLocal transcript."
    assert engine.state.get_pending_flow("Depressionsbot", account_id, "youtube_options") is None


def test_engine_youtube_transcript_runs_local_when_options_are_explicit(monkeypatch, tmp_path):
    from TeeBotus.core.youtube import YouTubeTranscriptError

    calls = []

    def fake_transcribe(url, **kwargs):
        calls.append((url, kwargs))
        if kwargs.get("local_allowed") is False:
            raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True)
        return "Local transcript.", "lokales Whisper"

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions())

    actions = engine.process(event(telegram_identity_key(1), "/youtube_transcript https://youtu.be/abc123 live nein, llm nein"))

    assert calls == [
        ("https://youtu.be/abc123", {"local_allowed": False, "instance_name": "Depressionsbot"}),
        ("https://youtu.be/abc123", {"local_allowed": True, "live_callback": None, "instance_name": "Depressionsbot"}),
    ]
    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "YouTube-Transkript (lokales Whisper):\n\nLocal transcript."


def test_engine_youtube_local_transcription_can_run_as_background_job(monkeypatch, tmp_path):
    from TeeBotus.core.youtube import YouTubeTranscriptError

    class FakeRunner:
        def __init__(self) -> None:
            self.callbacks = []

        def submit(self, callback):
            self.callbacks.append(callback)
            callback()
            return object()

    background: list[list[str]] = []
    calls = []

    def fake_transcribe(url, **kwargs):
        calls.append((url, kwargs))
        if kwargs.get("local_allowed") is False:
            raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True)
        live_callback = kwargs.get("live_callback")
        if live_callback is not None:
            live_callback("eins zwei drei", force=True)
        return "Local transcript.", "lokales Whisper"

    def dispatch(_event, actions):
        background.append([action.text for action in actions if hasattr(action, "text")])

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    runner = FakeRunner()
    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(),
        youtube_job_runner=runner,
        background_action_dispatcher=dispatch,
    )

    actions = engine.process(event(telegram_identity_key(1), "/youtube_transcript https://youtu.be/abc123 live ja, llm nein", channel="signal"))

    assert actions[0].text == "Lokale YouTube-Transkription gestartet. Ich melde mich, sobald sie fertig ist. Live-Ausgabe ist aktiviert."
    assert len(runner.callbacks) == 1
    assert calls[0] == ("https://youtu.be/abc123", {"local_allowed": False, "instance_name": "Depressionsbot"})
    assert calls[1][0] == "https://youtu.be/abc123"
    assert calls[1][1]["local_allowed"] is True
    assert calls[1][1]["instance_name"] == "Depressionsbot"
    assert callable(calls[1][1]["live_callback"])
    assert background == [["eins zwei drei"], ["YouTube-Transkript (lokales Whisper):\n\nLocal transcript."]]


def test_engine_youtube_background_off_off_dispatches_finished_transcript(monkeypatch, tmp_path):
    from TeeBotus.core.youtube import YouTubeTranscriptError

    class FakeRunner:
        def __init__(self) -> None:
            self.callbacks = []

        def submit(self, callback):
            self.callbacks.append(callback)
            callback()
            return object()

    background: list[list[str]] = []
    calls = []

    def fake_transcribe(url, **kwargs):
        calls.append((url, kwargs))
        if kwargs.get("local_allowed") is False:
            raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True)
        return "Local transcript.", "lokales Whisper"

    def dispatch(_event, actions):
        background.append([action.text for action in actions if hasattr(action, "text")])

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    runner = FakeRunner()
    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(),
        youtube_job_runner=runner,
        background_action_dispatcher=dispatch,
    )

    actions = engine.process(event(telegram_identity_key(1), "/youtube_transcript https://youtu.be/abc123 live nein, llm nein", channel="signal"))

    assert actions[0].text == "Lokale YouTube-Transkription gestartet. Ich melde mich, sobald sie fertig ist."
    assert len(runner.callbacks) == 1
    assert calls == [
        ("https://youtu.be/abc123", {"local_allowed": False, "instance_name": "Depressionsbot"}),
        ("https://youtu.be/abc123", {"local_allowed": True, "live_callback": None, "instance_name": "Depressionsbot"}),
    ]
    assert background == [["YouTube-Transkript (lokales Whisper):\n\nLocal transcript."]]


def test_engine_youtube_background_live_records_start_and_full_transcript(monkeypatch, tmp_path):
    from TeeBotus.core.youtube import YouTubeTranscriptError

    class FakeRunner:
        def submit(self, callback):
            callback()
            return object()

    def fake_transcribe(_url, **kwargs):
        if kwargs.get("local_allowed") is False:
            raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True)
        live_callback = kwargs.get("live_callback")
        if live_callback is not None:
            live_callback("eins zwei drei", force=True)
        return "Full local transcript.", "lokales Whisper"

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(user_memory_enabled=True),
        youtube_job_runner=FakeRunner(),
        background_action_dispatcher=lambda _event, _actions: None,
    )

    engine.process(event(identity, "/youtube_transcript https://youtu.be/abc123 live ja, llm nein", channel="signal"))

    bot_texts = [entry["bot_text"] for entry in account_store.read_memory_entries(account_id)]
    assert "Lokale YouTube-Transkription gestartet. Ich melde mich, sobald sie fertig ist. Live-Ausgabe ist aktiviert." in bot_texts
    assert "YouTube-Transkript (lokales Whisper):\n\nFull local transcript." in bot_texts


def test_engine_youtube_local_options_uses_llm_fallback(monkeypatch, tmp_path):
    from TeeBotus.core.youtube import YouTubeTranscriptError

    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.reply_inputs: list[str] = []

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.reply_inputs.append(user_text)
            if len(self.reply_inputs) == 1:
                return OpenAIResponse('{"live_output": false, "send_to_llm": true}', "resp-options", None)
            return OpenAIResponse("AI summary.", "resp-youtube", None)

    calls = []

    def fake_transcribe(url, **kwargs):
        calls.append((url, kwargs))
        if kwargs.get("local_allowed") is False:
            raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True)
        return "Local transcript.", "lokales Whisper"

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    monkeypatch.setattr("TeeBotus.runtime.engine._parse_youtube_local_options", lambda _text, **_kwargs: (None, None))
    monkeypatch.setattr("TeeBotus.runtime.engine._record_youtube_parser_miss", lambda *_args, **_kwargs: None)
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(openai_enabled=True),
        openai_client=client,
    )

    actions = engine.process(event(telegram_identity_key(1), "/youtube_transcript https://youtu.be/abc123 mach bitte die passende variante", channel="signal"))

    assert calls == [
        ("https://youtu.be/abc123", {"local_allowed": False, "instance_name": "Depressionsbot"}),
        ("https://youtu.be/abc123", {"local_allowed": True, "live_callback": None, "instance_name": "Depressionsbot"}),
    ]
    assert "Klassifiziere ausschliesslich die Optionen" in client.reply_inputs[0]
    assert "YouTube-Transkript:" in client.reply_inputs[1]
    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "AI summary."


def test_engine_youtube_natural_group_request_must_address_bot(monkeypatch, tmp_path):
    def fake_transcribe(_url, **_kwargs):
        raise AssertionError("transcribe_youtube_video must not be called")

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions())
    incoming = IncomingEvent(
        event_id="matrix:1",
        instance="Depressionsbot",
        channel="matrix",
        adapter_slot=1,
        identity_key=telegram_identity_key(1),
        chat_id="chat-1",
        chat_type="group",
        sender_id="alice",
        text="Bitte transkribiere dieses YouTube Video https://youtu.be/abc123",
        message_ref="1",
    )

    actions = engine.process(incoming)

    assert actions == []


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
