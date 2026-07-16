from __future__ import annotations

import base64
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from TeeBotus.admin import __main__ as admin_entrypoint
import TeeBotus.admin.account_memory_recovery as account_memory_recovery_module
import TeeBotus.admin.accounts_report as accounts_report_module
import TeeBotus.admin.status_auth_admin as status_auth_admin_module
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
from TeeBotus.admin.accounts_report import (
    ReadOnlySecretToolInstanceSecretProvider,
    build_accounts_admin_report,
    main as accounts_report_main,
    render_text_report,
    runtime_report_env,
)
from TeeBotus.admin.status_auth_admin import bootstrap_status_auth_secrets, build_status_auth_report, main as status_auth_admin_main
from TeeBotus.runtime.accounts import (
    ACCOUNT_MEMORY_KEY_PURPOSE,
    INSTANCE_MAPPING_KEY_PURPOSE,
    INSTANCE_STATE_ACCOUNT_ID,
    AccountStore,
    AccountStoreError,
    StaticSecretProvider,
    signal_identity_key,
)
from TeeBotus.runtime.sqlite_memory import SQLiteAccountMemoryBackend, SQLiteMemoryConfig


def provider() -> StaticSecretProvider:
    return StaticSecretProvider(b"a" * 32)


def test_admin_reports_use_runtime_secret_provider_defaults(monkeypatch, tmp_path: Path) -> None:
    sentinels: list[object] = []

    def fake_provider() -> StaticSecretProvider:
        sentinels.append(object())
        return provider()

    monkeypatch.setattr(accounts_report_module, "runtime_secret_provider", fake_provider)
    monkeypatch.setattr(status_auth_admin_module, "runtime_secret_provider", fake_provider)

    build_accounts_admin_report(instances_dir=tmp_path)
    build_status_auth_report(instances_dir=tmp_path)

    assert len(sentinels) == 2


def test_admin_instance_discovery_ignores_symlinked_instances_and_instructions(tmp_path: Path) -> None:
    instances_root = tmp_path / "instances"
    instances_root.mkdir()
    external = tmp_path / "external-instance"
    external.mkdir()
    (external / "Bot_Verhalten.md").write_text("external\n", encoding="utf-8")
    linked_instance = instances_root / "LinkedInstance"
    linked_instance.symlink_to(external, target_is_directory=True)

    local_instance = instances_root / "LocalInstance"
    local_instance.mkdir()
    instruction_target = tmp_path / "external-instruction.md"
    instruction_target.write_text("external\n", encoding="utf-8")
    (local_instance / "Bot_Verhalten.md").symlink_to(instruction_target)

    assert accounts_report_module.discover_instances(instances_root) == ()
    (instances_root / "NotAnInstance").write_text("file\n", encoding="utf-8")
    assert accounts_report_module.discover_instances(
        instances_root, ("LinkedInstance", "../external-instance", "NotAnInstance", "safe")
    ) == ("safe",)

    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(instances_root, target_is_directory=True)
    assert accounts_report_module.discover_instances(linked_root) == ()
    assert accounts_report_module.discover_instances(linked_root, ("safe",)) == ()


def test_memory_recovery_default_provider_uses_readonly_runtime_policy(monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_SECRET_TOOL_LOOKUP_RETRIES", "2")
    monkeypatch.setenv("TEEBOTUS_SECRET_TOOL_LOOKUP_RETRY_DELAY_SECONDS", "0.25")
    monkeypatch.setenv("TEEBOTUS_SECRET_TOOL_TIMEOUT_SECONDS", "4")

    provider = account_memory_recovery_module.ReadOnlySecretToolInstanceSecretProvider()

    assert provider.lookup_retries == 2
    assert provider.lookup_retry_delay_seconds == 0.25
    assert provider.timeout_seconds == 4.0


class RecordingBootstrapProvider:
    def __init__(self) -> None:
        self.secrets: dict[tuple[str, str], bytes] = {}
        self.created: list[tuple[str, str]] = []

    def get_secret(self, instance_name: str, purpose: str) -> bytes:
        key = (instance_name, purpose)
        if key not in self.secrets:
            raise AccountStoreError(f"missing {purpose}")
        return self.secrets[key]

    def has_secret(self, instance_name: str, purpose: str) -> bool:
        return (instance_name, purpose) in self.secrets

    def get_or_create_secret(self, instance_name: str, purpose: str, *, reason: str = "") -> bytes:
        key = (instance_name, purpose)
        if key not in self.secrets:
            self.secrets[key] = bytes([len(self.secrets) + 1]) * 32
            self.created.append(key)
        return self.secrets[key]


def make_instance(tmp_path: Path, name: str = "Depressionsbot") -> Path:
    instance_dir = tmp_path / name
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## Hilfe\n", encoding="utf-8")
    return instance_dir


def test_readonly_secret_provider_caches_secret_tool_lookup(monkeypatch) -> None:
    calls: list[list[str]] = []
    encoded_secret = base64.urlsafe_b64encode(b"a" * 32).decode("ascii") + "\n"
    monkeypatch.setattr("TeeBotus.admin.accounts_report.shutil.which", lambda _command: "/usr/bin/secret-tool")

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=encoded_secret, stderr="")

    monkeypatch.setattr("TeeBotus.admin.accounts_report.subprocess.run", fake_run)
    provider = ReadOnlySecretToolInstanceSecretProvider()

    for _ in range(3):
        assert provider.get_secret("TeeBotus_Logger", ACCOUNT_MEMORY_KEY_PURPOSE) == b"a" * 32

    assert len(calls) == 1


