from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from signalbot import Command
from signalbot.message import MessageType

from TeeBotus.runtime.accounts import StaticSecretProvider
from TeeBotus.runtime.actions import DeleteTrackedMessages, ExportFile, NotifyLinkedIdentity, SendPoll, SendText
from TeeBotus.runtime.config import AccountRunConfig, InstanceRunConfig, RuntimeConfig
from TeeBotus.runtime.engine import EngineResult
from TeeBotus.runtime.message_tracking import SentMessageRef
from TeeBotus.runtime.signal_runner import (
    SignalRuntimeError,
    check_signal_accounts,
    SignalServiceHealth,
    TeeBotusSignalCommand,
    check_signal_service,
    ensure_signal_services_available,
    _ensure_signal_json_rpc_daemon,
    _patch_signalbot_signal_cli_api_about,
    _pid_file_process_is_running,
    _require_signal_cli_api_accounts_registered,
    _signal_context_recipient,
    run_signal_account,
    run_signal_accounts,
)


class FakeSignalMessage:
    source_uuid = "signal-uuid"
    source_number = "+491234"
    source = "+491234"
    text = "/account"
    timestamp = 123456
    group = ""
    attachments_local_filenames = []
    base64_attachments = []
    type = MessageType.DATA_MESSAGE

    def recipient(self) -> str:
        return self.source


class FakeSignalContext:
    def __init__(self) -> None:
        self.message = FakeSignalMessage()
        self.sent: list[str] = []
        self.bot_sent: list[tuple[str, str, dict[str, object]]] = []
        self.bot_polls: list[tuple[str, str, list[str], dict[str, object]]] = []
        self.deleted_attachments: list[str] = []
        self.deleted: list[int] = []
        self.bot_deleted: list[tuple[str, int]] = []
        self.bot = SimpleNamespace(
            send=self.send_bot,
            poll=self.poll_bot,
            delete_attachment=self.delete_attachment,
            remote_delete=self.remote_delete_bot,
        )

    async def send(self, text: str, **_kwargs) -> int:
        self.sent.append(text)
        return 987654

    async def send_bot(self, receiver: str, text: str, **kwargs) -> int:
        self.sent.append(text)
        self.bot_sent.append((receiver, text, kwargs))
        return 987654

    async def poll_bot(self, receiver: str, question: str, answers: list[str], **kwargs) -> int:
        self.bot_polls.append((receiver, question, answers, kwargs))
        return 876543

    async def delete_attachment(self, filename: str) -> None:
        self.deleted_attachments.append(filename)

    async def start_typing(self) -> None:
        return None

    async def remote_delete(self, timestamp: int) -> int:
        self.deleted.append(timestamp)
        return timestamp

    async def remote_delete_bot(self, receiver: str, timestamp: int) -> int:
        self.bot_deleted.append((receiver, timestamp))
        return timestamp


class FakeSignalBot:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, receiver: str, text: str) -> int:
        self.sent.append((receiver, text))
        return 123


def test_signal_command_is_signalbot_command_subclass(tmp_path) -> None:
    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )

    assert isinstance(command, Command)
    assert command.bot is None


def test_signal_command_exposes_proactive_sender_when_bot_is_attached(tmp_path) -> None:
    class Bot:
        def __init__(self) -> None:
            self.calls = []

        async def send(self, receiver: str, text: str, **kwargs) -> int:
            self.calls.append((receiver, text, kwargs))
            return 123456

    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=2,
            label="signal:2",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )
    bot = Bot()
    command.bot = bot

    sender = command.proactive_sender()
    sent_ref = asyncio.run(sender({"adapter_slot": 2}, SendText("+491", "hi"), {}))

    assert sent_ref == 123456
    assert bot.calls[0][0:2] == ("+491", "hi")


def test_signal_command_routes_private_account_commands(tmp_path) -> None:
    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )
    context = FakeSignalContext()

    asyncio.run(command.handle(context))

    assert context.sent
    assert "Deine TeeBotus-Account-ID" in context.sent[0]


def test_signal_command_tracks_engine_result_account_id(tmp_path) -> None:
    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )
    target_account_id = "a" * 128
    command.engine = type(
        "FakeEngine",
        (),
        {"process_result": lambda self, event: EngineResult(target_account_id, [SendText(event.chat_id, "verbunden")], handled=True)},
    )()
    context = FakeSignalContext()

    asyncio.run(command.handle(context))

    refs = command.message_tracker.pop_for_cleanup(instance_name="Demo", channel="signal", chat_id="+491234", count=1)
    assert len(refs) == 1
    assert refs[0].account_id == target_account_id


