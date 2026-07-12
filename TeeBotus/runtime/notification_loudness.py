from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, utc_now
from TeeBotus.runtime.action_buttons import NOTIFICATION_LOUDNESS_BUTTONS
from TeeBotus.runtime.actions import SendText
from TeeBotus.runtime.activity_profile import contact_timing_decision
from TeeBotus.runtime.events import IncomingEvent
from TeeBotus.runtime.timezone import to_local

NOTIFICATION_LOUDNESS_SYSTEM_ITEM = "notification_loudness"
NOTIFICATION_LOUDNESS_INTENT = "notification_loudness_check"
NOTIFICATION_LOUDNESS_ONLINE_WINDOW = timedelta(minutes=5)
NOTIFICATION_LOUDNESS_WAKE_HOURS = (8, 22)
NOTIFICATION_LOUDNESS_PENDING_STATUS = "pending"
NOTIFICATION_LOUDNESS_TERMINAL_STATUSES = frozenset({"confirmed", "declined"})
NOTIFICATION_LOUDNESS_MUTE_TERMS = frozenset(
    {"stumm", "lautlos", "stummgeschaltet", "lautlosgeschaltet", "mute", "muted", "silence", "silenced", "silent"}
)
NOTIFICATION_LOUDNESS_OFF_TERMS = frozenset({"ausgeschaltet", "deaktiviert", "abgeschaltet", "off", "disabled"})
NOTIFICATION_LOUDNESS_NEGATION_TERMS = frozenset(
    {
        "nicht",
        "nie",
        "kein",
        "keine",
        "keiner",
        "keinem",
        "keinen",
        "keines",
        "keinerlei",
        "nichts",
        "nix",
        "weder",
        "ohne",
        "no",
        "none",
        "not",
        "never",
        "nothing",
        "neither",
        "without",
    }
)
NOTIFICATION_LOUDNESS_QUANTIFIER_TERMS = frozenset(
    {
        "kein",
        "keine",
        "keiner",
        "keinem",
        "keinen",
        "keines",
        "keinerlei",
        "nichts",
        "weder",
        "no",
        "none",
        "nothing",
        "neither",
    }
)
NOTIFICATION_LOUDNESS_NEGATION_PHRASES = (
    "don t",
    "doesn t",
    "didn t",
    "haven t",
    "hasn t",
    "isn t",
    "aren t",
    "wasn t",
    "weren t",
    "couldn t",
    "wouldn t",
    "shouldn t",
    "can t",
)
NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES = frozenset({"aber", "jedoch", "sondern", "und", "oder", "but", "however", "or", "and"})
NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN = "<clause>"
NOTIFICATION_LOUDNESS_UNCERTAINTY_PHRASES = (
    "weiss nicht",
    "keine ahnung",
    "nicht sicher",
    "unsicher",
    "vielleicht",
    "wahrscheinlich",
    "ich glaube",
    "ich denke",
    "kann nicht sagen",
    "i don t know",
    "not sure",
    "uncertain",
    "maybe",
    "probably",
    "i think",
    "i believe",
    "don t think",
    "don t believe",
    "do not know",
    "do not think",
    "do not believe",
    "can t tell",
    "cannot tell",
    "no idea",
    "no clue",
    "not certain",
    "unsure",
    "cannot say",
    "can t say",
)
NOTIFICATION_LOUDNESS_HISTORICAL_PHRASES = (
    "used to",
    "formerly",
    "previously",
    "yesterday",
    "earlier",
    "before",
    "last night",
    "last week",
    "i had ",
    "i was ",
    "i were ",
    "ich hatte ",
    "ich war ",
    "früher",
    "vorher",
    "gestern",
    "damals",
    "war ",
    "waren ",
    "hatte ",
    "had ",
    "was ",
    "were ",
    "no longer",
)
NOTIFICATION_LOUDNESS_NON_ASSERTIVE_STARTS = (
    "if ",
    "when ",
    "assuming ",
    "suppose ",
    "unless ",
    "provided ",
    "in case ",
    "falls ",
    "wenn ",
    "sofern ",
    "angenommen ",
)
NOTIFICATION_LOUDNESS_HABITUAL_MARKERS = (
    "usually",
    "always",
    "normally",
    "generally",
    "typically",
    "regularly",
    "often",
    "sometimes",
    "never",
    "meistens",
    "normalerweise",
    "immer",
    "häufig",
    "oft",
    "manchmal",
    "nie",
    "grundsätzlich",
)
NOTIFICATION_LOUDNESS_NON_DECLARATIVE_STARTS = (
    "stell ",
    "stelle ",
    "mach ",
    "mache ",
    "schalte ",
    "aktiviere ",
    "setze ",
    "stell sicher ",
    "stelle sicher ",
    "bitte stell ",
    "bitte stelle ",
    "bitte mach ",
    "bitte schalte ",
    "i want ",
    "i would like ",
    "i d like ",
    "i don t want ",
    "i don t mute ",
    "i do not mute ",
    "i don t keep ",
    "i do not keep ",
    "i don t leave ",
    "i do not leave ",
    "i don t set ",
    "i do not set ",
    "i don t turn ",
    "i do not turn ",
    "i need ",
    "i make ",
    "i put ",
    "i activate ",
    "i disable ",
    "i deactivate ",
    "i turn ",
    "i switch ",
    "i mute ",
    "i set ",
    "i take ",
    "i remove ",
    "i keep ",
    "i leave ",
    "i let ",
    "i will ",
    "i am going to ",
    "i m going to ",
    "i plan to ",
    "i intend to ",
    "ich will ",
    "ich möchte ",
    "ich moechte ",
    "ich werde ",
    "ich plane ",
    "ich habe vor ",
    "ich schalte ",
    "ich stelle ",
    "ich mache ",
    "ich aktiviere ",
    "ich setze ",
    "ich halte ",
    "ich lasse ",
    "lass ",
    "lasst ",
    "please turn ",
    "please keep ",
    "please set ",
    "please take ",
    "please remove ",
    "please make ",
    "don t mute ",
    "do not mute ",
    "don t keep ",
    "do not keep ",
    "don t leave ",
    "do not leave ",
    "nicht stumm lassen",
    "nicht auf lautlos lassen",
    "nicht ausgeschaltet lassen",
    "nicht aus lassen",
    "bitte nicht stumm",
    "can ",
    "could ",
    "will ",
    "would ",
    "do ",
    "does ",
    "have ",
    "has ",
    "can you ",
    "could you ",
    "kann man ",
    "können ",
    "koennen ",
    "turn ",
    "take ",
    "remove ",
    "set ",
    "keep ",
    "kannst du ",
    "koenntest du ",
    "könntest du ",
    "sag mir ",
    "weisst du ",
    "weißt du ",
)
NOTIFICATION_LOUDNESS_QUESTION_TAILS = (
    "oder",
    "oder nicht",
    "stimmt",
    "richtig",
    "right",
    "correct",
    "isn t it",
    "aren t they",
)
NOTIFICATION_LOUDNESS_STATUS_LEAD_TERMS = frozenset(
    {
        "laut",
        "loud",
        "auf",
        "an",
        "on",
        "aus",
        "off",
        "stumm",
        "lautlos",
        "stummgeschaltet",
        "lautlosgeschaltet",
        "muted",
        "silenced",
        "silent",
        "ausgeschaltet",
        "deaktiviert",
        "abgeschaltet",
        "disabled",
        "nicht",
        "not",
    }
)
NOTIFICATION_LOUDNESS_COMPLETION_PHRASES = (
    "erledigt",
    "gemacht",
    "getan",
    "fertig",
    "done",
    "completed",
    "geschafft",
    "eingeschaltet",
    "angeschaltet",
    "aktiviert",
    "laut gestellt",
    "laut geschaltet",
    "lautgeschaltet",
    "entstummt",
    "turned them on",
    "switched them on",
    "enabled them",
    "unmuted",
)
NOTIFICATION_LOUDNESS_POSITIVE_MUTE_PHRASES = (
    "off mute",
    "off of mute",
    "removed mute",
    "taken off mute",
    "taken off of mute",
)
NOTIFICATION_LOUDNESS_ACTION_WORDS = frozenset({"hab", "habe", "haben", "getan", "gemacht", "erledigt", "did", "done"})
NOTIFICATION_LOUDNESS_AFFIRMATION_WORDS = frozenset({"ja", "yes", "jep", "jo", "ok", "okay", "klar"})
NOTIFICATION_LOUDNESS_NEGATION_REPLY_WORDS = frozenset({"nein", "no", "nee", "nop", "nope"})

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
    if not account_id or not _is_private_chat_type(event.chat_type):
        return None
    try:
        if not _event_belongs_to_account(account_store, event, account_id):
            return None
        if not _event_has_current_private_route(account_store, event):
            return None
        with _account_proactive_outbox_lock(account_store, account_id):
            if not _event_belongs_to_account(account_store, event, account_id):
                return None
            if not _event_has_current_private_route(account_store, event):
                return None
            if not isinstance(account_store.read_agent_state(account_id), dict):
                return None
            route_status = _route_status(account_store, account_id, event)
            if route_status in NOTIFICATION_LOUDNESS_TERMINAL_STATUSES or route_status == "<invalid>":
                return None
            state = account_store.read_agent_state(account_id)
            notification_state = state.get("notification_loudness") if isinstance(state, dict) else None
            routes = notification_state.get("routes") if isinstance(notification_state, dict) else None
            route_state = _find_route_state(routes, _route_key(event)) if isinstance(routes, Mapping) else None
            if isinstance(route_state, Mapping) and not _notification_loudness_checks_active(route_state):
                return None
            decision = _notification_loudness_decision(event.text, pending=route_status == "pending")
            if decision is None:
                return None
            _set_notification_loudness_status(account_store, account_id, event, decision, now=now)
            _cancel_pending_notification_loudness_items(account_store, account_id, event)
            text = NOTIFICATION_LOUDNESS_CONFIRMED_REPLY if decision == "confirmed" else NOTIFICATION_LOUDNESS_DECLINED_REPLY
            return (SendText(event.chat_id, text, track=False),)
    except (AccountStoreError, OSError, ValueError):
        return None


