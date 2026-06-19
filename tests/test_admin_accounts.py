from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from TeeBotus.admin import __main__ as admin_entrypoint
from TeeBotus.admin.account_memory_recovery import (
    _add_totals,
    _account_recovery_status,
    _looks_like_running_teebotus_runtime,
    _sqlite_account_ids,
    _sqlite_sources_for_unrecoverable_accounts,
    _sqlite_raw_counts,
    build_account_memory_recovery_report,
    main as recovery_main,
    quarantine_unreadable_account_metadata,
    quarantine_unrecoverable_account_memory,
)
from TeeBotus.admin.account_memory_recovery import render_text_report as render_memory_recovery_text_report
from TeeBotus.admin.accounts_report import build_accounts_admin_report, main as accounts_report_main, render_text_report, runtime_report_env
from TeeBotus.runtime.accounts import ACCOUNT_MEMORY_KEY_PURPOSE, INSTANCE_STATE_ACCOUNT_ID, AccountStore, StaticSecretProvider, signal_identity_key
from TeeBotus.runtime.sqlite_memory import SQLiteAccountMemoryBackend, SQLiteMemoryConfig


def provider() -> StaticSecretProvider:
    return StaticSecretProvider(b"a" * 32)


def make_instance(tmp_path: Path, name: str = "Depressionsbot") -> Path:
    instance_dir = tmp_path / name
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## Hilfe\n", encoding="utf-8")
    return instance_dir


def test_account_memory_recovery_runtime_detection_includes_module_proactive() -> None:
    assert _looks_like_running_teebotus_runtime("python3 -m teebotus --all --channels telegram,signal")
    assert _looks_like_running_teebotus_runtime("python3 -m teebotus.proactive --dispatch --plan --tool-plan")
    assert _looks_like_running_teebotus_runtime("/home/user/.local/bin/teebotus-proactive --once")
    assert not _looks_like_running_teebotus_runtime("python3 -m teebotus.admin.account_memory_recovery --help")


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
    assert report["totals"]["identity_warnings"] == 0
    instance_report = report["instances"][0]
    assert set(report["totals"]) == {"account_dirs", "identity_warnings", "indexed_accounts", "linked_identities", "store_errors"}
    assert set(instance_report) == {
        "account_store",
        "accounts_root",
        "data_dir",
        "data_dir_exists",
        "identity_health",
        "instance",
        "instance_dir",
        "instruction_file_exists",
        "runtime_slots",
    }
    assert instance_report["identity_health"] == {"status": "ok", "warning_count": 0, "warnings": []}


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


