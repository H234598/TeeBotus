from __future__ import annotations

import json
import logging
import re

import pytest

from TeeBotus.runtime.accounts import (
    ACCOUNT_MEMORY_KEY_PURPOSE,
    AccountStore,
    AccountStoreError,
    StaticSecretProvider,
    matrix_identity_key,
    signal_identity_key,
    telegram_identity_key,
)
from TeeBotus.runtime.memory_fallback import WarningFallbackAccountMemoryBackend
from TeeBotus.runtime.sqlite_memory import SQLiteAccountMemoryBackend, SQLiteMemoryConfig

HEX_128 = re.compile(r"^[0-9a-f]{128}$")


def provider() -> StaticSecretProvider:
    return StaticSecretProvider(b"a" * 32)


def test_first_contact_creates_account_and_encrypted_identity_mapping(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(395935293), display_label="Teladi")

    assert HEX_128.fullmatch(account_id)
    assert store.get_account_for_identity("telegram:user:395935293") == account_id
    raw_identity_file = (tmp_path / "accounts" / "Account_Identities.json").read_text(encoding="utf-8")
    assert account_id not in raw_identity_file
    assert "telegram:user:395935293" not in raw_identity_file
    assert "TMBMAP1" in raw_identity_file


def test_telegram_identity_key_uses_username_and_display_fallbacks() -> None:
    assert telegram_identity_key(395935293, username="Teladi") == "telegram:user:395935293"
    assert telegram_identity_key("", username="@Teladi") == "telegram:username:teladi"
    display_key = telegram_identity_key("", display_name="Teladi Example")
    assert display_key.startswith("telegram:display:")
    assert len(display_key.removeprefix("telegram:display:")) == 64


def test_matrix_identity_key_uses_localpart_and_display_fallbacks() -> None:
    assert matrix_identity_key("@ada:example.org", localpart="ada") == "matrix:user:@ada:example.org"
    assert matrix_identity_key("", localpart="@Ada") == "matrix:localpart:ada"
    display_key = matrix_identity_key("", display_name="Ada Lovelace")
    assert display_key.startswith("matrix:display:")
    assert len(display_key.removeprefix("matrix:display:")) == 64


def test_signal_identity_key_normalizes_uuid_case() -> None:
    assert signal_identity_key(source_uuid="ABC-DEF") == "signal:uuid:abc-def"


def test_identity_lookup_normalizes_case_insensitive_fallback_keys(tmp_path) -> None:
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())

    signal_account = store.resolve_or_create_account("signal:uuid:ABC-DEF")
    telegram_account = store.resolve_or_create_account("telegram:username:@AdaUser")
    matrix_account = store.resolve_or_create_account("matrix:localpart:@Ada")

    assert store.get_account_for_identity("signal:uuid:abc-def") == signal_account
    assert store.resolve_or_create_account("signal:uuid:abc-def") == signal_account
    assert store.get_account_for_identity("telegram:username:adauser") == telegram_account
    assert store.resolve_or_create_account("telegram:username:ADAUSER") == telegram_account
    assert store.get_account_for_identity("matrix:localpart:ada") == matrix_account
    assert store.resolve_or_create_account("matrix:localpart:ADA") == matrix_account


def test_identity_lookup_migrates_legacy_case_variant_key(tmp_path) -> None:
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    canonical_key = "signal:uuid:abc-def"
    legacy_key = "signal:uuid:ABC-DEF"
    account_id = store.resolve_or_create_account(canonical_key)
    identities = store._load_identities()
    payload = identities.pop(canonical_key)
    payload["identity_key"] = legacy_key
    identities[legacy_key] = payload
    store._save_identities(identities)
    profile = store._read_account_profile(account_id)
    profile["linked_identities"] = [legacy_key]
    store._write_account_profile(account_id, profile)

    assert store.get_account_for_identity(canonical_key) == account_id
    assert store.resolve_or_create_account(canonical_key) == account_id

    migrated_identities = store._load_identities()
    assert canonical_key in migrated_identities
    assert legacy_key not in migrated_identities
    migrated_profile = store._read_account_profile(account_id)
    assert migrated_profile["linked_identities"] == [canonical_key]


