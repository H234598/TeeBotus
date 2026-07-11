from __future__ import annotations

from datetime import datetime, timedelta, timezone

from TeeBotus.decisions.reminder import ReminderDecision
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key
from TeeBotus.runtime.reminder_intent import maybe_queue_natural_reminder, parse_reminder_intent


def store(tmp_path) -> AccountStore:
    return AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"r" * 32))


def fixed_now() -> datetime:
    return datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)


def test_parse_reminder_with_tomorrow_time() -> None:
    intent = parse_reminder_intent("Erinnere mich morgen um 9 an den Zahnarzt", now=fixed_now())

    assert intent.is_request is True
    assert intent.missing_time is False
    assert intent.due_at == "2026-06-16T09:00:00+00:00"
    assert intent.subject == "den Zahnarzt"


def test_parse_reminder_accepts_reverse_question_wording() -> None:
    intent = parse_reminder_intent("Kannst du mich morgen an den Zahnarzt erinnern?", now=fixed_now())

    assert intent.is_request is True
    assert intent.due_at == "2026-06-16T09:00:00+00:00"
    assert intent.subject == "den Zahnarzt"


def test_parse_reminder_accepts_reverse_question_without_subject() -> None:
    intent = parse_reminder_intent("Kannst du mich morgen erinnern?", now=fixed_now())

    assert intent.is_request is True
    assert intent.due_at == "2026-06-16T09:00:00+00:00"
    assert intent.subject == "deinen Termin"


def test_parse_reminder_with_relative_time_and_loose_wording() -> None:
    intent = parse_reminder_intent("Bitte denk in 30 Minuten dran Wasser zu trinken.", now=fixed_now())

    assert intent.is_request is True
    assert intent.due_at == "2026-06-15T12:30:00+00:00"
    assert intent.subject == "Wasser zu trinken"


def test_parse_reminder_accepts_daran_imperative() -> None:
    intent = parse_reminder_intent(
        "Denk bitte daran, morgen um 9 den Antrag abzuschicken",
        now=fixed_now(),
    )

    assert intent.is_request is True
    assert intent.due_at == "2026-06-16T09:00:00+00:00"
    assert intent.subject == "den Antrag abzuschicken"


def test_parse_reminder_relative_days_and_weeks_keep_explicit_clock() -> None:
    now = datetime(2026, 6, 15, 12, 34, tzinfo=timezone.utc)

    in_days = parse_reminder_intent("Erinnere mich in 2 Tagen um 9 an den Termin", now=now)
    in_weeks = parse_reminder_intent("Erinnere mich in 2 Wochen gegen 8:15 an den Termin", now=now)

    assert in_days.due_at == "2026-06-17T09:00:00+00:00"
    assert in_weeks.due_at == "2026-06-29T08:15:00+00:00"


def test_parse_reminder_extracts_supported_recurrence_rules() -> None:
    now = datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc)

    daily = parse_reminder_intent("Erinnere mich jeden Tag um 9 an die Medikamente", now=now)
    weekly = parse_reminder_intent("Erinnere mich jeden Montag um 9 an die Therapie", now=now)
    every = parse_reminder_intent("Erinnere mich alle 2 Tage um 9 an Wasser", now=now)
    monthly = parse_reminder_intent("Erinnere mich monatlich am 1. um 10 an die Abrechnung", now=now)

    assert (daily.recurrence, daily.subject) == ("daily", "die Medikamente")
    assert (weekly.recurrence, weekly.subject) == ("weekly", "die Therapie")
    assert (every.recurrence, every.subject) == ("every 2 days", "Wasser")
    assert (monthly.recurrence, monthly.due_at, monthly.subject) == (
        "monthly",
        "2026-07-01T10:00:00+00:00",
        "die Abrechnung",
    )


def test_parse_reminder_default_now_uses_configured_local_timezone(monkeypatch) -> None:
    local = timezone(timedelta(hours=2))
    monkeypatch.setattr(
        "TeeBotus.runtime.reminder_intent.local_now",
        lambda: datetime(2026, 6, 15, 12, tzinfo=local),
    )

    intent = parse_reminder_intent("Erinnere mich morgen um 9 an den Termin")

    assert intent.due_at == "2026-06-16T09:00:00+02:00"


