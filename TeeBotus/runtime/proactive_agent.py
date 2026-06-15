from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from inspect import isawaitable
from typing import Any, Callable, Iterable, Mapping

from TeeBotus.runtime.accounts import AccountStore, utc_now
from TeeBotus.runtime.actions import SendText
from TeeBotus.runtime.events import IncomingEvent
from TeeBotus.runtime.message_tracking import MessageTracker, SentMessageRef

PROACTIVE_COMMANDS = {"/proactive", "/agent", "/proaktiv"}
PROACTIVE_ALLOWED_CATEGORIES = frozenset({"reminder", "task", "tip", "test", "image", "analysis", "reflection"})
PROACTIVE_DEFAULT_CATEGORIES = ("reminder", "task", "tip")
PROACTIVE_TERMINAL_STATUSES = frozenset({"sent", "skipped", "failed", "cancelled"})
PROACTIVE_INSTANCE_LIST_ENV = "TEEBOTUS_PROACTIVE_AGENT_INSTANCES"
PROACTIVE_INSTANCE_FLAG_PREFIX = "TEEBOTUS_PROACTIVE_AGENT_"
PROACTIVE_RISK_BLOCK_CATEGORIES = frozenset({"analysis", "reflection", "test", "image"})
PROACTIVE_RISK_MEMORY_KINDS = frozenset(
    {
        "risk_signal",
        "suicidal_ideation",
        "self_harm_signal",
        "violence_risk_signal",
        "neglect_risk_signal",
        "means_access",
    }
)
PROACTIVE_RISK_BLOCK_GATES = frozenset({"blocked", "crisis", "red", "acute", "unsafe"})
PROACTIVE_RISK_REVIEW_GATES = frozenset({"needs_review", "review", "human_review"})
PROACTIVE_RISK_LOOKBACK_DAYS = 30
PROACTIVE_PLANNER_MEMORY_KINDS = frozenset(
    {
        "therapy_goal",
        "treatment_goal",
        "coping_strategy",
        "homework",
        "task",
        "next_step",
        "treatment_plan",
    }
)


@dataclass(frozen=True)
class ProactiveDecision:
    allowed: bool
    reason: str
    route: dict[str, Any] | None = None


@dataclass(frozen=True)
class ProactiveAgentHealth:
    account_id: str
    ok: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProactiveDispatchResult:
    account_id: str
    item_id: str
    status: str
    reason: str
    channel: str = ""
    message_ref: str = ""


@dataclass(frozen=True)
class ProactivePlanningResult:
    account_id: str
    created_memory_ids: tuple[str, ...] = ()
    queued_item_ids: tuple[str, ...] = ()
    skipped_reason: str = ""


ProactiveSender = Callable[[dict[str, Any], SendText, dict[str, Any]], Any]


def handle_proactive_command(event: IncomingEvent, account_store: AccountStore, account_id: str) -> tuple[SendText, ...] | None:
    parts = str(event.text or "").strip().split()
    if not parts or parts[0].casefold() not in PROACTIVE_COMMANDS:
        return None
    if event.chat_type != "private":
        return (SendText(event.chat_id, "Bitte privat.", track=False),)
    if not proactive_agent_instance_enabled(event.instance):
        return (
            SendText(
                event.chat_id,
                "Proaktive Unterstützung ist für diese Instanz nicht freigeschaltet.",
                track=False,
            ),
        )
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


def proactive_agent_instance_enabled(instance_name: str, env: Mapping[str, str] | None = None) -> bool:
    source = env or os.environ
    instance = str(instance_name or "").strip()
    if not instance:
        return False
    listed = _parse_csv(source.get(PROACTIVE_INSTANCE_LIST_ENV, ""))
    if "all" in listed or instance.casefold() in listed or _instance_env_token(instance).casefold() in listed:
        return True
    flag = source.get(f"{PROACTIVE_INSTANCE_FLAG_PREFIX}{_instance_env_token(instance)}")
    return str(flag or "").strip().casefold() in {"1", "true", "yes", "on", "enabled", "ja", "an"}


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
    risk_gate: str = "none",
    planner: Mapping[str, Any] | None = None,
) -> ProactiveDecision:
    normalized_category = str(category or "").strip().casefold()
    normalized_risk_gate = _normalize_risk_gate(risk_gate)
    decision = proactive_policy_decision(account_store, account_id, category=normalized_category, now=now, item={"risk_gate": normalized_risk_gate})
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
            "risk_gate": normalized_risk_gate,
            "planner": {str(key): value for key, value in (planner or {}).items()},
            "policy_result": "allowed",
            "policy_reason": decision.reason,
            "route": decision.route or {},
            "status_history": [{"at": utc_now(), "status": "queued", "reason": "created"}],
        },
    )
    return ProactiveDecision(True, f"queued:{item_id}", decision.route)


