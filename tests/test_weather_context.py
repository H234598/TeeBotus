from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import time

from TeeBotus.instructions import BotInstructions
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key
from TeeBotus.runtime.engine import TeeBotusEngine
from TeeBotus.runtime.events import IncomingEvent
from TeeBotus.runtime.weather_context import extract_residence_city, update_city_and_weather_context, weather_context_text


def store(tmp_path) -> AccountStore:
    return AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"w" * 32))


def event(identity: str, text: str) -> IncomingEvent:
    return IncomingEvent(
        event_id="signal:1",
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


def prepare_account(account_store: AccountStore) -> tuple[str, str]:
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    return identity, account_id


def test_extract_residence_city_from_common_german_phrases() -> None:
    assert extract_residence_city("Ich wohne in Berlin und bin heute muede.") == "Berlin"
    assert extract_residence_city("Ich lebe jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist München.") == "München"
    assert extract_residence_city("Ich komme aus Hamburg, aber bin unterwegs.") == ""


def test_extract_residence_city_rejects_negated_or_non_city_phrases() -> None:
    for text in (
        "Ich wohne in keiner Stadt, sondern auf dem Land.",
        "Ich wohne bei meiner Mutter.",
        "Mein Wohnort ist nicht Berlin.",
        "Ich wohne in Berlin nicht mehr.",
    ):
        assert extract_residence_city(text) == ""


def test_extract_residence_city_prefers_explicit_current_residence_after_origin() -> None:
    assert extract_residence_city("Ich komme aus Deutschland und lebe jetzt in Berlin.") == "Berlin"


def test_weather_context_stores_city_memory_and_rate_limits_checks(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)
    calls: list[str] = []

    def provider(city: str) -> str:
        calls.append(city)
        return f"{city}: 12 C, trocken"

    first = update_city_and_weather_context(
        account_store,
        account_id,
        "Ich wohne in Berlin.",
        now=datetime(2026, 6, 15, 9, tzinfo=timezone.utc),
        provider=provider,
    )
    second = update_city_and_weather_context(
        account_store,
        account_id,
        "Hallo nochmal.",
        now=datetime(2026, 6, 15, 10, tzinfo=timezone.utc),
        provider=provider,
    )
    third = update_city_and_weather_context(
        account_store,
        account_id,
        "Hallo nach zwei Stunden.",
        now=datetime(2026, 6, 15, 11, 1, tzinfo=timezone.utc),
        provider=provider,
    )

    assert first.checked is True
    assert second.skipped_reason == "rate_limited"
    assert third.checked is True
    assert calls == ["Berlin", "Berlin"]
    state = account_store.read_agent_state(account_id)
    assert state["weather_context"]["city"] == "Berlin"
    assert "Berlin: 12 C" in weather_context_text(account_store, account_id)
    memories = account_store.read_memory_entries(account_id)
    assert any(entry.get("kind") == "biographical_fact" and "Berlin" in str(entry.get("user_text")) for entry in memories)


def test_city_change_is_persisted_even_when_weather_check_is_rate_limited(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)
    calls: list[str] = []

    def provider(city: str) -> str:
        calls.append(city)
        return f"{city}: 9 C"

    update_city_and_weather_context(account_store, account_id, "Ich wohne in Berlin.", now=datetime(2026, 6, 15, 9, tzinfo=timezone.utc), provider=provider)
    result = update_city_and_weather_context(account_store, account_id, "Ich wohne in Potsdam.", now=datetime(2026, 6, 15, 9, 30, tzinfo=timezone.utc), provider=provider)

    assert result.skipped_reason == "rate_limited"
    assert result.weather_text == ""
    assert account_store.read_agent_state(account_id)["weather_context"]["city"] == "Potsdam"
    assert weather_context_text(account_store, account_id) == ""
    assert calls == ["Berlin"]


def test_weather_provider_error_does_not_expose_stale_summary(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)

    update_city_and_weather_context(
        account_store,
        account_id,
        "Ich wohne in Berlin.",
        now=datetime(2026, 6, 15, 9, tzinfo=timezone.utc),
        provider=lambda city: f"{city}: 12 C",
    )

    def failing_provider(_city: str) -> str:
        raise RuntimeError("offline")

    result = update_city_and_weather_context(
        account_store,
        account_id,
        "Hallo.",
        now=datetime(2026, 6, 15, 11, 1, tzinfo=timezone.utc),
        provider=failing_provider,
    )

    assert result.checked is True
    assert result.skipped_reason == "weather_error"
    assert weather_context_text(account_store, account_id) == ""
    weather_state = account_store.read_agent_state(account_id)["weather_context"]
    assert weather_state["summary"] == ""
    assert "offline" in weather_state["last_error"]


def test_parallel_weather_updates_share_one_rate_limited_check(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)
    calls: list[str] = []

    def provider(city: str) -> str:
        calls.append(city)
        time.sleep(0.05)
        return f"{city}: 12 C"

    def update() -> object:
        return update_city_and_weather_context(
            account_store,
            account_id,
            "Ich wohne in Berlin.",
            now=datetime(2026, 6, 15, 9, tzinfo=timezone.utc),
            provider=provider,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: update(), range(2)))

    assert len(calls) == 1
    assert sorted(result.checked for result in results) == [False, True]


def test_engine_adds_cached_weather_context_to_openai_prompt(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    identity, account_id = prepare_account(account_store)
    update_city_and_weather_context(
        account_store,
        account_id,
        "Ich wohne in Berlin.",
        now=datetime.now(timezone.utc),
        provider=lambda city: f"{city}: 18 C, leicht bewoelkt",
    )
    prompts: list[str] = []

    class Client:
        def create_reply(self, prompt, _instructions, previous_response_id=None):
            prompts.append(prompt)
            return type("Response", (), {"text": "Antwort", "response_id": "resp_weather"})()

    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True),
        openai_client=Client(),
    )

    actions = engine.process(event(identity, "Was soll ich heute machen?"))

    assert any(getattr(action, "text", "") == "Antwort" for action in actions)
    assert "Lokaler Wetterkontext:" in prompts[0]
    assert "Stadt/Wohnort: Berlin" in prompts[0]
    assert "18 C" in prompts[0]
