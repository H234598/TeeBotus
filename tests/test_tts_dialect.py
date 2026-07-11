from __future__ import annotations

import threading
import time

from TeeBotus.instructions import BotInstructions
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key
from TeeBotus.runtime.tts_dialect import (
    extract_birth_city,
    extract_lifetime_city,
    handle_tts_mimic_voice_command,
    maybe_update_tts_dialect_preference,
    record_tts_voice_style_observation,
    tts_dialect_city,
    tts_mimic_voice_profile,
    voice_instructions_for_account,
)


def store(tmp_path) -> AccountStore:
    return AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"d" * 32))


def test_extract_birth_and_lifetime_city_phrases() -> None:
    assert extract_birth_city("Ich bin in Nürnberg geboren.") == "Nürnberg"
    assert extract_birth_city("Ich wurde in Dresden geboren.") == "Dresden"
    assert extract_birth_city("Geboren wurde ich in Leipzig.") == "Leipzig"
    assert extract_birth_city("Meine Geburtsstadt ist München.") == "München"
    assert extract_lifetime_city("Ich habe den größten Teil meines Lebens in Hamburg verbracht.") == "Hamburg"
    assert extract_birth_city("Meine Geburtsstadt ist nicht München.") == ""


def test_birth_city_sets_tts_dialect_without_prompt(tmp_path) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="dialect"))

    update = maybe_update_tts_dialect_preference(account_store, account_id, "Ich bin in Nürnberg geboren.")

    assert update.changed is True
    assert update.reply_text == ""
    assert tts_dialect_city(account_store, account_id) == "Nürnberg"
    adjusted = voice_instructions_for_account(BotInstructions(openai_voice_instructions="Basis."), account_store, account_id)
    assert "Basis." in adjusted.openai_voice_instructions
    assert "Nürnberg" in adjusted.openai_voice_instructions
    assert "nicht karikierend" in adjusted.openai_voice_instructions


def test_lifetime_city_requires_positive_confirmation(tmp_path) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="lifetime"))

    pending = maybe_update_tts_dialect_preference(
        account_store,
        account_id,
        "Ich habe den größten Teil meines Lebens in Hamburg verbracht.",
    )
    confirmed = maybe_update_tts_dialect_preference(account_store, account_id, "Ja, ich mochte es dort.")

    assert pending.pending is True
    assert "Mochtest du es dort" in pending.reply_text
    assert confirmed.changed is True
    assert tts_dialect_city(account_store, account_id) == "Hamburg"


def test_negative_lifetime_city_does_not_override_tts_dialect(tmp_path) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="negative"))

    update = maybe_update_tts_dialect_preference(
        account_store,
        account_id,
        "Ich habe den größten Teil meines Lebens in Berlin verbracht, aber ich mochte es dort nicht.",
    )

    assert update.changed is False
    assert tts_dialect_city(account_store, account_id) == ""


def test_negative_lifetime_phrasings_do_not_override_tts_dialect(tmp_path) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="negative-phrases"))

    for text in (
        "Ich habe den größten Teil meines Lebens in Berlin verbracht, aber es war nicht schön.",
        "Ich habe den größten Teil meines Lebens in Hamburg verbracht, aber nicht gern.",
    ):
        update = maybe_update_tts_dialect_preference(account_store, account_id, text)
        assert update.changed is False

    assert tts_dialect_city(account_store, account_id) == ""


def test_pending_lifetime_confirmation_rejects_contradictory_yes(tmp_path) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="pending-contradiction"))

    pending = maybe_update_tts_dialect_preference(
        account_store,
        account_id,
        "Ich habe den größten Teil meines Lebens in Hamburg verbracht.",
    )
    response = maybe_update_tts_dialect_preference(account_store, account_id, "Ja, ich mochte es dort nicht.")

    assert pending.pending is True
    assert response.changed is False
    assert response.pending is False
    assert tts_dialect_city(account_store, account_id) == ""


