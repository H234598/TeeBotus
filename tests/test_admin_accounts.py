from __future__ import annotations

import json
from pathlib import Path

from TeeBotus.admin import __main__ as admin_entrypoint
from TeeBotus.admin.account_memory_recovery import (
    build_account_memory_recovery_report,
    main as recovery_main,
    quarantine_unreadable_account_metadata,
    quarantine_unrecoverable_account_memory,
)
from TeeBotus.admin.account_memory_recovery import render_text_report as render_memory_recovery_text_report
from TeeBotus.admin.accounts_report import build_accounts_admin_report, render_text_report
from TeeBotus.runtime.accounts import ACCOUNT_MEMORY_KEY_PURPOSE, AccountStore, StaticSecretProvider
from TeeBotus.runtime.sqlite_memory import SQLiteAccountMemoryBackend, SQLiteMemoryConfig


def provider() -> StaticSecretProvider:
    return StaticSecretProvider(b"a" * 32)


def make_instance(tmp_path: Path, name: str = "Depressionsbot") -> Path:
    instance_dir = tmp_path / name
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## Hilfe\n", encoding="utf-8")
    return instance_dir


def test_admin_report_counts_accounts_and_identities(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:2", display_label="Ada")
    store.register_account(account_id)

    report = build_accounts_admin_report(instances_dir=tmp_path, provider=provider())

    assert report["schema_version"] == 2
    assert report["totals"]["account_dirs"] == 1
    assert report["totals"]["indexed_accounts"] == 1
    assert report["totals"]["linked_identities"] == 1
    instance_report = report["instances"][0]
    assert set(report["totals"]) == {"account_dirs", "indexed_accounts", "linked_identities", "store_errors"}
    assert set(instance_report) == {
        "account_store",
        "accounts_root",
        "data_dir",
        "data_dir_exists",
        "instance",
        "instance_dir",
        "instruction_file_exists",
    }


def test_admin_report_marks_store_errors(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    accounts_root.mkdir(parents=True)
    (accounts_root / "Account_Index.json").write_text("not encrypted\n", encoding="utf-8")

    report = build_accounts_admin_report(instances_dir=tmp_path, provider=provider())

    assert report["totals"]["store_errors"] == 1
    store_report = report["instances"][0]["account_store"]
    assert store_report["readable"] is False
    assert store_report["errors"]


def test_text_report_contains_only_account_store_summary(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    store.resolve_or_create_account("telegram:user:2", display_label="Ada")

    report = build_accounts_admin_report(instances_dir=tmp_path, provider=provider())
    text = render_text_report(report)

    assert "TeeBotus Account Admin Report" in text
    assert "account_directories: 1" in text
    assert "linked_identities: 1" in text
    assert "account_directories: 1" in text


def test_memory_recovery_report_finds_readable_fallback_when_primary_key_drifted(tmp_path: Path, caplog) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    store = AccountStore(accounts_root, "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:2", display_label="Ada")
    primary = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=StaticSecretProvider(b"b" * 32),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=accounts_root / "Account_Memory.sqlite3", fallback_path=None),
    )
    primary.write_entries(account_id, [{"id": "mem_bad", "user_text": "Primary"}])
    primary.write_index(account_id, {"scope": "account", "index": {}})
    fallback = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=accounts_root / "Account_Memory.backup.sqlite3", fallback_path=None),
    )
    fallback.write_entries(account_id, [{"id": "mem_ok", "user_text": "Fallback"}])
    fallback.write_index(account_id, {"scope": "account", "index": {}})

    with caplog.at_level("CRITICAL", logger="TeeBotus"):
        report = build_account_memory_recovery_report(instances_dir=tmp_path, provider=provider())

    account = report["instances"][0]["accounts"][0]
    assert report["scope"] == "account_memory"
    sources = {source["name"]: source for source in account["sources"]}
    assert sources["sqlite_primary"]["payload_kind"] == "encrypted_account_memory"
    assert account["recoverable"] is True
    assert account["recovery_status"] == "recoverable"
    assert account["recommendation"] == "Recover from readable source(s): sqlite_fallback."
    assert sources["sqlite_primary"]["readable"] is False
    assert sources["sqlite_primary"]["raw_entries"] == 1
    assert sources["sqlite_fallback"]["readable"] is True
    assert sources["sqlite_fallback"]["entries"] == 1
    assert report["totals"]["recoverable_accounts"] == 1
    assert report["totals"]["unrecoverable_accounts"] == 0
    assert report["totals"]["empty_accounts"] == 0
    assert report["totals"]["no_source_accounts"] == 0
    assert "account-memory skipped corrupt rows" not in caplog.text


