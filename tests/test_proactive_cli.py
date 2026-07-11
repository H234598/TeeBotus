from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from unittest.mock import patch

from TeeBotus.proactive import (
    ProactiveRoleLLMClient,
    main,
    resolve_proactive_role_llm_settings,
    resolve_proactive_role_openai_key,
    run_proactive_agent_cycle,
    run_proactive_agent_dry_run,
    runtime_proactive_role_llm_factory,
    runtime_llm_planner_factory,
    runtime_sender_factory,
)
from TeeBotus.runtime.actions import SendAttachment, SendText
from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, StaticSecretProvider, signal_identity_key
from TeeBotus.runtime.proactive_agent import claim_proactive_worker_job, enable_proactive_agent, queue_proactive_message


def store_for(instance_dir) -> AccountStore:
    return AccountStore(instance_dir / "data" / "accounts", instance_dir.name, StaticSecretProvider(b"p" * 32))


def test_proactive_dry_run_skips_instance_when_not_enabled(tmp_path) -> None:
    instance_dir = tmp_path / "instances" / "NeueInstanz"
    (instance_dir / "data" / "accounts").mkdir(parents=True)
    called = False

    def factory(*_args):
        nonlocal called
        called = True
        raise AssertionError("disabled instance should not open account store")

    report = run_proactive_agent_dry_run(
        instances_dir=tmp_path / "instances",
        selected_instances=("NeueInstanz",),
        env={},
        store_factory=factory,
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert report["ok"] is True
    assert called is False
    assert report["instances"][0]["enabled"] is False
    assert report["instances"][0]["skipped_reason"] == "instance_not_enabled"


def test_proactive_dry_run_reports_due_items_for_enabled_instance(tmp_path) -> None:
    instance_dir = tmp_path / "instances" / "Depressionsbot"
    account_store = store_for(instance_dir)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Magst du kurz berichten?",
        due_at="2026-06-15T11:00:00+00:00",
        now=datetime(2026, 6, 15, 10, tzinfo=timezone.utc),
    )
    assert queued.allowed is True

    report = run_proactive_agent_dry_run(
        instances_dir=tmp_path / "instances",
        selected_instances=("Depressionsbot",),
        env={"TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot"},
        store_factory=lambda _root, _instance: account_store,
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    account = report["instances"][0]["accounts"][0]
    assert account["account_id"] == account_id
    assert len(account["due_items"]) == 1
    assert account["due_items"][0]["intent"] == "follow_up"
    assert account["due_items"][0]["policy_allowed"] is True
    assert account_store.read_proactive_outbox(account_id)[0]["status"] == "queued"


def test_proactive_dry_run_reports_stale_stored_route_as_blocked(tmp_path) -> None:
    instance_dir = tmp_path / "instances" / "Depressionsbot"
    account_store = store_for(instance_dir)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Magst du kurz berichten?",
        due_at="2026-06-15T11:00:00+00:00",
        now=datetime(2026, 6, 15, 10, tzinfo=timezone.utc),
    )
    assert queued.allowed is True
    account_store.update_identity_route(identity, channel="signal", chat_id="+492", chat_type="private", adapter_slot=1)

    report = run_proactive_agent_dry_run(
        instances_dir=tmp_path / "instances",
        selected_instances=("Depressionsbot",),
        env={"TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot"},
        store_factory=lambda _root, _instance: account_store,
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    item = report["instances"][0]["accounts"][0]["due_items"][0]
    assert item["policy_allowed"] is False
    assert item["policy_reason"] == "stale_route"
    assert item["route"]["chat_id"] == "+491"


def test_proactive_cli_requires_dry_run_for_now(tmp_path, capsys) -> None:
    result = main(["--instances-dir", str(tmp_path / "instances")])

    captured = capsys.readouterr()
    assert result == 2
    assert "Use exactly one of --dry-run or --dispatch" in captured.err


def test_proactive_main_loads_runtime_environment_before_configuring_logging(tmp_path) -> None:
    import TeeBotus.proactive as proactive_module

    events: list[str] = []
    recorded: dict[str, object] = {}
    original_level = os.environ.get("TEEBOTUS_LOG_LEVEL")

    def fake_load_project_dotenv_for_instances(path, *, environ=None) -> None:
        events.append(f"load:{path}")
        os.environ["TEEBOTUS_LOG_LEVEL"] = "debug_all"

    def fake_load_runtime_config_defaults(path) -> None:
        events.append(f"defaults:{path}")

    def fake_configure_runtime_logging(*, level, tee_stdio) -> None:
        events.append("configure")
        recorded["level"] = level
        recorded["tee_stdio"] = tee_stdio

    with (
        patch("TeeBotus.proactive.load_project_dotenv_for_instances", side_effect=fake_load_project_dotenv_for_instances),
        patch("TeeBotus.proactive._load_runtime_config_defaults", side_effect=fake_load_runtime_config_defaults),
        patch("TeeBotus.proactive.configure_runtime_logging", side_effect=fake_configure_runtime_logging),
        patch(
            "TeeBotus.proactive.run_proactive_agent_cycle",
            return_value={"ok": True, "generated_at": "2026-06-15T12:00:00+00:00", "dispatch": False, "instances": []},
        ),
    ):
        result = proactive_module.main(["--instances-dir", str(tmp_path / "instances"), "--dry-run"])

    if original_level is None:
        os.environ.pop("TEEBOTUS_LOG_LEVEL", None)
    else:
        os.environ["TEEBOTUS_LOG_LEVEL"] = original_level

    assert result == 0
    assert events[0].startswith("load:")
    assert events[1].startswith("defaults:")
    assert events[2] == "configure"
    assert recorded["level"] == "debug_all"
    assert recorded["tee_stdio"] is True


def test_proactive_cli_default_instances_dir_is_project_root_relative(tmp_path, capsys, monkeypatch) -> None:
    import TeeBotus.proactive as proactive_module

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(proactive_module, "PROJECT_ROOT", tmp_path)
    recorded: dict[str, object] = {}

    def fake_load_dotenv(path, *, environ=None) -> None:
        if environ is not None:
            environ["TEEBOTUS_LOG_LEVEL"] = "debug_all"

    def fake_load_runtime_config_defaults(path) -> None:
        return None

    def fake_configure_runtime_logging(*, level, tee_stdio) -> None:
        return None

    def fake_run_proactive_agent_cycle(**kwargs):
        recorded["instances_dir"] = kwargs["instances_dir"]
        return {"ok": True, "generated_at": "2026-06-15T12:00:00+00:00", "dispatch": False, "instances": []}

    with (
        patch("TeeBotus.proactive.load_project_dotenv_for_instances", side_effect=fake_load_dotenv),
        patch("TeeBotus.proactive._load_runtime_config_defaults", side_effect=fake_load_runtime_config_defaults),
        patch("TeeBotus.proactive.configure_runtime_logging", side_effect=fake_configure_runtime_logging),
        patch("TeeBotus.proactive.run_proactive_agent_cycle", side_effect=fake_run_proactive_agent_cycle),
    ):
        result = proactive_module.main(["--dry-run"])

    captured = capsys.readouterr()
    assert result == 0
    assert recorded["instances_dir"] == tmp_path / "instances"
    assert "proactive_dry_run" in captured.out


def test_proactive_cli_uses_instances_dir_to_resolve_project_root(tmp_path, capsys) -> None:
    import TeeBotus.proactive as proactive_module

    custom_repo = tmp_path / "custom-project"
    instances_dir = custom_repo / "instances"
    instances_dir.mkdir(parents=True)
    (custom_repo / ".env").write_text("TEEBOTUS_LOG_LEVEL=debug_all\n", encoding="utf-8")
    (custom_repo / "ALL_BOTS_DEFAULT.md").write_text("## Laufzeitkonfiguration\n\n- LOG_LEVEL: info\n", encoding="utf-8")

    recorded: dict[str, object] = {}

    def fake_load_project_dotenv_for_instances(path, *, environ=None) -> None:
        recorded["dotenv_instances_dir"] = path
        if environ is not None:
            environ["TEEBOTUS_LOG_LEVEL"] = "debug_all"

    def fake_load_runtime_config_defaults(path) -> None:
        recorded["defaults_path"] = path

    def fake_configure_runtime_logging(*, level, tee_stdio) -> None:
        recorded["level"] = level
        recorded["tee_stdio"] = tee_stdio

    def fake_run_proactive_agent_cycle(**kwargs):
        recorded["instances_dir"] = kwargs["instances_dir"]
        return {"ok": True, "generated_at": "2026-06-15T12:00:00+00:00", "dispatch": False, "instances": []}

    with (
        patch("TeeBotus.proactive.load_project_dotenv_for_instances", side_effect=fake_load_project_dotenv_for_instances),
        patch("TeeBotus.proactive._load_runtime_config_defaults", side_effect=fake_load_runtime_config_defaults),
        patch("TeeBotus.proactive.configure_runtime_logging", side_effect=fake_configure_runtime_logging),
        patch("TeeBotus.proactive.run_proactive_agent_cycle", side_effect=fake_run_proactive_agent_cycle),
    ):
        result = proactive_module.main(["--instances-dir", str(instances_dir), "--dry-run"])

    captured = capsys.readouterr()
    assert result == 0
    assert recorded["dotenv_instances_dir"] == instances_dir
    assert recorded["defaults_path"] == custom_repo / "ALL_BOTS_DEFAULT.md"
    assert recorded["level"] == "debug_all"
    assert recorded["tee_stdio"] is True
    assert recorded["instances_dir"] == instances_dir
    assert "proactive_dry_run" in captured.out


def test_proactive_cli_dispatch_can_run_without_injected_sender_registry(tmp_path, capsys) -> None:
    result = main(["--instances-dir", str(tmp_path / "instances"), "--dispatch"])

    captured = capsys.readouterr()
    assert result == 0
    assert "proactive_dispatch" in captured.out


def test_runtime_sender_factory_builds_telegram_sender_from_runtime_config(tmp_path, monkeypatch) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    sent: list[tuple[str, str]] = []

    class API:
        def __init__(self, token: str) -> None:
            self.token = token

        def send_message(self, chat_id: str, text: str) -> str:
            sent.append((chat_id, f"{self.token}:{text}"))
            return "telegram-ref"

    monkeypatch.setattr("TeeBotus.proactive.TelegramAPI", API)
    factory = runtime_sender_factory(
        instances_dir,
        env={
            "TEEBOTUS_INSTANCES": "Depressionsbot",
            "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT": "token-a",
            "TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot",
        },
    )

    senders = factory("Depressionsbot", store_for(instance_dir))
    result = senders["telegram"]({"adapter_slot": 1}, SendText("123", "Ping"), {})

    assert result == "telegram-ref"
    assert sent == [("123", "token-a:Ping")]


def test_runtime_sender_factory_can_limit_sender_channels(tmp_path, monkeypatch) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    instance_dir.mkdir(parents=True)

    class API:
        def __init__(self, token: str) -> None:
            self.token = token

        def send_message(self, chat_id: str, text: str) -> str:
            return f"{self.token}:{chat_id}:{text}"

    def fail_signal_sender(_accounts):
        raise AssertionError("signal sender should not be built for telegram-only factory")

    monkeypatch.setattr("TeeBotus.proactive.TelegramAPI", API)
    monkeypatch.setattr("TeeBotus.proactive._signal_bots_for_accounts", fail_signal_sender)
    factory = runtime_sender_factory(
        instances_dir,
        env={
            "TEEBOTUS_INSTANCES": "Depressionsbot",
            "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT": "token-a",
            "SIGNAL_BOT_SERVICE_DEPRESSIONSBOT": "127.0.0.1:8080",
            "SIGNAL_BOT_PHONE_NUMBER_DEPRESSIONSBOT": "+491",
            "TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot",
        },
        channels=("telegram",),
    )

    senders = factory("Depressionsbot", store_for(instance_dir))

    assert tuple(senders) == ("telegram",)
    assert senders["telegram"]({"adapter_slot": 1}, SendText("123", "Ping"), {}) == "token-a:123:Ping"


def test_runtime_sender_factory_builds_lazy_matrix_sender_from_runtime_config(tmp_path, monkeypatch) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    started: list[tuple[str, str, str]] = []
    sent: list[tuple[str, str, dict[str, object]]] = []

    class FakeNioBot:
        def __init__(self, homeserver: str, user_id: str, *, device_id: str, command_prefix: str, global_message_type: str) -> None:
            self.homeserver = homeserver
            self.user_id = user_id
            self.device_id = device_id
            self.command_prefix = command_prefix
            self.global_message_type = global_message_type
            self.rooms = {}

        async def start(self, *, access_token: str) -> None:
            started.append((self.homeserver, self.user_id, access_token))

        async def send_message(self, room: str, content: str, **kwargs):
            sent.append((room, content, kwargs))
            return type("Response", (), {"event_id": "$matrix-ref"})()

    monkeypatch.setattr("TeeBotus.runtime.matrix_runner._import_niobot", lambda: type("NioBotModule", (), {"NioBot": FakeNioBot})())
    factory = runtime_sender_factory(
        instances_dir,
        env={
            "TEEBOTUS_INSTANCES": "Depressionsbot",
            "MATRIX_BOT_HOMESERVER_DEPRESSIONSBOT": "https://matrix.example",
            "MATRIX_BOT_USER_ID_DEPRESSIONSBOT": "@bot:example",
            "MATRIX_BOT_ACCESS_TOKEN_DEPRESSIONSBOT": "matrix-token",
            "MATRIX_BOT_DEVICE_ID_DEPRESSIONSBOT": "device-a",
            "TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot",
        },
    )

    senders = factory("Depressionsbot", store_for(instance_dir))
    result = asyncio.run(senders["matrix"]({"adapter_slot": 1}, SendText("!room:example", "Ping"), {}))

    assert result == "$matrix-ref"
    assert started == [("https://matrix.example", "@bot:example", "matrix-token")]
    assert sent == [("!room:example", "Ping", {"message_type": "m.text", "clean_mentions": True})]


def test_runtime_sender_factory_matrix_lazy_client_does_not_block_on_forever_start_for_files(tmp_path, monkeypatch) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    uploaded: list[tuple[bytes, dict[str, object]]] = []
    sent: list[dict[str, object]] = []

    class FakeNioBot:
        def __init__(self, homeserver: str, user_id: str, *, device_id: str, command_prefix: str, global_message_type: str) -> None:
            self.rooms: dict[str, object] = {}
            self.listeners: dict[str, list[object]] = {}

        def add_event_listener(self, event_name: str, func) -> None:
            self.listeners.setdefault(event_name, []).append(func)

        async def start(self, *, access_token: str) -> None:
            self.rooms["!room:example"] = type("Room", (), {"encrypted": True})()
            for listener in self.listeners.get("ready", []):
                await listener(object())
            await asyncio.Event().wait()

        async def upload(self, data_provider, **kwargs):
            uploaded.append((data_provider.read(), kwargs))
            return type("Upload", (), {"content_uri": "mxc://example/file"})(), {"key": {"k": "abc"}, "hashes": {"sha256": "hash"}, "iv": "iv"}

        async def room_send(self, **kwargs):
            sent.append(kwargs)
            return type("Response", (), {"event_id": "$matrix-file-ref"})()

    monkeypatch.setattr("TeeBotus.runtime.matrix_runner._import_niobot", lambda: type("NioBotModule", (), {"NioBot": FakeNioBot})())
    factory = runtime_sender_factory(
        instances_dir,
        env={
            "TEEBOTUS_INSTANCES": "Depressionsbot",
            "MATRIX_BOT_HOMESERVER_DEPRESSIONSBOT": "https://matrix.example",
            "MATRIX_BOT_USER_ID_DEPRESSIONSBOT": "@bot:example",
            "MATRIX_BOT_ACCESS_TOKEN_DEPRESSIONSBOT": "matrix-token",
            "TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot",
        },
    )

    senders = factory("Depressionsbot", store_for(instance_dir))
    result = asyncio.run(senders["matrix"]({"adapter_slot": 1}, SendAttachment("!room:example", b"data", "note.txt", "text/plain"), {}))

    assert result == "$matrix-file-ref"
    assert uploaded == [(b"data", {"content_type": "text/plain", "filename": "note.txt", "filesize": 4, "encrypt": True})]
    assert "file" in sent[0]["content"]
    assert sent[0]["content"]["file"]["url"] == "mxc://example/file"


def test_runtime_sender_factory_matrix_lazy_client_retries_after_start_failure(tmp_path, monkeypatch) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    sent: list[tuple[str, str]] = []

    class FakeNioBot:
        instances: list["FakeNioBot"] = []

        def __init__(self, homeserver: str, user_id: str, *, device_id: str, command_prefix: str, global_message_type: str) -> None:
            self.rooms: dict[str, object] = {}
            FakeNioBot.instances.append(self)

        async def start(self, *, access_token: str) -> None:
            if len(FakeNioBot.instances) == 1:
                raise RuntimeError("matrix login failed")
            self.rooms["!room:example"] = object()

        async def send_message(self, room: str, content: str, **kwargs):
            sent.append((room, content))
            return type("Response", (), {"event_id": "$matrix-ref"})()

    monkeypatch.setattr("TeeBotus.runtime.matrix_runner._import_niobot", lambda: type("NioBotModule", (), {"NioBot": FakeNioBot})())
    factory = runtime_sender_factory(
        instances_dir,
        env={
            "TEEBOTUS_INSTANCES": "Depressionsbot",
            "MATRIX_BOT_HOMESERVER_DEPRESSIONSBOT": "https://matrix.example",
            "MATRIX_BOT_USER_ID_DEPRESSIONSBOT": "@bot:example",
            "MATRIX_BOT_ACCESS_TOKEN_DEPRESSIONSBOT": "matrix-token",
            "TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot",
        },
    )

    senders = factory("Depressionsbot", store_for(instance_dir))
    try:
        asyncio.run(senders["matrix"]({"adapter_slot": 1}, SendText("!room:example", "Erster Versuch"), {}))
    except RuntimeError as exc:
        assert str(exc) == "matrix login failed"
    else:
        raise AssertionError("first Matrix lazy start should fail")

    result = asyncio.run(senders["matrix"]({"adapter_slot": 1}, SendText("!room:example", "Zweiter Versuch"), {}))

    assert result == "$matrix-ref"
    assert len(FakeNioBot.instances) == 2
    assert sent == [("!room:example", "Zweiter Versuch")]


def test_proactive_cli_llm_plan_requires_explicit_plan(capsys) -> None:
    result = main(["--dry-run", "--llm-plan"])

    captured = capsys.readouterr()
    assert result == 2
    assert "--llm-plan requires --plan" in captured.err


def test_proactive_cli_tool_plan_requires_explicit_plan(capsys) -> None:
    result = main(["--dry-run", "--tool-plan"])

    captured = capsys.readouterr()
    assert result == 2
    assert "--tool-plan requires --plan" in captured.err


def test_proactive_cli_rejects_two_model_planners(capsys) -> None:
    result = main(["--dry-run", "--plan", "--llm-plan", "--tool-plan"])

    captured = capsys.readouterr()
    assert result == 2
    assert "Use only one model planner" in captured.err


def test_proactive_cycle_plan_uses_instance_tool_planner_resolver(tmp_path) -> None:
    instance_dir = tmp_path / "instances" / "Depressionsbot"
    account_store = store_for(instance_dir)
    account_store.resolve_or_create_account(signal_identity_key(source_uuid="signal-user"))

    report = asyncio.run(
        run_proactive_agent_cycle(
            instances_dir=tmp_path / "instances",
            selected_instances=("Depressionsbot",),
            env={"TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot"},
            store_factory=lambda _root, _instance: account_store,
            now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
            plan=True,
            planner_resolver=lambda _instance_dir: "tool",
        )
    )

    account = report["instances"][0]["accounts"][0]
    assert "planning" in account
    assert account["tool_planning"] == {"skipped_reason": "tool_planner_instance_not_enabled"}
    assert "llm_planning" not in account


def test_proactive_cycle_tool_plan_skips_model_when_account_is_idle(tmp_path) -> None:
    class Client:
        def create_tool_calls(self, *_args):
            raise AssertionError("idle proactive accounts must not call the model planner")

    instance_dir = tmp_path / "instances" / "Depressionsbot"
    account_store = store_for(instance_dir)
    account_store.resolve_or_create_account(signal_identity_key(source_uuid="signal-user"))

    report = asyncio.run(
        run_proactive_agent_cycle(
            instances_dir=tmp_path / "instances",
            selected_instances=("Depressionsbot",),
            env={
                "TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot",
                "TEEBOTUS_PROACTIVE_LLM_PLANNER_INSTANCES": "Depressionsbot",
            },
            store_factory=lambda _root, _instance: account_store,
            now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
            tool_plan=True,
            llm_planner_factory=lambda _instance, _store, _account_id: (Client(), "instructions"),
        )
    )

    account = report["instances"][0]["accounts"][0]
    assert account["tool_planning"] == {"skipped_reason": "model_planner_idle:proactive_disabled"}
    assert account["due_items"] == []


def test_proactive_cycle_plan_uses_instance_llm_planner_resolver(tmp_path) -> None:
    instance_dir = tmp_path / "instances" / "Depressionsbot"
    account_store = store_for(instance_dir)
    account_store.resolve_or_create_account(signal_identity_key(source_uuid="signal-user"))

    report = asyncio.run(
        run_proactive_agent_cycle(
            instances_dir=tmp_path / "instances",
            selected_instances=("Depressionsbot",),
            env={"TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot"},
            store_factory=lambda _root, _instance: account_store,
            now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
            plan=True,
            planner_resolver=lambda _instance_dir: "llm",
        )
    )

    account = report["instances"][0]["accounts"][0]
    assert "planning" in account
    assert account["llm_planning"] == {"skipped_reason": "llm_planner_instance_not_enabled"}
    assert "tool_planning" not in account


def test_proactive_cycle_plan_can_disable_model_planner_per_instance(tmp_path) -> None:
    instance_dir = tmp_path / "instances" / "Depressionsbot"
    account_store = store_for(instance_dir)
    account_store.resolve_or_create_account(signal_identity_key(source_uuid="signal-user"))

    report = asyncio.run(
        run_proactive_agent_cycle(
            instances_dir=tmp_path / "instances",
            selected_instances=("Depressionsbot",),
            env={"TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot"},
            store_factory=lambda _root, _instance: account_store,
            now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
            plan=True,
            planner_resolver=lambda _instance_dir: "none",
        )
    )

    account = report["instances"][0]["accounts"][0]
    assert "planning" in account
    assert "llm_planning" not in account
    assert "tool_planning" not in account


def test_proactive_cycle_dispatches_due_items_with_injected_sender(tmp_path) -> None:
    instance_dir = tmp_path / "instances" / "Depressionsbot"
    account_store = store_for(instance_dir)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Magst du kurz berichten?",
        due_at="2026-06-15T11:00:00+00:00",
        now=datetime(2026, 6, 15, 10, tzinfo=timezone.utc),
    )
    calls = []

    def sender(route: dict, action: SendText, item: dict) -> str:
        calls.append((route, action, item))
        return "sent-ref"

    report = asyncio.run(
        run_proactive_agent_cycle(
            instances_dir=tmp_path / "instances",
            selected_instances=("Depressionsbot",),
            env={"TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot"},
            store_factory=lambda _root, _instance: account_store,
            now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
            dispatch=True,
            sender_factory=lambda _instance, _store: {"signal": sender},
        )
    )

    account = report["instances"][0]["accounts"][0]
    assert report["ok"] is True
    assert report["dispatch"] is True
    assert account["dispatch_results"][0]["status"] == "sent"
    assert account["dispatch_results"][0]["message_ref"] == "sent-ref"
    assert calls[0][1] == SendText("+491", "Magst du kurz berichten?", track=True)
    assert account_store.read_proactive_outbox(account_id)[0]["status"] == "sent"
    persisted_results = account_store.read_proactive_dispatch_results(account_id)
    assert persisted_results[0]["item_id"] == account["dispatch_results"][0]["item_id"]
    assert persisted_results[0]["message_ref"] == "sent-ref"
    assert persisted_results[0]["instance"] == "Depressionsbot"


