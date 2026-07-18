from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import re
from typing import Any, Callable, Iterable

from pydantic import ValidationError

from TeeBotus.decisions.reminder import ReminderDecision, parse_reminder_decision
from TeeBotus.runtime.accounts import AccountStore
from TeeBotus.runtime.proactive_agent import (
    enable_proactive_agent,
    proactive_agent_instance_enabled,
    queue_proactive_message,
    set_proactive_categories,
)
from TeeBotus.runtime.timezone import configured_timezone, local_now

StructuredReminderRunner = Callable[[str, type[Any]], Any]
LOGGER = logging.getLogger("TeeBotus.runtime.reminder_intent")


@dataclass(frozen=True)
class ReminderIntent:
    is_request: bool
    due_at: str = ""
    subject: str = ""
    recurrence: str = ""
    recurrence_anchor_day: int | None = None
    recurrence_anchor_end_of_month: bool | None = None
    missing_time: bool = False
    source: str = "classic"


REMINDER_REQUEST_RE = re.compile(
    r"\b("
    r"(?<!ich )erinner(?:e|st|n)?\s+(?:mich|mi|uns)|"
    r"(?<!ich )erinnere?\s+(?:mich|mi|uns)|"
    r"(?<!ich )denk(?:e)?(?:\s+bitte)?(?:\s+(?:fuer\s+)?(?:mich|uns))?(?:\s+.{0,80}?)?\s+(?:an|dran|daran)|"
    r"sag(?:e)?\s+(?:mir|uns)\s+(?:(?!\bbescheid\b).){0,80}\bbescheid|"
    r"remind\s+(?:me|us)|"
    r"(?:kannst|koenntest)\s+du\s+(?:mich|uns)\s+(?!irgendwann\b)"
    r"(?:(?!\berinner(?:n|en)?\b).){0,120}\berinner(?:n|en)?|"
    r"(?:kannst|koenntest)\s+du\s+(?:mich|uns)\s+(?:bitte\s+)?(?!irgendwann\b)"
    r"(?:(?!\b(?:an|daran)\b).){0,80}\b(?:an|daran)\b\s+.{1,120}\berinner(?:n|en)?|"
    r"mach(?:e)?\s+(?:mich|uns)\s+(?:(?!\baufmerksam\b).){0,80}\baufmerksam\b|"
    r"(?:nicht\s+vergessen|vergiss\w*(?:\s+bitte)?\s+nicht)\s*,?\s+(?:mich|uns)\s+"
    r"(?:(?!\berinner\w*\b).){0,120}\berinner\w*"
    r")\b",
    re.IGNORECASE,
)
STRUCTURED_REMINDER_CUE_RE = re.compile(
    r"(?:"
    r"\b(?:erinner\w*|remind\w*|remember\w*|reminder|dran|daran|bescheid|stups\w*|anstups\w*)\b|"
    r"\bdenk(?:e|en)?\s+(?:bitte\s+)?(?:an|dran|daran)\b|"
    r"\b(?:nicht\s+vergessen|vergiss\w*\s+nicht)\b|\bdon['’]?t\s+forget\b|\bdo\s+not\s+forget\b|"
    r"\b(?:ping|notify|alert)\s+(?:mich|me|uns|us)\b|"
    r"\bauf\s+dem\s+schirm\b"
    r")",
    re.IGNORECASE,
)
NEGATED_REMINDER_REQUEST_RE = re.compile(
    r"\b(?:"
    r"erinner(?:e|st|n)?\s+(?:mich|mi|uns)|"
    r"remind\s+(?:me|us)|"
    r"sag(?:e)?\s+(?:mir|uns)|"
    r"denk(?:e)?(?:\s+bitte)?(?:\s+(?:fuer\s+)?(?:mich|uns))?|"
    r"(?:kannst|koenntest)\s+du\s+(?:mich|uns)"
    r")\s+(?:bitte\s+)?(?:nicht|nie)\b|"
    r"erinner(?:e|st|n)?\s+(?:mich|mi|uns)(?:(?!\b(?:an|dran|daran)\b).){0,80}\b(?:nicht|nie)\b"
    r"(?:(?!\b(?:an|dran|daran)\b).){0,20}\b(?:an|dran|daran)\b|"
    r"denk(?:e)?(?:(?!\b(?:an|dran|daran)\b).){0,80}\b(?:nicht|nie)\b"
    r"(?:(?!\b(?:an|dran|daran)\b).){0,20}\b(?:an|dran|daran)\b|"
    r"sag(?:e)?\s+(?:mir|uns)(?:(?!\bbescheid\b).){0,80}\b(?:nicht|nie)\b"
    r"(?:(?!\bbescheid\b).){0,20}\bbescheid\b|"
    r"(?:kannst|koenntest)\s+du\s+(?:mich|uns)(?:(?!\berinner\w*\b).){0,120}\b(?:nicht|nie)\b"
    r"(?:(?!\berinner\w*\b).){0,30}\berinner\w*\b",
    re.IGNORECASE,
)
NON_REQUEST_REMINDER_STATEMENT_RE = re.compile(
    r"\b(?:ich|du|er|sie|wir|ihr)\s+(?:erinner\w*|denk\w*)\b",
    re.IGNORECASE,
)