def test_text_report_contains_account_store_and_identity_summary(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    store.resolve_or_create_account("telegram:user:2", display_label="Ada")

    report = build_accounts_admin_report(instances_dir=tmp_path, provider=provider())
    text = render_text_report(report)

    assert "TeeBotus Account Admin Report" in text
    assert "account_directories: 1" in text
    assert "linked_identities: 1" in text
    assert "identities_by_channel: telegram=1" in text
    assert "runtime_slots_by_channel: <none>" in text
    assert "identity_health: ok" in text


def test_admin_report_warns_when_configured_signal_has_no_linked_identity(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    store.resolve_or_create_account("telegram:user:2", display_label="Ada")
    env = {
        "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT": "telegram-token",
        "SIGNAL_BOT_SERVICE_DEPRESSIONSBOT": "127.0.0.1:8080",
        "SIGNAL_BOT_PHONE_NUMBER_DEPRESSIONSBOT": "+491",
    }

    report = build_accounts_admin_report(instances_dir=tmp_path, provider=provider(), env=env)

    instance_report = report["instances"][0]
    assert instance_report["runtime_slots"]["configured_channels"] == {"signal": 1, "telegram": 1}
    assert instance_report["runtime_slots"]["configured_slot_labels_by_channel"] == {
        "signal": ["signal:1"],
        "telegram": ["telegram:1"],
    }
    assert report["totals"]["identity_warnings"] == 1
    identity_health = instance_report["identity_health"]
    assert identity_health["status"] == "warning"
    assert identity_health["warning_count"] == 1
    warning = identity_health["warnings"][0]
    assert warning["code"] == "runtime_channel_without_identity"
    assert warning["channel"] == "signal"
    assert warning["configured_runtime_slots"] == 1
    assert warning["configured_runtime_labels"] == ["signal:1"]
    assert warning["identity_channels"] == {"telegram": 1}
    assert warning["other_linked_identities"] == 1
    assert "Incoming chats on this channel will use a separate account" in warning["message"]
    assert warning["recommended_action"] == (
        "First run /register or /rotate_secret in an already linked private chat, then open a private "
        "signal chat and link the existing account with /login <account_id> <secret>; "
        "use /register there only for a deliberately separate account."
    )
    text = render_text_report(report)
    assert "runtime_slots_by_channel: signal=1, telegram=1" in text
    assert "identity_warning: runtime_channel_without_identity channel=signal slots=1 labels=signal:1 identities=telegram=1" in text
    assert "action=First run /register or /rotate_secret in an already linked private chat" in text
    assert "then open a private signal chat and link the existing account with /login <account_id> <secret>" in text


def test_admin_report_accepts_configured_signal_with_linked_identity(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:2", display_label="Ada")
    _, secret = store.register_account(account_id)
    store.link_identity(signal_identity_key(source_uuid="abc-def"), account_id, secret)
    env = {
        "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT": "telegram-token",
        "SIGNAL_BOT_SERVICE_DEPRESSIONSBOT": "127.0.0.1:8080",
        "SIGNAL_BOT_PHONE_NUMBER_DEPRESSIONSBOT": "+491",
    }

    report = build_accounts_admin_report(instances_dir=tmp_path, provider=provider(), env=env)

    instance_report = report["instances"][0]
    assert instance_report["account_store"]["identities_by_channel"] == {"signal": 1, "telegram": 1}
    assert instance_report["identity_health"] == {"status": "ok", "warning_count": 0, "warnings": []}
    assert report["totals"]["identity_warnings"] == 0


def test_accounts_report_runtime_env_loads_dotenv_without_overriding_environment(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT=dotenv-telegram",
                "SIGNAL_BOT_SERVICE_DEPRESSIONSBOT=127.0.0.1:8080",
                'SIGNAL_BOT_PHONE_NUMBER_DEPRESSIONSBOT="+491"',
            ]
        ),
        encoding="utf-8",
    )

    env = runtime_report_env(
        tmp_path / "instances",
        base_env={"TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT": "process-telegram"},
    )

    assert env["TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT"] == "process-telegram"
    assert env["SIGNAL_BOT_SERVICE_DEPRESSIONSBOT"] == "127.0.0.1:8080"
    assert env["SIGNAL_BOT_PHONE_NUMBER_DEPRESSIONSBOT"] == "+491"


def test_accounts_report_cli_uses_local_dotenv_for_runtime_slots(tmp_path: Path, monkeypatch, capsys) -> None:
    instances_dir = tmp_path / "instances"
    make_instance(instances_dir)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT=dotenv-telegram",
                "SIGNAL_BOT_SERVICE_DEPRESSIONSBOT=127.0.0.1:8080",
                "SIGNAL_BOT_PHONE_NUMBER_DEPRESSIONSBOT=+491",
            ]
        ),
        encoding="utf-8",
    )
    for key in (
        "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT",
        "SIGNAL_BOT_SERVICE_DEPRESSIONSBOT",
        "SIGNAL_BOT_PHONE_NUMBER_DEPRESSIONSBOT",
    ):
        monkeypatch.delenv(key, raising=False)

    result = accounts_report_main(["accounts", "report", "--instances-dir", str(instances_dir), "--format", "json"])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["instances"][0]["runtime_slots"]["configured_channels"] == {"signal": 1, "telegram": 1}


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