def test_proactive_dispatch_report_includes_recovered_claim_in_due_items(tmp_path) -> None:
    instance_dir = tmp_path / "instances" / "Depressionsbot"
    account_store = store_for(instance_dir)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="crash_recovery_report",
        message_text="Bitte auch im Bericht sichtbar sein",
        due_at="2026-06-15T11:00:00+00:00",
        now=datetime(2026, 6, 15, 10, tzinfo=timezone.utc),
    )
    item_id = queued.reason.removeprefix("queued:")
    assert claim_proactive_worker_job(
        account_store,
        account_id,
        item_id,
        now=datetime(2026, 6, 15, 11, tzinfo=timezone.utc),
    )

    def sender(_route: dict, _action: SendText, _item: dict) -> str:
        return "recovered-ref"

    report = asyncio.run(
        run_proactive_agent_cycle(
            instances_dir=tmp_path / "instances",
            selected_instances=("Depressionsbot",),
            env={"TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot"},
            store_factory=lambda _root, _instance: account_store,
            now=datetime(2026, 6, 15, 11, 31, tzinfo=timezone.utc),
            dispatch=True,
            sender_factory=lambda _instance, _store: {"signal": sender},
        )
    )

    account = report["instances"][0]["accounts"][0]
    assert account["recovered_dispatching_item_ids"] == [item_id]
    assert [item["id"] for item in account["due_items"]] == [item_id]
    assert account["dispatch_results"][0]["status"] == "sent"
    assert account_store.read_proactive_outbox(account_id)[0]["dispatch_attempts"] == 2