def test_dialect_preference_updates_are_serialized_per_account(tmp_path, monkeypatch) -> None:
    first = store(tmp_path)
    second = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"d" * 32))
    account_id = first.resolve_or_create_account(signal_identity_key(source_uuid="dialect-lock"))
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

    def update(account_store, text: str) -> None:
        try:
            maybe_update_tts_dialect_preference(account_store, account_id, text)
        except BaseException as exc:  # pragma: no cover - only used to report thread failures.
            errors.append(exc)

    threads = [
        threading.Thread(target=update, args=(first, "Ich bin in Dresden geboren.")),
        threading.Thread(target=update, args=(second, "Ich bin in Leipzig geboren.")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert state["maximum"] == 1
    assert tts_dialect_city(first, account_id) in {"Dresden", "Leipzig"}


def test_mimic_command_and_observation_share_account_lock(tmp_path, monkeypatch) -> None:
    first = store(tmp_path)
    second = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"d" * 32))
    account_id = first.resolve_or_create_account(signal_identity_key(source_uuid="mimic-command-lock"))
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

    def run_command() -> None:
        try:
            handle_tts_mimic_voice_command(first, account_id, "/mimic_voice on", BotInstructions())
        except BaseException as exc:  # pragma: no cover - only used to report thread failures.
            errors.append(exc)

    def run_observation() -> None:
        try:
            record_tts_voice_style_observation(second, account_id, "Ich rede schnell und ruhig.", duration_seconds=3)
        except BaseException as exc:  # pragma: no cover - only used to report thread failures.
            errors.append(exc)

    threads = [threading.Thread(target=run_command), threading.Thread(target=run_observation)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert state["maximum"] == 1
    assert first.read_agent_state(account_id)["tts_mimic_voice"]["enabled"] is True


def test_voice_style_observations_are_serialized_per_account(tmp_path, monkeypatch) -> None:
    first = store(tmp_path)
    second = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"d" * 32))
    account_id = first.resolve_or_create_account(signal_identity_key(source_uuid="mimic-lock"))
    original_read = AccountStore.read_agent_state

    def slow_read(account_store, current_account_id):
        time.sleep(0.03)
        return original_read(account_store, current_account_id)

    monkeypatch.setattr(AccountStore, "read_agent_state", slow_read)
    errors: list[BaseException] = []

    def record(account_store, text: str) -> None:
        try:
            assert record_tts_voice_style_observation(account_store, account_id, text, duration_seconds=3) is True
        except BaseException as exc:  # pragma: no cover - only used to report thread failures.
            errors.append(exc)

    threads = [
        threading.Thread(target=record, args=(first, "Ich rede sehr schnell und bin nervoes.")),
        threading.Thread(target=record, args=(second, "Ich rede langsam und bin ruhig.")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert first.read_agent_state(account_id)["tts_mimic_voice"]["observations_count"] == 2


def test_corrupt_mimic_state_fails_closed_and_recovers_on_observation(tmp_path) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="mimic-corrupt"))
    state = account_store.read_agent_state(account_id)
    state["tts_mimic_voice"] = {
        "enabled": "false",
        "observations_count": "kaputt",
        "label_counts": {"spricht schnell": "kaputt"},
        "avg_words_per_minute": "kaputt",
    }
    account_store.write_agent_state(account_id, state)

    profile, position = tts_mimic_voice_profile(account_store, account_id)
    status = handle_tts_mimic_voice_command(account_store, account_id, "/mimic_voice", BotInstructions())
    changed = record_tts_voice_style_observation(account_store, account_id, "Ich rede schnell und ruhig.", duration_seconds=3)

    assert (profile, position) == ("", "after_dialect")
    assert status.enabled is False
    assert changed is True
    repaired = account_store.read_agent_state(account_id)["tts_mimic_voice"]
    assert repaired["observations_count"] == 1
    assert repaired["label_counts"]


def test_voice_style_observation_builds_mimic_profile_without_raw_transcript(tmp_path) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="mimic"))

    changed = record_tts_voice_style_observation(
        account_store,
        account_id,
        "Aehm also ich weiss nicht, ich bin vielleicht gerade etwas nervoes und rede sehr schnell.",
        duration_seconds=4,
    )
    result = handle_tts_mimic_voice_command(account_store, account_id, "/mimic_voice on", BotInstructions())
    profile, position = tts_mimic_voice_profile(account_store, account_id)
    state = account_store.read_agent_state(account_id)

    assert changed is True
    assert result.enabled is True
    assert position == "after_dialect"
    assert "spricht sehr schnell und hastig" in profile
    assert "unsicher oder aengstlich" in profile
    assert "ich weiss nicht" not in str(state)


def test_mimic_voice_instructions_can_be_ordered_before_dialect(tmp_path) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="mimic-order"))

    maybe_update_tts_dialect_preference(account_store, account_id, "Ich bin in Dresden geboren.")
    record_tts_voice_style_observation(
        account_store,
        account_id,
        "Aehm also isch rede gerade sehr schnell und bin nervoes.",
        duration_seconds=3,
    )
    handle_tts_mimic_voice_command(account_store, account_id, "/mimic_voice before", BotInstructions())

    adjusted = voice_instructions_for_account(BotInstructions(openai_voice_instructions="Basis."), account_store, account_id)

    assert "Basis." in adjusted.openai_voice_instructions
    assert adjusted.openai_voice_instructions.index("beobachtete Sprechweise") < adjusted.openai_voice_instructions.index("Dresden")
    assert "saechsischen Einschlag" in adjusted.openai_voice_instructions
