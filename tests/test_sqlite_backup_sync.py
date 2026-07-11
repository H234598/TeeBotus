from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import scripts.sync_account_memory_sqlite_backup as sqlite_backup_sync
from TeeBotus.runtime.accounts import ACCOUNT_MEMORY_KEY_PURPOSE, AccountStoreError, StaticSecretProvider
from TeeBotus.runtime.sqlite_memory import SQLiteAccountMemoryBackend, SQLiteMemoryConfig


def provider(secret: bytes = b"a" * 32) -> StaticSecretProvider:
    return StaticSecretProvider(secret)


def write_sqlite_memory(path: Path, *, instance: str = "Depressionsbot", secret: bytes = b"a" * 32, memory_id: str = "mem_1") -> None:
    backend = SQLiteAccountMemoryBackend(
        instance_name=instance,
        provider=provider(secret),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=path, fallback_path=None),
    )
    account_id = "a" * 128
    backend.write_entries(account_id, [{"id": memory_id, "user_text": memory_id, "keywords": [memory_id]}])
    backend.write_index(account_id, {"scope": "account", "index": {"entries": {memory_id: {}}}})


def read_sqlite_entry_ids(path: Path, *, instance: str = "Depressionsbot", secret: bytes = b"a" * 32) -> list[str]:
    backend = SQLiteAccountMemoryBackend(
        instance_name=instance,
        provider=provider(secret),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=path, fallback_path=None),
    )
    return [str(entry.get("id")) for entry in backend.read_entries("a" * 128)]


def test_sqlite_backup_sync_validates_and_preserves_old_secondary(tmp_path: Path) -> None:
    accounts_root = tmp_path / "instances" / "Depressionsbot" / "data" / "accounts"
    primary = accounts_root / "Account_Memory.sqlite3"
    secondary = accounts_root / "Account_Memory.backup.sqlite3"
    write_sqlite_memory(primary, memory_id="mem_primary")
    write_sqlite_memory(secondary, memory_id="mem_old_secondary")

    result = sqlite_backup_sync.sync_account_memory_sqlite_backup(
        accounts_root=accounts_root,
        provider=provider(),
    )

    assert result.copied is True
    assert result.decrypt_checked is True
    assert result.account_payloads_checked == 1
    assert result.secondary_backups_created >= 1
    assert read_sqlite_entry_ids(secondary) == ["mem_primary"]
    backup_dir = Path(result.secondary_backup_dir)
    assert (backup_dir / "Account_Memory.backup.sqlite3").exists()


def test_sqlite_backup_sync_refuses_unreadable_primary_without_overwriting_secondary(tmp_path: Path) -> None:
    accounts_root = tmp_path / "instances" / "Depressionsbot" / "data" / "accounts"
    primary = accounts_root / "Account_Memory.sqlite3"
    secondary = accounts_root / "Account_Memory.backup.sqlite3"
    write_sqlite_memory(primary, secret=b"b" * 32, memory_id="mem_wrong_secret")
    write_sqlite_memory(secondary, secret=b"a" * 32, memory_id="mem_old_secondary")

    with pytest.raises(RuntimeError, match="payload_not_decryptable"):
        sqlite_backup_sync.sync_account_memory_sqlite_backup(
            accounts_root=accounts_root,
            provider=provider(b"a" * 32),
        )

    assert read_sqlite_entry_ids(secondary, secret=b"a" * 32) == ["mem_old_secondary"]
    assert not list(accounts_root.glob(".pre-account-memory-backup-sync-*"))


def test_sqlite_backup_sync_refuses_incomplete_primary_schema(tmp_path: Path) -> None:
    primary = tmp_path / "primary.sqlite3"
    secondary = tmp_path / "secondary.sqlite3"
    sqlite3.connect(primary).close()

    with pytest.raises(RuntimeError, match="primary_schema_missing:memory_entries"):
        sqlite_backup_sync.sync_account_memory_sqlite_backup(
            accounts_root=tmp_path,
            primary=primary,
            secondary=secondary,
            provider=provider(),
            decrypt_check=False,
        )

    assert not secondary.exists()


def test_sqlite_backup_sync_checks_collection_payloads(tmp_path: Path) -> None:
    accounts_root = tmp_path / "instances" / "Depressionsbot" / "data" / "accounts"
    primary = accounts_root / "Account_Memory.sqlite3"
    backend = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(b"a" * 32),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=primary, fallback_path=None),
    )
    account_id = "a" * 128
    backend.write_collection(
        account_id,
        "proactive_outbox",
        [{"id": "pro_1", "message_text": "Backup testen", "status": "queued"}],
    )

    with sqlite3.connect(primary) as connection:
        connection.execute(
            """
            UPDATE account_jsonl_collections
            SET payload_ciphertext = ?
            WHERE account_id = ? AND collection = ?
            """,
            (b"broken", account_id, "proactive_outbox"),
        )

    with pytest.raises(RuntimeError, match="payload_not_decryptable"):
        sqlite_backup_sync.sync_account_memory_sqlite_backup(
            accounts_root=accounts_root,
            provider=provider(b"a" * 32),
        )


