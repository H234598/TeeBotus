from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading
import time

from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key
from TeeBotus.runtime.activity_profile import _trim_observations, contact_timing_decision, derive_activity_profile, record_account_activity
from TeeBotus.runtime.engine import TeeBotusEngine
from TeeBotus.runtime.events import IncomingEvent
from TeeBotus.runtime.proactive_agent import enable_proactive_agent, proactive_policy_decision, set_proactive_allowed_hours

LOCAL = timezone(timedelta(hours=2))


def store(tmp_path) -> AccountStore:
    return AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"a" * 32))


def event(identity: str, *, text: str = "Hallo", event_id: str = "signal:1") -> IncomingEvent:
    return IncomingEvent(
        event_id=event_id,
        instance="Depressionsbot",
        channel="signal",
        adapter_slot=1,
        account_id="",
        identity_key=identity,
        chat_id="+491",
        chat_type="private",
        sender_id=identity,
        sender_name="Signal User",
        text=text,
        message_ref="1",
    )


def set_identity_last_seen(account_store: AccountStore, identity: str, when: datetime) -> None:
    identities = account_store._load_identities()
    payload = identities[identity]
    timestamp = when.isoformat(timespec="seconds")
    payload["last_seen_at"] = timestamp
    payload["last_route"]["last_seen_at"] = timestamp
    identities[identity] = payload
    account_store._save_identities(identities)


def prepare_account(account_store: AccountStore) -> tuple[str, str]:
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    enable_proactive_agent(account_store, account_id, categories=("reminder",))
    set_proactive_allowed_hours(account_store, account_id, 0, 23)
    return identity, account_id


def record_hours(account_store: AccountStore, account_id: str, identity: str, values: list[tuple[int, int, int]]) -> None:
    for day, hour, minute in values:
        record_account_activity(
            account_store,
            account_id,
            event(
                identity,
                text="Ich schreibe gerade etwas laenger ueber meinen Tag.",
                event_id=f"signal:{day}:{hour}:{minute}",
            ),
            now=datetime(2026, 6, day, hour, minute, tzinfo=LOCAL),
        )


def test_contact_timing_learns_weekday_wake_and_quiet_hours(tmp_path) -> None:
    account_store = store(tmp_path)
    identity, account_id = prepare_account(account_store)
    record_hours(account_store, account_id, identity, [(8, 9, 0), (9, 9, 20), (10, 10, 0), (11, 9, 10), (12, 10, 15), (15, 9, 30)])
    set_identity_last_seen(account_store, identity, datetime(2026, 6, 15, 8, 0, tzinfo=LOCAL))

    allowed = contact_timing_decision(account_store, account_id, now=datetime(2026, 6, 15, 9, 30, tzinfo=LOCAL))
    quiet = contact_timing_decision(account_store, account_id, now=datetime(2026, 6, 15, 22, 0, tzinfo=LOCAL))

    assert allowed.allowed is True
    assert allowed.reason == "adaptive_contact_hour"
    assert quiet.allowed is False
    assert quiet.reason == "outside_adaptive_contact_window"


def test_engine_records_private_activity_observations(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", "Depressionsbot")
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="signal-user")
    account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    engine = TeeBotusEngine(account_store=account_store)

    engine.process(event(identity, text="/status"))

    account_id = account_store.get_account_for_identity(identity) or ""
    observations = account_store.read_agent_state(account_id)["activity_profile"]["observations"]
    assert len(observations) == 1
    assert observations[0]["channel"] == "signal"
    assert observations[0]["text_length"] == len("/status")


def test_record_account_activity_ignores_replayed_event(tmp_path) -> None:
    account_store = store(tmp_path)
    identity, account_id = prepare_account(account_store)
    incoming = event(identity, event_id="signal:replayed")

    record_account_activity(
        account_store,
        account_id,
        incoming,
        now=datetime(2026, 6, 15, 9, 0, tzinfo=LOCAL),
    )
    record_account_activity(
        account_store,
        account_id,
        incoming,
        now=datetime(2026, 6, 15, 10, 0, tzinfo=LOCAL),
    )

    observations = account_store.read_agent_state(account_id)["activity_profile"]["observations"]
    assert len(observations) == 1
    assert observations[0]["event_id"] == "signal:replayed"
    assert observations[0]["at"] == "2026-06-15T09:00:00+02:00"