def test_signal_context_recipient_tolerates_broken_signalbot_message() -> None:
    class Message:
        def recipient(self) -> str:
            raise RuntimeError("signalbot recipient failed")

    assert _signal_context_recipient(SimpleNamespace(message=Message())) == ""


def test_signal_cleanup_uses_context_remote_delete_first(tmp_path) -> None:
    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )
    command.engine = type("FakeEngine", (), {"process": lambda self, event: [DeleteTrackedMessages(event.chat_id, 1)]})()
    command.message_tracker.record(
        SentMessageRef(
            channel="signal",
            instance_name="Demo",
            account_id="account-1",
            chat_id="+491234",
            message_ref="444",
            ref_kind="signal_timestamp",
        )
    )
    context = FakeSignalContext()

    asyncio.run(command.handle(context))

    assert context.deleted == [444]
    assert context.bot_deleted == []


def test_signal_cleanup_falls_back_to_bot_remote_delete(tmp_path) -> None:
    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )
    command.engine = type("FakeEngine", (), {"process": lambda self, event: [DeleteTrackedMessages(event.chat_id, 1)]})()
    command.message_tracker.record(
        SentMessageRef(
            channel="signal",
            instance_name="Demo",
            account_id="account-1",
            chat_id="+491234",
            message_ref="555",
            ref_kind="signal_timestamp",
        )
    )
    context = FakeSignalContext()
    context.remote_delete = None

    asyncio.run(command.handle(context))

    assert context.deleted == []
    assert context.bot_deleted == [("+491234", 555)]


def test_signal_cleanup_restores_ref_when_remote_delete_fails(tmp_path) -> None:
    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )
    command.engine = type("FakeEngine", (), {"process": lambda self, event: [DeleteTrackedMessages(event.chat_id, 1)]})()
    ref = SentMessageRef(
        channel="signal",
        instance_name="Demo",
        account_id="account-1",
        chat_id="+491234",
        message_ref="666",
        ref_kind="signal_timestamp",
    )
    command.message_tracker.record(ref)
    context = FakeSignalContext()

    async def failing_remote_delete(_timestamp: int) -> int:
        raise RuntimeError("delete refused")

    context.remote_delete = failing_remote_delete

    asyncio.run(command.handle(context))

    assert command.message_tracker.list_for_chat("+491234", instance_name="Demo", channel="signal") == [ref]


def test_signal_command_uses_instance_instructions_for_builtin_replies(tmp_path) -> None:
    instance_dir = tmp_path / "Demo"
    instance_dir.mkdir()
    (instance_dir / "Bot_Verhalten.md").write_text("## Befehle\n- /custom: Signal custom fuer {first_name}.\n", encoding="utf-8")
    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )
    context = FakeSignalContext()
    context.message.text = "/custom"

    asyncio.run(command.handle(context))

    assert context.sent == ["Signal custom fuer +491234."]
    assert context.bot_sent == [
        (
            "+491234",
            "Signal custom fuer +491234.",
            {
                "base64_attachments": None,
                "quote_author": "+491234",
                "quote_message": "/custom",
                "quote_timestamp": 123456,
            },
        )
    ]


def test_signal_command_preserves_explicit_engine_reply_context(tmp_path) -> None:
    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )
    command.engine = type(
        "FakeEngine",
        (),
        {"process": lambda self, event: [SendText(event.chat_id, "Explizit", reply_to_ref="111")]},
    )()
    context = FakeSignalContext()

    asyncio.run(command.handle(context))

    assert context.sent == ["Explizit"]
    assert context.bot_sent == []


def test_signal_command_quotes_original_timestamp_for_edit_message(tmp_path) -> None:
    instance_dir = tmp_path / "Demo"
    instance_dir.mkdir()
    (instance_dir / "Bot_Verhalten.md").write_text("## Befehle\n- /custom: Signal custom fuer {first_name}.\n", encoding="utf-8")
    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )
    context = FakeSignalContext()
    context.message.type = MessageType.EDIT_MESSAGE
    context.message.text = "/custom"
    context.message.timestamp = 200
    context.message.target_sent_timestamp = 100

    asyncio.run(command.handle(context))

    assert context.sent == ["Signal custom fuer +491234."]
    assert context.bot_sent == [
        (
            "+491234",
            "Signal custom fuer +491234.",
            {
                "base64_attachments": None,
                "quote_author": "+491234",
                "quote_message": "/custom",
                "quote_timestamp": 100,
            },
        )
    ]


