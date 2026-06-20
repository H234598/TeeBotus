from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

import pytest

import scripts.import_legacy_user_memory as legacy_import
import TeeBotus.runtime.accounts as accounts_module
from scripts.import_legacy_user_memory import import_legacy_user_memory, main as import_main
from TeeBotus.runtime.accounts import (
    ACCOUNT_KEYRING_FILENAME,
    ACCOUNT_MEMORY_KEY_PURPOSE,
    INSTANCE_MAPPING_KEY_PURPOSE,
    AccountStore,
    AccountStoreError,
    StaticSecretProvider,
    telegram_identity_key,
)
from TeeBotus.runtime.sqlite_memory import SQLiteAccountMemoryBackend, SQLiteMemoryConfig


def provider(secret: bytes = b"a" * 32) -> StaticSecretProvider:
    return StaticSecretProvider(secret)


class PurposeSecretProvider:
    def __init__(self, secrets: dict[str, bytes], default: bytes = b"a" * 32) -> None:
        self.secrets = dict(secrets)
        self.default = default

    def get_secret(self, instance_name: str, purpose: str) -> bytes:
        secret = self.secrets.get(purpose, self.default)
        if len(secret) != 32:
            raise AssertionError("test secret must be 32 bytes")
        return secret


def keyring_manifest_provider(accounts_root: Path, instance_name: str, delegate: PurposeSecretProvider):
    return accounts_module._KeyringManifestSecretProvider(  # noqa: SLF001
        instance_name=instance_name,
        root=accounts_root,
        delegate=delegate,
    )


def write_account_keyring_manifest(accounts_root: Path, instance_name: str, secrets: dict[str, bytes]) -> None:
    purposes = {}
    for purpose, secret in secrets.items():
        purposes[purpose] = {
            "algorithm": "HMAC-SHA256",
            "created_at": "2026-06-01T00:00:00+00:00",
            "fingerprint": accounts_module._instance_secret_fingerprint(instance_name, purpose, secret),  # noqa: SLF001
            "purpose": purpose,
        }
    (accounts_root / ACCOUNT_KEYRING_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "instance": instance_name,
                "purposes": purposes,
                "updated_at": "2026-06-01T00:00:00+00:00",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def write_legacy_entries(
    root: Path,
    *,
    instance: str = "Depressionsbot",
    user_id: str = "395935293",
    memory_id: str = "legacy_mem_1",
) -> Path:
    user_dir = root / instance / "data" / "users" / user_id
    user_dir.mkdir(parents=True)
    rows = [
        {
            "id": memory_id,
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
    (user_dir / "User_Memory_Index.json").write_text(json.dumps({"index": {"entries": {memory_id: {}}}}), encoding="utf-8")
    return user_dir


def write_empty_legacy_entries(root: Path, *, instance: str = "Depressionsbot", user_id: str = "395935293") -> Path:
    user_dir = root / instance / "data" / "users" / user_id
    user_dir.mkdir(parents=True)
    (user_dir / "User_Memory_Entries.jsonl").write_text("", encoding="utf-8")
    return user_dir


def write_raw_legacy_entries(root: Path, text: str, *, instance: str = "Depressionsbot", user_id: str = "395935293") -> Path:
    user_dir = root / instance / "data" / "users" / user_id
    user_dir.mkdir(parents=True)
    (user_dir / "User_Memory_Entries.jsonl").write_text(text, encoding="utf-8")
    return user_dir


def write_legacy_entries_without_ids(root: Path, *, instance: str = "Depressionsbot", user_id: str = "395935293") -> Path:
    user_dir = root / instance / "data" / "users" / user_id
    user_dir.mkdir(parents=True)
    rows = [
        {
            "created_at": "2026-06-01T00:00:00+00:00",
            "updated_at": "2026-06-01T00:00:00+00:00",
            "sender": {"id": user_id},
            "source": {"legacy": True},
            "user_text": "Legacy text without id A",
            "bot_text": "",
            "keywords": ["legacy", "missing-id"],
            "related_ids": [],
        },
        {
            "created_at": "2026-06-01T00:00:01+00:00",
            "updated_at": "2026-06-01T00:00:01+00:00",
            "sender": {"id": user_id},
            "source": {"legacy": True},
            "user_text": "Legacy text without id B",
            "bot_text": "",
            "keywords": ["legacy", "missing-id"],
            "related_ids": [],
        },
    ]
    (user_dir / "User_Memory_Entries.jsonl").write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
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

    assert not (target_root / "Depressionsbot").exists()
    assert stats.sources == 1
    assert stats.entries_seen == 1
    assert stats.entries_imported == 1
    assert stats.events[0]["action"] == "would-import"
    assert stats.events[0]["entries"] == 1
    store = AccountStore(target_root / "Depressionsbot" / "data" / "accounts", "Depressionsbot", secret_provider=provider())
    assert store.get_account_for_identity(telegram_identity_key("395935293")) is None


def test_legacy_user_memory_import_main_expands_tilde_legacy_instances_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root)

    result = import_main(
        [
            "--legacy-instances-dir",
            "~/legacy",
            "--target-instances-dir",
            str(target_root),
            "--json-output",
            str(tmp_path / "import.json"),
            "--markdown-output",
            str(tmp_path / "import.md"),
        ]
    )

    assert result == 0
    assert (tmp_path / "import.json").exists()
    assert (tmp_path / "import.md").exists()
    payload = json.loads((tmp_path / "import.json").read_text(encoding="utf-8"))
    assert payload["requested_legacy_instances_dir"] == str(legacy_root)
    assert payload["legacy_instances_dir"] == str(legacy_root)
    assert not (tmp_path / "target" / "Depressionsbot").exists()


def test_legacy_user_memory_import_main_expands_tilde_report_outputs_and_creates_parents(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root)
    report_json = Path("~/teebotus-import-output/legacy-import.json")
    report_markdown = Path("~/teebotus-import-output/legacy-import.md")

    result = import_main(
        [
            "--legacy-instances-dir",
            str(legacy_root),
            "--target-instances-dir",
            str(target_root),
            "--json-output",
            str(report_json),
            "--markdown-output",
            str(report_markdown),
        ]
    )

    assert result == 0
    assert (tmp_path / "teebotus-import-output" / "legacy-import.json").exists()
    assert (tmp_path / "teebotus-import-output" / "legacy-import.md").exists()


def test_legacy_user_memory_import_main_normalizes_instance_filter(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root, instance="Depressionsbot", user_id="111")
    write_legacy_entries(legacy_root, instance="Otherbot", user_id="222")
    report = tmp_path / "legacy-import.json"

    result = import_main(
        [
            "--legacy-instances-dir",
            str(legacy_root),
            "--target-instances-dir",
            str(target_root),
            "--instance",
            "",
            "--instance",
            "   ",
            "--instance",
            "Depressionsbot",
            "--instance",
            "Depressionsbot",
            "--json-output",
            str(report),
        ]
    )

    assert result == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["instances"] == ["Depressionsbot"]
    assert payload["totals"]["sources"] == 1
    assert payload["totals"]["entries_imported"] == 1


def test_legacy_user_memory_import_function_normalizes_instance_filter(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root, instance="Depressionsbot", user_id="333")

    stats = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=False,
        instances=("  ", "Depressionsbot", "", "Depressionsbot"),
        provider=provider(),
    )

    assert stats.sources == 1


def test_legacy_user_memory_import_empty_source_does_not_create_account_or_reset_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_empty_legacy_entries(legacy_root)
    accounts_root = target_root / "Depressionsbot" / "data" / "accounts"
    bad_store = AccountStore(accounts_root, "Depressionsbot", secret_provider=provider(b"b" * 32))
    bad_store.resolve_or_create_account(telegram_identity_key("already-broken"))

    stats = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=True,
        replace_unreadable_account_metadata=True,
        provider=provider(),
    )

    assert stats.sources == 1
    assert stats.skipped_sources == 1
    assert stats.entries_seen == 0
    assert stats.entries_imported == 0
    assert stats.accounts_created == 0
    assert stats.unreadable_metadata == 0
    assert stats.account_store_resets == 0
    assert stats.events == [
        {
            "instance": "Depressionsbot",
            "legacy_user_id": "395935293",
            "identity": "telegram:user:395935293",
            "account_id": "<not-created>",
            "entries": 0,
            "imported": 0,
            "action": "skip-empty",
            "target_unreadable": False,
            "metadata_unreadable": False,
            "account_created": False,
            "error": "",
        }
    ]
    assert not list(accounts_root.glob(".pre-legacy-user-memory-account-store-reset-*"))


