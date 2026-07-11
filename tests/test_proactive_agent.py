from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, StaticSecretProvider, matrix_identity_key, signal_identity_key, telegram_identity_key
from TeeBotus.runtime.actions import SendAttachment, SendText
from TeeBotus.runtime.message_tracking import MessageTracker
from TeeBotus.runtime.proactive_agent import (
    active_proactive_risk_memory_ids,
    apply_proactive_agent_tool_calls,
    apply_proactive_llm_plan,
    apply_proactive_llm_plan_text,
    approve_proactive_review_item,
    build_proactive_llm_planner_prompt,
    extract_proactive_agent_tool_calls,
    check_proactive_agent_account,
    claim_proactive_worker_job,
    disable_proactive_agent,
    dispatch_due_proactive_outbox_items,
    due_proactive_outbox_items,
    enable_proactive_agent,
    expire_stale_proactive_outbox_items,
    pause_proactive_agent,
    proactive_agent_instance_enabled,
    proactive_status_text,
    proactive_policy_decision,
    queue_proactive_message,
    recover_stale_proactive_dispatching_items,
    reject_proactive_review_item,
    resume_proactive_agent,
    run_proactive_tool_agent,
    run_proactive_llm_planner,
    run_proactive_reflection_planner,
    select_proactive_route,
    should_run_proactive_model_planner,
    set_proactive_allowed_hours,
    set_proactive_categories,
    set_proactive_min_interval_minutes,
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


def test_proactive_state_string_booleans_do_not_enable_agent(tmp_path) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(telegram_identity_key(1))
    account_store.write_agent_state(
        account_id,
        {"proactive": {"enabled": "false", "paused": "0"}, "consent": {"categories": ["reminder"]}},
    )

    assert "- aktiviert: nein" in proactive_status_text(account_store, account_id)
    decision = proactive_policy_decision(
        account_store,
        account_id,
        category="reminder",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )
    assert decision.reason == "proactive_disabled"


def test_string_false_cannot_bypass_proactive_time_policy(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="1", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    now = datetime(2026, 6, 15, 22, tzinfo=timezone.utc)

    denied = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="user_requested_reminder",
        message_text="Nicht umgehen",
        now=now,
        user_requested="false",  # type: ignore[arg-type]
    )
    allowed = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="user_requested_reminder",
        message_text="Ausdrücklich gewünscht",
        now=now,
        user_requested="true",  # type: ignore[arg-type]
    )

    assert denied.allowed is False
    assert denied.reason == "outside_allowed_hours"
    assert allowed.allowed is True


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
    raw_outbox_path = account_store.account_dir(account_id) / "Proactive_Outbox.jsonl"
    if raw_outbox_path.exists():
        raw_outbox = raw_outbox_path.read_text(encoding="utf-8")
        assert "Du wolltest heute" not in raw_outbox
        assert "TMBMAP1" in raw_outbox


def test_proactive_queue_uses_supplied_now_for_initial_metadata(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    now = datetime(2026, 6, 15, 12, 34, 56, tzinfo=timezone.utc)

    queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="metadata_check",
        message_text="Ping",
        now=now,
    )

    item = account_store.read_proactive_outbox(account_id)[0]
    assert item["created_at"] == "2026-06-15T12:34:56+00:00"
    assert item["updated_at"] == "2026-06-15T12:34:56+00:00"
    assert item["status_history"][0] == {"at": "2026-06-15T12:34:56+00:00", "status": "queued", "reason": "created"}


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


def test_pausing_proactive_agent_blocks_without_losing_consent(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    pause_proactive_agent(account_store, account_id)

    paused = proactive_policy_decision(account_store, account_id, category="reminder", now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc))
    state = resume_proactive_agent(account_store, account_id)
    resumed = proactive_policy_decision(account_store, account_id, category="reminder", now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc))

    assert paused.allowed is False
    assert paused.reason == "proactive_paused"
    assert state["consent"]["categories"] == ["reminder"]
    assert resumed.allowed is True


def test_proactive_category_and_policy_setters_are_normalized(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="1", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id)

    state = set_proactive_categories(account_store, account_id, ("analysis", "bad", "analysis", "reminder"))
    state = set_proactive_allowed_hours(account_store, account_id, 22, 8)
    state = set_proactive_min_interval_minutes(account_store, account_id, 99999)
    decision_at_night = proactive_policy_decision(account_store, account_id, category="reminder", now=datetime(2026, 6, 15, 23, tzinfo=timezone.utc))

    assert state["consent"]["categories"] == ["analysis", "reminder"]
    assert state["policy"]["allowed_hours"] == [22, 8]
    assert state["policy"]["min_minutes_between_messages"] == 1440
    assert decision_at_night.allowed is True


def test_proactive_policy_enforces_min_interval_after_sent_message(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    state = enable_proactive_agent(account_store, account_id, categories=("reminder",))
    state["policy"]["min_minutes_between_messages"] = 180
    account_store.write_agent_state(account_id, state)
    first = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="first",
        message_text="First",
        due_at="2026-06-15T10:00:00+00:00",
        now=datetime(2026, 6, 15, 10, tzinfo=timezone.utc),
    )
    assert first.allowed is True
    assert update_proactive_outbox_item_status(
        account_store,
        account_id,
        first.reason.removeprefix("queued:"),
        status="sent",
        reason="test",
        now=datetime(2026, 6, 15, 10, 30, tzinfo=timezone.utc),
    )

    blocked = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="second",
        message_text="Second",
        due_at="2026-06-15T11:00:00+00:00",
        now=datetime(2026, 6, 15, 11, tzinfo=timezone.utc),
    )
    allowed = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="third",
        message_text="Third",
        due_at="2026-06-15T14:00:00+00:00",
        now=datetime(2026, 6, 15, 14, tzinfo=timezone.utc),
    )

    assert blocked.allowed is False
    assert blocked.reason == "min_interval_not_elapsed"
    assert allowed.allowed is True


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


def test_terminal_proactive_outbox_item_cannot_be_reactivated(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id)
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="terminal",
        message_text="Terminal",
        due_at="2026-06-15T11:00:00+00:00",
        now=now,
    )
    item_id = queued.reason.removeprefix("queued:")
    assert update_proactive_outbox_item_status(account_store, account_id, item_id, status="cancelled", reason="test", now=now)
    history_before = account_store.read_proactive_outbox(account_id)[0]["status_history"]

    assert not update_proactive_outbox_item_status(account_store, account_id, item_id, status="queued", reason="reactivate", now=now)
    assert not update_proactive_outbox_item_status(account_store, account_id, item_id, status="sent", reason="resend", now=now)

    item = account_store.read_proactive_outbox(account_id)[0]
    assert item["status"] == "cancelled"
    assert item["status_history"] == history_before
    assert due_proactive_outbox_items(account_store, account_id, now=now) == ()


def test_review_pending_proactive_outbox_item_cannot_bypass_human_review(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("analysis",))
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="analysis",
        intent="needs_review",
        message_text="Review",
        due_at="2026-06-15T11:00:00+00:00",
        risk_gate="needs_review",
        now=now,
    )
    item_id = queued.reason.removeprefix("review_pending:")
    assert queued.allowed is True

    assert not update_proactive_outbox_item_status(account_store, account_id, item_id, status="sent", reason="bypass", now=now)

    item = account_store.read_proactive_outbox(account_id)[0]
    assert item["status"] == "review_pending"


def test_due_proactive_outbox_items_normalizes_stored_status(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.write_proactive_outbox(
        account_id,
        [
            {
                "id": "pro_upper",
                "status": "QUEUED",
                "category": "reminder",
                "intent": "upper",
                "message_text": "Upper",
                "due_at": "2026-06-15T11:00:00+00:00",
            }
        ],
    )

    due = due_proactive_outbox_items(account_store, account_id, now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc))

    assert [item["id"] for item in due] == ["pro_upper"]


def test_proactive_status_text_normalizes_stored_status_counts(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    account_store.write_proactive_outbox(
        account_id,
        [
            {"id": "pro_queued", "status": "QUEUED", "category": "reminder", "intent": "queued", "message_text": "Queued"},
            {
                "id": "pro_review",
                "status": "Review_Pending",
                "category": "reminder",
                "intent": "review",
                "message_text": "Review",
            },
        ],
    )

    text = proactive_status_text(account_store, account_id)

    assert "- queued_outbox_items: 1" in text
    assert "- review_pending_items: 1" in text


def test_expire_stale_proactive_outbox_items_marks_old_queued_items(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    state = enable_proactive_agent(account_store, account_id, categories=("reminder",))
    state["policy"]["expire_queued_after_days"] = 7
    account_store.write_agent_state(account_id, state)
    old = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="old",
        message_text="Old",
        due_at="2026-06-01T12:00:00+00:00",
        now=datetime(2026, 6, 1, 10, tzinfo=timezone.utc),
    )
    fresh = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="fresh",
        message_text="Fresh",
        due_at="2026-06-14T12:00:00+00:00",
        now=datetime(2026, 6, 14, 10, tzinfo=timezone.utc),
    )

    expired = expire_stale_proactive_outbox_items(account_store, account_id, now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc))

    assert expired == (old.reason.removeprefix("queued:"),)
    rows = account_store.read_proactive_outbox(account_id)
    assert rows[0]["status"] == "expired"
    assert rows[0]["status_history"][-1]["reason"] == "queued_item_older_than_7_days"
    assert rows[1]["id"] == fresh.reason.removeprefix("queued:")
    assert rows[1]["status"] == "queued"
    assert [item["intent"] for item in due_proactive_outbox_items(account_store, account_id, now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc))] == ["fresh"]


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


def test_proactive_policy_counts_dispatching_job_as_daily_reservation(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    state = enable_proactive_agent(account_store, account_id, categories=("reminder",))
    state["policy"]["max_messages_per_day"] = 2
    account_store.write_agent_state(account_id, state)
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    first = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="first",
        message_text="First",
        due_at="2026-06-15T12:00:00+00:00",
        now=now,
    )
    state = account_store.read_agent_state(account_id)
    state["policy"]["max_messages_per_day"] = 1
    account_store.write_agent_state(account_id, state)
    assert claim_proactive_worker_job(account_store, account_id, first.reason.removeprefix("queued:"), now=now)

    second = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="second",
        message_text="Second",
        due_at="2026-06-15T13:00:00+00:00",
        now=now,
    )

    assert second.allowed is False
    assert second.reason == "daily_limit_reached"