def test_signal_group_free_text_must_address_bot(tmp_path) -> None:
    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )
    context = FakeSignalContext()
    context.message.group = "group-1"
    context.message.text = "Hallo Gruppe"

    asyncio.run(command.handle(context))

    assert context.sent == []
    assert command.account_store.get_account_for_identity("signal:uuid:signal-uuid") is None


def test_signal_group_free_text_can_address_bot_by_phone(tmp_path) -> None:
    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )
    context = FakeSignalContext()
    context.message.group = "group-1"
    context.message.text = "+491234 hallo"

    asyncio.run(command.handle(context))

    assert context.sent == ["Echo: +491234 hallo"]


def test_signal_command_constructs_openai_client_from_run_config(monkeypatch, tmp_path) -> None:
    captured: list[str] = []

    class FakeOpenAIClient:
        def __init__(self, api_key: str) -> None:
            captured.append(api_key)

    monkeypatch.setattr("TeeBotus.runtime.signal_runner.OpenAIClient", FakeOpenAIClient)
    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="sk-signal",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )

    assert captured == ["sk-signal"]
    assert command.engine.openai_client is command.openai_client


def test_signal_command_ignores_non_content_message_types(tmp_path) -> None:
    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )
    context = FakeSignalContext()
    context.message.type = MessageType.REACTION_MESSAGE

    asyncio.run(command.handle(context))

    assert context.sent == []
    assert command.account_store.get_account_for_identity("signal:uuid:signal-uuid") is None


def test_signal_cleanup_deletes_tracked_current_chat_messages(tmp_path) -> None:
    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )
    context = FakeSignalContext()
    account_id = command.account_store.resolve_or_create_account("signal:uuid:signal-uuid")
    command.message_tracker.record(
        SentMessageRef(
            channel="signal",
            instance_name="Demo",
            account_id=account_id,
            chat_id="+491234",
            message_ref="555",
            ref_kind="signal_timestamp",
        )
    )
    context.message.text = "/cleanup 1"

    asyncio.run(command.handle(context))

    assert context.deleted == [555]
    assert any("aktuellen Chat" in text for text in context.sent)


def test_signal_command_tracks_export_files_for_cleanup(tmp_path) -> None:
    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )
    command.engine = type(
        "FakeEngine",
        (),
        {"process": lambda self, event: [ExportFile(event.chat_id, "report.txt", "text/plain", b"hello")]},
    )()
    context = FakeSignalContext()

    asyncio.run(command.handle(context))

    refs = command.message_tracker.pop_for_cleanup(instance_name="Demo", channel="signal", chat_id="+491234", count=1)
    assert len(refs) == 1
    assert refs[0].message_ref == "987654"


def test_signal_command_tracks_polls_for_cleanup(tmp_path) -> None:
    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )
    command.engine = type(
        "FakeEngine",
        (),
        {"process": lambda self, event: [SendPoll(event.chat_id, "Tee?", ("Ja", "Nein"))]},
    )()
    context = FakeSignalContext()

    asyncio.run(command.handle(context))

    refs = command.message_tracker.pop_for_cleanup(instance_name="Demo", channel="signal", chat_id="+491234", count=1)
    assert len(refs) == 1
    assert refs[0].message_ref == "876543"
    assert context.bot_polls == [("+491234", "Tee?", ["Ja", "Nein"], {"allow_multiple_selections": False})]


def test_signal_command_deletes_local_attachments_after_handling(tmp_path) -> None:
    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )
    context = FakeSignalContext()
    context.message.attachments_local_filenames = ["voice.ogg", "", "voice.ogg", "photo.jpg"]

    asyncio.run(command.handle(context))

    assert context.deleted_attachments == ["voice.ogg", "photo.jpg"]


def test_signal_command_deletes_local_attachments_when_engine_fails(tmp_path) -> None:
    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )
    command.engine = type(
        "FailingEngine",
        (),
        {"process": lambda self, _event: (_ for _ in ()).throw(RuntimeError("engine failed"))},
    )()
    context = FakeSignalContext()
    context.message.attachments_local_filenames = ["voice.ogg"]

    try:
        asyncio.run(command.handle(context))
    except RuntimeError as exc:
        assert "engine failed" in str(exc)
    else:
        raise AssertionError("RuntimeError was not raised")

    assert context.deleted_attachments == ["voice.ogg"]


