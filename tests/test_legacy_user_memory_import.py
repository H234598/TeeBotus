from __future__ import annotations

import json
from pathlib import Path

from scripts.import_legacy_user_memory import import_legacy_user_memory, main as import_main
from TeeBotus.runtime.accounts import ACCOUNT_MEMORY_KEY_PURPOSE, AccountStore, StaticSecretProvider, telegram_identity_key
from TeeBotus.runtime.sqlite_memory import SQLiteAccountMemoryBackend, SQLiteMemoryConfig


def provider(secret: bytes = b"a" * 32) -> StaticSecretProvider:
    return StaticSecretProvider(secret)


def write_legacy_entries(root: Path, *, instance: str = "Depressionsbot", user_id: str = "395935293") -> Path:
    user_dir = root / instance / "data" / "users" / user_id
    user_dir.mkdir(parents=True)
    rows = [
        {
            "id": "legacy_mem_1",
            "created_at": "2026-06-01T00:00:00+00:00",
            "updated_at": "2026-06-01T00:00:00+00:00",
            "sender": {"id": user_id},
            "source": {"legacy": True},
            "user_text": "Legacy user text",
            "bot_text": "Legacy bot text",
            "keywords": ["legacy"],
            "related_ids": [],
        }
    ]
    (user_dir / "User_Memory_Entries.jsonl").write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
    (user_dir / "User_Memory_Index.json").write_text(json.dumps({"index": {"entries": {"legacy_mem_1": {}}}}), encoding="utf-8")
    return user_dir


def test_legacy_user_memory_import_dry_run_does_not_create_account(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root)

    stats = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=False,
        provider=provider(),
    )

    assert stats.sources == 1
    assert stats.entries_seen == 1
    assert stats.entries_imported == 1
    assert stats.events[0]["action"] == "would-import"
    assert stats.events[0]["entries"] == 1
    store = AccountStore(target_root / "Depressionsbot" / "data" / "accounts", "Depressionsbot", secret_provider=provider())
    assert store.get_account_for_identity(telegram_identity_key("395935293")) is None


def test_legacy_user_memory_import_apply_creates_encrypted_account_memory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root)

    stats = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=True,
        provider=provider(),
    )

    assert stats.imported_sources == 1
    assert stats.entries_imported == 1
    store = AccountStore(target_root / "Depressionsbot" / "data" / "accounts", "Depressionsbot", secret_provider=provider())
    account_id = store.get_account_for_identity(telegram_identity_key("395935293"))
    assert account_id
    entries = store.read_memory_entries(account_id)
    assert [entry["id"] for entry in entries] == ["legacy_mem_1"]
    assert entries[0]["source"]["legacy_import"] is True
    health = store.check_structured_memory_index(account_id)
    assert health.ok


def test_legacy_user_memory_import_requires_replace_for_unreadable_target(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root)
    accounts_root = target_root / "Depressionsbot" / "data" / "accounts"
    store = AccountStore(accounts_root, "Depressionsbot", secret_provider=provider())
    account_id = store.resolve_or_create_account(telegram_identity_key("395935293"))
    bad_backend = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(b"b" * 32),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=accounts_root / "Account_Memory.sqlite3", fallback_path=None),
    )
    bad_backend.write_entries(account_id, [{"id": "bad", "user_text": "unreadable"}])
    bad_backend.write_index(account_id, {"scope": "account", "index": {}})

    skipped = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=True,
        replace_unreadable=False,
        provider=provider(),
    )
    replaced = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=True,
        replace_unreadable=True,
        provider=provider(),
    )

    assert skipped.skipped_sources == 1
    assert skipped.unreadable_targets == 1
    assert replaced.imported_sources == 1
    assert replaced.backups_created >= 1
    assert [entry["id"] for entry in store.read_memory_entries(account_id)] == ["legacy_mem_1"]


