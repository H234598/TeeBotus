from __future__ import annotations

import asyncio
from types import SimpleNamespace

from TeeBotus.runtime.accounts import StaticSecretProvider
from TeeBotus.runtime.config import AccountRunConfig, InstanceRunConfig, RuntimeConfig
from TeeBotus.runtime.message_tracking import SentMessageRef
from TeeBotus.runtime.signal_runner import (
    SignalRuntimeError,
    SignalServiceHealth,
    TeeBotusSignalCommand,
    check_signal_service,
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

    def recipient(self) -> str:
        return self.source


class FakeSignalContext:
    def __init__(self) -> None:
        self.message = FakeSignalMessage()
        self.sent: list[str] = []
        self.deleted: list[int] = []

    async def send(self, text: str, **_kwargs) -> int:
        self.sent.append(text)
        return 987654

    async def start_typing(self) -> None:
        return None

    async def remote_delete(self, timestamp: int) -> int:
        self.deleted.append(timestamp)
        return timestamp


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
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.run_signal_account", lambda **_kwargs: calls.append("started"))

    try:
        run_signal_accounts(config)
    except SignalRuntimeError as exc:
        assert "signal-cli-rest-api nicht erreichbar" in str(exc)
    else:
        raise AssertionError("SignalRuntimeError was not raised")
    assert calls == []


def test_signal_account_normalizes_documented_http_service_url(monkeypatch, tmp_path) -> None:
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
            signal_service="http://127.0.0.1:8080",
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