def test_legacy_user_memory_import_skips_malformed_source_without_opening_store(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_raw_legacy_entries(legacy_root, '{"id": "ok"}\nnot-json\n')
    accounts_root = target_root / "Depressionsbot" / "data" / "accounts"
    bad_store = AccountStore(accounts_root, "Depressionsbot", secret_provider=provider(b"b" * 32))
    bad_store.resolve_or_create_account(telegram_identity_key("already-broken"))

    stats = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=True,
        replace_unreadable_account_metadata=True,
        provider=provider(),
    )

    assert stats.sources == 1
    assert stats.skipped_sources == 1
    assert stats.malformed_sources == 1
    assert stats.encrypted_sources == 0
    assert stats.entries_seen == 0
    assert stats.entries_imported == 0
    assert stats.accounts_created == 0
    assert stats.unreadable_metadata == 0
    assert stats.account_store_resets == 0
    assert stats.events[0]["action"] == "skip-malformed-source"
    assert stats.events[0]["account_id"] == "<not-created>"
    assert stats.events[0]["error"]
    assert not list(accounts_root.glob(".pre-legacy-user-memory-account-store-reset-*"))


def test_legacy_user_memory_import_skips_encrypted_source_without_opening_store(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_raw_legacy_entries(legacy_root, '{"version":1,"nonce":"n","ciphertext":"c"}\n')
    accounts_root = target_root / "Depressionsbot" / "data" / "accounts"
    bad_store = AccountStore(accounts_root, "Depressionsbot", secret_provider=provider(b"b" * 32))
    bad_store.resolve_or_create_account(telegram_identity_key("already-broken"))

    stats = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=True,
        replace_unreadable_account_metadata=True,
        provider=provider(),
    )

    assert stats.sources == 1
    assert stats.skipped_sources == 1
    assert stats.malformed_sources == 0
    assert stats.encrypted_sources == 1
    assert stats.entries_seen == 0
    assert stats.entries_imported == 0
    assert stats.accounts_created == 0
    assert stats.unreadable_metadata == 0
    assert stats.account_store_resets == 0
    assert stats.events[0]["action"] == "skip-encrypted-source"
    assert stats.events[0]["account_id"] == "<not-created>"
    assert stats.events[0]["error"]
    assert not list(accounts_root.glob(".pre-legacy-user-memory-account-store-reset-*"))


def test_legacy_user_memory_import_rejects_missing_legacy_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")

    with pytest.raises(SystemExit, match="legacy instances directory does not exist"):
        import_legacy_user_memory(
            legacy_instances_dir=tmp_path / "missing",
            target_instances_dir=tmp_path / "target",
            apply=False,
            provider=provider(),
        )


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


def test_legacy_user_memory_import_deletes_verified_source_artifact_inside_repo(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    repo_root = tmp_path / "TeeBotus"
    monkeypatch.setattr(legacy_import, "REPO_ROOT", repo_root)
    legacy_root = repo_root / "instances.bak"
    target_root = repo_root / "instances"
    user_dir = write_legacy_entries(legacy_root)

    stats = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=True,
        provider=provider(),
    )

    assert stats.imported_sources == 1
    assert stats.imported_source_artifacts_deleted == 1
    assert stats.imported_source_artifacts_kept_external == 0
    assert stats.imported_source_artifact_delete_failures == 0
    assert not user_dir.exists()
    assert stats.events[0]["source_cleanup"]["status"] == "deleted"