def test_readonly_secret_provider_retries_transient_secret_tool_lookup(monkeypatch) -> None:
    calls: list[list[str]] = []
    encoded_secret = base64.urlsafe_b64encode(b"a" * 32).decode("ascii") + "\n"
    monkeypatch.setenv("TEEBOTUS_SECRET_TOOL_LOOKUP_RETRIES", "2")
    monkeypatch.setenv("TEEBOTUS_SECRET_TOOL_LOOKUP_RETRY_DELAY_SECONDS", "0")
    monkeypatch.setenv("TEEBOTUS_SECRET_TOOL_TIMEOUT_SECONDS", "4")
    monkeypatch.setattr("TeeBotus.admin.accounts_report.shutil.which", lambda _command: "/usr/bin/secret-tool")

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if len(calls) == 1:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="lookup unavailable")
        return subprocess.CompletedProcess(args, 0, stdout=encoded_secret, stderr="")

    monkeypatch.setattr("TeeBotus.admin.accounts_report.subprocess.run", fake_run)
    provider = ReadOnlySecretToolInstanceSecretProvider()

    assert provider.get_secret("TeeBotus_Logger", ACCOUNT_MEMORY_KEY_PURPOSE) == b"a" * 32
    assert len(calls) == 2
    assert provider.lookup_retries == 2
    assert provider.timeout_seconds == 4.0


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
    assert set(report["totals"]) == {"account_dirs", "identity_notices", "identity_warnings", "indexed_accounts", "linked_identities", "store_errors"}
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
    assert instance_report["identity_health"] == {"status": "ok", "warning_count": 0, "warnings": [], "notice_count": 0, "notices": []}


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