def run_proactive_reflection_planner(
    account_store: AccountStore,
    account_id: str,
    *,
    now: datetime | None = None,
    max_items: int = 1,
) -> ProactivePlanningResult:
    resolved_now = now or datetime.now(timezone.utc)
    state = _normalized_agent_state(account_store.read_agent_state(account_id))
    if not state["proactive"]["enabled"]:
        return ProactivePlanningResult(account_id, skipped_reason="proactive_disabled")
    if active_proactive_risk_memory_ids(account_store, account_id, now=resolved_now):
        return ProactivePlanningResult(account_id, skipped_reason="active_risk_signal")
    created_memory_ids: list[str] = []
    queued_item_ids: list[str] = []
    existing_fingerprints = _existing_proactive_plan_fingerprints(account_store, account_id)
    for source in _proactive_planner_candidates(account_store, account_id):
        source_id = str(source.get("id") or "").strip()
        if not source_id:
            continue
        fingerprint = _proactive_plan_fingerprint(account_id, source)
        if fingerprint in existing_fingerprints:
            continue
        reflection_id = account_store.append_structured_memory_entry(
            account_id,
            {
                "kind": "reflection",
                "memory_type": "semantic",
                "user_text": f"Proaktive Reflexion zu {source_id}: sanftes Follow-up ist fachlich plausibel, sofern Consent und Policy weiter passen.",
                "bot_text": "Automatisch vom Proactive Planner erzeugt; keine Diagnose und keine direkte Sendefreigabe.",
                "importance": 3,
                "related_ids": [source_id],
                "supports": [source_id],
                "relations": [
                    {
                        "type": "derived_from",
                        "target_id": source_id,
                        "valid_from": resolved_now.isoformat(timespec="seconds"),
                        "provenance": {"job": "proactive-reflection-planner"},
                    }
                ],
                "proactive_plan_fingerprint": fingerprint,
            },
        )
        decision = queue_proactive_message(
            account_store,
            account_id,
            category="reminder",
            intent="planner_follow_up",
            message_text=_proactive_planner_message(source),
            reason_memory_ids=(source_id, reflection_id),
            due_at=_default_proactive_due_at(resolved_now),
            now=resolved_now,
            risk_gate="none",
            planner={
                "fingerprint": fingerprint,
                "source_memory_id": source_id,
                "reflection_memory_id": reflection_id,
                "collaboration_marker": "agent_suggested",
                "intervention_type": "reminder",
                "review_signal": "User berichtet erledigt/nicht erledigt/Belastung",
            },
        )
        if not decision.allowed:
            return ProactivePlanningResult(account_id, tuple(created_memory_ids), tuple(queued_item_ids), decision.reason)
        created_memory_ids.append(reflection_id)
        queued_item_ids.append(decision.reason.removeprefix("queued:"))
        existing_fingerprints.add(fingerprint)
        if len(queued_item_ids) >= max_items:
            break
    if not queued_item_ids:
        return ProactivePlanningResult(account_id, tuple(created_memory_ids), (), "no_candidate")
    return ProactivePlanningResult(account_id, tuple(created_memory_ids), tuple(queued_item_ids))


