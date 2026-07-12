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
    {
        "stumm",
        "lautlos",
        "stummgeschaltet",
        "lautlosgeschaltet",
        "stummschaltung",
        "mute",
        "muted",
        "silence",
        "silenced",
        "silent",
        "quiet",
        "inaudible",
        "unhoerbar",
        "hidden",
        "suppressed",
        "unsichtbar",
        "verborgen",
        "unterdrueckt",
    }
)
NOTIFICATION_LOUDNESS_OFF_TERMS = frozenset(
    {"aus", "ausgeschaltet", "deaktiviert", "abgeschaltet", "inaktiv", "inactive", "deactivated", "off", "disabled"}
)
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
        "keineswegs",
        "keinesfalls",
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
NOTIFICATION_LOUDNESS_PARTIAL_QUANTIFIER_PHRASES = (
    "not all",
    "not every",
    "not each",
    "nicht alle",
    "nicht jede",
    "nicht jeder",
    "nicht jedes",
    "some",
    "einige",
    "manche",
    "mehrere",
    "a few",
    "several",
    "ein paar",
    "most",
    "many",
    "almost all",
    "all but",
    "at least",
    "at most",
    "a majority",
    "die meisten",
    "viele",
    "wenige",
    "fast alle",
    "bis auf",
    "mindestens",
    "höchstens",
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
    "glaube ich",
    "ich denke",
    "denke ich",
    "ich vermute",
    "vermute ich",
    "ich schätze",
    "ich nehme an",
    "ich bezweifle",
    "anscheinend",
    "scheinbar",
    "es scheint",
    "soweit ich weiss",
    "weiss es nicht",
    "weiss nicht genau",
    "nicht genau",
    "kann nicht sagen",
    "ich erinnere mich nicht",
    "ich habe vergessen",
    "vergessen",
    "ich kann nicht bestätigen",
    "ich kann nicht verifizieren",
    "ich kann nicht sicher sein",
    "nicht absolut sicher",
    "nicht völlig sicher",
    "nicht ueberzeugt",
    "nicht überzeugt",
    "nicht genug informationen",
    "keine möglichkeit zu wissen",
    "keine möglichkeit zu sagen",
    "i don t know",
    "not sure",
    "uncertain",
    "maybe",
    "probably",
    "perhaps",
    "presumably",
    "i guess",
    "i suppose",
    "i assume",
    "i suspect",
    "i doubt",
    "apparently",
    "it seems",
    "seems like",
    "as far as i know",
    "i am pretty sure",
    "i m pretty sure",
    "i hope",
    "hopefully",
    "i pray",
    "i wish",
    "hoffentlich",
    "ich hoffe",
    "hoffe ich",
    "i think",
    "i believe",
    "don t think",
    "don t believe",
    "do not know",
    "do not think",
    "do not believe",
    "didn t know",
    "did not know",
    "didn t think",
    "did not think",
    "didn t believe",
    "did not believe",
    "wusste nicht",
    "can t tell",
    "cannot tell",
    "no idea",
    "no clue",
    "not certain",
    "someone told me",
    "they told me",
    "someone said",
    "they said",
    "according to someone",
    "reported that",
    "reportedly",
    "allegedly",
    "supposedly",
    "i heard that",
    "heard that",
    "i heard notifications are",
    "i heard notifications were",
    "i heard messages are",
    "i heard messages were",
    "not exactly",
    "unsure",
    "cannot say",
    "can t say",
    "can t remember",
    "cannot remember",
    "don t remember",
    "forgot",
    "can t recall",
    "cannot recall",
    "unclear",
    "not clear",
    "cannot confirm",
    "can t confirm",
    "cannot verify",
    "can t verify",
    "i do not deny that",
    "i don t deny that",
    "i cannot deny that",
    "i can t deny that",
    "ich bestreite nicht dass",
    "ich verneine nicht dass",
    "unable to confirm",
    "unable to verify",
    "unable to tell",
    "unable to know",
    "not able to confirm",
    "not able to verify",
    "not able to tell",
    "don t have enough information",
    "not enough information",
    "no way to know",
    "no way to tell",
    "there is no way to tell",
    "cannot be sure",
    "can t be sure",
    "not absolutely sure",
    "not completely sure",
    "not entirely sure",
    "not fully convinced",
    "not convinced",
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
)
NOTIFICATION_LOUDNESS_CURRENT_TIME_MARKER_PHRASES = (
    "now",
    "right now",
    "just now",
    "currently",
    "at the moment",
    "today",
    "jetzt",
    "nun",
    "aktuell",
    "gerade",
    "derzeit",
    "momentan",
    "heute",
    "neuerdings",
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
    "i need to ",
    "i have to ",
    "i can t ",
    "i couldn t ",
    "i won t ",
    "i can mute ",
    "i can keep ",
    "i can set ",
    "i can turn ",
    "i can switch ",
    "i can make ",
    "i can put ",
    "i can enable ",
    "i can activate ",
    "i can disable ",
    "i can leave ",
    "i have decided to ",
    "i have been meaning to ",
    "i am planning to ",
    "i should ",
    "i would ",
    "i may ",
    "i ought ",
    "i am allowed to ",
    "i am supposed to ",
    "i am expected to ",
    "i am likely to ",
    "i am unlikely to ",
    "i am meant to ",
    "i must ",
    "i could ",
    "i might ",
    "i cannot ",
    "i can not ",
    "i shouldn t ",
    "i wouldn t ",
    "i don t need ",
    "i do not need ",
    "i don t have to ",
    "i do not have to ",
    "i have to check ",
    "i should check ",
    "i am checking ",
    "i am trying ",
    "i m trying ",
    "i am about to ",
    "i m about to ",
    "i am working on ",
    "i m working on ",
    "i am in the process of ",
    "i m in the process of ",
    "i am able to ",
    "i m able to ",
    "i tried to ",
    "i attempted to ",
    "i intended to ",
    "i planned to ",
    "i wanted to ",
    "i hoped to ",
    "i meant to ",
    "i was trying to ",
    "i was planning to ",
    "i was about to ",
    "i am turning ",
    "i m turning ",
    "i am switching ",
    "i m switching ",
    "i am muting ",
    "i m muting ",
    "i am setting ",
    "i m setting ",
    "i am enabling ",
    "i m enabling ",
    "i am activating ",
    "i m activating ",
    "i am disabling ",
    "i m disabling ",
    "i am making ",
    "i m making ",
    "i am putting ",
    "i m putting ",
    "i am taking ",
    "i m taking ",
    "i am removing ",
    "i m removing ",
    "i am keeping ",
    "i m keeping ",
    "i am leaving ",
    "i m leaving ",
    "tell me ",
    "please tell me ",
    "let me know ",
    "i wonder ",
    "what if ",
    "how do i know ",
    "whether ",
    "in theory ",
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
    "i am not going to ",
    "i m not going to ",
    "i plan to ",
    "i am not planning to ",
    "i m not planning to ",
    "i intend to ",
    "i am not intending to ",
    "i m not intending to ",
    "i am not about to ",
    "i m not about to ",
    "i am not trying to ",
    "i m not trying to ",
    "i am not willing to ",
    "i m not willing to ",
    "i refuse to ",
    "i declined to ",
    "i decided not to ",
    "i have decided not to ",
    "i no longer mute ",
    "i no longer keep ",
    "i no longer turn ",
    "i no longer switch ",
    "i no longer set ",
    "i no longer make ",
    "ich will ",
    "ich kann ",
    "ich könnte ",
    "ich koennte ",
    "ich darf ",
    "ich dürfte ",
    "ich duerfte ",
    "ich würde ",
    "ich wuerde ",
    "ich sollte ",
    "ich muss ",
    "ich soll ",
    "ich konnte ",
    "ich habe beschlossen ",
    "ich kann nachrichten laut ",
    "ich kann die nachrichten laut ",
    "ich kann nachrichten stumm ",
    "ich kann die nachrichten stumm ",
    "ich kann nachrichten nicht stumm ",
    "ich kann die nachrichten nicht stumm ",
    "ich möchte ",
    "ich moechte ",
    "ich werde ",
    "ich plane ",
    "ich habe vor ",
    "ich muss prüfen ",
    "ich muss pruefen ",
    "ich prüfe ",
    "ich pruefe ",
    "ich versuche ",
    "ich bin dabei ",
    "ich bin gerade dabei ",
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
NOTIFICATION_LOUDNESS_CURRENT_STATUS_MODIFIERS = frozenset(
    {
        "jetzt",
        "nun",
        "aktuell",
        "gerade",
        "eben",
        "wieder",
        "heute",
        "now",
        "currently",
        "right",
        "today",
        "recently",
        "newly",
        "still",
        "noch",
        "neuerdings",
        "no",
        "longer",
        "anymore",
        "any",
        "mehr",
        "already",
        "bereits",
        "schon",
        "yet",
    }
)
NOTIFICATION_LOUDNESS_NON_ASSERTIVE_OPTIONAL_MODIFIERS = frozenset(
    set(NOTIFICATION_LOUDNESS_CURRENT_STATUS_MODIFIERS) | {"just"}
)
NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS = frozenset(
    {
        "laut",
        "loud",
        "an",
        "on",
        "aktiv",
        "active",
        "enabled",
        "hoerbar",
        "audible",
        "unmuted",
        "visible",
        "sichtbar",
    }
)
NOTIFICATION_LOUDNESS_VOLUME_TERMS = frozenset({"lautstaerke", "volume"})
NOTIFICATION_LOUDNESS_VOLUME_POSITIVE_TERMS = frozenset(
    {"hoch", "high", "voll", "voller", "full", "maximum", "maximal", "up"}
)
NOTIFICATION_LOUDNESS_VOLUME_NEGATIVE_TERMS = frozenset(
    {"niedrig", "low", "leise", "quiet", "minimum", "down", "runter", "herunter"}
)
NOTIFICATION_LOUDNESS_COMPLETION_PHRASES = (
    "erledigt",
    "gemacht",
    "getan",
    "fertig",
    "done",
    "completed",
    "finished",
    "all set",
    "took care of it",
    "take care of it",
    "taken care of",
    "handled it",
    "sorted it",
    "fixed it",
    "wrapped it up",
    "geschafft",
    "abgeschlossen",
    "damit durch",
    "darum gekuemmert",
    "mich darum gekuemmert",
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
    "made loud",
    "made them loud",
    "set to loud",
    "set them to loud",
    "gelungen",
)
NOTIFICATION_LOUDNESS_FAILED_ACTION_PHRASES = (
    "failed to",
    "couldn t manage",
    "could not manage",
    "was unable to",
    "were unable to",
    "never managed to",
    "haven t managed to",
    "hasn t managed to",
    "did not succeed",
    "didn t succeed",
    "tried and failed",
    "but failed",
    "gescheitert",
    "fehlgeschlagen",
    "nicht gelungen",
    "nicht geschafft",
    "konnte nicht",
    "konnten nicht",
    "was not able to",
    "wasn t able to",
    "were not able to",
    "weren t able to",
    "unable to",
    "not able to",
)
NOTIFICATION_LOUDNESS_SUCCESSFUL_ABILITY_PHRASES = (
    "was able to",
    "were able to",
    "have been able to",
    "has been able to",
)
NOTIFICATION_LOUDNESS_EXPLICIT_HISTORICAL_TIME_PHRASES = (
    "used to",
    "formerly",
    "previously",
    "yesterday",
    "earlier",
    "before",
    "last night",
    "last week",
    "früher",
    "vorher",
    "gestern",
    "damals",
)
NOTIFICATION_LOUDNESS_ATTEMPT_ACTION_PHRASES = (
    "tried",
    "attempted",
    "intended",
    "planned",
    "wanted",
    "hoped",
    "meant",
    "versuchte",
    "versucht",
    "wollte",
    "plante",
    "hoffte",
    "meinte",
    "probierte",
    "probiert",
)
NOTIFICATION_LOUDNESS_POSITIVE_MUTE_PHRASES = (
    "off mute",
    "off of mute",
    "removed mute",
    "removed the mute",
    "taken off mute",
    "taken off of mute",
    "taken off the mute",
    "took off mute",
    "took off the mute",
    "turned off mute",
    "turned mute off",
    "anything but muted",
    "anything but silent",
    "alles andere als stumm",
    "alles andere als lautlos",
    "frei von stummschaltung",
    "free of mute",
    "free from mute",
    "free from silence",
    "lautlosmodus ausgeschaltet",
    "lautlosmodus ausgemacht",
    "lautlosmodus fuer nachrichten ausgeschaltet",
    "stummmodus ausgeschaltet",
    "stummmodus ausgemacht",
    "nicht stoeren modus ausgeschaltet",
    "nicht stoeren modus ausgemacht",
)
NOTIFICATION_LOUDNESS_ACTION_WORDS = frozenset({"hab", "habe", "haben", "getan", "gemacht", "erledigt", "did", "done"})
NOTIFICATION_LOUDNESS_AFFIRMATION_WORDS = frozenset({"ja", "yes", "jep", "jo", "ok", "okay", "klar"})
NOTIFICATION_LOUDNESS_NEGATION_REPLY_WORDS = frozenset({"nein", "no", "nee", "nop", "nope"})
NOTIFICATION_LOUDNESS_PENDING_POSITIVE_STATUS_REPLIES = frozenset(
    {"laut", "loud", "an", "on", "nicht stumm", "nicht lautlos", "nicht aus", "not muted", "not off", "not disabled"}
)
NOTIFICATION_LOUDNESS_PENDING_NEGATIVE_STATUS_REPLIES = frozenset(
    {"stumm", "lautlos", "muted", "silent", "aus", "off", "disabled", "nicht laut", "nicht an", "not loud", "not on"}
)

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
    proposition_negation_decision = _notification_loudness_explicit_negated_status_decision(
        normalized, pending=pending
    )
    if proposition_negation_decision is not None:
        return proposition_negation_decision
    reply_prefix = _notification_loudness_leading_reply_prefix(text)
    if reply_prefix is not None:
        prefix_decision, remainder = reply_prefix
        if remainder and _notification_loudness_has_reply_status_context(remainder):
            remainder_decision = _notification_loudness_decision(remainder, pending=pending)
            if remainder_decision is not None:
                if remainder_decision == prefix_decision:
                    return prefix_decision
                return None
    if pending and "?" not in str(text or ""):
        direct_pronoun_decision = None
        if not _notification_loudness_has_uncertainty(normalized):
            candidate_texts = [normalized]
            tokens = normalized.split()
            if tokens and tokens[0] in NOTIFICATION_LOUDNESS_AFFIRMATION_WORDS | NOTIFICATION_LOUDNESS_NEGATION_REPLY_WORDS:
                candidate_texts.append(" ".join(tokens[1:]))
            for candidate in candidate_texts:
                direct_pronoun_decision = _notification_loudness_pending_pronoun_decision(candidate)
                candidate_tokens = candidate.split()
                if direct_pronoun_decision is None and len(candidate_tokens) >= 2 and candidate_tokens[0] in {"sie", "die", "das", "they", "it"}:
                    if candidate_tokens[1] in {"ist", "sind", "is", "are", "re"}:
                        if _notification_loudness_has_positive_current_status(candidate):
                            direct_pronoun_decision = "confirmed"
                        elif _notification_loudness_has_negative_current_status(candidate):
                            direct_pronoun_decision = "declined"
                if direct_pronoun_decision is not None:
                    break
        if direct_pronoun_decision is not None:
            return direct_pronoun_decision
    if pending and normalized in NOTIFICATION_LOUDNESS_PENDING_POSITIVE_STATUS_REPLIES:
        return "confirmed"
    if pending and normalized in NOTIFICATION_LOUDNESS_PENDING_NEGATIVE_STATUS_REPLIES:
        return "declined"
    words = set(normalized.split())
    explicit_context_needles = (
        "benachrichtigung",
        "benachrichtigungen",
        "benachrichtigungston",
        "benachrichtigungsbox",
        "nachricht",
        "nachrichten",
        "nachrichtenton",
        "notification",
        "notifications",
        "message",
        "messages",
        "nachrichtenlautstaerke",
        "benachrichtigungslautstaerke",
        "message volume",
        "notification volume",
        "chat",
        "conversation",
        "thread",
        "push",
        "alert",
        "alerts",
    )
    has_explicit_notification_context = any(
        _contains_normalized_phrase(normalized, needle) for needle in explicit_context_needles
    )
    has_volume_context = any(
        _contains_normalized_phrase(normalized, needle)
        for needle in ("nachrichtenlautstaerke", "benachrichtigungslautstaerke", "message volume", "notification volume")
    ) or (
        has_explicit_notification_context
        and any(_contains_normalized_phrase(normalized, term) for term in NOTIFICATION_LOUDNESS_VOLUME_TERMS)
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
    has_notification_context = has_notification_context or has_volume_context
    polarity_normalized = _normalize_text_for_polarity(text)
    has_explicit_confirmation = _notification_loudness_has_explicit_confirmation(normalized)
    has_sequenced_action_status = _notification_loudness_has_sequenced_action_status(polarity_normalized)
    has_notification_context = has_notification_context or has_explicit_confirmation or has_sequenced_action_status
    if _notification_loudness_has_verification_question(normalized):
        return None
    has_completed_action_positive, has_completed_action_negative = _notification_loudness_completed_action_polarity(
        polarity_normalized, has_notification_context=has_notification_context
    )
    has_unnegated_mute, has_negated_mute = _notification_loudness_mute_polarity(polarity_normalized)
    has_unnegated_german_still, has_negated_german_still = _notification_loudness_german_still_polarity(
        polarity_normalized
    )
    has_unnegated_mute = has_unnegated_mute or has_unnegated_german_still
    has_negated_mute = has_negated_mute or has_negated_german_still
    has_unnegated_off, has_negated_off = _notification_loudness_term_polarity(
        polarity_normalized, NOTIFICATION_LOUDNESS_OFF_TERMS
    )
    has_negated_completion = _notification_loudness_has_negated_phrase(
        polarity_normalized, NOTIFICATION_LOUDNESS_COMPLETION_PHRASES
    )
    has_positive_unmute_phrase = any(
        _contains_normalized_phrase(normalized, phrase) for phrase in NOTIFICATION_LOUDNESS_POSITIVE_MUTE_PHRASES
    )
    has_failed_action = _notification_loudness_has_failed_action(normalized)
    has_successful_ability_action = _notification_loudness_has_successful_ability_action(normalized)
    has_notification_context = has_notification_context or has_positive_unmute_phrase
    if _notification_loudness_has_uncertainty(normalized) and (has_notification_context or pending):
        return None
    if has_notification_context and _notification_loudness_has_partial_quantifier(normalized):
        return None
    temporal_segment = _notification_loudness_current_temporal_segment(
        _normalize_text_for_polarity(text)
    )
    if (
        has_notification_context
        and _notification_loudness_has_historical_marker(normalized)
        and not (
            _notification_loudness_has_recent_completion_marker(normalized)
            or temporal_segment
            or has_failed_action
            or (
                has_successful_ability_action
                and not _notification_loudness_has_explicit_historical_time(normalized)
            )
        )
    ):
        return None
    if temporal_segment:
        normalized = temporal_segment
        polarity_normalized = normalized
        has_unnegated_mute, has_negated_mute = _notification_loudness_mute_polarity(polarity_normalized)
        has_unnegated_german_still, has_negated_german_still = _notification_loudness_german_still_polarity(
            polarity_normalized
        )
        has_unnegated_mute = has_unnegated_mute or has_unnegated_german_still
        has_negated_mute = has_negated_mute or has_negated_german_still
        has_unnegated_off, has_negated_off = _notification_loudness_term_polarity(
            polarity_normalized, NOTIFICATION_LOUDNESS_OFF_TERMS
        )
        has_negated_completion = _notification_loudness_has_negated_phrase(
            polarity_normalized, NOTIFICATION_LOUDNESS_COMPLETION_PHRASES
        )
        has_positive_unmute_phrase = any(
            _contains_normalized_phrase(normalized, phrase) for phrase in NOTIFICATION_LOUDNESS_POSITIVE_MUTE_PHRASES
        )
        has_notification_context = has_notification_context or has_positive_unmute_phrase
        has_completed_action_positive, has_completed_action_negative = _notification_loudness_completed_action_polarity(
            polarity_normalized, has_notification_context=has_notification_context
        )
        has_failed_action = _notification_loudness_has_failed_action(normalized)
    if has_notification_context and _notification_loudness_has_failed_action(normalized):
        failed_action_polarity = _notification_loudness_failed_action_polarity(normalized)
        if failed_action_polarity == "negative":
            return None
        return "declined"
    if has_notification_context and _notification_loudness_has_habitual_marker(normalized) and not (
        has_completed_action_positive or has_completed_action_negative
    ):
        return None
    if has_notification_context and normalized.startswith(NOTIFICATION_LOUDNESS_NON_ASSERTIVE_STARTS):
        return None
    if has_notification_context and _notification_loudness_has_question_tail(normalized):
        return None
    if has_notification_context and "?" in str(text or ""):
        return None
    if has_notification_context and _notification_loudness_has_ambiguous_alternative(normalized):
        return None
    if has_notification_context and _notification_loudness_has_ambiguous_status_qualifier(normalized):
        return None
    if has_notification_context and _notification_loudness_has_ambiguous_location_status(normalized):
        return None
    if has_notification_context and _notification_loudness_has_ambiguous_chat_activity(normalized):
        return None
    if (
        has_notification_context
        and not has_explicit_notification_context
        and _notification_loudness_has_unscoped_subject_status(normalized)
        and not _notification_loudness_has_sequenced_action_status(polarity_normalized)
        and not has_explicit_confirmation
    ):
        return None
    has_audibility_state = _notification_loudness_has_audibility_state(normalized)
    if (
        has_notification_context
        and _notification_loudness_is_non_declarative(text, normalized)
        and not (
            has_audibility_state
            or has_explicit_confirmation
            or _notification_loudness_has_sequenced_action_status(polarity_normalized)
        )
    ):
        return None
    has_volume_positive, has_volume_negative = _notification_loudness_volume_polarity(
        normalized, has_volume_context=has_volume_context
    )
    if has_volume_positive and has_volume_negative:
        return None
    if has_completed_action_positive and has_completed_action_negative:
        return None
    has_positive_current_status = _notification_loudness_has_positive_current_status(normalized)
    has_negative_current_status = _notification_loudness_has_negative_current_status(polarity_normalized)
    has_absolute_negative_positive_status = _notification_loudness_has_absolute_negative_positive_status(normalized)
    has_absolute_negative_mute = _notification_loudness_has_absolute_negative_term(
        normalized, NOTIFICATION_LOUDNESS_MUTE_TERMS
    )
    has_absolute_negative_off = _notification_loudness_has_absolute_negative_term(
        normalized, NOTIFICATION_LOUDNESS_OFF_TERMS
    )
    has_absolute_negative_positive_inner_negation = _notification_loudness_has_absolute_negative_term(
        normalized, NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS, inner_negated=True
    )
    has_absolute_negative_mute_inner_negation = _notification_loudness_has_absolute_negative_term(
        normalized, NOTIFICATION_LOUDNESS_MUTE_TERMS, inner_negated=True
    )
    has_absolute_negative_still = _notification_loudness_has_absolute_negative_german_still(normalized)
    has_absolute_negative_still_inner_negation = _notification_loudness_has_absolute_negative_german_still(
        normalized, inner_negated=True
    )
    has_absolute_negative_off_inner_negation = _notification_loudness_has_absolute_negative_term(
        normalized, NOTIFICATION_LOUDNESS_OFF_TERMS, inner_negated=True
    )
    if has_notification_context and _notification_loudness_has_contradictory_state(
        polarity_normalized
    ) and not _notification_loudness_has_sequenced_action_status(
        polarity_normalized, activation_only=True
    ):
        return None
    if has_notification_context and _notification_loudness_has_cross_subject_conflict(
        polarity_normalized,
        has_unnegated_mute=has_unnegated_mute,
        has_negated_mute=has_negated_mute,
        has_unnegated_off=has_unnegated_off,
        has_negated_off=has_negated_off,
        has_positive_unmute_phrase=has_positive_unmute_phrase,
        has_positive_current_status=has_positive_current_status,
        has_negative_current_status=has_negative_current_status,
    ):
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
        "auf laut",
        "steht auf laut",
        "stehen auf laut",
        "are loud",
        "wieder laut",
        "ist an",
        "sind an",
        "are on",
        "been on",
        "turned on",
        "are enabled",
        "enabled",
        "was able to",
        "were able to",
        "have been able to",
        "has been able to",
        "are active",
        "sind aktiv",
        "turned on",
        "switched on",
        "unmuted",
        "laut geschaltet",
        "lautgeschaltet",
        "entstummt",
        "made loud",
        "made them loud",
        "made messages loud",
        "made notifications loud",
        "set notifications to loud",
        "set them to loud",
        "kann die nachrichten jetzt hoeren",
        "kann die benachrichtigungen jetzt hoeren",
        "man kann die nachrichten jetzt hoeren",
        "man kann die benachrichtigungen jetzt hoeren",
        "can hear notifications now",
        "can hear message notifications now",
        "can hear notifications",
        "can hear messages",
        "can hear message notifications",
        "messages ring now",
        "notifications ring now",
        "die nachrichten klingeln jetzt",
        "die benachrichtigungen klingeln jetzt",
        "notification bell is ringing",
        "message bell is ringing",
        "bell is ringing",
        "nachrichten klingeln",
        "benachrichtigungen klingeln",
        "kann die nachrichten hoeren",
        "kann die benachrichtigungen hoeren",
        "kann nachrichten hoeren",
        "kann benachrichtigungen hoeren",
        "sound from messages",
        "a notification sound",
        "get notification sound",
        "receive message sounds",
        "sound comes from messages",
        "messages make a sound",
        "notifications make a sound",
        "messages produce sound",
        "hear message notifications",
        "hoere den nachrichtenton",
        "einen benachrichtigungston",
        "kommt ein ton",
        "machen einen ton",
        "geben einen ton",
        "mit ton",
        "notifications show up",
        "notifications appear",
        "messages show up",
        "i see message notifications",
        "alerts are showing",
        "notifications are showing",
        "notifications are displayed",
        "benachrichtigungen werden angezeigt",
        "nachrichten erscheinen",
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
        "gelungen",
        "ich kann bestaetigen",
        "ich kann belegen",
        "ich bestaetige",
        "ich habe bestaetigt",
        "bestaetigt",
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
        "kann die nachrichten nicht hoeren",
        "kann die benachrichtigungen nicht hoeren",
        "cannot hear notifications",
        "can not hear notifications",
        "can t hear notifications",
        "cannot hear messages",
        "can not hear messages",
        "can t hear messages",
        "could not hear notifications",
        "couldn t hear notifications",
        "could not hear messages",
        "couldn t hear messages",
        "could not hear message notifications",
        "couldn t hear message notifications",
        "i do not hear notifications",
        "i don t hear notifications",
        "messages do not ring",
        "messages don t ring",
        "notifications do not ring",
        "notifications don t ring",
        "die nachrichten klingeln nicht",
        "die benachrichtigungen klingeln nicht",
        "messages are not audible",
        "notifications are not audible",
        "notification bell is not ringing",
        "message bell is not ringing",
        "bell is not ringing",
        "nachrichten klingeln nicht",
        "benachrichtigungen klingeln nicht",
        "notifications don t show up",
        "notifications do not show up",
        "notifications do not appear",
        "notification does not appear",
        "messages aren t popping up",
        "messages don t pop up",
        "i don t see notifications",
        "i cannot see message notifications",
        "no alerts appear",
        "there are no message alerts",
        "benachrichtigungen erscheinen nicht",
        "nachrichten tauchen nicht auf",
        "keine nachrichtenhinweise",
        "keine benachrichtigungen erscheinen",
        "no sound from messages",
        "no notification sound",
        "isn t any notification sound",
        "no message sounds",
        "no sound comes from messages",
        "messages make no sound",
        "notifications make no sound",
        "messages produce no sound",
        "hear no message notifications",
        "i don t get notification sound",
        "i do not get notification sound",
        "i don t receive message sounds",
        "i do not receive message sounds",
        "keinen nachrichtenton",
        "keinen benachrichtigungston",
        "bekomme keinen nachrichtenton",
        "bekomme keinen benachrichtigungston",
        "kein ton",
        "keinen ton",
        "ohne ton",
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
                    "not yet",
                }
                or not (has_negated_mute or has_negated_off)
            )
            and not (
                has_positive_unmute_phrase
                and needle in {"notifications off", "notification off", "benachrichtigungen aus"}
            )
            and not (
                has_completed_action_positive
                and needle in {"notifications off", "notification off", "benachrichtigungen aus"}
            )
            and not (
                has_negated_off
                and needle in {"notifications off", "notification off", "benachrichtigungen aus"}
            )
        )
    )
    has_declined_phrase = (
        has_declined_phrase
        or (
            has_unnegated_mute
            and not has_positive_unmute_phrase
            and not has_absolute_negative_mute
        )
        or (
            has_unnegated_off
            and not has_positive_unmute_phrase
            and not has_absolute_negative_off
        )
        or has_negated_completion
        or (has_negated_confirmed_phrase and not has_absolute_negative_positive_inner_negation)
        or (has_negative_current_status and not has_absolute_negative_positive_inner_negation)
        or has_absolute_negative_positive_status
        or has_absolute_negative_mute_inner_negation
        or has_absolute_negative_still_inner_negation
        or has_absolute_negative_off_inner_negation
        or has_volume_negative
        or (has_completed_action_negative and not has_explicit_confirmation)
    )
    if has_absolute_negative_positive_inner_negation:
        has_declined_phrase = False
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
        if _notification_loudness_is_non_declarative(
            text, normalized
        ) and not _notification_loudness_has_sequenced_action_status(polarity_normalized):
            return None
        return "confirmed"
    if pending and normalized in {"nein", "no", "nee", "nop", "nope"}:
        return "declined"
    if has_notification_context and (
        (
            any(_contains_normalized_phrase(normalized, needle) for needle in confirmed_needles)
            and not has_negated_confirmed_phrase
        )
        or (has_negated_mute and not has_absolute_negative_mute_inner_negation)
        or (has_negated_off and not has_absolute_negative_off_inner_negation)
        or has_positive_unmute_phrase
        or has_positive_current_status
        or has_absolute_negative_positive_inner_negation
        or has_absolute_negative_mute
        or has_absolute_negative_still
        or has_absolute_negative_off
        or has_volume_positive
        or has_completed_action_positive
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


def _notification_loudness_leading_reply_prefix(text: str) -> tuple[str, str] | None:
    raw = str(text or "").strip().casefold()
    for word in sorted(
        NOTIFICATION_LOUDNESS_AFFIRMATION_WORDS | NOTIFICATION_LOUDNESS_NEGATION_REPLY_WORDS,
        key=len,
        reverse=True,
    ):
        if not raw.startswith(word):
            continue
        remainder = raw[len(word) :]
        if not remainder or remainder[0] not in ",;:!?":
            continue
        decision = "confirmed" if word in NOTIFICATION_LOUDNESS_AFFIRMATION_WORDS else "declined"
        return decision, remainder[1:].strip()
    return None


def _notification_loudness_has_reply_status_context(text: str) -> bool:
    normalized = _normalize_text(text)
    tokens = set(normalized.split())
    return bool(
        tokens
        & (
            {
                "benachrichtigung",
                "benachrichtigungen",
                "nachricht",
                "nachrichten",
                "notification",
                "notifications",
                "message",
                "messages",
                "laut",
                "loud",
                "an",
                "on",
                "aus",
                "off",
            }
            | set(NOTIFICATION_LOUDNESS_MUTE_TERMS)
            | set(NOTIFICATION_LOUDNESS_OFF_TERMS)
        )
    )


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


def _notification_loudness_german_still_polarity(normalized: str) -> tuple[bool, bool]:
    """Treat German ``still`` as quiet without confusing English temporal ``still``."""
    tokens = normalized.split()
    copulas = {"ist", "sind", "war", "waren", "bleibt", "bleiben"}
    has_unnegated = False
    has_negated = False
    for index, token in enumerate(tokens):
        if token != "still":
            continue
        for copula_index in range(max(0, index - 5), index):
            if tokens[copula_index] not in copulas:
                continue
            negation_count = _notification_loudness_scoped_negation_count(
                tokens, copula_index + 1, index
            )
            if negation_count % 2:
                has_negated = True
            else:
                has_unnegated = True
            break
    return has_unnegated, has_negated


def _notification_loudness_term_polarity(
    normalized: str, terms: frozenset[str]
) -> tuple[bool, bool]:
    tokens = normalized.split()
    has_unnegated = False
    has_negated = False
    for index, token in enumerate(tokens):
        if token not in terms:
            continue
        preceding_start = max(0, index - 5)
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


def _notification_loudness_has_failed_action(normalized: str) -> bool:
    if any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in NOTIFICATION_LOUDNESS_FAILED_ACTION_PHRASES
    ):
        return True
    tokens = normalized.split()
    for index, token in enumerate(tokens):
        if token not in {"konnte", "konnten"}:
            continue
        if _notification_loudness_scoped_negation_count(tokens, index + 1, len(tokens)) % 2:
            return True
    return False