def maybe_notification_loudness_prompt_action(
    event: IncomingEvent,
    account_store: AccountStore,
    account_id: str,
    *,
    now: datetime | None = None,
) -> SendText | None:
    if not _is_private_chat_type(event.chat_type) or not account_id:
        return None
    try:
        if not _event_belongs_to_account(account_store, event, account_id):
            return None
        if not _event_has_current_private_route(account_store, event):
            return None
        with _account_proactive_outbox_lock(account_store, account_id):
            if not _event_belongs_to_account(account_store, event, account_id):
                return None
            if not _event_has_current_private_route(account_store, event):
                return None
            state = account_store.read_agent_state(account_id)
            if not isinstance(state, dict):
                return None
            route_state = _ensure_route_state(state, event)
            normalized_status = _normalized_route_status(route_state)
            if normalized_status in NOTIFICATION_LOUDNESS_TERMINAL_STATUSES or normalized_status == "<invalid>":
                return None
            if not _notification_loudness_checks_active(route_state):
                return None
            resolved_now = _resolve_loudness_now(now)
            if not _notification_loudness_prompt_allowed(route_state, resolved_now, require_online=False):
                account_store.write_agent_state(account_id, state)
                return None
            _mark_notification_loudness_prompted(route_state, event, resolved_now)
            account_store.write_agent_state(account_id, state)
            return SendText(event.chat_id, NOTIFICATION_LOUDNESS_PROMPT, track=False, buttons=NOTIFICATION_LOUDNESS_BUTTONS)
    except (AccountStoreError, OSError, ValueError):
        return None