def proactive_policy_decision(
    account_store: AccountStore,
    account_id: str,
    *,
    category: str,
    now: datetime | None = None,
    exclude_item_id: str = "",
    item: Mapping[str, Any] | None = None,
) -> ProactiveDecision:
    state = _normalized_agent_state(account_store.read_agent_state(account_id))
    normalized_category = str(category or "").strip().casefold()
    if normalized_category not in PROACTIVE_ALLOWED_CATEGORIES:
        return ProactiveDecision(False, "category_not_supported")
    if not state["proactive"]["enabled"]:
        return ProactiveDecision(False, "proactive_disabled")
    if normalized_category not in state["consent"]["categories"]:
        return ProactiveDecision(False, "category_not_consented")
    risk_decision = proactive_risk_policy_decision(account_store, account_id, category=normalized_category, now=now, item=item)
    if not risk_decision.allowed:
        return risk_decision
    resolved_now = now or datetime.now(timezone.utc)
    hour = resolved_now.astimezone().hour
    start_hour, end_hour = state["policy"]["allowed_hours"]
    if not _hour_in_window(hour, start_hour, end_hour):
        return ProactiveDecision(False, "outside_allowed_hours")
    if _proactive_daily_count(account_store, account_id, resolved_now, exclude_item_id=exclude_item_id) >= int(state["policy"]["max_messages_per_day"]):
        return ProactiveDecision(False, "daily_limit_reached")
    route = select_proactive_route(account_store, account_id)
    if route is None:
        return ProactiveDecision(False, "no_private_route")
    return ProactiveDecision(True, "allowed", route)


def due_proactive_outbox_items(account_store: AccountStore, account_id: str, *, now: datetime | None = None) -> tuple[dict[str, Any], ...]:
    resolved_now = now or datetime.now(timezone.utc)
    due: list[dict[str, Any]] = []
    for item in account_store.read_proactive_outbox(account_id):
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "queued") != "queued":
            continue
        due_at = _parse_proactive_datetime(str(item.get("due_at") or ""))
        if due_at is not None and due_at > resolved_now:
            continue
        due.append(dict(item))
    return tuple(due)


def update_proactive_outbox_item_status(
    account_store: AccountStore,
    account_id: str,
    item_id: str,
    *,
    status: str,
    reason: str = "",
    now: datetime | None = None,
    dispatch: Mapping[str, Any] | None = None,
) -> bool:
    normalized_status = str(status or "").strip().casefold()
    if normalized_status not in {"queued", *PROACTIVE_TERMINAL_STATUSES}:
        raise ValueError(f"unsupported proactive outbox status: {status}")
    rows = account_store.read_proactive_outbox(account_id)
    changed = False
    timestamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    for item in rows:
        if not isinstance(item, dict) or str(item.get("id") or "") != str(item_id or ""):
            continue
        item["status"] = normalized_status
        item["updated_at"] = timestamp
        if normalized_status == "sent":
            item["sent_at"] = timestamp
        if dispatch:
            item["dispatch"] = {str(key): value for key, value in dispatch.items()}
        history = item.setdefault("status_history", [])
        if not isinstance(history, list):
            history = []
            item["status_history"] = history
        history.append({"at": timestamp, "status": normalized_status, "reason": str(reason or "").strip()})
        changed = True
        break
    if changed:
        account_store.write_proactive_outbox(account_id, rows)
    return changed


