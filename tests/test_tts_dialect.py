from __future__ import annotations

from TeeBotus.instructions import BotInstructions
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key
from TeeBotus.runtime.tts_dialect import (
    extract_birth_city,
    extract_lifetime_city,
    maybe_update_tts_dialect_preference,
    tts_dialect_city,
    voice_instructions_for_account,
)


def store(tmp_path) -> AccountStore:
    return AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"d" * 32))


def test_extract_birth_and_lifetime_city_phrases() -> None:
    assert extract_birth_city("Ich bin in Nürnberg geboren.") == "Nürnberg"
    assert extract_birth_city("Meine Geburtsstadt ist München.") == "München"
    assert extract_lifetime_city("Ich habe den größten Teil meines Lebens in Hamburg verbracht.") == "Hamburg"


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