def _notification_loudness_failed_action_polarity(normalized: str) -> str | None:
    tokens = normalized.split()
    failure_phrases = tuple(
        _normalize_text(phrase).split() for phrase in NOTIFICATION_LOUDNESS_FAILED_ACTION_PHRASES
    )
    windows: list[list[str]] = []
    for phrase_tokens in failure_phrases:
        width = len(phrase_tokens)
        if not width:
            continue
        for index in range(len(tokens) - width + 1):
            if tokens[index : index + width] != phrase_tokens:
                continue
            windows.append(tokens[max(0, index - 8) : min(len(tokens), index + width + 10)])
    if not windows:
        return None
    positive_targets = (
        "laut",
        "loud",
        "an",
        "on",
        "enabled",
        "enable",
        "aktiv",
        "aktiviert",
        "activate",
        "activated",
        "unmute",
        "unmuted",
        "entstummt",
        "anschalten",
        "anzuschalten",
        "einschalten",
        "einzuschalten",
        "hoch",
        "up",
        "full",
    )
    negative_targets = (
        "stumm",
        "lautlos",
        "muted",
        "mute",
        "silent",
        "silenced",
        "aus",
        "off",
        "disabled",
        "disable",
        "inaktiv",
        "deaktiviert",
        "deactivate",
        "deactivated",
        "ausschalten",
        "auszuschalten",
        "abschalten",
        "abzuschalten",
        "leise",
        "quiet",
        "down",
        "low",
    )
    has_positive_target = any(set(window).intersection(positive_targets) for window in windows)
    has_negative_target = any(set(window).intersection(negative_targets) for window in windows)
    if has_positive_target and not has_negative_target:
        return "positive"
    if has_negative_target and not has_positive_target:
        return "negative"
    return None


