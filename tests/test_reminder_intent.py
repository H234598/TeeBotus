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
    direct_subject = parse_reminder_intent("Kannst du mich bitte an Punkt 3.4 erinnern?", now=fixed_now())
    daran_subject = parse_reminder_intent("Kannst du mich bitte daran erinnern, Wasser zu trinken?", now=fixed_now())

    assert intent.is_request is True
    assert intent.due_at == "2026-06-16T09:00:00+00:00"
    assert intent.subject == "den Zahnarzt"
    assert direct_subject.subject == "Punkt 3.4"
    assert daran_subject.subject == "Wasser zu trinken"


def test_parse_reminder_accepts_reverse_question_without_subject() -> None:
    intent = parse_reminder_intent("Kannst du mich morgen erinnern?", now=fixed_now())

    assert intent.is_request is True
    assert intent.due_at == "2026-06-16T09:00:00+00:00"
    assert intent.subject == "deinen Termin"


def test_parse_reminder_keeps_iso_date_inside_reverse_question_subject() -> None:
    intent = parse_reminder_intent(
        "Kannst du mich bitte in 2 Stunden an Version 2026-06-01 erinnern?",
        now=fixed_now(),
    )

    assert intent.due_at == "2026-06-15T14:00:00+00:00"
    assert intent.subject == "Version 2026-06-01"


def test_parse_reminder_subject_month_date_without_time_does_not_crash() -> None:
    intent = parse_reminder_intent(
        "Kannst du mich in 2 Stunden an 16. Maerz 2027 erinnern?",
        now=fixed_now(),
    )

    assert intent.due_at == "2026-06-15T14:00:00+00:00"
    assert intent.subject == "16. Maerz 2027"


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


def test_parse_reminder_accepts_written_relative_times() -> None:
    now = datetime(2026, 6, 15, 12, 34, tzinfo=timezone.utc)

    in_hour = parse_reminder_intent("Erinnere mich in einer Stunde an den Termin", now=now)
    half_hour = parse_reminder_intent("Erinnere mich in einer halben Stunde an den Termin", now=now)
    in_days = parse_reminder_intent("Erinnere mich in zwei Tagen um 9 an den Termin", now=now)

    assert (in_hour.due_at, in_hour.subject) == ("2026-06-15T13:34:00+00:00", "den Termin")
    assert (half_hour.due_at, half_hour.subject) == ("2026-06-15T13:04:00+00:00", "den Termin")
    assert in_days.due_at == "2026-06-17T09:00:00+00:00"


def test_parse_reminder_extracts_supported_recurrence_rules() -> None:
    now = datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc)

    daily = parse_reminder_intent("Erinnere mich jeden Tag um 9 an die Medikamente", now=now)
    weekly = parse_reminder_intent("Erinnere mich jeden Montag um 9 an die Therapie", now=now)
    every = parse_reminder_intent("Erinnere mich alle 2 Tage um 9 an Wasser", now=now)
    monthly = parse_reminder_intent("Erinnere mich monatlich am 1. um 10 an die Abrechnung", now=now)
    every_months = parse_reminder_intent("Erinnere mich alle 2 Monate am 1. um 10 an die Abrechnung", now=now)

    assert (daily.recurrence, daily.subject) == ("daily", "die Medikamente")
    assert (weekly.recurrence, weekly.subject) == ("weekly", "die Therapie")
    assert (every.recurrence, every.subject) == ("every 2 days", "Wasser")
    assert (monthly.recurrence, monthly.due_at, monthly.subject) == (
        "monthly",
        "2026-07-01T10:00:00+00:00",
        "die Abrechnung",
    )
    assert (every_months.recurrence, every_months.due_at) == ("every 2 months", "2026-07-01T10:00:00+00:00")


def test_parse_weekday_reminder_does_not_become_one_off_weekend_reminder() -> None:
    friday = parse_reminder_intent(
        "Erinnere mich jeden Werktag um 9 an die Medikamente",
        now=datetime(2026, 6, 19, 10, 0, tzinfo=timezone.utc),
    )
    saturday = parse_reminder_intent(
        "Erinnere mich jeden Wochentag um 9 an die Medikamente",
        now=datetime(2026, 6, 20, 8, 0, tzinfo=timezone.utc),
    )

    assert (friday.due_at, friday.recurrence, friday.subject) == (
        "2026-06-22T09:00:00+00:00",
        "weekdays",
        "die Medikamente",
    )
    assert (saturday.due_at, saturday.recurrence) == ("2026-06-22T09:00:00+00:00", "weekdays")


