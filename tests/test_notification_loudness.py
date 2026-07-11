from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import threading

from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, StaticSecretProvider, telegram_identity_key
from TeeBotus.runtime.actions import DelaySeconds, SendText
from TeeBotus.runtime.activity_profile import record_account_activity
from TeeBotus.runtime.engine import TeeBotusEngine
from TeeBotus.runtime.events import IncomingEvent
from TeeBotus.runtime.notification_loudness import (
    NOTIFICATION_LOUDNESS_PROMPT,
    NOTIFICATION_LOUDNESS_SYSTEM_ITEM,
    maybe_handle_notification_loudness_response,
    maybe_notification_loudness_prompt_action,
    notification_loudness_outbox_item_is_active,
    queue_due_notification_loudness_prompts,
    _notification_loudness_decision,
    _route_recently_seen,
    _route_slot,
)
from TeeBotus.runtime.proactive_agent import check_proactive_agent_account, dispatch_due_proactive_outbox_items

LOCAL = timezone(timedelta(hours=2))


class FixedWakeDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 6, 15, 12, tzinfo=timezone.utc)
        return value if tz is None else value.astimezone(tz)


def store(tmp_path) -> AccountStore:
    return AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"n" * 32))


def event(identity_key: str, text: str = "Hallo") -> IncomingEvent:
    return event_with_chat_type(identity_key, text=text, chat_type="private")


def event_with_chat_type(identity_key: str, text: str = "Hallo", chat_type: str = "private") -> IncomingEvent:
    return IncomingEvent(
        event_id="telegram:1",
        instance="Depressionsbot",
        channel="telegram",
        adapter_slot=1,
        account_id="",
        identity_key=identity_key,
        chat_id="chat-1",
        chat_type=chat_type,
        sender_id=identity_key,
        sender_name=identity_key,
        text=text,
        message_ref="1",
    )


def test_engine_asks_user_to_unmute_in_private_chat_type_variant(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("TeeBotus.runtime.notification_loudness.datetime", FixedWakeDatetime)
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    prepare_account_with_route(account_store, identity)
    engine = TeeBotusEngine(account_store=account_store)

    actions = engine.process(event_with_chat_type(identity, "/ping", chat_type="Private"))

    assert len(actions) == 20
    assert [action.text for action in actions if isinstance(action, SendText)][:10] == ["Pong"] * 10
    assert sum(isinstance(action, DelaySeconds) for action in actions) == 9
    assert actions[-1].text == NOTIFICATION_LOUDNESS_PROMPT


def prepare_account_with_route(account_store: AccountStore, identity: str) -> str:
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="chat-1", chat_type="private", adapter_slot=1)
    return account_id


def set_identity_last_seen(account_store: AccountStore, identity: str, when: datetime) -> None:
    identities = account_store._load_identities()
    payload = identities[identity]
    timestamp = when.isoformat(timespec="seconds")
    payload["last_seen_at"] = timestamp
    payload["last_route"]["last_seen_at"] = timestamp
    identities[identity] = payload
    account_store._save_identities(identities)