def test_memory_recovery_report_finds_readable_local_sqlite_snapshots(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    store = AccountStore(accounts_root, "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:2", display_label="Ada")
    snapshot_path = accounts_root / ".pre-account-memory-backup-sync-20260616T152426Z" / "Account_Memory.backup.sqlite3"
    snapshot = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=snapshot_path, fallback_path=None),
    )
    snapshot.write_entries(account_id, [{"id": "mem_snapshot", "user_text": "Snapshot"}])
    snapshot.write_index(account_id, {"scope": "account", "index": {}})

    report = build_account_memory_recovery_report(instances_dir=tmp_path, provider=provider())

    account = report["instances"][0]["accounts"][0]
    sources = {source["name"]: source for source in account["sources"]}
    snapshot_sources = [source for source in account["sources"] if source["name"].startswith("sqlite_snapshot_")]
    assert account["recoverable"] is True
    assert account["recovery_status"] == "recoverable"
    assert report["totals"]["recoverable_accounts"] == 1
    assert report["totals"]["empty_accounts"] == 0
    assert snapshot_sources
    assert snapshot_sources[0]["active"] is False
    assert snapshot_sources[0]["readable"] is True
    assert snapshot_sources[0]["entries"] == 1
    assert sources["json_files"]["active"] is True
    assert "sqlite_snapshot_" in account["recommendation"]


def test_memory_recovery_sqlite_snapshot_probe_does_not_create_sidecar_files(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    store = AccountStore(accounts_root, "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:2", display_label="Ada")
    snapshot_path = accounts_root / ".pre-account-memory-backup-sync-20260616T152426Z" / "Account_Memory.backup.sqlite3"
    snapshot = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=snapshot_path, fallback_path=None),
    )
    snapshot.write_entries(account_id, [{"id": "mem_snapshot", "user_text": "Snapshot"}])
    snapshot.write_index(account_id, {"scope": "account", "index": {}})
    with sqlite3.connect(snapshot_path) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    sidecars = [Path(str(snapshot_path) + suffix) for suffix in ("-wal", "-shm")]
    for sidecar in sidecars:
        if sidecar.exists():
            sidecar.unlink()

    build_account_memory_recovery_report(instances_dir=tmp_path, provider=provider())

    assert not any(sidecar.exists() for sidecar in sidecars)


def test_memory_recovery_sqlite_probes_do_not_create_missing_databases(tmp_path: Path) -> None:
    missing = tmp_path / "missing" / "Account_Memory.sqlite3"

    assert _sqlite_account_ids(missing) == set()
    assert _sqlite_raw_counts(missing, "Depressionsbot", "a" * 128) == (0, False, 0)
    assert not missing.exists()
    assert not missing.parent.exists()


def test_memory_recovery_report_counts_sqlite_collections_and_skips_instance_state_account(tmp_path: Path, monkeypatch) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    store = AccountStore(accounts_root, "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:2", display_label="Ada")
    store.write_agent_state(account_id, {"proactive": {"enabled": True}})
    store.write_instance_json_state(
        "Version_Notifications.json",
        "version_notifications",
        {"versions": {"1.0.3": {"sent_identities": ["telegram:user:2"]}}},
    )

    report = build_account_memory_recovery_report(instances_dir=tmp_path, provider=provider())

    assert _sqlite_account_ids(accounts_root / "Account_Memory.sqlite3") == {account_id}
    assert INSTANCE_STATE_ACCOUNT_ID not in _sqlite_account_ids(accounts_root / "Account_Memory.sqlite3")
    assert len(report["instances"][0]["accounts"]) == 1
    account = report["instances"][0]["accounts"][0]
    assert account["account_id"] == account_id
    assert account["recoverable"] is True
    assert account["recovery_status"] == "recoverable"
    source = next(source for source in account["sources"] if source["name"] == "sqlite_primary")
    assert source["collections"] == 1
    assert source["raw_collections"] == 1
    assert source["entries"] == 0
    assert source["index_present"] is False


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