def _notification_loudness_explicit_negated_status_decision(
    normalized: str, *, pending: bool
) -> str | None:
    tokens = normalized.split()
    markers = (
        ("not", "the", "case", "that"),
        ("nicht", "der", "fall", "dass"),
        ("not", "true", "that"),
        ("nicht", "wahr", "dass"),
        ("stimmt", "nicht", "dass"),
        ("false", "that"),
        ("falsch", "dass"),
        ("deny", "that"),
        ("denies", "that"),
        ("denied", "that"),
        ("bestreite", "dass"),
        ("bestreitet", "dass"),
        ("bestritt", "dass"),
        ("verneine", "dass"),
        ("verneint", "dass"),
        ("verneinte", "dass"),
        ("not", "true"),
        ("nicht", "wahr"),
    )
    for marker in sorted(markers, key=len, reverse=True):
        width = len(marker)
        for index in range(len(tokens) - width + 1):
            if tuple(tokens[index : index + width]) != marker:
                continue
            preceding = tokens[max(0, index - 3) : index]
            if (
                set(preceding) & {"not", "nicht", "cannot", "t"}
                or {"don", "t"}.issubset(preceding)
                or {"do", "not"}.issubset(preceding)
            ):
                continue
            remainder = " ".join(tokens[index + width :]).strip()
            if not remainder:
                continue
            inner_decision = _notification_loudness_decision(remainder, pending=pending)
            if inner_decision == "confirmed":
                return "declined"
            if inner_decision == "declined":
                return "confirmed"
    return None