def test_legacy_user_memory_import_keeps_verified_source_artifact_outside_repo(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    repo_root = tmp_path / "TeeBotus"
    monkeypatch.setattr(legacy_import, "REPO_ROOT", repo_root)
    legacy_root = tmp_path / "external-backup"
    target_root = repo_root / "instances"
    user_dir = write_legacy_entries(legacy_root)

    stats = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=True,
        provider=provider(),
    )

    assert stats.imported_sources == 1
    assert stats.imported_source_artifacts_deleted == 0
    assert stats.imported_source_artifacts_kept_external == 1
    assert stats.imported_source_artifact_delete_failures == 0
    assert user_dir.exists()
    assert stats.events[0]["source_cleanup"]["status"] == "kept-external"


def test_legacy_user_memory_import_dry_run_keeps_source_artifact_inside_repo(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    repo_root = tmp_path / "TeeBotus"
    monkeypatch.setattr(legacy_import, "REPO_ROOT", repo_root)
    legacy_root = repo_root / "instances.bak"
    target_root = repo_root / "instances"
    user_dir = write_legacy_entries(legacy_root)

    stats = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=False,
        provider=provider(),
    )

    assert stats.imported_sources == 1
    assert stats.imported_source_artifacts_deleted == 0
    assert user_dir.exists()
    assert "source_cleanup" not in stats.events[0]


def test_legacy_user_memory_import_scopes_colliding_legacy_ids_in_same_account(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root, user_id="111", memory_id="shared_legacy_id")
    linked_user_dir = write_legacy_entries(legacy_root, user_id="222", memory_id="shared_legacy_id")
    linked_entry = {
        "id": "link_to_shared",
        "created_at": "2026-06-01T00:00:01+00:00",
        "updated_at": "2026-06-01T00:00:01+00:00",
        "sender": {"id": "222"},
        "source": {"legacy": True},
        "user_text": "Second legacy user links to shared memory",
        "bot_text": "",
        "keywords": ["legacy", "link"],
        "related_ids": ["shared_legacy_id"],
        "supports": [{"target_id": "shared_legacy_id"}],
        "relations": [{"type": "related", "target_id": "shared_legacy_id"}],
    }
    with (linked_user_dir / "User_Memory_Entries.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(linked_entry, sort_keys=True) + "\n")
    accounts_root = target_root / "Depressionsbot" / "data" / "accounts"
    store = AccountStore(accounts_root, "Depressionsbot", secret_provider=provider())
    account_id = store.resolve_or_create_account(telegram_identity_key("111"))
    _account_id, account_secret = store.rotate_secret(account_id)
    store.link_identity(telegram_identity_key("222"), account_id, account_secret)

    first = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=True,
        provider=provider(),
    )
    second = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=True,
        provider=provider(),
    )

    entries = store.read_memory_entries(account_id)
    entry_ids = sorted(entry["id"] for entry in entries)
    source_user_ids = sorted(entry["source"]["legacy_user_id"] for entry in entries)
    by_original_id = {entry["source"]["legacy_original_id"]: entry for entry in entries}
    scoped_id = next(entry_id for entry_id in entry_ids if entry_id.startswith("legacy_"))
    link_entry = by_original_id["link_to_shared"]
    index = store.read_memory_index(account_id)
    graph = index["index"]["graph"]["links"]

    assert first.entries_imported == 3
    assert second.entries_imported == 0
    assert len(entries) == 3
    assert "shared_legacy_id" in entry_ids
    assert "link_to_shared" in entry_ids
    assert source_user_ids == ["111", "222", "222"]
    assert {entry["source"]["legacy_original_id"] for entry in entries} == {"shared_legacy_id", "link_to_shared"}
    assert link_entry["related_ids"] == [scoped_id]
    assert link_entry["supports"] == [scoped_id]
    assert link_entry["relations"][0]["target_id"] == scoped_id
    assert graph["related_ids"]["link_to_shared"] == [scoped_id]
    assert graph["supports"]["link_to_shared"] == [scoped_id]
    assert store.check_structured_memory_index(account_id).ok


def test_legacy_user_memory_import_assigns_stable_ids_to_missing_legacy_ids(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries_without_ids(legacy_root, user_id="333")

    first = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=True,
        provider=provider(),
    )
    second = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=True,
        provider=provider(),
    )

    store = AccountStore(target_root / "Depressionsbot" / "data" / "accounts", "Depressionsbot", secret_provider=provider())
    account_id = store.get_account_for_identity(telegram_identity_key("333"))
    assert account_id
    entries = store.read_memory_entries(account_id)
    entry_ids = sorted(entry["id"] for entry in entries)
    import_keys = sorted(entry["source"]["legacy_import_key"] for entry in entries)

    assert first.entries_imported == 2
    assert second.entries_imported == 0
    assert len(entries) == 2
    assert all(entry_id.startswith("legacy_") for entry_id in entry_ids)
    assert len(set(entry_ids)) == 2
    assert all(import_key.startswith("missing_id_") for import_key in import_keys)
    assert len(set(import_keys)) == 2
    assert {entry["source"]["legacy_original_id"] for entry in entries} == {""}
    assert store.check_structured_memory_index(account_id).ok