_CLOCK_HOUR = r"(?:2[0-3]|[01]?\d)(?!\d)"
EXPLICIT_TIME_CANDIDATE_RE = re.compile(
    r"\b(?:um|gegen)\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?:uhr)?",
    re.IGNORECASE,
)
DATE_TIME_CANDIDATE_RE = re.compile(
    r"\b(?:20\d{2}-\d{1,2}-\d{1,2}|\d{1,2}\.\d{1,2}(?:\.\d{2,4})?)"
    r"\s*(?:T|\s+)\s*(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?",
    re.IGNORECASE,
)
TIME_RE = re.compile(
    rf"\b(?:um|gegen)\s+(?P<hour>{_CLOCK_HOUR})(?::(?P<minute>[0-5]\d))?\s*(?:uhr)?\b",
    re.IGNORECASE,
)
WRITTEN_TIME_RE = re.compile(
    r"\b(?:um|gegen)\s+"
    r"(?:(?P<quarter>viertel)\s+(?P<direction>nach|vor)\s+|(?P<half>halb)\s+)?"
    r"(?P<hour>eins|ein|zwei|drei|vier|fuenf|fünf|sechs|sieben|acht|neun|zehn|elf|zwoelf|zwölf|"
    r"dreizehn|vierzehn|fuenfzehn|fünfzehn|sechzehn|siebzehn|achtzehn|neunzehn|zwanzig)"
    r"(?:\s+uhr)?\b",
    re.IGNORECASE,
)
DAYPART_DEFAULT_HOURS = (
    ("frueh", 9),
    ("fruh", 9),
    ("morgens", 9),
    ("vormittag", 10),
    ("mittag", 12),
    ("nachmittag", 15),
    ("abend", 18),
    ("nacht", 21),
)
RELATIVE_RE = re.compile(
    r"\bin\s+(?P<count>\d{1,3})\s*(?P<unit>min(?:ute)?n?|minuten?|std|stunden?|h|tage?n?|wochen?)\b",
    re.IGNORECASE,
)
RELATIVE_TEXT_RE = re.compile(
    r"\bin\s+(?P<phrase>(?:ein|eine|einer|einem|einen|zwei|drei|vier|fuenf|sechs|sieben|acht|neun|zehn)"
    r"(?:\s+(?:halbe|halben|viertel))?\s+(?:minute[n]?|stunde[n]?|tag(?:e|en)?|woche[n]?)"
    r"|(?:ein|eine|einer)\s+viertelstunde)\b",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"\b(?:am\s+)?(?P<day>[0-3]?\d)[.](?P<month>[01]?\d)(?:[.](?P<year>\d{2,4}))?[.]?"
    rf"(?:\s+(?:um|gegen)?\s*(?P<hour>{_CLOCK_HOUR})(?::(?P<minute>[0-5]\d))?\s*(?:uhr)?)?",
    re.IGNORECASE,
)
MONTH_NAME_DATE_RE = re.compile(
    r"\b(?:am\s+)?(?P<day>[0-3]?\d)\.?\s+"
    r"(?P<month>januar|jan|februar|feb|maerz|märz|marz|mrz|april|apr|mai|juni|jun|juli|jul|august|aug|"
    r"september|sep|oktober|okt|november|nov|dezember|dez)"
    r"(?:\s+(?P<year>\d{2,4}))?"
    rf"(?:\s+(?:um|gegen)?\s*(?P<hour>{_CLOCK_HOUR})(?::(?P<minute>[0-5]\d))?\s*(?:uhr)?)?",
    re.IGNORECASE,
)
ISO_RE = re.compile(
    r"\b(?P<year>20\d{2})-(?P<month>[01]\d)-(?P<day>[0-3]\d)"
    rf"(?:[T\s](?P<hour>{_CLOCK_HOUR}):(?P<minute>[0-5]\d))?",
    re.IGNORECASE,
)
DAY_WORDS = {
    "montag": 0,
    "dienstag": 1,
    "mittwoch": 2,
    "donnerstag": 3,
    "freitag": 4,
    "samstag": 5,
    "sonntag": 6,
}
MONTH_NAMES = {
    "januar": 1,
    "jan": 1,
    "februar": 2,
    "feb": 2,
    "maerz": 3,
    "märz": 3,
    "marz": 3,
    "mrz": 3,
    "april": 4,
    "apr": 4,
    "mai": 5,
    "juni": 6,
    "jun": 6,
    "juli": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "oktober": 10,
    "okt": 10,
    "november": 11,
    "nov": 11,
    "dezember": 12,
    "dez": 12,
}
DAY_WORD_RE = re.compile(
    r"\b(?P<day>montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)"
    rf"(?:\s+(?:um|gegen)\s+(?P<hour>{_CLOCK_HOUR})(?::(?P<minute>[0-5]\d))?\s*(?:uhr)?)?",
    re.IGNORECASE,
)
MONTH_DAY_RE = re.compile(
    rf"\b(?:am|zum|jeden)\s+(?P<day>[0-3]?\d)\.?"
    rf"(?:\s+(?:um|gegen)\s+(?P<hour>{_CLOCK_HOUR})(?::(?P<minute>[0-5]\d))?\s*(?:uhr)?)?",
    re.IGNORECASE,
)
RECURRENCE_EVERY_RE = re.compile(
    r"\b(?:alle|every)\s+(?P<count>\d{1,3})\s+"
    r"(?P<unit>min(?:ute|uten?)?|minutes?|std|stunden?|hours?|h|tage?n?|days?|wochen?|weeks?|w|monate?n?|months?)\b",
    re.IGNORECASE,
)
RECURRENCE_MARKER_RE = re.compile(
    r"(?i)\b(?:"
    r"(?:jeden|alle)\s+(?:werk|wochen)tag(?:e|en|s)?|every\s+weekdays?|"
    r"werktag(?:e|en|s)?|wochentag(?:e|en|s)?|weekdays?|business\s+days?|"
    r"taeglich|täglich|daily|"
    r"woechentlich|wöchentlich|weekly|"
    r"monatlich|monthly|"
    r"jeden\s+(?:tag|monat|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)|"
    r"jede\s+(?:woche|monat)|"
    r"alle\s+\d{1,3}\s+(?:min(?:ute|uten?)?|minutes?|std|stunden?|hours?|h|tage?n?|days?|wochen?|weeks?|w|monate?n?|months?)|"
    r"every\s+(?:day|week|month)|"
    r"every\s+\d{1,3}\s+(?:minutes?|hours?|days?|weeks?|months?)"
    r")\b"
)