def test_engine_asks_user_to_unmute_bot_messages_once_route_exists(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("TeeBotus.runtime.notification_loudness.datetime", FixedWakeDatetime)
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    prepare_account_with_route(account_store, identity)
    engine = TeeBotusEngine(account_store=account_store)

    actions = engine.process(event(identity, "/ping"))

    assert len(actions) == 20
    assert [action.text for action in actions if isinstance(action, SendText)][:10] == ["Pong"] * 10
    assert sum(isinstance(action, DelaySeconds) for action in actions) == 9
    assert actions[-1].text == NOTIFICATION_LOUDNESS_PROMPT
    assert [button.label for button in actions[-1].buttons] == ["Ja, ist laut", "Nein"]
    state = account_store.read_agent_state(account_store.get_account_for_identity(identity) or "")
    route_state = state["notification_loudness"]["routes"]["telegram:1:chat-1"]
    assert route_state["status"] == "pending"
    assert route_state["prompted_windows_by_date"]


def test_engine_stops_notification_loudness_prompt_after_confirmation(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    prompt = maybe_notification_loudness_prompt_action(event(identity), account_store, account_id, now=now)
    assert prompt is not None
    engine = TeeBotusEngine(account_store=account_store)

    actions = engine.process(event(identity, "ja, laut"))
    later_prompt = maybe_notification_loudness_prompt_action(event(identity), account_store, account_id, now=now + timedelta(days=2))

    assert len(actions) == 1
    assert actions[0].text == "Danke, ich frage deswegen nicht weiter nach."
    assert later_prompt is None
    state = account_store.read_agent_state(account_id)
    route_state = state["notification_loudness"]["routes"]["telegram:1:chat-1"]
    assert route_state["status"] == "confirmed"
    assert route_state["checks_active"] is False
    assert route_state["checks_stop_reason"] == "confirmed"


def test_scheduler_stops_online_check_after_notification_loudness_confirmation(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    now = datetime(2026, 6, 15, 8, tzinfo=timezone.utc)
    set_identity_last_seen(account_store, identity, now)
    assert maybe_notification_loudness_prompt_action(event(identity), account_store, account_id, now=now) is not None
    engine = TeeBotusEngine(account_store=account_store)
    assert engine.process(event(identity, "ja, laut"))[0].text == "Danke, ich frage deswegen nicht weiter nach."
    set_identity_last_seen(account_store, identity, now + timedelta(hours=7))

    def fail_contact_timing(*_args, **_kwargs):
        raise AssertionError("online/contact timing check should stop after notification loudness is decided")

    monkeypatch.setattr("TeeBotus.runtime.notification_loudness.contact_timing_decision", fail_contact_timing)

    due = queue_due_notification_loudness_prompts(account_store, account_id, now=now + timedelta(hours=7))

    assert due == ()
    route_state = account_store.read_agent_state(account_id)["notification_loudness"]["routes"]["telegram:1:chat-1"]
    assert route_state["checks_active"] is False
    assert route_state["checks_stop_reason"] == "confirmed"


def test_scheduler_refreshes_route_state_for_legacy_channel_case(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="chat-1", chat_type="private", adapter_slot=1)
    now = datetime(2026, 6, 15, 10, tzinfo=timezone.utc)
    set_identity_last_seen(account_store, identity, now)
    state = account_store.read_agent_state(account_id)
    state["notification_loudness"] = {
        "schema_version": 1,
        "routes": {
            "TeLegram:1:chat-1": {
                "status": "pending",
                "route_key": "TeLegram:1:chat-1",
                "route": {
                    "channel": "TeLegram",
                    "chat_id": "chat-1",
                    "chat_type": "Private",
                    "adapter_slot": 1,
                },
                "identity_key": identity,
            }
        },
    }
    account_store.write_agent_state(account_id, state)

    monkeypatch.setattr(
        "TeeBotus.runtime.notification_loudness.contact_timing_decision",
        lambda *_args, **_kwargs: type("Decision", (), {"allowed": True, "reason": "test", "profile": {}})(),
    )

    due = queue_due_notification_loudness_prompts(account_store, account_id, now=now)
    outbox = account_store.read_proactive_outbox(account_id)
    state = account_store.read_agent_state(account_id)
    route_state = state["notification_loudness"]["routes"]["TeLegram:1:chat-1"]

    assert outbox
    assert due == (outbox[0]["id"],)
    assert outbox[0]["route"]["channel"] == "telegram"
    assert route_state["route"]["channel"] == "telegram"


def test_response_normalizes_legacy_route_key_and_status(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    now = datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    assert maybe_notification_loudness_prompt_action(event(identity), account_store, account_id, now=now) is not None

    state = account_store.read_agent_state(account_id)
    route_state = state["notification_loudness"]["routes"].pop("telegram:1:chat-1")
    route_state["route_key"] = "TeLegram:1:chat-1"
    route_state["route"]["channel"] = "TeLegram"
    route_state["status"] = "PENDING"
    state["notification_loudness"]["routes"]["TeLegram:1:chat-1"] = route_state
    account_store.write_agent_state(account_id, state)
    account_store.append_proactive_outbox_item(
        account_id,
        {
            "status": "queued",
            "category": "system",
            "intent": "notification_loudness_check",
            "message_text": NOTIFICATION_LOUDNESS_PROMPT,
            "system_item": "notification_loudness",
            "route_key": "TeLegram:1:chat-1",
            "route": {"channel": "TeLegram", "chat_id": "chat-1", "chat_type": "Private", "adapter_slot": 1},
            "due_at": now.isoformat(timespec="seconds"),
        },
    )

    actions = maybe_handle_notification_loudness_response(event(identity, "ja"), account_store, account_id, now=now)

    assert actions is not None
    assert actions[0].text == "Danke, ich frage deswegen nicht weiter nach."
    stored_route = account_store.read_agent_state(account_id)["notification_loudness"]["routes"]["TeLegram:1:chat-1"]
    assert stored_route["status"] == "confirmed"
    assert account_store.read_proactive_outbox(account_id)[0]["status"] == "cancelled"


def test_response_ignores_private_route_that_is_no_longer_current(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    now = datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    assert maybe_notification_loudness_prompt_action(event(identity), account_store, account_id, now=now) is not None
    account_store.update_identity_route(identity, channel="telegram", chat_id="chat-2", chat_type="private", adapter_slot=1)

    assert maybe_handle_notification_loudness_response(event(identity, "ja"), account_store, account_id, now=now) is None
    route_state = account_store.read_agent_state(account_id)["notification_loudness"]["routes"]["telegram:1:chat-1"]
    assert route_state["status"] == "pending"


def test_scheduler_persists_legacy_route_refresh_when_prompt_is_not_due(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    now = datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    set_identity_last_seen(account_store, identity, now - timedelta(hours=1))
    state = account_store.read_agent_state(account_id)
    state["notification_loudness"] = {
        "schema_version": 1,
        "routes": {
            "TeLegram:1:chat-1": {
                "status": "pending",
                "route_key": "TeLegram:1:chat-1",
                "route": {
                    "channel": "TeLegram",
                    "chat_id": "chat-1",
                    "chat_type": "Private",
                    "adapter_slot": 1,
                    "last_seen_at": (now - timedelta(hours=1)).isoformat(timespec="seconds"),
                },
                "identity_key": identity,
            }
        },
    }
    account_store.write_agent_state(account_id, state)
    monkeypatch.setattr(
        "TeeBotus.runtime.notification_loudness.contact_timing_decision",
        lambda *_args, **_kwargs: type("Decision", (), {"allowed": True, "reason": "test", "profile": {}})(),
    )

    assert queue_due_notification_loudness_prompts(account_store, account_id, now=now) == ()
    stored_route = account_store.read_agent_state(account_id)["notification_loudness"]["routes"]["TeLegram:1:chat-1"]["route"]
    assert stored_route["channel"] == "telegram"


def test_prompt_does_not_resurrect_case_variant_terminal_route(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    state = account_store.read_agent_state(account_id)
    state["notification_loudness"] = {
        "schema_version": 1,
        "routes": {
            "TeLegram:1:chat-1": {
                "status": "DECLINED",
                "route_key": "TeLegram:1:chat-1",
                "route": {"channel": "TeLegram", "chat_id": "chat-1", "chat_type": "Private", "adapter_slot": 1},
                "identity_key": identity,
            }
        },
    }
    account_store.write_agent_state(account_id, state)

    assert maybe_notification_loudness_prompt_action(
        event(identity), account_store, account_id, now=datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    ) is None
    stored_route = account_store.read_agent_state(account_id)["notification_loudness"]["routes"]["TeLegram:1:chat-1"]
    assert stored_route["status"] == "DECLINED"


def test_scheduler_does_not_online_check_unknown_notification_loudness_routes(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    state = account_store.read_agent_state(account_id)
    state["notification_loudness"] = {
        "schema_version": 1,
        "routes": {
            "telegram:1:chat-1": {
                "status": "unknown",
                "route_key": "telegram:1:chat-1",
                "route": {"channel": "telegram", "chat_id": "chat-1", "chat_type": "private", "adapter_slot": 1},
                "identity_key": identity,
            }
        },
    }
    account_store.write_agent_state(account_id, state)
    set_identity_last_seen(account_store, identity, datetime(2026, 6, 15, 15, tzinfo=timezone.utc))

    def fail_contact_timing(*_args, **_kwargs):
        raise AssertionError("unknown routes should not start online/contact timing checks")

    monkeypatch.setattr("TeeBotus.runtime.notification_loudness.contact_timing_decision", fail_contact_timing)

    due = queue_due_notification_loudness_prompts(account_store, account_id, now=datetime(2026, 6, 15, 15, tzinfo=timezone.utc))

    assert due == ()


def test_scheduler_queues_notification_loudness_follow_up_when_recently_active_in_next_wake_half(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    now = datetime(2026, 6, 15, 8, tzinfo=timezone.utc)
    set_identity_last_seen(account_store, identity, now)
    assert maybe_notification_loudness_prompt_action(event(identity), account_store, account_id, now=now) is not None

    same_wake_half = queue_due_notification_loudness_prompts(account_store, account_id, now=now + timedelta(hours=1))
    second_wake_half = now + timedelta(hours=7)
    stale_online_state = queue_due_notification_loudness_prompts(account_store, account_id, now=second_wake_half)
    set_identity_last_seen(account_store, identity, second_wake_half - timedelta(minutes=4))
    due = queue_due_notification_loudness_prompts(account_store, account_id, now=second_wake_half)
    duplicate = queue_due_notification_loudness_prompts(account_store, account_id, now=second_wake_half + timedelta(minutes=1))

    assert same_wake_half == ()
    assert stale_online_state == ()
    assert len(due) == 1
    assert duplicate == ()
    row = account_store.read_proactive_outbox(account_id)[0]
    assert row["system_item"] == "notification_loudness"
    assert row["message_text"] == NOTIFICATION_LOUDNESS_PROMPT
    assert row["route"]["chat_id"] == "chat-1"
    state = account_store.read_agent_state(account_id)
    windows = state["notification_loudness"]["routes"]["telegram:1:chat-1"]["prompted_windows_by_date"]["2026-06-15"]
    assert windows == ["first", "second"]
    assert check_proactive_agent_account(account_store, account_id).ok is True


def test_scheduler_respects_adaptive_activity_profile_for_notification_loudness(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    for day in (8, 9, 10, 11, 12, 15):
        record_account_activity(account_store, account_id, event(identity, text="Morgens bin ich erreichbar."), now=datetime(2026, 6, day, 9, 0, tzinfo=LOCAL))
    now = datetime(2026, 6, 15, 8, 0, tzinfo=LOCAL)
    assert maybe_notification_loudness_prompt_action(event(identity), account_store, account_id, now=now) is not None
    late_same_day = datetime(2026, 6, 15, 17, 0, tzinfo=LOCAL)
    set_identity_last_seen(account_store, identity, late_same_day - timedelta(minutes=2))

    due = queue_due_notification_loudness_prompts(account_store, account_id, now=late_same_day)

    assert due == ()


def test_notification_loudness_system_item_dispatches_without_proactive_consent(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    now = datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    assert maybe_notification_loudness_prompt_action(event(identity), account_store, account_id, now=now - timedelta(hours=7)) is not None
    set_identity_last_seen(account_store, identity, now)
    queue_due_notification_loudness_prompts(account_store, account_id, now=now)
    sent: list[SendText] = []

    async def sender(_route, action, _item):
        sent.append(action)
        return "msg-1"

    result = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"telegram": sender},
            now=now,
        )
    )

    assert result[0].status == "sent"
    assert sent[0].text == NOTIFICATION_LOUDNESS_PROMPT


def test_terminal_loudness_route_blocks_legacy_queued_prompt(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    now = datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    maybe_notification_loudness_prompt_action(event(identity), account_store, account_id, now=now)
    state = account_store.read_agent_state(account_id)
    state["notification_loudness"]["routes"]["telegram:1:chat-1"]["status"] = "confirmed"
    account_store.write_agent_state(account_id, state)
    account_store.append_proactive_outbox_item(
        account_id,
        {
            "status": "queued",
            "category": "system",
            "intent": "notification_loudness_check",
            "message_text": NOTIFICATION_LOUDNESS_PROMPT,
            "system_item": "notification_loudness",
            "route_key": "telegram:1:chat-1",
            "route": {"channel": "telegram", "chat_id": "chat-1", "chat_type": "private", "adapter_slot": 1},
            "due_at": now.isoformat(timespec="seconds"),
        },
    )
    sent: list[SendText] = []

    async def sender(_route, action, _item):
        sent.append(action)
        return "should-not-send"

    result = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"telegram": sender},
            now=now,
        )
    )

    assert sent == []
    assert result[0].status == "skipped"
    assert result[0].reason == "notification_loudness_decided"
    assert account_store.read_proactive_outbox(account_id)[0]["status"] == "skipped"


def test_dispatch_rechecks_loudness_after_worker_claim(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    now = datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    prompt_now = now - timedelta(hours=7)
    assert maybe_notification_loudness_prompt_action(event(identity), account_store, account_id, now=prompt_now) is not None
    set_identity_last_seen(account_store, identity, now)
    assert queue_due_notification_loudness_prompts(account_store, account_id, now=now)

    import TeeBotus.runtime.proactive_agent as proactive_agent

    original_claim = proactive_agent.claim_proactive_worker_job

    def claim_then_confirm(current_store, current_account_id, item_id, *, now=None):
        claimed = original_claim(current_store, current_account_id, item_id, now=now)
        assert maybe_handle_notification_loudness_response(
            event(identity, "ja, laut"), current_store, current_account_id, now=now
        ) is not None
        return claimed

    monkeypatch.setattr(proactive_agent, "claim_proactive_worker_job", claim_then_confirm)
    sent: list[SendText] = []

    async def sender(_route, action, _item):
        sent.append(action)
        return "message-ref"

    result = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"telegram": sender},
            now=now,
        )
    )

    assert sent == []
    assert result[0].status == "skipped"
    assert result[0].reason == "notification_loudness_decided"
    assert account_store.read_proactive_outbox(account_id)[0]["status"] == "cancelled"


def test_dispatch_fails_loudness_item_when_post_claim_state_is_unavailable(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    now = datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    assert maybe_notification_loudness_prompt_action(event(identity), account_store, account_id, now=now - timedelta(hours=7)) is not None
    set_identity_last_seen(account_store, identity, now)
    assert queue_due_notification_loudness_prompts(account_store, account_id, now=now)

    import TeeBotus.runtime.proactive_agent as proactive_agent

    calls = 0

    def flaky_loudness_state(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls >= 3:
            raise AccountStoreError("notification loudness state unavailable")
        return True

    monkeypatch.setattr(proactive_agent, "notification_loudness_outbox_item_is_active", flaky_loudness_state)
    sent: list[SendText] = []

    async def sender(_route, action, _item):
        sent.append(action)
        return "message-ref"

    result = asyncio.run(
        dispatch_due_proactive_outbox_items(
            account_store,
            account_id,
            senders={"telegram": sender},
            now=now,
        )
    )

    assert sent == []
    assert result[0].status == "failed"
    assert result[0].reason == "notification_loudness_state_unavailable"
    assert account_store.read_proactive_outbox(account_id)[0]["status"] == "failed"


def test_queued_loudness_item_requires_explicit_pending_route_state(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    item = {"route_key": "telegram:1:chat-1"}

    assert notification_loudness_outbox_item_is_active(account_store, account_id, item) is False

    state = account_store.read_agent_state(account_id)
    state["notification_loudness"] = {"routes": {"telegram:1:chat-1": {"status": "unknown"}}}
    account_store.write_agent_state(account_id, state)
    assert notification_loudness_outbox_item_is_active(account_store, account_id, item) is False

    state["notification_loudness"]["routes"]["telegram:1:chat-1"] = {
        "status": "pending",
        "checks_active": False,
    }
    account_store.write_agent_state(account_id, state)
    assert notification_loudness_outbox_item_is_active(account_store, account_id, item) is False

    state["notification_loudness"]["routes"]["telegram:1:chat-1"] = {
        "status": "pending",
        "checks_active": "false",
    }
    account_store.write_agent_state(account_id, state)
    assert notification_loudness_outbox_item_is_active(account_store, account_id, item) is False

    state["notification_loudness"]["routes"]["telegram:1:chat-1"] = {"status": "pending"}
    account_store.write_agent_state(account_id, state)
    assert notification_loudness_outbox_item_is_active(account_store, account_id, item) is True


def test_loudness_route_slot_rejects_invalid_values() -> None:
    assert _route_slot(None) == 1
    assert _route_slot(" 2 ") == 2
    assert _route_slot(True) is None
    assert _route_slot("invalid") is None
    assert _route_slot(0) is None


def test_loudness_online_check_accepts_naive_utc_now() -> None:
    route = {"last_seen_at": "2026-06-15T12:00:00+00:00"}

    assert _route_recently_seen(route, datetime(2026, 6, 15, 12, 4)) is True


def test_loudness_scheduler_fails_closed_on_invalid_agent_state(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)

    original_read = account_store.read_agent_state
    account_store.read_agent_state = lambda _account_id: []  # type: ignore[method-assign]

    assert queue_due_notification_loudness_prompts(account_store, account_id) == ()
    assert maybe_notification_loudness_prompt_action(event(identity), account_store, account_id) is None
    assert maybe_handle_notification_loudness_response(event(identity, "ja, laut"), account_store, account_id) is None

    account_store.read_agent_state = original_read  # type: ignore[method-assign]


def test_loudness_scheduler_does_not_queue_when_checks_are_inactive(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    now = datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    set_identity_last_seen(account_store, identity, now - timedelta(minutes=2))
    state = account_store.read_agent_state(account_id)
    state["notification_loudness"] = {
        "schema_version": 1,
        "routes": {
            "telegram:1:chat-1": {
                "status": "pending",
                "checks_active": "false",
                "route": {
                    "channel": "telegram",
                    "chat_id": "chat-1",
                    "chat_type": "private",
                    "adapter_slot": 1,
                },
            }
        },
    }
    account_store.write_agent_state(account_id, state)

    assert queue_due_notification_loudness_prompts(account_store, account_id, now=now) == ()
    assert account_store.read_proactive_outbox(account_id) == []


def test_loudness_free_text_prioritizes_explicit_negation() -> None:
    assert _notification_loudness_decision(
        "Nein, ich habe die Nachrichten nicht laut gestellt",
        pending=True,
    ) == "declined"
    assert _notification_loudness_decision("noch nicht", pending=True) == "declined"
    assert _notification_loudness_decision("ja, laut gestellt", pending=True) == "confirmed"


def test_loudness_scheduler_does_not_duplicate_dispatching_prompt(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    now = datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    assert maybe_notification_loudness_prompt_action(
        event(identity), account_store, account_id, now=now - timedelta(hours=7)
    ) is not None
    set_identity_last_seen(account_store, identity, now - timedelta(minutes=4))
    account_store.append_proactive_outbox_item(
        account_id,
        {
            "status": "dispatching",
            "system_item": NOTIFICATION_LOUDNESS_SYSTEM_ITEM,
            "route_key": "telegram:1:chat-1",
            "route": {"channel": "telegram", "chat_id": "chat-1", "chat_type": "private", "adapter_slot": 1},
        },
    )

    assert queue_due_notification_loudness_prompts(account_store, account_id, now=now) == ()
    assert len(account_store.read_proactive_outbox(account_id)) == 1


def test_concurrent_loudness_scheduler_runs_queue_only_one_prompt(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    now = datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    assert maybe_notification_loudness_prompt_action(event(identity), account_store, account_id, now=now - timedelta(hours=7)) is not None
    set_identity_last_seen(account_store, identity, now - timedelta(minutes=4))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: queue_due_notification_loudness_prompts(account_store, account_id, now=now),
                (1, 2),
            )
        )

    assert sum(len(result) for result in results) == 1
    assert len(account_store.read_proactive_outbox(account_id)) == 1


def test_concurrent_incoming_messages_prompt_only_once(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    now = datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    incoming_event = event(identity)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: maybe_notification_loudness_prompt_action(incoming_event, account_store, account_id, now=now),
                (1, 2),
            )
        )

    assert sum(result is not None for result in results) == 1
    route_state = account_store.read_agent_state(account_id)["notification_loudness"]["routes"]["telegram:1:chat-1"]
    assert route_state["status"] == "pending"
    assert route_state["prompted_windows_by_date"]["2026-06-15"] == ["second"]


def test_concurrent_loudness_confirmations_reply_only_once(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    incoming_event = event(identity, "ja, laut")
    assert maybe_notification_loudness_prompt_action(
        event(identity), account_store, account_id, now=datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    ) is not None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: maybe_handle_notification_loudness_response(
                    incoming_event,
                    account_store,
                    account_id,
                    now=datetime(2026, 6, 15, 15, tzinfo=timezone.utc),
                ),
                (1, 2),
            )
        )

    assert sum(result is not None for result in results) == 1
    route_state = account_store.read_agent_state(account_id)["notification_loudness"]["routes"]["telegram:1:chat-1"]
    assert route_state["status"] == "confirmed"


def test_scheduler_cannot_overwrite_concurrent_loudness_confirmation(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    now = datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    assert maybe_notification_loudness_prompt_action(event(identity), account_store, account_id, now=now) is not None
    set_identity_last_seen(account_store, identity, now)
    original_read = AccountStore.read_agent_state
    scheduler_read = threading.Event()
    responder_started = threading.Event()
    release_scheduler = threading.Event()
    errors: list[BaseException] = []

    def gated_read(current_store, current_account_id):
        value = original_read(current_store, current_account_id)
        if threading.current_thread().name == "loudness-scheduler":
            scheduler_read.set()
            if not release_scheduler.wait(timeout=2):
                raise AssertionError("scheduler read gate was not released")
        return value

    monkeypatch.setattr(AccountStore, "read_agent_state", gated_read)

    def run_scheduler() -> None:
        try:
            queue_due_notification_loudness_prompts(account_store, account_id, now=now)
        except BaseException as exc:  # pragma: no cover - only used to report thread failures.
            errors.append(exc)

    def run_responder() -> None:
        try:
            responder_started.set()
            maybe_handle_notification_loudness_response(event(identity, "ja, laut"), account_store, account_id, now=now)
        except BaseException as exc:  # pragma: no cover - only used to report thread failures.
            errors.append(exc)

    scheduler = threading.Thread(target=run_scheduler, name="loudness-scheduler")
    responder = threading.Thread(target=run_responder, name="loudness-responder")
    scheduler.start()
    assert scheduler_read.wait(timeout=1)
    responder.start()
    assert responder_started.wait(timeout=1)
    release_scheduler.set()
    scheduler.join(timeout=2)
    responder.join(timeout=2)

    assert errors == []
    assert not scheduler.is_alive()
    assert not responder.is_alive()
    route_state = account_store.read_agent_state(account_id)["notification_loudness"]["routes"]["telegram:1:chat-1"]
    assert route_state["status"] == "confirmed"
