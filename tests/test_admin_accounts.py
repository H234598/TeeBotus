from __future__ import annotations

import json
from pathlib import Path

import pytest

from TeeBotus.admin import accounts as accounts_compat
from TeeBotus.admin import accounts_report
from TeeBotus.admin.__main__ import main as admin_main
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, telegram_identity_key


def provider() -> StaticSecretProvider:
    return StaticSecretProvider(b"r" * 32)


def make_instance(root: Path, name: str = "Depressionsbot") -> Path:
    instance_dir = root / name
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("# Bot_Verhalten.md\n", encoding="utf-8")
    return instance_dir


def test_admin_report_counts_accounts_identities_and_legacy_users(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1), display_label="Ada")
    store.register_account(account_id)

    legacy = instance_dir / "data" / "users" / "2"
    legacy.mkdir(parents=True)
    (legacy / "User_Memory_Index.json").write_text('{"keywords": {}}\n', encoding="utf-8")
    (legacy / "User_Memory_Entries.jsonl").write_text('{"text": "old"}\n', encoding="utf-8")

    report = accounts_report.build_accounts_admin_report(instances_dir=tmp_path, provider=provider())

    assert report["instance_count"] == 1
    assert report["totals"]["account_dirs"] == 1
    assert report["totals"]["indexed_accounts"] == 1
    assert report["totals"]["linked_identities"] == 1
    assert report["totals"]["legacy_user_dirs"] == 1
    assert report["totals"]["migration_create_account"] == 1
    instance_report = report["instances"][0]
    assert instance_report["account_store"]["encrypted_files_present"]["Account_Index.json"] is True
    user = instance_report["legacy_users"]["users"][0]
    assert user["sender_id"] == "2"
    assert user["recommended_action"] == "create_account_and_migrate"


def test_admin_report_marks_already_mapped_legacy_sender(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(2))
    legacy = instance_dir / "data" / "users" / "2"
    legacy.mkdir(parents=True)
    (legacy / "User_Habbits_and_behave.md").write_text("note\n", encoding="utf-8")

    report = accounts_report.build_accounts_admin_report(instances_dir=tmp_path, provider=provider())

    user = report["instances"][0]["legacy_users"]["users"][0]
    assert user["existing_account_id"] == account_id
    assert user["recommended_action"] == "already_mapped"
    assert report["totals"]["migration_already_mapped"] == 1


def test_admin_report_flags_encrypted_legacy_memory_for_live_key_migration(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    legacy = instance_dir / "data" / "users" / "3"
    legacy.mkdir(parents=True)
    (legacy / "User_Memory_Index.json").write_text('{"magic":"TMBMEM1","ciphertext":"x"}\n', encoding="utf-8")

    report = accounts_report.build_accounts_admin_report(instances_dir=tmp_path, provider=provider())

    user = report["instances"][0]["legacy_users"]["users"][0]
    assert user["encrypted_structured_memory"] is True
    assert user["recommended_action"] == "requires_live_legacy_key_migration"
    assert report["totals"]["migration_requires_live_legacy_key"] == 1


def test_admin_report_is_read_only_and_does_not_mutate_legacy_dirs(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    legacy = instance_dir / "data" / "users" / "2"
    legacy.mkdir(parents=True)
    (legacy / "User_Memory_Index.json").write_text("{}\n", encoding="utf-8")

    report = accounts_report.build_accounts_admin_report(instances_dir=tmp_path, provider=provider())

    assert legacy.exists()
    assert report["instances"][0]["migration_plan"]["actual_migration_implemented"] is False


def test_admin_migrate_without_dry_run_refuses_to_apply(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_instance(tmp_path)

    exit_code = accounts_report.main(["accounts", "migrate", "--instances-dir", str(tmp_path)])

    assert exit_code == 2
    assert "Actual account migration is intentionally not implemented" in capsys.readouterr().out


def test_admin_migrate_dry_run_prints_report(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    instance_dir = make_instance(tmp_path)
    legacy = instance_dir / "data" / "users" / "2"
    legacy.mkdir(parents=True)
    (legacy / "User_Memory_Index.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(accounts_report, "ReadOnlySecretToolInstanceSecretProvider", lambda: provider())
    exit_code = accounts_report.main(["accounts", "migrate", "--instances-dir", str(tmp_path), "--dry-run"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "TeeBotus Account Admin Report" in out
    assert "migration_would_create_accounts: 1" in out


def test_render_text_report_contains_summary(tmp_path: Path) -> None:
    make_instance(tmp_path, "Bote_der_Wahrheit")
    report = accounts_report.build_accounts_admin_report(instances_dir=tmp_path, provider=provider())

    text = accounts_report.render_text_report(report)

    assert "TeeBotus Account Admin Report" in text
    assert "Bote_der_Wahrheit" in text
    assert "migration_create_account" in text


def test_admin_cli_report_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_instance(tmp_path)

    monkeypatch.setattr(accounts_report, "ReadOnlySecretToolInstanceSecretProvider", lambda: provider())
    exit_code = admin_main(["accounts", "report", "--instances-dir", str(tmp_path), "--format", "json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["instance_count"] == 1


def test_admin_accounts_compat_entrypoint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_instance(tmp_path)

    monkeypatch.setattr(accounts_report, "ReadOnlySecretToolInstanceSecretProvider", lambda: provider())
    exit_code = accounts_compat.main(["report", "--instances-dir", str(tmp_path), "--format", "json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["instance_count"] == 1


def test_admin_report_does_not_create_accounts_directory_when_absent(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"

    report = accounts_report.build_accounts_admin_report(instances_dir=tmp_path, provider=provider())

    assert report["instance_count"] == 1
    assert not accounts_root.exists()


def test_live_migration_skip_on_unreadable_encrypted_legacy_does_not_create_account(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    legacy = instance_dir / "data" / "users" / "99"
    legacy.mkdir(parents=True)
    (legacy / "User_Memory_Index.json").write_text('{"magic":"TMBMEM1","ciphertext":"x"}\n', encoding="utf-8")
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    from TeeBotus.core.memory import LegacyMemoryMigrator

    result = LegacyMemoryMigrator(store, instance_dir).migrate_telegram_sender("99")

    assert result.migrated is False
    assert result.account_id == ""
    assert "legacy encrypted user memory" in result.skipped_reason
    assert legacy.exists()
    assert store.get_account_for_identity(telegram_identity_key(99)) is None