def test_signal_command_notifies_old_signal_identity_route(tmp_path) -> None:
    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )
    old_identity = "signal:uuid:old"
    command.account_store.resolve_or_create_account(old_identity)
    command.account_store.update_identity_route(old_identity, channel="signal", chat_id="+49999", chat_type="private", adapter_slot=1)
    command.engine = type(
        "FakeEngine",
        (),
        {
            "process": lambda self, event: [
                NotifyLinkedIdentity(
                    identity_key=old_identity,
                    text="Ein neuer Kommunikationsweg wurde verbunden.",
                    account_id=event.account_id,
                    new_identity_key=event.identity_key,
                )
            ]
        },
    )()
    fake_bot = FakeSignalBot()
    command.bot = fake_bot

    asyncio.run(command.handle(FakeSignalContext()))

    assert fake_bot.sent == [("+49999", "Ein neuer Kommunikationsweg wurde verbunden.")]


def test_signal_command_tracks_linked_identity_notification_when_requested(tmp_path) -> None:
    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )
    old_identity = "signal:uuid:old"
    command.account_store.resolve_or_create_account(old_identity)
    command.account_store.update_identity_route(old_identity, channel="signal", chat_id="+49999", chat_type="private", adapter_slot=1)
    command.engine = type(
        "FakeEngine",
        (),
        {
            "process": lambda self, event: [
                NotifyLinkedIdentity(
                    identity_key=old_identity,
                    text="Ein neuer Kommunikationsweg wurde verbunden.",
                    account_id=event.account_id,
                    new_identity_key=event.identity_key,
                    track=True,
                )
            ]
        },
    )()
    fake_bot = FakeSignalBot()
    command.bot = fake_bot

    asyncio.run(command.handle(FakeSignalContext()))

    refs = command.message_tracker.pop_for_cleanup(instance_name="Demo", channel="signal", chat_id="+49999", count=1)
    assert len(refs) == 1
    assert refs[0].message_ref == "123"


def test_signal_only_multi_slot_start_backgrounds_additional_slots(monkeypatch, tmp_path) -> None:
    calls: list[tuple[str, int]] = []

    class FakeThread:
        def __init__(self, slot: int) -> None:
            self.slot = slot

        def start(self) -> None:
            calls.append(("background", self.slot))

    accounts = (
        AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491",
        ),
        AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=2,
            label="signal:2",
            openai_api_key="",
            signal_service="http://127.0.0.1:8081",
            signal_phone_number="+492",
        ),
    )
    config = RuntimeConfig(
        instances_dir=tmp_path,
        selected_instances=("Demo",),
        channels=("signal",),
        instances=(InstanceRunConfig("Demo", tmp_path / "Bot_Verhalten.md", accounts),),
    )
    monkeypatch.setattr("TeeBotus.runtime.signal_runner._import_signalbot", lambda: object())
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_services", lambda _config: ())
    monkeypatch.setattr("TeeBotus.runtime.signal_runner._require_signal_cli_api_accounts_registered", lambda _config: None)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner._signal_account_thread", lambda *, account, instances_dir: FakeThread(account.slot))
    monkeypatch.setattr(
        "TeeBotus.runtime.signal_runner.run_signal_account",
        lambda *, account, instances_dir: calls.append(("blocking", account.slot)),
    )

    assert run_signal_accounts(config) == 0
    assert calls == [("background", 2), ("blocking", 1)]