def test_llm_cannot_spoof_user_requested_reminder_limit_bypass(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    state = enable_proactive_agent(account_store, account_id, categories=("reminder",))
    state["policy"]["max_messages_per_day"] = 1
    account_store.write_agent_state(account_id, state)
    first = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="first",
        message_text="First",
        due_at="2026-06-15T10:00:00+00:00",
        now=datetime(2026, 6, 15, 10, tzinfo=timezone.utc),
    )
    assert first.allowed is True
    assert update_proactive_outbox_item_status(
        account_store,
        account_id,
        first.reason.removeprefix("queued:"),
        status="sent",
        reason="test",
        now=datetime(2026, 6, 15, 10, 1, tzinfo=timezone.utc),
    )

    spoofed = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="user_requested_reminder",
        message_text="Nicht vom User angefordert",
        due_at="2026-06-15T11:00:00+00:00",
        now=datetime(2026, 6, 15, 11, tzinfo=timezone.utc),
    )

    assert spoofed.allowed is False
    assert spoofed.reason == "daily_limit_reached"
    assert len(account_store.read_proactive_outbox(account_id)) == 1


def test_proactive_policy_daily_limit_normalizes_stored_status(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    state = enable_proactive_agent(account_store, account_id, categories=("reminder",))
    state["policy"]["max_messages_per_day"] = 1
    account_store.write_agent_state(account_id, state)
    account_store.write_proactive_outbox(
        account_id,
        [
            {
                "id": "pro_sent",
                "status": "SENT",
                "category": "reminder",
                "intent": "sent",
                "message_text": "Schon gesendet",
                "sent_at": "2026-06-15T09:00:00+00:00",
                "route": {"channel": "signal", "chat_id": "+491", "chat_type": "private", "adapter_slot": 1},
                "reason_memory_ids": ["mem_sent"],
            }
        ],
    )

    decision = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="second",
        message_text="Second",
        due_at="2026-06-15T13:30:00+00:00",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert decision.allowed is False
    assert decision.reason == "daily_limit_reached"


def test_proactive_policy_default_does_not_limit_general_daily_messages(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)

    decisions = [
        queue_proactive_message(
            account_store,
            account_id,
            category="reminder",
            intent=f"message_{index}",
            message_text=f"Message {index}",
            due_at=f"2026-06-15T{12 + index}:30:00+00:00",
            now=now,
        )
        for index in range(3)
    ]

    assert [decision.allowed for decision in decisions] == [True, True, True]
    state = account_store.read_agent_state(account_id)
    assert state["policy"]["max_messages_per_day"] == 0


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
                "risk_gate": "needs_review",
                "due_at": "not-a-date",
                "route": {"channel": "telegram", "chat_id": "-100", "chat_type": "group"},
            }
        ],
    )

    health = check_proactive_agent_account(account_store, account_id)

    assert health.ok is False
    assert health.queued_count == 1
    assert health.review_pending_count == 0
    joined = "\n".join(health.errors)
    assert "category is not consented: analysis" in joined
    assert "missing intent" in joined
    assert "missing message_text" in joined
    assert "invalid due_at" in joined
    assert "route is not private" in joined
    assert "risk_gate blocks proactive dispatch: needs_review" in joined


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
        reason_memory_ids=("mem_follow_up",),
        due_at="2026-06-15T12:30:00+00:00",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    health = check_proactive_agent_account(account_store, account_id)

    assert decision.allowed is True
    assert health.ok is True
    assert health.queued_count == 1
    assert health.review_pending_count == 0
    assert health.errors == ()


def test_proactive_agent_health_accepts_fresh_dispatching_claim(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="health_fresh_claim",
        message_text="In Arbeit",
        due_at="2026-06-15T11:00:00+00:00",
        now=datetime(2026, 6, 15, 10, tzinfo=timezone.utc),
    )
    assert claim_proactive_worker_job(
        account_store,
        account_id,
        queued.reason.removeprefix("queued:"),
        now=datetime(2026, 6, 15, 11, tzinfo=timezone.utc),
    )

    health = check_proactive_agent_account(
        account_store,
        account_id,
        now=datetime(2026, 6, 15, 11, 29, tzinfo=timezone.utc),
    )

    assert health.ok is True
    assert health.dispatching_count == 1
    assert health.errors == ()


def test_proactive_agent_health_reports_stale_dispatching_claim(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="health_stale_claim",
        message_text="Hängt fest",
        due_at="2026-06-15T11:00:00+00:00",
        now=datetime(2026, 6, 15, 10, tzinfo=timezone.utc),
    )
    assert claim_proactive_worker_job(
        account_store,
        account_id,
        queued.reason.removeprefix("queued:"),
        now=datetime(2026, 6, 15, 11, tzinfo=timezone.utc),
    )

    health = check_proactive_agent_account(
        account_store,
        account_id,
        now=datetime(2026, 6, 15, 11, 30, 1, tzinfo=timezone.utc),
    )

    assert health.ok is False
    assert health.dispatching_count == 1
    assert "has stale claim" in "\n".join(health.errors)


def test_proactive_agent_health_reports_dispatching_claim_without_timestamp(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="health_missing_claim",
        message_text="Zeitstempel fehlt",
        due_at="2026-06-15T11:00:00+00:00",
        now=datetime(2026, 6, 15, 10, tzinfo=timezone.utc),
    )
    item_id = queued.reason.removeprefix("queued:")
    assert claim_proactive_worker_job(account_store, account_id, item_id, now=datetime(2026, 6, 15, 11, tzinfo=timezone.utc))
    rows = account_store.read_proactive_outbox(account_id)
    rows[0].pop("dispatching_at", None)
    rows[0].pop("updated_at", None)
    rows[0].pop("status_history", None)
    account_store.write_proactive_outbox(account_id, rows)

    health = check_proactive_agent_account(account_store, account_id, now=datetime(2026, 6, 15, 11, 1, tzinfo=timezone.utc))

    assert health.ok is False
    assert "missing claim timestamp" in "\n".join(health.errors)


def test_proactive_agent_health_reports_queued_item_without_provenance(tmp_path) -> None:
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
    assert health.ok is False
    assert "queued outbox item {item_id} missing provenance".format(item_id=decision.reason.removeprefix("queued:")) in health.errors


def test_proactive_agent_health_accepts_planner_provenance_without_reason_memory_ids(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="planner_follow_up",
        message_text="Magst du kurz berichten?",
        planner={"source": "local", "fingerprint": "fp_1"},
        due_at="2026-06-15T12:30:00+00:00",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    health = check_proactive_agent_account(account_store, account_id)

    assert health.ok is True
    assert health.errors == ()


def test_proactive_agent_health_reports_malformed_agent_state_shape(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.write_agent_state(
        account_id,
        {
            "schema_version": 1,
            "proactive": [],
            "consent": {"categories": "reminder"},
            "policy": {"allowed_hours": [9]},
        },
    )

    health = check_proactive_agent_account(account_store, account_id)

    assert health.ok is False
    joined = "\n".join(health.errors)
    assert "agent_state proactive is not an object" in joined
    assert "agent_state consent.categories is not a list" in joined
    assert "agent_state policy.allowed_hours is not a two-item list" in joined


def test_proactive_agent_health_reports_agent_state_read_error() -> None:
    class BrokenStore:
        def read_agent_state(self, _account_id: str) -> dict:
            raise AccountStoreError("encrypted envelope authentication failed")

    health = check_proactive_agent_account(BrokenStore(), "a" * 128)  # type: ignore[arg-type]

    assert health.ok is False
    assert health.queued_count == 0
    assert health.review_pending_count == 0
    assert health.errors == ("agent_state read failed: AccountStoreError: encrypted envelope authentication failed",)


def test_proactive_agent_health_reports_corrupt_sql_agent_state(tmp_path, monkeypatch) -> None:
    import sqlite3

    sqlite_path = tmp_path / "memory.sqlite3"
    fallback_path = tmp_path / "memory.backup.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH", str(fallback_path))
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(telegram_identity_key(1))
    account_store.write_agent_state(account_id, {"schema_version": 1, "proactive": {"enabled": True}})
    for path in (sqlite_path, fallback_path):
        with sqlite3.connect(path) as connection:
            connection.execute(
                """
                UPDATE account_jsonl_collections
                SET payload_ciphertext = ?
                WHERE account_id = ? AND collection = ?
                """,
                (b"broken", account_id, "agent_state"),
            )

    health = check_proactive_agent_account(account_store, account_id)

    assert health.ok is False
    assert health.queued_count == 0
    assert health.review_pending_count == 0
    assert len(health.errors) == 1
    assert health.errors[0].startswith("agent_state read failed: AccountStoreError:")
    assert "agent_state" in health.errors[0]


def test_proactive_agent_health_reports_outbox_read_error() -> None:
    class BrokenStore:
        def read_agent_state(self, _account_id: str) -> dict:
            return {}

        def read_proactive_outbox(self, _account_id: str) -> list:
            raise AccountStoreError("encrypted envelope authentication failed")

    health = check_proactive_agent_account(BrokenStore(), "a" * 128)  # type: ignore[arg-type]

    assert health.ok is False
    assert health.errors == ("proactive_outbox read failed: AccountStoreError: encrypted envelope authentication failed",)


def test_proactive_agent_health_does_not_duplicate_missing_outbox_ids(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    account_store.write_proactive_outbox(
        account_id,
        [
            {"status": "sent", "category": "reminder", "intent": "one", "message_text": "One"},
            {"status": "sent", "category": "reminder", "intent": "two", "message_text": "Two"},
        ],
    )

    health = check_proactive_agent_account(account_store, account_id)

    assert health.ok is False
    assert health.errors.count("outbox item 0 missing id") == 1
    assert health.errors.count("outbox item 1 missing id") == 1
    assert not any(error.startswith("duplicate outbox item id:") for error in health.errors)


def test_proactive_dispatch_sends_generated_calendar_file(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    decision = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="appointment_file",
        message_text="Hier ist dein Kalendereintrag.",
        due_at="2026-06-15T12:00:00+00:00",
        now=datetime(2026, 6, 15, 11, tzinfo=timezone.utc),
        file={
            "filename": "termin.ics",
            "content_type": "text/calendar",
            "text": "BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n",
        },
    )
    seen: list[SendAttachment] = []

    async def sender(_route, action, _item):
        seen.append(action)
        return "sent-file"

    result = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"signal": sender},
            now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
        )
    )

    assert decision.allowed is True
    assert result[0].status == "sent"
    assert isinstance(seen[0], SendAttachment)
    assert seen[0].filename == "termin.ics"
    assert seen[0].data.startswith(b"BEGIN:VCALENDAR")
    assert seen[0].caption == "Hier ist dein Kalendereintrag."