async def dispatch_due_proactive_outbox_items(
    account_store: AccountStore,
    account_id: str,
    *,
    senders: Mapping[str, ProactiveSender],
    now: datetime | None = None,
    message_tracker: MessageTracker | None = None,
    instance_name: str = "",
) -> tuple[ProactiveDispatchResult, ...]:
    resolved_now = now or datetime.now(timezone.utc)
    results: list[ProactiveDispatchResult] = []
    for item in due_proactive_outbox_items(account_store, account_id, now=resolved_now):
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            results.append(ProactiveDispatchResult(account_id, "", "failed", "missing_item_id"))
            continue
        category = str(item.get("category") or "").strip().casefold()
        decision = proactive_policy_decision(account_store, account_id, category=category, now=resolved_now, exclude_item_id=item_id, item=item)
        if not decision.allowed:
            update_proactive_outbox_item_status(account_store, account_id, item_id, status="skipped", reason=f"policy:{decision.reason}", now=resolved_now)
            results.append(ProactiveDispatchResult(account_id, item_id, "skipped", decision.reason, _item_channel(item)))
            continue
        route = decision.route or _item_route(item)
        channel = str(route.get("channel") or "").strip().casefold()
        chat_id = str(route.get("chat_id") or "").strip()
        if route.get("chat_type") != "private" or not channel or not chat_id:
            update_proactive_outbox_item_status(account_store, account_id, item_id, status="skipped", reason="invalid_route", now=resolved_now)
            results.append(ProactiveDispatchResult(account_id, item_id, "skipped", "invalid_route", channel))
            continue
        sender = senders.get(channel)
        if sender is None:
            update_proactive_outbox_item_status(account_store, account_id, item_id, status="failed", reason=f"missing_sender:{channel}", now=resolved_now)
            results.append(ProactiveDispatchResult(account_id, item_id, "failed", "missing_sender", channel))
            continue
        message_text = str(item.get("message_text") or "").strip()
        if not message_text:
            update_proactive_outbox_item_status(account_store, account_id, item_id, status="failed", reason="missing_message_text", now=resolved_now)
            results.append(ProactiveDispatchResult(account_id, item_id, "failed", "missing_message_text", channel))
            continue
        action = SendText(chat_id, message_text, track=True)
        try:
            sent_ref = await _maybe_await(sender(route, action, item))
        except Exception as exc:  # pragma: no cover - exact adapter exception types are channel specific
            update_proactive_outbox_item_status(account_store, account_id, item_id, status="failed", reason=f"send_error:{type(exc).__name__}", now=resolved_now)
            results.append(ProactiveDispatchResult(account_id, item_id, "failed", f"send_error:{type(exc).__name__}", channel))
            continue
        message_ref = _normalize_sent_ref(sent_ref)
        dispatch_meta = {"channel": channel, "chat_id": chat_id, "message_ref": message_ref}
        update_proactive_outbox_item_status(account_store, account_id, item_id, status="sent", reason="sent", now=resolved_now, dispatch=dispatch_meta)
        _record_proactive_sent_ref(
            message_tracker,
            instance_name=instance_name or account_store.instance_name,
            account_id=account_id,
            channel=channel,
            chat_id=chat_id,
            message_ref=message_ref,
        )
        results.append(ProactiveDispatchResult(account_id, item_id, "sent", "sent", channel, message_ref))
    return tuple(results)


def check_proactive_agent_account(account_store: AccountStore, account_id: str) -> ProactiveAgentHealth:
    errors: list[str] = []
    state = account_store.read_agent_state(account_id)
    if state:
        if state.get("schema_version") != 1:
            errors.append("agent_state schema_version is not 1")
        normalized_state = _normalized_agent_state(state)
        if normalized_state["proactive"]["enabled"] and not normalized_state["consent"]["categories"]:
            errors.append("proactive enabled without consent categories")
    else:
        normalized_state = _normalized_agent_state({})
    outbox = account_store.read_proactive_outbox(account_id)
    seen_ids: set[str] = set()
    consented_categories = set(normalized_state["consent"]["categories"])
    for index, item in enumerate(outbox):
        if not isinstance(item, dict):
            errors.append(f"outbox item {index} is not an object")
            continue
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            errors.append(f"outbox item {index} missing id")
        elif item_id in seen_ids:
            errors.append(f"duplicate outbox item id: {item_id}")
        seen_ids.add(item_id)
        status = str(item.get("status") or "queued").strip().casefold()
        if status not in {"queued", *PROACTIVE_TERMINAL_STATUSES}:
            errors.append(f"outbox item {item_id or index} has unsupported status: {status}")
        category = str(item.get("category") or "").strip().casefold()
        if category not in PROACTIVE_ALLOWED_CATEGORIES:
            errors.append(f"outbox item {item_id or index} has unsupported category: {category}")
        if status == "queued" and category and category not in consented_categories:
            errors.append(f"queued outbox item {item_id or index} category is not consented: {category}")
        risk_gate = _normalize_risk_gate(item.get("risk_gate"))
        if status == "queued" and risk_gate in PROACTIVE_RISK_BLOCK_GATES | PROACTIVE_RISK_REVIEW_GATES:
            errors.append(f"queued outbox item {item_id or index} risk_gate blocks proactive dispatch: {risk_gate}")
        for key in ("intent", "message_text"):
            if not str(item.get(key) or "").strip():
                errors.append(f"outbox item {item_id or index} missing {key}")
        due_at = str(item.get("due_at") or "").strip()
        if due_at and _parse_proactive_datetime(due_at) is None:
            errors.append(f"outbox item {item_id or index} has invalid due_at")
        route = item.get("route")
        if status == "queued":
            if not isinstance(route, dict):
                errors.append(f"queued outbox item {item_id or index} missing route")
            else:
                if route.get("chat_type") != "private":
                    errors.append(f"queued outbox item {item_id or index} route is not private")
                if not str(route.get("channel") or "").strip():
                    errors.append(f"queued outbox item {item_id or index} missing route channel")
                if not str(route.get("chat_id") or "").strip():
                    errors.append(f"queued outbox item {item_id or index} missing route chat_id")
    return ProactiveAgentHealth(account_id, not errors, tuple(errors))


