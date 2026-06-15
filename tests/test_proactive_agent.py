from __future__ import annotations

from datetime import datetime, timezone

from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key, telegram_identity_key
from TeeBotus.runtime.proactive_agent import (
    disable_proactive_agent,
    enable_proactive_agent,
    proactive_policy_decision,
    queue_proactive_message,
    select_proactive_route,
)


def store(tmp_path) -> AccountStore:
    return AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"p" * 32))


def test_proactive_policy_denies_without_explicit_consent(tmp_path) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(telegram_identity_key(1))
    account_store.update_identity_route(telegram_identity_key(1), channel="telegram", chat_id="1", chat_type="private", adapter_slot=1)

    decision = proactive_policy_decision(
        account_store,
        account_id,
        category="reminder",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert decision.allowed is False
    assert decision.reason == "proactive_disabled"
    assert account_store.read_proactive_outbox(account_id) == []


def test_proactive_message_is_queued_only_after_consent_and_private_route(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))

    decision = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up_homework",
        message_text="Du wolltest heute kurz rausgehen. Magst du mir sagen, ob es geklappt hat?",
        reason_memory_ids=("mem_homework",),
        due_at="2026-06-16T10:00:00+00:00",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert decision.allowed is True
    assert decision.reason.startswith("queued:pro_")
    outbox = account_store.read_proactive_outbox(account_id)
    assert len(outbox) == 1
    assert outbox[0]["category"] == "reminder"
    assert outbox[0]["intent"] == "follow_up_homework"
    assert outbox[0]["reason_memory_ids"] == ["mem_homework"]
    assert outbox[0]["route"]["channel"] == "signal"
    raw_outbox = (account_store.account_dir(account_id) / "Proactive_Outbox.jsonl").read_text(encoding="utf-8")
    assert "Du wolltest heute" not in raw_outbox
    assert "TMBMAP1" in raw_outbox


def test_proactive_policy_denies_non_consented_category_and_group_route(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="-100", chat_type="group", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))

    wrong_category = proactive_policy_decision(
        account_store,
        account_id,
        category="analysis",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )
    reminder = proactive_policy_decision(
        account_store,
        account_id,
        category="reminder",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert wrong_category.allowed is False
    assert wrong_category.reason == "category_not_consented"
    assert reminder.allowed is False
    assert reminder.reason == "no_private_route"
    assert select_proactive_route(account_store, account_id) is None


def test_disabling_proactive_agent_blocks_future_queueing(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id)
    disable_proactive_agent(account_store, account_id)

    decision = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Ping",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert decision.allowed is False
    assert decision.reason == "proactive_disabled"
    assert account_store.read_proactive_outbox(account_id) == []