def test_identity_route_is_stored_encrypted_and_read_back(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    identity = telegram_identity_key(395935293)
    store.resolve_or_create_account(identity, display_label="Teladi")

    store.update_identity_route(identity, channel="telegram", chat_id="395935293", chat_type="private", adapter_slot=2)

    route = store.get_identity_route(identity)
    assert route is not None
    assert route["adapter_slot"] == 2
    assert route["channel"] == "telegram"
    assert route["chat_id"] == "395935293"
    assert route["chat_type"] == "private"
    assert route["last_seen_at"]
    raw_identity_file = (tmp_path / "accounts" / "Account_Identities.json").read_text(encoding="utf-8")
    assert "395935293" not in raw_identity_file


def test_identity_route_normalizes_channel_and_chat_type(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    identity = signal_identity_key(source_uuid="abc")
    store.resolve_or_create_account(identity)

    store.update_identity_route(identity, channel="Signal", chat_id="+491", chat_type="Private", adapter_slot=1)

    route = store.get_identity_route(identity)
    assert route is not None
    assert route["channel"] == "signal"
    assert route["chat_type"] == "private"
    assert route["chat_id"] == "+491"


def test_privacy_confirmation_is_persisted_in_profile_and_reset_by_memory_reset(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(395935293), display_label="Teladi")

    assert store.has_privacy_confirmation(account_id) is False

    store.confirm_privacy(account_id, source="telegram")

    assert store.has_privacy_confirmation(account_id) is True

    store.reset_structured_memory(account_id)

    assert store.has_privacy_confirmation(account_id) is False


def test_register_generates_single_secret_and_verifier_not_plaintext(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Bote_der_Wahrheit", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    returned_account_id, secret = store.register_account(account_id)

    assert returned_account_id == account_id
    assert HEX_128.fullmatch(secret)
    assert store.verify_secret(account_id, secret)
    secrets_raw = (tmp_path / "accounts" / "Account_Secrets.json").read_text(encoding="utf-8")
    assert secret not in secrets_raw

    with pytest.raises(AccountStoreError):
        store.register_account(account_id)


def test_rotate_secret_invalidates_old_secret(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Bote_der_Wahrheit", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    _, first_secret = store.register_account(account_id)
    _, second_secret = store.rotate_secret(account_id)

    assert first_secret != second_secret
    assert not store.verify_secret(account_id, first_secret)
    assert store.verify_secret(account_id, second_secret)


def test_link_identity_merges_temporary_memory_and_tombstones_temp(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    target = store.resolve_or_create_account(telegram_identity_key(1))
    _, secret = store.register_account(target)
    temp = store.resolve_or_create_account(signal_identity_key(source_uuid="abc"))

    temp_dir = store.account_dir(temp)
    target_dir = store.account_dir(target)
    store.write_memory_entries(temp, [{"text": "from signal"}])
    store.write_memory_entries(target, [{"text": "from telegram"}])
    (temp_dir / "User_Habbits_and_behave.md").write_text("temporary note", encoding="utf-8")
    (target_dir / "User_Habbits_and_behave.md").write_text("target note", encoding="utf-8")

    result = store.link_identity(signal_identity_key(source_uuid="abc"), target, secret, display_label="Signal")

    assert result["merged_from"] == temp
    assert store.get_account_for_identity("signal:uuid:abc") == target
    merged_entries = store.read_memory_entries(target)
    assert any(entry.get("text") == "from signal" for entry in merged_entries)
    assert any(entry.get("text") == "from telegram" for entry in merged_entries)
    raw_entries = (target_dir / "User_Memory_Entries.jsonl").read_text(encoding="utf-8")
    assert "from signal" not in raw_entries
    assert "TMBMAP1" in raw_entries
    merged_habits = (target_dir / "User_Habbits_and_behave.md").read_text(encoding="utf-8")
    assert "target note" in merged_habits
    assert "temporary note" in merged_habits
    assert (temp_dir / "Account_Tombstone.json").exists()
    assert not (temp_dir / "User_Memory_Entries.jsonl").exists()


def test_unlink_identity_marks_orphaned_when_last_identity_removed(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))

    unlinked_account = store.unlink_identity(telegram_identity_key(1))

    assert unlinked_account == account_id
    summary = store.account_summary(account_id)
    assert summary["status"] == "orphaned"
    assert summary["linked_identities"] == []


def test_link_identity_refuses_to_silently_merge_registered_source_account(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    target = store.resolve_or_create_account(telegram_identity_key(1))
    _, target_secret = store.register_account(target)
    source = store.resolve_or_create_account(signal_identity_key(source_uuid="abc"))
    store.register_account(source)

    with pytest.raises(AccountStoreError):
        store.link_identity(signal_identity_key(source_uuid="abc"), target, target_secret, display_label="Signal")

    assert store.get_account_for_identity("signal:uuid:abc") == source


def test_encrypted_memory_with_wrong_instance_secret_does_not_fallback_to_envelope(tmp_path):
    first = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"a" * 32))
    account_id = first.resolve_or_create_account(telegram_identity_key(77))
    first.write_memory_index(account_id, {"keywords": {"tea": [1]}})

    second = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"b" * 32), create_dirs=False)

    with pytest.raises(AccountStoreError):
        second.read_memory_index(account_id)


def test_account_tombstone_is_encrypted_after_merge(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    target = store.resolve_or_create_account(telegram_identity_key(10))
    _, secret = store.register_account(target)
    source = store.resolve_or_create_account(signal_identity_key(source_uuid="merge-me"))

    store.link_identity(signal_identity_key(source_uuid="merge-me"), target, secret)

    tombstone = store.account_dir(source) / "Account_Tombstone.json"
    raw = tombstone.read_text(encoding="utf-8")
    assert "TMBMAP1" in raw
    assert source not in raw


def test_account_text_helpers_reject_path_traversal(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))

    with pytest.raises(AccountStoreError):
        store.write_account_text(account_id, "../escape.md", "bad")
    with pytest.raises(AccountStoreError):
        store.read_account_text(account_id, "/tmp/escape.md")


def test_structured_account_memory_updates_profile_keyword_index_and_prompt(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_account_text(account_id, "User_Habbits_and_behave.md", "Ada bevorzugt knappe Antworten.")

    first_id = store.append_structured_memory_entry(
        account_id,
        {
            "channel": "telegram",
            "chat_type": "private",
            "source": {"chat_id": "1", "sender_id": "1"},
            "user_text": "Ich mag Mond Tee.",
            "bot_text": "Gemerkter Mond-Tee.",
        },
        profile_updates={
            "names": "Ada",
            "usernames": "@ada",
            "chat_ids": "1",
            "chat_titles": "Privat",
            "channels": "telegram",
        },
    )
    store.append_structured_memory_entry(
        account_id,
        {
            "channel": "signal",
            "chat_type": "private",
            "source": {"chat_id": "+491", "sender_id": "uuid"},
            "user_text": "Ich mag Kaffee.",
            "bot_text": "Gemerkter Kaffee.",
        },
        profile_updates={"channels": "signal"},
    )

    index = store.read_memory_index(account_id)
    assert index["scope"] == "account"
    assert index["profile"]["names"] == ["Ada"]
    assert index["profile"]["usernames"] == ["@ada"]
    assert index["profile"]["channels"] == ["telegram", "signal"]
    assert index["index"]["entries"][first_id]["kind"] == "observation"
    assert index["index"]["entries"][first_id]["importance"] == 3
    assert first_id in index["index"]["keywords"]["mond"]
    selection = store.select_structured_memory(account_id, query_text="mond", max_prompt_chars=12000, max_entry_chars=2000)

    assert selection.selected_ids[0] == first_id
    assert "Ada bevorzugt knappe Antworten." in selection.prompt_text
    assert '"scope": "account"' in selection.prompt_text
    assert '"kind": "observation"' in selection.prompt_text
    assert '"importance": 3' in selection.prompt_text
    assert '"user_text": "Ich mag Mond Tee."' in selection.prompt_text
    assert '"user_text": "Ich mag Kaffee."' in selection.prompt_text
    assert selection.selected_ids[-1] != first_id


def test_structured_account_memory_migrates_legacy_top_level_index(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_memory_entries(account_id, [{"id": "mem_legacy", "user_text": "Mond", "bot_text": "Tee"}])
    store.write_memory_index(account_id, {"keywords": {"mond": ["mem_legacy"]}, "recent_ids": ["mem_legacy"]})

    store.append_structured_memory_entry(account_id, {"id": "mem_new", "user_text": "Kaffee", "bot_text": "Tasse"})

    index = store.read_memory_index(account_id)
    assert "keywords" not in index
    assert index["schema_version"] == 2
    assert index["index"]["entries"]["mem_legacy"]["schema_version"] == 2
    assert index["index"]["keywords"]["mond"] == ["mem_legacy"]
    assert index["index"]["keywords"]["kaffee"] == ["mem_new"]


def test_append_structured_account_memory_renames_duplicate_entry_id(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    first_id = store.append_structured_memory_entry(account_id, {"id": "mem_same", "user_text": "Mond", "bot_text": "Tee"})
    second_id = store.append_structured_memory_entry(account_id, {"id": "mem_same", "user_text": "Kaffee", "bot_text": "Tasse"})

    assert first_id == "mem_same"
    assert second_id != "mem_same"
    entries = store.read_memory_entries(account_id)
    assert [entry["id"] for entry in entries] == ["mem_same", second_id]
    index = store.read_memory_index(account_id)
    assert set(index["index"]["entries"]) == {"mem_same", second_id}
    assert index["index"]["keywords"]["kaffee"] == [second_id]


def test_rebuild_structured_account_memory_index_removes_stale_ids(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_memory_entries(
        account_id,
        [
            {
                "id": "mem_live",
                "channel": "telegram",
                "source": {"chat_id": "1"},
                "user_text": "Mond bleibt.",
                "bot_text": "Gemerkt.",
            }
        ],
    )
    store.write_memory_index(
        account_id,
        {
            "profile": {"names": ["Ada"]},
            "index": {
                "keywords": {"mond": ["mem_live", "mem_stale"], "stale": ["mem_stale"]},
                "recent_ids": ["mem_stale", "mem_live"],
                "entries": {"mem_live": {}, "mem_stale": {}},
            },
        },
    )

    store.rebuild_structured_memory_index(account_id)

    index = store.read_memory_index(account_id)
    assert index["profile"]["names"] == ["Ada"]
    assert index["index"]["recent_ids"] == ["mem_live"]
    assert index["index"]["keywords"]["mond"] == ["mem_live"]
    assert "stale" not in index["index"]["keywords"]
    assert list(index["index"]["entries"]) == ["mem_live"]
    entries = store.read_memory_entries(account_id)
    assert entries[0]["keywords"] == ["mond", "bleibt", "gemerkt"]
    assert entries[0]["kind"] == "observation"
    assert entries[0]["importance"] == 3


def test_structured_account_memory_importance_breaks_keyword_ties(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    low_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_low", "user_text": "Mond", "bot_text": "Tee", "importance": 1},
    )
    high_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_high", "user_text": "Mond", "bot_text": "Tasse", "kind": "preference", "importance": 5},
    )

    selection = store.select_structured_memory(account_id, query_text="mond", max_prompt_chars=12000, max_entry_chars=2000)

    assert selection.selected_ids[:2] == (high_id, low_id)
    index = store.read_memory_index(account_id)
    assert index["index"]["entries"][high_id]["kind"] == "preference"
    assert index["index"]["entries"][high_id]["importance"] == 5


def test_structured_account_memory_related_ids_boost_linked_entries(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    direct_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_direct", "user_text": "Mond", "bot_text": "Tee", "related_ids": ["mem_linked"]},
    )
    unrelated_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_unrelated", "user_text": "Kaffee", "bot_text": "Tasse"},
    )
    linked_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_linked", "user_text": "Blauer Planet", "bot_text": "Notiz"},
    )

    selection = store.select_structured_memory(account_id, query_text="mond", max_prompt_chars=12000, max_entry_chars=2000)

    assert selection.selected_ids[:3] == (direct_id, linked_id, unrelated_id)


def test_structured_account_memory_v2_keeps_entries_and_builds_graph_cache(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    anchor_id = store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_anchor",
            "kind": "risk_signal",
            "user_text": "Akute Krise bei Einsamkeit.",
            "bot_text": "Krise behutsam eingeordnet.",
            "importance": 5,
        },
    )
    hypothesis_id = store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_hypothesis",
            "kind": "psychoanalytic_hypothesis",
            "user_text": "Rueckzug wirkt wie Schutz vor Beschaemung.",
            "bot_text": "Hypothese nur vorsichtig nutzen.",
            "supports": [anchor_id],
            "contradicts": ["mem_old"],
        },
    )
    old_id = store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_old",
            "kind": "self_statement",
            "user_text": "Ich bin nie einsam.",
            "bot_text": "Als fruehere Selbstbeschreibung gemerkt.",
            "supersedes": [],
        },
    )

    index = store.read_memory_index(account_id)
    entries = store.read_memory_entries(account_id)

    assert index["schema_version"] == 2
    assert len(entries) == 3
    assert entries[0]["kind"] == "risk_signal"
    assert entries[0]["decay"]["policy"] == "retain"
    assert entries[1]["kind"] == "psychoanalytic_hypothesis"
    assert index["index"]["entries"][anchor_id]["salience"] == 8
    assert index["index"]["graph"]["links"]["supports"][hypothesis_id] == [anchor_id]
    assert index["index"]["graph"]["links"]["contradicts"][hypothesis_id] == [old_id]
    assert index["index"]["semantic_cache"]["rebuildable"] is True
    assert hypothesis_id in index["index"]["semantic_cache"]["entries"]


