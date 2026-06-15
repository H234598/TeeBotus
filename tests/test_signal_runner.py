from __future__ import annotations

import asyncio
from types import SimpleNamespace

from signalbot.message import MessageType

from TeeBotus.runtime.accounts import StaticSecretProvider
from TeeBotus.runtime.actions import ExportFile
from TeeBotus.runtime.config import AccountRunConfig, InstanceRunConfig, RuntimeConfig
from TeeBotus.runtime.message_tracking import SentMessageRef
from TeeBotus.runtime.signal_runner import (
    SignalRuntimeError,
    check_signal_accounts,
    SignalServiceHealth,
    TeeBotusSignalCommand,
    check_signal_service,
    ensure_signal_services_available,
    _patch_signalbot_signal_cli_api_about,
    _pid_file_process_is_running,
    _require_signal_cli_api_accounts_registered,
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
    monkeypatch.setattr("TeeBotus.runtime.signal_runner._start_local_signal_backend_if_possible", lambda _account: None)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.run_signal_account", lambda **_kwargs: calls.append("started"))

    try:
        run_signal_accounts(config)
    except SignalRuntimeError as exc:
        assert "signal-cli-api nicht erreichbar" in str(exc)
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

    def fake_popen(command, **_kwargs):
        commands.append(command)
        service_up["value"] = True
        return FakeProcess()

    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_services", fake_check_signal_services)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_service", fake_check_signal_service)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.runtime_dir", lambda: tmp_path / "runtime")
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.subprocess.Popen", fake_popen)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.shutil.which", lambda _binary: "signal-cli-api")

    ensure_signal_services_available(config)

    assert commands == [["signal-cli-api", "--listen", "127.0.0.1:8080"]]
    assert (tmp_path / "runtime" / "signal-cli-api-Demo-1.pid").read_text(encoding="utf-8") == "4321\n"


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

    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_services", fake_check_signal_services)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_service", fake_check_signal_service)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.runtime_dir", lambda: tmp_path / "runtime")
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.subprocess.Popen", fake_popen)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.shutil.which", lambda _binary: "signal-cli-api")

    ensure_signal_services_available(config)

    assert commands == [["signal-cli-api", "--listen", "127.0.0.1:8080"]]


def test_signalbot_patch_accepts_signal_cli_api_about_shape() -> None:
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
    assert asyncio.run(api.get_signal_cli_rest_api_version()) == "unset"
    assert asyncio.run(api.get_signal_cli_rest_api_mode()) == "json-rpc"


def test_signal_pid_check_rejects_dead_process(monkeypatch, tmp_path) -> None:
    pid_file = tmp_path / "signal-cli-api.pid"
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
    assert health[1].error == "account missing in signal-cli-api /v1/accounts"


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
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
    )

    assert captured["signal_service"] == "127.0.0.1:8080"
    assert captured["connection_mode"] == "http_only"
    assert captured["storage"] == "memory-storage"


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
