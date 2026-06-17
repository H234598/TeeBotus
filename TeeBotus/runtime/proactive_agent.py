from __future__ import annotations

import json
import os
import re
import calendar
from collections.abc import Iterable as IterableABC
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from inspect import isawaitable
from typing import Any, Callable, Iterable, Mapping

from pydantic import ValidationError

from TeeBotus.decisions.proactive import parse_proactive_tool_call_decision
from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, utc_now
from TeeBotus.runtime.actions import OutgoingAction, SendAttachment, SendText
from TeeBotus.runtime.activity_profile import contact_timing_decision
from TeeBotus.runtime.events import IncomingEvent
from TeeBotus.runtime.file_artifacts import generated_file_to_outbox_payload, normalize_generated_file
from TeeBotus.runtime.message_tracking import MessageTracker, SentMessageRef
from TeeBotus.runtime.notification_loudness import is_notification_loudness_outbox_item

PROACTIVE_COMMANDS = {"/proactive", "/agent", "/proaktiv"}
PROACTIVE_ALLOWED_CATEGORIES = frozenset({"reminder", "task", "tip", "test", "image", "analysis", "reflection"})
PROACTIVE_DEFAULT_CATEGORIES = ("reminder", "task", "tip")
PROACTIVE_REVIEW_STATUSES = frozenset({"review_pending"})
PROACTIVE_TERMINAL_STATUSES = frozenset({"sent", "skipped", "failed", "cancelled", "expired"})
PROACTIVE_OUTBOX_STATUSES = frozenset({"queued", *PROACTIVE_REVIEW_STATUSES, *PROACTIVE_TERMINAL_STATUSES})
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
PROACTIVE_UNSAFE_TEXT_PATTERNS = (
    re.compile(r"\bdu\s+(?:hast|leidest\s+an)\s+(?:eine[rmn]?\s+)?(?:depression|angststoerung|ptbs|borderline|bipolare\s+stoerung)\b"),
    re.compile(r"\b(?:ich\s+)?diagnostiziere\b"),
    re.compile(r"\b(?:du\s+bist|das\s+ist)\s+(?:krank|pathologisch|psychotisch|manisch|suizidal)\b"),
    re.compile(r"\bdu\s+musst\s+(?:sofort|jetzt|unbedingt)\b"),
    re.compile(r"\b(?:wenn\s+du\s+das\s+nicht\s+(?:sofort|jetzt)\s+tust|sonst\s+(?:wird|passiert))\b"),
    re.compile(r"\b(?:akute|lebensgefahr|notfall)\b.{0,80}\b(?:du\s+musst|sofort|jetzt)\b"),
    re.compile(r"\bdu\s+(?:erinnerst\s+dich|weisst|weißt)\s+(?:nur\s+)?(?:noch\s+)?nicht\b"),
    re.compile(r"\bdu\s+hast\s+(?:das|es|etwas)(?:\s+(?:bestimmt|sicher|offensichtlich))?\s+verdraengt\b"),
    re.compile(r"\b(?:bestimmt|sicher|offensichtlich)\s+(?:ist|war)\s+dir\s+damals\b"),
    re.compile(r"\b(?:deine\s+)?(?:verdraengte|verdrängte)\s+erinnerung(?:en)?\b"),
)
PROACTIVE_LLM_PLAN_SCHEMA_VERSION = 1
PROACTIVE_LLM_MAX_DECISIONS = 5
PROACTIVE_AGENT_TOOL_NAMES = frozenset(
    {
        "proactive_create_memory",
        "proactive_queue_message",
        "proactive_cancel_item",
        "proactive_snooze_item",
        "proactive_noop",
    }
)
PROACTIVE_LLM_MEMORY_KINDS = frozenset(
    {
        "reflection",
        "summary",
        "next_step",
        "homework",
        "treatment_plan",
        "assessment_note",
        "intervention_note",
        "response_note",
    }
)
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
    queued_count: int = 0
    review_pending_count: int = 0


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


@dataclass(frozen=True)
class ProactiveLLMPlanningResult:
    account_id: str
    created_memory_ids: tuple[str, ...] = ()
    queued_item_ids: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    audit_event_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProactiveAgentToolCall:
    name: str
    arguments: Mapping[str, Any]
    call_id: str = ""