def test_record_account_activity_serializes_concurrent_state_updates(tmp_path, monkeypatch) -> None:
    root = tmp_path / "accounts"
    first = store(tmp_path)
    second = AccountStore(root, "Depressionsbot", StaticSecretProvider(b"a" * 32))
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = first.resolve_or_create_account(identity)
    original_read = AccountStore.read_agent_state
    state = {"active": 0, "maximum": 0}
    state_lock = threading.Lock()
    errors: list[BaseException] = []

    def slow_read(account_store, current_account_id):
        with state_lock:
            state["active"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
        try:
            time.sleep(0.03)
            return original_read(account_store, current_account_id)
        finally:
            with state_lock:
                state["active"] -= 1

    monkeypatch.setattr(AccountStore, "read_agent_state", slow_read)

    def record(account_store, hour: int) -> None:
        try:
            record_account_activity(
                account_store,
                account_id,
                event(identity, event_id=f"signal:{hour}"),
                now=datetime(2026, 6, 15, hour, 0, tzinfo=LOCAL),
            )
        except BaseException as exc:  # pragma: no cover - only used to report thread failures.
            errors.append(exc)

    threads = [
        threading.Thread(target=record, args=(first, 9)),
        threading.Thread(target=record, args=(second, 10)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    observations = first.read_agent_state(account_id)["activity_profile"]["observations"]
    assert errors == []
    assert state["maximum"] == 1
    assert {observation["at"] for observation in observations} == {
        "2026-06-15T09:00:00+02:00",
        "2026-06-15T10:00:00+02:00",
    }


def test_contact_timing_reads_profile_under_account_lock(tmp_path, monkeypatch) -> None:
    first = store(tmp_path)
    second = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"a" * 32))
    identity = signal_identity_key(source_uuid="timing-lock")
    account_id = first.resolve_or_create_account(identity)
    state = {"active": 0, "maximum": 0}
    state_lock = threading.Lock()
    errors: list[BaseException] = []
    original_read = AccountStore.read_agent_state

    def slow_read(account_store, current_account_id):
        with state_lock:
            state["active"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
        try:
            time.sleep(0.03)
            return original_read(account_store, current_account_id)
        finally:
            with state_lock:
                state["active"] -= 1

    monkeypatch.setattr(AccountStore, "read_agent_state", slow_read)

    def record() -> None:
        try:
            record_account_activity(
                first,
                account_id,
                event(identity),
                now=datetime(2026, 6, 15, 9, 0, tzinfo=LOCAL),
            )
        except BaseException as exc:  # pragma: no cover - only used to report thread failures.
            errors.append(exc)

    def decide() -> None:
        try:
            contact_timing_decision(
                second,
                account_id,
                now=datetime(2026, 6, 15, 9, 0, tzinfo=LOCAL),
            )
        except BaseException as exc:  # pragma: no cover - only used to report thread failures.
            errors.append(exc)

    threads = [threading.Thread(target=record), threading.Thread(target=decide)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert state["maximum"] == 1


def test_activity_profile_ignores_observations_older_than_history_window() -> None:
    now = datetime(2026, 6, 15, 12, 0, tzinfo=LOCAL)
    observations = [
        {
            "at": f"2026-01-{day:02d}T12:00:00+02:00",
            "text_length": 40,
            "attachment_count": 0,
        }
        for day in range(1, 7)
    ]

    profile = derive_activity_profile(observations, now=now)

    assert profile["sufficient_data"] is False
    assert profile["observation_count"] == 0


def test_activity_profile_trim_keeps_newest_timestamps_not_append_order() -> None:
    now = datetime(2026, 6, 15, 12, 0, tzinfo=LOCAL)
    newest = now - timedelta(minutes=1)
    observations = [{"at": newest.isoformat(timespec="seconds")}]
    observations.extend(
        {"at": (now - timedelta(hours=index)).isoformat(timespec="seconds")}
        for index in range(1, 1001)
    )

    trimmed = _trim_observations(observations, now=now)

    timestamps = {observation["at"] for observation in trimmed}
    assert len(trimmed) == 1000
    assert newest.isoformat(timespec="seconds") in timestamps
    assert (now - timedelta(hours=1000)).isoformat(timespec="seconds") not in timestamps


def test_record_account_activity_does_not_move_profile_timestamp_backwards(tmp_path) -> None:
    account_store = store(tmp_path)
    identity, account_id = prepare_account(account_store)
    record_account_activity(
        account_store,
        account_id,
        event(identity),
        now=datetime(2026, 6, 15, 10, 0, tzinfo=LOCAL),
    )
    record_account_activity(
        account_store,
        account_id,
        event(identity),
        now=datetime(2026, 6, 15, 9, 0, tzinfo=LOCAL),
    )

    profile = account_store.read_agent_state(account_id)["activity_profile"]
    assert profile["updated_at"] == "2026-06-15T10:00:00+02:00"


def test_activity_profile_clamps_corrupt_negative_text_lengths() -> None:
    now = datetime(2026, 6, 15, 12, 0, tzinfo=LOCAL)
    observations = [
        {
            "at": (now - timedelta(hours=index)).isoformat(timespec="seconds"),
            "text_length": -100000,
            "attachment_count": -1,
        }
        for index in range(6)
    ]

    profile = derive_activity_profile(observations, now=now)

    assert profile["sufficient_data"] is True
    assert profile["observation_count"] == 6


def test_contact_timing_uses_weekend_profile_for_irregular_weekends(tmp_path) -> None:
    account_store = store(tmp_path)
    identity, account_id = prepare_account(account_store)
    record_hours(
        account_store,
        account_id,
        identity,
        [
            (8, 9, 0),
            (9, 9, 0),
            (10, 9, 0),
            (11, 9, 0),
            (6, 13, 0),
            (7, 13, 15),
            (13, 13, 0),
            (14, 13, 15),
            (20, 14, 0),
        ],
    )
    set_identity_last_seen(account_store, identity, datetime(2026, 6, 21, 8, 0, tzinfo=LOCAL))

    weekend_late = contact_timing_decision(account_store, account_id, now=datetime(2026, 6, 21, 13, 30, tzinfo=LOCAL))
    weekend_early = contact_timing_decision(account_store, account_id, now=datetime(2026, 6, 21, 9, 0, tzinfo=LOCAL))

    assert weekend_late.allowed is True
    assert weekend_early.allowed is False


def test_contact_timing_keeps_separate_activity_blocks_from_opening_whole_day(tmp_path) -> None:
    account_store = store(tmp_path)
    identity, account_id = prepare_account(account_store)
    record_hours(
        account_store,
        account_id,
        identity,
        [
            (8, 9, 0),
            (9, 9, 10),
            (10, 9, 20),
            (11, 21, 0),
            (12, 21, 10),
            (15, 21, 20),
        ],
    )

    morning = contact_timing_decision(account_store, account_id, now=datetime(2026, 6, 16, 9, 30, tzinfo=LOCAL))
    noon = contact_timing_decision(account_store, account_id, now=datetime(2026, 6, 16, 14, 0, tzinfo=LOCAL))
    evening = contact_timing_decision(account_store, account_id, now=datetime(2026, 6, 16, 21, 30, tzinfo=LOCAL))

    assert morning.allowed is True
    assert evening.allowed is True
    assert noon.allowed is False
    assert noon.reason == "outside_adaptive_contact_window"
    day_profile = noon.profile["profiles"]["weekday"]
    assert 14 in day_profile["quiet_hours"]
    assert len(day_profile["activity_blocks"]) >= 2


def test_activity_profile_derives_sleep_hours_from_longest_quiet_block(tmp_path) -> None:
    account_store = store(tmp_path)
    identity, account_id = prepare_account(account_store)
    record_hours(account_store, account_id, identity, [(8, 8, 30), (9, 9, 0), (10, 12, 0), (11, 17, 0), (12, 18, 0), (15, 19, 0)])

    decision = contact_timing_decision(account_store, account_id, now=datetime(2026, 6, 16, 3, 0, tzinfo=LOCAL))

    assert decision.allowed is False
    sleep_hours = decision.profile["profiles"]["weekday"]["sleep_hours"]
    assert 2 in sleep_hours
    assert 3 in sleep_hours


def test_proactive_policy_respects_adaptive_contact_window_and_recent_online_override(tmp_path) -> None:
    account_store = store(tmp_path)
    identity, account_id = prepare_account(account_store)
    record_hours(account_store, account_id, identity, [(8, 9, 0), (9, 9, 10), (10, 9, 20), (11, 10, 0), (12, 9, 40), (15, 10, 10)])
    set_identity_last_seen(account_store, identity, datetime(2026, 6, 15, 8, 0, tzinfo=LOCAL))

    blocked = proactive_policy_decision(account_store, account_id, category="reminder", now=datetime(2026, 6, 15, 22, 0, tzinfo=LOCAL))
    set_identity_last_seen(account_store, identity, datetime(2026, 6, 15, 10, 58, tzinfo=LOCAL))
    recent = proactive_policy_decision(account_store, account_id, category="reminder", now=datetime(2026, 6, 15, 11, 0, tzinfo=LOCAL))
    set_identity_last_seen(account_store, identity, datetime(2026, 6, 15, 21, 58, tzinfo=LOCAL))
    night_recent = proactive_policy_decision(account_store, account_id, category="reminder", now=datetime(2026, 6, 15, 22, 0, tzinfo=LOCAL))

    assert blocked.allowed is False
    assert blocked.reason == "outside_adaptive_contact_window"
    assert recent.allowed is True
    assert recent.reason == "allowed"
    assert night_recent.allowed is False