def maybe_queue_natural_reminder(
    *,
    account_store: AccountStore,
    account_id: str,
    instance_name: str,
    text: str,
    now: datetime | None = None,
    structured_decision_runner: StructuredReminderRunner | None = None,
) -> str | None:
    resolved_now = now or local_now()
    if _is_negated_reminder_request(text) or _is_reminder_statement(text):
        return None
    intent = parse_reminder_intent(text, now=resolved_now)
    if (
        not intent.is_request
        and structured_decision_runner is not None
        and _has_structured_reminder_cue(text)
    ):
        intent = _structured_reminder_intent(
            text,
            structured_decision_runner=structured_decision_runner,
            now=resolved_now,
        )
    if not intent.is_request:
        return None
    if not proactive_agent_instance_enabled(instance_name):
        return "Erinnerungen sind fuer diese Instanz nicht freigeschaltet."
    if intent.missing_time or not intent.due_at:
        return "Woran und wann soll ich dich erinnern? Beispiel: Erinnere mich morgen um 9 an den Termin."
    _ensure_reminder_consent(account_store, account_id)
    decision = queue_proactive_message(
        account_store,
        account_id,
        category="reminder",
        intent="user_requested_reminder",
        message_text=f"Du wolltest erinnert werden: {intent.subject}",
        due_at=intent.due_at,
        now=now,
        risk_gate="none",
        recurrence=intent.recurrence,
        recurrence_anchor_day=intent.recurrence_anchor_day,
        recurrence_anchor_end_of_month=intent.recurrence_anchor_end_of_month,
        user_requested=True,
        planner={
            "source": "structured_reminder_decision" if intent.source == "model" else "natural_reminder_request",
            "subject": intent.subject,
            "recurrence": intent.recurrence,
        },
    )
    if not decision.allowed:
        if decision.reason == "outside_allowed_hours":
            return "Ich habe die Erinnerung verstanden, aber sie liegt ausserhalb deines erlaubten Proactive-Zeitfensters."
        if decision.reason == "no_private_route":
            return "Ich kann dich nur in einem privaten Chat erinnern. Schreib mir bitte privat."
        return f"Ich konnte die Erinnerung nicht anlegen: {decision.reason}."
    due = _format_due_for_reply(intent.due_at)
    return f"Okay, ich erinnere dich {due}: {intent.subject}"


def parse_reminder_intent(text: str, *, now: datetime | None = None) -> ReminderIntent:
    raw = str(text or "").strip()
    if not raw or _is_negated_reminder_request(raw) or _is_reminder_statement(raw) or not REMINDER_REQUEST_RE.search(_normalize(raw)):
        return ReminderIntent(False)
    resolved_now = now or local_now()
    normalized_now = resolved_now if resolved_now.tzinfo else resolved_now.replace(tzinfo=timezone.utc)
    recurrence = _parse_recurrence(raw)
    due_at = _parse_due_at(raw, resolved_now)
    if due_at and TIME_RE.search(raw) and _recurrence_has_clock_only_anchor(raw, recurrence):
        due_at = _initial_recurrence_due_with_time(normalized_now, recurrence, raw)
    if recurrence == "weekdays" and due_at:
        due_at = _move_due_to_weekday(due_at, normalized_now)
    if not due_at and recurrence.startswith("every ") and not _has_invalid_explicit_time(raw):
        due_at = _initial_interval_due(normalized_now, recurrence)
    subject = _reminder_subject(raw)
    anchor_day, anchor_end_of_month = _recurrence_anchor_from_text(raw, recurrence, fallback=normalized_now)
    return ReminderIntent(
        True,
        due_at=due_at,
        subject=subject,
        recurrence=recurrence,
        recurrence_anchor_day=anchor_day,
        recurrence_anchor_end_of_month=anchor_end_of_month,
        missing_time=not bool(due_at),
    )