ProactiveSender = Callable[[dict[str, Any], OutgoingAction, dict[str, Any]], Any]


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
    if subcommand in {"pause", "pausieren"}:
        pause_proactive_agent(account_store, account_id)
        return (SendText(event.chat_id, "Proaktive Unterstützung ist pausiert.", track=False),)
    if subcommand in {"resume", "weiter", "fortsetzen"}:
        resume_proactive_agent(account_store, account_id)
        return (SendText(event.chat_id, "Proaktive Unterstützung ist wieder aktiv.", track=False),)
    if subcommand in {"category", "categories", "kategorie", "kategorien"}:
        return (SendText(event.chat_id, _handle_proactive_category_command(account_store, account_id, parts[2:]), track=False),)
    if subcommand in {"hours", "zeit", "zeiten", "window", "fenster"}:
        return (SendText(event.chat_id, _handle_proactive_hours_command(account_store, account_id, parts[2:]), track=False),)
    if subcommand in {"quiet", "ruhe", "ruhezeit"}:
        return (SendText(event.chat_id, _handle_proactive_quiet_command(account_store, account_id, parts[2:]), track=False),)
    if subcommand in {"interval", "abstand"}:
        return (SendText(event.chat_id, _handle_proactive_interval_command(account_store, account_id, parts[2:]), track=False),)
    if subcommand in {"status", "info"}:
        return (SendText(event.chat_id, proactive_status_text(account_store, account_id), track=False),)
    return (
        SendText(
            event.chat_id,
            "Nutzung: /proactive status, on, off, pause, resume, category on|off <name>, hours <start> <ende>, quiet <start> <ende>, interval <minuten>.",
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
    state["proactive"]["paused"] = False
    state["proactive"]["updated_at"] = utc_now()
    state["consent"]["categories"] = enabled_categories
    state["consent"]["updated_at"] = state["proactive"]["updated_at"]
    account_store.write_agent_state(account_id, state)
    return state


def proactive_agent_instance_enabled(instance_name: str, env: Mapping[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
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
    state["proactive"]["paused"] = False
    state["proactive"]["updated_at"] = utc_now()
    account_store.write_agent_state(account_id, state)
    return state


def pause_proactive_agent(account_store: AccountStore, account_id: str) -> dict[str, Any]:
    state = _normalized_agent_state(account_store.read_agent_state(account_id))
    state["proactive"]["paused"] = True
    state["proactive"]["updated_at"] = utc_now()
    account_store.write_agent_state(account_id, state)
    return state


def resume_proactive_agent(account_store: AccountStore, account_id: str) -> dict[str, Any]:
    state = _normalized_agent_state(account_store.read_agent_state(account_id))
    if not state["consent"]["categories"]:
        state["consent"]["categories"] = list(PROACTIVE_DEFAULT_CATEGORIES)
        state["consent"]["updated_at"] = utc_now()
    state["proactive"]["enabled"] = True
    state["proactive"]["paused"] = False
    state["proactive"]["updated_at"] = utc_now()
    account_store.write_agent_state(account_id, state)
    return state


def set_proactive_categories(account_store: AccountStore, account_id: str, categories: Iterable[str]) -> dict[str, Any]:
    state = _normalized_agent_state(account_store.read_agent_state(account_id))
    normalized = [
        category
        for category in dict.fromkeys(str(value or "").strip().casefold() for value in categories)
        if category in PROACTIVE_ALLOWED_CATEGORIES
    ]
    state["consent"]["categories"] = normalized
    state["consent"]["updated_at"] = utc_now()
    account_store.write_agent_state(account_id, state)
    return state


def set_proactive_allowed_hours(account_store: AccountStore, account_id: str, start_hour: Any, end_hour: Any) -> dict[str, Any]:
    state = _normalized_agent_state(account_store.read_agent_state(account_id))
    state["policy"]["allowed_hours"] = [_normalize_hour(start_hour, default=9), _normalize_hour(end_hour, default=20)]
    state["proactive"]["updated_at"] = utc_now()
    account_store.write_agent_state(account_id, state)
    return state


def set_proactive_min_interval_minutes(account_store: AccountStore, account_id: str, minutes: Any) -> dict[str, Any]:
    state = _normalized_agent_state(account_store.read_agent_state(account_id))
    state["policy"]["min_minutes_between_messages"] = min(24 * 60, max(0, _normalize_int(minutes, default=0)))
    state["proactive"]["updated_at"] = utc_now()
    account_store.write_agent_state(account_id, state)
    return state


def proactive_status_text(account_store: AccountStore, account_id: str) -> str:
    state = _normalized_agent_state(account_store.read_agent_state(account_id))
    outbox = account_store.read_proactive_outbox(account_id)
    queued = sum(1 for item in outbox if isinstance(item, dict) and _proactive_item_status(item) == "queued")
    review_pending = sum(1 for item in outbox if isinstance(item, dict) and _proactive_item_status(item) == "review_pending")
    enabled = "ja" if state["proactive"]["enabled"] else "nein"
    paused = "ja" if state["proactive"]["paused"] else "nein"
    categories = ", ".join(state["consent"]["categories"]) or "keine"
    contact_line = _adaptive_contact_status_line(account_store, account_id)
    return "\n".join(
        [
            "Proaktive Unterstützung",
            f"- aktiviert: {enabled}",
            f"- pausiert: {paused}",
            f"- Kategorien: {categories}",
            f"- erlaubtes Zeitfenster: {state['policy']['allowed_hours'][0]}-{state['policy']['allowed_hours'][1]} Uhr",
            f"- Mindestabstand: {state['policy']['min_minutes_between_messages']} Minuten",
            contact_line,
            f"- queued_outbox_items: {queued}",
            f"- review_pending_items: {review_pending}",
        ]
    )


def _adaptive_contact_status_line(account_store: AccountStore, account_id: str) -> str:
    decision = contact_timing_decision(account_store, account_id)
    profile = decision.profile
    if not profile.get("sufficient_data"):
        count = int(profile.get("observation_count") or 0) if isinstance(profile, Mapping) else 0
        return f"- adaptive Kontaktzeit: sammelt Daten ({count} Beobachtungen)"
    profiles = profile.get("profiles")
    if not isinstance(profiles, Mapping):
        return f"- adaptive Kontaktzeit: {decision.reason}"
    day_key = "weekend" if datetime.now(timezone.utc).astimezone().weekday() >= 5 else "weekday"
    day_profile = profiles.get(day_key)
    if not isinstance(day_profile, Mapping) or not day_profile.get("sufficient_data"):
        day_profile = profiles.get("all")
    if not isinstance(day_profile, Mapping):
        return f"- adaptive Kontaktzeit: {decision.reason}"
    recommended = [str(hour) for hour in day_profile.get("recommended_contact_hours", [])[:6]]
    if not recommended:
        return f"- adaptive Kontaktzeit: {decision.reason}"
    return f"- adaptive Kontaktstunden: {', '.join(recommended)} Uhr ({decision.reason})"


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
    file: Mapping[str, Any] | None = None,
    recurrence: str = "",
) -> ProactiveDecision:
    normalized_category = str(category or "").strip().casefold()
    normalized_risk_gate = _normalize_risk_gate(risk_gate)
    policy_item = {"risk_gate": "none"} if normalized_risk_gate in PROACTIVE_RISK_REVIEW_GATES else {"risk_gate": normalized_risk_gate}
    if str(intent or "").strip() == "user_requested_reminder":
        policy_item["user_requested_reminder"] = True
    decision = proactive_policy_decision(account_store, account_id, category=normalized_category, now=now, item=policy_item)
    if not decision.allowed:
        return decision
    status = "review_pending" if normalized_risk_gate in PROACTIVE_RISK_REVIEW_GATES else "queued"
    policy_result = "needs_review" if status == "review_pending" else "allowed"
    policy_reason = f"risk_gate_needs_review:{normalized_risk_gate}" if status == "review_pending" else decision.reason
    payload = {
        "status": status,
        "category": normalized_category,
        "intent": str(intent or "").strip(),
        "message_text": str(message_text or "").strip(),
        "reason_memory_ids": [str(memory_id) for memory_id in reason_memory_ids if str(memory_id or "").strip()],
        "due_at": str(due_at or "").strip(),
        "risk_gate": normalized_risk_gate,
        "planner": {str(key): value for key, value in (planner or {}).items()},
        "policy_result": policy_result,
        "policy_reason": policy_reason,
        "route": decision.route or {},
        "status_history": [{"at": utc_now(), "status": status, "reason": "created" if status == "queued" else policy_reason}],
    }
    if str(intent or "").strip() == "user_requested_reminder":
        payload["user_requested_reminder"] = True
    normalized_recurrence = _normalize_recurrence_rule(recurrence)
    if normalized_recurrence:
        payload["recurrence"] = normalized_recurrence
    if file is not None:
        generated_file = normalize_generated_file(file)
        if generated_file is None:
            return ProactiveDecision(False, "invalid_file")
        payload["file"] = generated_file_to_outbox_payload(generated_file)
    item_id = account_store.append_proactive_outbox_item(account_id, payload)
    return ProactiveDecision(True, f"{status}:{item_id}", decision.route)


def approve_proactive_review_item(
    account_store: AccountStore,
    account_id: str,
    item_id: str,
    *,
    reviewer: str = "operator",
    reason: str = "",
    now: datetime | None = None,
) -> ProactiveDecision:
    rows = account_store.read_proactive_outbox(account_id)
    target: dict[str, Any] | None = None
    for item in rows:
        if isinstance(item, dict) and str(item.get("id") or "").strip() == str(item_id or "").strip():
            target = item
            break
    if target is None:
        return ProactiveDecision(False, "item_not_found")
    if str(target.get("status") or "queued").strip().casefold() != "review_pending":
        return ProactiveDecision(False, "item_not_review_pending")
    category = str(target.get("category") or "").strip().casefold()
    decision = proactive_policy_decision(account_store, account_id, category=category, now=now, exclude_item_id=str(item_id or ""), item={**target, "risk_gate": "none"})
    if not decision.allowed:
        return decision
    timestamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    target["status"] = "queued"
    target["risk_gate"] = "none"
    target["updated_at"] = timestamp
    target["policy_result"] = "allowed"
    target["policy_reason"] = "human_review_approved"
    target["route"] = decision.route or target.get("route") or {}
    target["human_review"] = {
        "status": "approved",
        "reviewer": str(reviewer or "operator").strip()[:80],
        "reason": str(reason or "").strip()[:240],
        "reviewed_at": timestamp,
    }
    history = target.setdefault("status_history", [])
    if not isinstance(history, list):
        history = []
        target["status_history"] = history
    history.append({"at": timestamp, "status": "queued", "reason": "human_review_approved"})
    account_store.write_proactive_outbox(account_id, rows)
    return ProactiveDecision(True, f"queued:{item_id}", decision.route)


def reject_proactive_review_item(
    account_store: AccountStore,
    account_id: str,
    item_id: str,
    *,
    reviewer: str = "operator",
    reason: str = "",
    now: datetime | None = None,
) -> ProactiveDecision:
    rows = account_store.read_proactive_outbox(account_id)
    timestamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    for item in rows:
        if not isinstance(item, dict) or str(item.get("id") or "").strip() != str(item_id or "").strip():
            continue
        if str(item.get("status") or "queued").strip().casefold() != "review_pending":
            return ProactiveDecision(False, "item_not_review_pending")
        item["status"] = "cancelled"
        item["updated_at"] = timestamp
        item["human_review"] = {
            "status": "rejected",
            "reviewer": str(reviewer or "operator").strip()[:80],
            "reason": str(reason or "").strip()[:240],
            "reviewed_at": timestamp,
        }
        history = item.setdefault("status_history", [])
        if not isinstance(history, list):
            history = []
            item["status_history"] = history
        history.append({"at": timestamp, "status": "cancelled", "reason": "human_review_rejected"})
        account_store.write_proactive_outbox(account_id, rows)
        return ProactiveDecision(True, f"cancelled:{item_id}")
    return ProactiveDecision(False, "item_not_found")


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
        plan_memory_ids = _append_proactive_planner_memory_entries(
            account_store,
            account_id,
            source,
            source_id=source_id,
            fingerprint=fingerprint,
            now=resolved_now,
        )
        reflection_id = plan_memory_ids[0]
        decision = queue_proactive_message(
            account_store,
            account_id,
            category="reminder",
            intent="planner_follow_up",
            message_text=_proactive_planner_message(source),
            reason_memory_ids=(source_id, *plan_memory_ids),
            due_at=_default_proactive_due_at(resolved_now),
            now=resolved_now,
            risk_gate="none",
            planner={
                "fingerprint": fingerprint,
                "source_memory_id": source_id,
                "reflection_memory_id": reflection_id,
                "memory_ids": list(plan_memory_ids),
                "collaboration_marker": "agent_suggested",
                "intervention_type": "reminder",
                "review_signal": "User berichtet erledigt/nicht erledigt/Belastung",
            },
        )
        if not decision.allowed:
            return ProactivePlanningResult(account_id, tuple(created_memory_ids), tuple(queued_item_ids), decision.reason)
        created_memory_ids.extend(plan_memory_ids)
        queued_item_ids.append(decision.reason.removeprefix("queued:"))
        existing_fingerprints.add(fingerprint)
        if len(queued_item_ids) >= max_items:
            break
    if not queued_item_ids:
        return ProactivePlanningResult(account_id, tuple(created_memory_ids), (), "no_candidate")
    return ProactivePlanningResult(account_id, tuple(created_memory_ids), tuple(queued_item_ids))


def apply_proactive_llm_plan_text(
    account_store: AccountStore,
    account_id: str,
    plan_text: str,
    *,
    now: datetime | None = None,
) -> ProactiveLLMPlanningResult:
    try:
        payload = json.loads(_strip_json_code_fence(plan_text))
    except json.JSONDecodeError as exc:
        error = f"invalid_json:{exc.msg}"
        audit_id = _append_proactive_llm_audit_event(
            account_store,
            account_id,
            event_type="llm_plan_rejected",
            reason=error,
            plan_text=plan_text,
            now=now,
        )
        return ProactiveLLMPlanningResult(account_id, errors=(error,), audit_event_ids=(audit_id,))
    return apply_proactive_llm_plan(account_store, account_id, payload, now=now)


def run_proactive_llm_planner(
    account_store: AccountStore,
    account_id: str,
    *,
    openai_client: Any,
    instructions: Any,
    now: datetime | None = None,
    max_memory_chars: int = 6000,
) -> ProactiveLLMPlanningResult:
    prompt = build_proactive_llm_planner_prompt(account_store, account_id, max_memory_chars=max_memory_chars)
    response = openai_client.create_reply(prompt, instructions)
    return apply_proactive_llm_plan_text(account_store, account_id, str(getattr(response, "text", response) or ""), now=now)


def run_proactive_tool_agent(
    account_store: AccountStore,
    account_id: str,
    *,
    openai_client: Any,
    instructions: Any,
    now: datetime | None = None,
    max_memory_chars: int = 6000,
) -> ProactiveLLMPlanningResult:
    prompt = build_proactive_tool_agent_prompt(account_store, account_id, max_memory_chars=max_memory_chars)
    tool_definitions = proactive_agent_tool_definitions()
    create_tool_calls = getattr(openai_client, "create_tool_calls", None)
    if not callable(create_tool_calls):
        audit_id = _append_proactive_llm_audit_event(
            account_store,
            account_id,
            event_type="tool_agent_rejected",
            reason="client_missing_create_tool_calls",
            now=now,
        )
        return ProactiveLLMPlanningResult(account_id, errors=("client_missing_create_tool_calls",), audit_event_ids=(audit_id,))
    response = create_tool_calls(prompt, instructions, tool_definitions)
    tool_calls = extract_proactive_agent_tool_calls(response)
    if not tool_calls:
        plan_text = _response_output_text(response)
        if plan_text:
            result = apply_proactive_llm_plan_text(account_store, account_id, plan_text, now=now)
            if not result.errors:
                return result
        audit_id = _append_proactive_llm_audit_event(
            account_store,
            account_id,
            event_type="tool_agent_rejected",
            reason="no_tool_calls",
            payload=_safe_tool_response_payload(response),
            plan_text=plan_text,
            now=now,
        )
        return ProactiveLLMPlanningResult(account_id, errors=("no_tool_calls",), audit_event_ids=(audit_id,))
    return apply_proactive_agent_tool_calls(account_store, account_id, tool_calls, now=now)


def build_proactive_tool_agent_prompt(account_store: AccountStore, account_id: str, *, max_memory_chars: int = 6000) -> str:
    return "\n".join(
        [
            "Du bist der native Tool-Agent fuer TeeBotus Proactive Planning.",
            "Nutze ausschliesslich die bereitgestellten Tools. Sende nie direkt Nachrichten.",
            "Direkter Versand ist verboten; fuer spaetere Kontaktaufnahme nur proactive_queue_message verwenden.",
            "Krisen-, Suizid- oder Selbstverletzungsinhalte nicht proaktiv senden; nutze proactive_noop oder risk_gate needs_review.",
            "Jeder Queue-Vorschlag braucht reason_memory_ids aus dem Kontext.",
            "",
            build_proactive_llm_planner_prompt(account_store, account_id, max_memory_chars=max_memory_chars),
        ]
    )


def proactive_agent_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": "proactive_create_memory",
            "description": "Create one validated internal proactive memory note. Never use for diagnoses.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "kind": {"type": "string"},
                    "text": {"type": "string"},
                    "source_memory_ids": {"type": "array", "items": {"type": "string"}},
                    "importance": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                "required": ["kind", "text"],
            },
        },
        {
            "type": "function",
            "name": "proactive_queue_message",
            "description": "Queue one future proactive message after local consent, route, time and risk validation.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "category": {"type": "string"},
                    "intent": {"type": "string"},
                    "message_text": {"type": "string"},
                    "reason_memory_ids": {"type": "array", "items": {"type": "string"}},
                    "risk_gate": {"type": "string"},
                    "due_at": {"type": "string"},
                    "intervention_type": {"type": "string"},
                    "expected_response": {"type": "string"},
                    "review_signal": {"type": "string"},
                    "collaboration_marker": {"type": "string"},
                    "file": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "filename": {"type": "string"},
                            "content_type": {"type": "string"},
                            "caption": {"type": "string"},
                            "text": {"type": "string"},
                            "base64": {"type": "string"},
                            "data_base64": {"type": "string"},
                        },
                        "required": ["filename"],
                    },
                },
                "required": ["category", "intent", "message_text", "reason_memory_ids"],
            },
        },
        {
            "type": "function",
            "name": "proactive_cancel_item",
            "description": "Cancel one existing queued proactive outbox item.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"item_id": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["item_id"],
            },
        },
        {
            "type": "function",
            "name": "proactive_snooze_item",
            "description": "Move one existing queued proactive outbox item to a later due_at.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"item_id": {"type": "string"}, "due_at": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["item_id", "due_at"],
            },
        },
        {
            "type": "function",
            "name": "proactive_noop",
            "description": "Explicitly do nothing when no safe useful proactive action is available.",
            "parameters": {"type": "object", "additionalProperties": False, "properties": {"reason": {"type": "string"}}},
        },
    ]


