from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from TeeBotus.runtime.accounts import AccountStore, utc_now
from TeeBotus.runtime.actions import SendText
from TeeBotus.runtime.activity_profile import contact_timing_decision
from TeeBotus.runtime.events import IncomingEvent

NOTIFICATION_LOUDNESS_SYSTEM_ITEM = "notification_loudness"
NOTIFICATION_LOUDNESS_INTENT = "notification_loudness_check"
NOTIFICATION_LOUDNESS_ONLINE_WINDOW = timedelta(minutes=5)
NOTIFICATION_LOUDNESS_WAKE_HOURS = (8, 22)
NOTIFICATION_LOUDNESS_PENDING_STATUS = "pending"
NOTIFICATION_LOUDNESS_TERMINAL_STATUSES = frozenset({"confirmed", "declined"})

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
    if not _notification_loudness_prompt_allowed(route_state, resolved_now, require_online=False):
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
    state_changed = False
    for route_key, route_state in list(routes.items()):
        if not isinstance(route_state, dict):
            continue
        status = str(route_state.get("status") or "unknown").strip().casefold()
        if status in NOTIFICATION_LOUDNESS_TERMINAL_STATUSES:
            state_changed = _mark_notification_loudness_checks_stopped(route_state, status) or state_changed
            continue
        if status != NOTIFICATION_LOUDNESS_PENDING_STATUS:
            continue
        _refresh_route_state_from_account_routes(account_store, account_id, str(route_key), route_state)
        route = route_state.get("route")
        if isinstance(route, Mapping):
            adaptive_decision = contact_timing_decision(account_store, account_id, now=resolved_now, route=route)
            if not adaptive_decision.allowed:
                continue
        if not _notification_loudness_prompt_allowed(route_state, resolved_now, require_online=True):
            continue
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
    if queued_ids or state_changed:
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
    if status in NOTIFICATION_LOUDNESS_TERMINAL_STATUSES:
        route_state["checks_active"] = False
        route_state["checks_stopped_at"] = timestamp
        route_state["checks_stop_reason"] = status
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
    route_state["identity_key"] = event.identity_key
    return route_state


def _mark_notification_loudness_prompted(route_state: dict[str, Any], event: IncomingEvent, now: datetime) -> None:
    route_state["route"] = _event_route(event)
    _mark_route_state_prompted(route_state, now)


def _mark_route_state_prompted(route_state: dict[str, Any], now: datetime) -> None:
    timestamp = now.isoformat(timespec="seconds")
    route_state["status"] = NOTIFICATION_LOUDNESS_PENDING_STATUS
    route_state["checks_active"] = True
    route_state.pop("checks_stopped_at", None)
    route_state.pop("checks_stop_reason", None)
    route_state["last_prompt_at"] = timestamp
    route_state.pop("next_check_at", None)
    route_state["updated_at"] = timestamp
    prompts_by_date = route_state.setdefault("prompted_windows_by_date", {})
    if not isinstance(prompts_by_date, dict):
        prompts_by_date = {}
        route_state["prompted_windows_by_date"] = prompts_by_date
    date_key = _wake_date_key(now)
    windows = prompts_by_date.setdefault(date_key, [])
    if not isinstance(windows, list):
        windows = []
        prompts_by_date[date_key] = windows
    window = _wake_window_label(now)
    if window and window not in windows:
        windows.append(window)
    _trim_prompted_window_dates(prompts_by_date)


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


def _mark_notification_loudness_checks_stopped(route_state: dict[str, Any], reason: str) -> bool:
    if route_state.get("checks_active") is False and route_state.get("checks_stop_reason"):
        return False
    route_state["checks_active"] = False
    route_state["checks_stopped_at"] = utc_now()
    route_state["checks_stop_reason"] = reason
    return True


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


def _refresh_route_state_from_account_routes(account_store: AccountStore, account_id: str, route_key: str, route_state: dict[str, Any]) -> None:
    identity_key = str(route_state.get("identity_key") or "").strip()
    candidate_keys = [identity_key] if identity_key else []
    try:
        candidate_keys.extend(identity for identity in account_store.list_identities_for_account(account_id) if identity not in candidate_keys)
    except Exception:
        pass
    for candidate in candidate_keys:
        route = account_store.get_identity_route(candidate)
        if not _private_route(route):
            continue
        if _route_key_from_route(route) != route_key:
            continue
        route_state["identity_key"] = candidate
        route_state["route"] = route
        return


def _route_key_from_route(route: Mapping[str, Any]) -> str:
    return f"{route.get('channel')}:{_route_slot(route.get('adapter_slot'))}:{route.get('chat_id')}"


def _notification_loudness_prompt_allowed(route_state: Mapping[str, Any], now: datetime, *, require_online: bool) -> bool:
    if _wake_window_label(now) == "":
        return False
    if _already_prompted_in_wake_window(route_state, now):
        return False
    if require_online:
        route = route_state.get("route")
        if not isinstance(route, Mapping) or not _route_recently_seen(route, now):
            return False
    return True


def _already_prompted_in_wake_window(route_state: Mapping[str, Any], now: datetime) -> bool:
    prompts_by_date = route_state.get("prompted_windows_by_date")
    if not isinstance(prompts_by_date, Mapping):
        return False
    windows = prompts_by_date.get(_wake_date_key(now))
    if not isinstance(windows, list):
        return False
    return _wake_window_label(now) in {str(window) for window in windows}


def _wake_date_key(now: datetime) -> str:
    return now.astimezone().date().isoformat()


def _wake_window_label(now: datetime) -> str:
    local = now.astimezone()
    start_hour, end_hour = NOTIFICATION_LOUDNESS_WAKE_HOURS
    if not _hour_in_window(local.hour, start_hour, end_hour):
        return ""
    midpoint = start_hour + ((end_hour - start_hour) % 24) / 2
    if start_hour < end_hour:
        return "first" if local.hour + local.minute / 60 < midpoint else "second"
    hour_value = local.hour + local.minute / 60
    normalized = hour_value if hour_value >= start_hour else hour_value + 24
    return "first" if normalized < midpoint else "second"


def _hour_in_window(hour: int, start_hour: int, end_hour: int) -> bool:
    if start_hour == end_hour:
        return True
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def _route_recently_seen(route: Mapping[str, Any], now: datetime) -> bool:
    last_seen = _parse_datetime(str(route.get("last_seen_at") or ""))
    if last_seen is None:
        return False
    age = now - last_seen
    return timedelta(0) <= age <= NOTIFICATION_LOUDNESS_ONLINE_WINDOW


def _trim_prompted_window_dates(prompts_by_date: dict[str, Any]) -> None:
    for date_key in sorted(prompts_by_date)[:-14]:
        prompts_by_date.pop(date_key, None)


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