def test_structured_account_memory_accepts_clinical_note_kinds(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))

    examples = [
        ("mem_mse", "mse_mood", "MSE mood: niedergeschlagen.", "compact", 3),
        ("mem_risk", "suicidal_ideation", "Passive Suizidgedanken ohne Plan.", "retain", 6),
        ("mem_medication", "medication_adherence", "SSRI Einnahme meist regelmaessig.", "retain", 3),
        ("mem_process", "psychotherapy_process_note", "Vermeidung taucht bei Naehe auf.", "decay", 3),
        ("mem_hypothesis", "diagnostic_hypothesis", "Depressive Episode bleibt Hypothese.", "decay", 5),
        ("mem_treatment", "treatment_goal", "Schlafrhythmus stabilisieren.", "retain", 4),
    ]

    for memory_id, kind, user_text, expected_policy, expected_salience in examples:
        store.append_structured_memory_entry(
            account_id,
            {
                "id": memory_id,
                "kind": kind,
                "user_text": user_text,
                "bot_text": "Notiert.",
            },
        )

    entries = {entry["id"]: entry for entry in store.read_memory_entries(account_id)}
    index_entries = store.read_memory_index(account_id)["index"]["entries"]

    for memory_id, kind, _user_text, expected_policy, expected_salience in examples:
        assert entries[memory_id]["kind"] == kind
        assert entries[memory_id]["decay"]["policy"] == expected_policy
        assert index_entries[memory_id]["kind"] == kind
        assert index_entries[memory_id]["salience"] == expected_salience


