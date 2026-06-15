from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from TeeBotus.runtime.accounts import AccountStore, utc_now
from TeeBotus.runtime.actions import SendText
from TeeBotus.runtime.events import IncomingEvent

NOTIFICATION_LOUDNESS_SYSTEM_ITEM = "notification_loudness"
NOTIFICATION_LOUDNESS_INTENT = "notification_loudness_check"
NOTIFICATION_LOUDNESS_INTERVAL = timedelta(hours=12)

NOTIFICATION_LOUDNESS_PROMPT = (
    "Bitte stell meine Nachrichten in diesem Chat auf laut, damit Erinnerungen, Termine und wichtige Hinweise nicht untergehen.\n"
    "Hast du das erledigt? Antworte bitte mit „ja, laut“ oder „nein“."
)
NOTIFICATION_LOUDNESS_CONFIRMED_REPLY = "Danke, ich frage deswegen nicht weiter nach."
NOTIFICATION_LOUDNESS_DECLINED_REPLY = "Okay, ich frage deswegen nicht weiter nach."


def maybe_handle_notification_loudness_response(
    event: IncomingEvent,
    account_store: AccountStore,
    account_id: str,
    *,
    now: datetime | None = None,
) -> tuple[SendText, ...] | None:
    if event.chat_type != "private":
        return None
    decision = _notification_loudness_decision(event.text, pending=_route_status(account_store, account_id, event) == "pending")
    if decision is None:
        return None
    _set_notification_loudness_status(account_store, account_id, event, decision, now=now)
    _cancel_queued_notification_loudness_items(account_store, account_id, event)
    text = NOTIFICATION_LOUDNESS_CONFIRMED_REPLY if decision == "confirmed" else NOTIFICATION_LOUDNESS_DECLINED_REPLY
    return (SendText(event.chat_id, text, track=False),)


def maybe_notification_loudness_prompt_action(
    event: IncomingEvent,
    account_store: AccountStore,
    account_id: str,
    *,
    now: datetime | None = None,
) -> SendText | None:
    if event.chat_type != "private" or not account_id:
        return None
    if not _event_has_current_private_route(account_store, event):
        return None
    state = account_store.read_agent_state(account_id)
    route_state = _ensure_route_state(state, event)
    if str(route_state.get("status") or "unknown") in {"confirmed", "declined"}:
        return None
    resolved_now = now or datetime.now(timezone.utc)
    next_check = _parse_datetime(str(route_state.get("next_check_at") or ""))
    if next_check is not None and next_check > resolved_now:
        account_store.write_agent_state(account_id, state)
        return None
    _mark_notification_loudness_prompted(route_state, event, resolved_now)
    account_store.write_agent_state(account_id, state)
    return SendText(event.chat_id, NOTIFICATION_LOUDNESS_PROMPT, track=False)


def queue_due_notification_loudness_prompts(
    account_store: AccountStore,
    account_id: str,
    *,
    now: datetime | None = None,
) -> tuple[str, ...]:
    state = account_store.read_agent_state(account_id)
    state.setdefault("schema_version", 1)
    notification_state = state.get("notification_loudness")
    if not isinstance(notification_state, dict):
        return ()
    routes = notification_state.get("routes")
    if not isinstance(routes, dict):
        return ()
    resolved_now = now or datetime.now(timezone.utc)
    queued_ids: list[str] = []
    for route_key, route_state in list(routes.items()):
        if not isinstance(route_state, dict):
            continue
        if str(route_state.get("status") or "unknown") in {"confirmed", "declined"}:
            continue
        next_check = _parse_datetime(str(route_state.get("next_check_at") or ""))
        if next_check is not None and next_check > resolved_now:
            continue
        route = route_state.get("route")
        if not _private_route(route):
            continue
        if _has_queued_notification_loudness_item(account_store, account_id, route_key):
            continue
        _mark_route_state_prompted(route_state, resolved_now)
        queued_ids.append(
            account_store.append_proactive_outbox_item(
                account_id,
                {
                    "status": "queued",
                    "category": "system",
                    "intent": NOTIFICATION_LOUDNESS_INTENT,
                    "message_text": NOTIFICATION_LOUDNESS_PROMPT,
                    "reason_memory_ids": [],
                    "due_at": resolved_now.isoformat(timespec="seconds"),
                    "risk_gate": "none",
                    "planner": {"source": "system", "system_item": NOTIFICATION_LOUDNESS_SYSTEM_ITEM},
                    "policy_result": "allowed",
                    "policy_reason": "system_notification_loudness_prompt",
                    "route": dict(route),
                    "system_item": NOTIFICATION_LOUDNESS_SYSTEM_ITEM,
                    "route_key": str(route_key),
                    "status_history": [{"at": utc_now(), "status": "queued", "reason": "created"}],
                },
            )
        )
    if queued_ids:
        account_store.write_agent_state(account_id, state)
    return tuple(queued_ids)