def test_signal_start_fails_before_threads_when_service_unreachable(monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    account = AccountRunConfig(
        instance_name="Demo",
        channel="signal",
        slot=1,
        label="signal:1",
        openai_api_key="",
        signal_service="http://127.0.0.1:8080",
        signal_phone_number="+491",
    )
    config = RuntimeConfig(
        instances_dir=tmp_path,
        selected_instances=("Demo",),
        channels=("signal",),
        instances=(InstanceRunConfig("Demo", tmp_path / "Bot_Verhalten.md", (account,)),),
    )
    monkeypatch.setattr("TeeBotus.runtime.signal_runner._import_signalbot", lambda: object())
    monkeypatch.setattr(
        "TeeBotus.runtime.signal_runner.check_signal_services",
        lambda _config: (SignalServiceHealth(account=account, ok=False, target="127.0.0.1:8080", error="connection refused"),),
    )
    monkeypatch.setattr("TeeBotus.runtime.signal_runner._start_local_signal_backend_if_possible", lambda _account: None)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.run_signal_account", lambda **_kwargs: calls.append("started"))

    try:
        run_signal_accounts(config)
    except SignalRuntimeError as exc:
        assert "signal-cli-rest-api nicht erreichbar" in str(exc)
    else:
        raise AssertionError("SignalRuntimeError was not raised")
    assert calls == []


def test_signal_backend_autostarts_local_signal_cli_api(monkeypatch, tmp_path) -> None:
    account = AccountRunConfig(
        instance_name="Demo",
        channel="signal",
        slot=1,
        label="signal:1",
        openai_api_key="",
        signal_service="http://localhost:8080",
        signal_phone_number="+491",
    )
    config = RuntimeConfig(
        instances_dir=tmp_path,
        selected_instances=("Demo",),
        channels=("signal",),
        instances=(InstanceRunConfig("Demo", tmp_path / "Bot_Verhalten.md", (account,)),),
    )
    commands: list[list[str]] = []
    envs: list[dict[str, str]] = []
    service_up = {"value": False}

    class FakeProcess:
        pid = 4321

        def poll(self):
            return None

    def fake_check_signal_services(_config):
        return (
            SignalServiceHealth(
                account=account,
                ok=service_up["value"],
                target="localhost:8080",
                error="" if service_up["value"] else "connection refused",
            ),
        )

    def fake_check_signal_service(_account, timeout_seconds=1.0):
        return SignalServiceHealth(
            account=account,
            ok=service_up["value"],
            target="localhost:8080",
            error="" if service_up["value"] else "connection refused",
        )

    def fake_popen(command, **kwargs):
        commands.append(command)
        envs.append(kwargs["env"])
        service_up["value"] = True
        return FakeProcess()

    def fake_which(binary, path=None):
        if binary == "signal-cli-rest-api":
            return "signal-cli-rest-api"
        if binary == "signal-cli" and path and ".local/bin" in path:
            return "/home/teladi/.local/bin/signal-cli"
        return None

    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_services", fake_check_signal_services)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_service", fake_check_signal_service)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.runtime_dir", lambda: tmp_path / "runtime")
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.subprocess.Popen", fake_popen)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.shutil.which", fake_which)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner._ensure_signal_json_rpc_daemon", lambda: None)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner._require_signal_cli_api_accounts_registered", lambda _config: None)

    ensure_signal_services_available(config)

    assert commands == [
        [
            "signal-cli-rest-api",
            "-signal-cli-config",
            str(Path.home() / ".local" / "share" / "signal-cli"),
            "-attachment-tmp-dir",
            str(tmp_path / "runtime"),
            "-avatar-tmp-dir",
            str(tmp_path / "runtime"),
        ]
    ]
    assert envs[0]["PORT"] == "8080"
    assert envs[0]["MODE"] == "json-rpc"
    assert envs[0]["BUILD_VERSION"] == "0.100"
    assert ".local/bin" in envs[0]["PATH"]
    assert ".cargo/bin" in envs[0]["PATH"]
    assert (tmp_path / "runtime" / "signal-cli-rest-api-Demo-1.pid").read_text(encoding="utf-8") == "4321\n"


def test_signal_backend_autostart_requires_signal_cli_binary(monkeypatch, tmp_path) -> None:
    account = AccountRunConfig(
        instance_name="Demo",
        channel="signal",
        slot=1,
        label="signal:1",
        openai_api_key="",
        signal_service="http://localhost:8080",
        signal_phone_number="+491",
    )
    config = RuntimeConfig(
        instances_dir=tmp_path,
        selected_instances=("Demo",),
        channels=("signal",),
        instances=(InstanceRunConfig("Demo", tmp_path / "Bot_Verhalten.md", (account,)),),
    )

    monkeypatch.setattr(
        "TeeBotus.runtime.signal_runner.check_signal_services",
        lambda _config: (SignalServiceHealth(account=account, ok=False, target="localhost:8080", error="connection refused"),),
    )
    monkeypatch.setattr(
        "TeeBotus.runtime.signal_runner.check_signal_service",
        lambda _account, timeout_seconds=1.0: SignalServiceHealth(
            account=account,
            ok=False,
            target="localhost:8080",
            error="connection refused",
        ),
    )
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.runtime_dir", lambda: tmp_path / "runtime")
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.shutil.which", lambda binary, path=None: "signal-cli-rest-api" if binary == "signal-cli-rest-api" else None)
    monkeypatch.setattr(
        "TeeBotus.runtime.signal_runner.subprocess.Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("signal-cli-rest-api must not start without signal-cli")),
    )

    try:
        ensure_signal_services_available(config)
    except SignalRuntimeError as exc:
        assert "signal-cli ist nicht im PATH" in str(exc)
    else:
        raise AssertionError("SignalRuntimeError was not raised")