def test_proactive_dispatch_accepts_icl_calendar_file(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    decision = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="appointment_icl_file",
        message_text="Hier ist dein Kalendereintrag.",
        due_at="2026-06-15T12:00:00+00:00",
        now=datetime(2026, 6, 15, 11, tzinfo=timezone.utc),
        file={"filename": "termin.icl", "text": "BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n"},
    )
    seen: list[SendAttachment] = []

    async def sender(_route, action, _item):
        seen.append(action)
        return "sent-file"

    result = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"signal": sender},
            now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
        )
    )

    assert decision.allowed is True
    assert result[0].status == "sent"
    assert seen[0].filename == "termin.icl"
    assert seen[0].content_type == "text/calendar; charset=utf-8"


def test_proactive_agent_health_rejects_invalid_generated_file(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="bad_file",
        message_text="Datei",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )
    rows = account_store.read_proactive_outbox(account_id)
    rows[0]["file"] = {"filename": "run.sh", "text": "echo nope"}
    account_store.write_proactive_outbox(account_id, rows)

    health = check_proactive_agent_account(account_store, account_id)

    assert health.ok is False
    assert "has invalid file" in "\n".join(health.errors)


def test_proactive_agent_health_reports_invalid_status_history(tmp_path) -> None:
    account_store = store(tmp_path)
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
        reason_memory_ids=("mem_follow_up",),
        due_at="2026-06-15T12:30:00+00:00",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )
    rows = account_store.read_proactive_outbox(account_id)
    rows[0]["status_history"] = [
        {"at": "not-a-date", "status": "queued", "reason": ""},
        {"at": "2026-06-15T12:01:00+00:00", "status": "sent", "reason": "sent"},
        "broken",
    ]
    account_store.write_proactive_outbox(account_id, rows)

    health = check_proactive_agent_account(account_store, account_id)

    assert health.ok is False
    joined = "\n".join(health.errors)
    assert "status_history[0] has invalid at" in joined
    assert "status_history[0] missing reason" in joined
    assert "status_history[2] is not an object" in joined
    assert "last status sent does not match current status queued" in joined


def test_proactive_agent_health_reports_terminal_status_reactivation_history(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="history_reactivation",
        message_text="Historie",
        reason_memory_ids=("mem_history",),
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )
    rows = account_store.read_proactive_outbox(account_id)
    rows[0]["status"] = "queued"
    rows[0]["status_history"] = [
        {"at": "2026-06-15T12:00:00+00:00", "status": "queued", "reason": "created"},
        {"at": "2026-06-15T12:01:00+00:00", "status": "cancelled", "reason": "cancelled"},
        {"at": "2026-06-15T12:02:00+00:00", "status": "queued", "reason": "reactivated"},
    ]
    account_store.write_proactive_outbox(account_id, rows)

    health = check_proactive_agent_account(account_store, account_id)

    assert health.ok is False
    assert "transition is not allowed: cancelled -> queued" in "\n".join(health.errors)


def test_proactive_agent_health_accepts_string_adapter_slot_in_queued_route(tmp_path) -> None:
    account_store = store(tmp_path)
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
        reason_memory_ids=("mem_follow_up",),
        due_at="2026-06-15T12:30:00+00:00",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )
    rows = account_store.read_proactive_outbox(account_id)
    rows[0]["route"]["adapter_slot"] = "1"
    account_store.write_proactive_outbox(account_id, rows)

    health = check_proactive_agent_account(account_store, account_id)

    assert health.ok is True
    assert health.queued_count == 1
    assert health.review_pending_count == 0
    assert health.errors == ()


def test_proactive_agent_health_reports_stale_queued_route(tmp_path) -> None:
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
        reason_memory_ids=("mem_follow_up",),
        due_at="2026-06-15T12:30:00+00:00",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )
    account_store.update_identity_route(identity, channel="signal", chat_id="+492", chat_type="private", adapter_slot=1)

    health = check_proactive_agent_account(account_store, account_id)

    assert decision.allowed is True
    assert health.ok is False
    assert health.queued_count == 1
    assert health.review_pending_count == 0
    assert "route is stale or not linked to account identity" in "\n".join(health.errors)


def test_proactive_agent_health_rejects_invalid_queued_route_adapter_slot(tmp_path) -> None:
    account_store = store(tmp_path)
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
        reason_memory_ids=("mem_follow_up",),
        due_at="2026-06-15T12:30:00+00:00",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )
    rows = account_store.read_proactive_outbox(account_id)
    rows[0]["route"]["adapter_slot"] = "telegram:broken"
    account_store.write_proactive_outbox(account_id, rows)

    health = check_proactive_agent_account(account_store, account_id)

    assert health.ok is False
    assert "route is stale or not linked to account identity" in "\n".join(health.errors)


def test_proactive_agent_route_matching_uses_normalized_channel_and_chat_type(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="Signal", chat_id="+491", chat_type="Private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    decision = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Magst du kurz berichten?",
        reason_memory_ids=("mem_follow_up",),
        due_at="2026-06-15T12:30:00+00:00",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    health = check_proactive_agent_account(account_store, account_id)
    route = select_proactive_route(account_store, account_id)

    assert decision.allowed is True
    assert health.ok is True
    assert route is not None
    assert route["channel"] == "signal"
    assert route["chat_type"] == "private"


def test_select_proactive_route_prefers_recent_activity_over_channel_priority(tmp_path) -> None:
    account_store = store(tmp_path)
    signal_identity = signal_identity_key(source_uuid="signal-user")
    telegram_identity = telegram_identity_key(123)
    account_id = account_store.resolve_or_create_account(signal_identity)
    account_store.link_identity_to_account(telegram_identity, account_id)
    account_store.update_identity_route(signal_identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    account_store.update_identity_route(telegram_identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)

    identities = account_store._load_identities()
    identities[signal_identity]["last_route"]["last_seen_at"] = "2026-06-15T10:00:00+00:00"
    identities[signal_identity]["last_seen_at"] = "2026-06-15T10:00:00+00:00"
    identities[telegram_identity]["last_route"]["last_seen_at"] = "2026-06-15T11:00:00+00:00"
    identities[telegram_identity]["last_seen_at"] = "2026-06-15T11:00:00+00:00"
    account_store._save_identities(identities)

    route = select_proactive_route(account_store, account_id)

    assert route is not None
    assert route["channel"] == "telegram"


def test_select_proactive_route_rejects_invalid_adapter_slot(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)

    monkeypatch.setattr(
        account_store,
        "get_identity_route",
        lambda _identity: {"channel": "signal", "chat_id": "+491", "chat_type": "private", "adapter_slot": "broken"},
    )

    assert select_proactive_route(account_store, account_id) is None


@pytest.mark.parametrize("invalid_slot", [None, 1.5, "1.5"])
def test_select_proactive_route_rejects_invalid_adapter_slot_value(tmp_path, monkeypatch, invalid_slot) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)

    monkeypatch.setattr(
        account_store,
        "get_identity_route",
        lambda _identity: {"channel": "signal", "chat_id": "+491", "chat_type": "private", "adapter_slot": invalid_slot},
    )

    assert select_proactive_route(account_store, account_id) is None


def test_proactive_policy_does_not_treat_missing_item_slot_as_current_slot(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=2)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))

    decision = proactive_policy_decision(
        account_store,
        account_id,
        category="reminder",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
        item={"route": {"channel": "signal", "chat_id": "+491", "chat_type": "private"}},
    )

    assert decision.allowed is False
    assert decision.reason == "stale_route"


def test_select_proactive_route_accepts_case_variant_route_fields(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)

    def fake_get_identity_route(_identity: str) -> dict[str, object]:
        return {"channel": "Signal", "chat_id": "+491", "chat_type": "Private", "adapter_slot": 1}

    monkeypatch.setattr(account_store, "get_identity_route", fake_get_identity_route)

    route = select_proactive_route(account_store, account_id)

    assert route is not None
    assert route["channel"] == "Signal"
    assert route["chat_type"] == "Private"


def test_check_proactive_agent_account_allows_uppercase_route_values_in_outbox(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Ping",
        reason_memory_ids=("mem_follow_up",),
        due_at="2026-06-15T11:00:00+00:00",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )
    rows = account_store.read_proactive_outbox(account_id)
    rows[0]["route"] = {"channel": "Signal", "chat_id": "+491", "chat_type": "Private", "adapter_slot": 1}
    account_store.write_proactive_outbox(account_id, rows)

    health = check_proactive_agent_account(account_store, account_id)

    assert health.ok is True


def test_proactive_risk_gate_queues_for_human_review_without_dispatch(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))

    decision = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="risk_follow_up",
        message_text="Magst du kurz berichten?",
        reason_memory_ids=("mem_risk",),
        risk_gate="needs_review",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert decision.allowed is True
    assert decision.reason.startswith("review_pending:pro_")
    rows = account_store.read_proactive_outbox(account_id)
    assert rows[0]["status"] == "review_pending"
    assert rows[0]["risk_gate"] == "needs_review"
    assert rows[0]["policy_result"] == "needs_review"
    assert due_proactive_outbox_items(account_store, account_id, now=datetime(2026, 6, 15, 13, tzinfo=timezone.utc)) == ()
    health = check_proactive_agent_account(account_store, account_id)
    assert health.ok is True
    assert health.queued_count == 0
    assert health.review_pending_count == 1