def test_sqlite_backup_sync_refuses_unreadable_collection_primary_without_overwriting_secondary(tmp_path: Path) -> None:
    accounts_root = tmp_path / "instances" / "Depressionsbot" / "data" / "accounts"
    primary = accounts_root / "Account_Memory.sqlite3"
    secondary = accounts_root / "Account_Memory.backup.sqlite3"
    primary_backend = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(b"a" * 32),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=primary, fallback_path=None),
    )
    secondary_backend = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(b"a" * 32),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=secondary, fallback_path=None),
    )
    account_id = "a" * 128
    primary_backend.write_collection(
        account_id,
        "proactive_outbox",
        [{"id": "pro_1", "message_text": "Backup broken", "status": "queued"}],
    )
    secondary_backend.write_collection(
        account_id,
        "proactive_outbox",
        [{"id": "pro_2", "message_text": "Backup old", "status": "queued"}],
    )

    with sqlite3.connect(primary) as connection:
        connection.execute(
            """
            UPDATE account_jsonl_collections
            SET payload_ciphertext = ?
            WHERE account_id = ? AND collection = ?
            """,
            (b"broken", account_id, "proactive_outbox"),
        )

    with pytest.raises(RuntimeError, match="payload_not_decryptable"):
        sqlite_backup_sync.sync_account_memory_sqlite_backup(
            accounts_root=accounts_root,
            provider=provider(b"a" * 32),
        )

    with sqlite3.connect(secondary) as connection:
        rows = connection.execute(
            """
            SELECT COUNT(*)
            FROM account_jsonl_collections
            WHERE instance_name = ? AND account_id = ? AND collection = ?
            """,
            ("Depressionsbot", "a" * 128, "proactive_outbox"),
        ).fetchone()
    assert int(rows[0]) == 1
    assert not list(accounts_root.glob(".pre-account-memory-backup-sync-*"))


def test_sqlite_backup_sync_checks_collection_accounts_for_payload_count(tmp_path: Path) -> None:
    accounts_root = tmp_path / "instances" / "Depressionsbot" / "data" / "accounts"
    primary = accounts_root / "Account_Memory.sqlite3"
    backend = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(b"a" * 32),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=primary, fallback_path=None),
    )
    account_id = "a" * 128
    backend.write_collection(
        account_id,
        "proactive_outbox",
        [
            {
                "id": "pro_1",
                "message_text": "Backup zählen",
                "status": "queued",
                "updated_at": "2026-06-14T12:00:00+00:00",
            }
        ],
    )

    result = sqlite_backup_sync.sync_account_memory_sqlite_backup(
        accounts_root=accounts_root,
        provider=provider(b"a" * 32),
    )

    assert result.account_payloads_checked == 1
    assert result.copied is True


def test_sqlite_backup_sync_deduplicates_accounts_with_collection_and_entry_payloads(tmp_path: Path) -> None:
    accounts_root = tmp_path / "instances" / "Depressionsbot" / "data" / "accounts"
    primary = accounts_root / "Account_Memory.sqlite3"
    write_sqlite_memory(primary, memory_id="mem_primary")

    mixed_backend = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(b"a" * 32),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=primary, fallback_path=None),
    )
    mixed_backend.write_collection(
        "a" * 128,
        "proactive_outbox",
        [{"id": "pro_1", "message_text": "Backup dedupe", "status": "queued"}],
    )

    result = sqlite_backup_sync.sync_account_memory_sqlite_backup(
        accounts_root=accounts_root,
        provider=provider(b"a" * 32),
    )

    assert result.account_payloads_checked == 1


def test_sqlite_backup_sync_resolves_relative_paths_under_accounts_root(tmp_path: Path, monkeypatch) -> None:
    accounts_root = tmp_path / "instances" / "Depressionsbot" / "data" / "accounts"
    primary = accounts_root / "primary.sqlite3"
    write_sqlite_memory(primary, memory_id="mem_relative")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", "primary.sqlite3")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH", "backup/secondary.sqlite3")

    result = sqlite_backup_sync.sync_account_memory_sqlite_backup(
        accounts_root=accounts_root,
        provider=provider(),
        dry_run=True,
    )

    assert Path(result.primary) == primary.resolve()
    assert Path(result.secondary) == (accounts_root / "backup" / "secondary.sqlite3").resolve()


def test_sqlite_backup_sync_rejects_alias_primary_and_secondary(tmp_path: Path) -> None:
    primary = tmp_path / "primary.sqlite3"
    write_sqlite_memory(primary)

    with pytest.raises(AccountStoreError, match="must point to different files"):
        sqlite_backup_sync.sync_account_memory_sqlite_backup(
            accounts_root=tmp_path,
            primary=primary,
            secondary=primary,
            provider=provider(),
            decrypt_check=False,
        )


def test_sqlite_backup_sync_rejects_hardlinked_primary_and_secondary(tmp_path: Path) -> None:
    primary = tmp_path / "primary.sqlite3"
    secondary = tmp_path / "secondary.sqlite3"
    write_sqlite_memory(primary)
    secondary.hardlink_to(primary)

    with pytest.raises(AccountStoreError, match="must not be hardlinks"):
        sqlite_backup_sync.sync_account_memory_sqlite_backup(
            accounts_root=tmp_path,
            primary=primary,
            secondary=secondary,
            provider=provider(),
            decrypt_check=False,
        )