def test_legacy_user_memory_import_verifies_imported_identity_mapping_and_profile(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    accounts_root = tmp_path / "target" / "Depressionsbot" / "data" / "accounts"
    store = AccountStore(accounts_root, "Depressionsbot", secret_provider=provider())
    identity = telegram_identity_key("395935293")
    account_id = store.resolve_or_create_account(identity)

    legacy_import._verify_imported_account_identity(
        store,
        identity,
        account_id,
        instance_name="Depressionsbot",
        legacy_user_id="395935293",
    )
    with pytest.raises(SystemExit, match="identity verification failed"):
        legacy_import._verify_imported_account_identity(
            store,
            telegram_identity_key("1284666801"),
            account_id,
            instance_name="Depressionsbot",
            legacy_user_id="1284666801",
        )

    profile = store._read_account_profile(account_id)
    profile["linked_identities"] = []
    store._write_account_profile(account_id, profile)
    with pytest.raises(SystemExit, match="profile verification failed"):
        legacy_import._verify_imported_account_identity(
            store,
            identity,
            account_id,
            instance_name="Depressionsbot",
            legacy_user_id="395935293",
        )


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
    bad_fallback_backend = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(b"b" * 32),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=accounts_root / "Account_Memory.backup.sqlite3", fallback_path=None),
    )
    bad_fallback_backend.write_entries(account_id, [{"id": "bad", "user_text": "unreadable"}])
    bad_fallback_backend.write_index(account_id, {"scope": "account", "index": {}})

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
    bad_account_id = bad_store.resolve_or_create_account(telegram_identity_key("395935293"))

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
    assert replaced.events[0]["action"] == "import-after-metadata-reset"
    assert replaced.events[0]["metadata_unreadable"] is True
    assert replaced.events[0]["metadata_reset_existing_accounts"] == [bad_account_id]
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


def test_legacy_user_memory_import_pre_resets_when_account_profile_is_unreadable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root, user_id="395935293")
    write_legacy_entries(legacy_root, user_id="1284666801")
    accounts_root = target_root / "Depressionsbot" / "data" / "accounts"
    good_store = AccountStore(accounts_root, "Depressionsbot", secret_provider=provider())
    unreadable_profile_account = good_store.resolve_or_create_account(telegram_identity_key("395935293"))
    bad_store = AccountStore(accounts_root, "Depressionsbot", secret_provider=provider(b"b" * 32))
    profile_path = bad_store.account_dir(unreadable_profile_account) / "Account_Profile.json"
    profile_path.write_bytes(
        bad_store.vault.encrypt(
            json.dumps(
                {
                    "schema_version": 2,
                    "instance": "Depressionsbot",
                    "account_id": unreadable_profile_account,
                    "status": "active",
                    "linked_identities": [telegram_identity_key("395935293")],
                },
                sort_keys=True,
            ).encode("utf-8"),
            kind="Account_Profile.json",
        )
    )

    stats = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=True,
        replace_unreadable_account_metadata=True,
        provider=provider(),
    )

    assert stats.account_store_resets == 1
    assert stats.metadata_backups_created >= 1
    store = AccountStore(accounts_root, "Depressionsbot", secret_provider=provider())
    imported_ids = [
        store.get_account_for_identity(telegram_identity_key("1284666801")),
        store.get_account_for_identity(telegram_identity_key("395935293")),
    ]
    assert all(imported_ids)
    assert unreadable_profile_account not in imported_ids
    for account_id in imported_ids:
        assert store.check_structured_memory_index(account_id).ok
    assert sorted(entry["source"]["legacy_user_id"] for account_id in imported_ids for entry in store.read_memory_entries(account_id)) == [
        "1284666801",
        "395935293",
    ]


def test_legacy_user_memory_import_dry_run_simulates_unreadable_account_profile_reset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root, user_id="395935293")
    accounts_root = target_root / "Depressionsbot" / "data" / "accounts"
    good_store = AccountStore(accounts_root, "Depressionsbot", secret_provider=provider())
    unreadable_profile_account = good_store.resolve_or_create_account(telegram_identity_key("395935293"))
    bad_store = AccountStore(accounts_root, "Depressionsbot", secret_provider=provider(b"b" * 32))
    profile_path = bad_store.account_dir(unreadable_profile_account) / "Account_Profile.json"
    profile_path.write_bytes(
        bad_store.vault.encrypt(
            json.dumps(
                {
                    "schema_version": 2,
                    "instance": "Depressionsbot",
                    "account_id": unreadable_profile_account,
                    "status": "active",
                    "linked_identities": [telegram_identity_key("395935293")],
                },
                sort_keys=True,
            ).encode("utf-8"),
            kind="Account_Profile.json",
        )
    )

    stats = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=False,
        replace_unreadable_account_metadata=True,
        provider=provider(),
    )

    assert stats.account_store_resets == 0
    assert stats.metadata_backups_created == 0
    assert stats.unreadable_metadata == 1
    assert stats.accounts_existing == 0
    assert stats.accounts_created == 1
    assert stats.events[0]["account_id"] == "<new>"
    assert stats.events[0]["action"] == "would-import-after-metadata-reset"
    assert stats.events[0]["metadata_unreadable"] is True
    assert stats.events[0]["metadata_reset_existing_accounts"] == [unreadable_profile_account]


def test_legacy_user_memory_import_dry_run_can_simulate_metadata_replacement(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root)
    accounts_root = target_root / "Depressionsbot" / "data" / "accounts"
    bad_store = AccountStore(accounts_root, "Depressionsbot", secret_provider=provider(b"b" * 32))
    bad_account_id = bad_store.resolve_or_create_account(telegram_identity_key("395935293"))

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
    assert stats.events[0]["action"] == "would-import-after-metadata-reset"
    assert stats.events[0]["metadata_unreadable"] is True
    assert stats.events[0]["metadata_reset_existing_accounts"] == [bad_account_id]
    report = legacy_import._build_import_report(
        stats,
        mode="dry-run",
        legacy_instances_dir=legacy_root,
        requested_legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        instances=(),
        backend="sqlite",
        replace_unreadable=False,
        replace_unreadable_account_metadata=True,
        backup_current=True,
    )
    markdown = legacy_import._render_markdown_report(report)
    assert "action=`would-import-after-metadata-reset`" in markdown
    assert "flags=`metadata_unreadable,account_created`" in markdown
    assert f"metadata_reset_accounts=`{bad_account_id[:12]}`" in markdown