def test_human_review_approval_makes_review_item_dispatchable(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    decision = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="risk_follow_up",
        message_text="Magst du kurz berichten?",
        risk_gate="needs_review",
        due_at="2026-06-15T11:00:00+00:00",
        now=datetime(2026, 6, 15, 10, tzinfo=timezone.utc),
    )
    item_id = decision.reason.removeprefix("review_pending:")

    approved = approve_proactive_review_item(
        account_store,
        account_id,
        item_id,
        reviewer="tester",
        reason="fachlich unkritischer Check-in",
        now=datetime(2026, 6, 15, 10, 30, tzinfo=timezone.utc),
    )

    assert approved.allowed is True
    rows = account_store.read_proactive_outbox(account_id)
    assert rows[0]["status"] == "queued"
    assert rows[0]["risk_gate"] == "none"
    assert rows[0]["human_review"]["status"] == "approved"
    assert due_proactive_outbox_items(account_store, account_id, now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc))[0]["id"] == item_id


def test_human_review_rejection_cancels_review_item(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    decision = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="risk_follow_up",
        message_text="Magst du kurz berichten?",
        risk_gate="needs_review",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )
    item_id = decision.reason.removeprefix("review_pending:")

    rejected = reject_proactive_review_item(account_store, account_id, item_id, reviewer="tester", reason="zu riskant")

    assert rejected.allowed is True
    rows = account_store.read_proactive_outbox(account_id)
    assert rows[0]["status"] == "cancelled"
    assert rows[0]["human_review"]["status"] == "rejected"


def test_active_risk_memory_blocks_proactive_analysis_but_not_plain_reminder(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder", "analysis"))
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    memory_id = account_store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_risk",
            "kind": "suicidal_ideation",
            "user_text": "Passive Suizidgedanken.",
            "created_at": "2026-06-15T10:00:00+00:00",
            "updated_at": "2026-06-15T10:00:00+00:00",
        },
    )

    analysis = queue_proactive_message(
        account_store,
        account_id,
        category="analysis",
        intent="deep_analysis",
        message_text="Ich habe eine Analyse vorbereitet.",
        now=now,
    )
    reminder = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="plain_checkin",
        message_text="Denk bitte an deine vereinbarte Pause.",
        now=now,
    )

    assert active_proactive_risk_memory_ids(account_store, account_id, now=now) == (memory_id,)
    assert analysis.allowed is False
    assert analysis.reason == "active_risk_signal"
    assert reminder.allowed is True


def test_dispatch_skips_queued_analysis_when_risk_memory_becomes_active(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("analysis",))
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    decision = queue_proactive_message(
        account_store,
        account_id,
        category="analysis",
        intent="pre_risk_analysis",
        message_text="Ich habe eine Analyse vorbereitet.",
        due_at="2026-06-15T11:00:00+00:00",
        now=datetime(2026, 6, 15, 8, tzinfo=timezone.utc),
    )
    assert decision.allowed is True
    account_store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_risk",
            "kind": "self_harm_signal",
            "user_text": "Selbstverletzungsdruck.",
            "created_at": "2026-06-15T10:00:00+00:00",
            "updated_at": "2026-06-15T10:00:00+00:00",
        },
    )

    results = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"signal": lambda _route, _action, _item: "sent-ref"},
            now=now,
        )
    )

    assert results[0].status == "skipped"
    assert results[0].reason == "active_risk_signal"
    item = account_store.read_proactive_outbox(account_id)[0]
    assert item["status"] == "skipped"
    assert item["status_history"][-1]["reason"] == "policy:active_risk_signal"
    audit = account_store.read_proactive_audit(account_id)
    assert len(audit) == 1
    assert audit[0]["event_type"] == "proactive_safety_hold"
    assert audit[0]["source"] == "proactive_dispatch_policy"
    assert audit[0]["reason"] == "active_risk_signal"
    assert audit[0]["item"]["id"] == decision.reason.removeprefix("queued:")
    assert "No automatic proactive clinical content was sent" in audit[0]["safe_standard_hint"]


def test_dispatch_audits_blocked_risk_gate_without_sending(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    account_store.write_proactive_outbox(
        account_id,
        [
            {
                "id": "pro_crisis",
                "status": "queued",
                "category": "reminder",
                "intent": "unsafe_followup",
                "message_text": "Bitte melde dich sofort.",
                "risk_gate": "crisis",
                "reason_memory_ids": ["mem_risk"],
                "due_at": "2026-06-15T11:00:00+00:00",
                "route": {"channel": "signal", "chat_id": "+491", "chat_type": "private", "adapter_slot": 1},
            }
        ],
    )
    sent: list[str] = []

    results = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"signal": lambda _route, _action, _item: sent.append("sent") or "sent-ref"},
            now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
        )
    )

    assert sent == []
    assert results[0].status == "skipped"
    assert results[0].reason == "risk_gate_blocked:crisis"
    item = account_store.read_proactive_outbox(account_id)[0]
    assert item["status"] == "skipped"
    assert item["status_history"][-1]["reason"] == "policy:risk_gate_blocked:crisis"
    audit = account_store.read_proactive_audit(account_id)
    assert len(audit) == 1
    assert audit[0]["event_type"] == "proactive_safety_hold"
    assert audit[0]["reason"] == "risk_gate_blocked:crisis"
    assert audit[0]["item"]["id"] == "pro_crisis"


def test_reflection_planner_creates_reflection_and_queues_safe_reminder(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    source_id = account_store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_goal",
            "kind": "therapy_goal",
            "user_text": "Diese Woche zweimal zehn Minuten spazieren gehen.",
            "created_at": "2026-06-15T08:00:00+00:00",
            "updated_at": "2026-06-15T08:00:00+00:00",
        },
    )

    result = run_proactive_reflection_planner(
        account_store,
        account_id,
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.skipped_reason == ""
    assert len(result.created_memory_ids) == 9
    assert len(result.queued_item_ids) == 1
    entries = account_store.read_memory_entries(account_id)
    created = [entry for entry in entries if entry["id"] in result.created_memory_ids]
    assert [entry["kind"] for entry in created] == [
        "reflection",
        "summary",
        "assessment_note",
        "intervention_note",
        "response_note",
        "next_step",
        "follow_up",
        "treatment_plan",
        "homework",
    ]
    reflection = next(entry for entry in entries if entry["id"] == result.created_memory_ids[0])
    assert reflection["kind"] == "reflection"
    assert reflection["relations"][0]["type"] == "derived_from"
    assert reflection["relations"][0]["target_id"] == source_id
    assert all(entry["relations"][0]["target_id"] == source_id for entry in created)
    assert all(entry["proactive_planner"]["source"] == "local" for entry in created)
    outbox = account_store.read_proactive_outbox(account_id)
    assert outbox[0]["id"] == result.queued_item_ids[0]
    assert outbox[0]["category"] == "reminder"
    assert outbox[0]["intent"] == "planner_follow_up"
    assert outbox[0]["planner"]["source_memory_id"] == source_id
    assert outbox[0]["planner"]["memory_ids"] == list(result.created_memory_ids)
    assert outbox[0]["reason_memory_ids"] == [source_id, *result.created_memory_ids]


def test_reflection_planner_is_idempotent_per_source_memory(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    account_store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_goal",
            "kind": "treatment_goal",
            "user_text": "Schlafrhythmus stabilisieren.",
            "created_at": "2026-06-15T08:00:00+00:00",
            "updated_at": "2026-06-15T08:00:00+00:00",
        },
    )

    first = run_proactive_reflection_planner(account_store, account_id, now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc))
    second = run_proactive_reflection_planner(account_store, account_id, now=datetime(2026, 6, 15, 13, tzinfo=timezone.utc))

    assert len(first.queued_item_ids) == 1
    assert second.queued_item_ids == ()
    assert second.skipped_reason == "no_candidate"
    assert len(account_store.read_proactive_outbox(account_id)) == 1
    assert len([entry for entry in account_store.read_memory_entries(account_id) if entry.get("proactive_plan_fingerprint")]) == 9


def test_reflection_planner_does_not_write_memories_when_route_policy_blocks(tmp_path) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="signal-user"))
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    account_store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_goal",
            "kind": "therapy_goal",
            "user_text": "Spaziergang planen.",
            "created_at": "2026-06-15T08:00:00+00:00",
            "updated_at": "2026-06-15T08:00:00+00:00",
        },
    )

    result = run_proactive_reflection_planner(
        account_store,
        account_id,
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.skipped_reason == "no_private_route"
    assert result.created_memory_ids == ()
    assert result.queued_item_ids == ()
    assert [entry["id"] for entry in account_store.read_memory_entries(account_id)] == ["mem_goal"]
    assert account_store.read_proactive_outbox(account_id) == []


def test_reflection_planner_honors_zero_max_items_without_writes(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    account_store.append_structured_memory_entry(account_id, {"id": "mem_goal", "kind": "therapy_goal", "user_text": "Spaziergang planen."})

    result = run_proactive_reflection_planner(account_store, account_id, max_items=0, now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc))

    assert result.skipped_reason == "max_items_reached"
    assert result.created_memory_ids == ()
    assert result.queued_item_ids == ()
    assert account_store.read_proactive_outbox(account_id) == []


def test_reflection_planner_skips_when_risk_memory_is_active(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    account_store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_goal",
            "kind": "therapy_goal",
            "user_text": "Spazieren gehen.",
            "created_at": "2026-06-15T08:00:00+00:00",
            "updated_at": "2026-06-15T08:00:00+00:00",
        },
    )
    account_store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_risk",
            "kind": "suicidal_ideation",
            "user_text": "Passive Suizidgedanken.",
            "created_at": "2026-06-15T10:00:00+00:00",
            "updated_at": "2026-06-15T10:00:00+00:00",
        },
    )

    result = run_proactive_reflection_planner(account_store, account_id, now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc))

    assert result.skipped_reason == "active_risk_signal"
    assert result.queued_item_ids == ()
    assert account_store.read_proactive_outbox(account_id) == []