def test_proactive_cycle_expires_stale_items_before_due_selection(tmp_path) -> None:
    instance_dir = tmp_path / "instances" / "Depressionsbot"
    account_store = store_for(instance_dir)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    state = enable_proactive_agent(account_store, account_id, categories=("reminder",))
    state["policy"]["expire_queued_after_days"] = 7
    account_store.write_agent_state(account_id, state)
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="old",
        message_text="Old",
        due_at="2026-06-01T12:00:00+00:00",
        now=datetime(2026, 6, 1, 10, tzinfo=timezone.utc),
    )

    report = asyncio.run(
        run_proactive_agent_cycle(
            instances_dir=tmp_path / "instances",
            selected_instances=("Depressionsbot",),
            env={"TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot"},
            store_factory=lambda _root, _instance: account_store,
            now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
        )
    )

    account = report["instances"][0]["accounts"][0]
    assert account["expired_item_ids"] == [queued.reason.removeprefix("queued:")]
    assert account["due_items"] == []
    assert account_store.read_proactive_outbox(account_id)[0]["status"] == "expired"


def test_proactive_cycle_dispatch_requires_sender_factory(tmp_path) -> None:
    try:
        asyncio.run(run_proactive_agent_cycle(instances_dir=tmp_path, dispatch=True))
    except ValueError as exc:
        assert "sender_factory is required" in str(exc)
    else:
        raise AssertionError("dispatch without sender_factory should fail")