def test_legacy_user_memory_import_treats_memory_keyring_mismatch_as_unreadable_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root)
    accounts_root = target_root / "Depressionsbot" / "data" / "accounts"
    mapping_key = b"m" * 32
    old_memory_key = b"o" * 32
    current_memory_key = b"n" * 32
    writer = PurposeSecretProvider(
        {
            INSTANCE_MAPPING_KEY_PURPOSE: mapping_key,
            ACCOUNT_MEMORY_KEY_PURPOSE: old_memory_key,
        }
    )
    store = AccountStore(accounts_root, "Depressionsbot", secret_provider=writer)
    account_id = store.resolve_or_create_account(telegram_identity_key("395935293"))
    store.write_memory_entries(account_id, [{"id": "old_mem", "user_text": "old encrypted memory"}])
    write_account_keyring_manifest(
        accounts_root,
        "Depressionsbot",
        {
            INSTANCE_MAPPING_KEY_PURPOSE: mapping_key,
            ACCOUNT_MEMORY_KEY_PURPOSE: old_memory_key,
        },
    )
    guarded_provider = keyring_manifest_provider(
        accounts_root,
        "Depressionsbot",
        PurposeSecretProvider(
            {
                INSTANCE_MAPPING_KEY_PURPOSE: mapping_key,
                ACCOUNT_MEMORY_KEY_PURPOSE: current_memory_key,
            }
        ),
    )

    with pytest.raises(AccountStoreError, match="account-structured-memory-key"):
        AccountStore(accounts_root, "Depressionsbot", secret_provider=guarded_provider)

    stats = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=False,
        replace_unreadable=True,
        replace_unreadable_account_metadata=True,
        provider=guarded_provider,
    )

    assert stats.unreadable_metadata == 0
    assert stats.unreadable_targets == 1
    assert stats.accounts_existing == 1
    assert stats.accounts_created == 0
    assert stats.entries_imported == 1
    assert stats.events[0]["account_id"] == account_id
    assert stats.events[0]["action"] == "would-import"
    assert stats.events[0]["metadata_unreadable"] is False
    assert stats.events[0]["target_unreadable"] is True


def test_legacy_user_memory_import_apply_repairs_memory_keyring_and_preserves_readable_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root)
    accounts_root = target_root / "Depressionsbot" / "data" / "accounts"
    mapping_key = b"m" * 32
    stale_memory_key = b"s" * 32
    current_memory_key = b"c" * 32
    current_delegate = PurposeSecretProvider(
        {
            INSTANCE_MAPPING_KEY_PURPOSE: mapping_key,
            ACCOUNT_MEMORY_KEY_PURPOSE: current_memory_key,
        }
    )
    store = AccountStore(accounts_root, "Depressionsbot", secret_provider=current_delegate)
    account_id = store.resolve_or_create_account(telegram_identity_key("395935293"))
    store.write_memory_entries(account_id, [{"id": "current_mem", "user_text": "current readable memory"}])
    stale_state_store = AccountStore(
        accounts_root,
        "Depressionsbot",
        secret_provider=PurposeSecretProvider(
            {
                INSTANCE_MAPPING_KEY_PURPOSE: mapping_key,
                ACCOUNT_MEMORY_KEY_PURPOSE: stale_memory_key,
            }
        ),
    )
    stale_state_store.account_memory_vault.write_json(
        stale_state_store.account_dir(account_id) / "Agent_State.json",
        {"stale": True},
    )
    write_account_keyring_manifest(
        accounts_root,
        "Depressionsbot",
        {
            INSTANCE_MAPPING_KEY_PURPOSE: mapping_key,
            ACCOUNT_MEMORY_KEY_PURPOSE: stale_memory_key,
        },
    )
    guarded_provider = keyring_manifest_provider(accounts_root, "Depressionsbot", current_delegate)

    stats = import_legacy_user_memory(
        legacy_instances_dir=legacy_root,
        target_instances_dir=target_root,
        apply=True,
        replace_unreadable=True,
        provider=guarded_provider,
    )

    strict_store = AccountStore(accounts_root, "Depressionsbot", secret_provider=guarded_provider)
    entries = strict_store.read_memory_entries(account_id)
    assert stats.unreadable_targets == 1
    assert stats.memory_keyring_repairs == 1
    assert stats.entries_imported == 1
    assert [entry["id"] for entry in entries] == ["current_mem", "legacy_mem_1"]
    assert strict_store.check_structured_memory_index(account_id).ok
    assert not (strict_store.account_dir(account_id) / "Agent_State.json").exists()
    assert list(strict_store.account_dir(account_id).glob(".pre-legacy-user-memory-state-replace-*/Agent_State.json"))