def test_signal_backend_autostarts_shared_local_service_once(monkeypatch, tmp_path) -> None:
    accounts = (
        AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://localhost:8080",
            signal_phone_number="+491",
        ),
        AccountRunConfig(
            instance_name="Other",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://localhost:8080",
            signal_phone_number="+492",
        ),
    )
    config = RuntimeConfig(
        instances_dir=tmp_path,
        selected_instances=("Demo", "Other"),
        channels=("signal",),
        instances=(
            InstanceRunConfig("Demo", tmp_path / "Demo.md", (accounts[0],)),
            InstanceRunConfig("Other", tmp_path / "Other.md", (accounts[1],)),
        ),
    )
    commands: list[list[str]] = []
    service_up = {"value": False}

    class FakeProcess:
        pid = 4321

        def poll(self):
            return None

    def fake_check_signal_services(_config):
        return tuple(
            SignalServiceHealth(
                account=account,
                ok=service_up["value"],
                target="localhost:8080",
                error="" if service_up["value"] else "connection refused",
            )
            for account in accounts
        )

    def fake_check_signal_service(account, timeout_seconds=1.0):
        return SignalServiceHealth(
            account=account,
            ok=service_up["value"],
            target="localhost:8080",
            error="" if service_up["value"] else "connection refused",
        )

    def fake_popen(command, **_kwargs):
        commands.append(command)
        service_up["value"] = True
        return FakeProcess()

    def fake_which(binary, path=None):
        if binary == "signal-cli-rest-api":
            return "signal-cli-rest-api"
        if binary == "signal-cli":
            return "/home/teladi/.local/bin/signal-cli"
        return None

    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_services", fake_check_signal_services)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_service", fake_check_signal_service)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.runtime_dir", lambda: tmp_path / "runtime")
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.subprocess.Popen", fake_popen)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.shutil.which", fake_which)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner._ensure_signal_json_rpc_daemon", lambda: None)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner._require_signal_cli_api_accounts_registered", lambda _config: None)

    ensure_signal_services_available(config)

    assert commands == [
        [
            "signal-cli-rest-api",
            "-signal-cli-config",
            str(Path.home() / ".local" / "share" / "signal-cli"),
            "-attachment-tmp-dir",
            str(tmp_path / "runtime"),
            "-avatar-tmp-dir",
            str(tmp_path / "runtime"),
        ]
    ]


def test_signal_json_rpc_daemon_writes_config_and_starts_signal_cli(monkeypatch, tmp_path) -> None:
    commands: list[list[str]] = []
    opened = {"value": False}

    class FakeProcess:
        pid = 9876

        def poll(self):
            return None

    def fake_popen(command, **_kwargs):
        commands.append(command)
        opened["value"] = True
        return FakeProcess()

    monkeypatch.setenv("SIGNAL_CLI_CONFIG_DIR", str(tmp_path / "signal-cli"))
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.runtime_dir", lambda: tmp_path / "runtime")
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.shutil.which", lambda binary, path=None: "/home/teladi/.local/bin/signal-cli" if binary == "signal-cli" else None)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.subprocess.Popen", fake_popen)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner._tcp_port_is_open", lambda *_args, **_kwargs: opened["value"])

    _ensure_signal_json_rpc_daemon()

    assert (tmp_path / "signal-cli" / "jsonrpc2.yml").read_text(encoding="utf-8") == "config:\n  <multi-account>:\n    tcp_port: 6001\n"
    assert commands == [
        [
            "/home/teladi/.local/bin/signal-cli",
            "--output=json",
            "--config",
            str(tmp_path / "signal-cli"),
            "daemon",
            "--tcp",
            "127.0.0.1:6001",
        ]
    ]
    assert (tmp_path / "runtime" / "signal-cli-json-rpc-daemon.pid").read_text(encoding="utf-8") == "9876\n"


def test_signalbot_patch_accepts_signal_cli_rest_api_about_shape() -> None:
    class FakeSignalAPI:
        async def get_signal_cli_about(self):
            return {"build": {"os": "linux"}, "versions": {"signal-cli-rest-api": "0.100"}}

        async def get_signal_cli_rest_api_version(self):
            raise KeyError("version")

        async def get_signal_cli_rest_api_mode(self):
            raise KeyError("mode")

    fake_signalbot = SimpleNamespace(api=SimpleNamespace(SignalAPI=FakeSignalAPI))

    _patch_signalbot_signal_cli_api_about(fake_signalbot)

    api = FakeSignalAPI()
    assert asyncio.run(api.get_signal_cli_rest_api_version()) == "0.100"
    assert asyncio.run(api.get_signal_cli_rest_api_mode()) == "json-rpc"