def test_llm_plan_validator_applies_safe_memory_and_queue_decisions(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    source_id = account_store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_goal",
            "kind": "therapy_goal",
            "user_text": "Diese Woche zweimal zehn Minuten spazieren gehen.",
            "created_at": "2026-06-15T08:00:00+00:00",
            "updated_at": "2026-06-15T08:00:00+00:00",
        },
    )

    result = apply_proactive_llm_plan(
        account_store,
        account_id,
        {
            "schema_version": 1,
            "decisions": [
                {
                    "action": "memory",
                    "kind": "reflection",
                    "text": "Sanftes Follow-up zu Spaziergaengen ist plausibel, sofern der User einverstanden bleibt.",
                    "source_memory_ids": [source_id],
                },
                {
                    "action": "queue",
                    "category": "reminder",
                    "intent": "llm_follow_up",
                    "message_text": "Magst du kurz sagen, ob ein kurzer Spaziergang heute realistisch ist?",
                    "reason_memory_ids": [source_id],
                    "risk_gate": "none",
                    "intervention_type": "reminder",
                    "expected_response": "kurze Rueckmeldung",
                    "review_signal": "erledigt/nicht erledigt/Belastung",
                },
            ],
        },
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.errors == ()
    assert len(result.created_memory_ids) == 1
    assert len(result.queued_item_ids) == 1
    memory = next(entry for entry in account_store.read_memory_entries(account_id) if entry["id"] == result.created_memory_ids[0])
    assert memory["kind"] == "reflection"
    assert memory["relations"][0]["target_id"] == source_id
    outbox = account_store.read_proactive_outbox(account_id)
    assert outbox[0]["id"] == result.queued_item_ids[0]
    assert outbox[0]["planner"]["source"] == "llm"
    assert outbox[0]["reason_memory_ids"] == [source_id]


def test_llm_plan_validator_can_cancel_and_snooze_queued_items(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    first = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="cancel_me",
        message_text="Cancel me",
        due_at="2026-06-15T13:00:00+00:00",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )
    second = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="snooze_me",
        message_text="Snooze me",
        due_at="2026-06-15T13:00:00+00:00",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )
    first_id = first.reason.removeprefix("queued:")
    second_id = second.reason.removeprefix("queued:")

    result = apply_proactive_llm_plan(
        account_store,
        account_id,
        {
            "schema_version": 1,
            "decisions": [
                {"action": "cancel", "item_id": first_id, "reason": "nicht mehr passend"},
                {"action": "snooze", "item_id": second_id, "due_at": "2026-06-16T09:30:00+00:00", "reason": "spaeter besser"},
            ],
        },
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.errors == ()
    assert len(result.audit_event_ids) == 2
    rows = account_store.read_proactive_outbox(account_id)
    assert rows[0]["id"] == first_id
    assert rows[0]["status"] == "cancelled"
    assert rows[0]["status_history"][-1]["reason"] == "llm_cancel:nicht mehr passend"
    assert rows[1]["id"] == second_id
    assert rows[1]["status"] == "queued"
    assert rows[1]["due_at"] == "2026-06-16T09:30:00+00:00"
    assert rows[1]["status_history"][-1]["reason"] == "llm_snooze:spaeter besser"
    audit = account_store.read_proactive_audit(account_id)
    assert [event["event_type"] for event in audit] == ["llm_decision_applied", "llm_decision_applied"]
    assert [event["reason"] for event in audit] == [f"cancelled:{first_id}", f"snoozed:{second_id}"]


def test_llm_plan_validator_rejects_cancel_and_snooze_for_invalid_items(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="already_sent",
        message_text="Already sent",
        due_at="2026-06-15T13:00:00+00:00",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )
    queued_id = queued.reason.removeprefix("queued:")
    update_proactive_outbox_item_status(account_store, account_id, queued_id, status="sent", reason="test", now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc))

    result = apply_proactive_llm_plan(
        account_store,
        account_id,
        {
            "schema_version": 1,
            "decisions": [
                {"action": "cancel", "item_id": queued_id, "reason": "zu spaet"},
                {"action": "snooze", "item_id": "pro_missing", "due_at": "2026-06-16T09:30:00+00:00"},
                {"action": "snooze", "item_id": queued_id, "due_at": "not-a-date"},
            ],
        },
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.errors == (
        "decision_0_item_not_queued",
        "decision_1_item_not_queued",
        "decision_2_item_not_queued",
    )
    assert len(result.audit_event_ids) == 3
    assert account_store.read_proactive_outbox(account_id)[0]["status"] == "sent"
    audit = account_store.read_proactive_audit(account_id)
    assert [event["event_type"] for event in audit] == ["llm_decision_rejected", "llm_decision_rejected", "llm_decision_rejected"]


def test_llm_cancel_does_not_overwrite_terminal_item_after_stale_precheck(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="already_sent",
        message_text="Already sent",
        due_at="2026-06-15T13:00:00+00:00",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )
    item_id = queued.reason.removeprefix("queued:")
    update_proactive_outbox_item_status(
        account_store,
        account_id,
        item_id,
        status="sent",
        reason="sent_before_cancel",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )
    monkeypatch.setattr("TeeBotus.runtime.proactive_agent._queued_proactive_outbox_item_exists", lambda *_args: True)

    result = apply_proactive_llm_plan(
        account_store,
        account_id,
        {
            "schema_version": 1,
            "decisions": [
                {"action": "cancel", "item_id": item_id, "reason": "zu spaet"},
            ],
        },
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.errors == ("decision_0_item_not_queued",)
    item = account_store.read_proactive_outbox(account_id)[0]
    assert item["status"] == "sent"
    assert item["status_history"][-1]["reason"] == "sent_before_cancel"


def test_llm_planner_prompt_includes_queued_outbox_ids_for_cancel_snooze(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Follow up",
        due_at="2026-06-15T13:00:00+00:00",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    prompt = build_proactive_llm_planner_prompt(account_store, account_id)

    assert '"action":"none|memory|queue|cancel|snooze"' in prompt
    assert "Queued Outbox fuer Cancel/Snooze:" in prompt
    assert queued.reason.removeprefix("queued:") in prompt


def test_llm_plan_validator_rejects_malformed_json_without_mutation(tmp_path) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="signal-user"))

    result = apply_proactive_llm_plan_text(account_store, account_id, "```json\n{not-json}\n```")

    assert result.created_memory_ids == ()
    assert result.queued_item_ids == ()
    assert result.errors[0].startswith("invalid_json:")
    assert len(result.audit_event_ids) == 1
    assert account_store.read_memory_entries(account_id) == []
    assert account_store.read_proactive_outbox(account_id) == []
    audit = account_store.read_proactive_audit(account_id)
    assert audit[0]["id"] == result.audit_event_ids[0]
    assert audit[0]["event_type"] == "llm_plan_rejected"
    assert audit[0]["reason"].startswith("invalid_json:")


@pytest.mark.parametrize("schema_version", ["invalid", {}, []])
def test_llm_plan_rejects_non_numeric_schema_version_without_crashing(tmp_path, schema_version) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="signal-user"))

    result = apply_proactive_llm_plan(
        account_store,
        account_id,
        {"schema_version": schema_version, "decisions": []},
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.errors == ("unsupported_schema_version",)
    assert len(result.audit_event_ids) == 1
    assert account_store.read_proactive_outbox(account_id) == []
    assert account_store.read_proactive_audit(account_id)[0]["reason"] == "unsupported_schema_version"


def test_llm_plan_validator_rejects_unsafe_message_and_queues_review_gate(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    source_id = account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_goal", "kind": "therapy_goal", "user_text": "Spazieren gehen."},
    )

    result = apply_proactive_llm_plan(
        account_store,
        account_id,
        {
            "schema_version": 1,
            "decisions": [
                {
                    "action": "queue",
                    "category": "reminder",
                    "intent": "unsafe",
                    "message_text": "Du hast Depression, also musst du das jetzt tun.",
                    "reason_memory_ids": [source_id],
                    "risk_gate": "none",
                },
                {
                    "action": "queue",
                    "category": "reminder",
                    "intent": "review",
                    "message_text": "Magst du kurz berichten?",
                    "reason_memory_ids": [source_id],
                    "risk_gate": "needs_review",
                },
            ],
        },
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert "decision_0_unsafe_message_text" in result.errors
    assert len(result.audit_event_ids) == 1
    assert len(result.queued_item_ids) == 1
    rows = account_store.read_proactive_outbox(account_id)
    assert rows[0]["id"] == result.queued_item_ids[0]
    assert rows[0]["status"] == "review_pending"
    assert rows[0]["risk_gate"] == "needs_review"
    audit = account_store.read_proactive_audit(account_id)
    assert [event["reason"] for event in audit] == ["decision_0_unsafe_message_text"]
    assert audit[0]["decision"]["intent"] == "unsafe"
    assert audit[0]["event_type"] == "llm_decision_rejected"


def test_llm_plan_validator_rejects_pressure_message_text(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    source_id = account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_goal", "kind": "therapy_goal", "user_text": "Spazieren gehen."},
    )

    result = apply_proactive_llm_plan(
        account_store,
        account_id,
        {
            "schema_version": 1,
            "decisions": [
                {
                    "action": "queue",
                    "category": "reminder",
                    "intent": "pressure",
                    "message_text": "Du musst sofort antworten, sonst wird alles schlimmer.",
                    "reason_memory_ids": [source_id],
                    "risk_gate": "none",
                }
            ],
        },
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.queued_item_ids == ()
    assert result.errors == ("decision_0_unsafe_message_text",)
    assert account_store.read_proactive_outbox(account_id) == []
    audit = account_store.read_proactive_audit(account_id)
    assert audit[0]["event_type"] == "llm_decision_rejected"
    assert audit[0]["reason"] == "decision_0_unsafe_message_text"


def test_llm_plan_validator_rejects_diagnostic_memory_text(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))

    result = apply_proactive_llm_plan(
        account_store,
        account_id,
        {
            "schema_version": 1,
            "decisions": [
                {
                    "action": "memory",
                    "kind": "assessment_note",
                    "text": "Du leidest an einer Depression.",
                    "source_memory_ids": [],
                }
            ],
        },
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.created_memory_ids == ()
    assert result.errors == ("decision_0_unsafe_memory_text",)
    assert account_store.read_memory_entries(account_id) == []
    audit = account_store.read_proactive_audit(account_id)
    assert audit[0]["event_type"] == "llm_decision_rejected"
    assert audit[0]["reason"] == "decision_0_unsafe_memory_text"


def test_llm_plan_validator_rejects_suggestive_false_memory_message(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    source_id = account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_goal", "kind": "therapy_goal", "user_text": "Mehr Stabilitaet im Alltag."},
    )

    result = apply_proactive_llm_plan(
        account_store,
        account_id,
        {
            "schema_version": 1,
            "decisions": [
                {
                    "action": "queue",
                    "category": "reminder",
                    "intent": "false_memory_prompt",
                    "message_text": "Du erinnerst dich nur noch nicht, was damals passiert ist.",
                    "reason_memory_ids": [source_id],
                    "risk_gate": "none",
                }
            ],
        },
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.queued_item_ids == ()
    assert result.errors == ("decision_0_unsafe_message_text",)
    assert account_store.read_proactive_outbox(account_id) == []
    audit = account_store.read_proactive_audit(account_id)
    assert audit[0]["event_type"] == "llm_decision_rejected"
    assert audit[0]["reason"] == "decision_0_unsafe_message_text"


def test_llm_plan_validator_rejects_suggestive_false_memory_note(tmp_path) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="signal-user"))

    result = apply_proactive_llm_plan(
        account_store,
        account_id,
        {
            "schema_version": 1,
            "decisions": [
                {
                    "action": "memory",
                    "kind": "assessment_note",
                    "text": "Du hast das bestimmt verdraengt.",
                    "source_memory_ids": [],
                }
            ],
        },
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.created_memory_ids == ()
    assert result.errors == ("decision_0_unsafe_memory_text",)
    assert account_store.read_memory_entries(account_id) == []
    audit = account_store.read_proactive_audit(account_id)
    assert audit[0]["event_type"] == "llm_decision_rejected"
    assert audit[0]["reason"] == "decision_0_unsafe_memory_text"


def test_llm_plan_validator_audits_unsupported_actions_without_applying_them(tmp_path) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="signal-user"))

    result = apply_proactive_llm_plan(
        account_store,
        account_id,
        {"schema_version": 1, "decisions": [{"action": "send_now", "message_text": "Hallo"}]},
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.errors == ("decision_0_unsupported_action:send_now",)
    assert len(result.audit_event_ids) == 1
    assert result.created_memory_ids == ()
    assert result.queued_item_ids == ()
    assert account_store.read_memory_entries(account_id) == []
    assert account_store.read_proactive_outbox(account_id) == []
    audit = account_store.read_proactive_audit(account_id)
    assert audit[0]["id"] == result.audit_event_ids[0]
    assert audit[0]["decision_index"] == 0
    assert audit[0]["decision"]["action"] == "send_now"


def test_llm_planner_runner_uses_client_text_and_validates_before_applying(tmp_path) -> None:
    class Response:
        text = '{"schema_version":1,"decisions":[{"action":"queue","category":"reminder","intent":"llm_follow_up","message_text":"Magst du kurz berichten, ob du an deinem Ziel weiterarbeiten moechtest?","reason_memory_ids":["mem_goal"],"risk_gate":"none"}]}'

    class Client:
        def __init__(self) -> None:
            self.prompts = []

        def create_reply(self, prompt, instructions):
            self.prompts.append((prompt, instructions))
            return Response()

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_goal", "kind": "therapy_goal", "user_text": "Spazieren gehen."},
    )
    client = Client()
    instructions = object()

    result = run_proactive_llm_planner(
        account_store,
        account_id,
        openai_client=client,
        instructions=instructions,
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.errors == ()
    assert len(result.queued_item_ids) == 1
    assert client.prompts[0][1] is instructions
    assert "Gib ausschliesslich valides JSON" in client.prompts[0][0]
    assert "mem_goal" in client.prompts[0][0]
    assert account_store.read_proactive_outbox(account_id)[0]["planner"]["source"] == "llm"


def test_disabled_proactive_account_skips_model_planner_before_provider_call(tmp_path) -> None:
    class Client:
        def create_reply(self, *_args):
            raise AssertionError("disabled proactive account must not call the LLM")

    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="signal-user"))
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_goal", "kind": "therapy_goal", "user_text": "Spazieren gehen."},
    )

    assert should_run_proactive_model_planner(account_store, account_id) == (False, "proactive_disabled")
    result = run_proactive_llm_planner(
        account_store,
        account_id,
        openai_client=Client(),
        instructions=object(),
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.errors == ("proactive_disabled",)
    assert account_store.read_memory_entries(account_id)[-1]["id"] == "mem_goal"
    assert account_store.read_proactive_outbox(account_id) == []
    assert account_store.read_proactive_audit(account_id)[0]["reason"] == "proactive_disabled"


def test_disabled_proactive_account_blocks_safe_llm_memory_write(tmp_path) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="signal-user"))

    result = apply_proactive_llm_plan(
        account_store,
        account_id,
        {
            "schema_version": 1,
            "decisions": [
                {
                    "action": "memory",
                    "kind": "reflection",
                    "text": "Interne Reflexion darf nicht geschrieben werden.",
                }
            ],
        },
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.errors == ("decision_0_proactive_disabled",)
    assert result.created_memory_ids == ()
    assert account_store.read_memory_entries(account_id) == []


def test_llm_planner_prompt_has_schema_and_memory_context(tmp_path) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="signal-user"))
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_goal", "kind": "therapy_goal", "user_text": "Spazieren gehen."},
    )

    prompt = build_proactive_llm_planner_prompt(account_store, account_id)

    assert '"schema_version":1' in prompt
    assert "Du sendest nie direkt Nachrichten" in prompt
    assert "mem_goal" in prompt