def test_proactive_cycle_reports_account_store_errors_without_crashing(tmp_path) -> None:
    instance_dir = tmp_path / "instances" / "Depressionsbot"
    account_dir = instance_dir / "data" / "accounts" / "accounts" / ("a" * 128)
    account_dir.mkdir(parents=True)

    class BrokenStore:
        accounts_dir = instance_dir / "data" / "accounts" / "accounts"

        def read_agent_state(self, _account_id: str) -> dict:
            raise AccountStoreError("boom")

        def read_proactive_outbox(self, _account_id: str) -> list:
            return []

    report = asyncio.run(
        run_proactive_agent_cycle(
            instances_dir=tmp_path / "instances",
            selected_instances=("Depressionsbot",),
            env={"TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot"},
            store_factory=lambda _root, _instance: BrokenStore(),
            now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
        )
    )

    account = report["instances"][0]["accounts"][0]
    assert report["ok"] is False
    assert account["account_id"] == "a" * 128
    assert "AccountStoreError: boom" in account["error"]


def test_proactive_cycle_can_run_local_planner_before_due_selection(tmp_path) -> None:
    instance_dir = tmp_path / "instances" / "Depressionsbot"
    account_store = store_for(instance_dir)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    account_store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_goal",
            "kind": "therapy_goal",
            "user_text": "Diese Woche zweimal zehn Minuten spazieren gehen.",
            "created_at": "2026-06-15T08:00:00+00:00",
            "updated_at": "2026-06-15T08:00:00+00:00",
        },
    )

    report = asyncio.run(
        run_proactive_agent_cycle(
            instances_dir=tmp_path / "instances",
            selected_instances=("Depressionsbot",),
            env={"TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot"},
            store_factory=lambda _root, _instance: account_store,
            now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
            plan=True,
        )
    )

    account = report["instances"][0]["accounts"][0]
    assert len(account["planning"]["created_memory_ids"]) == 9
    assert len(account["planning"]["queued_item_ids"]) == 1
    assert account["due_items"] == []
    assert account_store.read_proactive_outbox(account_id)[0]["due_at"] == "2026-06-16T10:00:00+00:00"