def test_parse_reminder_weekday_can_target_later_today() -> None:
    now = datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc)

    intent = parse_reminder_intent("Erinnere mich am Montag um 9 an den Termin", now=now)

    assert intent.due_at == "2026-06-15T09:00:00+00:00"


def test_parse_reminder_next_weekday_skips_current_day() -> None:
    now = datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc)

    next_week = parse_reminder_intent("Erinnere mich nächsten Montag um 9 an die Therapie", now=now)
    coming_week = parse_reminder_intent("Erinnere mich am kommenden Montag um 9 an die Therapie", now=now)

    assert next_week.due_at == "2026-06-22T09:00:00+00:00"
    assert coming_week.due_at == "2026-06-22T09:00:00+00:00"
    assert next_week.subject == "die Therapie"
    assert coming_week.subject == "die Therapie"


def test_parse_reminder_date_without_year_rolls_to_next_occurrence() -> None:
    intent = parse_reminder_intent(
        "Erinnere mich am 01.01. um 9 an den Geburtstag",
        now=datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc),
    )

    assert intent.due_at == "2027-01-01T09:00:00+00:00"


def test_parse_reminder_does_not_queue_past_today_time() -> None:
    intent = parse_reminder_intent(
        "Erinnere mich heute um 9 an den Termin",
        now=datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc),
    )

    assert intent.missing_time is True
    assert intent.due_at == ""


def test_parse_reminder_rejects_invalid_clock_without_raising() -> None:
    for text in (
        "Erinnere mich morgen um 25 an den Termin",
        "Erinnere mich am Montag um 25 an den Termin",
        "Erinnere mich um 9:61 an den Termin",
        "Erinnere mich am 2026-06-16T25:00 an den Termin",
        "Erinnere mich am 16.06.2026 25:00 an den Termin",
    ):
        intent = parse_reminder_intent(text, now=fixed_now())

        assert intent.is_request is True
        assert intent.missing_time is True
        assert intent.due_at == ""


def test_parse_reminder_without_time_asks_for_missing_time() -> None:
    intent = parse_reminder_intent("Sag mir bitte Bescheid wegen dem Termin", now=fixed_now())

    assert intent.is_request is True
    assert intent.missing_time is True
    assert intent.subject == "wegen dem Termin"


def test_parse_non_reminder_is_not_request() -> None:
    intent = parse_reminder_intent("Was denkst du ueber den Termin?", now=fixed_now())

    assert intent.is_request is False


def test_structured_reminder_fallback_can_queue_natural_request(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", "Depressionsbot")
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    calls = []

    def fake_runner(prompt, schema):
        calls.append((prompt, schema))
        return ReminderDecision(
            should_create=True,
            text="die Unterlagen mitnehmen",
            datetime_iso="2026-06-16T08:30:00+00:00",
            recurrence=None,
            confidence=0.86,
        )

    reply = maybe_queue_natural_reminder(
        account_store=account_store,
        account_id=account_id,
        instance_name="Depressionsbot",
        text="Kannst du mich morgen frueh wegen der Unterlagen anstupsen?",
        now=fixed_now(),
        structured_decision_runner=fake_runner,
    )

    assert reply == "Okay, ich erinnere dich am 16.06.2026 um 08:30: die Unterlagen mitnehmen"
    assert calls and calls[0][1] is ReminderDecision
    queued = account_store.read_proactive_outbox(account_id)
    assert queued[0]["planner"]["source"] == "structured_reminder_decision"
    assert queued[0]["due_at"] == "2026-06-16T08:30:00+00:00"


def test_classic_recurring_reminder_persists_recurrence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", "Depressionsbot")
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)

    reply = maybe_queue_natural_reminder(
        account_store=account_store,
        account_id=account_id,
        instance_name="Depressionsbot",
        text="Erinnere mich jeden Montag um 9 an die Therapie",
        now=datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc),
    )

    assert reply == "Okay, ich erinnere dich am 15.06.2026 um 09:00: die Therapie"
    queued = account_store.read_proactive_outbox(account_id)
    assert queued[0]["recurrence"] == "weekly"