def extract_proactive_agent_tool_calls(response: Any) -> tuple[ProactiveAgentToolCall, ...]:
    raw_calls = getattr(response, "tool_calls", None)
    if raw_calls is None and isinstance(response, Mapping):
        raw_calls = response.get("tool_calls")
    if raw_calls is None:
        raw_calls = _response_output_tool_calls(response)
    calls: list[ProactiveAgentToolCall] = []
    if not isinstance(raw_calls, IterableABC) or isinstance(raw_calls, (str, bytes, Mapping)):
        return ()
    for raw_call in raw_calls:
        call = _normalize_proactive_agent_tool_call(raw_call)
        if call is not None:
            calls.append(call)
    return tuple(calls)


def apply_proactive_agent_tool_calls(
    account_store: AccountStore,
    account_id: str,
    tool_calls: Iterable[ProactiveAgentToolCall | Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> ProactiveLLMPlanningResult:
    decisions: list[dict[str, Any]] = []
    errors: list[str] = []
    audit_event_ids: list[str] = []
    resolved_now = now or datetime.now(timezone.utc)
    for index, raw_call in enumerate(list(tool_calls)[:PROACTIVE_LLM_MAX_DECISIONS]):
        call = raw_call if isinstance(raw_call, ProactiveAgentToolCall) else _normalize_proactive_agent_tool_call(raw_call)
        if call is None:
            error = f"tool_{index}_invalid_tool_call"
            errors.append(error)
            audit_event_ids.append(_append_proactive_llm_audit_event(account_store, account_id, event_type="tool_call_rejected", reason=error, decision_index=index, decision=raw_call, now=resolved_now))
            continue
        if call.name not in PROACTIVE_AGENT_TOOL_NAMES:
            error = f"tool_{index}_unsupported_tool:{call.name}"
            errors.append(error)
            audit_event_ids.append(_append_proactive_llm_audit_event(account_store, account_id, event_type="tool_call_rejected", reason=error, decision_index=index, decision=_tool_call_audit_payload(call), now=resolved_now))
            continue
        decisions.append(_tool_call_to_llm_decision(call))
    result = apply_proactive_llm_plan(account_store, account_id, {"schema_version": PROACTIVE_LLM_PLAN_SCHEMA_VERSION, "decisions": decisions}, now=resolved_now)
    if errors:
        return ProactiveLLMPlanningResult(
            account_id,
            result.created_memory_ids,
            result.queued_item_ids,
            tuple([*errors, *result.errors]),
            tuple([*audit_event_ids, *result.audit_event_ids]),
        )
    return result


def build_proactive_llm_planner_prompt(account_store: AccountStore, account_id: str, *, max_memory_chars: int = 6000) -> str:
    selection = account_store.select_structured_memory(
        account_id,
        query_text="proaktive Planung Therapie Ziel Aufgabe Follow-up Risiko Schutzfaktor",
        max_prompt_chars=max_memory_chars,
        max_entry_chars=1200,
    )
    return "\n".join(
        [
            "Du bist nur ein Planungsmodul fuer TeeBotus. Du sendest nie direkt Nachrichten.",
            "Gib ausschliesslich valides JSON zurueck, ohne Markdown, ohne Erklaertext.",
            "Schema:",
            '{"schema_version":1,"decisions":[{"action":"none|memory|queue|cancel|snooze"}]}',
            "Erlaubte memory actions:",
            '{"action":"memory","kind":"reflection|summary|next_step|follow_up|homework|treatment_plan|assessment_note|intervention_note|response_note","text":"...","source_memory_ids":["mem_..."],"importance":1}',
            "Erlaubte queue actions:",
            '{"action":"queue","category":"reminder|task|tip|test|image|analysis|reflection","intent":"...","message_text":"...","reason_memory_ids":["mem_..."],"risk_gate":"none|needs_review|blocked","intervention_type":"...","expected_response":"...","review_signal":"...","file":{"filename":"termin.ics","content_type":"text/calendar","text":"BEGIN:VCALENDAR..."}}',
            "Erlaubte cancel/snooze actions fuer bestehende queued Outbox-Items:",
            '{"action":"cancel","item_id":"pro_...","reason":"..."}',
            '{"action":"snooze","item_id":"pro_...","due_at":"2026-06-16T10:00:00+00:00","reason":"..."}',
            "Regeln:",
            "- Keine Diagnosen behaupten.",
            "- Keine Krisen-, Suizid- oder Selbstverletzungs-Nachrichten proaktiv vorschlagen; dann action none oder risk_gate needs_review.",
            "- Queue-Vorschlaege brauchen reason_memory_ids.",
            "- Cancel/Snooze duerfen nur unten gelistete queued Outbox-IDs betreffen.",
            "- Maximal 5 Entscheidungen.",
            "",
            selection.prompt_text or "Keine nutzbaren Account-Memorys vorhanden.",
            "",
            _proactive_llm_outbox_prompt_text(account_store, account_id),
        ]
    )


def apply_proactive_llm_plan(
    account_store: AccountStore,
    account_id: str,
    payload: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> ProactiveLLMPlanningResult:
    resolved_now = now or datetime.now(timezone.utc)
    if not isinstance(payload, Mapping):
        audit_id = _append_proactive_llm_audit_event(account_store, account_id, event_type="llm_plan_rejected", reason="payload_not_object", payload=payload, now=resolved_now)
        return ProactiveLLMPlanningResult(account_id, errors=("payload_not_object",), audit_event_ids=(audit_id,))
    if int(payload.get("schema_version") or 0) != PROACTIVE_LLM_PLAN_SCHEMA_VERSION:
        audit_id = _append_proactive_llm_audit_event(account_store, account_id, event_type="llm_plan_rejected", reason="unsupported_schema_version", payload=payload, now=resolved_now)
        return ProactiveLLMPlanningResult(account_id, errors=("unsupported_schema_version",), audit_event_ids=(audit_id,))
    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        audit_id = _append_proactive_llm_audit_event(account_store, account_id, event_type="llm_plan_rejected", reason="decisions_not_list", payload=payload, now=resolved_now)
        return ProactiveLLMPlanningResult(account_id, errors=("decisions_not_list",), audit_event_ids=(audit_id,))
    created_memory_ids: list[str] = []
    queued_item_ids: list[str] = []
    errors: list[str] = []
    audit_event_ids: list[str] = []
    memory_ids = _account_memory_ids(account_store, account_id)
    for index, raw_decision in enumerate(decisions[:PROACTIVE_LLM_MAX_DECISIONS]):
        if not isinstance(raw_decision, Mapping):
            error = f"decision_{index}_not_object"
            errors.append(error)
            audit_event_ids.append(_append_proactive_llm_audit_event(account_store, account_id, event_type="llm_decision_rejected", reason=error, decision_index=index, decision=raw_decision, now=resolved_now))
            continue
        action = str(raw_decision.get("action") or "none").strip().casefold()
        if action == "none":
            continue
        if action == "memory":
            memory_result = _apply_proactive_llm_memory_decision(account_store, account_id, raw_decision, memory_ids, resolved_now)
            if memory_result.startswith("error:"):
                error = f"decision_{index}_{memory_result.removeprefix('error:')}"
                errors.append(error)
                audit_event_ids.append(_append_proactive_llm_audit_event(account_store, account_id, event_type="llm_decision_rejected", reason=error, decision_index=index, decision=raw_decision, now=resolved_now))
            else:
                created_memory_ids.append(memory_result)
                memory_ids.add(memory_result)
            continue
        if action == "queue":
            queue_result = _apply_proactive_llm_queue_decision(account_store, account_id, raw_decision, memory_ids, resolved_now)
            if queue_result.startswith("error:"):
                error = f"decision_{index}_{queue_result.removeprefix('error:')}"
                errors.append(error)
                audit_event_ids.append(_append_proactive_llm_audit_event(account_store, account_id, event_type="llm_decision_rejected", reason=error, decision_index=index, decision=raw_decision, now=resolved_now))
            else:
                queued_item_ids.append(queue_result)
            continue
        if action == "cancel":
            cancel_result = _apply_proactive_llm_cancel_decision(account_store, account_id, raw_decision, resolved_now)
            if cancel_result.startswith("error:"):
                error = f"decision_{index}_{cancel_result.removeprefix('error:')}"
                errors.append(error)
                audit_event_ids.append(_append_proactive_llm_audit_event(account_store, account_id, event_type="llm_decision_rejected", reason=error, decision_index=index, decision=raw_decision, now=resolved_now))
            else:
                audit_event_ids.append(_append_proactive_llm_audit_event(account_store, account_id, event_type="llm_decision_applied", reason=cancel_result, decision_index=index, decision=raw_decision, now=resolved_now))
            continue
        if action == "snooze":
            snooze_result = _apply_proactive_llm_snooze_decision(account_store, account_id, raw_decision, resolved_now)
            if snooze_result.startswith("error:"):
                error = f"decision_{index}_{snooze_result.removeprefix('error:')}"
                errors.append(error)
                audit_event_ids.append(_append_proactive_llm_audit_event(account_store, account_id, event_type="llm_decision_rejected", reason=error, decision_index=index, decision=raw_decision, now=resolved_now))
            else:
                audit_event_ids.append(_append_proactive_llm_audit_event(account_store, account_id, event_type="llm_decision_applied", reason=snooze_result, decision_index=index, decision=raw_decision, now=resolved_now))
            continue
        error = f"decision_{index}_unsupported_action:{action}"
        errors.append(error)
        audit_event_ids.append(_append_proactive_llm_audit_event(account_store, account_id, event_type="llm_decision_rejected", reason=error, decision_index=index, decision=raw_decision, now=resolved_now))
    if len(decisions) > PROACTIVE_LLM_MAX_DECISIONS:
        errors.append("too_many_decisions_truncated")
        audit_event_ids.append(_append_proactive_llm_audit_event(account_store, account_id, event_type="llm_plan_truncated", reason="too_many_decisions_truncated", payload={"decision_count": len(decisions)}, now=resolved_now))
    return ProactiveLLMPlanningResult(account_id, tuple(created_memory_ids), tuple(queued_item_ids), tuple(errors), tuple(audit_event_ids))


def proactive_policy_decision(
    account_store: AccountStore,
    account_id: str,
    *,
    category: str,
    now: datetime | None = None,
    exclude_item_id: str = "",
    item: Mapping[str, Any] | None = None,
) -> ProactiveDecision:
    if is_notification_loudness_outbox_item(item):
        route = _item_route(item or {})
        if route.get("chat_type") != "private":
            return ProactiveDecision(False, "invalid_route")
        if not str(route.get("channel") or "").strip() or not str(route.get("chat_id") or "").strip():
            return ProactiveDecision(False, "invalid_route")
        if not _account_has_matching_proactive_route(account_store, account_id, route):
            return ProactiveDecision(False, "stale_route")
        return ProactiveDecision(True, "system_allowed", route)
    state = _normalized_agent_state(account_store.read_agent_state(account_id))
    normalized_category = str(category or "").strip().casefold()
    if normalized_category not in PROACTIVE_ALLOWED_CATEGORIES:
        return ProactiveDecision(False, "category_not_supported")
    if not state["proactive"]["enabled"]:
        return ProactiveDecision(False, "proactive_disabled")
    if state["proactive"].get("paused") is True:
        return ProactiveDecision(False, "proactive_paused")
    if normalized_category not in state["consent"]["categories"]:
        return ProactiveDecision(False, "category_not_consented")
    risk_decision = proactive_risk_policy_decision(account_store, account_id, category=normalized_category, now=now, item=item)
    if not risk_decision.allowed:
        return risk_decision
    resolved_now = now or datetime.now(timezone.utc)
    route = select_proactive_route(account_store, account_id)
    if route is None:
        return ProactiveDecision(False, "no_private_route")
    if isinstance(item, Mapping) and item.get("user_requested_reminder") is True:
        return ProactiveDecision(True, "user_requested_reminder", route)
    hour = resolved_now.astimezone().hour
    start_hour, end_hour = state["policy"]["allowed_hours"]
    if not _hour_in_window(hour, start_hour, end_hour):
        return ProactiveDecision(False, "outside_allowed_hours")
    max_messages_per_day = int(state["policy"]["max_messages_per_day"])
    if max_messages_per_day > 0 and _proactive_daily_count(account_store, account_id, resolved_now, exclude_item_id=exclude_item_id) >= max_messages_per_day:
        return ProactiveDecision(False, "daily_limit_reached")
    min_interval = int(state["policy"].get("min_minutes_between_messages") or 0)
    if min_interval > 0 and _proactive_last_sent_within(account_store, account_id, resolved_now, timedelta(minutes=min_interval), exclude_item_id=exclude_item_id):
        return ProactiveDecision(False, "min_interval_not_elapsed")
    adaptive_decision = contact_timing_decision(account_store, account_id, now=resolved_now, route=route)
    if not adaptive_decision.allowed:
        return ProactiveDecision(False, adaptive_decision.reason)
    return ProactiveDecision(True, "allowed", route)


def due_proactive_outbox_items(account_store: AccountStore, account_id: str, *, now: datetime | None = None) -> tuple[dict[str, Any], ...]:
    resolved_now = now or datetime.now(timezone.utc)
    due: list[dict[str, Any]] = []
    for item in account_store.read_proactive_outbox(account_id):
        if not isinstance(item, dict):
            continue
        if _proactive_item_status(item) != "queued":
            continue
        due_at = _parse_proactive_datetime(str(item.get("due_at") or ""))
        if due_at is not None and due_at > resolved_now:
            continue
        if str(item.get("due_at") or "").strip() and due_at is None:
            continue
        due.append(dict(item))
    return tuple(due)


def _proactive_item_status(item: Mapping[str, Any]) -> str:
    return str(item.get("status") or "queued").strip().casefold()


def fail_invalid_due_proactive_outbox_items(account_store: AccountStore, account_id: str, *, now: datetime | None = None) -> tuple[str, ...]:
    rows = account_store.read_proactive_outbox(account_id)
    failed_ids: list[str] = []
    timestamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    for item in rows:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "queued").strip().casefold() != "queued":
            continue
        due_at = str(item.get("due_at") or "").strip()
        if not due_at or _parse_proactive_datetime(due_at) is not None:
            continue
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        item["status"] = "failed"
        item["updated_at"] = timestamp
        history = item.setdefault("status_history", [])
        if not isinstance(history, list):
            history = []
            item["status_history"] = history
        history.append({"at": timestamp, "status": "failed", "reason": "invalid_due_at"})
        failed_ids.append(item_id)
    if failed_ids:
        account_store.write_proactive_outbox(account_id, rows)
    return tuple(failed_ids)


def expire_stale_proactive_outbox_items(account_store: AccountStore, account_id: str, *, now: datetime | None = None) -> tuple[str, ...]:
    state = _normalized_agent_state(account_store.read_agent_state(account_id))
    expire_after_days = int(state["policy"].get("expire_queued_after_days") or 0)
    if expire_after_days <= 0:
        return ()
    resolved_now = now or datetime.now(timezone.utc)
    cutoff = resolved_now - timedelta(days=expire_after_days)
    rows = account_store.read_proactive_outbox(account_id)
    expired_ids: list[str] = []
    timestamp = resolved_now.isoformat(timespec="seconds")
    for item in rows:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "queued").strip().casefold() != "queued":
            continue
        reference = _parse_proactive_datetime(str(item.get("due_at") or item.get("created_at") or item.get("updated_at") or ""))
        if reference is None or reference > cutoff:
            continue
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        item["status"] = "expired"
        item["updated_at"] = timestamp
        history = item.setdefault("status_history", [])
        if not isinstance(history, list):
            history = []
            item["status_history"] = history
        history.append({"at": timestamp, "status": "expired", "reason": f"queued_item_older_than_{expire_after_days}_days"})
        expired_ids.append(item_id)
    if expired_ids:
        account_store.write_proactive_outbox(account_id, rows)
    return tuple(expired_ids)


def update_proactive_outbox_item_status(
    account_store: AccountStore,
    account_id: str,
    item_id: str,
    *,
    status: str,
    reason: str = "",
    now: datetime | None = None,
    dispatch: Mapping[str, Any] | None = None,
    expected_status: str = "",
) -> bool:
    normalized_status = str(status or "").strip().casefold()
    if normalized_status not in PROACTIVE_OUTBOX_STATUSES:
        raise ValueError(f"unsupported proactive outbox status: {status}")
    expected = str(expected_status or "").strip().casefold()
    if expected and expected not in PROACTIVE_OUTBOX_STATUSES:
        raise ValueError(f"unsupported proactive outbox expected status: {expected_status}")
    rows = account_store.read_proactive_outbox(account_id)
    changed = False
    timestamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    for item in rows:
        if not isinstance(item, dict) or str(item.get("id") or "") != str(item_id or ""):
            continue
        current_status = str(item.get("status") or "queued").strip().casefold()
        if expected and current_status != expected:
            return False
        item["status"] = normalized_status
        item["updated_at"] = timestamp
        if normalized_status == "sent":
            item["sent_at"] = timestamp
            item["last_sent_at"] = timestamp
        if dispatch:
            item["dispatch"] = {str(key): value for key, value in dispatch.items()}
        history = item.setdefault("status_history", [])
        if not isinstance(history, list):
            history = []
            item["status_history"] = history
        history.append({"at": timestamp, "status": normalized_status, "reason": str(reason or "").strip()})
        if normalized_status == "sent":
            next_due_at = _next_recurrence_due_at(item, timestamp)
            if next_due_at:
                item["status"] = "queued"
                item["due_at"] = next_due_at
                item["updated_at"] = timestamp
                count = _normalize_int(item.get("recurrence_count"), default=0) + 1
                item["recurrence_count"] = count
                history.append({"at": timestamp, "status": "queued", "reason": f"recurrence:{item.get('recurrence')}"})
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
    expire_stale_proactive_outbox_items(account_store, account_id, now=resolved_now)
    invalid_due_item_ids = fail_invalid_due_proactive_outbox_items(account_store, account_id, now=resolved_now)
    results: list[ProactiveDispatchResult] = []
    for item_id in invalid_due_item_ids:
        results.append(ProactiveDispatchResult(account_id, item_id, "failed", "invalid_due_at"))
    for item in due_proactive_outbox_items(account_store, account_id, now=resolved_now):
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            results.append(ProactiveDispatchResult(account_id, "", "failed", "missing_item_id"))
            continue
        current_item = _current_due_proactive_outbox_item(account_store, account_id, item_id, now=resolved_now)
        if current_item is None:
            results.append(ProactiveDispatchResult(account_id, item_id, "skipped", "stale_outbox_item", _item_channel(item)))
            continue
        item = current_item
        category = str(item.get("category") or "").strip().casefold()
        decision = proactive_policy_decision(account_store, account_id, category=category, now=resolved_now, exclude_item_id=item_id, item=item)
        if not decision.allowed:
            update_proactive_outbox_item_status(
                account_store,
                account_id,
                item_id,
                status="skipped",
                reason=f"policy:{decision.reason}",
                now=resolved_now,
                expected_status="queued",
            )
            _append_proactive_safety_audit_event(
                account_store,
                account_id,
                item=item,
                reason=decision.reason,
                now=resolved_now,
            )
            results.append(ProactiveDispatchResult(account_id, item_id, "skipped", decision.reason, _item_channel(item)))
            continue
        route = decision.route or _item_route(item)
        channel = str(route.get("channel") or "").strip().casefold()
        chat_id = str(route.get("chat_id") or "").strip()
        if route.get("chat_type") != "private" or not channel or not chat_id:
            update_proactive_outbox_item_status(account_store, account_id, item_id, status="skipped", reason="invalid_route", now=resolved_now, expected_status="queued")
            results.append(ProactiveDispatchResult(account_id, item_id, "skipped", "invalid_route", channel))
            continue
        sender = senders.get(channel)
        if sender is None:
            update_proactive_outbox_item_status(
                account_store,
                account_id,
                item_id,
                status="failed",
                reason=f"missing_sender:{channel}",
                now=resolved_now,
                expected_status="queued",
            )
            results.append(ProactiveDispatchResult(account_id, item_id, "failed", "missing_sender", channel))
            continue
        message_text = str(item.get("message_text") or "").strip()
        if not message_text:
            update_proactive_outbox_item_status(account_store, account_id, item_id, status="failed", reason="missing_message_text", now=resolved_now, expected_status="queued")
            results.append(ProactiveDispatchResult(account_id, item_id, "failed", "missing_message_text", channel))
            continue
        action = _proactive_item_action(chat_id, message_text, item)
        if action is None:
            update_proactive_outbox_item_status(account_store, account_id, item_id, status="failed", reason="invalid_file", now=resolved_now, expected_status="queued")
            results.append(ProactiveDispatchResult(account_id, item_id, "failed", "invalid_file", channel))
            continue
        try:
            sent_ref = await _maybe_await(sender(route, action, item))
        except Exception as exc:  # pragma: no cover - exact adapter exception types are channel specific
            update_proactive_outbox_item_status(
                account_store,
                account_id,
                item_id,
                status="failed",
                reason=f"send_error:{type(exc).__name__}",
                now=resolved_now,
                expected_status="queued",
            )
            results.append(ProactiveDispatchResult(account_id, item_id, "failed", f"send_error:{type(exc).__name__}", channel))
            continue
        message_ref = _normalize_sent_ref(sent_ref)
        dispatch_meta = {"channel": channel, "chat_id": chat_id, "message_ref": message_ref}
        if not update_proactive_outbox_item_status(
            account_store,
            account_id,
            item_id,
            status="sent",
            reason="sent",
            now=resolved_now,
            dispatch=dispatch_meta,
            expected_status="queued",
        ):
            results.append(ProactiveDispatchResult(account_id, item_id, "failed", "status_update_failed", channel, message_ref))
            continue
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


def _current_due_proactive_outbox_item(
    account_store: AccountStore,
    account_id: str,
    item_id: str,
    *,
    now: datetime,
) -> dict[str, Any] | None:
    for item in account_store.read_proactive_outbox(account_id):
        if not isinstance(item, dict) or str(item.get("id") or "").strip() != str(item_id or "").strip():
            continue
        if str(item.get("status") or "queued").strip().casefold() != "queued":
            return None
        due_raw = str(item.get("due_at") or "").strip()
        due_at = _parse_proactive_datetime(due_raw)
        if due_raw and due_at is None:
            return None
        if due_at is not None and due_at > now:
            return None
        return dict(item)
    return None


def _proactive_item_action(chat_id: str, message_text: str, item: Mapping[str, Any]) -> OutgoingAction | None:
    file_payload = item.get("file")
    if isinstance(file_payload, Mapping):
        generated_file = normalize_generated_file(file_payload)
        if generated_file is None:
            return None
        return SendAttachment(
            chat_id,
            generated_file.data,
            generated_file.filename,
            generated_file.content_type,
            caption=generated_file.caption or message_text,
            track=True,
        )
    return SendText(chat_id, message_text, track=True)


def _append_proactive_safety_audit_event(
    account_store: AccountStore,
    account_id: str,
    *,
    item: Mapping[str, Any],
    reason: str,
    now: datetime,
) -> str:
    normalized_reason = str(reason or "").strip().casefold()
    if not (
        normalized_reason == "active_risk_signal"
        or normalized_reason.startswith("risk_gate_blocked:")
        or normalized_reason.startswith("risk_gate_needs_review:")
    ):
        return ""
    event_type = "proactive_safety_hold"
    if normalized_reason.startswith("risk_gate_needs_review:"):
        event_type = "proactive_safety_review_hold"
    return account_store.append_proactive_audit_event(
        account_id,
        {
            "event_type": event_type,
            "source": "proactive_dispatch_policy",
            "reason": normalized_reason,
            "created_at": now.isoformat(timespec="seconds"),
            "item": _compact_audit_value(
                {
                    "id": str(item.get("id") or "").strip(),
                    "status": str(item.get("status") or "").strip(),
                    "category": str(item.get("category") or "").strip(),
                    "intent": str(item.get("intent") or "").strip(),
                    "risk_gate": _normalize_risk_gate(item.get("risk_gate")),
                    "reason_memory_ids": item.get("reason_memory_ids") if isinstance(item.get("reason_memory_ids"), list) else [],
                }
            ),
            "safe_standard_hint": (
                "No automatic proactive clinical content was sent. Keep the item held, prefer human review, "
                "and if the user re-engages with acute danger, respond with crisis-safe support and human-help guidance."
            ),
        },
    )


def _proactive_agent_state_shape_errors(state: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    proactive = state.get("proactive")
    if proactive is not None and not isinstance(proactive, Mapping):
        errors.append("agent_state proactive is not an object")
    consent = state.get("consent")
    if consent is not None and not isinstance(consent, Mapping):
        errors.append("agent_state consent is not an object")
    elif isinstance(consent, Mapping):
        categories = consent.get("categories")
        if categories is not None and not isinstance(categories, list):
            errors.append("agent_state consent.categories is not a list")
    policy = state.get("policy")
    if policy is not None and not isinstance(policy, Mapping):
        errors.append("agent_state policy is not an object")
    elif isinstance(policy, Mapping):
        allowed_hours = policy.get("allowed_hours")
        if allowed_hours is not None and (not isinstance(allowed_hours, list) or len(allowed_hours) != 2):
            errors.append("agent_state policy.allowed_hours is not a two-item list")
    return errors


def check_proactive_agent_account(account_store: AccountStore, account_id: str) -> ProactiveAgentHealth:
    errors: list[str] = []
    queued_count = 0
    review_pending_count = 0
    try:
        state = account_store.read_agent_state(account_id)
    except (AccountStoreError, OSError, ValueError) as exc:
        return ProactiveAgentHealth(account_id, False, (f"agent_state read failed: {type(exc).__name__}: {exc}",), 0, 0)
    if state:
        if state.get("schema_version") != 1:
            errors.append("agent_state schema_version is not 1")
        errors.extend(_proactive_agent_state_shape_errors(state))
        normalized_state = _normalized_agent_state(state)
        if normalized_state["proactive"]["enabled"] and not normalized_state["consent"]["categories"]:
            errors.append("proactive enabled without consent categories")
    else:
        normalized_state = _normalized_agent_state({})
    try:
        outbox = account_store.read_proactive_outbox(account_id)
    except (AccountStoreError, OSError, ValueError) as exc:
        return ProactiveAgentHealth(account_id, False, (f"proactive_outbox read failed: {type(exc).__name__}: {exc}",), 0, 0)
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
        if item_id:
            seen_ids.add(item_id)
        status = str(item.get("status") or "queued").strip().casefold()
        if status == "queued":
            queued_count += 1
        elif status == "review_pending":
            review_pending_count += 1
        if status not in PROACTIVE_OUTBOX_STATUSES:
            errors.append(f"outbox item {item_id or index} has unsupported status: {status}")
        errors.extend(_proactive_outbox_status_history_errors(item, item_id or str(index), current_status=status))
        category = str(item.get("category") or "").strip().casefold()
        system_notification_item = is_notification_loudness_outbox_item(item)
        if status in {"queued", "review_pending"} and not system_notification_item and not _proactive_outbox_item_has_provenance(item):
            errors.append(f"{status} outbox item {item_id or index} missing provenance")
        if category not in PROACTIVE_ALLOWED_CATEGORIES and not system_notification_item:
            errors.append(f"outbox item {item_id or index} has unsupported category: {category}")
        if status == "queued" and category and category not in consented_categories and not system_notification_item:
            errors.append(f"queued outbox item {item_id or index} category is not consented: {category}")
        risk_gate = _normalize_risk_gate(item.get("risk_gate"))
        if status == "queued" and risk_gate in PROACTIVE_RISK_BLOCK_GATES | PROACTIVE_RISK_REVIEW_GATES:
            errors.append(f"queued outbox item {item_id or index} risk_gate blocks proactive dispatch: {risk_gate}")
        if status == "review_pending" and risk_gate not in PROACTIVE_RISK_REVIEW_GATES:
            errors.append(f"review_pending outbox item {item_id or index} needs review risk_gate")
        for key in ("intent", "message_text"):
            if not str(item.get(key) or "").strip():
                errors.append(f"outbox item {item_id or index} missing {key}")
        file_payload = item.get("file")
        if file_payload is not None:
            if not isinstance(file_payload, Mapping):
                errors.append(f"outbox item {item_id or index} file is not an object")
            elif normalize_generated_file(file_payload) is None:
                errors.append(f"outbox item {item_id or index} has invalid file")
        due_at = str(item.get("due_at") or "").strip()
        if due_at and _parse_proactive_datetime(due_at) is None:
            errors.append(f"outbox item {item_id or index} has invalid due_at")
        route = item.get("route")
        if status in {"queued", "review_pending"}:
            if not isinstance(route, dict):
                errors.append(f"{status} outbox item {item_id or index} missing route")
            else:
                if route.get("chat_type") != "private":
                    errors.append(f"{status} outbox item {item_id or index} route is not private")
                if not str(route.get("channel") or "").strip():
                    errors.append(f"{status} outbox item {item_id or index} missing route channel")
                if not str(route.get("chat_id") or "").strip():
                    errors.append(f"{status} outbox item {item_id or index} missing route chat_id")
                try:
                    route_matches = _account_has_matching_proactive_route(account_store, account_id, route)
                except (AccountStoreError, OSError, ValueError) as exc:
                    errors.append(f"{status} outbox item {item_id or index} route check failed: {type(exc).__name__}: {exc}")
                else:
                    if not route_matches:
                        errors.append(f"{status} outbox item {item_id or index} route is stale or not linked to account identity")
    return ProactiveAgentHealth(account_id, not errors, tuple(errors), queued_count, review_pending_count)


def _proactive_outbox_item_has_provenance(item: Mapping[str, Any]) -> bool:
    reason_memory_ids = item.get("reason_memory_ids")
    if isinstance(reason_memory_ids, list) and any(str(memory_id or "").strip() for memory_id in reason_memory_ids):
        return True
    planner = item.get("planner")
    if isinstance(planner, Mapping):
        for key in ("source_memory_id", "reflection_memory_id", "fingerprint", "source"):
            if str(planner.get(key) or "").strip():
                return True
        memory_ids = planner.get("memory_ids")
        if isinstance(memory_ids, list) and any(str(memory_id or "").strip() for memory_id in memory_ids):
            return True
    return False


def _proactive_outbox_status_history_errors(item: Mapping[str, Any], item_label: str, *, current_status: str) -> list[str]:
    history = item.get("status_history")
    if history is None:
        return []
    if not isinstance(history, list):
        return [f"outbox item {item_label} status_history is not a list"]
    errors: list[str] = []
    last_status = ""
    for index, entry in enumerate(history):
        if not isinstance(entry, Mapping):
            errors.append(f"outbox item {item_label} status_history[{index}] is not an object")
            continue
        entry_status = str(entry.get("status") or "").strip().casefold()
        if entry_status not in PROACTIVE_OUTBOX_STATUSES:
            errors.append(f"outbox item {item_label} status_history[{index}] has unsupported status: {entry_status}")
        elif entry_status:
            last_status = entry_status
        at = str(entry.get("at") or "").strip()
        if not at:
            errors.append(f"outbox item {item_label} status_history[{index}] missing at")
        elif _parse_proactive_datetime(at) is None:
            errors.append(f"outbox item {item_label} status_history[{index}] has invalid at")
        if not str(entry.get("reason") or "").strip():
            errors.append(f"outbox item {item_label} status_history[{index}] missing reason")
    if history and last_status and current_status in PROACTIVE_OUTBOX_STATUSES and last_status != current_status:
        errors.append(f"outbox item {item_label} status_history last status {last_status} does not match current status {current_status}")
    return errors


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
        if (
            isinstance(entry, dict)
            and str(entry.get("kind") or "").strip().casefold() in PROACTIVE_PLANNER_MEMORY_KINDS
            and not _is_proactive_planner_generated_memory(entry)
        )
    ]
    rows.sort(key=lambda entry: (_parse_proactive_datetime(str(entry.get("updated_at") or entry.get("created_at") or "")) or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    return tuple(rows)


def _is_proactive_planner_generated_memory(entry: Mapping[str, Any]) -> bool:
    if entry.get("proactive_plan_fingerprint"):
        return True
    planner = entry.get("proactive_planner")
    if isinstance(planner, Mapping) and str(planner.get("source") or "").strip().casefold() == "local":
        return True
    relations = entry.get("relations")
    if isinstance(relations, list):
        for relation in relations:
            if not isinstance(relation, Mapping):
                continue
            provenance = relation.get("provenance")
            if isinstance(provenance, Mapping) and provenance.get("job") == "proactive-reflection-planner":
                return True
    bot_text = str(entry.get("bot_text") or "")
    return "Proactive Planner" in bot_text


def _existing_proactive_plan_fingerprints(account_store: AccountStore, account_id: str) -> set[str]:
    fingerprints: set[str] = set()
    for entry in account_store.read_memory_entries(account_id):
        if isinstance(entry, dict):
            fingerprint = str(entry.get("proactive_plan_fingerprint") or "").strip()
            if fingerprint:
                fingerprints.add(fingerprint)
            planner = entry.get("proactive_planner")
            if isinstance(planner, dict):
                fingerprint = str(planner.get("fingerprint") or "").strip()
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


def _append_proactive_planner_memory_entries(
    account_store: AccountStore,
    account_id: str,
    source: Mapping[str, Any],
    *,
    source_id: str,
    fingerprint: str,
    now: datetime,
) -> tuple[str, ...]:
    return tuple(
        account_store.append_structured_memory_entry(account_id, payload)
        for payload in _proactive_planner_memory_payloads(source, source_id=source_id, fingerprint=fingerprint, now=now)
    )


def _proactive_planner_memory_payloads(
    source: Mapping[str, Any],
    *,
    source_id: str,
    fingerprint: str,
    now: datetime,
) -> tuple[dict[str, Any], ...]:
    source_kind = str(source.get("kind") or "memory").strip().casefold() or "memory"
    short = _proactive_source_excerpt(source)
    timestamp = now.isoformat(timespec="seconds")
    relation = {
        "type": "derived_from",
        "target_id": source_id,
        "valid_from": timestamp,
        "provenance": {"job": "proactive-reflection-planner"},
    }
    common = {
        "memory_type": "semantic",
        "importance": 3,
        "related_ids": [source_id],
        "supports": [source_id],
        "relations": [relation],
        "proactive_plan_fingerprint": fingerprint,
        "proactive_planner": {
            "source": "local",
            "fingerprint": fingerprint,
            "source_memory_id": source_id,
            "source_kind": source_kind,
            "created_at": timestamp,
        },
    }
    templates = (
        (
            "reflection",
            f"Proaktive Reflexion zu {source_id}: sanftes Follow-up ist fachlich plausibel, sofern Consent und Policy weiter passen.",
            "Automatisch vom Proactive Planner erzeugt; keine Diagnose und keine direkte Sendefreigabe.",
        ),
        (
            "summary",
            f"Proaktive Kurz-Zusammenfassung aus {source_kind}: {short}",
            "Stabile Arbeitszusammenfassung fuer spaetere, begruendete Follow-ups.",
        ),
        (
            "assessment_note",
            f"Assessment-Hypothese ohne Diagnose: Aus {source_kind} ergibt sich ein moeglicher, niedrigschwelliger Unterstuetzungsbedarf.",
            "Nur als interne Hypothese mit Provenienz speichern; keine klinische Feststellung.",
        ),
        (
            "intervention_note",
            "Geeignete Intervention: kurzer, nicht druckvoller Check-in oder Erinnerung, falls Opt-in, Kategorie und Zeitfenster passen.",
            "Intervention bleibt policy-abhaengig und wird nicht direkt gesendet.",
        ),
        (
            "response_note",
            "Erwartete Response: kurze Rueckmeldung, ob das Vorhaben passt, erledigt wurde oder gerade zu belastend ist.",
            "Diese Note beschreibt erwartbare Auswertung, nicht eine bereits erfolgte User-Antwort.",
        ),
        (
            "next_step",
            f"Naechster Schritt: bei passender Policy behutsam anknuepfen an: {short}",
            "Konkreter interner Schritt fuer den Scheduler/Planner.",
        ),
        (
            "follow_up",
            "Follow-up geplant: spaeter pruefen, ob der User weiter an dem benannten Thema arbeiten moechte.",
            "Follow-up braucht weiter Consent, private Route und Risk-Guard.",
        ),
        (
            "treatment_plan",
            "Behandlungsplan-Hypothese: Zielbezug erhalten, niedrigschwellige Handlung anbieten und spaetere Rueckmeldung auswerten.",
            "Kein Ersatz fuer professionelle Behandlung; nur interne Planstruktur.",
        ),
        (
            "homework",
            "Moegliche Hausaufgabe: eine kleine, freiwillige Handlung oder Reflexion nur anbieten, wenn der User dafuer offen bleibt.",
            "Nicht als verpflichtende Aufgabe formulieren; spaeter auf Belastungssignale achten.",
        ),
    )
    return tuple({**common, "kind": kind, "user_text": user_text, "bot_text": bot_text} for kind, user_text, bot_text in templates)


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


def _proactive_source_excerpt(source: Mapping[str, Any], *, max_chars: int = 140) -> str:
    text = " ".join(str(source.get("user_text") or source.get("bot_text") or "dem gespeicherten Thema").split())
    if len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    return text or "dem gespeicherten Thema"


def _proactive_planner_message(source: Mapping[str, Any]) -> str:
    short = _proactive_source_excerpt(source, max_chars=90)
    if len(short) > 90:
        short = short[:87].rstrip() + "..."
    return f"Kurzer Check-in zu deinem Vorhaben: {short} Magst du kurz sagen, ob du daran weiterarbeiten moechtest?"


def _default_proactive_due_at(now: datetime) -> str:
    due = now + timedelta(days=1)
    due = due.replace(hour=10, minute=0, second=0, microsecond=0)
    return due.isoformat()


def _apply_proactive_llm_memory_decision(
    account_store: AccountStore,
    account_id: str,
    decision: Mapping[str, Any],
    memory_ids: set[str],
    now: datetime,
) -> str:
    kind = str(decision.get("kind") or "").strip().casefold()
    if kind not in PROACTIVE_LLM_MEMORY_KINDS:
        return f"error:unsupported_memory_kind:{kind}"
    text = _safe_llm_text(decision.get("text"), max_chars=1200)
    if not text:
        return "error:missing_memory_text"
    if _text_has_unsafe_clinical_claim(text):
        return "error:unsafe_memory_text"
    source_ids = _valid_memory_ids(decision.get("source_memory_ids"), memory_ids)
    relations = [
        {
            "type": "derived_from",
            "target_id": source_id,
            "valid_from": now.isoformat(timespec="seconds"),
            "provenance": {"job": "proactive-llm-planner"},
        }
        for source_id in source_ids
    ]
    return account_store.append_structured_memory_entry(
        account_id,
        {
            "kind": kind,
            "memory_type": "semantic",
            "user_text": text,
            "bot_text": "Validated LLM planner proposal; stored as internal hypothesis/support note, not a diagnosis.",
            "importance": _bounded_int(decision.get("importance"), default=3, low=1, high=5),
            "related_ids": source_ids,
            "supports": source_ids,
            "relations": relations,
            "proactive_llm_plan": True,
        },
    )


def _apply_proactive_llm_queue_decision(
    account_store: AccountStore,
    account_id: str,
    decision: Mapping[str, Any],
    memory_ids: set[str],
    now: datetime,
) -> str:
    category = str(decision.get("category") or "").strip().casefold()
    if category not in PROACTIVE_ALLOWED_CATEGORIES:
        return f"error:unsupported_category:{category}"
    message_text = _safe_llm_text(decision.get("message_text"), max_chars=800)
    if not message_text:
        return "error:missing_message_text"
    if _text_has_unsafe_clinical_claim(message_text):
        return "error:unsafe_message_text"
    risk_gate = _normalize_risk_gate(decision.get("risk_gate"))
    reason_memory_ids = _valid_memory_ids(decision.get("reason_memory_ids"), memory_ids)
    if not reason_memory_ids:
        return "error:missing_reason_memory_ids"
    planner = {
        "source": "llm",
        "schema_version": PROACTIVE_LLM_PLAN_SCHEMA_VERSION,
        "intervention_type": str(decision.get("intervention_type") or category).strip()[:80],
        "expected_response": str(decision.get("expected_response") or "").strip()[:240],
        "review_signal": str(decision.get("review_signal") or "").strip()[:240],
        "collaboration_marker": str(decision.get("collaboration_marker") or "agent_suggested").strip()[:80],
    }
    result = queue_proactive_message(
        account_store,
        account_id,
        category=category,
        intent=str(decision.get("intent") or "llm_planner").strip()[:80] or "llm_planner",
        message_text=message_text,
        reason_memory_ids=reason_memory_ids,
        due_at=str(decision.get("due_at") or _default_proactive_due_at(now)).strip(),
        now=now,
        risk_gate=risk_gate,
        planner=planner,
        file=decision.get("file") if isinstance(decision.get("file"), Mapping) else None,
    )
    if not result.allowed:
        return f"error:policy:{result.reason}"
    if result.reason.startswith("queued:"):
        return result.reason.removeprefix("queued:")
    if result.reason.startswith("review_pending:"):
        return result.reason.removeprefix("review_pending:")
    return result.reason


def _response_output_tool_calls(response: Any) -> Any:
    output = getattr(response, "output", None)
    if output is None and isinstance(response, Mapping):
        output = response.get("output")
    if not isinstance(output, list):
        return None
    return [item for item in output if _tool_call_name(item)]


def _response_output_text(response: Any) -> str:
    output = getattr(response, "output", None)
    if output is None and isinstance(response, Mapping):
        output = response.get("output")
    if not isinstance(output, list):
        text = getattr(response, "text", None)
        if text is None and isinstance(response, Mapping):
            text = response.get("text")
        return str(text or "").strip()
    parts: list[str] = []
    for item in output:
        content = item.get("content") if isinstance(item, Mapping) else getattr(item, "content", None)
        if not isinstance(content, list):
            continue
        for part in content:
            text = part.get("text") if isinstance(part, Mapping) else getattr(part, "text", None)
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n".join(parts).strip()


def _normalize_proactive_agent_tool_call(raw_call: Any) -> ProactiveAgentToolCall | None:
    if isinstance(raw_call, ProactiveAgentToolCall):
        payload = {"name": raw_call.name, "arguments": dict(raw_call.arguments), "call_id": raw_call.call_id}
    else:
        name = _tool_call_name(raw_call)
        if not name:
            return None
        arguments = _tool_call_arguments(raw_call)
        call_id = ""
        if isinstance(raw_call, Mapping):
            call_id = str(raw_call.get("call_id") or raw_call.get("id") or "").strip()
        else:
            call_id = str(getattr(raw_call, "call_id", None) or getattr(raw_call, "id", "") or "").strip()
        payload = {"name": name, "arguments": dict(arguments), "call_id": call_id}
    try:
        validated = parse_proactive_tool_call_decision(payload)
    except (TypeError, ValueError, ValidationError):
        return None
    return ProactiveAgentToolCall(name=validated.name, arguments=validated.arguments, call_id=validated.call_id)


def _tool_call_name(raw_call: Any) -> str:
    if isinstance(raw_call, Mapping):
        function = raw_call.get("function")
        if isinstance(function, Mapping):
            return str(function.get("name") or "").strip()
        if raw_call.get("type") in {"function_call", "tool_call"}:
            return str(raw_call.get("name") or "").strip()
        return str(raw_call.get("name") or "").strip()
    function = getattr(raw_call, "function", None)
    if function is not None:
        return str(getattr(function, "name", "") or "").strip()
    return str(getattr(raw_call, "name", "") or "").strip()


def _tool_call_arguments(raw_call: Any) -> Mapping[str, Any]:
    raw_arguments: Any
    if isinstance(raw_call, Mapping):
        function = raw_call.get("function")
        if isinstance(function, Mapping) and "arguments" in function:
            raw_arguments = function.get("arguments")
        else:
            raw_arguments = raw_call.get("arguments", {})
    else:
        function = getattr(raw_call, "function", None)
        if function is not None and hasattr(function, "arguments"):
            raw_arguments = getattr(function, "arguments")
        else:
            raw_arguments = getattr(raw_call, "arguments", {})
    if isinstance(raw_arguments, Mapping):
        return raw_arguments
    if isinstance(raw_arguments, str):
        try:
            decoded = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, Mapping) else {}
    return {}


def _tool_call_to_llm_decision(call: ProactiveAgentToolCall) -> dict[str, Any]:
    args = dict(call.arguments)
    if call.name == "proactive_create_memory":
        return {"action": "memory", **args}
    if call.name == "proactive_queue_message":
        return {"action": "queue", **args}
    if call.name == "proactive_cancel_item":
        return {"action": "cancel", **args}
    if call.name == "proactive_snooze_item":
        return {"action": "snooze", **args}
    return {"action": "none", **args}


def _tool_call_audit_payload(call: ProactiveAgentToolCall) -> dict[str, Any]:
    return {"name": call.name, "arguments": dict(call.arguments), "call_id": call.call_id}


def _safe_tool_response_payload(response: Any) -> Any:
    if isinstance(response, Mapping):
        return {str(key): value for key, value in response.items() if str(key) in {"id", "output", "tool_calls", "text"}}
    return {
        "id": str(getattr(response, "id", "") or ""),
        "text": str(getattr(response, "text", "") or "")[:600],
    }


def _apply_proactive_llm_cancel_decision(
    account_store: AccountStore,
    account_id: str,
    decision: Mapping[str, Any],
    now: datetime,
) -> str:
    item_id = str(decision.get("item_id") or "").strip()
    if not item_id:
        return "error:missing_item_id"
    if not _queued_proactive_outbox_item_exists(account_store, account_id, item_id):
        return "error:item_not_queued"
    reason = _safe_llm_text(decision.get("reason"), max_chars=160) or "llm_cancel"
    if not update_proactive_outbox_item_status(
        account_store,
        account_id,
        item_id,
        status="cancelled",
        reason=f"llm_cancel:{reason}",
        now=now,
        expected_status="queued",
    ):
        return "error:item_not_queued"
    return f"cancelled:{item_id}"


def _apply_proactive_llm_snooze_decision(
    account_store: AccountStore,
    account_id: str,
    decision: Mapping[str, Any],
    now: datetime,
) -> str:
    item_id = str(decision.get("item_id") or "").strip()
    if not item_id:
        return "error:missing_item_id"
    if not _queued_proactive_outbox_item_exists(account_store, account_id, item_id):
        return "error:item_not_queued"
    due_at = str(decision.get("due_at") or "").strip()
    parsed_due_at = _parse_proactive_datetime(due_at)
    if parsed_due_at is None:
        return "error:invalid_due_at"
    if parsed_due_at <= now:
        return "error:due_at_not_future"
    reason = _safe_llm_text(decision.get("reason"), max_chars=160) or "llm_snooze"
    if not _update_proactive_outbox_item_due_at(account_store, account_id, item_id, due_at=parsed_due_at.isoformat(timespec="seconds"), reason=f"llm_snooze:{reason}", now=now):
        return "error:item_not_found"
    return f"snoozed:{item_id}"


def _queued_proactive_outbox_item_exists(account_store: AccountStore, account_id: str, item_id: str) -> bool:
    for item in account_store.read_proactive_outbox(account_id):
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "").strip() != item_id:
            continue
        return str(item.get("status") or "queued").strip().casefold() == "queued"
    return False


def _update_proactive_outbox_item_due_at(
    account_store: AccountStore,
    account_id: str,
    item_id: str,
    *,
    due_at: str,
    reason: str,
    now: datetime,
) -> bool:
    rows = account_store.read_proactive_outbox(account_id)
    timestamp = now.isoformat(timespec="seconds")
    changed = False
    for item in rows:
        if not isinstance(item, dict) or str(item.get("id") or "").strip() != item_id:
            continue
        if str(item.get("status") or "queued").strip().casefold() != "queued":
            return False
        item["due_at"] = due_at
        item["updated_at"] = timestamp
        history = item.setdefault("status_history", [])
        if not isinstance(history, list):
            history = []
            item["status_history"] = history
        history.append({"at": timestamp, "status": "queued", "reason": str(reason or "").strip()})
        changed = True
        break
    if changed:
        account_store.write_proactive_outbox(account_id, rows)
    return changed


def _account_memory_ids(account_store: AccountStore, account_id: str) -> set[str]:
    return {
        str(entry.get("id") or "").strip()
        for entry in account_store.read_memory_entries(account_id)
        if isinstance(entry, dict) and str(entry.get("id") or "").strip()
    }


def _proactive_llm_outbox_prompt_text(account_store: AccountStore, account_id: str, *, max_items: int = 12) -> str:
    rows: list[dict[str, Any]] = []
    for item in account_store.read_proactive_outbox(account_id):
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "queued").strip().casefold() != "queued":
            continue
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        rows.append(
            {
                "id": item_id,
                "category": str(item.get("category") or "").strip(),
                "intent": str(item.get("intent") or "").strip()[:120],
                "due_at": str(item.get("due_at") or "").strip(),
                "risk_gate": _normalize_risk_gate(item.get("risk_gate")),
            }
        )
        if len(rows) >= max_items:
            break
    if not rows:
        return "Queued Outbox: keine queued Items fuer Cancel/Snooze."
    return "Queued Outbox fuer Cancel/Snooze:\n" + json.dumps(rows, ensure_ascii=False, indent=2)


