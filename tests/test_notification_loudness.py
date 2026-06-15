from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, telegram_identity_key
from TeeBotus.runtime.actions import SendText
from TeeBotus.runtime.engine import TeeBotusEngine
from TeeBotus.runtime.events import IncomingEvent
from TeeBotus.runtime.notification_loudness import (
    NOTIFICATION_LOUDNESS_PROMPT,
    maybe_notification_loudness_prompt_action,
    queue_due_notification_loudness_prompts,
)
from TeeBotus.runtime.proactive_agent import check_proactive_agent_account, dispatch_due_proactive_outbox_items


def store(tmp_path) -> AccountStore:
    return AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"n" * 32))


def event(identity_key: str, text: str = "Hallo") -> IncomingEvent:
    return IncomingEvent(
        event_id="telegram:1",
        instance="Depressionsbot",
        channel="telegram",
        adapter_slot=1,
        account_id="",
        identity_key=identity_key,
        chat_id="chat-1",
        chat_type="private",
        sender_id=identity_key,
        sender_name=identity_key,
        text=text,
        message_ref="1",
    )


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


def test_engine_asks_user_to_unmute_bot_messages_once_route_exists(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    prepare_account_with_route(account_store, identity)
    engine = TeeBotusEngine(account_store=account_store)

    actions = engine.process(event(identity, "/ping"))

    assert len(actions) == 2
    assert actions[0].text == "pong"
    assert actions[1].text == NOTIFICATION_LOUDNESS_PROMPT
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
    assert state["notification_loudness"]["routes"]["telegram:1:chat-1"]["status"] == "confirmed"


def test_scheduler_queues_notification_loudness_follow_up_when_recently_active_in_next_wake_half(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = prepare_account_with_route(account_store, identity)
    now = datetime(2026, 6, 15, 8, tzinfo=timezone.utc)
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