def test_structured_account_memory_v2_has_no_default_entry_store_limit(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))

    for index in range(205):
        store.append_structured_memory_entry(account_id, {"id": f"mem_{index}", "user_text": f"Mond {index}", "bot_text": "Tee"})

    assert len(store.read_memory_entries(account_id)) == 205
    memory_index = store.read_memory_index(account_id)
    assert memory_index["index"]["retention"]["entry_store_limit"] is None
    assert memory_index["index"]["retention"]["storage_backend"] == "encrypted-jsonl-plus-json-index"
    assert memory_index["index"]["retention"]["next_backend_candidate"] == "sqlite-row-encrypted-projection"


def test_account_store_sqlite_backend_stores_memory_outside_json_files(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "memory.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))

    memory_id = store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_sqlite",
            "kind": "observation",
            "memory_type": "episodic",
            "user_text": "Mond SQLite geheim",
            "bot_text": "Notiert.",
            "keywords": ["mond", "sqlite"],
        },
    )

    assert memory_id == "mem_sqlite"
    entries = store.read_memory_entries(account_id)
    index = store.read_memory_index(account_id)
    assert entries[0]["id"] == "mem_sqlite"
    assert index["index"]["entries"]["mem_sqlite"]["kind"] == "observation"
    account_dir = store.account_dir(account_id)
    assert not (account_dir / "User_Memory_Entries.jsonl").exists()
    assert not (account_dir / "User_Memory_Index.json").exists()
    raw_db = sqlite_path.read_bytes()
    assert b"Mond SQLite geheim" not in raw_db


