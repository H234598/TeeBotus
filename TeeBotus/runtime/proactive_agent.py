from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from TeeBotus.runtime.accounts import AccountStore, utc_now
from TeeBotus.runtime.actions import SendText
from TeeBotus.runtime.events import IncomingEvent

PROACTIVE_COMMANDS = {"/proactive", "/agent", "/proaktiv"}
PROACTIVE_ALLOWED_CATEGORIES = frozenset({"reminder", "task", "tip", "test", "image", "analysis", "reflection"})
PROACTIVE_DEFAULT_CATEGORIES = ("reminder", "task", "tip")


@dataclass(frozen=True)
class ProactiveDecision:
    allowed: bool
    reason: str
    route: dict[str, Any] | None = None


def handle_proactive_command(event: IncomingEvent, account_store: AccountStore, account_id: str) -> tuple[SendText, ...] | None:
    parts = str(event.text or "").strip().split()
    if not parts or parts[0].casefold() not in PROACTIVE_COMMANDS:
        return None
    if event.chat_type != "private":
        return (SendText(event.chat_id, "Bitte privat.", track=False),)
    subcommand = parts[1].casefold() if len(parts) > 1 else "status"
    if subcommand in {"on", "enable", "an", "ein"}:
        state = enable_proactive_agent(account_store, account_id)
        categories = ", ".join(state["consent"]["categories"])
        return (
            SendText(
                event.chat_id,
                "Proaktive Unterstützung ist aktiviert.\n"
                f"Aktivierte Kategorien: {categories}\n"
                "Ich lege proaktive Nachrichten zuerst in eine interne Outbox und sende nur, wenn Policy und Route passen.",
                track=False,
            ),
        )
    if subcommand in {"off", "disable", "aus"}:
        disable_proactive_agent(account_store, account_id)
        return (SendText(event.chat_id, "Proaktive Unterstützung ist deaktiviert.", track=False),)
    if subcommand in {"status", "info"}:
        return (SendText(event.chat_id, proactive_status_text(account_store, account_id), track=False),)
    return (
        SendText(
            event.chat_id,
            "Nutzung: /proactive status, /proactive on oder /proactive off.",
            track=False,
        ),
    )


def enable_proactive_agent(account_store: AccountStore, account_id: str, *, categories: Iterable[str] = PROACTIVE_DEFAULT_CATEGORIES) -> dict[str, Any]:
    state = _normalized_agent_state(account_store.read_agent_state(account_id))
    enabled_categories = [
        category
        for category in dict.fromkeys(str(value or "").strip().casefold() for value in categories)
        if category in PROACTIVE_ALLOWED_CATEGORIES
    ]
    if not enabled_categories:
        enabled_categories = list(PROACTIVE_DEFAULT_CATEGORIES)
    state["proactive"]["enabled"] = True
    state["proactive"]["updated_at"] = utc_now()
    state["consent"]["categories"] = enabled_categories
    state["consent"]["updated_at"] = state["proactive"]["updated_at"]
    account_store.write_agent_state(account_id, state)
    return state


def disable_proactive_agent(account_store: AccountStore, account_id: str) -> dict[str, Any]:
    state = _normalized_agent_state(account_store.read_agent_state(account_id))
    state["proactive"]["enabled"] = False
    state["proactive"]["updated_at"] = utc_now()
    account_store.write_agent_state(account_id, state)
    return state


def proactive_status_text(account_store: AccountStore, account_id: str) -> str:
    state = _normalized_agent_state(account_store.read_agent_state(account_id))
    outbox = account_store.read_proactive_outbox(account_id)
    queued = sum(1 for item in outbox if isinstance(item, dict) and item.get("status", "queued") == "queued")
    enabled = "ja" if state["proactive"]["enabled"] else "nein"
    categories = ", ".join(state["consent"]["categories"]) or "keine"
    return "\n".join(
        [
            "Proaktive Unterstützung",
            f"- aktiviert: {enabled}",
            f"- Kategorien: {categories}",
            f"- erlaubtes Zeitfenster: {state['policy']['allowed_hours'][0]}-{state['policy']['allowed_hours'][1]} Uhr",
            f"- queued_outbox_items: {queued}",
        ]
    )