def test_memory_recovery_cli_writes_json_without_secret_payloads(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    store.resolve_or_create_account("telegram:user:2", display_label="Ada")
    output = tmp_path / "recovery.json"

    result = recovery_main(["--instances-dir", str(tmp_path), "--format", "json", "--output", str(output)])

    assert result == 0
    text = output.read_text(encoding="utf-8")
    assert "schema_version" in text
    assert "Ada" not in text
    assert "telegram:user:2" not in text


def test_memory_recovery_report_marks_unrecoverable_key_drift(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    store = AccountStore(accounts_root, "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:2", display_label="Ada")
    primary = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=StaticSecretProvider(b"b" * 32),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=accounts_root / "Account_Memory.sqlite3", fallback_path=None),
    )
    primary.write_entries(account_id, [{"id": "mem_bad", "user_text": "Primary"}])
    primary.write_index(account_id, {"scope": "account", "index": {}})

    report = build_account_memory_recovery_report(instances_dir=tmp_path, provider=provider())

    account = report["instances"][0]["accounts"][0]
    assert account["recoverable"] is False
    assert account["recovery_status"] == "unrecoverable"
    assert "restore the matching old secret" in account["recommendation"]
    assert report["totals"]["recoverable_accounts"] == 0
    assert report["totals"]["unrecoverable_accounts"] == 1
    assert report["totals"]["empty_accounts"] == 0


def test_memory_recovery_quarantines_unrecoverable_sqlite_rows(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    store = AccountStore(accounts_root, "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:2", display_label="Ada")
    primary_path = accounts_root / "Account_Memory.sqlite3"
    primary = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=StaticSecretProvider(b"b" * 32),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=primary_path, fallback_path=None),
    )
    primary.write_entries(account_id, [{"id": "mem_bad", "user_text": "Primary"}])
    primary.write_index(account_id, {"scope": "account", "index": {}})
    report = build_account_memory_recovery_report(instances_dir=tmp_path, provider=provider())
    quarantine_dir = tmp_path / "quarantine"

    result = quarantine_unrecoverable_account_memory(report, apply=True, quarantine_dir=quarantine_dir, running_processes=[])

    assert result["status"] == "applied"
    assert result["scope"] == "account_memory"
    assert result["payload_kind"] == "encrypted_account_memory"
    assert result["totals"]["accounts_quarantined"] == 1
    assert result["totals"]["snapshots_created"] == 1
    assert result["totals"]["sqlite_rows_quarantined"] == 2
    follow_up = build_account_memory_recovery_report(instances_dir=tmp_path, provider=provider())
    account = follow_up["instances"][0]["accounts"][0]
    assert account["recovery_status"] == "empty"
    snapshot = quarantine_dir / "Depressionsbot" / next((quarantine_dir / "Depressionsbot").iterdir()).name / "sqlite_snapshots" / "Account_Memory.sqlite3"
    assert snapshot.exists()
    snapshot_backend = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=StaticSecretProvider(b"b" * 32),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=snapshot, fallback_path=None),
    )
    assert snapshot_backend.read_entries(account_id)[0]["id"] == "mem_bad"


def test_admin_entrypoint_returns_json_dependency_error(monkeypatch, capsys) -> None:
    def fail_import(name: str):
        raise ModuleNotFoundError("No module named 'cryptography'", name="cryptography")

    monkeypatch.setattr(admin_entrypoint.importlib, "import_module", fail_import)

    result = admin_entrypoint.main(["memory-recovery", "--format", "json"])

    assert result == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["missing_dependency"] == "cryptography"


