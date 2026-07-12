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
    is_notification_loudness_outbox_item,
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


def test_loudness_paths_recheck_current_route_inside_outbox_lock(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    incoming_event = event(identity, "ja, laut")
    checks = iter((True, False, True, False))
    monkeypatch.setattr(
        "TeeBotus.runtime.notification_loudness._event_has_current_private_route",
        lambda *_args: next(checks),
    )

    assert maybe_handle_notification_loudness_response(incoming_event, account_store, account_id) is None
    assert maybe_notification_loudness_prompt_action(event(identity), account_store, account_id) is None


def test_loudness_paths_reject_event_for_different_account(tmp_path) -> None:
    account_store = store(tmp_path)
    first_identity = telegram_identity_key(1)
    second_identity = telegram_identity_key(2)
    first_account_id = prepare_account_with_route(account_store, first_identity)
    second_account_id = prepare_account_with_route(account_store, second_identity)
    now = datetime(2026, 6, 15, 15, tzinfo=timezone.utc)

    assert maybe_notification_loudness_prompt_action(
        event(first_identity), account_store, second_account_id, now=now
    ) is None
    assert maybe_handle_notification_loudness_response(
        event(first_identity, "ja, laut"), account_store, second_account_id, now=now
    ) is None
    assert "notification_loudness" not in account_store.read_agent_state(second_account_id)
    assert "notification_loudness" not in account_store.read_agent_state(first_account_id)


def test_loudness_paths_recheck_account_ownership_inside_outbox_lock(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    now = datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    assert maybe_notification_loudness_prompt_action(event(identity), account_store, account_id, now=now) is not None

    original_lookup = account_store.get_account_for_identity
    ownership_results = iter((account_id, None))
    monkeypatch.setattr(account_store, "get_account_for_identity", lambda _identity: next(ownership_results))
    assert maybe_handle_notification_loudness_response(
        event(identity, "ja, laut"), account_store, account_id, now=now
    ) is None

    monkeypatch.setattr(account_store, "get_account_for_identity", original_lookup)
    route_state = account_store.read_agent_state(account_id)["notification_loudness"]["routes"]["telegram:1:chat-1"]
    assert route_state["status"] == "pending"


def test_loudness_route_refresh_rejects_foreign_identity_key(tmp_path) -> None:
    account_store = store(tmp_path)
    account_identity = telegram_identity_key(1)
    foreign_identity = telegram_identity_key(2)
    account_id = prepare_account_with_route(account_store, account_identity)
    foreign_account_id = prepare_account_with_route(account_store, foreign_identity)
    account_store.update_identity_route(account_identity, channel="telegram", chat_id="chat-2", chat_type="private", adapter_slot=1)
    state = account_store.read_agent_state(account_id)
    state["notification_loudness"] = {
        "routes": {
            "telegram:1:chat-1": {
                "status": "pending",
                "checks_active": True,
                "identity_key": foreign_identity,
                "route": {"channel": "telegram", "chat_id": "chat-1", "chat_type": "private", "adapter_slot": 1},
            }
        }
    }
    account_store.write_agent_state(account_id, state)
    item = {
        "status": "queued",
        "system_item": NOTIFICATION_LOUDNESS_SYSTEM_ITEM,
        "route_key": "telegram:1:chat-1",
        "route": {"channel": "telegram", "chat_id": "chat-1", "chat_type": "private", "adapter_slot": 1},
    }

    assert notification_loudness_outbox_item_is_active(account_store, account_id, item) is False
    assert account_store.get_account_for_identity(foreign_identity) == foreign_account_id


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


def test_scheduler_does_not_queue_stale_identity_route(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    now = datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    state = account_store.read_agent_state(account_id)
    state["notification_loudness"] = {
        "schema_version": 1,
        "routes": {
            "telegram:1:chat-1": {
                "status": "pending",
                "checks_active": True,
                "route": {
                    "channel": "telegram",
                    "chat_id": "chat-1",
                    "chat_type": "private",
                    "adapter_slot": 1,
                    "last_seen_at": (now - timedelta(minutes=2)).isoformat(timespec="seconds"),
                },
                "identity_key": identity,
            }
        },
    }
    account_store.write_agent_state(account_id, state)
    account_store.update_identity_route(identity, channel="telegram", chat_id="chat-2", chat_type="private", adapter_slot=1)

    assert queue_due_notification_loudness_prompts(account_store, account_id, now=now) == ()
    assert account_store.read_proactive_outbox(account_id) == []


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


def test_scheduler_does_not_run_contact_timing_for_non_private_routes(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    state = account_store.read_agent_state(account_id)
    state["notification_loudness"] = {
        "schema_version": 1,
        "routes": {
            "telegram:1:group-1": {
                "status": "pending",
                "checks_active": True,
                "route": {"channel": "telegram", "chat_id": "group-1", "chat_type": "group", "adapter_slot": 1},
                "identity_key": identity,
            }
        },
    }
    account_store.write_agent_state(account_id, state)

    def fail_contact_timing(*_args, **_kwargs):
        raise AssertionError("group routes must not enter contact timing")

    monkeypatch.setattr("TeeBotus.runtime.notification_loudness.contact_timing_decision", fail_contact_timing)

    assert queue_due_notification_loudness_prompts(
        account_store, account_id, now=datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    ) == ()


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


def test_inconsistent_loudness_outbox_route_fails_closed(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    state = account_store.read_agent_state(account_id)
    state["notification_loudness"] = {
        "routes": {
            "telegram:1:chat-2": {"status": "pending", "checks_active": True}
        }
    }
    account_store.write_agent_state(account_id, state)

    item = {
        "route_key": "telegram:1:chat-2",
        "route": {"channel": "telegram", "chat_id": "chat-1", "chat_type": "private", "adapter_slot": 1},
    }

    assert notification_loudness_outbox_item_is_active(account_store, account_id, item) is False


def test_group_loudness_outbox_route_fails_closed(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    state = account_store.read_agent_state(account_id)
    state["notification_loudness"] = {"routes": {"telegram:1:chat-1": {"status": "pending"}}}
    account_store.write_agent_state(account_id, state)

    item = {
        "route_key": "telegram:1:chat-1",
        "route": {"channel": "telegram", "chat_id": "chat-1", "chat_type": "group", "adapter_slot": 1},
    }

    assert notification_loudness_outbox_item_is_active(account_store, account_id, item) is False


def test_terminal_loudness_outbox_item_is_not_active(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    state = account_store.read_agent_state(account_id)
    state["notification_loudness"] = {"routes": {"telegram:1:chat-1": {"status": "pending"}}}
    account_store.write_agent_state(account_id, state)

    assert notification_loudness_outbox_item_is_active(
        account_store, account_id, {"status": "sent", "route_key": "telegram:1:chat-1"}
    ) is False
    assert notification_loudness_outbox_item_is_active(
        account_store, account_id, {"status": "cancelled", "route_key": "telegram:1:chat-1"}
    ) is False


def test_malformed_loudness_outbox_status_is_not_active(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    state = account_store.read_agent_state(account_id)
    state["notification_loudness"] = {"routes": {"telegram:1:chat-1": {"status": "pending"}}}
    account_store.write_agent_state(account_id, state)

    for status in (None, "", 0, {}):
        assert notification_loudness_outbox_item_is_active(
            account_store, account_id, {"status": status, "route_key": "telegram:1:chat-1"}
        ) is False


def test_malformed_explicit_route_status_does_not_start_loudness_check(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    for status in (None, "", 0, {}):
        state = account_store.read_agent_state(account_id)
        state["notification_loudness"] = {
            "routes": {
                "telegram:1:chat-1": {
                    "status": status,
                    "checks_active": True,
                    "route": {"channel": "telegram", "chat_id": "chat-1", "chat_type": "private", "adapter_slot": 1},
                    "identity_key": identity,
                }
            }
        }
        account_store.write_agent_state(account_id, state)

        assert maybe_notification_loudness_prompt_action(
            event(identity), account_store, account_id, now=datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
        ) is None
        assert queue_due_notification_loudness_prompts(
            account_store, account_id, now=datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
        ) == ()


def test_terminal_loudness_state_repairs_malformed_active_flag(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    for active in (None, "false", "malformed"):
        state = account_store.read_agent_state(account_id)
        state["notification_loudness"] = {
            "routes": {
                "telegram:1:chat-1": {
                    "status": "declined",
                    "checks_active": active,
                    "checks_stop_reason": "declined",
                }
            }
        }
        account_store.write_agent_state(account_id, state)

        assert queue_due_notification_loudness_prompts(account_store, account_id) == ()
        repaired = account_store.read_agent_state(account_id)["notification_loudness"]["routes"]["telegram:1:chat-1"]
        assert repaired["checks_active"] is False
        assert repaired["checks_stop_reason"] == "declined"


def test_terminal_loudness_state_repairs_inconsistent_stop_metadata(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    state = account_store.read_agent_state(account_id)
    state["notification_loudness"] = {
        "routes": {
            "telegram:1:chat-1": {
                "status": "DECLINED",
                "checks_active": False,
                "checks_stop_reason": "confirmed",
                "checks_stopped_at": "not-a-timestamp",
            }
        }
    }
    account_store.write_agent_state(account_id, state)

    assert queue_due_notification_loudness_prompts(account_store, account_id) == ()
    repaired = account_store.read_agent_state(account_id)["notification_loudness"]["routes"]["telegram:1:chat-1"]
    assert repaired["checks_active"] is False
    assert repaired["checks_stop_reason"] == "declined"
    assert isinstance(repaired["checks_stopped_at"], str)
    assert repaired["checks_stopped_at"].endswith("+00:00")


def test_loudness_outbox_system_item_token_is_case_insensitive() -> None:
    assert is_notification_loudness_outbox_item({"system_item": "Notification_Loudness"}) is True
    assert is_notification_loudness_outbox_item({"planner": {"system_item": "NOTIFICATION_LOUDNESS"}}) is True


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


def test_loudness_paths_fail_closed_when_agent_state_storage_is_unavailable(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    original_read = account_store.read_agent_state

    def unavailable(_account_id):
        raise AccountStoreError("agent state unavailable")

    account_store.read_agent_state = unavailable  # type: ignore[method-assign]

    assert queue_due_notification_loudness_prompts(account_store, account_id) == ()
    assert maybe_notification_loudness_prompt_action(event(identity), account_store, account_id) is None
    assert maybe_handle_notification_loudness_response(event(identity, "ja, laut"), account_store, account_id) is None

    account_store.read_agent_state = original_read  # type: ignore[method-assign]


def test_malformed_explicit_loudness_active_flag_fails_closed(tmp_path) -> None:
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
                "checks_active": "maybe",
                "route": {"channel": "telegram", "chat_id": "chat-1", "chat_type": "private", "adapter_slot": 1},
                "identity_key": identity,
            }
        },
    }
    account_store.write_agent_state(account_id, state)

    assert queue_due_notification_loudness_prompts(account_store, account_id, now=now) == ()
    assert maybe_notification_loudness_prompt_action(event(identity), account_store, account_id, now=now) is None
    assert notification_loudness_outbox_item_is_active(
        account_store, account_id, {"route_key": "telegram:1:chat-1"}
    ) is False

    state["notification_loudness"]["routes"]["telegram:1:chat-1"]["checks_active"] = None
    account_store.write_agent_state(account_id, state)
    assert queue_due_notification_loudness_prompts(account_store, account_id, now=now) == ()


def test_legacy_loudness_outbox_route_fallback_prevents_duplicate_and_cancels(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    now = datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    assert maybe_notification_loudness_prompt_action(
        event(identity), account_store, account_id, now=now - timedelta(hours=7)
    ) is not None
    set_identity_last_seen(account_store, identity, now - timedelta(minutes=2))
    account_store.append_proactive_outbox_item(
        account_id,
        {
            "status": "queued",
            "system_item": "notification_loudness",
            "route": {"channel": "telegram", "chat_id": "chat-1", "chat_type": "private", "adapter_slot": 1},
        },
    )
    account_store.append_proactive_outbox_item(
        account_id,
        {
            "status": "queued",
            "system_item": "notification_loudness",
            "route_key": "malformed-route-key",
            "route": {"channel": "telegram", "chat_id": "chat-1", "chat_type": "private", "adapter_slot": 1},
        },
    )

    assert queue_due_notification_loudness_prompts(account_store, account_id, now=now) == ()
    assert maybe_handle_notification_loudness_response(
        event(identity, "ja, laut"), account_store, account_id, now=now
    ) is not None
    assert [item["status"] for item in account_store.read_proactive_outbox(account_id)] == ["cancelled", "cancelled"]


def test_legacy_next_check_at_blocks_loudness_prompt_until_due(tmp_path, monkeypatch) -> None:
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
                "checks_active": True,
                "next_check_at": (now + timedelta(hours=1)).isoformat(timespec="seconds"),
                "route": {"channel": "telegram", "chat_id": "chat-1", "chat_type": "private", "adapter_slot": 1},
                "identity_key": identity,
            }
        },
    }
    account_store.write_agent_state(account_id, state)
    monkeypatch.setattr(
        "TeeBotus.runtime.notification_loudness.contact_timing_decision",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cooldown must short-circuit contact timing")),
    )

    assert queue_due_notification_loudness_prompts(account_store, account_id, now=now) == ()
    assert maybe_notification_loudness_prompt_action(event(identity), account_store, account_id, now=now) is None
    assert account_store.read_proactive_outbox(account_id) == []


def test_malformed_legacy_next_check_at_blocks_loudness_prompt(tmp_path) -> None:
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
                "checks_active": True,
                "next_check_at": "not-a-timestamp",
                "route": {"channel": "telegram", "chat_id": "chat-1", "chat_type": "private", "adapter_slot": 1},
                "identity_key": identity,
            }
        },
    }
    account_store.write_agent_state(account_id, state)

    assert queue_due_notification_loudness_prompts(account_store, account_id, now=now) == ()
    assert maybe_notification_loudness_prompt_action(event(identity), account_store, account_id, now=now) is None


def test_prompt_handles_mixed_prompt_window_key_types(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    state = account_store.read_agent_state(account_id)
    state["notification_loudness"] = {
        "schema_version": 1,
        "routes": {
            "telegram:1:chat-1": {
                "status": "pending",
                "checks_active": True,
                "prompted_windows_by_date": {"2026-06-01": [], 7: []},
                "route": {"channel": "telegram", "chat_id": "chat-1", "chat_type": "private", "adapter_slot": 1},
                "identity_key": identity,
            }
        },
    }
    account_store.read_agent_state = lambda _account_id: state  # type: ignore[method-assign]
    account_store.write_agent_state = lambda _account_id, _state: None  # type: ignore[method-assign]

    prompt = maybe_notification_loudness_prompt_action(
        event(identity), account_store, account_id, now=datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    )

    assert prompt is not None


def test_scheduler_rejects_private_route_with_invalid_adapter_slot(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    now = datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    state = account_store.read_agent_state(account_id)
    state["notification_loudness"] = {
        "schema_version": 1,
        "routes": {
            "telegram:<invalid>:chat-1": {
                "status": "pending",
                "checks_active": True,
                "route": {
                    "channel": "telegram",
                    "chat_id": "chat-1",
                    "chat_type": "private",
                    "adapter_slot": "invalid",
                    "last_seen_at": (now - timedelta(minutes=2)).isoformat(timespec="seconds"),
                },
                "identity_key": "",
            }
        },
    }
    account_store.write_agent_state(account_id, state)

    assert queue_due_notification_loudness_prompts(account_store, account_id, now=now) == ()
    assert account_store.read_proactive_outbox(account_id) == []


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


def test_loudness_free_text_accepts_natural_completion_phrases() -> None:
    assert _notification_loudness_decision("Habe ich erledigt", pending=True) == "confirmed"
    assert _notification_loudness_decision("Ich habe es gemacht", pending=True) == "confirmed"
    assert _notification_loudness_decision("Benachrichtigungen sind eingeschaltet", pending=True) == "confirmed"
    assert _notification_loudness_decision("Ich habe es nicht gemacht", pending=True) == "declined"
    assert _notification_loudness_decision("Noch nicht aktiviert", pending=True) == "declined"


def test_loudness_free_text_accepts_natural_mute_phrases() -> None:
    assert _notification_loudness_decision("Die Nachrichten sind stumm", pending=True) == "declined"
    assert _notification_loudness_decision("Benachrichtigungen sind ausgeschaltet", pending=True) == "declined"
    assert _notification_loudness_decision("Keine Benachrichtigungen", pending=True) == "declined"


def test_loudness_free_text_distinguishes_negated_mute_terms() -> None:
    assert _notification_loudness_decision("Benachrichtigungen sind nicht stumm", pending=True) == "confirmed"
    assert _notification_loudness_decision("Benachrichtigungen sind nicht lautlos", pending=True) == "confirmed"
    assert _notification_loudness_decision("Benachrichtigungen sind nicht stummgeschaltet", pending=False) == "confirmed"
    assert _notification_loudness_decision("Benachrichtigungen sind nicht laut", pending=True) == "declined"
    assert _notification_loudness_decision("Benachrichtigungen sind stummgeschaltet", pending=True) == "declined"


def test_loudness_free_text_accepts_natural_on_off_and_loud_status_phrases() -> None:
    assert _notification_loudness_decision("Benachrichtigungen sind an", pending=True) == "confirmed"
    assert _notification_loudness_decision("Benachrichtigungen sind aus", pending=True) == "declined"
    assert _notification_loudness_decision("Die Nachrichten sind wieder laut", pending=True) == "confirmed"
    assert _notification_loudness_decision("Aktuell stehen die Nachrichten auf laut", pending=False) == "confirmed"
    assert _notification_loudness_decision("Die Nachrichten sind jetzt auf laut", pending=True) == "confirmed"


def test_loudness_free_text_accepts_english_notification_status_phrases() -> None:
    assert _notification_loudness_decision("notifications on", pending=True) == "confirmed"
    assert _notification_loudness_decision("notifications off", pending=True) == "declined"
    assert _notification_loudness_decision("notifications are disabled", pending=False) == "declined"
    assert _notification_loudness_decision("messages are loud", pending=True) == "confirmed"
    assert _notification_loudness_decision("messages are muted", pending=True) == "declined"
    assert _notification_loudness_decision("messages are not muted", pending=False) == "confirmed"
    assert _notification_loudness_decision("Notifications have been enabled", pending=True) == "confirmed"
    assert _notification_loudness_decision("I enabled notifications", pending=False) == "confirmed"
    assert _notification_loudness_decision("I have enabled notifications", pending=True) == "confirmed"
    assert _notification_loudness_decision("The notifications have been on since today", pending=False) == "confirmed"
    assert _notification_loudness_decision("Have notifications been enabled", pending=True) is None
    assert _notification_loudness_decision("Has notifications been enabled", pending=False) is None
    assert _notification_loudness_decision("Notifications are active", pending=False) == "confirmed"
    assert _notification_loudness_decision("Notifications are turned on", pending=True) == "confirmed"
    assert _notification_loudness_decision("Benachrichtigungen sind aktiv", pending=True) == "confirmed"
    assert _notification_loudness_decision("Notifications are unmuted", pending=False) == "confirmed"
    assert _notification_loudness_decision("I have unmuted notifications", pending=True) == "confirmed"
    assert _notification_loudness_decision("I turned them on", pending=True) == "confirmed"
    assert _notification_loudness_decision("I switched them on", pending=True) == "confirmed"
    assert _notification_loudness_decision("Ich habe Benachrichtigungen laut geschaltet", pending=True) == "confirmed"
    assert _notification_loudness_decision("Benachrichtigungen lautgeschaltet", pending=False) == "confirmed"
    assert _notification_loudness_decision("Die Nachrichten sind lautgeschaltet", pending=True) == "confirmed"
    assert _notification_loudness_decision("Ich habe die Nachrichten entstummt", pending=False) == "confirmed"
    assert _notification_loudness_decision("Die Nachrichten sind nicht laut geschaltet", pending=True) == "declined"
    assert _notification_loudness_decision("I took notifications off mute", pending=False) == "confirmed"
    assert _notification_loudness_decision("I removed mute from notifications", pending=True) == "confirmed"
    assert _notification_loudness_decision("Notifications are off mute", pending=False) == "confirmed"
    assert _notification_loudness_decision("Please take notifications off mute", pending=True) is None
    assert _notification_loudness_decision("Remove mute from notifications", pending=True) is None


def test_loudness_free_text_preserves_negation_for_disabled_status() -> None:
    assert _notification_loudness_decision("Benachrichtigungen sind nicht aus", pending=True) == "confirmed"
    assert _notification_loudness_decision("Benachrichtigungen sind nicht ausgeschaltet", pending=True) == "confirmed"
    assert _notification_loudness_decision("Benachrichtigungen sind nicht deaktiviert", pending=False) == "confirmed"
    assert _notification_loudness_decision("notifications are not off", pending=True) == "confirmed"
    assert _notification_loudness_decision("notifications are not disabled", pending=False) == "confirmed"
    assert _notification_loudness_decision("Benachrichtigungen sind ausgeschaltet", pending=True) == "declined"


def test_loudness_free_text_handles_negation_parity_and_explicit_status() -> None:
    assert _notification_loudness_decision("nicht nicht stumm", pending=True) == "declined"
    assert _notification_loudness_decision("not not muted", pending=True) == "declined"
    assert _notification_loudness_decision("keine Benachrichtigungen sind ausgeschaltet", pending=True) == "confirmed"
    assert _notification_loudness_decision("keine Benachrichtigungen sind stumm", pending=True) == "confirmed"
    assert _notification_loudness_decision("I have no notifications on", pending=True) == "declined"
    assert _notification_loudness_decision("No notifications are muted", pending=True) == "confirmed"
    assert _notification_loudness_decision("None of my notifications are muted", pending=True) == "confirmed"
    assert _notification_loudness_decision("Keine der Benachrichtigungen sind stumm", pending=True) == "confirmed"
    assert _notification_loudness_decision("Neither notifications nor messages are muted", pending=True) == "confirmed"
    assert _notification_loudness_decision("Weder Benachrichtigungen noch Nachrichten sind stumm", pending=True) == "confirmed"


def test_loudness_free_text_does_not_leak_negation_across_clauses() -> None:
    assert _notification_loudness_decision("nicht stumm, aber lautlos", pending=True) == "declined"
    assert _notification_loudness_decision("not muted but silenced", pending=False) == "declined"
    assert _notification_loudness_decision("nicht stumm und nicht lautlos", pending=True) == "confirmed"
    assert _notification_loudness_decision("nicht ausgeschaltet, aber deaktiviert", pending=True) == "declined"


def test_loudness_free_text_preserves_punctuation_clause_boundaries() -> None:
    assert _notification_loudness_decision("nicht stumm, lautlos", pending=True) == "declined"
    assert _notification_loudness_decision("not muted, silenced", pending=False) == "declined"
    assert _notification_loudness_decision("nicht stumm; nicht lautlos", pending=True) == "confirmed"


def test_loudness_free_text_does_not_decide_uncertain_status_statements() -> None:
    assert _notification_loudness_decision("Ich kann nicht sagen, ob die Benachrichtigungen an sind", pending=True) is None
    assert _notification_loudness_decision("Keine Ahnung, ob die Nachrichten stumm sind", pending=True) is None
    assert _notification_loudness_decision("Ich bin mir nicht sicher, ob die Nachrichten nicht lautlos sind", pending=False) is None
    assert _notification_loudness_decision("I am not sure whether messages are muted", pending=True) is None
    assert _notification_loudness_decision("Maybe notifications are on", pending=False) is None
    assert _notification_loudness_decision("I guess notifications are on", pending=True) is None
    assert _notification_loudness_decision("I suppose messages are muted", pending=False) is None
    assert _notification_loudness_decision("Perhaps notifications are enabled", pending=True) is None
    assert _notification_loudness_decision("Presumably notifications are on", pending=False) is None
    assert _notification_loudness_decision("Ich vermute, dass Benachrichtigungen an sind", pending=True) is None
    assert _notification_loudness_decision("Ich schätze, die Nachrichten sind laut", pending=False) is None
    assert _notification_loudness_decision("Ich nehme an, Benachrichtigungen sind an", pending=True) is None
    assert _notification_loudness_decision("I suspect notifications are on", pending=True) is None
    assert _notification_loudness_decision("I doubt messages are muted", pending=False) is None
    assert _notification_loudness_decision("Apparently notifications are on", pending=True) is None
    assert _notification_loudness_decision("It seems notifications are on", pending=False) is None
    assert _notification_loudness_decision("As far as I know notifications are on", pending=True) is None
    assert _notification_loudness_decision("I am pretty sure notifications are on", pending=False) is None
    assert _notification_loudness_decision("Anscheinend sind Benachrichtigungen an", pending=True) is None


def test_loudness_free_text_does_not_treat_imperative_as_confirmation() -> None:
    assert _notification_loudness_decision("Stell die Nachrichten auf laut", pending=True) is None
    assert _notification_loudness_decision("Die Nachrichten sind auf laut", pending=True) == "confirmed"
    assert _notification_loudness_decision("Die Nachrichten stehen auf laut", pending=False) == "confirmed"


def test_loudness_free_text_does_not_decide_questions_or_requests() -> None:
    assert _notification_loudness_decision("Sind die Benachrichtigungen an?", pending=True) is None
    assert _notification_loudness_decision("Sind die Nachrichten nicht stumm?", pending=True) is None
    assert _notification_loudness_decision("Are notifications on?", pending=True) is None
    assert _notification_loudness_decision("Weißt du, ob die Benachrichtigungen an sind?", pending=False) is None
    assert _notification_loudness_decision("Bitte stell sicher, dass die Benachrichtigungen an sind", pending=True) is None
    assert _notification_loudness_decision("Stell sicher, dass die Nachrichten nicht stumm sind", pending=False) is None
    assert _notification_loudness_decision("Die Benachrichtigungen sind an.", pending=True) == "confirmed"
    assert _notification_loudness_decision("Ist laut gestellt", pending=True) == "confirmed"
    assert _notification_loudness_decision("Ist auf laut", pending=False) == "confirmed"
    assert _notification_loudness_decision("Is muted", pending=True) == "declined"
    assert _notification_loudness_decision("Nachrichten sind laut, oder", pending=True) is None
    assert _notification_loudness_decision("Notifications are on, right", pending=False) is None
    assert _notification_loudness_decision("Messages are muted, correct", pending=True) is None
    assert _notification_loudness_decision("Tell me if notifications are on", pending=True) is None
    assert _notification_loudness_decision("Let me know if messages are muted", pending=False) is None
    assert _notification_loudness_decision("Please tell me if notifications are on", pending=True) is None
    assert _notification_loudness_decision("I wonder whether messages are muted", pending=False) is None
    assert _notification_loudness_decision("What if notifications are on", pending=True) is None
    assert _notification_loudness_decision("How do I know notifications are on", pending=False) is None
    assert _notification_loudness_decision("Notifications are on or off", pending=True) is None
    assert _notification_loudness_decision("Messages are loud or muted", pending=False) is None
    assert _notification_loudness_decision("Benachrichtigungen sind an oder aus", pending=True) is None


def test_loudness_free_text_does_not_decide_english_and_inverted_questions() -> None:
    assert _notification_loudness_decision("Can messages be muted", pending=True) is None
    assert _notification_loudness_decision("Can notifications be on", pending=False) is None
    assert _notification_loudness_decision("Could you check if messages are muted", pending=True) is None
    assert _notification_loudness_decision("Will notifications be on", pending=False) is None
    assert _notification_loudness_decision("Would messages be loud", pending=True) is None
    assert _notification_loudness_decision("Kann man Nachrichten stumm schalten", pending=False) is None
    assert _notification_loudness_decision("Können Benachrichtigungen an sein", pending=True) is None


def test_loudness_free_text_recognizes_message_and_push_context() -> None:
    assert _notification_loudness_decision("Die Nachrichten sind ausgeschaltet", pending=False) == "declined"
    assert _notification_loudness_decision("Die Nachrichten sind nicht ausgeschaltet", pending=False) == "confirmed"
    assert _notification_loudness_decision("Messages are disabled", pending=False) == "declined"
    assert _notification_loudness_decision("Messages are not disabled", pending=False) == "confirmed"
    assert _notification_loudness_decision("Push ist ausgeschaltet", pending=False) == "declined"
    assert _notification_loudness_decision("Push ist nicht ausgeschaltet", pending=False) == "confirmed"


def test_loudness_free_text_ignores_unrelated_loudness_subjects() -> None:
    assert _notification_loudness_decision("Das Radio ist laut", pending=True) is None
    assert _notification_loudness_decision("I am not loud", pending=True) is None
    assert _notification_loudness_decision("The phone is muted", pending=True) is None
    assert _notification_loudness_decision("Phone is muted", pending=True) is None
    assert _notification_loudness_decision("My phone is off", pending=True) is None
    assert _notification_loudness_decision("Die Nachrichten sind laut", pending=True) == "confirmed"


def test_loudness_free_text_respects_negated_completion_phrases() -> None:
    assert _notification_loudness_decision("Ich habe noch nichts gemacht", pending=True) == "declined"
    assert _notification_loudness_decision("Ich habe nichts erledigt", pending=True) == "declined"
    assert _notification_loudness_decision("Ich habe nichts aktiviert", pending=True) == "declined"
    assert _notification_loudness_decision("Ich habe nix eingeschaltet", pending=True) == "declined"
    assert _notification_loudness_decision("Ich habe nichts laut gestellt", pending=False) == "declined"


def test_loudness_free_text_accepts_short_pending_action_replies() -> None:
    assert _notification_loudness_decision("ja hab ich", pending=True) == "confirmed"
    assert _notification_loudness_decision("jo habe ich", pending=True) == "confirmed"
    assert _notification_loudness_decision("yes I did", pending=True) == "confirmed"
    assert _notification_loudness_decision("ja hab ich nicht", pending=True) == "declined"
    assert _notification_loudness_decision("okay, habe ich nicht", pending=True) == "declined"
    assert _notification_loudness_decision("nee hab ich nicht", pending=True) == "declined"
    assert _notification_loudness_decision("nein habe ich nicht", pending=True) == "declined"


def test_loudness_free_text_accepts_completion_synonyms() -> None:
    assert _notification_loudness_decision("Ich habe es getan", pending=True) == "confirmed"
    assert _notification_loudness_decision("fertig", pending=True) == "confirmed"
    assert _notification_loudness_decision("I am done", pending=True) == "confirmed"
    assert _notification_loudness_decision("I completed it", pending=True) == "confirmed"
    assert _notification_loudness_decision("Ich habe es geschafft", pending=True) == "confirmed"
    assert _notification_loudness_decision("Ich bin nicht fertig", pending=True) == "declined"
    assert _notification_loudness_decision("I am not done", pending=True) == "declined"


def test_loudness_free_text_respects_contracted_english_negations() -> None:
    assert _notification_loudness_decision("I haven't done it", pending=True) == "declined"
    assert _notification_loudness_decision("I haven't completed it", pending=True) == "declined"
    assert _notification_loudness_decision("I didn't do it", pending=True) == "declined"
    assert _notification_loudness_decision("No, I didn't", pending=True) == "declined"
    assert _notification_loudness_decision("No, I haven't", pending=True) == "declined"
    assert _notification_loudness_decision("No, not yet", pending=True) == "declined"
    assert _notification_loudness_decision("Nein, ich habe es getan", pending=True) == "confirmed"
    assert _notification_loudness_decision("Nein, ich habe es nicht getan", pending=True) == "declined"
    assert _notification_loudness_decision("I haven't muted the messages", pending=True) == "confirmed"
    assert _notification_loudness_decision("I didn't mute notifications", pending=False) == "confirmed"
    assert _notification_loudness_decision("I haven't disabled notifications", pending=False) == "confirmed"


def test_loudness_free_text_rejects_negated_positive_status_substrings() -> None:
    assert _notification_loudness_decision("Notifications aren't on", pending=True) == "declined"
    assert _notification_loudness_decision("Notifications aren't enabled", pending=False) == "declined"
    assert _notification_loudness_decision("Messages aren't loud", pending=True) == "declined"
    assert _notification_loudness_decision("The messages are not loud", pending=False) == "declined"
    assert _notification_loudness_decision("The messages are not on", pending=False) == "declined"
    assert _notification_loudness_decision("I don't have notifications on", pending=True) == "declined"
    assert _notification_loudness_decision("I don't have notifications enabled", pending=False) == "declined"


def test_loudness_free_text_rejects_contracted_uncertainty_markers() -> None:
    assert _notification_loudness_decision("I don't think notifications are on", pending=True) is None
    assert _notification_loudness_decision("I don’t think notifications are on", pending=True) is None
    assert _notification_loudness_decision("I don't believe messages are loud", pending=False) is None
    assert _notification_loudness_decision("I can't tell if messages are muted", pending=True) is None
    assert _notification_loudness_decision("I can’t tell if messages are muted", pending=True) is None
    assert _notification_loudness_decision("I have no idea whether notifications are enabled", pending=False) is None
    assert _notification_loudness_decision("I am unsure whether messages are loud", pending=True) is None


def test_loudness_free_text_rejects_explicit_english_uncertainty_markers() -> None:
    assert _notification_loudness_decision("I do not know if notifications are on", pending=True) is None
    assert _notification_loudness_decision("I do not think notifications are on", pending=False) is None
    assert _notification_loudness_decision("I do not believe messages are loud", pending=True) is None


def test_loudness_free_text_does_not_decide_requests_as_completed() -> None:
    assert _notification_loudness_decision("I want notifications on", pending=True) is None
    assert _notification_loudness_decision("I want messages not muted", pending=False) is None
    assert _notification_loudness_decision("I don't want messages muted", pending=True) is None
    assert _notification_loudness_decision("Please turn notifications on", pending=False) is None
    assert _notification_loudness_decision("Don't mute messages", pending=True) is None
    assert _notification_loudness_decision("Do not mute notifications", pending=False) is None
    assert _notification_loudness_decision("Lass die Nachrichten nicht stumm", pending=True) is None
    assert _notification_loudness_decision("Ich möchte, dass Nachrichten nicht stumm sind", pending=False) is None


def test_loudness_free_text_does_not_decide_future_intentions_as_completed() -> None:
    assert _notification_loudness_decision("I will turn notifications on", pending=True) is None
    assert _notification_loudness_decision("I am going to turn notifications on", pending=False) is None
    assert _notification_loudness_decision("I plan to turn notifications on", pending=True) is None
    assert _notification_loudness_decision("I intend to mute messages", pending=False) is None
    assert _notification_loudness_decision("Ich werde Nachrichten laut stellen", pending=True) is None
    assert _notification_loudness_decision("Ich habe vor, Nachrichten laut zu stellen", pending=False) is None
    assert _notification_loudness_decision("I have turned notifications on", pending=True) == "confirmed"
    assert _notification_loudness_decision("I just turned notifications on", pending=False) == "confirmed"


def test_loudness_free_text_does_not_decide_historical_status_as_current() -> None:
    assert _notification_loudness_decision("I used to have notifications on", pending=True) is None
    assert _notification_loudness_decision("I formerly had notifications on", pending=False) is None
    assert _notification_loudness_decision("I previously had notifications on", pending=True) is None
    assert _notification_loudness_decision("I had notifications on yesterday", pending=False) is None
    assert _notification_loudness_decision("Die Nachrichten waren vorher nicht stumm", pending=True) is None
    assert _notification_loudness_decision("Gestern waren die Nachrichten laut", pending=False) is None
    assert _notification_loudness_decision("I have notifications on now", pending=True) == "confirmed"
    assert _notification_loudness_decision("Notifications are on now", pending=False) == "confirmed"


def test_loudness_free_text_does_not_decide_habitual_status_as_current() -> None:
    assert _notification_loudness_decision("I usually have notifications on", pending=True) is None
    assert _notification_loudness_decision("I always have notifications on", pending=False) is None
    assert _notification_loudness_decision("I often mute messages", pending=True) is None
    assert _notification_loudness_decision("I sometimes turn notifications off", pending=False) is None
    assert _notification_loudness_decision("I never turn notifications off", pending=True) is None
    assert _notification_loudness_decision("Normalerweise sind Benachrichtigungen an", pending=False) is None
    assert _notification_loudness_decision("Häufig sind Benachrichtigungen an", pending=True) is None
    assert _notification_loudness_decision("Grundsätzlich: Benachrichtigungen sind an", pending=True) is None
    assert _notification_loudness_decision("Aktuell sind Benachrichtigungen an", pending=True) == "confirmed"


def test_loudness_free_text_normalizes_historical_markers_before_matching() -> None:
    assert _notification_loudness_decision("Früher: Benachrichtigungen sind an", pending=True) is None


def test_loudness_free_text_does_not_decide_no_longer_status_as_current() -> None:
    assert _notification_loudness_decision("I no longer have notifications on", pending=True) is None
    assert _notification_loudness_decision("I no longer mute messages", pending=False) is None
    assert _notification_loudness_decision("Messages are no longer muted", pending=True) is None


def test_loudness_free_text_does_not_decide_conditional_status_as_current() -> None:
    assert _notification_loudness_decision("If notifications are on, reminders work", pending=True) is None
    assert _notification_loudness_decision("When messages are loud, I notice them", pending=False) is None
    assert _notification_loudness_decision("Assuming notifications are on", pending=True) is None
    assert _notification_loudness_decision("Suppose messages are loud", pending=False) is None
    assert _notification_loudness_decision("Unless notifications are off", pending=True) is None
    assert _notification_loudness_decision("Provided messages are not muted", pending=False) is None
    assert _notification_loudness_decision("Falls Benachrichtigungen an sind", pending=True) is None


def test_loudness_free_text_does_not_decide_negated_keep_requests() -> None:
    assert _notification_loudness_decision("Don't keep messages muted", pending=True) is None
    assert _notification_loudness_decision("Do not keep notifications off", pending=False) is None
    assert _notification_loudness_decision("Don't leave messages muted", pending=True) is None
    assert _notification_loudness_decision("Do not leave notifications off", pending=False) is None
    assert _notification_loudness_decision("Nicht stumm lassen", pending=True) is None
    assert _notification_loudness_decision("Bitte nicht stumm lassen", pending=False) is None
    assert _notification_loudness_decision("Die Nachrichten sind nicht stumm", pending=True) == "confirmed"
    assert _notification_loudness_decision("I don't leave messages muted", pending=True) is None
    assert _notification_loudness_decision("I do not keep notifications off", pending=False) is None
    assert _notification_loudness_decision("I don't mute messages", pending=True) is None
    assert _notification_loudness_decision("I do not turn notifications on", pending=False) is None
    assert _notification_loudness_decision("I leave messages muted", pending=True) is None
    assert _notification_loudness_decision("I leave notifications off", pending=False) is None
    assert _notification_loudness_decision("Ich lasse die Nachrichten stumm", pending=True) is None
    assert _notification_loudness_decision("Ich lasse die Nachrichten nicht stumm", pending=False) is None
    assert _notification_loudness_decision("I set notifications to loud", pending=True) is None
    assert _notification_loudness_decision("I make messages loud", pending=False) is None


def test_loudness_free_text_accepts_completed_set_and_make_forms() -> None:
    assert _notification_loudness_decision("I have set notifications to loud", pending=False) == "confirmed"
    assert _notification_loudness_decision("I have set them to loud", pending=True) == "confirmed"
    assert _notification_loudness_decision("I have made messages loud", pending=False) == "confirmed"
    assert _notification_loudness_decision("I have made them loud", pending=True) == "confirmed"


def test_loudness_free_text_does_not_decide_present_actions_as_completed() -> None:
    assert _notification_loudness_decision("I turn notifications on", pending=True) is None
    assert _notification_loudness_decision("I switch notifications on", pending=False) is None
    assert _notification_loudness_decision("I mute messages", pending=True) is None
    assert _notification_loudness_decision("Ich schalte Benachrichtigungen an", pending=True) is None
    assert _notification_loudness_decision("Ich aktiviere Benachrichtigungen", pending=False) is None
    assert _notification_loudness_decision("Ich habe Benachrichtigungen angeschaltet", pending=True) == "confirmed"
    assert _notification_loudness_decision("I make messages muted", pending=True) is None
    assert _notification_loudness_decision("I put notifications on", pending=True) is None
    assert _notification_loudness_decision("I activate notifications", pending=False) is None
    assert _notification_loudness_decision("I disable notifications", pending=True) is None


def test_loudness_free_text_accepts_affirmation_variants_with_context() -> None:
    assert _notification_loudness_decision("jo, laut", pending=True) == "confirmed"
    assert _notification_loudness_decision("jep, Nachrichten sind an", pending=True) == "confirmed"
    assert _notification_loudness_decision("okay, laut", pending=True) == "confirmed"
    assert _notification_loudness_decision("klar, messages are loud", pending=True) == "confirmed"


def test_loudness_free_text_accepts_pending_pronoun_statuses() -> None:
    assert _notification_loudness_decision("Sie sind an", pending=True) == "confirmed"
    assert _notification_loudness_decision("Sie sind nicht stumm", pending=True) == "confirmed"
    assert _notification_loudness_decision("They are on", pending=True) == "confirmed"
    assert _notification_loudness_decision("They're not muted", pending=True) == "confirmed"
    assert _notification_loudness_decision("They are not off", pending=True) == "confirmed"
    assert _notification_loudness_decision("Sie sind nicht ausgeschaltet", pending=True) == "confirmed"
    assert _notification_loudness_decision("Sie sind aus", pending=True) == "declined"
    assert _notification_loudness_decision("Sie sind nicht laut", pending=True) == "declined"
    assert _notification_loudness_decision("They aren't loud", pending=True) == "declined"
    assert _notification_loudness_decision("They are muted", pending=True) == "declined"
    assert _notification_loudness_decision("They are disabled", pending=True) == "declined"
    assert _notification_loudness_decision("They are on?", pending=True) is None
    assert _notification_loudness_decision("Sie sind nicht stumm?", pending=True) is None
    assert _notification_loudness_decision("They are on", pending=False) is None


def test_loudness_free_text_keeps_negation_precedence_without_pending_state() -> None:
    assert _notification_loudness_decision("Benachrichtigungen sind deaktiviert", pending=False) == "declined"
    assert _notification_loudness_decision("Benachrichtigungen sind nicht aktiviert", pending=False) == "declined"


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


def test_loudness_outbox_item_is_inactive_after_account_route_changes(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    assert maybe_notification_loudness_prompt_action(
        event(identity), account_store, account_id, now=datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    ) is not None

    account_store.update_identity_route(identity, channel="telegram", chat_id="chat-2", chat_type="private", adapter_slot=1)

    item = {
        "status": "queued",
        "system_item": NOTIFICATION_LOUDNESS_SYSTEM_ITEM,
        "route_key": "telegram:1:chat-1",
        "route": {"channel": "telegram", "chat_id": "chat-1", "chat_type": "private", "adapter_slot": 1},
    }
    assert notification_loudness_outbox_item_is_active(account_store, account_id, item) is False


def test_inactive_pending_loudness_check_is_not_resurrected_by_incoming_message(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    state = account_store.read_agent_state(account_id)
    state["notification_loudness"] = {
        "schema_version": 1,
        "routes": {
            "telegram:1:chat-1": {
                "status": "pending",
                "checks_active": False,
                "route": {"channel": "telegram", "chat_id": "chat-1", "chat_type": "private", "adapter_slot": 1},
                "identity_key": identity,
            }
        },
    }
    account_store.write_agent_state(account_id, state)

    assert maybe_notification_loudness_prompt_action(
        event(identity), account_store, account_id, now=datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    ) is None
    assert maybe_handle_notification_loudness_response(
        event(identity, "ja, laut"), account_store, account_id, now=datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    ) is None
    route_state = account_store.read_agent_state(account_id)["notification_loudness"]["routes"]["telegram:1:chat-1"]
    assert route_state["status"] == "pending"
    assert route_state["checks_active"] is False


def test_terminal_case_variant_route_wins_over_duplicate_pending_route(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    state = account_store.read_agent_state(account_id)
    state["notification_loudness"] = {
        "schema_version": 1,
        "routes": {
            "telegram:1:chat-1": {
                "status": "pending",
                "checks_active": True,
                "route": {"channel": "telegram", "chat_id": "chat-1", "chat_type": "private", "adapter_slot": 1},
                "identity_key": identity,
            },
            "TeLegram:1:chat-1": {
                "status": "declined",
                "checks_active": False,
                "route": {"channel": "TeLegram", "chat_id": "chat-1", "chat_type": "Private", "adapter_slot": 1},
                "identity_key": identity,
            },
        },
    }
    account_store.write_agent_state(account_id, state)
    set_identity_last_seen(account_store, identity, datetime(2026, 6, 15, 15, tzinfo=timezone.utc))

    assert maybe_notification_loudness_prompt_action(
        event(identity), account_store, account_id, now=datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    ) is None
    assert queue_due_notification_loudness_prompts(
        account_store, account_id, now=datetime(2026, 6, 15, 15, tzinfo=timezone.utc)
    ) == ()


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