def _structured_reminder_intent(
    text: str,
    *,
    structured_decision_runner: StructuredReminderRunner,
    now: datetime,
) -> ReminderIntent:
    raw = str(text or "").strip()
    if not raw or raw.startswith("/"):
        return ReminderIntent(False)
    resolved_now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    prompt_now = resolved_now.astimezone(configured_timezone())
    try:
        payload = structured_decision_runner(_structured_reminder_prompt(raw, now=prompt_now), ReminderDecision)
        decision = parse_reminder_decision(payload)
    except (TypeError, ValueError, ValidationError):
        return ReminderIntent(False)
    except Exception:  # noqa: BLE001 - optional classifier failures must not abort normal chat.
        LOGGER.exception("Structured reminder classifier failed")
        return ReminderIntent(False)
    if not decision.should_create or decision.confidence < 0.7:
        return ReminderIntent(False)
    subject = decision.text.strip() or "deinen Termin"
    recurrence = str(decision.recurrence or "").strip()
    anchor_day, anchor_end_of_month = _recurrence_anchor_from_text(raw, recurrence, fallback=resolved_now)
    if not decision.datetime_iso:
        return ReminderIntent(
            True,
            subject=subject,
            recurrence=recurrence,
            recurrence_anchor_day=anchor_day,
            recurrence_anchor_end_of_month=anchor_end_of_month,
            missing_time=True,
            source="model",
        )
    parsed_due_at = _parse_structured_due_at(decision.datetime_iso)
    if parsed_due_at is None:
        return ReminderIntent(
            True,
            subject=subject,
            recurrence=recurrence,
            recurrence_anchor_day=anchor_day,
            recurrence_anchor_end_of_month=anchor_end_of_month,
            missing_time=True,
            source="model",
        )
    if parsed_due_at <= resolved_now:
        return ReminderIntent(
            True,
            subject=subject,
            recurrence=recurrence,
            recurrence_anchor_day=anchor_day,
            recurrence_anchor_end_of_month=anchor_end_of_month,
            missing_time=True,
            source="model",
        )
    return ReminderIntent(
        True,
        due_at=parsed_due_at.isoformat(timespec="seconds"),
        subject=subject[:240],
        recurrence=recurrence,
        recurrence_anchor_day=anchor_day,
        recurrence_anchor_end_of_month=anchor_end_of_month,
        missing_time=False,
        source="model",
    )


def _parse_structured_due_at(value: str) -> datetime | None:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=configured_timezone())
    return parsed


def _structured_reminder_prompt(text: str, *, now: datetime) -> str:
    timezone_name = getattr(now.tzinfo, "key", str(now.tzinfo or "UTC"))
    return (
        "Pruefe, ob die natuerliche Nachricht eine Bitte ist, eine Erinnerung fuer den User anzulegen. "
        "Antworte ausschliesslich als JSON fuer ReminderDecision. Lege nur User-gewuenschte Erinnerungen an; "
        "keine allgemeinen Fragen, keine Bot-Aufgaben ohne Reminderwunsch. "
        "Nutze den folgenden Zeitanker fuer relative Angaben. Gib datetime_iso immer mit einem expliziten "
        "UTC-Offset aus; eine Uhrzeit ohne Offset ist lokale Userzeit. Wenn die Zeit nicht sicher bestimmbar ist, "
        "lasse datetime_iso leer.\n"
        f"Aktuelle lokale Zeit: {now.isoformat(timespec='seconds')} ({timezone_name})\n\n"
        f"Nachricht:\n{text}"
    )


def _ensure_reminder_consent(account_store: AccountStore, account_id: str) -> None:
    state = account_store.read_agent_state(account_id)
    proactive = state.get("proactive") if isinstance(state, dict) else {}
    consent = state.get("consent") if isinstance(state, dict) else {}
    categories = consent.get("categories") if isinstance(consent, dict) else []
    normalized = _normalized_categories(categories)
    if "reminder" not in normalized:
        normalized = [*normalized, "reminder"]
    if not isinstance(proactive, dict) or not proactive.get("enabled"):
        enable_proactive_agent(account_store, account_id, categories=normalized)
        return
    set_proactive_categories(account_store, account_id, normalized)


def _normalized_categories(values: object) -> list[str]:
    if not isinstance(values, Iterable) or isinstance(values, (str, bytes)):
        return []
    allowed = {"reminder", "task", "tip", "test", "image", "analysis", "reflection"}
    return [value for value in dict.fromkeys(str(item or "").strip().casefold() for item in values) if value in allowed]


def _has_structured_reminder_cue(text: str) -> bool:
    return STRUCTURED_REMINDER_CUE_RE.search(str(text or "")) is not None


def _is_negated_reminder_request(text: str) -> bool:
    return NEGATED_REMINDER_REQUEST_RE.search(_normalize(str(text or ""))) is not None


def _is_reminder_statement(text: str) -> bool:
    return NON_REQUEST_REMINDER_STATEMENT_RE.search(_normalize(str(text or ""))) is not None