def is_notification_loudness_outbox_item(item: Mapping[str, Any] | None) -> bool:
    if not isinstance(item, Mapping):
        return False
    if str(item.get("system_item") or "").strip() == NOTIFICATION_LOUDNESS_SYSTEM_ITEM:
        return True
    planner = item.get("planner")
    return isinstance(planner, Mapping) and str(planner.get("system_item") or "").strip() == NOTIFICATION_LOUDNESS_SYSTEM_ITEM


def _notification_loudness_decision(text: str, *, pending: bool) -> str | None:
    normalized = _normalize_text(text)
    if not normalized:
        return None
    words = set(normalized.split())
    has_notification_context = any(
        needle in normalized
        for needle in (
            "laut",
            "benachrichtigung",
            "notification",
            "notifications",
            "stumm",
        )
    )
    confirmed_needles = (
        "ja laut",
        "laut gestellt",
        "auf laut",
        "benachrichtigungen an",
        "benachrichtigung an",
        "notifications on",
        "notification on",
        "ist laut",
        "erledigt",
        "gemacht",
    )
    declined_needles = (
        "ablehnen",
        "abgelehnt",
        "nicht fragen",
        "frag nicht",
        "keine nachfrage",
        "will ich nicht",
        "moechte ich nicht",
        "möchte ich nicht",
        "stumm lassen",
        "bleibt stumm",
    )
    if pending and (normalized in {"ja", "yes", "jep", "jo", "ok", "okay", "klar", "erledigt", "gemacht"} or words & {"ja", "yes"} and has_notification_context):
        return "confirmed"
    if pending and normalized in {"nein", "no", "nee", "nop", "nope"}:
        return "declined"
    if has_notification_context and any(needle in normalized for needle in confirmed_needles):
        return "confirmed"
    if has_notification_context and any(needle in normalized for needle in declined_needles):
        return "declined"
    return None


def _set_notification_loudness_status(
    account_store: AccountStore,
    account_id: str,
    event: IncomingEvent,
    status: str,
    *,
    now: datetime | None = None,
) -> None:
    state = account_store.read_agent_state(account_id)
    route_state = _ensure_route_state(state, event)
    timestamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    route_state["status"] = status
    route_state["decided_at"] = timestamp
    route_state["updated_at"] = timestamp
    route_state.pop("next_check_at", None)
    account_store.write_agent_state(account_id, state)


def _route_status(account_store: AccountStore, account_id: str, event: IncomingEvent) -> str:
    state = account_store.read_agent_state(account_id)
    notification_state = state.get("notification_loudness")
    if not isinstance(notification_state, dict):
        return "unknown"
    routes = notification_state.get("routes")
    if not isinstance(routes, dict):
        return "unknown"
    route_state = routes.get(_route_key(event))
    if not isinstance(route_state, dict):
        return "unknown"
    return str(route_state.get("status") or "unknown").strip()