def test_legacy_user_memory_import_can_replace_unreadable_account_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root)
    accounts_root = target_root / "Depressionsbot" / "data" / "accounts"
    bad_store = AccountStore(accounts_root, "Depressionsbot", secret_provider=provider(b"b" * 32))
    bad_store.resolve_or_create_account(telegram_identity_key("395935293"))

    skipped = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=True,
        provider=provider(),
    )
    replaced = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=True,
        replace_unreadable_account_metadata=True,
        provider=provider(),
    )

    assert skipped.skipped_sources == 1
    assert skipped.unreadable_metadata == 1
    assert replaced.metadata_backups_created >= 1
    assert replaced.account_store_resets == 1
    store = AccountStore(accounts_root, "Depressionsbot", secret_provider=provider())
    account_id = store.get_account_for_identity(telegram_identity_key("395935293"))
    assert account_id
    assert [entry["id"] for entry in store.read_memory_entries(account_id)] == ["legacy_mem_1"]
    assert store.check_structured_memory_index(account_id).ok


def test_legacy_user_memory_import_metadata_reset_moves_old_sqlite_rows_out_of_active_store(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root, user_id="395935293")
    write_legacy_entries(legacy_root, user_id="1284666801")
    accounts_root = target_root / "Depressionsbot" / "data" / "accounts"
    bad_store = AccountStore(accounts_root, "Depressionsbot", secret_provider=provider(b"b" * 32))
    first_bad_account = bad_store.resolve_or_create_account(telegram_identity_key("395935293"))
    bad_store.write_memory_entries(first_bad_account, [{"id": "bad", "user_text": "unreadable"}])
    bad_store.write_memory_index(first_bad_account, {"scope": "account", "index": {"entries": {"bad": {}}}})

    stats = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=True,
        replace_unreadable_account_metadata=True,
        provider=provider(),
    )

    assert stats.account_store_resets == 1
    store = AccountStore(accounts_root, "Depressionsbot", secret_provider=provider())
    imported_ids = [
        store.get_account_for_identity(telegram_identity_key("1284666801")),
        store.get_account_for_identity(telegram_identity_key("395935293")),
    ]
    assert all(imported_ids)
    for account_id in imported_ids:
        assert account_id != first_bad_account
        assert store.check_structured_memory_index(account_id).ok
    active_entries = []
    for account_id in imported_ids:
        active_entries.extend(entry["id"] for entry in store.read_memory_entries(account_id))
    assert active_entries == ["legacy_mem_1", "legacy_mem_1"]
    assert list(accounts_root.glob(".pre-legacy-user-memory-account-store-reset-*"))


def test_legacy_user_memory_import_dry_run_can_simulate_metadata_replacement(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root)
    accounts_root = target_root / "Depressionsbot" / "data" / "accounts"
    bad_store = AccountStore(accounts_root, "Depressionsbot", secret_provider=provider(b"b" * 32))
    bad_store.resolve_or_create_account(telegram_identity_key("395935293"))

    stats = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=False,
        replace_unreadable_account_metadata=True,
        provider=provider(),
    )

    assert stats.unreadable_metadata == 1
    assert stats.entries_seen == 1
    assert stats.entries_imported == 1
    assert stats.metadata_backups_created == 0


def test_legacy_user_memory_import_writes_json_and_markdown_reports(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root)
    json_output = tmp_path / "import.json"
    markdown_output = tmp_path / "import.md"

    result = import_main(
        [
            "--legacy-instances-dir",
            str(legacy_root),
            "--target-instances-dir",
            str(target_root),
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(markdown_output),
        ]
    )

    assert result == 0
    payload = json.loads(json_output.read_text(encoding="utf-8"))
    markdown = markdown_output.read_text(encoding="utf-8")
    assert payload["mode"] == "dry-run"
    assert payload["totals"]["entries_imported"] == 1
    assert payload["events"][0]["identity"] == "telegram:user:395935293"
    assert payload["events"][0]["action"] == "would-import"
    assert "Legacy user text" not in json_output.read_text(encoding="utf-8")
    assert "Legacy user text" not in markdown
    assert "entries_imported" in markdown