def test_tool_agent_extracts_responses_api_function_calls() -> None:
    response = {
        "output": [
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "proactive_create_memory",
                "arguments": '{"kind":"reflection","text":"Sanfter Plan","source_memory_ids":["mem_goal"]}',
            }
        ]
    }

    calls = extract_proactive_agent_tool_calls(response)

    assert len(calls) == 1
    assert calls[0].name == "proactive_create_memory"
    assert calls[0].call_id == "call_1"
    assert calls[0].arguments["kind"] == "reflection"


def test_tool_agent_applies_memory_queue_and_snooze_tools_through_validator(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    source_id = account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_goal", "kind": "therapy_goal", "user_text": "Spazieren gehen."},
    )
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="existing",
        message_text="Old",
        due_at="2026-06-15T13:00:00+00:00",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )
    queued_id = queued.reason.removeprefix("queued:")

    result = apply_proactive_agent_tool_calls(
        account_store,
        account_id,
        [
            {
                "name": "proactive_create_memory",
                "arguments": {
                    "kind": "reflection",
                    "text": "Sanftes Follow-up ist plausibel.",
                    "source_memory_ids": [source_id],
                },
            },
            {
                "name": "proactive_queue_message",
                "arguments": {
                    "category": "reminder",
                    "intent": "tool_follow_up",
                    "message_text": "Magst du kurz berichten, ob ein kleiner Spaziergang passt?",
                    "reason_memory_ids": [source_id],
                    "risk_gate": "none",
                    "file": {
                        "filename": "spaziergang.vcf",
                        "content_type": "text/vcard",
                        "text": "BEGIN:VCARD\nVERSION:4.0\nFN:Spaziergang\nEND:VCARD\n",
                    },
                },
            },
            {
                "name": "proactive_snooze_item",
                "arguments": {"item_id": queued_id, "due_at": "2026-06-16T09:30:00+00:00", "reason": "spaeter"},
            },
        ],
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.errors == ()
    assert len(result.created_memory_ids) == 1
    assert len(result.queued_item_ids) == 1
    rows = account_store.read_proactive_outbox(account_id)
    assert rows[0]["id"] == queued_id
    assert rows[0]["due_at"] == "2026-06-16T09:30:00+00:00"
    assert rows[1]["id"] == result.queued_item_ids[0]
    assert rows[1]["planner"]["source"] == "llm"
    assert rows[1]["file"]["filename"] == "spaziergang.vcf"
    assert rows[1]["file"]["text"].startswith("BEGIN:VCARD")


def test_tool_agent_rejects_unknown_tools_without_mutating(tmp_path) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="signal-user"))

    result = apply_proactive_agent_tool_calls(
        account_store,
        account_id,
        [{"name": "proactive_send_now", "arguments": {"message_text": "Hallo"}}],
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.errors == ("tool_0_unsupported_tool:proactive_send_now",)
    assert account_store.read_memory_entries(account_id) == []
    assert account_store.read_proactive_outbox(account_id) == []
    audit = account_store.read_proactive_audit(account_id)
    assert audit[0]["event_type"] == "tool_call_rejected"


def test_tool_agent_rejects_known_tool_with_invalid_arguments_without_mutating(tmp_path) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="signal-user"))

    result = apply_proactive_agent_tool_calls(
        account_store,
        account_id,
        [
            {
                "name": "proactive_queue_message",
                "arguments": {
                    "category": "reminder",
                    "intent": "missing_reasons",
                    "message_text": "Hallo",
                },
            }
        ],
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.errors == ("tool_0_invalid_tool_call",)
    assert account_store.read_memory_entries(account_id) == []
    assert account_store.read_proactive_outbox(account_id) == []
    audit = account_store.read_proactive_audit(account_id)
    assert audit[0]["event_type"] == "tool_call_rejected"


def test_tool_agent_rejects_known_tool_with_empty_required_arguments_without_mutating(tmp_path) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="signal-user"))

    result = apply_proactive_agent_tool_calls(
        account_store,
        account_id,
        [
            {
                "name": "proactive_queue_message",
                "arguments": {
                    "category": "reminder",
                    "intent": "follow_up",
                    "message_text": "   ",
                    "reason_memory_ids": ["mem_goal"],
                },
            }
        ],
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.errors == ("tool_0_invalid_tool_call",)
    assert account_store.read_memory_entries(account_id) == []
    assert account_store.read_proactive_outbox(account_id) == []
    audit = account_store.read_proactive_audit(account_id)
    assert audit[0]["event_type"] == "tool_call_rejected"


def test_tool_agent_rejects_secret_like_generated_file_without_mutating(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    source_id = account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_goal", "kind": "therapy_goal", "user_text": "Termin vorbereiten."},
    )
    secret = "sk-" + "live" + "-secret1234567890"

    result = apply_proactive_agent_tool_calls(
        account_store,
        account_id,
        [
            {
                "name": "proactive_queue_message",
                "arguments": {
                    "category": "reminder",
                    "intent": "secret_file",
                    "message_text": "Hier ist die Datei.",
                    "reason_memory_ids": [source_id],
                    "risk_gate": "none",
                    "file": {
                        "filename": "zugang.txt",
                        "content_type": "text/plain",
                        "text": f"OPENAI_API_KEY={secret}",
                    },
                },
            }
        ],
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.errors == ("decision_0_policy:invalid_file",)
    assert account_store.read_proactive_outbox(account_id) == []
    audit = account_store.read_proactive_audit(account_id)
    assert audit[0]["event_type"] == "llm_decision_rejected"


def test_tool_agent_runner_uses_client_tool_calls(tmp_path) -> None:
    class Client:
        def __init__(self) -> None:
            self.calls = []

        def create_tool_calls(self, prompt, instructions, tools):
            self.calls.append((prompt, instructions, tools))
            return {
                "tool_calls": [
                    {
                        "name": "proactive_queue_message",
                        "arguments": {
                            "category": "reminder",
                            "intent": "tool_runner_follow_up",
                            "message_text": "Magst du kurz berichten?",
                            "reason_memory_ids": ["mem_goal"],
                            "risk_gate": "none",
                        },
                    }
                ]
            }

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    account_store.append_structured_memory_entry(account_id, {"id": "mem_goal", "kind": "therapy_goal", "user_text": "Spazieren gehen."})
    client = Client()
    instructions = object()

    result = run_proactive_tool_agent(
        account_store,
        account_id,
        openai_client=client,
        instructions=instructions,
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.errors == ()
    assert len(result.queued_item_ids) == 1
    assert client.calls[0][1] is instructions
    assert client.calls[0][2][0]["name"] == "proactive_create_memory"
    assert "Nutze ausschliesslich die bereitgestellten Tools" in client.calls[0][0]


def test_tool_agent_runner_accepts_valid_json_text_fallback(tmp_path) -> None:
    class Client:
        def create_tool_calls(self, _prompt, _instructions, _tools):
            return {
                "output": [
                    {"type": "reasoning", "content": []},
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"schema_version":1,"decisions":[{"action":"none"}]}',
                            }
                        ],
                    },
                ]
            }

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))

    result = run_proactive_tool_agent(
        account_store,
        account_id,
        openai_client=Client(),
        instructions=object(),
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert result.errors == ()
    assert result.created_memory_ids == ()
    assert result.queued_item_ids == ()
    assert account_store.read_proactive_audit(account_id) == []


def test_dispatch_due_proactive_items_sends_with_mocked_channel_and_tracks_ref(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Magst du kurz berichten?",
        due_at="2026-06-15T11:00:00+00:00",
        now=now,
    )
    calls = []

    async def sender(route: dict, action: SendText, item: dict) -> str:
        calls.append((route, action, item))
        return "123456789"

    tracker = MessageTracker(tmp_path / "sent_refs.json")
    results = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"signal": sender},
            now=now,
            message_tracker=tracker,
            instance_name="Depressionsbot",
        )
    )

    item_id = queued.reason.removeprefix("queued:")
    assert [result.item_id for result in results] == [item_id]
    assert results[0].status == "sent"
    assert results[0].message_ref == "123456789"
    assert calls[0][1] == SendText("+491", "Magst du kurz berichten?", track=True)
    sent_item = account_store.read_proactive_outbox(account_id)[0]
    assert sent_item["status"] == "sent"
    assert sent_item["dispatch"]["channel"] == "signal"
    assert sent_item["dispatch"]["message_ref"] == "123456789"
    assert sent_item["dispatch_attempts"] == 1
    assert "dispatching_at" not in sent_item
    assert [entry["status"] for entry in sent_item["status_history"]] == ["queued", "dispatching", "sent"]
    refs = tracker.list_for_chat("+491", instance_name="Depressionsbot", channel="signal")
    assert len(refs) == 1
    assert refs[0].message_ref == "123456789"
    assert refs[0].ref_kind == "signal_timestamp"