def queue_due_notification_loudness_prompts(
    account_store: AccountStore,
    account_id: str,
    *,
    now: datetime | None = None,
) -> tuple[str, ...]:
    try:
        with _account_proactive_outbox_lock(account_store, account_id):
            return _queue_due_notification_loudness_prompts_unlocked(account_store, account_id, now=now)
    except (AccountStoreError, OSError, ValueError):
        return ()


def _queue_due_notification_loudness_prompts_unlocked(
    account_store: AccountStore,
    account_id: str,
    *,
    now: datetime | None = None,
) -> tuple[str, ...]:
    state = account_store.read_agent_state(account_id)
    if not isinstance(state, dict):
        return ()
    state.setdefault("schema_version", 1)
    notification_state = state.get("notification_loudness")
    if not isinstance(notification_state, dict):
        return ()
    routes = notification_state.get("routes")
    if not isinstance(routes, dict):
        return ()
    resolved_now = _resolve_loudness_now(now)
    queued_ids: list[str] = []
    state_changed = False
    terminal_route_keys = {
        _normalize_route_key(route_key)
        for route_key, route_state in routes.items()
        if isinstance(route_state, dict) and _normalized_route_status(route_state) in NOTIFICATION_LOUDNESS_TERMINAL_STATUSES
    }
    for route_key, route_state in list(routes.items()):
        if not isinstance(route_state, dict):
            continue
        status = str(route_state.get("status") or "unknown").strip().casefold()
        if status in NOTIFICATION_LOUDNESS_TERMINAL_STATUSES:
            state_changed = _mark_notification_loudness_checks_stopped(route_state, status) or state_changed
            continue
        if _normalize_route_key(route_key) in terminal_route_keys:
            continue
        if status != NOTIFICATION_LOUDNESS_PENDING_STATUS:
            continue
        if not _notification_loudness_checks_active(route_state):
            continue
        route_state_changed, current_route_found = _refresh_route_state_from_account_routes(
            account_store, account_id, str(route_key), route_state
        )
        state_changed = route_state_changed or state_changed
        if not current_route_found:
            continue
        route = route_state.get("route")
        if not _private_route(route):
            continue
        if not _notification_loudness_prompt_allowed(route_state, resolved_now, require_online=True):
            continue
        if isinstance(route, Mapping):
            adaptive_decision = contact_timing_decision(account_store, account_id, now=resolved_now, route=route)
            if not adaptive_decision.allowed:
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
    if str(item.get("system_item") or "").strip().casefold() == NOTIFICATION_LOUDNESS_SYSTEM_ITEM:
        return True
    planner = item.get("planner")
    return isinstance(planner, Mapping) and str(planner.get("system_item") or "").strip().casefold() == NOTIFICATION_LOUDNESS_SYSTEM_ITEM