def test_signalbot_patch_accepts_unset_signal_cli_rest_api_about_version() -> None:
    class FakeSignalAPI:
        async def get_signal_cli_about(self):
            return {"build": {"os": "linux"}, "versions": {"signal-cli-rest-api": ""}}

        async def get_signal_cli_rest_api_version(self):
            raise KeyError("version")

        async def get_signal_cli_rest_api_mode(self):
            raise KeyError("mode")

    fake_signalbot = SimpleNamespace(api=SimpleNamespace(SignalAPI=FakeSignalAPI))

    _patch_signalbot_signal_cli_api_about(fake_signalbot)

    api = FakeSignalAPI()
    assert asyncio.run(api.get_signal_cli_rest_api_version()) == "unset"
    assert asyncio.run(api.get_signal_cli_rest_api_mode()) == "json-rpc"


def test_signalbot_patch_rejects_incompatible_rust_signal_cli_api_about_shape() -> None:
    class FakeSignalAPI:
        async def get_signal_cli_about(self):
            return {"build": {"os": "linux"}, "versions": {"signal-cli-api": "0.1.1"}}

        async def get_signal_cli_rest_api_version(self):
            raise KeyError("version")

        async def get_signal_cli_rest_api_mode(self):
            raise KeyError("mode")

    fake_signalbot = SimpleNamespace(api=SimpleNamespace(SignalAPI=FakeSignalAPI))

    _patch_signalbot_signal_cli_api_about(fake_signalbot)

    api = FakeSignalAPI()
    with pytest.raises(KeyError):
        asyncio.run(api.get_signal_cli_rest_api_version())


def test_signal_pid_check_rejects_dead_process(monkeypatch, tmp_path) -> None:
    pid_file = tmp_path / "signal-cli-rest-api.pid"
    pid_file.write_text("999999\n", encoding="utf-8")

    class Result:
        returncode = 1

    monkeypatch.setattr("TeeBotus.runtime.signal_runner.subprocess.run", lambda *_args, **_kwargs: Result())

    assert _pid_file_process_is_running(pid_file) is False


def test_signal_cli_api_account_preflight_accepts_registered_number(monkeypatch, tmp_path) -> None:
    account = AccountRunConfig(
        instance_name="Demo",
        channel="signal",
        slot=1,
        label="signal:1",
        openai_api_key="",
        signal_service="http://127.0.0.1:8080",
        signal_phone_number="+491",
    )
    config = RuntimeConfig(
        instances_dir=tmp_path,
        selected_instances=("Demo",),
        channels=("signal",),
        instances=(InstanceRunConfig("Demo", tmp_path / "Demo.md", (account,)),),
    )
    monkeypatch.setattr("TeeBotus.runtime.signal_runner._signal_service_looks_like_signal_cli_api", lambda _account: True)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner._signal_cli_api_accounts", lambda _account: ["+491"])

    _require_signal_cli_api_accounts_registered(config)


def test_signal_cli_api_account_preflight_rejects_missing_number(monkeypatch, tmp_path) -> None:
    account = AccountRunConfig(
        instance_name="Demo",
        channel="signal",
        slot=1,
        label="signal:1",
        openai_api_key="",
        signal_service="http://127.0.0.1:8080",
        signal_phone_number="+491",
    )
    config = RuntimeConfig(
        instances_dir=tmp_path,
        selected_instances=("Demo",),
        channels=("signal",),
        instances=(InstanceRunConfig("Demo", tmp_path / "Demo.md", (account,)),),
    )
    monkeypatch.setattr("TeeBotus.runtime.signal_runner._signal_service_looks_like_signal_cli_api", lambda _account: True)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner._signal_cli_api_accounts", lambda _account: [])

    try:
        _require_signal_cli_api_accounts_registered(config)
    except SignalRuntimeError as exc:
        assert "kennt den konfigurierten Signal-Account nicht" in str(exc)
    else:
        raise AssertionError("SignalRuntimeError was not raised")