def test_dispatch_claim_prevents_nested_worker_from_sending_same_item(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Ping",
        due_at="2026-06-15T11:00:00+00:00",
        now=now,
    )
    item_id = queued.reason.removeprefix("queued:")
    calls: list[str] = []
    nested_results = []

    async def duplicate_sender(_route: dict, _action: SendText, _item: dict) -> str:
        raise AssertionError("claimed proactive outbox item was sent twice")

    async def sender(_route: dict, _action: SendText, item: dict) -> str:
        calls.append(str(item.get("id")))
        nested_results.extend(
            await dispatch_due_proactive_outbox_items(
                account_store,
                account_id,
                senders={"signal": duplicate_sender},
                now=now,
            )
        )
        return "sent-ref"

    results = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"signal": sender},
            now=now,
        )
    )

    assert calls == [item_id]
    assert nested_results == []
    assert len(results) == 1
    assert results[0].status == "sent"
    item = account_store.read_proactive_outbox(account_id)[0]
    assert item["status"] == "sent"
    assert [entry["status"] for entry in item["status_history"]] == ["queued", "dispatching", "sent"]


def test_fresh_proactive_dispatch_claim_is_not_recovered(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Ping",
        due_at="2026-06-15T11:00:00+00:00",
        now=datetime(2026, 6, 15, 10, tzinfo=timezone.utc),
    )
    item_id = queued.reason.removeprefix("queued:")
    claimed_at = datetime(2026, 6, 15, 11, 59, tzinfo=timezone.utc)

    assert claim_proactive_worker_job(account_store, account_id, item_id, now=claimed_at)
    assert recover_stale_proactive_dispatching_items(
        account_store,
        account_id,
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
    ) == ()
    item = account_store.read_proactive_outbox(account_id)[0]
    assert item["status"] == "dispatching"
    assert item["dispatching_at"] == "2026-06-15T11:59:00+00:00"
    assert item["dispatch_attempts"] == 1


def test_dispatch_recovers_stale_claim_after_worker_crash(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="crash_recovery",
        message_text="Bitte nicht verlieren",
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
    calls = []

    async def sender(route: dict, action: SendText, item: dict) -> str:
        calls.append((route, action, item))
        return "recovered-ref"

    results = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"signal": sender},
            now=datetime(2026, 6, 15, 11, 31, tzinfo=timezone.utc),
        )
    )

    assert len(calls) == 1
    assert results[0].status == "sent"
    assert results[0].message_ref == "recovered-ref"
    item = account_store.read_proactive_outbox(account_id)[0]
    assert item["status"] == "sent"
    assert item["dispatch_attempts"] == 2
    assert "dispatching_at" not in item
    assert [entry["status"] for entry in item["status_history"]] == ["queued", "dispatching", "queued", "dispatching", "sent"]
    assert item["status_history"][2]["reason"] == "stale_dispatch_reclaimed_after_30_minutes"


def test_dispatch_reschedules_recurring_user_reminder_after_successful_send(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="user_requested_reminder",
        message_text="Du wolltest erinnert werden: Wasser trinken",
        due_at="2026-06-15T11:00:00+00:00",
        now=now,
        recurrence="daily",
        user_requested=True,
    )

    results = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"signal": lambda _route, _action, _item: "123456789"},
            now=now,
        )
    )

    item_id = queued.reason.removeprefix("queued:")
    assert [result.item_id for result in results] == [item_id]
    assert results[0].status == "sent"
    item = account_store.read_proactive_outbox(account_id)[0]
    assert item["id"] == item_id
    assert item["status"] == "queued"
    assert item["user_requested_reminder"] is True
    assert item["recurrence"] == "daily"
    assert item["due_at"] == "2026-06-16T11:00:00+00:00"
    assert item["sent_at"] == "2026-06-15T12:00:00+00:00"
    assert item["recurrence_count"] == 1
    assert item["status_history"][-2]["status"] == "sent"
    assert item["status_history"][-1] == {"at": "2026-06-15T12:00:00+00:00", "status": "queued", "reason": "recurrence:daily"}
    assert due_proactive_outbox_items(account_store, account_id, now=now) == ()
    assert due_proactive_outbox_items(account_store, account_id, now=datetime(2026, 6, 16, 11, tzinfo=timezone.utc))[0]["id"] == item_id


def test_dispatch_reschedules_month_interval_recurring_reminder(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    now = datetime(2026, 1, 31, 12, tzinfo=timezone.utc)
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="user_requested_reminder",
        message_text="Abrechnung",
        due_at="2026-01-31T11:00:00+00:00",
        now=now,
        recurrence="every 2 months",
        user_requested=True,
    )

    results = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"signal": lambda _route, _action, _item: "123456789"},
            now=now,
        )
    )

    item_id = queued.reason.removeprefix("queued:")
    assert results[0].status == "sent"
    item = account_store.read_proactive_outbox(account_id)[0]
    assert item["id"] == item_id
    assert item["recurrence"] == "every 2 months"
    assert item["due_at"] == "2026-03-31T11:00:00+00:00"