def notification_loudness_outbox_item_is_active(account_store: AccountStore, account_id: str, item: Mapping[str, Any]) -> bool:
    """Return whether a queued loudness prompt still belongs to an open check."""
    item_status = _notification_loudness_outbox_status(item)
    if item_status not in {"queued", "dispatching"}:
        return False
    if not _outbox_route_is_consistent(item):
        return False
    route_key = _outbox_route_key(item)
    if not route_key:
        return False
    state = account_store.read_agent_state(account_id)
    notification_state = state.get("notification_loudness") if isinstance(state, dict) else None
    routes = notification_state.get("routes") if isinstance(notification_state, dict) else None
    if not isinstance(routes, dict):
        return False
    route_state = _find_route_state(routes, route_key)
    if not isinstance(route_state, dict):
        return False
    if _normalized_route_status(route_state) != NOTIFICATION_LOUDNESS_PENDING_STATUS:
        return False
    if not _notification_loudness_checks_active(route_state):
        return False
    _, current_route_found = _refresh_route_state_from_account_routes(account_store, account_id, route_key, route_state)
    return current_route_found


def _notification_loudness_decision(text: str, *, pending: bool) -> str | None:
    normalized = _normalize_text(text)
    if not normalized:
        return None
    if pending and "?" not in str(text or ""):
        direct_pronoun_decision = _notification_loudness_pending_pronoun_decision(normalized)
        if direct_pronoun_decision is not None:
            return direct_pronoun_decision
    words = set(normalized.split())
    explicit_context_needles = (
        "benachrichtigung",
        "benachrichtigungen",
        "nachricht",
        "nachrichten",
        "notification",
        "notifications",
        "message",
        "messages",
        "push",
        "alert",
        "alerts",
    )
    has_explicit_notification_context = any(
        _contains_normalized_phrase(normalized, needle) for needle in explicit_context_needles
    )
    has_notification_context = has_explicit_notification_context or any(
        _contains_normalized_phrase(normalized, needle)
        for needle in (
            "laut",
            "loud",
            *NOTIFICATION_LOUDNESS_MUTE_TERMS,
            *NOTIFICATION_LOUDNESS_OFF_TERMS,
        )
    )
    polarity_normalized = _normalize_text_for_polarity(text)
    has_unnegated_mute, has_negated_mute = _notification_loudness_mute_polarity(polarity_normalized)
    has_unnegated_off, has_negated_off = _notification_loudness_term_polarity(
        polarity_normalized, NOTIFICATION_LOUDNESS_OFF_TERMS
    )
    has_negated_completion = _notification_loudness_has_negated_phrase(
        polarity_normalized, NOTIFICATION_LOUDNESS_COMPLETION_PHRASES
    )
    has_positive_unmute_phrase = any(
        _contains_normalized_phrase(normalized, phrase) for phrase in NOTIFICATION_LOUDNESS_POSITIVE_MUTE_PHRASES
    )
    if has_notification_context and _notification_loudness_has_uncertainty(normalized):
        return None
    if has_notification_context and _notification_loudness_has_historical_marker(normalized):
        return None
    if has_notification_context and _notification_loudness_has_habitual_marker(normalized):
        return None
    if has_notification_context and normalized.startswith(NOTIFICATION_LOUDNESS_NON_ASSERTIVE_STARTS):
        return None
    if has_notification_context and _notification_loudness_has_question_tail(normalized):
        return None
    if (
        has_notification_context
        and not has_explicit_notification_context
        and _notification_loudness_has_unscoped_subject_status(normalized)
    ):
        return None
    if has_notification_context and _notification_loudness_is_non_declarative(text, normalized):
        return None
    confirmed_needles = (
        "ja laut",
        "laut gestellt",
        "benachrichtigungen an",
        "benachrichtigung an",
        "notifications on",
        "notification on",
        "notifications enabled",
        "notification enabled",
        "nicht aus",
        "not off",
        "ist laut",
        "sind laut",
        "ist auf laut",
        "sind auf laut",
        "steht auf laut",
        "stehen auf laut",
        "are loud",
        "wieder laut",
        "ist an",
        "sind an",
        "are on",
        "are enabled",
        "enabled",
        "are active",
        "sind aktiv",
        "turned on",
        "switched on",
        "unmuted",
        "laut geschaltet",
        "lautgeschaltet",
        "entstummt",
        "eingeschaltet",
        "angeschaltet",
        "aktiviert",
        "erledigt",
        "gemacht",
        "getan",
        "fertig",
        "done",
        "completed",
        "geschafft",
    )
    declined_needles = (
        "ablehnen",
        "abgelehnt",
        "nicht fragen",
        "frag nicht",
        "nicht laut",
        "nicht auf laut",
        "nicht an",
        "not loud",
        "not on",
        "not enabled",
        "aren t loud",
        "isn t loud",
        "aren t on",
        "isn t on",
        "aren t enabled",
        "isn t enabled",
        "noch nicht",
        "nicht erledigt",
        "nicht gemacht",
        "nicht eingeschaltet",
        "nicht aktiviert",
        "did not",
        "didn t",
        "haven t",
        "have not done",
        "haven t done",
        "have not completed",
        "haven t completed",
        "not yet",
        "keine benachrichtigung",
        "keine benachrichtigungen",
        "benachrichtigungen aus",
        "notifications off",
        "notification off",
        "ist aus",
        "sind aus",
        "kann ich nicht",
        "will nicht",
        "moechte nicht",
        "möchte nicht",
        "keine nachfrage",
        "will ich nicht",
        "moechte ich nicht",
        "möchte ich nicht",
    )
    has_negated_confirmed_phrase = _notification_loudness_has_negated_phrase(
        polarity_normalized, confirmed_needles
    )
    has_declined_phrase = any(
        _contains_normalized_phrase(normalized, needle)
        for needle in declined_needles
        if (
            (
                needle not in {
                    "keine benachrichtigung",
                    "keine benachrichtigungen",
                    "did not",
                    "didn t",
                    "haven t",
                }
                or not (has_negated_mute or has_negated_off)
            )
            and not (
                has_positive_unmute_phrase
                and needle in {"notifications off", "notification off", "benachrichtigungen aus"}
            )
        )
    )
    has_declined_phrase = (
        has_declined_phrase
        or (has_unnegated_mute and not has_positive_unmute_phrase)
        or (has_unnegated_off and not has_positive_unmute_phrase)
        or has_negated_completion
        or has_negated_confirmed_phrase
    )
    if has_declined_phrase and (pending or has_notification_context):
        return "declined"
    if pending and (normalized in {"ja", "yes", "jep", "jo", "ok", "okay", "klar", "erledigt", "gemacht"} or words & {"ja", "yes"} and has_notification_context):
        return "confirmed"
    if (
        pending
        and words & NOTIFICATION_LOUDNESS_AFFIRMATION_WORDS
        and words & NOTIFICATION_LOUDNESS_ACTION_WORDS
        and words & NOTIFICATION_LOUDNESS_NEGATION_TERMS
        and not has_notification_context
    ):
        return "declined"
    if pending and words & NOTIFICATION_LOUDNESS_AFFIRMATION_WORDS and words & NOTIFICATION_LOUDNESS_ACTION_WORDS:
        return "confirmed"
    if pending and words & NOTIFICATION_LOUDNESS_AFFIRMATION_WORDS and has_notification_context:
        return "confirmed"
    if (
        pending
        and words & NOTIFICATION_LOUDNESS_NEGATION_REPLY_WORDS
        and words & NOTIFICATION_LOUDNESS_ACTION_WORDS
        and not (has_negated_mute or has_negated_off)
    ):
        if any(_contains_normalized_phrase(normalized, phrase) for phrase in NOTIFICATION_LOUDNESS_COMPLETION_PHRASES) and not has_negated_completion:
            return "confirmed"
        return "declined"
    if pending and any(_contains_normalized_phrase(normalized, needle) for needle in NOTIFICATION_LOUDNESS_COMPLETION_PHRASES):
        return "confirmed"
    if pending and normalized in {"nein", "no", "nee", "nop", "nope"}:
        return "declined"
    if has_notification_context and (
        (
            any(_contains_normalized_phrase(normalized, needle) for needle in confirmed_needles)
            and not has_negated_confirmed_phrase
        )
        or has_negated_mute
        or has_negated_off
        or has_positive_unmute_phrase
    ):
        return "confirmed"
    if has_notification_context and has_declined_phrase:
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
    timestamp = _resolve_loudness_now(now).isoformat(timespec="seconds")
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
    notification_state = state.get("notification_loudness") if isinstance(state, dict) else None
    if not isinstance(notification_state, dict):
        return "unknown"
    routes = notification_state.get("routes")
    if not isinstance(routes, dict):
        return "unknown"
    route_state = _find_route_state(routes, _route_key(event))
    if not isinstance(route_state, dict):
        return "unknown"
    return _normalized_route_status(route_state)


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
    route_state = _find_route_state(routes, route_key)
    if route_state is None:
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