def test_memory_recovery_report_treats_partially_readable_sqlite_as_recoverable(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    store = AccountStore(accounts_root, "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:2", display_label="Ada")
    primary_path = accounts_root / "Account_Memory.sqlite3"
    primary = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=primary_path, fallback_path=None),
    )
    primary.write_entries(
        account_id,
        [
            {"id": "mem_ok", "user_text": "Lesbar behalten."},
            {"id": "mem_bad", "user_text": "Korrupt simuliert."},
        ],
    )
    primary.write_index(account_id, {"scope": "account", "index": {"entries": {"mem_ok": {}, "mem_bad": {}}}})
    with sqlite3.connect(primary_path) as connection:
        with connection:
            connection.execute(
                "UPDATE memory_entries SET payload_ciphertext = ? WHERE instance_name = ? AND account_id = ? AND memory_id = ?",
                (b"broken", "Depressionsbot", account_id, "mem_bad"),
            )

    report = build_account_memory_recovery_report(instances_dir=tmp_path, provider=provider())

    account = report["instances"][0]["accounts"][0]
    source = {source["name"]: source for source in account["sources"]}["sqlite_primary"]
    assert account["recoverable"] is True
    assert account["recovery_status"] == "recoverable"
    assert source["readable"] is True
    assert source["entries"] == 1
    assert source["raw_entries"] == 2
    assert "entries:" in source["error"]
    assert report["totals"]["recoverable_accounts"] == 1
    assert report["totals"]["unrecoverable_accounts"] == 0

    quarantine = quarantine_unrecoverable_account_memory(report, apply=False, quarantine_dir=tmp_path / "quarantine", running_processes=[])
    assert quarantine["status"] == "no-op"
    assert quarantine["totals"]["unrecoverable_accounts"] == 0
    text_report = render_memory_recovery_text_report(report)
    assert "sqlite_primary: active readable (partial) entries=1 raw_entries=2" in text_report
    assert "raw_index_present=True" in text_report


def test_account_recovery_status_ignores_malformed_source_counts_without_crashing() -> None:
    status, recommendation = _account_recovery_status(
        [
            {
                "name": "sqlite_primary",
                "active": True,
                "readable": True,
                "entries": "one",
                "index_present": False,
                "raw_entries": "one",
                "raw_index_present": False,
            }
        ]
    )

    assert status == "empty"
    assert "readable but contain no memory payloads" in recommendation


def test_sqlite_sources_for_unrecoverable_accounts_ignores_malformed_counts_without_crashing(tmp_path: Path) -> None:
    path = tmp_path / "Account_Memory.sqlite3"

    sources = _sqlite_sources_for_unrecoverable_accounts(
        [
            {
                "sources": [
                    {
                        "name": "sqlite_primary",
                        "kind": "sqlite",
                        "active": True,
                        "path": str(path),
                        "raw_entries": "one",
                        "raw_index_present": False,
                    }
                ]
            }
        ]
    )

    assert sources == []


def test_memory_recovery_totals_ignore_malformed_legacy_counts_without_crashing() -> None:
    totals = {
        "accounts": 0,
        "recoverable_accounts": 0,
        "unrecoverable_accounts": 0,
        "empty_accounts": 0,
        "no_source_accounts": 0,
        "sources": 0,
        "readable_sources": 0,
        "unreadable_sources": 0,
        "legacy_plaintext_sources": 0,
        "legacy_plaintext_entries": 0,
        "metadata_broken_instances": 0,
        "metadata_unreadable_items": 0,
        "metadata_unreadable_accounts": 0,
    }

    _add_totals(
        totals,
        {
            "metadata_health": {"readable": True, "items": []},
            "accounts": [],
            "legacy_plaintext_import": {"sources": "many", "entries": "many"},
        },
    )

    assert totals["legacy_plaintext_sources"] == 0
    assert totals["legacy_plaintext_entries"] == 0


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


def test_memory_recovery_report_mentions_unreadable_inactive_snapshots_under_accounts_root(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    store = AccountStore(accounts_root, "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:2", display_label="Ada")
    snapshot_path = accounts_root / "Account_Memory_Quarantine" / "20260617T011157Z" / "sqlite_snapshots" / "Account_Memory.sqlite3"
    snapshot = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=StaticSecretProvider(b"b" * 32),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=snapshot_path, fallback_path=None),
    )
    snapshot.write_entries(account_id, [{"id": "mem_bad", "user_text": "Snapshot"}])
    snapshot.write_index(account_id, {"scope": "account", "index": {}})

    report = build_account_memory_recovery_report(instances_dir=tmp_path, provider=provider())

    account = report["instances"][0]["accounts"][0]
    assert account["recovery_status"] == "empty"
    assert account["recoverable"] is False
    assert "inactive snapshots contain encrypted payloads" in account["recommendation"]
    assert any(source["active"] is False and source["raw_entries"] == 1 for source in account["sources"])