def test_account_store_sqlite_backend_falls_back_to_secondary_with_warning(tmp_path, monkeypatch, caplog):
    provider_instance = provider()
    fallback_path = tmp_path / "fallback.sqlite3"
    fallback_backend = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider_instance,
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=fallback_path, fallback_path=None),
    )
    account_id = "a" * 128
    fallback_backend.write_entries(account_id, [{"id": "mem_backup", "user_text": "Backup"}])
    fallback_backend.write_index(account_id, {"index": {"entries": {"mem_backup": {}}}})
    broken_primary_path = tmp_path / "broken-primary.sqlite3"
    broken_primary_path.mkdir()
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(broken_primary_path))
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH", str(fallback_path))
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider_instance)

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        entries = store.read_memory_entries(account_id)

    assert entries == [{"id": "mem_backup", "user_text": "Backup"}]
    assert "ACCOUNT MEMORY PRIMARY DATABASE FAILED" in caplog.text


def test_account_memory_fallback_syncs_dirty_entries_back_to_primary(caplog):
    class Backend:
        def __init__(self, *, fail_write: bool = False) -> None:
            self.fail_write = fail_write
            self.entries: dict[str, list[dict[str, str]]] = {}

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            if self.fail_write:
                raise OSError("primary unavailable")
            self.entries[account_id] = [dict(row) for row in rows]

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

    primary = Backend(fail_write=True)
    fallback = Backend()
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")
    account_id = "a" * 128

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        backend.write_entries(account_id, [{"id": "mem_fallback"}])
        primary.fail_write = False
        entries = backend.read_entries(account_id)

    assert entries == [{"id": "mem_fallback"}]
    assert primary.entries[account_id] == [{"id": "mem_fallback"}]
    assert "ACCOUNT MEMORY PRIMARY DATABASE FAILED" in caplog.text
    assert "primary backend recovered" in caplog.text


