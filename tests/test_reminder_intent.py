from __future__ import annotations

from datetime import datetime, timezone

from TeeBotus.runtime.reminder_intent import parse_reminder_intent


def fixed_now() -> datetime:
    return datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)


def test_parse_reminder_with_tomorrow_time() -> None:
    intent = parse_reminder_intent("Erinnere mich morgen um 9 an den Zahnarzt", now=fixed_now())

    assert intent.is_request is True
    assert intent.missing_time is False
    assert intent.due_at == "2026-06-16T09:00:00+00:00"
    assert intent.subject == "den Zahnarzt"


def test_parse_reminder_with_relative_time_and_loose_wording() -> None:
    intent = parse_reminder_intent("Bitte denk in 30 Minuten dran Wasser zu trinken.", now=fixed_now())

    assert intent.is_request is True
    assert intent.due_at == "2026-06-15T12:30:00+00:00"
    assert intent.subject == "Wasser zu trinken"


def test_parse_reminder_without_time_asks_for_missing_time() -> None:
    intent = parse_reminder_intent("Sag mir bitte Bescheid wegen dem Termin", now=fixed_now())

    assert intent.is_request is True
    assert intent.missing_time is True
    assert intent.subject == "wegen dem Termin"


def test_parse_non_reminder_is_not_request() -> None:
    intent = parse_reminder_intent("Was denkst du ueber den Termin?", now=fixed_now())

    assert intent.is_request is False
