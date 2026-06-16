from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

import pytest

import scripts.import_legacy_user_memory as legacy_import
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
    bad_store._write_account_profile(
        unreadable_profile_account,
        {
            "schema_version": 2,
            "instance": "Depressionsbot",
            "account_id": unreadable_profile_account,
            "status": "active",
            "linked_identities": [telegram_identity_key("395935293")],
        },
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
    rehearsal_root = tmp_path / "rehearsal-instances"
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


def test_legacy_user_memory_import_rehearsal_requires_apply(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setattr(legacy_import, "_detect_running_teebotus_processes", lambda: [])
    legacy_root = tmp_path / "legacy"
    target_root = tmp_path / "target"
    rehearsal_root = tmp_path / "rehearsal-instances"
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

    first_count = legacy_import._reset_unreadable_account_store(accounts_root)
    (accounts_root / "Account_Index.json").write_text('{"new": 2}', encoding="utf-8")
    second_count = legacy_import._reset_unreadable_account_store(accounts_root)

    backup_dirs = sorted(accounts_root.glob(".pre-legacy-user-memory-account-store-reset-*"))
    assert first_count == 1
    assert second_count == 1
    assert len(backup_dirs) == 2
    assert [path.name for path in backup_dirs] == [
        ".pre-legacy-user-memory-account-store-reset-20260616T120000Z",
        ".pre-legacy-user-memory-account-store-reset-20260616T120000Z-001",
    ]
    assert (backup_dirs[0] / "Account_Index.json").read_text(encoding="utf-8") == '{"old": 1}'
    assert (backup_dirs[1] / "Account_Index.json").read_text(encoding="utf-8") == '{"new": 2}'