def test_proactive_cycle_llm_plan_requires_planner_factory(tmp_path) -> None:
    try:
        asyncio.run(run_proactive_agent_cycle(instances_dir=tmp_path, llm_plan=True))
    except ValueError as exc:
        assert "llm_planner_factory is required" in str(exc)
    else:
        raise AssertionError("llm_plan without llm_planner_factory should fail")


def test_proactive_cycle_tool_plan_requires_planner_factory(tmp_path) -> None:
    try:
        asyncio.run(run_proactive_agent_cycle(instances_dir=tmp_path, tool_plan=True))
    except ValueError as exc:
        assert "llm_planner_factory is required" in str(exc)
    else:
        raise AssertionError("tool_plan without llm_planner_factory should fail")


def test_proactive_cycle_rejects_llm_and_tool_plan_together(tmp_path) -> None:
    try:
        asyncio.run(
            run_proactive_agent_cycle(
                instances_dir=tmp_path,
                llm_plan=True,
                tool_plan=True,
                llm_planner_factory=lambda _instance, _store, _account_id: None,
            )
        )
    except ValueError as exc:
        assert "mutually exclusive" in str(exc)
    else:
        raise AssertionError("llm_plan and tool_plan should be mutually exclusive")


def test_proactive_cycle_llm_plan_respects_separate_instance_gate(tmp_path) -> None:
    instance_dir = tmp_path / "instances" / "Depressionsbot"
    account_store = store_for(instance_dir)
    account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="signal-user"))

    report = asyncio.run(
        run_proactive_agent_cycle(
            instances_dir=tmp_path / "instances",
            selected_instances=("Depressionsbot",),
            env={"TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot"},
            store_factory=lambda _root, _instance: account_store,
            now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
            llm_plan=True,
            llm_planner_factory=lambda *_args: (_ for _ in ()).throw(AssertionError("LLM planner must not run without gate")),
        )
    )

    account = report["instances"][0]["accounts"][0]
    assert account["account_id"] == account_id
    assert account["llm_planning"] == {"skipped_reason": "llm_planner_instance_not_enabled"}


