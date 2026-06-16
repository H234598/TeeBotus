from __future__ import annotations

from pathlib import Path

from TeeBotus.admin.account_memory_recovery import build_account_memory_recovery_report, main as recovery_main
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
    sources = {source["name"]: source for source in account["sources"]}
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