def test_admin_report_warns_for_dangling_account_directory(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts" / "accounts"
    accounts_root.mkdir(parents=True)
    (accounts_root / ("a" * 128)).mkdir()

    report = build_accounts_admin_report(instances_dir=tmp_path, provider=provider())

    store_report = report["instances"][0]["account_store"]
    assert store_report["readable"] is True
    assert store_report["errors"] == []
    assert store_report["dangling_account_dirs"] == 1
    assert store_report["warnings"] == ["account directory has no Account_Profile.json"]
    assert report["totals"]["store_errors"] == 0
    identity_health = report["instances"][0]["identity_health"]
    assert identity_health["status"] == "warning"
    assert identity_health["warning_count"] == 1
    assert identity_health["warnings"][0]["code"] == "account_store_integrity_warning"
    assert identity_health["warnings"][0]["configured_runtime_slots"] == "<none>"
    text = render_text_report(report)
    assert "dangling_account_dirs: 1" in text
    assert "account_store_warning: account directory has no Account_Profile.json" in text


def test_admin_report_ignores_account_directory_with_only_transient_locks(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    account_dir = instance_dir / "data" / "accounts" / "accounts" / ("a" * 128)
    account_dir.mkdir(parents=True)
    (account_dir / ".Codex_History_Outbox.jsonl.lock").touch()
    (account_dir / ".Status_Outbox.jsonl.lock").touch()

    report = build_accounts_admin_report(instances_dir=tmp_path, provider=provider())

    store_report = report["instances"][0]["account_store"]
    assert store_report["account_directories"] == 0
    assert store_report["dangling_account_dirs"] == 0
    assert store_report["warnings"] == []
    assert report["instances"][0]["identity_health"] == {"status": "ok", "warning_count": 0, "warnings": [], "notice_count": 0, "notices": []}


def test_admin_report_ignores_symlinked_account_directories(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts" / "accounts"
    accounts_root.mkdir(parents=True)
    external_account = tmp_path / "external-account"
    external_account.mkdir()
    (accounts_root / ("a" * 128)).symlink_to(external_account, target_is_directory=True)

    report = build_accounts_admin_report(instances_dir=tmp_path, provider=provider())

    store_report = report["instances"][0]["account_store"]
    assert store_report["account_directories"] == 0
    assert store_report["account_directory_ids"] == []


def test_admin_report_marks_account_directory_scan_error(monkeypatch, tmp_path: Path) -> None:
    make_instance(tmp_path)

    def fail_scan(_accounts_dir: Path) -> list[Path]:
        raise OSError("accounts directory disappeared")

    monkeypatch.setattr(accounts_report_module, "_account_dirs", fail_scan)

    report = build_accounts_admin_report(instances_dir=tmp_path, provider=provider())

    store_report = report["instances"][0]["account_store"]
    assert store_report["readable"] is False
    assert store_report["errors"] == ["account_directories: accounts directory disappeared"]
    assert report["totals"]["store_errors"] == 1


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


def test_admin_report_notices_when_configured_signal_has_no_linked_identity(tmp_path: Path) -> None:
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
    assert report["totals"]["identity_warnings"] == 0
    assert report["totals"]["identity_notices"] == 1
    identity_health = instance_report["identity_health"]
    assert identity_health["status"] == "ok"
    assert identity_health["warning_count"] == 0
    assert identity_health["notice_count"] == 1
    notice = identity_health["notices"][0]
    assert notice["code"] == "runtime_channel_without_identity"
    assert notice["channel"] == "signal"
    assert notice["configured_runtime_slots"] == 1
    assert notice["configured_runtime_labels"] == ["signal:1"]
    assert notice["identity_channels"] == {"telegram": 1}
    assert notice["other_linked_identities"] == 1
    assert "Incoming chats on this channel will use a separate account" in notice["message"]
    assert notice["recommended_action"] == (
        "First run /register or /rotate_secret in an already linked private chat, then open a private "
        "signal chat and link the existing account with /login <account_id> <secret>; "
        "use /register there only for a deliberately separate account."
    )
    text = render_text_report(report)
    assert "runtime_slots_by_channel: signal=1, telegram=1" in text
    assert "identity_notice: runtime_channel_without_identity channel=signal slots=1 labels=signal:1 identities=telegram=1" in text
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
    assert instance_report["identity_health"] == {"status": "ok", "warning_count": 0, "warnings": [], "notice_count": 0, "notices": []}
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


def test_accounts_report_cli_rejects_missing_parent_directory(tmp_path: Path, capsys) -> None:
    instances_dir = tmp_path / "instances"
    make_instance(instances_dir)

    output_path = tmp_path / "missing" / "dir" / "accounts.json"
    result = accounts_report_main(
        [
            "accounts",
            "report",
            "--instances-dir",
            str(instances_dir),
            "--format",
            "json",
            "--output",
            str(output_path),
        ]
    )

    assert result == 2
    assert "accounts:" in capsys.readouterr().err
    assert not output_path.exists()


def test_status_auth_report_lists_authorized_accounts_and_outbox(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:2", display_label="Ada")
    store.update_identity_route("telegram:user:2", channel="telegram", chat_id="2", chat_type="private", adapter_slot=1)
    store.write_status_auth_state(
        account_id,
        {
            "schema_version": 1,
            "authorized": True,
            "authorized_at": "2026-06-19T12:00:00+00:00",
        },
    )
    store.append_status_outbox_item(account_id, {"kind": "runtime_status_summary", "summary_number": 1, "status": "sent"})

    report = build_status_auth_report(instances_dir=tmp_path, provider=provider())

    instance_report = report["instances"][0]
    assert instance_report["status_auth"]["authorized_accounts"] == 1
    assert instance_report["status_auth"]["outbox_items"] == 1
    assert instance_report["status_auth"]["accounts"][0]["account_id"] == account_id
    assert instance_report["status_auth"]["accounts"][0]["route"]["channel"] == "telegram"


def test_status_auth_report_cli_outputs_json(tmp_path: Path, capsys) -> None:
    instance_dir = make_instance(tmp_path)
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:2", display_label="Ada")
    store.write_status_auth_state(account_id, {"schema_version": 1, "authorized": True})

    result = status_auth_admin_main(["report", "--instances-dir", str(tmp_path), "--format", "json"], provider=provider())

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["totals"]["authorized_accounts"] == 1


def test_status_auth_bootstrap_creates_mapping_and_memory_purposes(tmp_path: Path) -> None:
    make_instance(tmp_path, "TeeBotus_Logger")
    bootstrap_provider = RecordingBootstrapProvider()

    report = bootstrap_status_auth_secrets(
        instances_dir=tmp_path,
        instances=("TeeBotus_Logger",),
        provider=bootstrap_provider,
    )

    bootstrap = report["instances"][0]["bootstrap"]
    assert bootstrap["created_purposes"] == 2
    assert bootstrap["existing_purposes"] == 0
    assert bootstrap_provider.created == [
        ("TeeBotus_Logger", INSTANCE_MAPPING_KEY_PURPOSE),
        ("TeeBotus_Logger", ACCOUNT_MEMORY_KEY_PURPOSE),
    ]
    assert {row["status"] for row in bootstrap["purposes"]} == {"created"}


def test_status_auth_bootstrap_reuses_existing_purposes(tmp_path: Path) -> None:
    make_instance(tmp_path, "TeeBotus_Logger")
    bootstrap_provider = RecordingBootstrapProvider()
    bootstrap_provider.secrets[("TeeBotus_Logger", INSTANCE_MAPPING_KEY_PURPOSE)] = b"m" * 32
    bootstrap_provider.secrets[("TeeBotus_Logger", ACCOUNT_MEMORY_KEY_PURPOSE)] = b"s" * 32

    report = bootstrap_status_auth_secrets(
        instances_dir=tmp_path,
        instances=("TeeBotus_Logger",),
        provider=bootstrap_provider,
    )

    bootstrap = report["instances"][0]["bootstrap"]
    assert bootstrap["created_purposes"] == 0
    assert bootstrap["existing_purposes"] == 2
    assert bootstrap_provider.created == []
    assert {row["status"] for row in bootstrap["purposes"]} == {"existing"}


def test_status_auth_bootstrap_cli_outputs_json(tmp_path: Path, capsys) -> None:
    make_instance(tmp_path, "TeeBotus_Logger")
    bootstrap_provider = RecordingBootstrapProvider()

    result = status_auth_admin_main(
        ["bootstrap", "--instances-dir", str(tmp_path), "--instances", "TeeBotus_Logger", "--format", "json"],
        provider=bootstrap_provider,
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "status_auth_bootstrap"
    assert payload["totals"]["created_purposes"] == 2


def test_status_auth_bootstrap_does_not_create_missing_instance_dir(tmp_path: Path) -> None:
    bootstrap_provider = RecordingBootstrapProvider()

    report = bootstrap_status_auth_secrets(
        instances_dir=tmp_path,
        instances=("TeeBotus_Logger",),
        provider=bootstrap_provider,
    )

    assert report["totals"]["missing_instances"] == 1
    assert report["totals"]["created_purposes"] == 0
    assert bootstrap_provider.created == []
    assert not (tmp_path / "TeeBotus_Logger").exists()


def test_status_auth_bootstrap_rejects_instance_path_escape(tmp_path: Path) -> None:
    bootstrap_provider = RecordingBootstrapProvider()

    report = bootstrap_status_auth_secrets(
        instances_dir=tmp_path,
        instances=("../outside",),
        provider=bootstrap_provider,
    )

    assert report["instance_count"] == 0
    assert report["instances"] == []
    assert bootstrap_provider.created == []
    assert not (tmp_path.parent / "outside").exists()


def test_status_auth_report_keeps_account_when_route_lookup_fails(tmp_path: Path, monkeypatch) -> None:
    instance_dir = make_instance(tmp_path)
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:2", display_label="Ada")
    store.write_status_auth_state(account_id, {"schema_version": 1, "authorized": True})

    def _broken_route(_store: AccountStore, _account_id: str) -> dict[str, Any]:
        raise AccountStoreError("route lookup failed")

    monkeypatch.setattr("TeeBotus.admin.status_auth_admin.select_proactive_route", _broken_route)

    report = build_status_auth_report(instances_dir=tmp_path, provider=provider())

    account_report = report["instances"][0]["status_auth"]["accounts"][0]
    assert account_report["account_id"] == account_id
    assert account_report["route_error"] == "AccountStoreError:route lookup failed"


def test_status_auth_report_handles_non_mapping_state(tmp_path: Path, monkeypatch) -> None:
    instance_dir = make_instance(tmp_path)
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:2", display_label="Ada")
    store.append_status_outbox_item(
        account_id,
        {
            "kind": "runtime_status_summary",
            "summary_number": 1,
            "summary_prefix": "v1.0.0 #0001",
            "status": "sent",
            "message_text": "release",
        },
    )

    monkeypatch.setattr(store, "read_status_auth_state", lambda _account_id: [])

    report = build_status_auth_report(instances_dir=tmp_path, provider=provider())

    status_auth = report["instances"][0]["status_auth"]
    assert status_auth["authorized_accounts"] == 0
    assert status_auth["outbox_items"] == 1
    assert len(status_auth["accounts"]) == 1
    assert status_auth["accounts"][0]["account_id"] == account_id
    assert status_auth["accounts"][0]["authorized"] is False


def test_status_auth_report_cli_redacts_sensitive_fields(tmp_path: Path, capsys) -> None:
    instance_dir = make_instance(tmp_path)
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:3", display_label="Ada")
    store.write_status_auth_state(account_id, {"schema_version": 1, "authorized": True})

    result = status_auth_admin_main(["report", "--instances-dir", str(tmp_path), "--format", "json"], provider=provider())

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    account = payload["instances"][0]["status_auth"]["accounts"][0]
    assert account["account_id"] == "<redacted>"
    assert account["authorized"] is True


def test_status_auth_report_cli_rejects_absolute_output_path(tmp_path: Path, capsys) -> None:
    instance_dir = make_instance(tmp_path)
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:4", display_label="Ada")
    store.write_status_auth_state(account_id, {"schema_version": 1, "authorized": True})

    output_path = tmp_path / "outside" / "status-auth.json"
    absolute_path = output_path.resolve()

    result = status_auth_admin_main(
        [
            "report",
            "--instances-dir",
            str(tmp_path),
            "--format",
            "json",
            "--output",
            str(absolute_path),
        ],
        provider=provider(),
    )

    assert result == 2
    assert "status-auth:" in capsys.readouterr().err
    assert not absolute_path.exists()


def test_status_auth_report_cli_rejects_parent_traversal_output_path(tmp_path: Path, capsys) -> None:
    instance_dir = make_instance(tmp_path)
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:4", display_label="Ada")
    store.write_status_auth_state(account_id, {"schema_version": 1, "authorized": True})

    result = status_auth_admin_main(
        [
            "report",
            "--instances-dir",
            str(tmp_path),
            "--format",
            "json",
            "--output",
            "../status-auth.json",
        ],
        provider=provider(),
    )

    assert result == 2
    assert "status-auth:" in capsys.readouterr().err


def test_status_auth_report_cli_rejects_directory_output_path(tmp_path: Path, capsys) -> None:
    instance_dir = make_instance(tmp_path)
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:4", display_label="Ada")
    store.write_status_auth_state(account_id, {"schema_version": 1, "authorized": True})

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    result = status_auth_admin_main(
        [
            "report",
            "--instances-dir",
            str(tmp_path),
            "--format",
            "json",
            "--output",
            "out",
        ],
        provider=provider(),
    )

    assert result == 2
    assert "status-auth:" in capsys.readouterr().err


def test_status_auth_report_cli_rejects_missing_parent_directory(tmp_path: Path, capsys) -> None:
    instance_dir = make_instance(tmp_path)
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:4", display_label="Ada")
    store.write_status_auth_state(account_id, {"schema_version": 1, "authorized": True})

    output_path = tmp_path / "missing" / "dir" / "status-auth.json"
    result = status_auth_admin_main(
        [
            "report",
            "--instances-dir",
            str(tmp_path),
            "--format",
            "json",
            "--output",
            str(output_path),
        ],
        provider=provider(),
    )

    assert result == 2
    assert "status-auth:" in capsys.readouterr().err
    assert not output_path.exists()


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


def test_memory_recovery_sqlite_probes_report_disappearing_sources(monkeypatch, tmp_path: Path) -> None:
    def disappear(_path: Path):
        raise OSError("source disappeared during probe")

    monkeypatch.setattr(account_memory_recovery_module, "_connect_sqlite_readonly", disappear)
    missing = tmp_path / "Account_Memory.sqlite3"
    missing.write_bytes(b"sqlite placeholder")

    assert _sqlite_account_ids(missing) == set()
    assert _sqlite_raw_counts(missing, "Depressionsbot", "a" * 128) == (0, False, 0)
    entries, index, collections, errors = account_memory_recovery_module._read_sqlite_snapshot_payloads(
        missing,
        instance_name="Depressionsbot",
        account_id="a" * 128,
        provider=provider(),
    )

    assert entries == []
    assert index == {}
    assert collections == []
    assert errors == ["sqlite: source disappeared during probe"]


def test_memory_recovery_sqlite_probes_reject_symlinked_source_and_sidecar(tmp_path: Path) -> None:
    source = tmp_path / "Account_Memory.sqlite3"
    target = tmp_path / "outside.sqlite3"
    target.write_bytes(b"not a database")
    source.symlink_to(target)

    assert _sqlite_account_ids(source) == set()
    assert _sqlite_raw_counts(source, "Depressionsbot", "a" * 128) == (0, False, 0)
    _, _, _, source_errors = account_memory_recovery_module._read_sqlite_snapshot_payloads(
        source,
        instance_name="Depressionsbot",
        account_id="a" * 128,
        provider=provider(),
    )
    assert source_errors == [f"sqlite: refusing symlinked SQLite recovery source: {source}"]

    real_source = tmp_path / "real.sqlite3"
    real_source.write_bytes(b"not a database")
    sidecar = Path(str(real_source) + "-wal")
    sidecar_target = tmp_path / "outside-wal"
    sidecar_target.write_bytes(b"outside")
    sidecar.symlink_to(sidecar_target)
    _, _, _, sidecar_errors = account_memory_recovery_module._read_sqlite_snapshot_payloads(
        real_source,
        instance_name="Depressionsbot",
        account_id="a" * 128,
        provider=provider(),
    )
    assert sidecar_errors == [f"sqlite: refusing symlinked SQLite recovery sidecar: {sidecar}"]


def test_memory_recovery_rejects_hardlinked_sqlite_sources_before_delete(tmp_path: Path) -> None:
    source = tmp_path / "Account_Memory.sqlite3"
    external = tmp_path / "external.sqlite3"
    external.write_bytes(b"not a database")
    source.hardlink_to(external)

    assert _sqlite_account_ids(source) == set()
    _, _, _, errors = account_memory_recovery_module._read_sqlite_snapshot_payloads(
        source,
        instance_name="Depressionsbot",
        account_id="a" * 128,
        provider=provider(),
    )
    assert errors == [f"sqlite: refusing hardlinked SQLite recovery source: {source}"]

    with pytest.raises(OSError, match="hardlinked SQLite recovery source"):
        account_memory_recovery_module._delete_sqlite_account_rows(source, "Depressionsbot", ["a" * 128])
    assert external.read_bytes() == b"not a database"


def test_memory_recovery_rejects_symlinked_sqlite_parent_before_probe(tmp_path: Path) -> None:
    real_root = tmp_path / "real"
    real_root.mkdir()
    source = real_root / "Account_Memory.sqlite3"
    source.write_bytes(b"not a database")
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(real_root, target_is_directory=True)
    linked_source = linked_root / "Account_Memory.sqlite3"

    assert _sqlite_account_ids(linked_source) == set()
    _, _, _, errors = account_memory_recovery_module._read_sqlite_snapshot_payloads(
        linked_source,
        instance_name="Depressionsbot",
        account_id="a" * 128,
        provider=provider(),
    )

    assert errors == [f"sqlite: refusing symlinked SQLite recovery path component: {linked_root}"]


def test_memory_recovery_accounts_directory_race_stays_fail_closed(monkeypatch, tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    accounts_dir = accounts_root / "accounts"
    accounts_dir.mkdir(parents=True)
    original_iterdir = Path.iterdir

    def race_iterdir(path: Path):
        if path == accounts_dir:
            def disappeared():
                raise OSError("accounts directory disappeared")
                yield from ()

            return disappeared()
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", race_iterdir)

    assert account_memory_recovery_module._discover_account_ids(accounts_root) == []
    items = account_memory_recovery_module._unreadable_metadata_items(accounts_root, "Depressionsbot", provider())

    assert items == [
        {
            "kind": "accounts_dir",
            "path": accounts_dir,
            "account_ids": [],
            "error": "unable to inspect accounts directory: accounts directory disappeared",
            "quarantine_safe": False,
        }
    ]


def test_memory_recovery_metadata_probe_errors_block_apply(monkeypatch, tmp_path: Path) -> None:
    make_instance(tmp_path)

    def probe_error(*_args, **_kwargs):
        raise OSError("metadata source disappeared")

    monkeypatch.setattr(account_memory_recovery_module, "_unreadable_metadata_items", probe_error)

    result = quarantine_unreadable_account_metadata(
        instances_dir=tmp_path,
        provider=provider(),
        apply=True,
        quarantine_dir=tmp_path / "quarantine",
        running_processes=[],
    )

    assert result["status"] == "blocked"
    assert result["instances"][0]["status"] == "blocked"
    assert result["instances"][0]["items"][0]["error"] == "metadata source disappeared"
    assert not (tmp_path / "quarantine").exists()


def test_memory_recovery_quarantine_blocks_missing_report_accounts_root(tmp_path: Path) -> None:
    account_id = "e" * 128
    report = {
        "instances": [
            {
                "instance": "Depressionsbot",
                "accounts_root": "",
                "accounts": [
                    {
                        "account_id": account_id,
                        "recovery_status": "unrecoverable",
                        "sources": [],
                    }
                ],
            }
        ]
    }

    result = quarantine_unrecoverable_account_memory(report, apply=True, running_processes=[])

    assert result["status"] == "blocked"
    assert result["instances"][0]["status"] == "blocked"
    assert "accounts_root" in result["instances"][0]["error"]
    assert not (tmp_path / "accounts").exists()


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


def test_memory_recovery_cli_rejects_missing_parent_directory(tmp_path: Path, capsys) -> None:
    instance_dir = make_instance(tmp_path)
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    store.resolve_or_create_account("telegram:user:2", display_label="Ada")

    output_path = tmp_path / "missing" / "recovery" / "report.json"
    result = recovery_main(["--instances-dir", str(tmp_path), "--format", "json", "--output", str(output_path)])

    assert result == 2
    assert "account-memory-recovery:" in capsys.readouterr().err
    assert not output_path.exists()


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


def test_account_recovery_status_treats_readable_empty_raw_sources_as_empty() -> None:
    status, recommendation = _account_recovery_status(
        [
            {
                "name": "json_files",
                "active": True,
                "readable": True,
                "entries": 0,
                "index_present": False,
                "collections": 0,
                "raw_entries": 0,
                "raw_index_present": True,
                "raw_collections": 1,
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


def test_sqlite_sources_for_unrecoverable_accounts_rejects_paths_outside_root(tmp_path: Path) -> None:
    accounts_root = tmp_path / "accounts"
    external = tmp_path / "external.sqlite3"

    sources = _sqlite_sources_for_unrecoverable_accounts(
        [
            {
                "sources": [
                    {
                        "kind": "sqlite",
                        "active": True,
                        "path": str(external),
                        "raw_entries": 1,
                    }
                ]
            }
        ],
        accounts_root=accounts_root,
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


def test_memory_recovery_snapshot_rejects_existing_symlink_destination(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    source.write_bytes(b"sqlite placeholder")
    outside = tmp_path / "outside.sqlite3"
    outside.write_bytes(b"outside")
    target = tmp_path / "quarantine" / "snapshot.sqlite3"
    target.parent.mkdir()
    target.symlink_to(outside)

    with pytest.raises(AccountStoreError, match="existing SQLite snapshot destination"):
        account_memory_recovery_module._snapshot_sqlite_database(source, target)

    assert outside.read_bytes() == b"outside"


def test_memory_recovery_manifest_rejects_existing_symlink_destination(tmp_path: Path) -> None:
    outside = tmp_path / "outside-manifest.json"
    outside.write_text("outside\n", encoding="utf-8")
    manifest = tmp_path / "quarantine" / "manifest.json"
    manifest.parent.mkdir()
    manifest.symlink_to(outside)

    with pytest.raises(AccountStoreError, match="existing quarantine manifest"):
        account_memory_recovery_module._write_quarantine_manifest(manifest, {"status": "applied"})

    assert outside.read_text(encoding="utf-8") == "outside\n"


def test_memory_recovery_quarantines_unrecoverable_sqlite_collection_rows(tmp_path: Path) -> None:
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
    primary.write_collection(account_id, "agent_state", [{"id": "agent_state", "proactive": {"enabled": True}}])
    report = build_account_memory_recovery_report(instances_dir=tmp_path, provider=provider())
    account = report["instances"][0]["accounts"][0]
    source = next(source for source in account["sources"] if source["name"] == "sqlite_primary")

    assert account["recovery_status"] == "unrecoverable"
    assert source["raw_collections"] == 1
    assert source["collections"] == 0
    assert "collections:" in source["error"]

    result = quarantine_unrecoverable_account_memory(report, apply=True, quarantine_dir=tmp_path / "quarantine", running_processes=[])

    assert result["status"] == "applied"
    assert result["totals"]["sqlite_rows_quarantined"] == 1
    follow_up = build_account_memory_recovery_report(instances_dir=tmp_path, provider=provider())
    follow_up_account = follow_up["instances"][0]["accounts"][0]
    assert follow_up_account["recovery_status"] == "empty"
    follow_up_source = next(source for source in follow_up_account["sources"] if source["name"] == "sqlite_primary")
    assert follow_up_source["raw_collections"] == 0


def test_memory_recovery_quarantines_unrecoverable_json_state_files(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    store = AccountStore(accounts_root, "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:2", display_label="Ada")
    wrong_store = AccountStore(accounts_root, "Depressionsbot", StaticSecretProvider(b"b" * 32), create_dirs=False)
    wrong_store.write_agent_state(account_id, {"proactive": {"enabled": True}})
    state_path = store.account_dir(account_id) / "Agent_State.json"

    report = build_account_memory_recovery_report(instances_dir=tmp_path, provider=provider())
    account = report["instances"][0]["accounts"][0]
    source = next(source for source in account["sources"] if source["name"] == "json_files")

    assert account["recovery_status"] == "unrecoverable"
    assert source["raw_collections"] == 1
    assert source["collections"] == 0
    assert "Agent_State.json:" in source["error"]

    result = quarantine_unrecoverable_account_memory(report, apply=True, quarantine_dir=tmp_path / "quarantine", running_processes=[])

    assert result["status"] == "applied"
    assert result["totals"]["json_files_quarantined"] == 1
    assert not state_path.exists()
    moved = result["instances"][0]["json_files"][0]
    assert moved["path"] == str(state_path)
    assert Path(moved["quarantine_path"]).exists()


def test_memory_recovery_report_treats_empty_json_state_as_empty(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    store = AccountStore(accounts_root, "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:2", display_label="Ada")
    store.write_agent_state(account_id, {})

    report = build_account_memory_recovery_report(instances_dir=tmp_path, provider=provider())

    account = report["instances"][0]["accounts"][0]
    source = next(source for source in account["sources"] if source["name"] == "json_files")
    assert account["recovery_status"] == "empty"
    assert source["readable"] is True
    assert source["raw_collections"] == 1
    assert source["collections"] == 0


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
    assert "status-auth" in output


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


def test_memory_recovery_metadata_quarantine_blocks_key_mismatch(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    bad_store = AccountStore(accounts_root, "Depressionsbot", StaticSecretProvider(b"b" * 32))
    account_id = bad_store.resolve_or_create_account("telegram:user:2", display_label="Ada")
    assert build_accounts_admin_report(instances_dir=tmp_path, provider=provider())["totals"]["store_errors"] == 1

    result = quarantine_unreadable_account_metadata(
        instances_dir=tmp_path,
        provider=provider(),
        apply=True,
        quarantine_dir=tmp_path / "quarantine",
        running_processes=[],
    )

    assert result["status"] == "blocked"
    assert result["totals"]["instances_with_unreadable_metadata"] == 0
    assert result["totals"]["items_quarantined"] == 0
    assert result["totals"]["account_dirs_quarantined"] == 0
    assert (accounts_root / "Account_Index.json").exists()
    assert (accounts_root / "Account_Identities.json").exists()
    assert (accounts_root / "accounts" / account_id / "Account_Profile.json").exists()
    assert not (tmp_path / "quarantine").exists()


def test_memory_recovery_metadata_quarantine_preserves_readable_account_dirs(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    good_store = AccountStore(accounts_root, "Depressionsbot", provider())
    readable_account = good_store.resolve_or_create_account("telegram:user:1")
    unreadable_account = good_store.resolve_or_create_account("telegram:user:2")
    bad_profile_path = good_store.account_dir(unreadable_account) / "Account_Profile.json"
    bad_profile_path.write_bytes(b"malformed envelope\n")

    result = quarantine_unreadable_account_metadata(
        instances_dir=tmp_path,
        provider=provider(),
        apply=True,
        quarantine_dir=tmp_path / "quarantine",
        running_processes=[],
    )

    assert result["status"] == "applied"
    assert result["totals"]["account_dirs_quarantined"] == 1
    accounts_dir = accounts_root / "accounts"
    assert (accounts_dir / readable_account / "Account_Profile.json").exists()
    assert not (accounts_dir / unreadable_account).exists()
    metadata_quarantine = tmp_path / "quarantine" / "Depressionsbot" / "metadata"
    timestamp_dir = next(metadata_quarantine.iterdir())
    assert (timestamp_dir / "accounts" / unreadable_account / "Account_Profile.json").exists()


def test_memory_recovery_metadata_quarantine_refuses_missing_secret(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    store = AccountStore(accounts_root, "Depressionsbot", provider())
    account_id = store.resolve_or_create_account("telegram:user:1")

    class MissingSecretProvider:
        def get_secret(self, _instance_name: str, _purpose: str) -> bytes:
            raise AccountStoreError("instance secret is missing")

        def has_secret(self, _instance_name: str, _purpose: str) -> bool:
            return False

    result = quarantine_unreadable_account_metadata(
        instances_dir=tmp_path,
        provider=MissingSecretProvider(),
        apply=True,
        quarantine_dir=tmp_path / "quarantine",
        running_processes=[],
    )

    assert result["status"] == "blocked"
    assert result["totals"]["items_quarantined"] == 0
    assert (accounts_root / "Account_Index.json").exists()
    assert (accounts_root / "Account_Identities.json").exists()
    assert (accounts_root / "accounts" / account_id / "Account_Profile.json").exists()
    assert not (tmp_path / "quarantine").exists()


def test_memory_recovery_metadata_quarantine_blocks_symlinked_metadata_file(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    external = tmp_path / "outside-index.json"
    external.write_text("outside\n", encoding="utf-8")
    index_path = accounts_root / "Account_Index.json"
    index_path.parent.mkdir(parents=True)
    index_path.symlink_to(external)

    result = quarantine_unreadable_account_metadata(
        instances_dir=tmp_path,
        provider=provider(),
        apply=True,
        quarantine_dir=tmp_path / "quarantine",
        running_processes=[],
    )

    assert result["status"] == "blocked"
    assert external.read_text(encoding="utf-8") == "outside\n"
    assert index_path.is_symlink()
    assert not (tmp_path / "quarantine").exists()


def test_memory_recovery_metadata_quarantine_blocks_symlinked_account_dir(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    external = tmp_path / "outside-account"
    external.mkdir(parents=True)
    (external / "Account_Profile.json").write_text("outside\n", encoding="utf-8")
    account_id = "d" * 128
    account_dir = accounts_root / "accounts" / account_id
    account_dir.parent.mkdir(parents=True)
    account_dir.symlink_to(external, target_is_directory=True)

    result = quarantine_unreadable_account_metadata(
        instances_dir=tmp_path,
        provider=provider(),
        apply=True,
        quarantine_dir=tmp_path / "quarantine",
        running_processes=[],
    )

    assert result["status"] == "blocked"
    assert external.joinpath("Account_Profile.json").read_text(encoding="utf-8") == "outside\n"
    assert account_dir.is_symlink()
    assert not (tmp_path / "quarantine").exists()


def test_memory_recovery_metadata_quarantine_keeps_truncated_auth_failure_blocked(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    good_store = AccountStore(accounts_root, "Depressionsbot", provider())
    account_ids = sorted(
        good_store.resolve_or_create_account(f"telegram:user:{number}")
        for number in range(6)
    )
    wrong_store = AccountStore(
        accounts_root,
        "Depressionsbot",
        StaticSecretProvider(b"b" * 32),
        create_dirs=False,
        memory_backend_enabled=False,
    )
    for account_id in account_ids[:-1]:
        (good_store.account_dir(account_id) / "Account_Profile.json").write_bytes(b"malformed envelope\n")
    auth_failure_path = good_store.account_dir(account_ids[-1]) / "Account_Profile.json"
    auth_failure_path.write_bytes(
        wrong_store.vault.encrypt(
            json.dumps({"account_id": account_ids[-1], "status": "active"}).encode("utf-8"),
            kind=auth_failure_path.name,
        )
    )

    result = quarantine_unreadable_account_metadata(
        instances_dir=tmp_path,
        provider=provider(),
        apply=True,
        quarantine_dir=tmp_path / "quarantine",
        running_processes=[],
    )

    assert result["status"] == "blocked"
    assert result["totals"]["items_quarantined"] == 0
    assert all((good_store.account_dir(account_id) / "Account_Profile.json").exists() for account_id in account_ids)
    assert not (tmp_path / "quarantine").exists()


def test_memory_recovery_metadata_quarantine_blocks_unsupported_envelope(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    store = AccountStore(accounts_root, "Depressionsbot", provider())
    store.resolve_or_create_account("telegram:user:1")
    index_path = accounts_root / "Account_Index.json"
    index_path.write_text(
        json.dumps(
            {
                "magic": "TMBMAP1",
                "version": 999,
                "algorithm": "AES-256-GCM",
                "kind": "Account_Index.json",
            }
        ),
        encoding="utf-8",
    )

    result = quarantine_unreadable_account_metadata(
        instances_dir=tmp_path,
        provider=provider(),
        apply=True,
        quarantine_dir=tmp_path / "quarantine",
        running_processes=[],
    )

    assert result["status"] == "blocked"
    assert index_path.exists()
    assert not (tmp_path / "quarantine").exists()


def test_memory_recovery_quarantine_rejects_symlinked_destination(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    accounts_root = instance_dir / "data" / "accounts"
    store = AccountStore(accounts_root, "Depressionsbot", provider())
    store.resolve_or_create_account("telegram:user:1")
    index_path = accounts_root / "Account_Index.json"
    index_path.write_bytes(b"malformed envelope\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    quarantine = tmp_path / "quarantine"
    quarantine.symlink_to(outside, target_is_directory=True)

    with pytest.raises(AccountStoreError, match="symlinked quarantine directory"):
        quarantine_unreadable_account_metadata(
            instances_dir=tmp_path,
            provider=provider(),
            apply=True,
            quarantine_dir=quarantine,
            running_processes=[],
        )

    assert index_path.exists()
    assert not any(outside.iterdir())


def test_memory_recovery_snapshots_all_sqlite_sources_before_deleting(monkeypatch, tmp_path: Path) -> None:
    account_id = "a" * 128
    first = tmp_path / "Account_Memory.sqlite3"
    second = tmp_path / "Account_Memory.backup.sqlite3"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    snapshot_calls: list[Path] = []
    delete_calls: list[Path] = []

    def snapshot(source: Path, _target: Path) -> None:
        snapshot_calls.append(source)
        if source == second:
            raise OSError("second snapshot failed")

    monkeypatch.setattr(account_memory_recovery_module, "_snapshot_sqlite_database", snapshot)
    monkeypatch.setattr(
        account_memory_recovery_module,
        "_delete_sqlite_account_rows",
        lambda source, _instance, _accounts: delete_calls.append(source) or 1,
    )
    report = {
        "instances": [
            {
                "instance": "Depressionsbot",
                "accounts_root": str(tmp_path),
                "accounts": [
                    {
                        "account_id": account_id,
                        "recovery_status": "unrecoverable",
                        "sources": [
                            {"kind": "sqlite", "active": True, "path": str(first), "raw_entries": 1},
                            {"kind": "sqlite", "active": True, "path": str(second), "raw_entries": 1},
                        ],
                    }
                ],
            }
        ]
    }

    with pytest.raises(OSError, match="second snapshot failed"):
        quarantine_unrecoverable_account_memory(report, apply=True, running_processes=[])

    assert snapshot_calls == [first, second]
    assert delete_calls == []


def test_memory_recovery_json_quarantine_ignores_symlinked_account_dir(tmp_path: Path) -> None:
    accounts_root = tmp_path / "data" / "accounts"
    external = tmp_path / "external-account"
    external.mkdir(parents=True)
    (external / "User_Memory_Entries.jsonl").write_text("outside\n", encoding="utf-8")
    account_id = "a" * 128
    account_dir = accounts_root / "accounts" / account_id
    account_dir.parent.mkdir(parents=True)
    account_dir.symlink_to(external, target_is_directory=True)

    assert account_memory_recovery_module._json_memory_files_for_accounts(accounts_root, [account_id]) == []
    assert (external / "User_Memory_Entries.jsonl").exists()


def test_memory_recovery_json_report_ignores_symlinked_account_paths(tmp_path: Path) -> None:
    accounts_root = tmp_path / "data" / "accounts"
    external = tmp_path / "external-account"
    external.mkdir(parents=True)
    (external / "User_Memory_Entries.jsonl").write_text("outside\n", encoding="utf-8")
    account_id = "b" * 128
    account_dir = accounts_root / "accounts" / account_id
    account_dir.parent.mkdir(parents=True)
    account_dir.symlink_to(external, target_is_directory=True)

    assert account_id not in account_memory_recovery_module._discover_account_ids(accounts_root)
    report = account_memory_recovery_module._inspect_json_source(
        account_memory_recovery_module.RecoverySource("json_files", "json", account_dir.parent),
        instance_name="Depressionsbot",
        account_id=account_id,
        provider=provider(),
    )

    assert report["readable"] is False
    assert report["entries"] == 0
    assert "refusing symlinked JSON recovery path" in report["error"]
    assert (external / "User_Memory_Entries.jsonl").exists()


def test_memory_recovery_json_report_rejects_symlinked_memory_file(tmp_path: Path) -> None:
    accounts_root = tmp_path / "data" / "accounts"
    account_id = "c" * 128
    account_dir = accounts_root / "accounts" / account_id
    account_dir.mkdir(parents=True)
    external = tmp_path / "external-entries.jsonl"
    external.write_text("outside\n", encoding="utf-8")
    (account_dir / "User_Memory_Entries.jsonl").symlink_to(external)

    report = account_memory_recovery_module._inspect_json_source(
        account_memory_recovery_module.RecoverySource("json_files", "json", account_dir.parent),
        instance_name="Depressionsbot",
        account_id=account_id,
        provider=provider(),
    )

    assert report["readable"] is False
    assert report["entries"] == 0
    assert report["raw_entries"] == 0
    assert "refusing symlinked JSON recovery file" in report["error"]
    assert external.read_text(encoding="utf-8") == "outside\n"


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