def test_dispatch_expires_stale_queued_items_before_sending(tmp_path) -> None:
    account_store = store(tmp_path)
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
    calls = []

    async def sender(route: dict, action: SendText, item: dict) -> str:
        calls.append((route, action, item))
        return "sent-ref"

    results = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"signal": sender},
            now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
        )
    )

    assert results == ()
    assert calls == []
    item = account_store.read_proactive_outbox(account_id)[0]
    assert item["id"] == queued.reason.removeprefix("queued:")
    assert item["status"] == "expired"


def test_dispatch_recheck_does_not_count_current_queued_item_against_daily_limit(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    state = enable_proactive_agent(account_store, account_id, categories=("reminder",))
    state["policy"]["max_messages_per_day"] = 1
    account_store.write_agent_state(account_id, state)
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Ping",
        due_at="2026-06-15T11:00:00+00:00",
        now=now,
    )
    assert queued.allowed is True

    results = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"signal": lambda _route, _action, _item: "sent-ref"},
            now=now,
        )
    )

    assert results[0].status == "sent"
    assert account_store.read_proactive_outbox(account_id)[0]["status"] == "sent"


def test_dispatch_skips_queued_item_when_stored_route_becomes_stale(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Ping",
        due_at="2026-06-15T11:00:00+00:00",
        now=now,
    )
    item_id = queued.reason.removeprefix("queued:")
    account_store.update_identity_route(identity, channel="signal", chat_id="+492", chat_type="private", adapter_slot=1)

    async def sender(_route: dict, _action: SendText, _item: dict) -> str:
        raise AssertionError("stale proactive route was sent")

    results = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"signal": sender},
            now=now,
        )
    )

    assert len(results) == 1
    assert results[0].item_id == item_id
    assert results[0].status == "skipped"
    assert results[0].reason == "stale_route"
    item = account_store.read_proactive_outbox(account_id)[0]
    assert item["status"] == "skipped"
    assert item["status_history"][-1]["reason"] == "policy:stale_route"


def test_dispatch_skips_stale_outbox_snapshot_without_sending(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Ping",
        due_at="2026-06-15T11:00:00+00:00",
        now=now,
    )
    item_id = queued.reason.removeprefix("queued:")
    stale_item = dict(account_store.read_proactive_outbox(account_id)[0])
    update_proactive_outbox_item_status(account_store, account_id, item_id, status="cancelled", reason="user_cancelled", now=now)
    monkeypatch.setattr(
        "TeeBotus.runtime.proactive_agent.due_proactive_outbox_items",
        lambda _store, _account_id, *, now=None: (stale_item,),
    )

    async def sender(_route: dict, _action: SendText, _item: dict) -> str:
        raise AssertionError("stale proactive outbox item was sent")

    results = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"signal": sender},
            now=now,
        )
    )

    assert len(results) == 1
    assert results[0].item_id == item_id
    assert results[0].status == "skipped"
    assert results[0].reason == "stale_outbox_item"
    assert account_store.read_proactive_outbox(account_id)[0]["status"] == "cancelled"


def test_dispatch_skips_item_that_was_snoozed_after_due_snapshot(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Ping",
        due_at="2026-06-15T11:00:00+00:00",
        now=now,
    )
    stale_item = dict(account_store.read_proactive_outbox(account_id)[0])
    current_rows = account_store.read_proactive_outbox(account_id)
    current_rows[0]["due_at"] = "2026-06-15T14:00:00+00:00"
    account_store.write_proactive_outbox(account_id, current_rows)
    monkeypatch.setattr(
        "TeeBotus.runtime.proactive_agent.due_proactive_outbox_items",
        lambda _store, _account_id, *, now=None: (stale_item,),
    )

    async def sender(_route: dict, _action: SendText, _item: dict) -> str:
        raise AssertionError("snoozed proactive outbox item was sent")

    results = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"signal": sender},
            now=now,
        )
    )

    assert len(results) == 1
    assert results[0].status == "skipped"
    assert results[0].reason == "stale_outbox_item"
    assert account_store.read_proactive_outbox(account_id)[0]["due_at"] == "2026-06-15T14:00:00+00:00"


def test_dispatch_does_not_overwrite_item_cancelled_during_send(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Ping",
        due_at="2026-06-15T11:00:00+00:00",
        now=now,
    )
    item_id = queued.reason.removeprefix("queued:")
    tracker = MessageTracker(tmp_path / "refs.json")

    async def sender(_route: dict, _action: SendText, _item: dict) -> str:
        update_proactive_outbox_item_status(
            account_store,
            account_id,
            item_id,
            status="cancelled",
            reason="cancelled_during_send",
            now=now,
        )
        return "sent-ref"

    results = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"signal": sender},
            now=now,
            message_tracker=tracker,
            instance_name="Depressionsbot",
        )
    )

    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].reason == "status_update_failed"
    item = account_store.read_proactive_outbox(account_id)[0]
    assert item["status"] == "cancelled"
    assert item["status_history"][-1]["reason"] == "cancelled_during_send"
    assert tracker.list_for_chat("+491", instance_name="Depressionsbot", channel="signal") == []


def test_dispatch_fails_invalid_due_at_without_sending(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    queued = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Ping",
        due_at="not-a-date",
        now=now,
    )
    calls = []

    async def sender(route: dict, action: SendText, item: dict) -> str:
        calls.append((route, action, item))
        return "sent-ref"

    results = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"signal": sender},
            now=now,
        )
    )

    item_id = queued.reason.removeprefix("queued:")
    assert [result.item_id for result in results] == [item_id]
    assert results[0].status == "failed"
    assert results[0].reason == "invalid_due_at"
    assert calls == []
    item = account_store.read_proactive_outbox(account_id)[0]
    assert item["status"] == "failed"
    assert item["status_history"][-1]["reason"] == "invalid_due_at"


def test_dispatch_due_proactive_items_fails_when_sender_is_missing(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Ping",
        due_at="2026-06-15T11:00:00+00:00",
        now=now,
    )

    results = asyncio.run(
        dispatch_due_proactive_outbox_items(account_store, account_id, senders={}, now=now)
    )

    assert results[0].status == "failed"
    assert results[0].reason == "missing_sender"
    item = account_store.read_proactive_outbox(account_id)[0]
    assert item["status"] == "failed"
    assert item["status_history"][-1]["reason"] == "missing_sender:signal"


def test_dispatch_due_proactive_items_finds_sender_case_insensitive(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Ping",
        due_at="2026-06-15T11:00:00+00:00",
        now=now,
    )
    calls: list[tuple[dict[str, Any], object, dict[str, Any]]] = []

    async def sender(route: dict, action, item: dict) -> str:
        calls.append((route, action, item))
        return "sent-ref"

    results = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"Signal": sender},
            now=now,
        )
    )

    assert len(results) == 1
    assert results[0].status == "sent"
    assert calls


def test_dispatch_due_proactive_items_fails_when_sender_is_non_callable(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Ping",
        due_at="2026-06-15T11:00:00+00:00",
        now=now,
    )

    results = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"signal": 42},
            now=now,
        )
    )

    assert results[0].status == "failed"
    assert results[0].reason == "invalid_sender"
    item = account_store.read_proactive_outbox(account_id)[0]
    assert item["status"] == "failed"
    assert item["status_history"][-1]["reason"] == "invalid_sender"


def test_dispatch_due_proactive_items_fails_with_non_mapping_route(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Ping",
        due_at="2026-06-15T11:00:00+00:00",
        now=now,
    )

    rows = account_store.read_proactive_outbox(account_id)
    rows[0]["route"] = "not-a-mapping"
    account_store.write_proactive_outbox(account_id, rows)

    async def sender(route: dict, action: SendText, item: dict) -> str:
        raise AssertionError("sender must not be called")

    results = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"signal": sender},
            now=now,
        )
    )

    assert results[0].status == "failed"
    assert results[0].reason == "invalid_route"
    item = account_store.read_proactive_outbox(account_id)[0]
    assert item["status"] == "failed"
    assert item["status_history"][-1]["reason"] == "invalid_route"


def test_dispatch_due_proactive_items_rejects_invalid_route_adapter_slot(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Ping",
        due_at="2026-06-15T11:00:00+00:00",
        now=now,
    )
    rows = account_store.read_proactive_outbox(account_id)
    rows[0]["route"]["adapter_slot"] = "broken"
    account_store.write_proactive_outbox(account_id, rows)

    async def sender(route: dict, action: SendText, item: dict) -> str:
        raise AssertionError("sender must not be called")

    results = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"signal": sender},
            now=now,
        )
    )

    assert results[0].status == "skipped"
    assert results[0].reason == "invalid_route"
    assert account_store.read_proactive_outbox(account_id)[0]["status"] == "skipped"


@pytest.mark.parametrize(
    ("channel", "identity", "chat_id", "message_ref", "ref_kind"),
    [
        ("telegram", telegram_identity_key(1001), "1001", "42", "telegram_message_id"),
        ("signal", signal_identity_key(source_uuid="signal-user"), "+491", "123456789", "signal_timestamp"),
        ("matrix", matrix_identity_key("@user:example.org"), "!room:example.org", "$event", "matrix_event_id"),
    ],
)
def test_dispatch_tracks_sent_refs_for_all_supported_channels(tmp_path, channel: str, identity: str, chat_id: str, message_ref: str, ref_kind: str) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel=channel, chat_id=chat_id, chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="follow_up",
        message_text="Ping",
        due_at="2026-06-15T11:00:00+00:00",
        now=now,
    )
    tracker = MessageTracker(tmp_path / f"{channel}_refs.json")

    results = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={channel: lambda _route, _action, _item: message_ref},
            now=now,
            message_tracker=tracker,
            instance_name="Depressionsbot",
        )
    )

    assert results[0].channel == channel
    assert results[0].message_ref == message_ref
    refs = tracker.list_for_chat(chat_id, instance_name="Depressionsbot", channel=channel)
    assert len(refs) == 1
    assert refs[0].ref_kind == ref_kind