def queue_proactive_message(
    account_store: AccountStore,
    account_id: str,
    *,
    category: str,
    message_text: str,
    intent: str,
    reason_memory_ids: Iterable[str] = (),
    due_at: str = "",
    now: datetime | None = None,
) -> ProactiveDecision:
    normalized_category = str(category or "").strip().casefold()
    decision = proactive_policy_decision(account_store, account_id, category=normalized_category, now=now)
    if not decision.allowed:
        return decision
    item_id = account_store.append_proactive_outbox_item(
        account_id,
        {
            "category": normalized_category,
            "intent": str(intent or "").strip(),
            "message_text": str(message_text or "").strip(),
            "reason_memory_ids": [str(memory_id) for memory_id in reason_memory_ids if str(memory_id or "").strip()],
            "due_at": str(due_at or "").strip(),
            "policy_result": "allowed",
            "policy_reason": decision.reason,
            "route": decision.route or {},
        },
    )
    return ProactiveDecision(True, f"queued:{item_id}", decision.route)


def proactive_policy_decision(
    account_store: AccountStore,
    account_id: str,
    *,
    category: str,
    now: datetime | None = None,
) -> ProactiveDecision:
    state = _normalized_agent_state(account_store.read_agent_state(account_id))
    normalized_category = str(category or "").strip().casefold()
    if normalized_category not in PROACTIVE_ALLOWED_CATEGORIES:
        return ProactiveDecision(False, "category_not_supported")
    if not state["proactive"]["enabled"]:
        return ProactiveDecision(False, "proactive_disabled")
    if normalized_category not in state["consent"]["categories"]:
        return ProactiveDecision(False, "category_not_consented")
    resolved_now = now or datetime.now(timezone.utc)
    hour = resolved_now.astimezone().hour
    start_hour, end_hour = state["policy"]["allowed_hours"]
    if not _hour_in_window(hour, start_hour, end_hour):
        return ProactiveDecision(False, "outside_allowed_hours")
    route = select_proactive_route(account_store, account_id)
    if route is None:
        return ProactiveDecision(False, "no_private_route")
    return ProactiveDecision(True, "allowed", route)


def select_proactive_route(account_store: AccountStore, account_id: str) -> dict[str, Any] | None:
    summary = account_store.account_summary(account_id)
    identities = summary.get("linked_identities", [])
    if not isinstance(identities, list):
        return None
    preferred_order = {"signal": 0, "telegram": 1, "matrix": 2}
    routes: list[dict[str, Any]] = []
    for identity in identities:
        route = account_store.get_identity_route(str(identity))
        if not route or route.get("chat_type") != "private":
            continue
        channel = str(route.get("channel") or "").strip()
        chat_id = str(route.get("chat_id") or "").strip()
        if not channel or not chat_id:
            continue
        routes.append(dict(route))
    if not routes:
        return None
    return sorted(routes, key=lambda route: (preferred_order.get(str(route.get("channel")), 99), str(route.get("last_seen_at") or "")))[0]


def _normalized_agent_state(data: dict[str, Any]) -> dict[str, Any]:
    state = dict(data) if isinstance(data, dict) else {}
    state["schema_version"] = 1
    proactive = state.setdefault("proactive", {})
    if not isinstance(proactive, dict):
        proactive = {}
        state["proactive"] = proactive
    proactive.setdefault("enabled", False)
    proactive.setdefault("updated_at", "")
    consent = state.setdefault("consent", {})
    if not isinstance(consent, dict):
        consent = {}
        state["consent"] = consent
    categories = consent.get("categories")
    if not isinstance(categories, list):
        categories = []
    consent["categories"] = [
        category
        for category in dict.fromkeys(str(value or "").strip().casefold() for value in categories)
        if category in PROACTIVE_ALLOWED_CATEGORIES
    ]
    consent.setdefault("updated_at", "")
    policy = state.setdefault("policy", {})
    if not isinstance(policy, dict):
        policy = {}
        state["policy"] = policy
    hours = policy.get("allowed_hours")
    if not isinstance(hours, list) or len(hours) != 2:
        hours = [9, 20]
    policy["allowed_hours"] = [_normalize_hour(hours[0], default=9), _normalize_hour(hours[1], default=20)]
    policy.setdefault("max_messages_per_day", 2)
    return state


def _normalize_hour(value: Any, *, default: int) -> int:
    try:
        hour = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(23, hour))


def _hour_in_window(hour: int, start_hour: int, end_hour: int) -> bool:
    if start_hour == end_hour:
        return False
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour
