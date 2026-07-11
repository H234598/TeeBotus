from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
from TeeBotus.runtime.timezone import local_now

StructuredReminderRunner = Callable[[str, type[Any]], Any]


@dataclass(frozen=True)
class ReminderIntent:
    is_request: bool
    due_at: str = ""
    subject: str = ""
    recurrence: str = ""
    missing_time: bool = False
    source: str = "classic"


REMINDER_REQUEST_RE = re.compile(
    r"\b("
    r"erinner(?:e|st|n)?\s+(?:mich|mi|uns)|"
    r"erinnere?\s+(?:mich|mi|uns)|"
    r"denk(?:e)?(?:\s+bitte)?(?:\s+(?:fuer\s+)?(?:mich|uns))?(?:\s+.{0,80}?)?\s+dran|"
    r"sag(?:e)?\s+(?:mir|uns)\s+(?:bitte\s+)?bescheid|"
    r"remind\s+(?:me|us)|"
    r"(?:kannst|koenntest)\s+du\s+(?:mich|uns)\s+(?:bitte\s+)?(?!irgendwann\b)"
    r"(?:(?!\b(?:an|daran)\b).){0,80}\b(?:an|daran)\b\s+.{1,120}\berinner(?:n|en)?"
    r")\b",
    re.IGNORECASE,
)

TIME_RE = re.compile(r"\b(?:um|gegen)\s+(?P<hour>[0-2]?\d)(?::(?P<minute>[0-5]\d))?\s*(?:uhr)?\b", re.IGNORECASE)
RELATIVE_RE = re.compile(
    r"\bin\s+(?P<count>\d{1,3})\s*(?P<unit>min(?:ute)?n?|minuten?|std|stunden?|h|tage?n?|wochen?)\b",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"\b(?:am\s+)?(?P<day>[0-3]?\d)[.](?P<month>[01]?\d)(?:[.](?P<year>\d{2,4}))?"
    r"(?:\s+(?:um|gegen)?\s*(?P<hour>[0-2]?\d)(?::(?P<minute>[0-5]\d))?\s*(?:uhr)?)?",
    re.IGNORECASE,
)
ISO_RE = re.compile(
    r"\b(?P<year>20\d{2})-(?P<month>[01]\d)-(?P<day>[0-3]\d)"
    r"(?:[T\s](?P<hour>[0-2]\d):(?P<minute>[0-5]\d))?",
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
DAY_WORD_RE = re.compile(
    r"\b(?P<day>montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)"
    r"(?:\s+(?:um|gegen)\s+(?P<hour>[0-2]?\d)(?::(?P<minute>[0-5]\d))?\s*(?:uhr)?)?",
    re.IGNORECASE,
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
    intent = parse_reminder_intent(text, now=now)
    if not intent.is_request and structured_decision_runner is not None:
        intent = _structured_reminder_intent(text, structured_decision_runner=structured_decision_runner)
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
    if not raw or not REMINDER_REQUEST_RE.search(_normalize(raw)):
        return ReminderIntent(False)
    resolved_now = now or local_now()
    due_at = _parse_due_at(raw, resolved_now)
    subject = _reminder_subject(raw)
    return ReminderIntent(True, due_at=due_at, subject=subject, missing_time=not bool(due_at))


def _structured_reminder_intent(text: str, *, structured_decision_runner: StructuredReminderRunner) -> ReminderIntent:
    raw = str(text or "").strip()
    if not raw or raw.startswith("/"):
        return ReminderIntent(False)
    try:
        payload = structured_decision_runner(_structured_reminder_prompt(raw), ReminderDecision)
        decision = parse_reminder_decision(payload)
    except (TypeError, ValueError, ValidationError):
        return ReminderIntent(False)
    if not decision.should_create or decision.confidence < 0.7:
        return ReminderIntent(False)
    subject = decision.text.strip() or "deinen Termin"
    if not decision.datetime_iso:
        return ReminderIntent(True, subject=subject, recurrence=str(decision.recurrence or "").strip(), missing_time=True, source="model")
    try:
        datetime.fromisoformat(decision.datetime_iso)
    except ValueError:
        return ReminderIntent(True, subject=subject, recurrence=str(decision.recurrence or "").strip(), missing_time=True, source="model")
    return ReminderIntent(True, due_at=decision.datetime_iso, subject=subject[:240], recurrence=str(decision.recurrence or "").strip(), missing_time=False, source="model")


def _structured_reminder_prompt(text: str) -> str:
    return (
        "Pruefe, ob die natuerliche Nachricht eine Bitte ist, eine Erinnerung fuer den User anzulegen. "
        "Antworte ausschliesslich als JSON fuer ReminderDecision. Lege nur User-gewuenschte Erinnerungen an; "
        "keine allgemeinen Fragen, keine Bot-Aufgaben ohne Reminderwunsch.\n\n"
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


def _parse_due_at(text: str, now: datetime) -> str:
    normalized_now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    relative = RELATIVE_RE.search(_normalize(text))
    if relative:
        count = int(relative.group("count"))
        unit = relative.group("unit").casefold()
        if unit.startswith("min"):
            return _iso(normalized_now + timedelta(minutes=count))
        if unit in {"h", "std"} or unit.startswith("stunde"):
            return _iso(normalized_now + timedelta(hours=count))
        if unit.startswith("tag"):
            return _iso(normalized_now + timedelta(days=count))
        if unit.startswith("woche"):
            return _iso(normalized_now + timedelta(weeks=count))
    iso = ISO_RE.search(text)
    if iso:
        return _build_datetime(
            normalized_now,
            int(iso.group("year")),
            int(iso.group("month")),
            int(iso.group("day")),
            int(iso.group("hour") or 9),
            int(iso.group("minute") or 0),
        )
    date = DATE_RE.search(text)
    if date:
        year = _normalize_year(date.group("year"), normalized_now.year)
        return _build_datetime(
            normalized_now,
            year,
            int(date.group("month")),
            int(date.group("day")),
            int(date.group("hour") or 9),
            int(date.group("minute") or 0),
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
        hour = int(weekday.group("hour") or 9)
        minute = int(weekday.group("minute") or 0)
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


def _build_datetime(now: datetime, year: int, month: int, day: int, hour: int, minute: int) -> str:
    try:
        due = now.replace(year=year, month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
    except ValueError:
        return ""
    if due <= now:
        return ""
    return _iso(due)


def _time_in_text(text: str, *, default_hour: int) -> tuple[int, int]:
    match = TIME_RE.search(text)
    if not match:
        return default_hour, 0
    return int(match.group("hour")), int(match.group("minute") or 0)


def _normalize_year(value: str | None, current_year: int) -> int:
    if not value:
        return current_year
    year = int(value)
    if year < 100:
        return 2000 + year
    return year


def _reminder_subject(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(
        r"(?i)\b("
        r"erinner(?:e|st|n)?\s+(?:mich|mi|uns)|"
        r"remind\s+(?:me|us)|"
        r"sag(?:e)?\s+(?:mir|uns)\s+(?:bitte\s+)?bescheid|"
        r"denk(?:e)?(?:\s+bitte)?(?:\s+(?:fuer\s+)?(?:mich|uns))?"
        r")\b",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)\b(?:kannst|koenntest)\s+du\s+(?:mich|uns)\s+(?:bitte\s+)?"
        r"(?!irgendwann\b)(?:(?!\b(?:an|daran)\b).){0,80}\b(?:an|daran)\b\s+",
        "",
        cleaned,
    )
    cleaned = re.sub(r"(?i)\b(bit+e|bitte|please)\b", "", cleaned)
    cleaned = RELATIVE_RE.sub("", cleaned)
    cleaned = TIME_RE.sub("", cleaned)
    cleaned = ISO_RE.sub("", cleaned)
    cleaned = DATE_RE.sub("", cleaned)
    cleaned = DAY_WORD_RE.sub("", cleaned)
    cleaned = re.sub(r"(?i)\b(heute|morgen|uebermorgen|übermorgen|um|gegen|uhr|daran|dran|an|dass)\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\b(?:erinnern|erinnerst|erinnere?)\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,:;!?-")
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