def _valid_memory_ids(value: Any, memory_ids: set[str]) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        memory_id = str(item or "").strip()
        if memory_id and memory_id in memory_ids and memory_id not in result:
            result.append(memory_id)
    return result


def _safe_llm_text(value: Any, *, max_chars: int) -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:max_chars].strip()


def _text_has_unsafe_clinical_claim(text: str) -> bool:
    normalized = str(text or "").casefold()
    return any(
        phrase in normalized
        for phrase in (
            "du hast depression",
            "du bist depressiv",
            "diagnose:",
            "ich diagnostiziere",
            "suizid begehen",
            "bring dich um",
        )
    ) or any(pattern.search(normalized) for pattern in PROACTIVE_UNSAFE_TEXT_PATTERNS)


def _bounded_int(value: Any, *, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(high, max(low, parsed))


def _strip_json_code_fence(text: str) -> str:
    stripped = str(text or "").strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _append_proactive_llm_audit_event(
    account_store: AccountStore,
    account_id: str,
    *,
    event_type: str,
    reason: str,
    decision_index: int | None = None,
    decision: Any = None,
    payload: Any = None,
    plan_text: str = "",
    now: datetime | None = None,
) -> str:
    timestamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    event: dict[str, Any] = {
        "event_type": str(event_type or "llm_decision_rejected").strip(),
        "source": "proactive_llm_planner",
        "reason": str(reason or "").strip()[:240],
        "created_at": timestamp,
    }
    if decision_index is not None:
        event["decision_index"] = int(decision_index)
    if decision is not None:
        event["decision"] = _compact_audit_value(decision)
    if payload is not None:
        event["payload"] = _compact_audit_value(payload)
    if plan_text:
        event["plan_text_preview"] = _safe_llm_text(plan_text, max_chars=600)
    return account_store.append_proactive_audit_event(account_id, event)


def _compact_audit_value(value: Any, *, max_string_chars: int = 400, max_items: int = 12) -> Any:
    if isinstance(value, Mapping):
        compact: dict[str, Any] = {}
        for key, item in list(value.items())[:max_items]:
            compact[str(key)[:80]] = _compact_audit_value(item, max_string_chars=max_string_chars, max_items=max_items)
        if len(value) > max_items:
            compact["_truncated_keys"] = len(value) - max_items
        return compact
    if isinstance(value, list):
        compact_list = [_compact_audit_value(item, max_string_chars=max_string_chars, max_items=max_items) for item in value[:max_items]]
        if len(value) > max_items:
            compact_list.append({"_truncated_items": len(value) - max_items})
        return compact_list
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str):
            return _safe_llm_text(value, max_chars=max_string_chars)
        return value
    return _safe_llm_text(repr(value), max_chars=max_string_chars)