def test_parse_reminder_interval_recurrence_starts_from_now() -> None:
    now = datetime(2026, 6, 15, 12, 34, tzinfo=timezone.utc)

    hours = parse_reminder_intent("Erinnere mich alle 2 Stunden an Wasser", now=now)
    days = parse_reminder_intent("Erinnere mich alle 2 Tage an Wasser", now=now)

    assert (hours.due_at, hours.recurrence) == ("2026-06-15T14:34:00+00:00", "every 2 hours")
    assert (days.due_at, days.recurrence) == ("2026-06-17T12:34:00+00:00", "every 2 days")


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


def test_parse_reminder_supports_german_month_names_and_explicit_year() -> None:
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)

    next_may = parse_reminder_intent("Erinnere mich am 10. Mai um 14:30 an den Termin", now=now)
    march = parse_reminder_intent("Erinnere mich am 16. Maerz 2027 um 17:47 an Dr. Oliver", now=now)
    umlaut = parse_reminder_intent("Erinnere mich am 16. März 2027 um 17:47 an Dr. Oliver", now=now)

    assert (next_may.due_at, next_may.subject) == ("2027-05-10T14:30:00+00:00", "den Termin")
    assert (march.due_at, march.subject) == ("2027-03-16T17:47:00+00:00", "Dr. Oliver")
    assert umlaut.due_at == march.due_at


def test_parse_reminder_named_month_keeps_late_evening_hour() -> None:
    intent = parse_reminder_intent(
        "Erinnere mich am 31. Dezember um 23:59 an Silvester",
        now=fixed_now(),
    )

    assert intent.due_at == "2026-12-31T23:59:00+00:00"


def test_parse_reminder_named_month_rejects_out_of_range_hour() -> None:
    intent = parse_reminder_intent(
        "Erinnere mich am 31. Dezember um 25:00 an Silvester",
        now=fixed_now(),
    )

    assert intent.due_at == ""
    assert intent.missing_time is True


def test_parse_reminder_does_not_treat_decimal_subject_as_date() -> None:
    intent = parse_reminder_intent(
        "Erinnere mich morgen um 9 an 1.5 Liter Wasser",
        now=fixed_now(),
    )

    assert intent.due_at == "2026-06-16T09:00:00+00:00"
    assert intent.subject == "1.5 Liter Wasser"


def test_parse_reminder_does_not_treat_iso_subject_as_date() -> None:
    intent = parse_reminder_intent(
        "Erinnere mich morgen um 9 an Version 2026-06-01",
        now=fixed_now(),
    )

    assert intent.due_at == "2026-06-16T09:00:00+00:00"
    assert intent.subject == "Version 2026-06-01"


def test_parse_reminder_supports_trailing_dot_before_numeric_time() -> None:
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)

    with_year = parse_reminder_intent(
        "Erinnere mich am 16.03.2027. um 17:47 an Dr. Oliver",
        now=now,
    )
    without_year = parse_reminder_intent(
        "Erinnere mich am 16.03. um 17:47 an Dr. Oliver",
        now=now,
    )

    assert with_year.due_at == "2027-03-16T17:47:00+00:00"
    assert with_year.subject == "Dr. Oliver"
    assert without_year.due_at == "2027-03-16T17:47:00+00:00"
    assert without_year.subject == "Dr. Oliver"


def test_parse_reminder_rejects_invalid_named_month_date_without_fallback() -> None:
    intent = parse_reminder_intent("Erinnere mich am 31. Februar 2027 um 10 an den Termin", now=fixed_now())

    assert intent.is_request is True
    assert intent.missing_time is True
    assert intent.due_at == ""


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


def test_classic_monthly_day_28_is_not_inferred_as_month_end(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", "Depressionsbot")
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)

    maybe_queue_natural_reminder(
        account_store=account_store,
        account_id=account_id,
        instance_name="Depressionsbot",
        text="Erinnere mich monatlich am 28. um 10 an die Abrechnung",
        now=datetime(2026, 1, 29, 12, 0, tzinfo=timezone.utc),
    )

    item = account_store.read_proactive_outbox(account_id)[0]
    assert item["due_at"] == "2026-02-28T10:00:00+00:00"
    assert item["recurrence_anchor_day"] == 28
    assert item["recurrence_anchor_end_of_month"] is False


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
