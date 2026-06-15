from __future__ import annotations

from datetime import datetime, timezone

from TeeBotus.proactive import main, run_proactive_agent_dry_run
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
    assert "Use --dry-run" in captured.err