def _handle_proactive_category_command(account_store: AccountStore, account_id: str, args: list[str]) -> str:
    state = _normalized_agent_state(account_store.read_agent_state(account_id))
    if not args or args[0].casefold() in {"list", "status", "info"}:
        active = ", ".join(state["consent"]["categories"]) or "keine"
        allowed = ", ".join(sorted(PROACTIVE_ALLOWED_CATEGORIES))
        return f"Kategorien aktiv: {active}\nKategorien moeglich: {allowed}"
    if len(args) < 2:
        return "Nutzung: /proactive category on <name> oder /proactive category off <name>."
    operation = args[0].casefold()
    category = args[1].casefold()
    if category not in PROACTIVE_ALLOWED_CATEGORIES:
        return f"Unbekannte Kategorie: {category}"
    categories = list(state["consent"]["categories"])
    if operation in {"on", "add", "enable", "an", "ein"}:
        if category not in categories:
            categories.append(category)
    elif operation in {"off", "remove", "disable", "aus"}:
        categories = [value for value in categories if value != category]
    else:
        return "Nutzung: /proactive category on <name> oder /proactive category off <name>."
    state = set_proactive_categories(account_store, account_id, categories)
    active = ", ".join(state["consent"]["categories"]) or "keine"
    return f"Kategorien aktualisiert: {active}"


