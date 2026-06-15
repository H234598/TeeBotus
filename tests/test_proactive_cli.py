from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from TeeBotus.proactive import main, run_proactive_agent_cycle, run_proactive_agent_dry_run, runtime_llm_planner_factory
from TeeBotus.runtime.actions import SendText
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key
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


def test_proactive_cli_dispatch_requires_runtime_sender_registry(tmp_path, capsys) -> None:
    result = main(["--instances-dir", str(tmp_path / "instances"), "--dispatch"])

    captured = capsys.readouterr()
    assert result == 2
    assert "requires a runtime-provided sender registry" in captured.err


def test_proactive_cli_llm_plan_requires_explicit_plan(capsys) -> None:
    result = main(["--dry-run", "--llm-plan"])

    captured = capsys.readouterr()
    assert result == 2
    assert "--llm-plan requires --plan" in captured.err


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
    assert len(account["planning"]["created_memory_ids"]) == 1
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