def _notification_loudness_has_successful_ability_action(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in NOTIFICATION_LOUDNESS_SUCCESSFUL_ABILITY_PHRASES
    )


def _notification_loudness_has_explicit_historical_time(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in NOTIFICATION_LOUDNESS_EXPLICIT_HISTORICAL_TIME_PHRASES
    )


def _notification_loudness_has_current_temporal_contrast(normalized: str) -> bool:
    return _notification_loudness_current_temporal_segment(normalized) is not None


def _notification_loudness_current_temporal_segment(normalized: str) -> str | None:
    tokens = normalized.split()
    historical_phrases = tuple(
        _normalize_text(phrase.strip()).split()
        for phrase in NOTIFICATION_LOUDNESS_HISTORICAL_PHRASES
    ) + tuple(
        _normalize_text(phrase).split()
        for phrase in NOTIFICATION_LOUDNESS_FAILED_ACTION_PHRASES
    ) + tuple(
        _normalize_text(phrase).split()
        for phrase in NOTIFICATION_LOUDNESS_ATTEMPT_ACTION_PHRASES
    )
    current_phrases = tuple(_normalize_text(phrase).split() for phrase in NOTIFICATION_LOUDNESS_CURRENT_TIME_MARKER_PHRASES)
    historical_ranges: list[tuple[int, int]] = []
    current_starts: list[int] = []
    for phrase in historical_phrases:
        width = len(phrase)
        historical_ranges.extend(
            (index, index + width)
            for index in range(len(tokens) - width + 1)
            if tokens[index : index + width] == phrase
        )
    for phrase in current_phrases:
        width = len(phrase)
        current_starts.extend(
            index
            for index in range(len(tokens) - width + 1)
            if tokens[index : index + width] == phrase
        )
    candidates: list[tuple[int, int]] = []
    for historical_start, historical_end in historical_ranges:
        for current_start in current_starts:
            if current_start < historical_end:
                continue
            between = tokens[historical_end:current_start]
            if not between or any(
                token in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES
                or token == NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
                for token in between
            ):
                boundary_indices = [
                    index
                    for index in range(historical_end, current_start)
                    if tokens[index] in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES
                    or tokens[index] == NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
                ]
                segment_start = (max(boundary_indices) + 1) if boundary_indices else historical_end
                candidates.append((current_start, segment_start))
    if not candidates:
        return None
    _, segment_start = max(candidates)
    segment = [token for token in tokens[segment_start:] if token != NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN]
    return " ".join(segment) or None