def test_signal_account_health_reports_registered_and_missing_numbers(monkeypatch, tmp_path) -> None:
    accounts = (
        AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491",
        ),
        AccountRunConfig(
            instance_name="Other",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+492",
        ),
    )
    config = RuntimeConfig(
        instances_dir=tmp_path,
        selected_instances=("Demo", "Other"),
        channels=("signal",),
        instances=(
            InstanceRunConfig("Demo", tmp_path / "Demo.md", (accounts[0],)),
            InstanceRunConfig("Other", tmp_path / "Other.md", (accounts[1],)),
        ),
    )
    monkeypatch.setattr("TeeBotus.runtime.signal_runner._signal_service_looks_like_signal_cli_api", lambda _account: True)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner._signal_cli_api_accounts", lambda _account: ["+491"])

    health = check_signal_accounts(config)

    assert [item.registered for item in health] == [True, False]
    assert health[1].error == "account missing in signal-cli-rest-api /v1/accounts"


def test_signal_account_normalizes_documented_http_service_url(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    class FakeConfig:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    class FakeBot:
        def __init__(self, config: FakeConfig) -> None:
            self.config = config
            self.command = None

        def register(self, command) -> None:
            self.command = command

        def start(self) -> None:
            return None

    fake_signalbot = SimpleNamespace(
        Config=FakeConfig,
        SignalBot=FakeBot,
        InMemoryConfig=lambda: "memory-storage",
        api=SimpleNamespace(ConnectionMode=SimpleNamespace(HTTP_ONLY="http_only", HTTPS_ONLY="https_only")),
    )
    bots = []
    original_bot_class = fake_signalbot.SignalBot
    fake_signalbot.SignalBot = lambda config: bots.append(original_bot_class(config)) or bots[-1]
    monkeypatch.setattr("TeeBotus.runtime.signal_runner._import_signalbot", lambda: fake_signalbot)

    run_signal_account(
        account=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
    )

    assert captured["signal_service"] == "127.0.0.1:8080"
    assert captured["connection_mode"] == "http_only"
    assert captured["storage"] == "memory-storage"
    assert bots[0].command is not None
    assert bots[0].command.bot is bots[0]


def test_signal_account_uses_http_only_for_local_service_without_scheme(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    class FakeConfig:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    class FakeBot:
        def __init__(self, config: FakeConfig) -> None:
            self.config = config

        def register(self, _command) -> None:
            return None

        def start(self) -> None:
            return None

    fake_signalbot = SimpleNamespace(
        Config=FakeConfig,
        SignalBot=FakeBot,
        InMemoryConfig=lambda: "memory-storage",
        api=SimpleNamespace(ConnectionMode=SimpleNamespace(HTTP_ONLY="http_only", HTTPS_ONLY="https_only")),
    )
    monkeypatch.setattr("TeeBotus.runtime.signal_runner._import_signalbot", lambda: fake_signalbot)

    run_signal_account(
        account=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
    )

    assert captured["signal_service"] == "127.0.0.1:8080"
    assert captured["connection_mode"] == "http_only"


def test_signal_account_rejects_service_url_with_path(monkeypatch, tmp_path) -> None:
    fake_signalbot = SimpleNamespace(
        Config=lambda **kwargs: kwargs,
        SignalBot=lambda _config: None,
        api=SimpleNamespace(ConnectionMode=SimpleNamespace(HTTP_ONLY="http_only", HTTPS_ONLY="https_only")),
    )
    monkeypatch.setattr("TeeBotus.runtime.signal_runner._import_signalbot", lambda: fake_signalbot)

    try:
        run_signal_account(
            account=AccountRunConfig(
                instance_name="Demo",
                channel="signal",
                slot=1,
                label="signal:1",
                openai_api_key="",
                signal_service="http://127.0.0.1:8080/api",
                signal_phone_number="+491234",
            ),
            instances_dir=tmp_path,
        )
    except SignalRuntimeError as exc:
        assert "darf keinen Pfad" in str(exc)
    else:
        raise AssertionError("SignalRuntimeError was not raised")


def test_signal_service_health_uses_normalized_host_port(monkeypatch) -> None:
    calls: list[tuple[tuple[str, int], float]] = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    def fake_create_connection(address, timeout):
        calls.append((address, timeout))
        return FakeSocket()

    monkeypatch.setattr("TeeBotus.runtime.signal_runner.socket.create_connection", fake_create_connection)

    health = check_signal_service(
        AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        timeout_seconds=0.25,
    )

    assert health.ok
    assert health.target == "127.0.0.1:8080"
    assert calls == [(("127.0.0.1", 8080), 0.25)]


def test_signal_service_health_reports_unreachable_service(monkeypatch) -> None:
    def fake_create_connection(_address, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr("TeeBotus.runtime.signal_runner.socket.create_connection", fake_create_connection)

    health = check_signal_service(
        AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        )
    )

    assert not health.ok
    assert health.target == "127.0.0.1:8080"
    assert "connection refused" in health.error