def test_admin_entrypoint_returns_json_dependency_error(monkeypatch, capsys) -> None:
    def fail_import(name: str):
        raise ModuleNotFoundError("No module named 'cryptography'", name="cryptography")

    monkeypatch.setattr(admin_entrypoint.importlib, "import_module", fail_import)

    result = admin_entrypoint.main(["memory-recovery", "--format", "json"])

    assert result == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["missing_dependency"] == "cryptography"


def test_admin_entrypoint_help_lists_memory_recovery(capsys) -> None:
    result = admin_entrypoint.main(["--help"])

    assert result == 0
    output = capsys.readouterr().out
    assert "accounts" in output
    assert "memory-recovery" in output


def test_account_memory_recovery_module_is_directly_executable() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "TeeBotus.admin.account_memory_recovery", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "TeeBotus account-memory recovery report" in result.stdout
    assert "--legacy-instances-dir" in result.stdout


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


def test_memory_recovery_quarantine_dry_run_reports_apply_blocked_by_runtime(tmp_path: Path) -> None:
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
    report = build_account_memory_recovery_report(instances_dir=tmp_path, provider=provider())

    result = quarantine_unrecoverable_account_memory(
        report,
        apply=False,
        quarantine_dir=tmp_path / "quarantine",
        running_processes=[{"pid": "123", "cmdline": "python3 -m TeeBotus --all"}],
    )

    assert result["status"] == "dry-run"
    assert result["apply_safety"]["apply_allowed_now"] is False
    assert result["apply_safety"]["apply_requires_stopped_bot"] is True


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