def _cancel_pending_notification_loudness_items(account_store: AccountStore, account_id: str, event: IncomingEvent) -> None:
    route_key = _route_key(event)
    with _account_proactive_outbox_lock(account_store, account_id):
        rows = account_store.read_proactive_outbox(account_id)
        changed = False
        timestamp = utc_now()
        for item in rows:
            if not isinstance(item, dict) or not is_notification_loudness_outbox_item(item):
                continue
            if _outbox_route_key(item) != _normalize_route_key(route_key):
                continue
            if _notification_loudness_outbox_status(item) not in {"queued", "dispatching"}:
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
        if _outbox_route_key(item) != _normalize_route_key(route_key):
            continue
        if _notification_loudness_outbox_status(item) in {"queued", "dispatching"}:
            return True
    return False


def _account_proactive_outbox_lock(account_store: AccountStore, account_id: str):
    lock = getattr(account_store, "proactive_outbox_lock", None)
    if callable(lock):
        return lock(account_id)
    return nullcontext()


def _notification_loudness_outbox_status(item: Mapping[str, Any]) -> str | None:
    if "status" not in item:
        return "queued"
    value = item.get("status")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().casefold()


def _mark_notification_loudness_checks_stopped(route_state: dict[str, Any], reason: str) -> bool:
    stopped_at = route_state.get("checks_stopped_at")
    if (
        route_state.get("checks_active") is False
        and route_state.get("checks_stop_reason") == reason
        and isinstance(stopped_at, str)
        and _parse_datetime(stopped_at) is not None
    ):
        return False
    route_state["checks_active"] = False
    route_state["checks_stopped_at"] = utc_now()
    route_state["checks_stop_reason"] = reason
    return True