def _ensure_route_state(state: dict[str, Any], event: IncomingEvent) -> dict[str, Any]:
    state.setdefault("schema_version", 1)
    notification_state = state.setdefault("notification_loudness", {})
    if not isinstance(notification_state, dict):
        notification_state = {}
        state["notification_loudness"] = notification_state
    notification_state["schema_version"] = 1
    routes = notification_state.setdefault("routes", {})
    if not isinstance(routes, dict):
        routes = {}
        notification_state["routes"] = routes
    route_key = _route_key(event)
    route_state = routes.setdefault(route_key, {})
    if not isinstance(route_state, dict):
        route_state = {}
        routes[route_key] = route_state
    route_state.setdefault("status", "unknown")
    route_state["route_key"] = route_key
    route_state["route"] = _event_route(event)
    return route_state


def _mark_notification_loudness_prompted(route_state: dict[str, Any], event: IncomingEvent, now: datetime) -> None:
    route_state["route"] = _event_route(event)
    _mark_route_state_prompted(route_state, now)


def _mark_route_state_prompted(route_state: dict[str, Any], now: datetime) -> None:
    timestamp = now.isoformat(timespec="seconds")
    route_state["status"] = "pending"
    route_state["last_prompt_at"] = timestamp
    route_state["next_check_at"] = (now + NOTIFICATION_LOUDNESS_INTERVAL).isoformat(timespec="seconds")
    route_state["updated_at"] = timestamp


def _cancel_queued_notification_loudness_items(account_store: AccountStore, account_id: str, event: IncomingEvent) -> None:
    route_key = _route_key(event)
    rows = account_store.read_proactive_outbox(account_id)
    changed = False
    timestamp = utc_now()
    for item in rows:
        if not isinstance(item, dict) or not is_notification_loudness_outbox_item(item):
            continue
        if str(item.get("route_key") or "") != route_key:
            continue
        if str(item.get("status") or "queued").strip().casefold() != "queued":
            continue
        item["status"] = "cancelled"
        item["updated_at"] = timestamp
        history = item.setdefault("status_history", [])
        if not isinstance(history, list):
            history = []
            item["status_history"] = history
        history.append({"at": timestamp, "status": "cancelled", "reason": "notification_loudness_decided"})
        changed = True
    if changed:
        account_store.write_proactive_outbox(account_id, rows)


def _has_queued_notification_loudness_item(account_store: AccountStore, account_id: str, route_key: str) -> bool:
    for item in account_store.read_proactive_outbox(account_id):
        if not isinstance(item, dict) or not is_notification_loudness_outbox_item(item):
            continue
        if str(item.get("route_key") or "") != str(route_key):
            continue
        if str(item.get("status") or "queued").strip().casefold() == "queued":
            return True
    return False


def _event_route(event: IncomingEvent) -> dict[str, Any]:
    return {
        "channel": event.channel,
        "chat_id": event.chat_id,
        "chat_type": event.chat_type,
        "adapter_slot": event.adapter_slot,
    }


def _route_key(event: IncomingEvent) -> str:
    return f"{event.channel}:{event.adapter_slot}:{event.chat_id}"


def _private_route(route: Any) -> bool:
    return isinstance(route, Mapping) and route.get("chat_type") == "private" and bool(str(route.get("channel") or "").strip()) and bool(str(route.get("chat_id") or "").strip())


def _event_has_current_private_route(account_store: AccountStore, event: IncomingEvent) -> bool:
    route = account_store.get_identity_route(event.identity_key)
    if not _private_route(route):
        return False
    return (
        str(route.get("channel") or "") == event.channel
        and str(route.get("chat_id") or "") == event.chat_id
        and _route_slot(route.get("adapter_slot")) == int(event.adapter_slot or 1)
    )


def _route_slot(value: Any) -> int:
    try:
        return int(value or 1)
    except (TypeError, ValueError):
        return 1


def _parse_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _normalize_text(text: str) -> str:
    normalized = str(text or "").casefold().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    for char in ",.;:!?()[]{}\"'":
        normalized = normalized.replace(char, " ")
    return " ".join(normalized.split())
