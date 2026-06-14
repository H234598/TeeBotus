from __future__ import annotations

from pathlib import Path

from TeeBotus.admin.accounts_report import build_accounts_admin_report, render_text_report
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider


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