def _event_route(event: IncomingEvent) -> dict[str, Any]:
    return {
        "channel": _normalize_channel(event.channel),
        "chat_id": event.chat_id,
        "chat_type": _normalize_chat_type(event.chat_type),
        "adapter_slot": event.adapter_slot,
    }


def _route_key(event: IncomingEvent) -> str:
    return _route_key_for_channel_chat(event.channel, event.adapter_slot, event.chat_id)


def _private_route(route: Any) -> bool:
    return (
        isinstance(route, Mapping)
        and _is_private_chat_type(route.get("chat_type"))
        and bool(str(route.get("channel") or "").strip())
        and bool(str(route.get("chat_id") or "").strip())
        and _route_slot(route.get("adapter_slot")) is not None
    )


def _event_has_current_private_route(account_store: AccountStore, event: IncomingEvent) -> bool:
    route = account_store.get_identity_route(event.identity_key)
    if not _private_route(route):
        return False
    if not _is_private_chat_type(event.chat_type):
        return False
    route_slot = _route_slot(route.get("adapter_slot"))
    event_slot = _route_slot(event.adapter_slot)
    if route_slot is None or event_slot is None:
        return False
    return (
        str(route.get("channel") or "").strip().casefold() == str(event.channel or "").strip().casefold()
        and str(route.get("chat_id") or "").strip() == str(event.chat_id or "").strip()
        and route_slot == event_slot
    )


def _event_belongs_to_account(account_store: AccountStore, event: IncomingEvent, account_id: str) -> bool:
    return account_store.get_account_for_identity(event.identity_key) == account_id


def _route_slot(value: Any) -> int | None:
    if value is None:
        return 1
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        slot = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return 1
        if not text.isdecimal():
            return None
        slot = int(text)
    else:
        return None
    return slot if slot >= 1 else None


def _refresh_route_state_from_account_routes(
    account_store: AccountStore, account_id: str, route_key: str, route_state: dict[str, Any]
) -> tuple[bool, bool]:
    identity_key = str(route_state.get("identity_key") or "").strip()
    try:
        account_identity_keys = [str(identity) for identity in account_store.list_identities_for_account(account_id)]
    except Exception:
        return False, False
    candidate_keys = [identity_key] if identity_key and identity_key in account_identity_keys else []
    candidate_keys.extend(identity for identity in account_identity_keys if identity not in candidate_keys)
    for candidate in candidate_keys:
        route = account_store.get_identity_route(candidate)
        if not _private_route(route):
            continue
        if _route_key_from_route(route) != _normalize_route_key(route_key):
            continue
        changed = route_state.get("identity_key") != candidate or route_state.get("route") != route
        route_state["identity_key"] = candidate
        route_state["route"] = route
        return changed, True
    return False, False


def _find_route_state(routes: Mapping[str, Any], route_key: Any) -> dict[str, Any] | None:
    direct = routes.get(route_key) if isinstance(route_key, str) else None
    normalized_key = _normalize_route_key(route_key)
    fallback: dict[str, Any] | None = direct if isinstance(direct, dict) else None
    for candidate_key, candidate in routes.items():
        if not isinstance(candidate, dict) or _normalize_route_key(candidate_key) != normalized_key:
            continue
        if _normalized_route_status(candidate) in NOTIFICATION_LOUDNESS_TERMINAL_STATUSES:
            return candidate
        if fallback is None:
            fallback = candidate
    return fallback


def _normalized_route_status(route_state: Mapping[str, Any]) -> str:
    if "status" not in route_state:
        return "unknown"
    value = route_state.get("status")
    if not isinstance(value, str) or not value.strip():
        return "<invalid>"
    return value.strip().casefold()


def _notification_loudness_checks_active(route_state: Mapping[str, Any]) -> bool:
    if "checks_active" not in route_state:
        return True
    return _normalize_bool(route_state.get("checks_active"), default=False)