def _handle_proactive_hours_command(account_store: AccountStore, account_id: str, args: list[str]) -> str:
    if len(args) != 2 or not _is_int_text(args[0]) or not _is_int_text(args[1]):
        return "Nutzung: /proactive hours <startstunde> <endstunde>, z.B. /proactive hours 9 20."
    state = set_proactive_allowed_hours(account_store, account_id, args[0], args[1])
    start_hour, end_hour = state["policy"]["allowed_hours"]
    return f"Erlaubtes Zeitfenster aktualisiert: {start_hour}-{end_hour} Uhr."


def _handle_proactive_quiet_command(account_store: AccountStore, account_id: str, args: list[str]) -> str:
    if len(args) != 2 or not _is_int_text(args[0]) or not _is_int_text(args[1]):
        return "Nutzung: /proactive quiet <ruhe-start> <ruhe-ende>, z.B. /proactive quiet 22 8."
    quiet_start = _normalize_hour(args[0], default=22)
    quiet_end = _normalize_hour(args[1], default=8)
    state = set_proactive_allowed_hours(account_store, account_id, quiet_end, quiet_start)
    start_hour, end_hour = state["policy"]["allowed_hours"]
    return f"Ruhezeit aktualisiert: {quiet_start}-{quiet_end} Uhr. Erlaubtes Zeitfenster: {start_hour}-{end_hour} Uhr."


