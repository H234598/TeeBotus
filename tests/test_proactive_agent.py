from __future__ import annotations

from datetime import datetime, timezone

from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key, telegram_identity_key
from TeeBotus.runtime.proactive_agent import (
    check_proactive_agent_account,
    disable_proactive_agent,
    due_proactive_outbox_items,
    enable_proactive_agent,
    proactive_agent_instance_enabled,
    proactive_policy_decision,
    queue_proactive_message,
    select_proactive_route,
    update_proactive_outbox_item_status,
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


def test_proactive_agent_instance_is_default_off_and_can_be_enabled_by_env() -> None:
    assert proactive_agent_instance_enabled("Neue_Instanz", env={}) is False
    assert proactive_agent_instance_enabled(
        "Depressionsbot",
        env={"TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot"},
    ) is True
    assert proactive_agent_instance_enabled(
        "Depressionsbot",
        env={"TEEBOTUS_PROACTIVE_AGENT_DEPRESSIONSBOT": "1"},
    ) is True


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


def test_due_proactive_outbox_items_filters_future_and_terminal_items(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id)
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    past = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="past",
        message_text="Past",
        due_at="2026-06-15T11:00:00+00:00",
        now=now,
    )
    future = queue_proactive_message(
        account_store,
        account_id,
        category="task",
        intent="future",
        message_text="Future",
        due_at="2026-06-15T13:00:00+00:00",
        now=now,
    )
    assert past.allowed is True
    assert future.allowed is True
    past_id = past.reason.removeprefix("queued:")
    assert update_proactive_outbox_item_status(account_store, account_id, past_id, status="skipped", reason="test", now=now)

    due = due_proactive_outbox_items(account_store, account_id, now=now)

    assert due == ()
    assert due_proactive_outbox_items(account_store, account_id, now=datetime(2026, 6, 15, 14, tzinfo=timezone.utc))[0]["intent"] == "future"


def test_proactive_policy_enforces_daily_limit(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    state = enable_proactive_agent(account_store, account_id, categories=("reminder",))
    state["policy"]["max_messages_per_day"] = 1
    account_store.write_agent_state(account_id, state)
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    first = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="first",
        message_text="First",
        due_at="2026-06-15T12:30:00+00:00",
        now=now,
    )

    second = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="second",
        message_text="Second",
        due_at="2026-06-15T13:30:00+00:00",
        now=now,
    )

    assert first.allowed is True
    assert second.allowed is False
    assert second.reason == "daily_limit_reached"


def test_proactive_agent_health_reports_invalid_queued_items(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    account_store.write_proactive_outbox(
        account_id,
        [
            {
                "id": "pro_bad",
                "status": "queued",
                "category": "analysis",
                "intent": "",
                "message_text": "",
                "due_at": "not-a-date",
                "route": {"channel": "telegram", "chat_id": "-100", "chat_type": "group"},
            }
        ],
    )

    health = check_proactive_agent_account(account_store, account_id)

    assert health.ok is False
    joined = "\n".join(health.errors)
    assert "category is not consented: analysis" in joined
    assert "missing intent" in joined
    assert "missing message_text" in joined
    assert "invalid due_at" in joined
    assert "route is not private" in joined


def test_proactive_agent_health_accepts_valid_queued_item(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    decision = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Magst du kurz berichten?",
        due_at="2026-06-15T12:30:00+00:00",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    health = check_proactive_agent_account(account_store, account_id)

    assert decision.allowed is True
    assert health.ok is True
    assert health.errors == ()