def _parse_due_at(text: str, now: datetime) -> str:
    normalized_now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    if _has_invalid_explicit_time(text):
        return ""
    relative = RELATIVE_RE.search(_normalize(text))
    if relative:
        count = int(relative.group("count"))
        unit = relative.group("unit").casefold()
        if unit.startswith("min"):
            return _iso(normalized_now + timedelta(minutes=count))
        if unit in {"h", "std"} or unit.startswith("stunde"):
            return _iso(normalized_now + timedelta(hours=count))
        if unit.startswith("tag"):
            return _iso(_apply_explicit_time(normalized_now + timedelta(days=count), text))
        if unit.startswith("woche"):
            return _iso(_apply_explicit_time(normalized_now + timedelta(weeks=count), text))
    relative_text = RELATIVE_TEXT_RE.search(_normalize(text))
    if relative_text:
        delta = _relative_text_delta(relative_text.group("phrase"))
        if delta is not None:
            candidate = normalized_now + delta
            if _relative_text_uses_calendar_unit(relative_text.group("phrase")):
                candidate = _apply_explicit_time(candidate, text)
            return _iso(candidate)
    month_name_date = MONTH_NAME_DATE_RE.search(_normalize(text))
    if month_name_date is not None and _date_match_is_after_subject_marker(_normalize(text), month_name_date):
        month_name_date = None
    if month_name_date:
        month = MONTH_NAMES[month_name_date.group("month").casefold()]
        day = int(month_name_date.group("day"))
        hour, minute = _date_time_from_match(month_name_date, text)
        if month_name_date.group("year"):
            return _build_datetime(normalized_now, _normalize_year(month_name_date.group("year"), normalized_now.year), month, day, hour, minute)
        return _next_annual_date(normalized_now, month=month, day=day, hour=hour, minute=minute)
    iso = ISO_RE.search(text)
    if iso is not None and _date_match_is_after_subject_marker(text, iso):
        iso = None
    if iso:
        return _build_datetime(
            normalized_now,
            int(iso.group("year")),
            int(iso.group("month")),
            int(iso.group("day")),
            *_date_time_from_match(iso, text),
        )
    date = DATE_RE.search(text)
    if date is not None and _date_match_is_after_subject_marker(text, date):
        date = None
    if date:
        year = _normalize_year(date.group("year"), normalized_now.year)
        if not date.group("year"):
            return _next_annual_date(
                normalized_now,
                month=int(date.group("month")),
                day=int(date.group("day")),
                hour=_date_time_from_match(date, text)[0],
                minute=_date_time_from_match(date, text)[1],
            )
        return _build_datetime(
            normalized_now,
            year,
            int(date.group("month")),
            int(date.group("day")),
            *_date_time_from_match(date, text),
        )
    month_day = MONTH_DAY_RE.search(text)
    if month_day:
        return _next_month_day(
            normalized_now,
            day=int(month_day.group("day")),
            hour=_date_time_from_match(month_day, text)[0],
            minute=_date_time_from_match(month_day, text)[1],
        )
    lowered = _normalize(text)
    for word, offset in (("uebermorgen", 2), ("morgen", 1), ("heute", 0)):
        if re.search(rf"\b{word}\b", lowered):
            hour, minute = _time_in_text(text, default_hour=9)
            due = normalized_now + timedelta(days=offset)
            candidate = due.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= normalized_now:
                return ""
            return _iso(candidate)
    weekday = DAY_WORD_RE.search(lowered)
    if weekday:
        target_weekday = DAY_WORDS[weekday.group("day").casefold()]
        days = (target_weekday - normalized_now.weekday()) % 7
        if days == 0 and re.search(
            rf"\b(?:naechsten|kommenden)\s+{weekday.group('day')}"
            r"(?:abend(?:s)?|morgen(?:s)?|nacht(?:s)?|vormittag(?:s)?|mittag(?:s)?|nachmittag(?:s)?)?\b",
            lowered,
        ):
            days = 7
        hour, minute = _date_time_from_match(weekday, text)
        due = normalized_now + timedelta(days=days)
        candidate = due.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= normalized_now:
            candidate += timedelta(days=7)
        return _iso(candidate)
    time_match = TIME_RE.search(text)
    if time_match:
        hour = int(time_match.group("hour"))
        minute = int(time_match.group("minute") or 0)
        due = normalized_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if due <= normalized_now:
            due += timedelta(days=1)
        return _iso(due)
    return ""


_RELATIVE_TEXT_COUNTS = {
    "ein": 1.0,
    "eine": 1.0,
    "einer": 1.0,
    "einem": 1.0,
    "einen": 1.0,
    "zwei": 2.0,
    "drei": 3.0,
    "vier": 4.0,
    "fuenf": 5.0,
    "sechs": 6.0,
    "sieben": 7.0,
    "acht": 8.0,
    "neun": 9.0,
    "zehn": 10.0,
}
_RELATIVE_TEXT_UNITS = {
    "minute": "minutes",
    "minuten": "minutes",
    "stunde": "hours",
    "stunden": "hours",
    "tag": "days",
    "tage": "days",
    "tagen": "days",
    "woche": "weeks",
    "wochen": "weeks",
}
_WRITTEN_HOURS = {
    "ein": 1,
    "eins": 1,
    "zwei": 2,
    "drei": 3,
    "vier": 4,
    "fuenf": 5,
    "fünf": 5,
    "sechs": 6,
    "sieben": 7,
    "acht": 8,
    "neun": 9,
    "zehn": 10,
    "elf": 11,
    "zwoelf": 12,
    "zwölf": 12,
    "dreizehn": 13,
    "vierzehn": 14,
    "fuenfzehn": 15,
    "fünfzehn": 15,
    "sechzehn": 16,
    "siebzehn": 17,
    "achtzehn": 18,
    "neunzehn": 19,
    "zwanzig": 20,
}


