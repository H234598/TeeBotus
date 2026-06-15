from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from TeeBotus.proactive import main, run_proactive_agent_cycle, run_proactive_agent_dry_run, runtime_llm_planner_factory, runtime_sender_factory
from TeeBotus.runtime.actions import SendAttachment, SendText
from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, StaticSecretProvider, signal_identity_key
from TeeBotus.runtime.proactive_agent import enable_proactive_agent, queue_proactive_message


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


def test_proactive_cli_requires_dry_run_for_now(tmp_path, capsys) -> None:
    result = main(["--instances-dir", str(tmp_path / "instances")])

    captured = capsys.readouterr()
    assert result == 2
    assert "Use exactly one of --dry-run or --dispatch" in captured.err


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
    assert report["ok"] is True
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
    assert account["tool_planning"]["errors"] == []
    assert len(account["tool_planning"]["queued_item_ids"]) == 1
    assert account["due_items"][0]["intent"] == "tool_cycle_follow_up"
    assert account_store.read_proactive_outbox(account_id)[0]["planner"]["source"] == "llm"


def test_runtime_llm_planner_factory_uses_proactive_key_and_instance_instructions(tmp_path, monkeypatch) -> None:
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
            "OPENAI_API_KEY_DEPRESSIONSBOT_PROACTIVE": "sk-proactive",
            "OPENAI_API_KEY_DEPRESSIONSBOT": "sk-instance",
        },
    )

    context = factory("Depressionsbot", store_for(instance_dir), "account")

    assert context is not None
    client, instructions = context
    assert isinstance(client, Client)
    assert created_keys == ["sk-proactive"]
    assert instructions.openai_model == "gpt-test-proactive"
    assert instructions.openai_timeout_seconds == 123


def test_runtime_llm_planner_factory_returns_none_without_key(tmp_path) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## OpenAI\n- enabled: true\n", encoding="utf-8")
    factory = runtime_llm_planner_factory(instances_dir, env={})

    assert factory("Depressionsbot", store_for(instance_dir), "account") is None