def _handle_proactive_interval_command(account_store: AccountStore, account_id: str, args: list[str]) -> str:
    if len(args) != 1 or not _is_int_text(args[0]):
        return "Nutzung: /proactive interval <minuten>, z.B. /proactive interval 180."
    state = set_proactive_min_interval_minutes(account_store, account_id, args[0])
    return f"Mindestabstand aktualisiert: {state['policy']['min_minutes_between_messages']} Minuten."


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


def _account_has_matching_proactive_route(account_store: AccountStore, account_id: str, route: Mapping[str, Any]) -> bool:
    expected_channel = str(route.get("channel") or "").strip()
    expected_chat_id = str(route.get("chat_id") or "").strip()
    if not expected_channel or not expected_chat_id or route.get("chat_type") != "private":
        return False
    expected_slot = route.get("adapter_slot")
    for identity_key in account_store.list_identities_for_account(account_id):
        current = account_store.get_identity_route(identity_key)
        if not current:
            continue
        if str(current.get("channel") or "").strip() != expected_channel:
            continue
        if str(current.get("chat_id") or "").strip() != expected_chat_id:
            continue
        if current.get("chat_type") != "private":
            continue
        if expected_slot is not None and _normalize_route_slot(current.get("adapter_slot")) != _normalize_route_slot(expected_slot):
            continue
        return True
    return False