def proactive_risk_policy_decision(
    account_store: AccountStore,
    account_id: str,
    *,
    category: str,
    now: datetime | None = None,
    item: Mapping[str, Any] | None = None,
) -> ProactiveDecision:
    risk_gate = _normalize_risk_gate((item or {}).get("risk_gate"))
    if risk_gate in PROACTIVE_RISK_BLOCK_GATES:
        return ProactiveDecision(False, f"risk_gate_blocked:{risk_gate}")
    if risk_gate in PROACTIVE_RISK_REVIEW_GATES:
        return ProactiveDecision(False, f"risk_gate_needs_review:{risk_gate}")
    normalized_category = str(category or "").strip().casefold()
    if normalized_category in PROACTIVE_RISK_BLOCK_CATEGORIES and active_proactive_risk_memory_ids(account_store, account_id, now=now):
        return ProactiveDecision(False, "active_risk_signal")
    return ProactiveDecision(True, "risk_ok")


def active_proactive_risk_memory_ids(account_store: AccountStore, account_id: str, *, now: datetime | None = None) -> tuple[str, ...]:
    resolved_now = now or datetime.now(timezone.utc)
    active: list[str] = []
    for entry in account_store.read_memory_entries(account_id):
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind") or "").strip().casefold()
        if kind not in PROACTIVE_RISK_MEMORY_KINDS:
            continue
        if _risk_memory_is_active(entry, resolved_now):
            memory_id = str(entry.get("id") or "").strip()
            if memory_id:
                active.append(memory_id)
    return tuple(active)