def test_proactive_cycle_llm_plan_reports_plan_role_when_context_is_unavailable(tmp_path) -> None:
    instance_dir = tmp_path / "instances" / "Depressionsbot"
    account_store = store_for(instance_dir)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_goal", "kind": "therapy_goal", "user_text": "Spazieren gehen."},
    )

    report = asyncio.run(
        run_proactive_agent_cycle(
            instances_dir=tmp_path / "instances",
            selected_instances=("Depressionsbot",),
            env={
                "TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot",
                "TEEBOTUS_PROACTIVE_LLM_PLANNER_INSTANCES": "Depressionsbot",
            },
            store_factory=lambda _root, _instance: account_store,
            now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
            llm_plan=True,
            llm_planner_factory=lambda _instance, _store, _account_id: None,
        )
    )

    account = report["instances"][0]["accounts"][0]
    assert account["llm_planning"] == {"llm_role": "plan", "openai_role": "plan", "skipped_reason": "llm_planner_unavailable"}


def test_proactive_cycle_llm_plan_uses_injected_client_when_gate_is_enabled(tmp_path) -> None:
    class Response:
        text = '{"schema_version":1,"decisions":[{"action":"queue","category":"reminder","intent":"llm_cycle_follow_up","message_text":"Magst du kurz berichten, ob du weiterarbeiten moechtest?","reason_memory_ids":["mem_goal"],"risk_gate":"none","due_at":"2026-06-15T11:30:00+00:00"}]}'

    class Client:
        def __init__(self) -> None:
            self.calls = 0

        def create_reply(self, prompt, instructions):
            self.calls += 1
            assert instructions == "instructions"
            assert "mem_goal" in prompt
            return Response()

    instance_dir = tmp_path / "instances" / "Depressionsbot"
    account_store = store_for(instance_dir)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_goal", "kind": "therapy_goal", "user_text": "Spazieren gehen."},
    )
    client = Client()

    report = asyncio.run(
        run_proactive_agent_cycle(
            instances_dir=tmp_path / "instances",
            selected_instances=("Depressionsbot",),
            env={
                "TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot",
                "TEEBOTUS_PROACTIVE_LLM_PLANNER_INSTANCES": "Depressionsbot",
            },
            store_factory=lambda _root, _instance: account_store,
            now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
            llm_plan=True,
            llm_planner_factory=lambda _instance, _store, _account_id: (client, "instructions"),
        )
    )

    account = report["instances"][0]["accounts"][0]
    assert client.calls == 1
    assert account["llm_planning"]["openai_role"] == "plan"
    assert account["llm_planning"]["errors"] == []
    assert len(account["llm_planning"]["queued_item_ids"]) == 1
    assert account["due_items"][0]["intent"] == "llm_cycle_follow_up"
    assert account_store.read_proactive_outbox(account_id)[0]["planner"]["source"] == "llm"


def test_proactive_cycle_tool_plan_uses_injected_client_when_gate_is_enabled(tmp_path) -> None:
    class Client:
        def __init__(self) -> None:
            self.calls = 0

        def create_tool_calls(self, prompt, instructions, tools):
            self.calls += 1
            assert instructions == "instructions"
            assert "mem_goal" in prompt
            assert tools[0]["name"] == "proactive_create_memory"
            return {
                "tool_calls": [
                    {
                        "name": "proactive_queue_message",
                        "arguments": {
                            "category": "reminder",
                            "intent": "tool_cycle_follow_up",
                            "message_text": "Magst du kurz berichten?",
                            "reason_memory_ids": ["mem_goal"],
                            "risk_gate": "none",
                            "due_at": "2026-06-15T11:30:00+00:00",
                        },
                    }
                ]
            }

    instance_dir = tmp_path / "instances" / "Depressionsbot"
    account_store = store_for(instance_dir)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_goal", "kind": "therapy_goal", "user_text": "Spazieren gehen."},
    )
    client = Client()

    report = asyncio.run(
        run_proactive_agent_cycle(
            instances_dir=tmp_path / "instances",
            selected_instances=("Depressionsbot",),
            env={
                "TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot",
                "TEEBOTUS_PROACTIVE_LLM_PLANNER_INSTANCES": "Depressionsbot",
            },
            store_factory=lambda _root, _instance: account_store,
            now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
            tool_plan=True,
            llm_planner_factory=lambda _instance, _store, _account_id: (client, "instructions"),
        )
    )

    account = report["instances"][0]["accounts"][0]
    assert client.calls == 1
    assert account["tool_planning"]["openai_role"] == "plan"
    assert account["tool_planning"]["errors"] == []
    assert len(account["tool_planning"]["queued_item_ids"]) == 1
    assert account["due_items"][0]["intent"] == "tool_cycle_follow_up"
    assert account_store.read_proactive_outbox(account_id)[0]["planner"]["source"] == "llm"