def _relative_text_delta(phrase: str) -> timedelta | None:
    normalized = " ".join(str(phrase or "").casefold().split())
    if normalized in {"einer viertelstunde", "eine viertelstunde", "ein viertelstunde"}:
        return timedelta(minutes=15)
    tokens = normalized.split()
    if len(tokens) not in {2, 3}:
        return None
    count = _RELATIVE_TEXT_COUNTS.get(tokens[0])
    if count is None:
        return None
    modifier = tokens[1] if len(tokens) == 3 else ""
    unit = _RELATIVE_TEXT_UNITS.get(tokens[-1])
    if unit is None:
        return None
    factor = {"halbe": 0.5, "halben": 0.5, "viertel": 0.25}.get(modifier, 1.0)
    amount = count * factor
    if unit == "minutes":
        return timedelta(minutes=amount)
    if unit == "hours":
        return timedelta(hours=amount)
    if unit == "days":
        return timedelta(days=amount)
    return timedelta(weeks=amount)


def _relative_text_uses_calendar_unit(phrase: str) -> bool:
    return str(phrase or "").casefold().split()[-1] in {
        "tag",
        "tage",
        "tagen",
        "woche",
        "wochen",
    }


def _move_due_to_weekday(due_at: str, now: datetime) -> str:
    try:
        candidate = datetime.fromisoformat(due_at)
    except ValueError:
        return ""
    while candidate.weekday() >= 5 or candidate <= now:
        candidate += timedelta(days=1)
    return _iso(candidate)