def _proactive_planner_candidates(account_store: AccountStore, account_id: str) -> tuple[dict[str, Any], ...]:
    rows = [
        entry
        for entry in account_store.read_memory_entries(account_id)
        if isinstance(entry, dict) and str(entry.get("kind") or "").strip().casefold() in PROACTIVE_PLANNER_MEMORY_KINDS
    ]
    rows.sort(key=lambda entry: (_parse_proactive_datetime(str(entry.get("updated_at") or entry.get("created_at") or "")) or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    return tuple(rows)


def _existing_proactive_plan_fingerprints(account_store: AccountStore, account_id: str) -> set[str]:
    fingerprints: set[str] = set()
    for entry in account_store.read_memory_entries(account_id):
        if isinstance(entry, dict):
            fingerprint = str(entry.get("proactive_plan_fingerprint") or "").strip()
            if fingerprint:
                fingerprints.add(fingerprint)
    for item in account_store.read_proactive_outbox(account_id):
        if not isinstance(item, dict):
            continue
        planner = item.get("planner")
        if isinstance(planner, dict):
            fingerprint = str(planner.get("fingerprint") or "").strip()
            if fingerprint:
                fingerprints.add(fingerprint)
    return fingerprints


def _proactive_plan_fingerprint(account_id: str, source: Mapping[str, Any]) -> str:
    payload = "|".join(
        [
            "proactive-plan-v1",
            str(account_id),
            str(source.get("id") or ""),
            str(source.get("kind") or ""),
            str(source.get("updated_at") or source.get("created_at") or ""),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _proactive_planner_message(source: Mapping[str, Any]) -> str:
    text = str(source.get("user_text") or source.get("bot_text") or "deinem Vorhaben").strip()
    short = " ".join(text.split())
    if len(short) > 90:
        short = short[:87].rstrip() + "..."
    return f"Kurzer Check-in zu deinem Vorhaben: {short} Magst du kurz sagen, ob du daran weiterarbeiten moechtest?"


def _default_proactive_due_at(now: datetime) -> str:
    due = now + timedelta(days=1)
    due = due.replace(hour=10, minute=0, second=0, microsecond=0)
    return due.isoformat()


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
    return sorted(routes, key=lambda route: (preferred_order.get(str(route.get("channel")), 99), -_route_seen_timestamp(route)))[0]


def _proactive_daily_count(account_store: AccountStore, account_id: str, now: datetime, *, exclude_item_id: str = "") -> int:
    count = 0
    for item in account_store.read_proactive_outbox(account_id):
        if not isinstance(item, dict):
            continue
        if exclude_item_id and str(item.get("id") or "") == exclude_item_id:
            continue
        status = str(item.get("status") or "queued")
        if status not in {"queued", "sent"}:
            continue
        timestamp = _parse_proactive_datetime(str(item.get("sent_at") or item.get("due_at") or item.get("created_at") or ""))
        if timestamp is None:
            continue
        if timestamp.astimezone().date() == now.astimezone().date():
            count += 1
    return count


async def _maybe_await(value: Any) -> Any:
    if isawaitable(value):
        return await value
    return value


def _item_route(item: Mapping[str, Any]) -> dict[str, Any]:
    route = item.get("route")
    return dict(route) if isinstance(route, dict) else {}


def _item_channel(item: Mapping[str, Any]) -> str:
    return str(_item_route(item).get("channel") or "").strip().casefold()


def _normalize_sent_ref(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        for item in value:
            normalized = _normalize_sent_ref(item)
            if normalized:
                return normalized
        return ""
    if value is None:
        return ""
    return str(value)


def _normalize_risk_gate(value: Any) -> str:
    text = str(value or "none").strip().casefold()
    return text or "none"


def _risk_memory_is_active(entry: Mapping[str, Any], now: datetime) -> bool:
    valid_to = _parse_proactive_datetime(str(entry.get("valid_to") or ""))
    if valid_to is not None:
        return valid_to >= now
    valid_from = _parse_proactive_datetime(str(entry.get("valid_from") or ""))
    if valid_from is not None and valid_from > now:
        return False
    timestamp = _parse_proactive_datetime(str(entry.get("updated_at") or entry.get("created_at") or ""))
    if timestamp is None:
        return True
    age_seconds = max(0.0, (now - timestamp).total_seconds())
    return age_seconds <= PROACTIVE_RISK_LOOKBACK_DAYS * 24 * 60 * 60


def _record_proactive_sent_ref(
    message_tracker: MessageTracker | None,
    *,
    instance_name: str,
    account_id: str,
    channel: str,
    chat_id: str,
    message_ref: str,
) -> None:
    if message_tracker is None or not message_ref:
        return
    ref_kind = {
        "telegram": "telegram_message_id",
        "signal": "signal_timestamp",
        "matrix": "matrix_event_id",
    }.get(channel)
    if ref_kind is None:
        return
    message_tracker.record(
        SentMessageRef(
            channel=channel,
            instance_name=instance_name,
            account_id=account_id,
            chat_id=chat_id,
            message_ref=message_ref,
            ref_kind=ref_kind,  # type: ignore[arg-type]
        )
    )


def _route_seen_timestamp(route: Mapping[str, Any]) -> float:
    parsed = _parse_proactive_datetime(str(route.get("last_seen_at") or ""))
    if parsed is None:
        return 0.0
    return parsed.timestamp()


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
    policy["max_messages_per_day"] = max(0, _normalize_int(policy.get("max_messages_per_day"), default=2))
    return state


def _normalize_hour(value: Any, *, default: int) -> int:
    try:
        hour = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(23, hour))


def _normalize_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_csv(value: str) -> set[str]:
    return {part.strip().casefold() for part in str(value or "").split(",") if part.strip()}


def _instance_env_token(instance_name: str) -> str:
    token = "".join(char if char.isalnum() else "_" for char in str(instance_name or "").strip().upper())
    return "_".join(part for part in token.split("_") if part)


def _hour_in_window(hour: int, start_hour: int, end_hour: int) -> bool:
    if start_hour == end_hour:
        return False
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def _parse_proactive_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