def test_memory_recovery_quarantine_refuses_running_runtime(tmp_path: Path) -> None:
    make_instance(tmp_path)
    report = build_account_memory_recovery_report(instances_dir=tmp_path, provider=provider())

    result = quarantine_unrecoverable_account_memory(
        report,
        apply=True,
        quarantine_dir=tmp_path / "quarantine",
        running_processes=[{"pid": "123", "cmdline": "python3 -m TeeBotus --all"}],
    )

    assert result["status"] == "blocked"
    assert result["apply_safety"]["apply_allowed_now"] is False


def test_memory_recovery_quarantines_unreadable_account_metadata(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    bad_store = AccountStore(accounts_root, "Depressionsbot", StaticSecretProvider(b"b" * 32))
    bad_store.resolve_or_create_account("telegram:user:2", display_label="Ada")
    assert build_accounts_admin_report(instances_dir=tmp_path, provider=provider())["totals"]["store_errors"] == 1

    result = quarantine_unreadable_account_metadata(
        instances_dir=tmp_path,
        provider=provider(),
        apply=True,
        quarantine_dir=tmp_path / "quarantine",
        running_processes=[],
    )

    assert result["status"] == "applied"
    assert result["totals"]["instances_with_unreadable_metadata"] == 1
    assert result["totals"]["items_quarantined"] == 3
    assert result["totals"]["account_dirs_quarantined"] == 1
    follow_up = build_accounts_admin_report(instances_dir=tmp_path, provider=provider())
    assert follow_up["totals"]["store_errors"] == 0
    assert follow_up["totals"]["account_dirs"] == 0
    instance_quarantine = tmp_path / "quarantine" / "Depressionsbot" / "metadata"
    timestamp_dir = next(instance_quarantine.iterdir())
    assert (timestamp_dir / "Account_Index.json").exists()
    assert (timestamp_dir / "Account_Identities.json").exists()
    assert (timestamp_dir / "accounts").exists()
    assert (timestamp_dir / "manifest.json").exists()


def test_memory_recovery_metadata_quarantine_refuses_running_runtime(tmp_path: Path) -> None:
    make_instance(tmp_path)

    result = quarantine_unreadable_account_metadata(
        instances_dir=tmp_path,
        provider=provider(),
        apply=True,
        quarantine_dir=tmp_path / "quarantine",
        running_processes=[{"pid": "123", "cmdline": "python3 -m TeeBotus --all"}],
    )

    assert result["status"] == "blocked"
    assert result["apply_safety"]["apply_allowed_now"] is False


def test_memory_recovery_report_counts_empty_accounts(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    store.resolve_or_create_account("telegram:user:2", display_label="Ada")

    report = build_account_memory_recovery_report(instances_dir=tmp_path, provider=provider())

    account = report["instances"][0]["accounts"][0]
    assert account["recoverable"] is False
    assert account["recovery_status"] == "empty"
    assert report["totals"]["recoverable_accounts"] == 0
    assert report["totals"]["unrecoverable_accounts"] == 0
    assert report["totals"]["empty_accounts"] == 1


def test_memory_recovery_text_report_is_markdown_structured(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    store.resolve_or_create_account("telegram:user:2", display_label="Ada")

    report = build_account_memory_recovery_report(instances_dir=tmp_path, provider=provider())
    text = render_memory_recovery_text_report(report)

    assert "# TeeBotus Account-Memory Recovery Report" in text
    assert "## Totals" in text
    assert "## Instance: Depressionsbot" in text
    assert "- recovery_status: `empty`" in text
    assert text.index("## Totals") < text.index("## Instance: Depressionsbot")


def test_memory_recovery_report_counts_legacy_plaintext_import_sources(tmp_path: Path) -> None:
    target_dir = tmp_path / "target"
    legacy_dir = tmp_path / "legacy"
    make_instance(target_dir)
    user_dir = legacy_dir / "Depressionsbot" / "data" / "users" / "395935293"
    user_dir.mkdir(parents=True)
    (user_dir / "User_Memory_Entries.jsonl").write_text(
        '{"id":"legacy_1","user_text":"A","bot_text":"B"}\n'
        '{"id":"legacy_2","user_text":"C","bot_text":"D"}\n',
        encoding="utf-8",
    )

    report = build_account_memory_recovery_report(instances_dir=target_dir, legacy_instances_dir=legacy_dir, provider=provider())

    assert report["totals"]["legacy_plaintext_sources"] == 1
    assert report["totals"]["legacy_plaintext_entries"] == 2
    legacy = report["instances"][0]["legacy_plaintext_import"]
    assert legacy["sources"] == 1
    assert legacy["entries"] == 2
    assert "--replace-unreadable-account-metadata" in legacy["dry_run_command"]
    assert "--json-output" in legacy["dry_run_command"]
    assert "--markdown-output" in legacy["dry_run_command"]
    assert "teebotus-legacy-import-preflight-Depressionsbot.json" in legacy["dry_run_command"]
    assert "--apply" in legacy["apply_command"]
    assert "--replace-unreadable" in legacy["apply_command"]
    assert "--replace-unreadable-account-metadata" in legacy["apply_command"]


def test_memory_recovery_report_resolves_legacy_backup_root(tmp_path: Path) -> None:
    target_dir = tmp_path / "target"
    backup_root = tmp_path / "TeeBotus.bak2"
    make_instance(target_dir)
    users_dir = backup_root / "instances.bak" / "Depressionsbot" / "data" / "users"
    for user_id in ("395935293", "1682346404"):
        user_dir = users_dir / user_id
        user_dir.mkdir(parents=True)
        (user_dir / "User_Memory_Entries.jsonl").write_text('{"id":"legacy_1","user_text":"A"}\n', encoding="utf-8")

    report = build_account_memory_recovery_report(instances_dir=target_dir, legacy_instances_dir=backup_root, provider=provider())

    legacy = report["instances"][0]["legacy_plaintext_import"]
    assert legacy["requested_legacy_instances_dir"] == str(backup_root)
    assert legacy["legacy_instances_dir"] == str(backup_root / "instances.bak")
    assert legacy["sources"] == 2
    assert legacy["entries"] == 2
    assert "--apply" in legacy["apply_command"]


def test_memory_recovery_report_sanitizes_legacy_preflight_artifact_name(tmp_path: Path) -> None:
    target_dir = tmp_path / "target"
    legacy_dir = tmp_path / "legacy"
    make_instance(target_dir, name="Demo Bot")
    user_dir = legacy_dir / "Demo Bot" / "data" / "users" / "395935293"
    user_dir.mkdir(parents=True)
    (user_dir / "User_Memory_Entries.jsonl").write_text('{"id":"legacy_1","user_text":"A"}\n', encoding="utf-8")

    report = build_account_memory_recovery_report(instances_dir=target_dir, legacy_instances_dir=legacy_dir, provider=provider())

    legacy = report["instances"][0]["legacy_plaintext_import"]
    assert "--instance 'Demo Bot'" in legacy["dry_run_command"]
    assert "--instance 'Demo Bot'" in legacy["apply_command"]
    assert "teebotus-legacy-import-preflight-Demo_Bot.json" in legacy["dry_run_command"]
    assert "teebotus-legacy-import-preflight-Demo_Bot.md" in legacy["dry_run_command"]


def test_memory_recovery_report_ignores_encrypted_legacy_sources(tmp_path: Path) -> None:
    target_dir = tmp_path / "target"
    legacy_dir = tmp_path / "legacy"
    make_instance(target_dir)
    user_dir = legacy_dir / "Depressionsbot" / "data" / "users" / "395935293"
    user_dir.mkdir(parents=True)
    (user_dir / "User_Memory_Entries.jsonl").write_text('{"version":1,"nonce":"n","ciphertext":"c"}\n', encoding="utf-8")

    report = build_account_memory_recovery_report(instances_dir=target_dir, legacy_instances_dir=legacy_dir, provider=provider())

    legacy = report["instances"][0]["legacy_plaintext_import"]
    assert legacy["sources"] == 0
    assert legacy["entries"] == 0
    assert legacy["encrypted_sources"] == 1