def _normalize_route_key(route_key: Any) -> str:
    parts = str(route_key or "").strip().split(":", 2)
    if len(parts) != 3:
        return str(route_key or "").strip()
    return _route_key_for_channel_chat(parts[0], parts[1], parts[2])


def _route_key_from_route(route: Mapping[str, Any]) -> str:
    return _route_key_for_channel_chat(route.get("channel"), route.get("adapter_slot"), route.get("chat_id"))


def _outbox_route_key(item: Mapping[str, Any]) -> str:
    route_key = _canonical_outbox_route_key(item.get("route_key"))
    if route_key:
        return route_key
    route = item.get("route")
    return _canonical_outbox_route_key(_route_key_from_route(route)) if isinstance(route, Mapping) else ""


def _outbox_route_is_consistent(item: Mapping[str, Any]) -> bool:
    declared_key = _canonical_outbox_route_key(item.get("route_key"))
    route = item.get("route")
    if not isinstance(route, Mapping):
        return True
    if "chat_type" in route and not _is_private_chat_type(route.get("chat_type")):
        return False
    route_key = _canonical_outbox_route_key(_route_key_from_route(route))
    return not declared_key or not route_key or declared_key == route_key


def _canonical_outbox_route_key(route_key: Any) -> str:
    normalized = _normalize_route_key(route_key)
    parts = normalized.split(":", 2)
    if len(parts) != 3 or not parts[0] or not parts[2] or _route_slot(parts[1]) is None:
        return ""
    return normalized


def _route_key_for_channel_chat(channel: Any, adapter_slot: Any, chat_id: Any) -> str:
    normalized_channel = str(channel or "").strip().casefold()
    normalized_chat_id = str(chat_id or "").strip()
    normalized_slot = _route_slot(adapter_slot)
    slot_label = str(normalized_slot) if normalized_slot is not None else "<invalid>"
    return f"{normalized_channel}:{slot_label}:{normalized_chat_id}"


def _notification_loudness_prompt_allowed(route_state: Mapping[str, Any], now: datetime, *, require_online: bool) -> bool:
    if _wake_window_label(now) == "":
        return False
    raw_next_check = route_state.get("next_check_at")
    if raw_next_check not in (None, ""):
        next_check = _parse_datetime(str(raw_next_check))
        if next_check is None or next_check > now:
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
    return to_local(now).date().isoformat()


def _wake_window_label(now: datetime) -> str:
    local = to_local(now)
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
    age = _resolve_loudness_now(now) - last_seen
    return timedelta(0) <= age <= NOTIFICATION_LOUDNESS_ONLINE_WINDOW


def _trim_prompted_window_dates(prompts_by_date: dict[str, Any]) -> None:
    for date_key in sorted(prompts_by_date, key=lambda value: str(value))[:-14]:
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


def _resolve_loudness_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _normalize_text(text: str) -> str:
    return _normalize_text_value(text, preserve_clause_boundaries=False)


def _normalize_text_for_polarity(text: str) -> str:
    return _normalize_text_value(text, preserve_clause_boundaries=True)


def _normalize_text_value(text: str, *, preserve_clause_boundaries: bool) -> str:
    normalized = str(text or "").casefold().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    for char in ",.;:!?":
        replacement = f" {NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN} " if preserve_clause_boundaries else " "
        normalized = normalized.replace(char, replacement)
    for char in "()[]{}\"'’‘":
        normalized = normalized.replace(char, " ")
    return " ".join(normalized.split())


def _contains_normalized_phrase(normalized: str, phrase: str) -> bool:
    phrase_tokens = str(phrase or "").split()
    if not phrase_tokens:
        return False
    tokens = normalized.split()
    width = len(phrase_tokens)
    return any(tokens[index : index + width] == phrase_tokens for index in range(len(tokens) - width + 1))


def _notification_loudness_mute_polarity(normalized: str) -> tuple[bool, bool]:
    return _notification_loudness_term_polarity(normalized, NOTIFICATION_LOUDNESS_MUTE_TERMS)


def _notification_loudness_term_polarity(
    normalized: str, terms: frozenset[str]
) -> tuple[bool, bool]:
    tokens = normalized.split()
    has_unnegated = False
    has_negated = False
    for index, token in enumerate(tokens):
        if token not in terms:
            continue
        preceding_start = max(0, index - 3)
        for boundary_index in range(preceding_start, index):
            if (
                tokens[boundary_index] in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES
                or tokens[boundary_index] == NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
            ):
                preceding_start = boundary_index + 1
        negation_count = _notification_loudness_scoped_negation_count(tokens, preceding_start, index)
        if negation_count % 2:
            has_negated = True
        else:
            has_unnegated = True
    return has_unnegated, has_negated