def _normalize_route_slot(value: Any) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


def _proactive_daily_count(account_store: AccountStore, account_id: str, now: datetime, *, exclude_item_id: str = "") -> int:
    count = 0
    for item in account_store.read_proactive_outbox(account_id):
        if not isinstance(item, dict):
            continue
        if exclude_item_id and str(item.get("id") or "") == exclude_item_id:
            continue
        status = str(item.get("status") or "queued").strip().casefold()
        if status not in {"queued", "sent"}:
            continue
        timestamp = _parse_proactive_datetime(str(item.get("sent_at") or item.get("due_at") or item.get("created_at") or ""))
        if timestamp is None:
            continue
        if timestamp.astimezone().date() == now.astimezone().date():
            count += 1
    return count


def _proactive_last_sent_within(account_store: AccountStore, account_id: str, now: datetime, interval: timedelta, *, exclude_item_id: str = "") -> bool:
    threshold = now - interval
    for item in account_store.read_proactive_outbox(account_id):
        if not isinstance(item, dict):
            continue
        if exclude_item_id and str(item.get("id") or "") == exclude_item_id:
            continue
        status = str(item.get("status") or "").strip().casefold()
        if status != "sent" and not str(item.get("sent_at") or "").strip():
            continue
        sent_at = _parse_proactive_datetime(str(item.get("sent_at") or item.get("updated_at") or ""))
        if sent_at is not None and threshold <= sent_at <= now:
            return True
    return False


def _normalize_recurrence_rule(value: object) -> str:
    raw = str(value or "").strip().casefold()
    if not raw:
        return ""
    aliases = {
        "daily": "daily",
        "taeglich": "daily",
        "täglich": "daily",
        "jeden tag": "daily",
        "weekly": "weekly",
        "woechentlich": "weekly",
        "wöchentlich": "weekly",
        "jede woche": "weekly",
        "monthly": "monthly",
        "monatlich": "monthly",
        "jeden monat": "monthly",
    }
    if raw in aliases:
        return aliases[raw]
    match = re.fullmatch(
        r"(?:every|alle|jede[nrms]?)\s+(?P<count>\d{1,3})?\s*(?P<unit>minute|minuten|minutes|hour|hours|stunde|stunden|day|days|tag|tage|week|weeks|woche|wochen)",
        raw,
    )
    if not match:
        return ""
    count = int(match.group("count") or 1)
    if count < 1:
        return ""
    unit = match.group("unit")
    if unit.startswith("min"):
        normalized_unit = "minutes"
    elif unit in {"hour", "hours", "stunde", "stunden"}:
        normalized_unit = "hours"
    elif unit in {"day", "days", "tag", "tage"}:
        normalized_unit = "days"
    else:
        normalized_unit = "weeks"
    return f"every {count} {normalized_unit}"


def _next_recurrence_due_at(item: Mapping[str, Any], sent_at: str) -> str:
    recurrence = _normalize_recurrence_rule(item.get("recurrence"))
    if not recurrence:
        return ""
    sent = _parse_proactive_datetime(sent_at)
    if sent is None:
        return ""
    base = _parse_proactive_datetime(str(item.get("due_at") or "")) or sent
    next_due = _advance_recurrence_due_at(base, recurrence)
    for _ in range(366):
        if next_due is None:
            return ""
        if next_due > sent:
            return next_due.isoformat(timespec="seconds")
        next_due = _advance_recurrence_due_at(next_due, recurrence)
    return ""


def _advance_recurrence_due_at(base: datetime, recurrence: str) -> datetime | None:
    if recurrence == "daily":
        return base + timedelta(days=1)
    if recurrence == "weekly":
        return base + timedelta(weeks=1)
    if recurrence == "monthly":
        return _add_month(base)
    match = re.fullmatch(r"every\s+(?P<count>\d{1,3})\s+(?P<unit>minutes|hours|days|weeks)", recurrence)
    if not match:
        return None
    count = int(match.group("count"))
    unit = match.group("unit")
    if unit == "minutes":
        return base + timedelta(minutes=count)
    if unit == "hours":
        return base + timedelta(hours=count)
    if unit == "days":
        return base + timedelta(days=count)
    return base + timedelta(weeks=count)


def _add_month(value: datetime) -> datetime:
    month = value.month + 1
    year = value.year + (month - 1) // 12
    month = ((month - 1) % 12) + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


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
    proactive["enabled"] = bool(proactive.get("enabled"))
    proactive["paused"] = bool(proactive.get("paused", False))
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
    policy["max_messages_per_day"] = max(0, _normalize_int(policy.get("max_messages_per_day"), default=0))
    policy["min_minutes_between_messages"] = min(24 * 60, max(0, _normalize_int(policy.get("min_minutes_between_messages"), default=0)))
    policy["expire_queued_after_days"] = min(365, max(0, _normalize_int(policy.get("expire_queued_after_days"), default=14)))
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


def _is_int_text(value: Any) -> bool:
    try:
        int(str(value).strip())
    except (TypeError, ValueError):
        return False
    return True


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
