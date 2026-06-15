from __future__ import annotations

import json
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
PROACTIVE_TERMINAL_STATUSES = frozenset({"sent", "skipped", "failed", "cancelled", "expired"})
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
PROACTIVE_LLM_PLAN_SCHEMA_VERSION = 1
PROACTIVE_LLM_MAX_DECISIONS = 5
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
    queued = sum(1 for item in outbox if isinstance(item, dict) and item.get("status", "queued") == "queued")
    enabled = "ja" if state["proactive"]["enabled"] else "nein"
    paused = "ja" if state["proactive"]["paused"] else "nein"
    categories = ", ".join(state["consent"]["categories"]) or "keine"
    return "\n".join(
        [
            "Proaktive Unterstützung",
            f"- aktiviert: {enabled}",
            f"- pausiert: {paused}",
            f"- Kategorien: {categories}",
            f"- erlaubtes Zeitfenster: {state['policy']['allowed_hours'][0]}-{state['policy']['allowed_hours'][1]} Uhr",
            f"- Mindestabstand: {state['policy']['min_minutes_between_messages']} Minuten",
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
            '{"action":"queue","category":"reminder|task|tip|test|image|analysis|reflection","intent":"...","message_text":"...","reason_memory_ids":["mem_..."],"risk_gate":"none|needs_review|blocked","intervention_type":"...","expected_response":"...","review_signal":"..."}',
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
    hour = resolved_now.astimezone().hour
    start_hour, end_hour = state["policy"]["allowed_hours"]
    if not _hour_in_window(hour, start_hour, end_hour):
        return ProactiveDecision(False, "outside_allowed_hours")
    if _proactive_daily_count(account_store, account_id, resolved_now, exclude_item_id=exclude_item_id) >= int(state["policy"]["max_messages_per_day"]):
        return ProactiveDecision(False, "daily_limit_reached")
    min_interval = int(state["policy"].get("min_minutes_between_messages") or 0)
    if min_interval > 0 and _proactive_last_sent_within(account_store, account_id, resolved_now, timedelta(minutes=min_interval), exclude_item_id=exclude_item_id):
        return ProactiveDecision(False, "min_interval_not_elapsed")
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
    expire_stale_proactive_outbox_items(account_store, account_id, now=resolved_now)
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
                if not _account_has_matching_proactive_route(account_store, account_id, route):
                    errors.append(f"queued outbox item {item_id or index} route is stale or not linked to account identity")
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
    )
    if not result.allowed:
        return f"error:policy:{result.reason}"
    return result.reason.removeprefix("queued:")


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
    if not update_proactive_outbox_item_status(account_store, account_id, item_id, status="cancelled", reason=f"llm_cancel:{reason}", now=now):
        return "error:item_not_found"
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
    )


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
        status = str(item.get("status") or "queued")
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
        if str(item.get("status") or "").strip().casefold() != "sent":
            continue
        sent_at = _parse_proactive_datetime(str(item.get("sent_at") or item.get("updated_at") or ""))
        if sent_at is not None and threshold <= sent_at <= now:
            return True
    return False


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
    policy["max_messages_per_day"] = max(0, _normalize_int(policy.get("max_messages_per_day"), default=2))
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