def _build_datetime(now: datetime, year: int, month: int, day: int, hour: int, minute: int) -> str:
    try:
        due = now.replace(year=year, month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
    except ValueError:
        return ""
    if due <= now:
        return ""
    return _iso(due)


def _next_annual_date(now: datetime, *, month: int, day: int, hour: int, minute: int) -> str:
    for year_offset in range(8):
        try:
            candidate = now.replace(
                year=now.year + year_offset,
                month=month,
                day=day,
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0,
            )
        except ValueError:
            continue
        if candidate > now:
            return _iso(candidate)
    return ""


def _next_month_day(now: datetime, *, day: int, hour: int, minute: int) -> str:
    month_index = now.year * 12 + now.month - 1
    for offset in range(13):
        candidate_index = month_index + offset
        year, zero_based_month = divmod(candidate_index, 12)
        try:
            candidate = now.replace(
                year=year,
                month=zero_based_month + 1,
                day=day,
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0,
            )
        except ValueError:
            continue
        if candidate > now:
            return _iso(candidate)
    return ""


def _add_calendar_months(value: datetime, count: int) -> datetime:
    month_index = value.year * 12 + value.month - 1 + count
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _time_in_text(text: str, *, default_hour: int) -> tuple[int, int]:
    marker = _time_marker_in_text(text)
    return marker if marker is not None else (default_hour, 0)


def _time_marker_in_text(text: str) -> tuple[int, int] | None:
    match = TIME_RE.search(text)
    if match:
        return int(match.group("hour")), int(match.group("minute") or 0)
    written = WRITTEN_TIME_RE.search(text)
    if written:
        hour = _WRITTEN_HOURS[written.group("hour").casefold()]
        if written.group("half"):
            return max(hour - 1, 0), 30
        if written.group("quarter"):
            if written.group("direction") == "vor":
                return max(hour - 1, 0), 45
            return hour, 15
        return hour, 0
    normalized = _normalize(text)
    for marker, hour in DAYPART_DEFAULT_HOURS:
        suffix = "" if marker.endswith("s") else "s?"
        if re.search(rf"{marker}{suffix}\b", normalized):
            return hour, 0
    return None


def _date_time_from_match(match: re.Match[str], text: str) -> tuple[int, int]:
    hour_text = match.groupdict().get("hour")
    minute_text = match.groupdict().get("minute")
    if hour_text is not None:
        return int(hour_text), int(minute_text or 0)
    return _time_in_text(text, default_hour=9)


def _parse_recurrence(text: str) -> str:
    normalized = _normalize(text)
    if re.search(r"\b(?:werktag(?:e|en|s)?|wochentag(?:e|en|s)?|weekdays?|business\s+days?)\b", normalized):
        return "weekdays"
    if re.search(r"\b(?:taeglich|daily|jeden\s+tag|every\s+day)\b", normalized):
        return "daily"
    if re.search(
        r"\b(?:woechentlich|weekly|jede\s+woche|jeden\s+(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)|every\s+week)\b",
        normalized,
    ):
        return "weekly"
    if re.search(r"\b(?:monatlich|monthly|jeden\s+monat|jede\s+monat|every\s+month)\b", normalized):
        return "monthly"
    match = RECURRENCE_EVERY_RE.search(normalized)
    if not match:
        return ""
    count = int(match.group("count"))
    unit = match.group("unit").casefold()
    if unit.startswith("min"):
        normalized_unit = "minutes"
    elif unit in {"std", "h"} or unit.startswith(("stunde", "hour")):
        normalized_unit = "hours"
    elif unit.startswith(("tag", "day")):
        normalized_unit = "days"
    elif unit in {"w", "week"} or unit.startswith(("woche", "week")):
        normalized_unit = "weeks"
    elif unit.startswith(("monat", "month")):
        normalized_unit = "months"
    else:
        return ""
    return f"every {count} {normalized_unit}"


def _recurrence_anchor_from_text(
    text: str,
    recurrence: str,
    *,
    fallback: datetime | None = None,
) -> tuple[int | None, bool | None]:
    normalized_recurrence = str(recurrence or "").strip().casefold()
    if normalized_recurrence != "monthly" and not re.fullmatch(r"every\s+\d{1,3}\s+months", normalized_recurrence):
        return None, None
    normalized = _normalize(text)
    for pattern in (MONTH_DAY_RE, MONTH_NAME_DATE_RE, DATE_RE, ISO_RE):
        match = pattern.search(normalized)
        if match is None or _date_match_is_after_subject_marker(normalized, match):
            continue
        try:
            day = int(match.group("day"))
        except (TypeError, ValueError):
            continue
        if 1 <= day <= 31:
            return day, day == 31
    if fallback is not None:
        return fallback.day, fallback.day == calendar.monthrange(fallback.year, fallback.month)[1]
    return None, None


def _initial_interval_due(now: datetime, recurrence: str) -> str:
    match = re.fullmatch(r"every\s+(?P<count>\d{1,3})\s+(?P<unit>minutes|hours|days|weeks|months)", recurrence)
    if not match:
        return ""
    count = int(match.group("count"))
    unit = match.group("unit")
    if unit == "minutes":
        due = now + timedelta(minutes=count)
    elif unit == "hours":
        due = now + timedelta(hours=count)
    elif unit == "days":
        due = now + timedelta(days=count)
    elif unit == "weeks":
        due = now + timedelta(weeks=count)
    else:
        due = _add_calendar_months(now, count)
    return _iso(due)


def _recurrence_has_clock_only_anchor(text: str, recurrence: str) -> bool:
    if recurrence in {"weekly", "monthly"} or re.fullmatch(r"every\s+\d{1,3}\s+(?:days|weeks|months)", recurrence):
        normalized = _normalize(text)
        return not bool(
            re.search(r"\b(?:heute|morgen|uebermorgen|naechsten|kommenden)\b", normalized)
            or RELATIVE_RE.search(normalized)
            or RELATIVE_TEXT_RE.search(normalized)
            or DAY_WORD_RE.search(normalized)
            or MONTH_DAY_RE.search(normalized)
            or MONTH_NAME_DATE_RE.search(normalized)
            or ISO_RE.search(normalized)
            or DATE_RE.search(normalized)
        )
    return False


def _initial_recurrence_due_with_time(now: datetime, recurrence: str, text: str) -> str:
    if recurrence == "weekly":
        base = now + timedelta(weeks=1)
    elif recurrence == "monthly":
        base = _add_calendar_months(now, 1)
    else:
        match = re.fullmatch(r"every\s+(?P<count>\d{1,3})\s+(?P<unit>days|weeks|months)", recurrence)
        if match is None:
            return ""
        count = int(match.group("count"))
        unit = match.group("unit")
        if unit == "days":
            base = now + timedelta(days=count)
        elif unit == "weeks":
            base = now + timedelta(weeks=count)
        else:
            base = _add_calendar_months(now, count)
    return _iso(_apply_explicit_time(base, text))


def _apply_explicit_time(value: datetime, text: str) -> datetime:
    marker = _time_marker_in_text(text)
    if marker is None:
        return value
    return value.replace(
        hour=marker[0],
        minute=marker[1],
        second=0,
        microsecond=0,
    )


def _has_invalid_explicit_time(text: str) -> bool:
    raw = str(text or "")
    for pattern, candidate_text in (
        (EXPLICIT_TIME_CANDIDATE_RE, raw),
        (DATE_TIME_CANDIDATE_RE, raw),
        (MONTH_NAME_DATE_RE, _normalize(raw)),
    ):
        match = pattern.search(candidate_text)
        if match is None:
            continue
        hour_text = match.group("hour")
        if hour_text is None:
            continue
        hour = int(hour_text)
        minute = int(match.group("minute") or 0)
        if hour > 23 or minute > 59:
            return True
    return False


def _date_match_is_after_subject_marker(text: str, match: re.Match[str]) -> bool:
    prefix = _normalize(str(text or "")[: match.start()])
    direct_date_marker = re.search(r"\ban(?:\s+den)?\s*$", prefix)
    if direct_date_marker:
        return _has_temporal_anchor(prefix[: direct_date_marker.start()])
    if not re.search(r"\ban\b", prefix):
        return False
    return not bool(re.match(r"\s*am\b", _normalize(match.group(0))))


def _has_temporal_anchor(text: str) -> bool:
    normalized = _normalize(text)
    return bool(
        re.search(r"\b(?:heute|morgen|uebermorgen|naechsten|kommenden|naechste|kommende)\b", normalized)
        or re.search(r"\b(?:naechste|kommende)\s+woche\b", normalized)
        or RELATIVE_RE.search(normalized)
        or RELATIVE_TEXT_RE.search(normalized)
        or TIME_RE.search(normalized)
        or DAY_WORD_RE.search(normalized)
        or MONTH_DAY_RE.search(normalized)
        or MONTH_NAME_DATE_RE.search(normalized)
        or ISO_RE.search(normalized)
        or DATE_RE.search(normalized)
    )


def _normalize_year(value: str | None, current_year: int) -> int:
    if not value:
        return current_year
    year = int(value)
    if year < 100:
        return 2000 + year
    return year


def _reminder_subject(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = ISO_RE.sub(
        lambda match: match.group(0) if _date_match_is_after_subject_marker(cleaned, match) else "",
        cleaned,
    )
    cleaned = MONTH_NAME_DATE_RE.sub(
        lambda match: match.group(0) if _date_match_is_after_subject_marker(cleaned, match) else "",
        cleaned,
    )
    cleaned = DATE_RE.sub(
        lambda match: match.group(0) if _date_match_is_after_subject_marker(cleaned, match) else "",
        cleaned,
    )
    cleaned = re.sub(r"(?i)\b(?:naechste|nächste|kommende)\s+woche\b", " ", cleaned)
    cleaned = re.sub(
        r"(?i)\b(?:fuer|für)\s+(?=(?:heute|morgen|uebermorgen|übermorgen|naechste|nächste|kommende)\b)",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"(?i)\ban\s+den\s+(?=(?:um|gegen|an|daran)\b|$)", " ", cleaned)
    cleaned = re.sub(
        r"(?i)\b("
        r"erinner(?:e|st|n)?\s+(?:mich|mi|uns)|"
        r"remind\s+(?:me|us)|"
        r"sag(?:e)?\s+(?:mir|uns)\s+(?:(?!\bbescheid\b).){0,80}\bbescheid|"
        r"denk(?:e)?(?:\s+bitte)?(?:\s+(?:fuer\s+)?(?:mich|uns))?"
        r")\b",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)\b(?:kannst|koenntest)\s+du\s+(?:mich|uns)\s+(?:bitte\s+)?"
        r"(?!irgendwann\b)(?:(?!\b(?:an|daran)\b).){0,80}\b(?:an|daran)\b\s+",
        lambda match: "daran " if re.search(r"(?i)\bdaran\b", match.group(0)) else "an ",
        cleaned,
    )
    cleaned = re.sub(r"(?i)\b(?:kannst|koenntest)\s+du\s+(?:mich|uns)\s+", "", cleaned)
    cleaned = re.sub(
        r"(?i)\bmach(?:e)?\s+(?:mich|uns)\s+(?:(?!\bauf\b).){0,80}\bauf\s+",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)\b(?:nicht\s+vergessen|vergiss\w*(?:\s+bitte)?\s+nicht)\s*,?\s*(?:mich|uns)\s+",
        "",
        cleaned,
    )
    cleaned = re.sub(r"(?i)\baufmerksam\b", " ", cleaned)
    cleaned = RECURRENCE_MARKER_RE.sub(" ", cleaned)
    cleaned = re.sub(r"(?i)\b(bit+e|bitte|please)\b", "", cleaned)
    cleaned = RELATIVE_TEXT_RE.sub("", cleaned)
    cleaned = RELATIVE_RE.sub("", cleaned)
    cleaned = TIME_RE.sub("", cleaned)
    cleaned = WRITTEN_TIME_RE.sub("", cleaned)
    cleaned = MONTH_DAY_RE.sub("", cleaned)
    cleaned = DAY_WORD_RE.sub("", cleaned)
    cleaned = re.sub(
        r"(?i)\b(heute|morgen|uebermorgen|übermorgen|naechsten|nächsten|kommenden|frueh|früh|morgens|vormittag|vormittags|mittag|mittags|nachmittag|nachmittags|abend|abends|nacht|nachts|um|gegen|uhr|am|daran|dran|an|dass)\b",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"(?i)\bzu\s+erinnern\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\b(?:erinnern|erinnerst|erinnere?)\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" \t\r\n.,:;!?-")
    if cleaned.casefold() in {
        "der",
        "die",
        "das",
        "den",
        "dem",
        "des",
        "ein",
        "eine",
        "einen",
        "einem",
        "einer",
        "eines",
    }:
        return "deinen Termin"
    return cleaned[:240] or "deinen Termin"


def _format_due_for_reply(due_at: str) -> str:
    try:
        parsed = datetime.fromisoformat(due_at)
    except ValueError:
        return f"am {due_at}"
    return f"am {parsed.strftime('%d.%m.%Y um %H:%M')}"


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat(timespec="seconds")


def _normalize(text: str) -> str:
    return (
        str(text or "")
        .casefold()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