def test_legacy_user_memory_import_writes_json_and_markdown_reports(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setattr(legacy_import, "_detect_running_teebotus_processes", lambda: [])
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
    assert payload["totals"]["malformed_sources"] == 0
    assert payload["totals"]["encrypted_sources"] == 0
    assert payload["totals"]["entries_imported"] == 1
    assert payload["events"][0]["identity"] == "telegram:user:395935293"
    assert payload["events"][0]["action"] == "would-import"
    assert payload["apply_safety"]["apply_allowed_now"] is True
    assert payload["apply_safety"]["apply_requires_stopped_bot"] is False
    assert payload["apply_safety"]["running_bot_process_count"] == 0
    assert "Legacy user text" not in json_output.read_text(encoding="utf-8")
    assert "Legacy user text" not in markdown
    assert "entries_imported" in markdown
    assert "Apply Safety" in markdown
    assert markdown.index("## Totals") < markdown.index("- entries_imported:")
    assert markdown.index("- entries_imported:") < markdown.index("## Events")


def test_legacy_user_memory_import_dry_run_reports_running_bot_apply_block(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setattr(
        legacy_import,
        "_detect_running_teebotus_processes",
        lambda: [{"pid": "123", "cmdline": "python3 -m TeeBotus --all --channels telegram,signal"}],
    )
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
    assert payload["apply_safety"]["apply_allowed_now"] is False
    assert payload["apply_safety"]["apply_requires_stopped_bot"] is True
    assert payload["apply_safety"]["running_bot_process_count"] == 1
    assert payload["apply_safety"]["running_bot_processes"][0]["pid"] == "123"
    assert "stop bot/proactive jobs" in payload["apply_safety"]["message"]
    assert "Running Bot Processes" in markdown
    assert "pid=`123`" in markdown
    assert markdown.index("## Totals") < markdown.index("- entries_imported:")
    assert markdown.index("- entries_imported:") < markdown.index("### Running Bot Processes")
    assert markdown.index("### Running Bot Processes") < markdown.index("## Events")


def test_legacy_user_memory_import_apply_report_still_blocks_running_bot_without_override(tmp_path: Path) -> None:
    report = legacy_import._build_import_report(
        legacy_import.ImportStats(),
        mode="apply",
        legacy_instances_dir=tmp_path / "legacy",
        requested_legacy_instances_dir=tmp_path / "legacy",
        target_instances_dir=tmp_path / "target",
        instances=(),
        backend="sqlite",
        replace_unreadable=True,
        replace_unreadable_account_metadata=True,
        backup_current=True,
        allow_running_bot=False,
        running_processes=[{"pid": "123", "cmdline": "python3 -m TeeBotus --all"}],
    )

    assert report["apply_safety"]["apply_allowed_now"] is False
    assert report["apply_safety"]["apply_requires_stopped_bot"] is True


def test_legacy_user_memory_runtime_process_detection_ignores_admin_false_positives() -> None:
    assert legacy_import._looks_like_running_teebotus_runtime("python3 -m teebotus --all --channels telegram")
    assert legacy_import._looks_like_running_teebotus_runtime("bash -lc cd repo && python3 -m teebotus --all")
    assert legacy_import._looks_like_running_teebotus_runtime("python3 -m teebotus.proactive --dispatch --plan --tool-plan")
    assert legacy_import._looks_like_running_teebotus_runtime("/home/user/.local/bin/teebotus-proactive --once")
    assert not legacy_import._looks_like_running_teebotus_runtime("python3 -m teebotus.admin memory-recovery")
    assert not legacy_import._looks_like_running_teebotus_runtime("python3 scripts/import_legacy_user_memory.py --legacy-instances-dir backup")
    assert not legacy_import._looks_like_running_teebotus_runtime("python3 -m pytest tests/test_legacy_user_memory_import.py")


def test_legacy_user_memory_import_dry_run_does_not_create_missing_secret(tmp_path: Path, monkeypatch) -> None:
    created_with: list[bool] = []

    class FakeSecretProvider(StaticSecretProvider):
        def __init__(self, *, create_if_missing: bool = True) -> None:
            created_with.append(create_if_missing)
            super().__init__(b"a" * 32)

    monkeypatch.setattr(legacy_import, "SecretToolInstanceSecretProvider", FakeSecretProvider)
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root)

    result = import_main(
        [
            "--legacy-instances-dir",
            str(legacy_root),
            "--target-instances-dir",
            str(target_root),
        ]
    )

    assert result == 0
    assert created_with == [False]


def test_legacy_user_memory_import_apply_does_not_create_missing_secret(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(legacy_import, "_detect_running_teebotus_processes", lambda: [])
    created_with: list[bool] = []

    class FakeSecretProvider(StaticSecretProvider):
        def __init__(self, *, create_if_missing: bool = True) -> None:
            created_with.append(create_if_missing)
            super().__init__(b"a" * 32)

    monkeypatch.setattr(legacy_import, "SecretToolInstanceSecretProvider", FakeSecretProvider)
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root)

    result = import_main(
        [
            "--legacy-instances-dir",
            str(legacy_root),
            "--target-instances-dir",
            str(target_root),
            "--apply",
        ]
    )

    assert result == 0
    assert created_with == [False]


def test_legacy_user_memory_import_accepts_backup_root_and_selects_best_instances_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    backup_root = tmp_path / "TeeBotus.bak2"
    target_root = tmp_path / "target"
    write_legacy_entries(backup_root / "instances", user_id="111")
    write_legacy_entries(backup_root / "instances.bak", user_id="111")
    write_legacy_entries(backup_root / "instances.bak", user_id="222")
    json_output = tmp_path / "import.json"

    result = import_main(
        [
            "--legacy-instances-dir",
            str(backup_root),
            "--target-instances-dir",
            str(target_root),
            "--json-output",
            str(json_output),
        ]
    )

    assert result == 0
    payload = json.loads(json_output.read_text(encoding="utf-8"))
    assert payload["requested_legacy_instances_dir"] == str(backup_root)
    assert payload["legacy_instances_dir"] == str(backup_root / "instances.bak")
    assert payload["totals"]["sources"] == 2
    assert payload["totals"]["entries_imported"] == 2


def test_legacy_user_memory_import_apply_refuses_running_bot(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setattr(
        legacy_import,
        "_detect_running_teebotus_processes",
        lambda: [{"pid": "123", "cmdline": "python3 -m TeeBotus --all --channels telegram,signal"}],
    )
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root)

    result = import_main(
        [
            "--legacy-instances-dir",
            str(legacy_root),
            "--target-instances-dir",
            str(target_root),
            "--apply",
        ]
    )

    assert result == 2
    assert "Refusing legacy memory import --apply" in capsys.readouterr().err
    store = AccountStore(target_root / "Depressionsbot" / "data" / "accounts", "Depressionsbot", secret_provider=provider())
    assert store.get_account_for_identity(telegram_identity_key("395935293")) is None


def test_legacy_user_memory_import_apply_block_writes_preflight_reports(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setattr(
        legacy_import,
        "_detect_running_teebotus_processes",
        lambda: [{"pid": "123", "cmdline": "python3 -m TeeBotus --all --channels telegram,signal"}],
    )
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root)
    json_output = tmp_path / "blocked.json"
    markdown_output = tmp_path / "blocked.md"

    result = import_main(
        [
            "--legacy-instances-dir",
            str(legacy_root),
            "--target-instances-dir",
            str(target_root),
            "--apply",
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(markdown_output),
        ]
    )

    assert result == 2
    assert "Refusing legacy memory import --apply" in capsys.readouterr().err
    payload = json.loads(json_output.read_text(encoding="utf-8"))
    markdown = markdown_output.read_text(encoding="utf-8")
    assert payload["mode"] == "apply-blocked"
    assert payload["apply_safety"]["apply_allowed_now"] is False
    assert payload["apply_safety"]["apply_requires_stopped_bot"] is True
    assert payload["apply_safety"]["running_bot_process_count"] == 1
    assert payload["totals"]["entries_imported"] == 1
    assert payload["events"][0]["action"] == "would-import"
    assert "mode: `apply-blocked`" in markdown
    assert "Running Bot Processes" in markdown
    store = AccountStore(target_root / "Depressionsbot" / "data" / "accounts", "Depressionsbot", secret_provider=provider())
    assert store.get_account_for_identity(telegram_identity_key("395935293")) is None


def test_legacy_user_memory_import_apply_can_override_running_bot_guard(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setattr(
        legacy_import,
        "_detect_running_teebotus_processes",
        lambda: [{"pid": "123", "cmdline": "python3 -m TeeBotus --all --channels telegram,signal"}],
    )
    monkeypatch.setattr(legacy_import, "SecretToolInstanceSecretProvider", lambda **_kwargs: provider())
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    write_legacy_entries(legacy_root)

    result = import_main(
        [
            "--legacy-instances-dir",
            str(legacy_root),
            "--target-instances-dir",
            str(target_root),
            "--apply",
            "--allow-running-bot",
        ]
    )

    assert result == 0
    store = AccountStore(target_root / "Depressionsbot" / "data" / "accounts", "Depressionsbot", secret_provider=provider())
    account_id = store.get_account_for_identity(telegram_identity_key("395935293"))
    assert account_id


def test_legacy_user_memory_import_rehearsal_apply_writes_only_copy_while_bot_runs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setattr(
        legacy_import,
        "_detect_running_teebotus_processes",
        lambda: [{"pid": "123", "cmdline": "python3 -m TeeBotus --all --channels telegram,signal"}],
    )
    monkeypatch.setattr(legacy_import, "SecretToolInstanceSecretProvider", lambda **_kwargs: provider())
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    rehearsal_root = tmp_path / "teebotus-rehearsal-instances"
    write_legacy_entries(legacy_root)
    (target_root / "Depressionsbot" / "data").mkdir(parents=True)
    json_output = tmp_path / "rehearsal.json"
    markdown_output = tmp_path / "rehearsal.md"

    result = import_main(
        [
            "--legacy-instances-dir",
            str(legacy_root),
            "--target-instances-dir",
            str(target_root),
            "--rehearsal-copy-dir",
            str(rehearsal_root),
            "--replace-unreadable-account-metadata",
            "--apply",
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(markdown_output),
        ]
    )

    assert result == 0
    live_store = AccountStore(target_root / "Depressionsbot" / "data" / "accounts", "Depressionsbot", secret_provider=provider())
    rehearsal_store = AccountStore(rehearsal_root / "Depressionsbot" / "data" / "accounts", "Depressionsbot", secret_provider=provider())
    assert live_store.get_account_for_identity(telegram_identity_key("395935293")) is None
    rehearsal_account_id = rehearsal_store.get_account_for_identity(telegram_identity_key("395935293"))
    assert rehearsal_account_id
    assert [entry["id"] for entry in rehearsal_store.read_memory_entries(rehearsal_account_id)] == ["legacy_mem_1"]

    payload = json.loads(json_output.read_text(encoding="utf-8"))
    markdown = markdown_output.read_text(encoding="utf-8")
    assert payload["mode"] == "rehearsal-apply"
    assert payload["requested_target_instances_dir"] == str(target_root)
    assert payload["target_instances_dir"] == str(rehearsal_root)
    assert payload["options"]["rehearsal_active"] is True
    assert payload["options"]["rehearsal_copy_dir"] == str(rehearsal_root)
    assert payload["apply_safety"]["apply_allowed_now"] is True
    assert payload["apply_safety"]["apply_requires_stopped_bot"] is False
    assert "live TeeBotus data is not modified" in payload["apply_safety"]["message"]
    assert "rehearsal_active: `True`" in markdown


def test_legacy_user_memory_import_prepare_rehearsal_copy_dir_cleans_existing_directory(tmp_path: Path) -> None:
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    rehearsal_root = tmp_path / "rehearsal-root"
    rehearsal_root.mkdir(parents=True)
    (rehearsal_root / "old.txt").write_text("old", encoding="utf-8")

    result = legacy_import._prepare_rehearsal_target_copy(legacy_root, rehearsal_root)

    assert result == rehearsal_root
    assert rehearsal_root.exists()
    assert rehearsal_root.is_dir()
    assert not (rehearsal_root / "old.txt").exists()


def test_legacy_user_memory_import_prepare_rehearsal_copy_file_is_replaced(tmp_path: Path) -> None:
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    rehearsal_root = tmp_path / "rehearsal-root"
    rehearsal_root.write_text("old", encoding="utf-8")

    result = legacy_import._prepare_rehearsal_target_copy(legacy_root, rehearsal_root)

    assert result == rehearsal_root
    assert rehearsal_root.exists()
    assert rehearsal_root.is_dir()
    assert not (rehearsal_root / "old.txt").exists()


def test_legacy_user_memory_import_prepare_rehearsal_copy_broken_symlink_is_replaced(tmp_path: Path) -> None:
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    target_dir = tmp_path / "does-not-exist"
    rehearsal_link = tmp_path / "rehearsal-link"
    rehearsal_link.symlink_to(target_dir)

    result = legacy_import._prepare_rehearsal_target_copy(legacy_root, rehearsal_link)

    assert result == rehearsal_link
    assert rehearsal_link.exists()
    assert rehearsal_link.is_dir()
    assert not rehearsal_link.is_symlink()


def test_legacy_user_memory_import_prepare_rehearsal_copy_rejects_same_path_as_source(tmp_path: Path) -> None:
    legacy_root = tmp_path / "teebotus-instances"
    legacy_root.mkdir(parents=True)

    with pytest.raises(SystemExit):
        legacy_import._prepare_rehearsal_target_copy(legacy_root, legacy_root)
    assert legacy_root.exists()
    assert legacy_root.is_dir()


def test_legacy_user_memory_import_prepare_rehearsal_copy_rejects_nested_path_within_source(tmp_path: Path) -> None:
    legacy_root = tmp_path / "teebotus-instances"
    legacy_root.mkdir(parents=True)
    nested = legacy_root / "nested"

    with pytest.raises(SystemExit):
        legacy_import._prepare_rehearsal_target_copy(legacy_root, nested)
    assert nested.exists() is False


def test_legacy_user_memory_import_prepare_rehearsal_copy_rejects_parent_path_of_source(tmp_path: Path) -> None:
    source_root = tmp_path / "teebotus"
    source = source_root / "instances"
    source_root.mkdir(parents=True)
    source.mkdir()

    with pytest.raises(SystemExit):
        legacy_import._prepare_rehearsal_target_copy(source, source_root)
    assert source_root.exists()
    assert source.exists()


def test_legacy_user_memory_import_rehearsal_requires_apply(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setattr(legacy_import, "_detect_running_teebotus_processes", lambda: [])
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    rehearsal_root = tmp_path / "teebotus-rehearsal-instances"
    write_legacy_entries(legacy_root)
    target_root.mkdir()

    result = import_main(
        [
            "--legacy-instances-dir",
            str(legacy_root),
            "--target-instances-dir",
            str(target_root),
            "--rehearsal-copy-dir",
            str(rehearsal_root),
        ]
    )

    assert result == 2
    assert "requires --apply" in capsys.readouterr().err
    assert not rehearsal_root.exists()


def test_legacy_user_memory_import_rehearsal_rejects_unsafe_copy_dir(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    rehearsal_root = tmp_path / "rehearsal-instances"
    rehearsal_root.mkdir(parents=True)
    (rehearsal_root / "old.txt").write_text("old", encoding="utf-8")
    write_legacy_entries(legacy_root)

    result = import_main(
        [
            "--legacy-instances-dir",
            str(legacy_root),
            "--target-instances-dir",
            str(target_root),
            "--rehearsal-copy-dir",
            str(rehearsal_root),
        ]
    )

    assert result == 2
    assert "unsafe rehearsal copy dir" in capsys.readouterr().err
    assert rehearsal_root.exists()
    assert (rehearsal_root / "old.txt").exists()


def test_legacy_user_memory_import_sqlite_backups_are_unique_within_same_second(tmp_path: Path, monkeypatch) -> None:
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001
            return datetime(2026, 6, 16, 12, 0, tzinfo=tz or timezone.utc)

    monkeypatch.setattr(legacy_import, "datetime", FixedDatetime)
    accounts_root = tmp_path / "accounts"
    accounts_root.mkdir()
    sqlite_path = accounts_root / "Account_Memory.sqlite3"
    sqlite_path.write_text("first", encoding="utf-8")

    first_count = legacy_import._backup_sqlite_files(accounts_root)
    sqlite_path.write_text("second", encoding="utf-8")
    second_count = legacy_import._backup_sqlite_files(accounts_root)

    backup_dirs = sorted(accounts_root.glob(".pre-legacy-user-memory-import-*"))
    assert first_count == 1
    assert second_count == 1
    assert len(backup_dirs) == 2
    assert [path.name for path in backup_dirs] == [
        ".pre-legacy-user-memory-import-20260616T120000Z",
        ".pre-legacy-user-memory-import-20260616T120000Z-001",
    ]
    assert (backup_dirs[0] / "Account_Memory.sqlite3").read_text(encoding="utf-8") == "first"
    assert (backup_dirs[1] / "Account_Memory.sqlite3").read_text(encoding="utf-8") == "second"


def test_legacy_user_memory_import_metadata_reset_backups_are_unique_within_same_second(tmp_path: Path, monkeypatch) -> None:
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001
            return datetime(2026, 6, 16, 12, 0, tzinfo=tz or timezone.utc)

    monkeypatch.setattr(legacy_import, "datetime", FixedDatetime)
    accounts_root = tmp_path / "accounts"
    accounts_root.mkdir()
    (accounts_root / "Account_Index.json").write_text('{"old": 1}', encoding="utf-8")
    (accounts_root / "Account_Keyring.json").write_text('{"old_keyring": 1}', encoding="utf-8")

    first_count = legacy_import._reset_unreadable_account_store(accounts_root)
    (accounts_root / "Account_Index.json").write_text('{"new": 2}', encoding="utf-8")
    (accounts_root / "Account_Keyring.json").write_text('{"new_keyring": 2}', encoding="utf-8")
    second_count = legacy_import._reset_unreadable_account_store(accounts_root)

    backup_dirs = sorted(accounts_root.glob(".pre-legacy-user-memory-account-store-reset-*"))
    assert first_count == 2
    assert second_count == 2
    assert len(backup_dirs) == 2
    assert [path.name for path in backup_dirs] == [
        ".pre-legacy-user-memory-account-store-reset-20260616T120000Z",
        ".pre-legacy-user-memory-account-store-reset-20260616T120000Z-001",
    ]
    assert (backup_dirs[0] / "Account_Index.json").read_text(encoding="utf-8") == '{"old": 1}'
    assert (backup_dirs[1] / "Account_Index.json").read_text(encoding="utf-8") == '{"new": 2}'
    assert (backup_dirs[0] / "Account_Keyring.json").read_text(encoding="utf-8") == '{"old_keyring": 1}'
    assert (backup_dirs[1] / "Account_Keyring.json").read_text(encoding="utf-8") == '{"new_keyring": 2}'