def test_resolve_proactive_role_openai_key_keeps_roles_separate() -> None:
    env = {
        "OPENAI_API_KEY_DEPRESSIONSBOT_PROACTIVE_PLAN": "sk-plan",
        "OPENAI_API_KEY_DEPRESSIONSBOT_PROACTIVE_DECISION": "sk-decision",
        "OPENAI_API_KEY_DEPRESSIONSBOT_PROACTIVE_WORKER": "sk-worker",
        "OPENAI_API_KEY_DEPRESSIONSBOT_PROACTIVE": "sk-legacy",
    }

    assert resolve_proactive_role_openai_key("Depressionsbot", "plan", env) == "sk-plan"
    assert resolve_proactive_role_openai_key("Depressionsbot", "decision", env) == "sk-decision"
    assert resolve_proactive_role_openai_key("Depressionsbot", "worker", env) == "sk-worker"


def test_resolve_proactive_role_openai_key_allows_shared_proactive_fallback_for_all_roles() -> None:
    env = {
        "OPENAI_API_KEY_DEPRESSIONSBOT_PROACTIVE": "sk-legacy",
        "Depressionsbot_BACKGROUND_SERVICES": "sk-background",
    }

    assert resolve_proactive_role_openai_key("Depressionsbot", "plan", env) == "sk-legacy"
    assert resolve_proactive_role_openai_key("Depressionsbot", "decision", env) == "sk-legacy"
    assert resolve_proactive_role_openai_key("Depressionsbot", "worker", env) == "sk-legacy"


def test_resolve_proactive_role_openai_key_falls_back_to_global_and_background_keys() -> None:
    env = {
        "OPENAI_API_KEY_PROACTIVE": "sk-global-proactive",
        "OPENAI_API_KEY_DEPRESSIONSBOT_BACKGROUND": "sk-background",
        "OPENAI_API_KEY_BACKGROUND": "fixture-global-background-key",
    }

    assert resolve_proactive_role_openai_key("Depressionsbot", "decision", env) == "sk-global-proactive"
    assert resolve_proactive_role_openai_key(
        "Depressionsbot",
        "worker",
        {
            "OPENAI_API_KEY_DEPRESSIONSBOT_BACKGROUND": "sk-background",
            "OPENAI_API_KEY_BACKGROUND": "fixture-global-background-key",
        },
    ) == "sk-background"


def test_resolve_proactive_role_openai_key_rejects_unknown_role() -> None:
    try:
        resolve_proactive_role_openai_key("Depressionsbot", "sender", {})
    except ValueError as exc:
        assert "unsupported proactive LLM role" in str(exc)
    else:
        raise AssertionError("expected unsupported proactive role to fail")


def test_resolve_proactive_role_llm_settings_keeps_role_keys_separate() -> None:
    env = {
        "TEEBOTUS_LLM_PROFILE_DEPRESSIONSBOT_PROACTIVE_PLAN": "gemini_flash_stateful",
        "TEEBOTUS_LLM_API_KEY_DEPRESSIONSBOT_PROACTIVE_PLAN": "plan-key",
        "TEEBOTUS_LLM_PROFILE_DEPRESSIONSBOT_PROACTIVE_DECISION": "groq_fast",
        "TEEBOTUS_LLM_API_KEY_DEPRESSIONSBOT_PROACTIVE_DECISION": "decision-key",
        "TEEBOTUS_LLM_PROVIDER_DEPRESSIONSBOT_PROACTIVE_WORKER": "litellm",
        "TEEBOTUS_LLM_MODEL_DEPRESSIONSBOT_PROACTIVE_WORKER": "anthropic/worker",
        "TEEBOTUS_LLM_API_KEY_DEPRESSIONSBOT_PROACTIVE_WORKER": "worker-key",
    }

    assert resolve_proactive_role_llm_settings("Depressionsbot", "plan", env)["api_key"] == "plan-key"
    assert resolve_proactive_role_llm_settings("Depressionsbot", "decision", env)["profile"] == "groq_fast"
    worker = resolve_proactive_role_llm_settings("Depressionsbot", "worker", env)
    assert worker["provider"] == "litellm"
    assert worker["model"] == "anthropic/worker"
    assert worker["api_key"] == "worker-key"


def test_runtime_proactive_role_llm_factory_builds_non_openai_clients_with_role_keys(tmp_path, monkeypatch) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## OpenAI\n- enabled: true\n", encoding="utf-8")
    calls: list[dict] = []

    class Client:
        provider = "litellm"
        model = "test-model"

        def create_reply(self, _text, _instructions, _previous_response_id=None):
            return '{"schema_version":1,"decisions":[]}'

    def build_client(**kwargs):
        calls.append(kwargs)
        return Client()

    monkeypatch.setattr("TeeBotus.proactive.build_runtime_text_llm_client", build_client)
    env = {
        "TEEBOTUS_LLM_PROVIDER_DEPRESSIONSBOT_PROACTIVE_PLAN": "litellm",
        "TEEBOTUS_LLM_MODEL_DEPRESSIONSBOT_PROACTIVE_PLAN": "groq/plan",
        "TEEBOTUS_LLM_API_KEY_DEPRESSIONSBOT_PROACTIVE_PLAN": "plan-key",
        "TEEBOTUS_LLM_PROVIDER_DEPRESSIONSBOT_PROACTIVE_DECISION": "litellm",
        "TEEBOTUS_LLM_MODEL_DEPRESSIONSBOT_PROACTIVE_DECISION": "groq/decision",
        "TEEBOTUS_LLM_API_KEY_DEPRESSIONSBOT_PROACTIVE_DECISION": "decision-key",
        "TEEBOTUS_LLM_PROVIDER_DEPRESSIONSBOT_PROACTIVE_WORKER": "litellm",
        "TEEBOTUS_LLM_MODEL_DEPRESSIONSBOT_PROACTIVE_WORKER": "groq/worker",
        "TEEBOTUS_LLM_API_KEY_DEPRESSIONSBOT_PROACTIVE_WORKER": "worker-key",
    }

    contexts = {
        role: runtime_proactive_role_llm_factory(instances_dir, role=role, env=env)("Depressionsbot", store_for(instance_dir), "account")
        for role in ("plan", "decision", "worker")
    }

    assert all(context is not None for context in contexts.values())
    assert [call["provider"] for call in calls] == ["litellm", "litellm", "litellm"]
    assert [call["model"] for call in calls] == ["groq/plan", "groq/decision", "groq/worker"]
    assert [call["api_key"] for call in calls] == ["plan-key", "decision-key", "worker-key"]
    assert [call["gemini_key_scope"] for call in calls] == ["proactive_plan", "proactive_decision", "proactive_worker"]
    for role, context in contexts.items():
        assert context is not None
        client, _instructions = context
        assert isinstance(client, ProactiveRoleLLMClient)
        assert client.proactive_role == role