def test_account_memory_fallback_syncs_dirty_index_back_to_primary(caplog):
    class Backend:
        def __init__(self, *, fail_write: bool = False) -> None:
            self.fail_write = fail_write
            self.indexes: dict[str, dict[str, object]] = {}

        def read_entries(self, _account_id: str) -> list[dict[str, str]]:
            return []

        def write_entries(self, _account_id: str, _rows: list[dict[str, str]]) -> None:
            return None

        def read_index(self, account_id: str) -> dict[str, object]:
            return dict(self.indexes.get(account_id, {}))

        def write_index(self, account_id: str, data: dict[str, object]) -> None:
            if self.fail_write:
                raise OSError("primary unavailable")
            self.indexes[account_id] = dict(data)

    primary = Backend(fail_write=True)
    fallback = Backend()
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")
    account_id = "a" * 128

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        backend.write_index(account_id, {"index": {"entries": {"mem_fallback": {}}}})
        primary.fail_write = False
        index = backend.read_index(account_id)

    assert index == {"index": {"entries": {"mem_fallback": {}}}}
    assert primary.indexes[account_id] == {"index": {"entries": {"mem_fallback": {}}}}
    assert "ACCOUNT MEMORY PRIMARY DATABASE FAILED" in caplog.text
    assert "primary backend recovered" in caplog.text


def test_account_store_sqlite_backend_skips_corrupt_rows(tmp_path, monkeypatch, caplog):
    sqlite_path = tmp_path / "memory.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_memory_entries(account_id, [{"id": "mem_ok", "user_text": "ok"}])
    import sqlite3

    con = sqlite3.connect(sqlite_path)
    with con:
        con.execute("update memory_entries set payload_ciphertext = ? where memory_id = ?", (b"broken", "mem_ok"))
    con.close()

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        entries = store.read_memory_entries(account_id)

    assert entries == []
    assert "skipped corrupt rows" in caplog.text


def test_structured_account_memory_semantic_cache_boosts_synced_signature(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    direct_id = store.append_structured_memory_entry(account_id, {"id": "mem_direct", "user_text": "Mond", "bot_text": "Tee"})
    semantic_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_semantic", "kind": "coping_strategy", "user_text": "Spaziergang hilft bei Druck.", "bot_text": "Ressource notiert."},
    )
    index = store.read_memory_index(account_id)
    index["index"]["keywords"].pop("spaziergang", None)
    store.write_memory_index(account_id, index)

    selection = store.select_structured_memory(account_id, query_text="spaziergang", max_prompt_chars=12000, max_entry_chars=2000)

    assert selection.selected_ids[:2] == (semantic_id, direct_id)


def test_structured_account_memory_semantic_embedding_matches_synonym(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    walk_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_walk", "kind": "coping_strategy", "user_text": "Spaziergang hilft bei Druck.", "bot_text": "Ressource notiert."},
    )
    other_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_other", "user_text": "Mond Tee.", "bot_text": "Notiz."},
    )

    selection = store.select_structured_memory(account_id, query_text="gehen stress", max_prompt_chars=12000, max_entry_chars=2000)

    assert selection.selected_ids[:2] == (walk_id, other_id)
    semantic_entry = store.read_memory_index(account_id)["index"]["semantic_cache"]["entries"][walk_id]
    assert len(semantic_entry["embedding"]) == 64


def test_structured_account_memory_selection_can_exclude_loaded_ids(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    walk_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_walk", "kind": "coping_strategy", "user_text": "Spaziergang hilft bei Druck.", "bot_text": "Ressource notiert."},
    )
    tea_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_tea", "user_text": "Tee hilft beim Sortieren.", "bot_text": "Notiz."},
    )

    selection = store.select_structured_memory(
        account_id,
        query_text="gehen stress tee",
        max_prompt_chars=12000,
        max_entry_chars=2000,
        exclude_ids=(walk_id,),
    )

    assert walk_id not in selection.selected_ids
    assert tea_id in selection.selected_ids
    assert '"id": "mem_walk"' not in selection.prompt_text