def test_memory_recovery_report_includes_unreadable_metadata_account_ids(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    bad_store = AccountStore(accounts_root, "Depressionsbot", StaticSecretProvider(b"b" * 32))
    account_id = bad_store.resolve_or_create_account("telegram:user:2", display_label="Ada")

    report = build_account_memory_recovery_report(instances_dir=tmp_path, provider=provider())

    metadata_health = report["instances"][0]["metadata_health"]
    assert metadata_health["readable"] is False
    assert metadata_health["unreadable_items"] == 3
    assert report["totals"]["metadata_broken_instances"] == 1
    assert report["totals"]["metadata_unreadable_items"] == 3
    assert report["totals"]["metadata_unreadable_accounts"] == 1
    kinds = {item["kind"] for item in metadata_health["items"]}
    assert kinds == {"account_index", "identity_mapping", "accounts_dir"}
    accounts_dir_item = next(item for item in metadata_health["items"] if item["kind"] == "accounts_dir")
    assert accounts_dir_item["account_ids"] == [account_id]


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


def test_memory_recovery_metadata_quarantine_dry_run_reports_apply_blocked_by_runtime(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    bad_store = AccountStore(accounts_root, "Depressionsbot", StaticSecretProvider(b"b" * 32))
    bad_store.resolve_or_create_account("telegram:user:2", display_label="Ada")

    result = quarantine_unreadable_account_metadata(
        instances_dir=tmp_path,
        provider=provider(),
        apply=False,
        quarantine_dir=tmp_path / "quarantine",
        running_processes=[{"pid": "123", "cmdline": "python3 -m TeeBotus --all"}],
    )

    assert result["status"] == "dry-run"
    assert result["apply_safety"]["apply_allowed_now"] is False
    assert result["apply_safety"]["apply_requires_stopped_bot"] is True


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
    assert "- metadata_health: readable=`True` unreadable_items=`0`" in text
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
    assert legacy["status"] == "available"
    assert legacy["requested_legacy_instances_dir_exists"] is True
    assert legacy["legacy_instances_dir_exists"] is True
    assert legacy["path_exists"] is True
    assert legacy["users"] == [{"user_id": "395935293", "entries": 2, "path": str(user_dir)}]
    assert "--replace-unreadable" in legacy["dry_run_command"]
    assert "--replace-unreadable-account-metadata" in legacy["dry_run_command"]
    assert "--json-output" in legacy["dry_run_command"]
    assert "--markdown-output" in legacy["dry_run_command"]
    assert "teebotus-legacy-import-preflight-Depressionsbot.json" in legacy["dry_run_command"]
    assert "--apply" in legacy["apply_command"]
    assert "--replace-unreadable" in legacy["apply_command"]
    assert "--replace-unreadable-account-metadata" in legacy["apply_command"]


def test_memory_recovery_report_marks_mapped_legacy_plaintext_as_account_recoverable(tmp_path: Path) -> None:
    target_dir = tmp_path / "target"
    legacy_dir = tmp_path / "legacy"
    instance_dir = make_instance(target_dir)
    accounts_root = instance_dir / "data" / "accounts"
    store = AccountStore(accounts_root, "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:395935293", display_label="Ada")
    broken = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=StaticSecretProvider(b"b" * 32),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=accounts_root / "Account_Memory.sqlite3", fallback_path=None),
    )
    broken.write_entries(account_id, [{"id": "mem_bad", "user_text": "falscher Key"}])
    broken.write_index(account_id, {"scope": "account", "index": {}})
    user_dir = legacy_dir / "Depressionsbot" / "data" / "users" / "395935293"
    user_dir.mkdir(parents=True)
    (user_dir / "User_Memory_Entries.jsonl").write_text(
        '{"id":"legacy_1","user_text":"A","bot_text":"B"}\n'
        '{"id":"legacy_2","user_text":"C","bot_text":"D"}\n',
        encoding="utf-8",
    )

    report = build_account_memory_recovery_report(
        instances_dir=target_dir,
        legacy_instances_dir=legacy_dir,
        provider=provider(),
    )

    account = report["instances"][0]["accounts"][0]
    sources = {source["name"]: source for source in account["sources"]}
    legacy_source = sources["legacy_plaintext_import_395935293"]
    assert account["account_id"] == account_id
    assert account["recoverable"] is True
    assert account["recovery_status"] == "recoverable"
    assert "legacy_plaintext_import_395935293" in account["recommendation"]
    assert legacy_source["payload_kind"] == "legacy_plaintext_user_memory"
    assert legacy_source["entries"] == 2
    assert legacy_source["identity"] == "telegram:user:395935293"
    assert report["totals"]["recoverable_accounts"] == 1
    assert report["totals"]["unrecoverable_accounts"] == 0


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
    assert legacy["requested_legacy_instances_dir_exists"] is True
    assert legacy["legacy_instances_dir"] == str(backup_root / "instances.bak")
    assert legacy["legacy_instances_dir_exists"] is True
    assert legacy["path_exists"] is True
    assert legacy["status"] == "available"
    assert legacy["sources"] == 2
    assert legacy["entries"] == 2
    assert [user["user_id"] for user in legacy["users"]] == ["1682346404", "395935293"]
    assert "--apply" in legacy["apply_command"]


def test_memory_recovery_report_marks_missing_legacy_backup_root(tmp_path: Path) -> None:
    target_dir = tmp_path / "target"
    missing_root = tmp_path / "missing-backup"
    make_instance(target_dir)

    report = build_account_memory_recovery_report(instances_dir=target_dir, legacy_instances_dir=missing_root, provider=provider())

    legacy = report["instances"][0]["legacy_plaintext_import"]
    assert legacy["requested_legacy_instances_dir"] == str(missing_root)
    assert legacy["requested_legacy_instances_dir_exists"] is False
    assert legacy["legacy_instances_dir"] == str(missing_root)
    assert legacy["legacy_instances_dir_exists"] is False
    assert legacy["path_exists"] is False
    assert legacy["status"] == "missing"
    assert legacy["sources"] == 0
    assert legacy["entries"] == 0


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