def test_structured_reminder_fallback_interprets_naive_datetime_as_configured_local_time(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", "Depressionsbot")
    monkeypatch.setattr(
        "TeeBotus.runtime.reminder_intent.configured_timezone",
        lambda: timezone(timedelta(hours=2)),
    )
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)

    prompts = []

    def fake_runner(prompt, _schema):
        prompts.append(prompt)
        return ReminderDecision(
            should_create=True,
            text="die Unterlagen mitnehmen",
            datetime_iso="2026-06-16T08:30:00",
            confidence=0.86,
        )

    reply = maybe_queue_natural_reminder(
        account_store=account_store,
        account_id=account_id,
        instance_name="Depressionsbot",
        text="Kannst du mich morgen wegen der Unterlagen anstupsen?",
        now=fixed_now(),
        structured_decision_runner=fake_runner,
    )

    assert reply == "Okay, ich erinnere dich am 16.06.2026 um 08:30: die Unterlagen mitnehmen"
    assert "Aktuelle lokale Zeit: 2026-06-15T14:00:00+02:00" in prompts[0]
    assert account_store.read_proactive_outbox(account_id)[0]["due_at"] == "2026-06-16T08:30:00+02:00"


def test_structured_reminder_fallback_does_not_queue_past_model_datetime(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", "Depressionsbot")
    monkeypatch.setattr(
        "TeeBotus.runtime.reminder_intent.configured_timezone",
        lambda: timezone(timedelta(hours=2)),
    )
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)

    reply = maybe_queue_natural_reminder(
        account_store=account_store,
        account_id=account_id,
        instance_name="Depressionsbot",
        text="Kannst du mich wegen der Unterlagen anstupsen?",
        now=fixed_now(),
        structured_decision_runner=lambda _prompt, _schema: ReminderDecision(
            should_create=True,
            text="die Unterlagen mitnehmen",
            datetime_iso="2026-06-15T11:00:00",
            confidence=0.86,
        ),
    )

    assert reply == "Woran und wann soll ich dich erinnern? Beispiel: Erinnere mich morgen um 9 an den Termin."
    assert account_store.read_proactive_outbox(account_id) == []


def test_structured_reminder_fallback_preserves_recurrence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", "Depressionsbot")
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)

    reply = maybe_queue_natural_reminder(
        account_store=account_store,
        account_id=account_id,
        instance_name="Depressionsbot",
        text="Stups mich bitte jeden Tag wegen Wasser an.",
        now=fixed_now(),
        structured_decision_runner=lambda _prompt, _schema: ReminderDecision(
            should_create=True,
            text="Wasser trinken",
            datetime_iso="2026-06-16T08:30:00+00:00",
            recurrence="daily",
            confidence=0.86,
        ),
    )

    assert reply == "Okay, ich erinnere dich am 16.06.2026 um 08:30: Wasser trinken"
    queued = account_store.read_proactive_outbox(account_id)
    assert queued[0]["user_requested_reminder"] is True
    assert queued[0]["recurrence"] == "daily"
    assert queued[0]["planner"]["recurrence"] == "daily"


def test_structured_reminder_fallback_ignores_low_confidence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", "Depressionsbot")
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)

    reply = maybe_queue_natural_reminder(
        account_store=account_store,
        account_id=account_id,
        instance_name="Depressionsbot",
        text="Vielleicht irgendwann mal an Papier denken.",
        now=fixed_now(),
        structured_decision_runner=lambda _prompt, _schema: {
            "should_create": True,
            "text": "Papier",
            "datetime_iso": "2026-06-16T08:30:00+00:00",
            "confidence": 0.3,
        },
    )

    assert reply is None
    assert account_store.read_proactive_outbox(account_id) == []


def test_structured_reminder_fallback_ignores_invalid_datetime_payload(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", "Depressionsbot")
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)

    reply = maybe_queue_natural_reminder(
        account_store=account_store,
        account_id=account_id,
        instance_name="Depressionsbot",
        text="Kannst du mich irgendwann daran erinnern?",
        now=fixed_now(),
        structured_decision_runner=lambda _prompt, _schema: {
            "should_create": True,
            "text": "Termin",
            "datetime_iso": "morgen um acht",
            "confidence": 0.91,
        },
    )

    assert reply is None
    assert account_store.read_proactive_outbox(account_id) == []