def _notification_loudness_has_partial_quantifier(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, _normalize_text(phrase))
        for phrase in NOTIFICATION_LOUDNESS_PARTIAL_QUANTIFIER_PHRASES
    )


def _notification_loudness_has_absolute_negative_positive_status(normalized: str) -> bool:
    return _notification_loudness_has_absolute_negative_term(
        normalized, NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS
    )


def _notification_loudness_has_absolute_negative_term(
    normalized: str, terms: frozenset[str], *, inner_negated: bool = False
) -> bool:
    tokens = normalized.split()
    quantifier_patterns = (
        ("not", "a", "single"),
        ("not", "one"),
        ("nicht", "eine", "einzige"),
        ("nicht", "eine"),
        ("nicht", "ein", "einziger"),
        ("no",),
        ("none",),
        ("neither",),
        ("kein",),
        ("keine",),
        ("keinerlei",),
        ("weder",),
    )
    for pattern in quantifier_patterns:
        width = len(pattern)
        for start in range(len(tokens) - width + 1):
            if tuple(tokens[start : start + width]) != pattern:
                continue
            for index in range(start + width, len(tokens)):
                if tokens[index] in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES:
                    if width == 1 and tokens[index] in {"or", "nor", "oder", "noch"}:
                        continue
                    break
                if tokens[index] not in terms:
                    continue
                between = tokens[start + width : index]
                has_inner_negation = bool({"not", "nicht"}.intersection(between))
                if has_inner_negation is inner_negated:
                    return True
    return False