def _notification_loudness_has_uncertainty(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, _normalize_text(phrase))
        for phrase in NOTIFICATION_LOUDNESS_UNCERTAINTY_PHRASES
    )


def _notification_loudness_has_historical_marker(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, _normalize_text(phrase.strip()))
        for phrase in NOTIFICATION_LOUDNESS_HISTORICAL_PHRASES
    )


def _notification_loudness_has_habitual_marker(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, _normalize_text(phrase))
        for phrase in NOTIFICATION_LOUDNESS_HABITUAL_MARKERS
    )


def _notification_loudness_has_question_tail(normalized: str) -> bool:
    return any(
        normalized == _normalize_text(tail) or normalized.endswith(f" {_normalize_text(tail)}")
        for tail in NOTIFICATION_LOUDNESS_QUESTION_TAILS
    )


def _notification_loudness_pending_pronoun_decision(normalized: str) -> str | None:
    if normalized in {
        "sie sind an",
        "sie sind laut",
        "sie sind nicht aus",
        "sie sind nicht ausgeschaltet",
        "sie sind nicht stumm",
        "sie sind nicht lautlos",
        "they are on",
        "they re on",
        "they are loud",
        "they re loud",
        "they are not off",
        "they re not off",
        "they are not disabled",
        "they re not disabled",
        "they are not muted",
        "they re not muted",
        "they are enabled",
        "they re enabled",
        "they are unmuted",
        "they re unmuted",
    }:
        return "confirmed"
    if normalized in {
        "sie sind aus",
        "sie sind stumm",
        "sie sind lautlos",
        "sie sind nicht laut",
        "sie sind nicht an",
        "sie sind ausgeschaltet",
        "they are off",
        "they re off",
        "they are muted",
        "they re muted",
        "they are not loud",
        "they re not loud",
        "they are disabled",
        "they re disabled",
        "they are not on",
        "they re not on",
    }:
        return "declined"
    return None


def _notification_loudness_has_unscoped_subject_status(normalized: str) -> bool:
    if normalized.startswith(("bin ", "ist ", "sind ", "am ", "is ", "are ")):
        return False
    return any(
        _contains_normalized_phrase(normalized, copula)
        for copula in ("bin", "ist", "sind", "am", "is", "are")
    )


def _notification_loudness_is_non_declarative(text: str, normalized: str) -> bool:
    if "?" in str(text or ""):
        return True
    tokens = normalized.split()
    if tokens and tokens[0] in {"sind", "ist", "are", "is"}:
        return len(tokens) > 1 and tokens[1] not in NOTIFICATION_LOUDNESS_STATUS_LEAD_TERMS
    return normalized.startswith(NOTIFICATION_LOUDNESS_NON_DECLARATIVE_STARTS)


def _notification_loudness_has_negated_phrase(normalized: str, phrases: tuple[str, ...]) -> bool:
    tokens = normalized.split()
    for phrase in phrases:
        phrase_tokens = phrase.split()
        width = len(phrase_tokens)
        for index in range(len(tokens) - width + 1):
            if tokens[index : index + width] != phrase_tokens:
                continue
            preceding_start = max(0, index - 3)
            for boundary_index in range(preceding_start, index):
                if (
                    tokens[boundary_index] in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES
                    or tokens[boundary_index] == NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
                ):
                    preceding_start = boundary_index + 1
            if _notification_loudness_scoped_negation_count(tokens, preceding_start, index) % 2:
                return True
    return False


def _notification_loudness_negation_count(tokens: list[str]) -> int:
    count = sum(value in NOTIFICATION_LOUDNESS_NEGATION_TERMS for value in tokens)
    for phrase in NOTIFICATION_LOUDNESS_NEGATION_PHRASES:
        phrase_tokens = phrase.split()
        width = len(phrase_tokens)
        count += sum(tokens[index : index + width] == phrase_tokens for index in range(len(tokens) - width + 1))
    return count


def _notification_loudness_scoped_negation_count(tokens: list[str], start: int, end: int) -> int:
    count = _notification_loudness_negation_count(tokens[start:end])
    clause_start = 0
    for boundary_index in range(end - 1, -1, -1):
        if (
            tokens[boundary_index] in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES
            or tokens[boundary_index] == NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
        ):
            clause_start = boundary_index + 1
            break
    if clause_start < start:
        count += sum(token in NOTIFICATION_LOUDNESS_QUANTIFIER_TERMS for token in tokens[clause_start:start])
    return count


def _normalize_channel(channel: Any) -> str:
    return str(channel or "").strip().casefold()


def _normalize_chat_type(chat_type: Any) -> str:
    return str(chat_type or "").strip().casefold()


def _is_private_chat_type(chat_type: Any) -> bool:
    return _normalize_chat_type(chat_type) == "private"


def _normalize_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "on", "enabled", "ja", "an"}:
        return True
    if text in {"0", "false", "no", "off", "disabled", "nein", "aus"}:
        return False
    return default
