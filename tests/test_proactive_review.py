from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from TeeBotus.proactive_review import list_proactive_review_items, main, review_proactive_item
from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, StaticSecretProvider, signal_identity_key
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


def test_proactive_review_uses_store_account_ids_when_directory_scan_is_empty(tmp_path: Path, monkeypatch) -> None:
    _instance_dir, store, account_id, item_id = _review_fixture(tmp_path)
    monkeypatch.setattr("TeeBotus.proactive_review._account_dirs", lambda _accounts_dir: [])

    report = list_proactive_review_items(
        instances_dir=tmp_path / "instances",
        selected_instances=("Depressionsbot",),
        store_factory=lambda _root, _instance: store,
    )

    assert report["review_pending_count"] == 1
    assert report["items"][0]["account_id"] == account_id
    assert report["items"][0]["item_id"] == item_id


def test_proactive_review_rejects_unsafe_and_missing_selected_instances(tmp_path: Path) -> None:
    instances_dir = tmp_path / "instances"
    (instances_dir / "Healthy" / "data" / "accounts").mkdir(parents=True)
    calls = []

    def factory(_root, instance_name):
        calls.append(instance_name)
        raise AssertionError("review must not open stores for invalid or missing instances")

    report = list_proactive_review_items(
        instances_dir=instances_dir,
        selected_instances=("../outside", "Missing"),
        store_factory=factory,
    )

    assert report["ok"] is False
    assert report["items"] == []
    assert report["errors"] == [
        "../outside: invalid_instance_name",
        "Missing: selected_instance_not_found",
    ]
    assert calls == []
    assert not (tmp_path / "outside").exists()


def test_proactive_review_does_not_hide_store_account_discovery_errors(tmp_path: Path) -> None:
    instance_dir = tmp_path / "instances" / "Depressionsbot"
    (instance_dir / "data" / "accounts").mkdir(parents=True)

    class BrokenStore:
        accounts_dir = instance_dir / "data" / "accounts" / "accounts"

        def list_account_ids(self, *, include_unresolvable=False):
            assert include_unresolvable is False
            raise AccountStoreError("account index unavailable")

    report = list_proactive_review_items(
        instances_dir=tmp_path / "instances",
        selected_instances=("Depressionsbot",),
        store_factory=lambda _root, _instance: BrokenStore(),
    )

    assert report["ok"] is False
    assert report["review_pending_count"] == 0
    assert report["errors"] == ["Depressionsbot: AccountStoreError: account index unavailable"]


def test_proactive_review_rejects_unsafe_single_instance_without_store_access(tmp_path: Path) -> None:
    called = False

    def factory(*_args):
        nonlocal called
        called = True
        raise AssertionError("unsafe review target must not open a store")

    report = review_proactive_item(
        instances_dir=tmp_path / "instances",
        instance_name="../outside",
        account_id="a" * 128,
        item_id="pro_bad",
        action="approve",
        store_factory=factory,
    )

    assert report["ok"] is False
    assert report["reason"] == "invalid_instance_name"
    assert called is False


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


def test_proactive_review_approve_reports_store_errors(tmp_path: Path) -> None:
    (tmp_path / "instances" / "Depressionsbot" / "data" / "accounts").mkdir(parents=True)

    class BrokenStore:
        def read_proactive_outbox(self, _account_id: str) -> list:
            raise AccountStoreError("encrypted envelope authentication failed")

    report = review_proactive_item(
        instances_dir=tmp_path / "instances",
        instance_name="Depressionsbot",
        account_id="a" * 128,
        item_id="pro_bad",
        action="approve",
        store_factory=lambda _root, _instance: BrokenStore(),  # type: ignore[return-value]
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert report["ok"] is False
    assert report["action"] == "approve"
    assert report["account_id"] == "a" * 128
    assert report["item_id"] == "pro_bad"
    assert report["reason"] == "review_store_error:AccountStoreError: encrypted envelope authentication failed"


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


def test_proactive_review_cli_default_instances_dir_is_repo_root_relative(tmp_path: Path, monkeypatch, capsys) -> None:
    import TeeBotus.proactive_review as proactive_review_module

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(proactive_review_module, "PROJECT_ROOT", tmp_path)
    _instance_dir, store, _account_id, _item_id = _review_fixture(tmp_path)

    result = main(["list", "--instance", "Depressionsbot"], store_factory=lambda _root, _instance: store)

    captured = capsys.readouterr()
    assert result == 0
    assert "review_pending=1" in captured.out


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