def _notification_loudness_has_absolute_negative_german_still(
    normalized: str, *, inner_negated: bool = False
) -> bool:
    has_german_still, has_negated_german_still = _notification_loudness_german_still_polarity(normalized)
    if not (has_german_still or has_negated_german_still):
        return False
    return _notification_loudness_has_absolute_negative_term(
        normalized, frozenset({"still"}), inner_negated=inner_negated
    )


def _notification_loudness_has_recent_completion_marker(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in (
            "just now",
            "right now",
            "just turned on",
            "just enabled",
            "recently turned on",
            "recently enabled",
            "newly enabled",
            "just muted",
            "recently muted",
            "just silenced",
            "recently silenced",
            "just disabled",
            "recently disabled",
            "gerade eben",
            "gerade angeschaltet",
            "gerade aktiviert",
            "gerade stummgeschaltet",
            "gerade deaktiviert",
            "soeben",
        )
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


def _notification_loudness_has_positive_current_status(normalized: str) -> bool:
    tokens = normalized.split()
    copulas = {"ist", "sind", "is", "are", "re"}
    subject_terms = {
        "nachricht",
        "nachrichten",
        "message",
        "messages",
        "benachrichtigung",
        "benachrichtigungen",
        "benachrichtigungston",
        "notification",
        "notifications",
        "sie",
        "die",
        "das",
        "they",
        "it",
    }
    for status_index, token in enumerate(tokens):
        if token not in NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS:
            continue
        for copula_index in range(max(0, status_index - 4), status_index):
            if tokens[copula_index] not in copulas:
                continue
            between = tokens[copula_index + 1 : status_index]
            if all(value in NOTIFICATION_LOUDNESS_CURRENT_STATUS_MODIFIERS for value in between):
                return True
            before_copula = tokens[max(0, copula_index - 3) : copula_index]
            if before_copula and all(value in NOTIFICATION_LOUDNESS_CURRENT_STATUS_MODIFIERS for value in before_copula) and any(
                value in subject_terms for value in between
            ):
                return True
    for copula_index, copula in enumerate(tokens):
        if copula not in {"ist", "sind"}:
            continue
        for status_index in range(max(0, copula_index - 4), copula_index):
            if tokens[status_index] not in NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS:
                continue
            before_status = tokens[max(0, status_index - 4) : status_index]
            after_status = tokens[status_index + 1 : copula_index]
            if any(value in NOTIFICATION_LOUDNESS_NEGATION_TERMS for value in before_status):
                continue
            if any(value in subject_terms for value in before_status) and all(
                value in NOTIFICATION_LOUDNESS_CURRENT_STATUS_MODIFIERS for value in after_status
            ):
                return True
    return False


def _notification_loudness_volume_polarity(
    normalized: str, *, has_volume_context: bool
) -> tuple[bool, bool]:
    if not has_volume_context:
        return False, False
    tokens = normalized.split()
    positive = False
    negative = False
    copulas = {"ist", "sind", "is", "are"}
    for index, token in enumerate(tokens):
        if token not in NOTIFICATION_LOUDNESS_VOLUME_POSITIVE_TERMS | NOTIFICATION_LOUDNESS_VOLUME_NEGATIVE_TERMS:
            continue
        if not any(tokens[candidate] in copulas for candidate in range(max(0, index - 5), index)):
            continue
        negated = _notification_loudness_scoped_negation_count(
            tokens, max(0, index - 3), index
        ) % 2 == 1
        is_positive_term = token in NOTIFICATION_LOUDNESS_VOLUME_POSITIVE_TERMS
        if is_positive_term is negated:
            negative = True
        else:
            positive = True
    for phrase in (
        "volle lautstaerke",
        "voller lautstaerke",
        "auf voller lautstaerke",
        "full volume",
        "maximum volume",
        "at full volume",
    ):
        if not _contains_normalized_phrase(normalized, phrase):
            continue
        if _notification_loudness_phrase_is_negated(normalized, phrase):
            negative = True
        else:
            positive = True
    if any(_contains_normalized_phrase(normalized, phrase) for phrase in (
        "leise gestellt",
    )):
        negative = True
    for index, token in enumerate(tokens):
        if token != "turned":
            continue
        following = tokens[index + 1 : index + 6]
        negated = _notification_loudness_scoped_negation_count(
            tokens, max(0, index - 3), index
        ) % 2 == 1
        if "up" in following:
            if negated:
                negative = True
            else:
                positive = True
        if "down" in following:
            if negated:
                positive = True
            else:
                negative = True
    for action, action_is_positive in (
        ("hochgestellt", True),
        ("hochgedreht", True),
        ("hochgesetzt", True),
        ("runtergedreht", False),
        ("heruntergedreht", False),
    ):
        if action not in tokens:
            continue
        index = tokens.index(action)
        negated = _notification_loudness_scoped_negation_count(
            tokens, max(0, index - 3), index
        ) % 2 == 1
        if action_is_positive is negated:
            negative = True
        else:
            positive = True
    if "100" in tokens and any(value in tokens for value in {"prozent", "percent"}):
        positive = True
    if "0" in tokens and any(value in tokens for value in {"prozent", "percent"}):
        negative = True
    return positive, negative


def _notification_loudness_completed_action_polarity(
    normalized: str, *, has_notification_context: bool
) -> tuple[bool, bool]:
    if not has_notification_context:
        return False, False
    tokens = normalized.split()
    actions = {
        "set",
        "put",
        "make",
        "made",
        "turn",
        "turned",
        "switch",
        "switched",
        "enable",
        "enabled",
        "activate",
        "activated",
        "muted",
        "silenced",
        "disabled",
    }
    positive_targets = {
        "laut",
        "loud",
        "an",
        "on",
        "up",
        "hoch",
        "high",
        "full",
        "unmuted",
        "enabled",
        "active",
    }
    negative_targets = {
        "stumm",
        "lautlos",
        "muted",
        "silent",
        "off",
        "down",
        "niedrig",
        "low",
        "leise",
    }
    subjects = {
        "nachricht",
        "nachrichten",
        "message",
        "messages",
        "benachrichtigung",
        "benachrichtigungen",
        "notification",
        "notifications",
        "chat",
        "conversation",
        "thread",
    }
    positive = False
    negative = False
    for auxiliary_index, auxiliary in enumerate(tokens):
        if auxiliary not in {"have", "has"}:
            continue
        for action_index in range(auxiliary_index + 1, min(len(tokens), auxiliary_index + 10)):
            action = tokens[action_index]
            if action in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES:
                break
            if action not in actions:
                continue
            tail_end = min(len(tokens), action_index + 10)
            for boundary_index in range(action_index + 1, tail_end):
                if (
                    tokens[boundary_index] in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES
                    or tokens[boundary_index] == NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
                ):
                    tail_end = boundary_index
                    break
            tail = tokens[action_index + 1 : tail_end]
            has_positive_target = bool(set(tail) & positive_targets)
            has_negative_target = bool(set(tail) & negative_targets)
            if action in {"enabled", "activated"} and set(tail) & subjects:
                has_positive_target = True
            if action in {"muted", "silenced", "disabled"} and set(tail) & subjects:
                has_negative_target = True
            if not has_positive_target and not has_negative_target:
                continue
            negated = _notification_loudness_scoped_negation_count(
                tokens, max(0, action_index - 4), action_index
            ) % 2 == 1
            if has_positive_target:
                if negated:
                    negative = True
                else:
                    positive = True
            if has_negative_target:
                if negated:
                    positive = True
                else:
                    negative = True
    simple_past_actions = {
        "turned",
        "switched",
        "enabled",
        "activated",
        "muted",
        "silenced",
        "disabled",
        "unmuted",
        "made",
        "set",
        "put",
        "stellte",
        "schaltete",
        "machte",
        "setzte",
        "gestellt",
        "geschaltet",
        "gemacht",
        "gesetzt",
        "turn",
        "switch",
        "mute",
        "silence",
        "enable",
        "activate",
        "disable",
    }
    did_actions = {"turn", "switch", "mute", "silence", "enable", "activate", "disable"}
    for action_index, action in enumerate(tokens):
        if action not in simple_past_actions:
            continue
        if action in did_actions and not any(
            tokens[candidate] in {"did", "didn"}
            for candidate in range(max(0, action_index - 3), action_index)
        ):
            continue
        if any(
            tokens[candidate] in {"ist", "sind", "war", "waren", "is", "are", "were"}
            for candidate in range(max(0, action_index - 5), action_index)
        ):
            continue
        context_start = max(0, action_index - 5)
        for boundary_index in range(context_start, action_index):
            if (
                tokens[boundary_index] in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES
                or tokens[boundary_index] == NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
            ):
                context_start = boundary_index + 1
        context_end = min(len(tokens), action_index + 10)
        for boundary_index in range(action_index + 1, context_end):
            if (
                tokens[boundary_index] in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES
                or tokens[boundary_index] == NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
            ):
                context_end = boundary_index
                break
        context = tokens[context_start:context_end]
        if action in {
            "muted",
            "mute",
            "silenced",
            "silence",
            "disabled",
            "disable",
            "unmuted",
            "enabled",
            "activated",
            "enable",
            "activate",
        } and not (
            set(context) & subjects
        ):
            continue
        has_positive_target = bool(set(context) & positive_targets)
        has_negative_target = bool(set(context) & negative_targets)
        if action in {"enabled", "activated", "enable", "activate"} and set(context) & subjects:
            has_positive_target = True
        if action in {"muted", "mute", "silenced", "silence", "disabled", "disable"} and set(context) & subjects:
            has_negative_target = True
        if not has_positive_target and not has_negative_target:
            continue
        negated = _notification_loudness_scoped_negation_count(
            tokens, max(0, action_index - 5), action_index
        ) % 2 == 1
        if has_positive_target:
            if negated:
                negative = True
            else:
                positive = True
        if has_negative_target:
            if negated:
                positive = True
            else:
                negative = True
    has_perfect_never = bool(
        {"habe", "haben", "hat", "have", "has"}.intersection(tokens)
        and {"nie", "niemals", "never"}.intersection(tokens)
    )
    if has_perfect_never:
        for phrase, action_is_positive in (
            ("laut gestellt", True),
            ("laut geschaltet", True),
            ("stumm geschaltet", False),
            ("stummgeschaltet", False),
            ("ausgeschaltet", False),
        ):
            if not _contains_normalized_phrase(normalized, phrase):
                continue
            if action_is_positive:
                negative = True
            else:
                positive = True
    return positive, negative


def _notification_loudness_phrase_is_negated(normalized: str, phrase: str) -> bool:
    tokens = normalized.split()
    phrase_tokens = phrase.split()
    width = len(phrase_tokens)
    for index in range(len(tokens) - width + 1):
        if tokens[index : index + width] != phrase_tokens:
            continue
        if _notification_loudness_scoped_negation_count(
            tokens, max(0, index - 3), index
        ) % 2:
            return True
    return False


def _notification_loudness_has_negative_current_status(normalized: str) -> bool:
    tokens = normalized.split()
    positive_status_terms = NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS
    contracted_copulas = {"isn", "aren", "re"}
    for status_index, token in enumerate(tokens):
        if token not in positive_status_terms:
            continue
        for copula_index in range(max(0, status_index - 4), status_index):
            copula = tokens[copula_index]
            between_start = copula_index + 1
            for boundary_index in range(between_start, status_index):
                if (
                    tokens[boundary_index] in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES
                    or tokens[boundary_index] == NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
                ):
                    between_start = boundary_index + 1
            between = tokens[between_start:status_index]
            if copula in {"is", "are", "re"} and "not" in between:
                return True
            if copula in {"ist", "sind"} and "nicht" in between:
                return True
            if copula in contracted_copulas and "t" in between:
                return True
    for copula_index, copula in enumerate(tokens):
        if copula not in {"ist", "sind"}:
            continue
        for status_index in range(max(0, copula_index - 4), copula_index):
            if tokens[status_index] not in positive_status_terms:
                continue
            before_status = tokens[max(0, status_index - 4) : status_index]
            after_status = tokens[status_index + 1 : copula_index]
            if (
                any(value in NOTIFICATION_LOUDNESS_NEGATION_TERMS for value in before_status)
                and any(
                    value
                    in {
                        "nachricht",
                        "nachrichten",
                        "message",
                        "messages",
                        "benachrichtigung",
                        "benachrichtigungen",
                        "die",
                        "sie",
                    }
                    for value in before_status
                )
                and all(value in NOTIFICATION_LOUDNESS_CURRENT_STATUS_MODIFIERS for value in after_status)
            ):
                return True
    return False


def _notification_loudness_has_contradictory_state(normalized: str) -> bool:
    state_terms = (
        set(NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS)
        | set(NOTIFICATION_LOUDNESS_MUTE_TERMS)
        | set(NOTIFICATION_LOUDNESS_OFF_TERMS)
    )
    for term in state_terms:
        has_unnegated, has_negated = _notification_loudness_term_polarity(normalized, frozenset({term}))
        if has_unnegated and has_negated:
            return True
    german_still_unnegated, german_still_negated = _notification_loudness_german_still_polarity(normalized)
    if german_still_unnegated and german_still_negated:
        return True
    for left, right, negated_pair_is_contradictory in (
        ("on", "off", True),
        ("aktiv", "inaktiv", True),
        ("active", "inactive", True),
        ("enabled", "disabled", True),
        ("sichtbar", "unsichtbar", True),
        ("visible", "hidden", True),
        ("loud", "muted", False),
    ):
        left_unnegated, left_negated = _notification_loudness_term_polarity(
            normalized, frozenset({left})
        )
        right_unnegated, right_negated = _notification_loudness_term_polarity(
            normalized, frozenset({right})
        )
        if left_unnegated and right_unnegated:
            return True
        if negated_pair_is_contradictory and left_negated and right_negated:
            return True
    for loud_term in ("loud", "laut"):
        for mute_term in ("muted", "silenced", "silent", "quiet", "stumm", "lautlos"):
            loud_unnegated, _ = _notification_loudness_term_polarity(
                normalized, frozenset({loud_term})
            )
            mute_unnegated, _ = _notification_loudness_term_polarity(
                normalized, frozenset({mute_term})
            )
            if loud_unnegated and mute_unnegated:
                return True
    return False


def _notification_loudness_has_sequenced_action_status(
    normalized: str, *, activation_only: bool = False
) -> bool:
    tokens = normalized.split()
    action_terms = {
        "set",
        "put",
        "make",
        "made",
        "turn",
        "turned",
        "switch",
        "switched",
        "enable",
        "enabled",
        "activate",
        "activated",
        "mute",
        "muted",
        "silence",
        "silenced",
        "disable",
        "disabled",
        "stellte",
        "schaltete",
        "machte",
        "setzte",
        "gestellt",
        "geschaltet",
        "gemacht",
        "gesetzt",
        "checked",
        "verified",
        "confirmed",
        "noticed",
        "saw",
        "geprueft",
        "sichergestellt",
    }
    subject_terms = {
        "nachricht",
        "nachrichten",
        "message",
        "messages",
        "benachrichtigung",
        "benachrichtigungen",
        "notification",
        "notifications",
        "sie",
        "they",
        "it",
        "die",
        "das",
    }
    if activation_only:
        state_terms = {
            "an",
            "on",
            "aktiv",
            "active",
            "enabled",
            "sichtbar",
            "visible",
            *NOTIFICATION_LOUDNESS_OFF_TERMS,
        }
    else:
        state_terms = (
            set(NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS)
            | set(NOTIFICATION_LOUDNESS_MUTE_TERMS)
            | set(NOTIFICATION_LOUDNESS_OFF_TERMS)
        )
    boundaries = NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES | {
        NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
    }
    for boundary_index, token in enumerate(tokens):
        if token not in boundaries:
            continue
        before = tokens[:boundary_index]
        after = tokens[boundary_index + 1 :]
        if (
            any(value in action_terms for value in before)
            and any(value in subject_terms for value in after)
            and any(value in state_terms for value in after)
        ):
            return True
    return False


def _notification_loudness_has_cross_subject_conflict(
    normalized: str,
    *,
    has_unnegated_mute: bool,
    has_negated_mute: bool,
    has_unnegated_off: bool,
    has_negated_off: bool,
    has_positive_unmute_phrase: bool,
    has_positive_current_status: bool,
    has_negative_current_status: bool,
) -> bool:
    tokens = set(normalized.split())
    message_subject = tokens & {"nachricht", "nachrichten", "message", "messages"}
    notification_subject = tokens & {
        "benachrichtigung",
        "benachrichtigungen",
        "benachrichtigungston",
        "notification",
        "notifications",
    }
    if not message_subject or not notification_subject:
        return False
    if not (
        tokens & NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES
        or NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN in tokens
    ):
        return False
    positive = has_negated_mute or has_negated_off or has_positive_unmute_phrase or has_positive_current_status
    negative = has_unnegated_mute or has_unnegated_off or has_negative_current_status
    return positive and negative


def _notification_loudness_has_audibility_state(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in (
            "cannot hear notifications",
            "can not hear notifications",
            "can t hear notifications",
            "cannot hear messages",
            "can not hear messages",
            "can t hear messages",
            "could not hear notifications",
            "couldn t hear notifications",
            "could not hear messages",
            "couldn t hear messages",
            "could not hear message notifications",
            "couldn t hear message notifications",
            "i do not hear notifications",
            "i don t hear notifications",
            "i can hear notifications",
            "i can hear messages",
            "i can hear message notifications",
            "ich kann nachrichten hoeren",
            "ich kann nachrichten jetzt hoeren",
            "ich kann die nachrichten hoeren",
            "ich kann die nachrichten jetzt hoeren",
            "ich kann die benachrichtigungen hoeren",
            "ich kann die benachrichtigungen jetzt hoeren",
            "kann die nachrichten nicht hoeren",
            "kann die benachrichtigungen nicht hoeren",
        )
    )


def _notification_loudness_has_explicit_confirmation(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in (
            "made sure",
            "verified that",
            "confirmed that",
            "sichergestellt",
            "ich kann bestaetigen",
            "ich kann belegen",
            "ich bestaetige",
            "ich habe bestaetigt",
            "ich kann bestätigen",
            "ich bestätige",
            "ich habe bestätigt",
        )
    )


def _notification_loudness_has_verification_question(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in (
            "checked if",
            "checked whether",
            "verified if",
            "verified whether",
            "checked to see if",
            "geprueft ob",
            "geprüft ob",
            "nachgesehen ob",
            "ueberprueft ob",
            "überprüft ob",
        )
    )


def _notification_loudness_has_ambiguous_alternative(normalized: str) -> bool:
    tokens = set(normalized.split())
    if not tokens & {"or", "oder"}:
        return False
    positive_phrases = (
        "laut",
        "loud",
        "an",
        "on",
        "active",
        "enabled",
        "unmuted",
        "nicht stumm",
        "nicht lautlos",
        "not muted",
        "not off",
        "not disabled",
    )
    negative_phrases = (
        "stumm",
        "lautlos",
        "muted",
        "silenced",
        "silent",
        "aus",
        "off",
        "disabled",
        "nicht laut",
        "not loud",
        "not on",
    )
    return (
        any(_contains_normalized_phrase(normalized, phrase) for phrase in positive_phrases)
        and any(_contains_normalized_phrase(normalized, phrase) for phrase in negative_phrases)
    )


def _notification_loudness_has_ambiguous_status_qualifier(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in (
            "on hold",
            "on pause",
            "on standby",
            "on vacation",
            "off topic",
            "off duty",
            "on telegram",
            "on signal",
            "on whatsapp",
            "on in the app",
            "on in app",
        )
    )


def _notification_loudness_has_ambiguous_location_status(normalized: str) -> bool:
    location_phrases = (
        "on my phone",
        "on the phone",
        "on my device",
        "on the device",
        "on screen",
        "on the screen",
        "on the lock screen",
        "off my phone",
        "off the phone",
        "off the record",
    )
    if not any(_contains_normalized_phrase(normalized, phrase) for phrase in location_phrases):
        return False
    other_state_terms = (
        set(NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS) - {"on"}
    ) | set(NOTIFICATION_LOUDNESS_MUTE_TERMS) | (set(NOTIFICATION_LOUDNESS_OFF_TERMS) - {"off"}) | {
        "laut",
        "loud",
    }
    return not any(_contains_normalized_phrase(normalized, term) for term in other_state_terms)


def _notification_loudness_has_ambiguous_chat_activity(normalized: str) -> bool:
    tokens = set(normalized.split())
    if not tokens & {"chat", "conversation", "thread"}:
        return False
    if tokens & {
        "laut",
        "loud",
        "stumm",
        "lautlos",
        "muted",
        "silenced",
        "silent",
        "unmuted",
        "audible",
        "hoerbar",
        "volume",
    }:
        return False
    return bool(
        tokens
        & {
            "aktiv",
            "active",
            "inaktiv",
            "inactive",
            "enabled",
            "disabled",
            "sichtbar",
            "visible",
            "an",
            "on",
            "aus",
            "off",
        }
    )


def _notification_loudness_pending_pronoun_decision(normalized: str) -> str | None:
    if normalized in {
        "sie sind an",
        "sie sind laut",
        "sie sind nicht aus",
        "sie sind nicht ausgeschaltet",
        "sie sind nicht stumm",
        "sie sind nicht lautlos",
        "sie sind nicht still",
        "die sind an",
        "die sind laut",
        "die sind nicht aus",
        "die sind nicht ausgeschaltet",
        "die sind nicht stumm",
        "die sind nicht lautlos",
        "die sind nicht still",
        "das ist an",
        "das ist laut",
        "das ist nicht aus",
        "das ist nicht ausgeschaltet",
        "das ist nicht stumm",
        "das ist nicht lautlos",
        "das ist nicht still",
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
        "it is on",
        "it is loud",
        "it is not off",
        "it is not disabled",
        "it is not muted",
    }:
        return "confirmed"
    if normalized in {
        "sie sind aus",
        "sie sind stumm",
        "sie sind lautlos",
        "sie sind still",
        "sie sind nicht laut",
        "sie sind nicht an",
        "sie sind ausgeschaltet",
        "die sind aus",
        "die sind stumm",
        "die sind lautlos",
        "die sind still",
        "die sind nicht laut",
        "die sind nicht an",
        "die sind ausgeschaltet",
        "das ist aus",
        "das ist stumm",
        "das ist lautlos",
        "das ist still",
        "das ist nicht laut",
        "das ist nicht an",
        "das ist ausgeschaltet",
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
        "it is off",
        "it is muted",
        "it is silent",
        "it is not loud",
        "it is not on",
        "it is disabled",
    }:
        return "declined"
    tokens = normalized.split()
    pronouns = {"sie", "die", "das", "they", "it"}
    copulas = {"ist", "sind", "is", "are", "re"}
    status_terms = (
        NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS
        | NOTIFICATION_LOUDNESS_MUTE_TERMS
        | NOTIFICATION_LOUDNESS_OFF_TERMS
    )
    if len(tokens) >= 3 and tokens[0] in pronouns and tokens[1] in copulas:
        for status_index in range(2, len(tokens)):
            status = tokens[status_index]
            if status not in status_terms:
                continue
            between = tokens[2:status_index]
            if not all(
                value in NOTIFICATION_LOUDNESS_CURRENT_STATUS_MODIFIERS
                or value in NOTIFICATION_LOUDNESS_NEGATION_TERMS
                for value in between
            ):
                continue
            after = tokens[status_index + 1 :]
            if not all(value in NOTIFICATION_LOUDNESS_CURRENT_STATUS_MODIFIERS for value in after):
                continue
            negated = sum(value in NOTIFICATION_LOUDNESS_NEGATION_TERMS for value in between) % 2 == 1
            if status in NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS:
                return "declined" if negated else "confirmed"
            return "confirmed" if negated else "declined"
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
    if normalized.startswith(NOTIFICATION_LOUDNESS_NON_DECLARATIVE_STARTS):
        return True
    without_temporal_fillers = " ".join(
        token
        for token in tokens
        if token not in NOTIFICATION_LOUDNESS_NON_ASSERTIVE_OPTIONAL_MODIFIERS
    )
    return without_temporal_fillers.startswith(NOTIFICATION_LOUDNESS_NON_DECLARATIVE_STARTS)


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
