from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from TeeBotus.proactive_review import list_proactive_review_items, main, review_proactive_item
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key
from TeeBotus.runtime.proactive_agent import enable_proactive_agent, queue_proactive_message


def test_proactive_review_lists_pending_items(tmp_path: Path) -> None:
    instance_dir, store, account_id, item_id = _review_fixture(tmp_path)

    report = list_proactive_review_items(
        instances_dir=tmp_path / "instances",
        selected_instances=("Depressionsbot",),
        store_factory=lambda _root, _instance: store,
    )

    assert report["ok"] is True
    assert report["review_pending_count"] == 1
    assert report["items"][0]["instance"] == instance_dir.name
    assert report["items"][0]["account_id"] == account_id
    assert report["items"][0]["item_id"] == item_id
    assert report["items"][0]["risk_gate"] == "needs_review"
    assert report["items"][0]["route"]["channel"] == "signal"


def test_proactive_review_approve_queues_item(tmp_path: Path) -> None:
    _instance_dir, store, account_id, item_id = _review_fixture(tmp_path)

    report = review_proactive_item(
        instances_dir=tmp_path / "instances",
        instance_name="Depressionsbot",
        account_id=account_id,
        item_id=item_id,
        action="approve",
        reviewer="tester",
        reason="geprueft",
        store_factory=lambda _root, _instance: store,
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    row = store.read_proactive_outbox(account_id)[0]
    assert report["ok"] is True
    assert report["reason"] == f"queued:{item_id}"
    assert row["status"] == "queued"
    assert row["risk_gate"] == "none"
    assert row["human_review"]["reviewer"] == "tester"
    assert row["human_review"]["reason"] == "geprueft"


def test_proactive_review_reject_cancels_item(tmp_path: Path) -> None:
    _instance_dir, store, account_id, item_id = _review_fixture(tmp_path)

    report = review_proactive_item(
        instances_dir=tmp_path / "instances",
        instance_name="Depressionsbot",
        account_id=account_id,
        item_id=item_id,
        action="reject",
        reviewer="tester",
        reason="zu riskant",
        store_factory=lambda _root, _instance: store,
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    row = store.read_proactive_outbox(account_id)[0]
    assert report["ok"] is True
    assert report["reason"] == f"cancelled:{item_id}"
    assert row["status"] == "cancelled"
    assert row["human_review"]["status"] == "rejected"
    assert row["human_review"]["reason"] == "zu riskant"


def test_proactive_review_cli_prints_json(tmp_path: Path, capsys) -> None:
    _instance_dir, store, _account_id, item_id = _review_fixture(tmp_path)

    result = main(
        ["--instances-dir", str(tmp_path / "instances"), "--json", "list", "--instance", "Depressionsbot"],
        store_factory=lambda _root, _instance: store,
    )

    captured = capsys.readouterr()
    assert result == 0
    assert '"review_pending_count": 1' in captured.out
    assert item_id in captured.out


def _review_fixture(tmp_path: Path) -> tuple[Path, AccountStore, str, str]:
    instance_dir = tmp_path / "instances" / "Depressionsbot"
    store = AccountStore(instance_dir / "data" / "accounts", instance_dir.name, StaticSecretProvider(b"p" * 32))
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = store.resolve_or_create_account(identity)
    store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(store, account_id, categories=("reminder",))
    decision = queue_proactive_message(
        store,
        account_id,
        category="reminder",
        intent="review_follow_up",
        message_text="Magst du kurz berichten?",
        reason_memory_ids=("mem_goal",),
        risk_gate="needs_review",
        due_at="2026-06-15T12:00:00+00:00",
        now=datetime(2026, 6, 15, 10, tzinfo=timezone.utc),
    )
    item_id = decision.reason.removeprefix("review_pending:")
    return instance_dir, store, account_id, item_id