def test_proactive_role_llm_client_uses_text_reply_as_tool_plan_fallback() -> None:
    class TextOnlyClient:
        provider = "litellm"
        model = "groq/test"

        def create_reply(self, user_text, _instructions, _previous_response_id=None):
            assert "Tool-Definitionen nur als Referenz" in user_text
            return type("Response", (), {"text": '{"schema_version":1,"decisions":[]}'})()

    client = ProactiveRoleLLMClient(TextOnlyClient(), role="worker", channel="proactive_worker")

    response = client.create_tool_calls("Prompt", "instructions", [{"name": "proactive_noop"}])

    assert response["text"] == '{"schema_version":1,"decisions":[]}'
    assert response["output"][0]["content"][0]["text"] == '{"schema_version":1,"decisions":[]}'


def test_runtime_llm_planner_factory_uses_proactive_plan_key_and_instance_instructions(tmp_path, monkeypatch) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text(
        "\n".join(
            [
                "## OpenAI",
                "- enabled: true",
                "- model: gpt-test-proactive",
                "- timeout_seconds: 123",
            ]
        ),
        encoding="utf-8",
    )
    created_keys: list[str] = []

    class Client:
        def __init__(self, key: str) -> None:
            created_keys.append(key)

    monkeypatch.setattr("TeeBotus.proactive.OpenAIClient", Client)
    factory = runtime_llm_planner_factory(
        instances_dir,
        env={
            "OPENAI_API_KEY_DEPRESSIONSBOT_PROACTIVE_PLAN": "sk-plan",
            "OPENAI_API_KEY_DEPRESSIONSBOT_PROACTIVE": "sk-proactive",
            "OPENAI_API_KEY_DEPRESSIONSBOT": "sk-instance",
        },
    )

    context = factory("Depressionsbot", store_for(instance_dir), "account")

    assert context is not None
    client, instructions = context
    assert isinstance(client, Client)
    assert created_keys == ["sk-plan"]
    assert instructions.openai_model == "gpt-test-proactive"
    assert instructions.openai_timeout_seconds == 123


def test_runtime_llm_planner_factory_falls_back_to_legacy_proactive_key(tmp_path, monkeypatch) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## OpenAI\n- enabled: true\n", encoding="utf-8")
    created_keys: list[str] = []

    class Client:
        def __init__(self, key: str) -> None:
            created_keys.append(key)

    monkeypatch.setattr("TeeBotus.proactive.OpenAIClient", Client)
    factory = runtime_llm_planner_factory(
        instances_dir,
        env={
            "OPENAI_API_KEY_DEPRESSIONSBOT_PROACTIVE": "sk-proactive",
            "OPENAI_API_KEY_DEPRESSIONSBOT": "sk-instance",
        },
    )

    context = factory("Depressionsbot", store_for(instance_dir), "account")

    assert context is not None
    assert created_keys == ["sk-proactive"]


def test_runtime_llm_planner_factory_uses_plan_services_key_before_background_key(tmp_path, monkeypatch) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## OpenAI\n- enabled: true\n", encoding="utf-8")
    created_keys: list[str] = []

    class Client:
        def __init__(self, key: str) -> None:
            created_keys.append(key)

    monkeypatch.setattr("TeeBotus.proactive.OpenAIClient", Client)
    factory = runtime_llm_planner_factory(
        instances_dir,
        env={
            "Depressionsbot_PROACTIVE_PLAN_SERVICES": "fixture-plan-services-key",
            "Depressionsbot_BACKGROUND_SERVICES": "sk-background",
            "OPENAI_API_KEY_DEPRESSIONSBOT": "sk-instance",
        },
    )

    context = factory("Depressionsbot", store_for(instance_dir), "account")

    assert context is not None
    assert created_keys == ["fixture-plan-services-key"]


def test_runtime_llm_planner_factory_uses_background_key_before_instance_key(tmp_path, monkeypatch) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## OpenAI\n- enabled: true\n", encoding="utf-8")
    created_keys: list[str] = []

    class Client:
        def __init__(self, key: str) -> None:
            created_keys.append(key)

    monkeypatch.setattr("TeeBotus.proactive.OpenAIClient", Client)
    factory = runtime_llm_planner_factory(
        instances_dir,
        env={
            "Depressionsbot_BACKGROUND_SERVICES": "sk-background",
            "OPENAI_API_KEY_DEPRESSIONSBOT": "sk-instance",
        },
    )

    context = factory("Depressionsbot", store_for(instance_dir), "account")

    assert context is not None
    assert created_keys == ["sk-background"]


def test_runtime_llm_planner_factory_returns_none_without_key(tmp_path) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## OpenAI\n- enabled: true\n", encoding="utf-8")
    factory = runtime_llm_planner_factory(instances_dir, env={})

    assert factory("Depressionsbot", store_for(instance_dir), "account") is None