def test_structured_account_memory_semantic_cache_can_be_disabled(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_memory_index(account_id, {"index": {"semantic_cache": {"enabled": False, "entries": {"stale": {}}}}})

    store.append_structured_memory_entry(
        account_id,
        {"id": "mem_walk", "kind": "coping_strategy", "user_text": "Spaziergang hilft bei Druck.", "bot_text": "Ressource notiert."},
    )

    semantic_cache = store.read_memory_index(account_id)["index"]["semantic_cache"]
    assert semantic_cache["enabled"] is False
    assert semantic_cache["entries"] == {}


def test_rebuild_structured_account_memory_keeps_semantic_cache_disabled(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.append_structured_memory_entry(
        account_id,
        {"id": "mem_walk", "kind": "coping_strategy", "user_text": "Spaziergang hilft bei Druck.", "bot_text": "Ressource notiert."},
    )
    index = store.read_memory_index(account_id)
    index["index"]["semantic_cache"]["enabled"] = False
    index["index"]["semantic_cache"]["entries"] = {"stale": {}}
    store.write_memory_index(account_id, index)

    store.rebuild_structured_memory_index(account_id)

    semantic_cache = store.read_memory_index(account_id)["index"]["semantic_cache"]
    assert semantic_cache["enabled"] is False
    assert semantic_cache["entries"] == {}


def test_structured_account_memory_records_access_recency(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    first_id = store.append_structured_memory_entry(account_id, {"id": "mem_first", "user_text": "Mond", "bot_text": "Tee"})
    second_id = store.append_structured_memory_entry(account_id, {"id": "mem_second", "user_text": "Kaffee", "bot_text": "Tasse"})

    selection = store.select_structured_memory(account_id, query_text="mond", max_prompt_chars=12000, max_entry_chars=2000)

    assert selection.selected_ids[:2] == (first_id, second_id)
    entries = {entry["id"]: entry for entry in store.read_memory_entries(account_id)}
    index = store.read_memory_index(account_id)["index"]
    assert entries[first_id]["access_count"] == 1
    assert entries[first_id]["last_accessed_at"]
    assert index["accessed_ids"][-2:] == [first_id, second_id]


def test_rebuild_structured_account_memory_restores_access_recency(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    first_id = store.append_structured_memory_entry(account_id, {"id": "mem_first", "user_text": "Mond", "bot_text": "Tee"})
    second_id = store.append_structured_memory_entry(account_id, {"id": "mem_second", "user_text": "Kaffee", "bot_text": "Tasse"})
    store.select_structured_memory(account_id, query_text="mond", max_prompt_chars=12000, max_entry_chars=2000)
    index = store.read_memory_index(account_id)
    index["index"]["accessed_ids"] = []
    store.write_memory_index(account_id, index)

    store.rebuild_structured_memory_index(account_id)

    rebuilt = store.read_memory_index(account_id)["index"]
    assert rebuilt["accessed_ids"][-2:] == [first_id, second_id]
    assert store.check_structured_memory_index(account_id).ok


def test_structured_account_memory_indexes_types_and_temporal_relations(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    source_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_episode", "memory_type": "episodic", "user_text": "Episode Druck.", "bot_text": "Notiert."},
    )
    fact_id = store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_fact",
            "kind": "fact",
            "memory_type": "semantic",
            "user_text": "Druck bessert sich durch Bewegung.",
            "bot_text": "Faktensignal notiert.",
            "valid_from": "2026-06-15",
            "relations": [
                {
                    "type": "derived_from",
                    "target_id": source_id,
                    "valid_from": "2026-06-15",
                    "provenance": {"source": "test"},
                    "confidence": 0.75,
                }
            ],
        },
    )

    index = store.read_memory_index(account_id)["index"]

    assert source_id in index["types"]["episodic"]
    assert fact_id in index["types"]["semantic"]
    assert index["entries"][fact_id]["valid_from"] == "2026-06-15"
    assert index["entries"][fact_id]["relations"][0]["type"] == "derived_from"
    assert {"source_id": fact_id, "target_id": source_id, "type": "derived_from", "valid_from": "2026-06-15", "valid_to": "", "provenance": {"source": "test"}, "confidence": 0.75} in index["graph"]["relations"]


def test_structured_account_memory_maintenance_consolidates_repeated_episodes(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    for index in range(3):
        store.append_structured_memory_entry(
            account_id,
            {
                "id": f"mem_episode_{index}",
                "memory_type": "episodic",
                "user_text": f"Spaziergang hilft gegen Druck {index}.",
                "bot_text": "Notiert.",
            },
        )

    created = store.run_memory_maintenance(account_id)

    assert len(created) == 1
    entries = {entry["id"]: entry for entry in store.read_memory_entries(account_id)}
    consolidated = entries[created[0]]
    assert consolidated["memory_type"] == "semantic"
    assert consolidated["kind"] == "summary"
    assert consolidated["supports"] == ["mem_episode_0", "mem_episode_1", "mem_episode_2"]


def test_rebuild_structured_account_memory_index_renames_duplicate_ids(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_memory_entries(
        account_id,
        [
            {"id": "mem_same", "user_text": "Mond", "bot_text": "Tee"},
            {"id": "mem_same", "user_text": "Kaffee", "bot_text": "Tasse"},
        ],
    )

    store.rebuild_structured_memory_index(account_id)

    entries = store.read_memory_entries(account_id)
    ids = [entry["id"] for entry in entries]
    assert ids[0] == "mem_same"
    assert ids[1] != "mem_same"
    assert len(set(ids)) == 2
    index = store.read_memory_index(account_id)
    assert set(index["index"]["entries"]) == set(ids)
    assert index["index"]["keywords"]["mond"] == [ids[0]]
    assert index["index"]["keywords"]["kaffee"] == [ids[1]]


def test_structured_account_memory_index_health_reports_ok(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.append_structured_memory_entry(account_id, {"id": "mem_live", "user_text": "Mond", "bot_text": "Tee"})

    health = store.check_structured_memory_index(account_id)

    assert health.ok
    assert health.errors == ()


def test_structured_account_memory_index_health_reports_broken_invariants(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_memory_entries(
        account_id,
        [
            {"id": "mem_live", "user_text": "Mond"},
            {"id": "mem_live", "user_text": "Kaffee"},
        ],
    )
    store.write_memory_index(
        account_id,
        {
            "scope": "legacy",
            "keywords": {"legacy": ["mem_live"]},
            "index": {
                "recent_ids": ["mem_live", "mem_live", "mem_missing_recent"],
                "keywords": {"mond": ["mem_live", "mem_missing_keyword"]},
                "entries": {"mem_live": {}, "mem_missing_entry": {}},
            },
        },
    )
    entries = store.read_memory_entries(account_id)
    entries[0]["related_ids"] = ["mem_missing_related"]
    store.write_memory_entries(account_id, entries)

    health = store.check_structured_memory_index(account_id)

    assert not health.ok
    error_text = "\n".join(health.errors)
    assert "duplicate entry ids: mem_live" in error_text
    assert "index scope is not account" in error_text
    assert "legacy top-level keywords is present" in error_text
    assert "duplicate recent_ids: mem_live" in error_text
    assert "recent_ids missing entries: mem_missing_recent" in error_text
    assert "keyword ids missing entries: mem_missing_keyword" in error_text
    assert "index.entries missing entries: mem_missing_entry" in error_text
    assert "related_ids missing entries: mem_missing_related" in error_text


def test_structured_account_memory_index_health_reports_stale_semantic_cache(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.append_structured_memory_entry(account_id, {"id": "mem_live", "user_text": "Mond", "bot_text": "Tee"})
    entries = store.read_memory_entries(account_id)
    entries[0]["user_text"] = "Kaffee"
    store.write_memory_entries(account_id, entries)

    health = store.check_structured_memory_index(account_id)

    assert not health.ok
    assert "semantic_cache entries stale: mem_live" in "\n".join(health.errors)


def test_structured_account_memory_index_health_reports_malformed_semantic_cache(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.append_structured_memory_entry(account_id, {"id": "mem_live", "user_text": "Mond", "bot_text": "Tee"})
    index = store.read_memory_index(account_id)
    index["index"]["semantic_cache"]["entries"]["mem_live"]["embedding"] = [1.0]
    index["index"]["semantic_cache"]["entries"]["mem_live"]["signature"] = "mond"
    store.write_memory_index(account_id, index)

    health = store.check_structured_memory_index(account_id)

    assert not health.ok
    assert "semantic_cache entries malformed: mem_live" in "\n".join(health.errors)


def test_merge_rebuilds_structured_account_memory_index_from_merged_entries(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    target = store.resolve_or_create_account(telegram_identity_key(1))
    _, secret = store.register_account(target)
    source = store.resolve_or_create_account(signal_identity_key(source_uuid="abc"))
    store.write_memory_entries(
        target,
        [{"id": "mem_target", "user_text": "Telegram Mond.", "bot_text": "Gemerkt.", "channel": "telegram"}],
    )
    store.write_memory_entries(
        source,
        [{"id": "mem_source", "user_text": "Signal Kaffee.", "bot_text": "Gemerkt.", "channel": "signal"}],
    )
    store.write_memory_index(target, {"index": {"keywords": {"stale": ["mem_missing"]}, "recent_ids": ["mem_missing"], "entries": {"mem_missing": {}}}})
    store.write_memory_index(source, {"index": {"keywords": {"ghost": ["mem_ghost"]}, "recent_ids": ["mem_ghost"], "entries": {"mem_ghost": {}}}})

    store.link_identity(signal_identity_key(source_uuid="abc"), target, secret, display_label="Signal")

    index = store.read_memory_index(target)
    assert index["index"]["recent_ids"] == ["mem_target", "mem_source"]
    assert "stale" not in index["index"]["keywords"]
    assert "ghost" not in index["index"]["keywords"]
    assert index["index"]["keywords"]["mond"] == ["mem_target"]
    assert index["index"]["keywords"]["kaffee"] == ["mem_source"]
    assert set(index["index"]["entries"]) == {"mem_target", "mem_source"}
