from __future__ import annotations

import base64
import json
import logging
import re
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from TeeBotus.runtime.accounts import (
    ACCOUNT_KEYRING_FILENAME,
    ACCOUNT_MEMORY_KEY_PURPOSE,
    CODEX_HISTORY_OUTBOX_FILENAME,
    PROACTIVE_OUTBOX_FILENAME,
    STATUS_AUTH_STATE_FILENAME,
    STATUS_OUTBOX_FILENAME,
    USER_MEMORY_ENTRIES_FILENAME,
    USER_MEMORY_INDEX_FILENAME,
    INSTANCE_MAPPING_KEY_PURPOSE,
    INSTANCE_PEPPER_PURPOSE,
    EncryptedJsonVault,
    AccountStore,
    AccountStoreError,
    LLM_STATE_FILENAME,
    OPENAI_STATE_FILENAME,
    SecretToolInstanceSecretProvider,
    StaticSecretProvider,
    _merge_account_jsonl_rows,
    _atomic_write_text,
    matrix_identity_key,
    runtime_secret_provider,
    signal_identity_key,
    telegram_identity_key,
)
from TeeBotus.runtime.memory_fallback import WarningFallbackAccountMemoryBackend
from TeeBotus.runtime.sqlite_memory import SQLiteAccountMemoryBackend, SQLiteMemoryConfig

HEX_128 = re.compile(r"^[0-9a-f]{128}$")


def provider() -> StaticSecretProvider:
    return StaticSecretProvider(b"a" * 32)


def test_secret_tool_provider_caches_lookup_result(monkeypatch) -> None:
    first = b"a" * 32
    second = b"b" * 32
    lookups = [first, second]
    provider_instance = SecretToolInstanceSecretProvider()

    monkeypatch.setattr(provider_instance, "_lookup", lambda _instance, _purpose: lookups.pop(0))

    assert provider_instance.get_secret("Demo", "account_memory") == first
    assert provider_instance.get_secret("Demo", "account_memory") == first
    assert lookups == [second]


def test_secret_tool_provider_can_refuse_missing_secret(monkeypatch) -> None:
    provider_instance = SecretToolInstanceSecretProvider(create_if_missing=False)
    monkeypatch.setattr(provider_instance, "_lookup", lambda _instance, _purpose: None)

    with pytest.raises(AccountStoreError, match="instance secret is missing"):
        provider_instance.get_secret("Demo", "account_memory")


def test_secret_tool_provider_defaults_to_refuse_missing_secret(monkeypatch) -> None:
    provider_instance = SecretToolInstanceSecretProvider()
    monkeypatch.setattr(provider_instance, "_lookup", lambda _instance, _purpose: None)
    monkeypatch.setattr(
        provider_instance,
        "_store",
        lambda _instance, _purpose, _secret: pytest.fail("missing secrets must not be auto-created by default"),
    )

    with pytest.raises(AccountStoreError, match="instance secret is missing"):
        provider_instance.get_secret("Demo", "account_memory")


def test_runtime_secret_provider_never_autocreates_missing_secret(monkeypatch) -> None:
    provider_instance = runtime_secret_provider()
    monkeypatch.setattr(provider_instance, "_lookup", lambda _instance, _purpose: None)
    provider_instance.lookup_retries = 0
    monkeypatch.setattr(
        provider_instance,
        "_store",
        lambda _instance, _purpose, _secret: pytest.fail("runtime provider must not create missing secrets"),
    )

    with pytest.raises(AccountStoreError, match="instance secret is missing"):
        provider_instance.get_secret("Demo", "account-structured-memory-key")


def test_runtime_secret_provider_uses_secret_service_retry_defaults(monkeypatch) -> None:
    monkeypatch.delenv("TEEBOTUS_SECRET_TOOL_LOOKUP_RETRIES", raising=False)
    monkeypatch.delenv("TEEBOTUS_SECRET_TOOL_LOOKUP_RETRY_DELAY_SECONDS", raising=False)
    monkeypatch.delenv("TEEBOTUS_SECRET_TOOL_TIMEOUT_SECONDS", raising=False)

    provider_instance = runtime_secret_provider()

    assert provider_instance.lookup_retries == 6
    assert provider_instance.lookup_retry_delay_seconds == 2.0
    assert provider_instance.timeout_seconds == 5.0


def test_runtime_secret_provider_accepts_secret_service_retry_env(monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_SECRET_TOOL_LOOKUP_RETRIES", "2")
    monkeypatch.setenv("TEEBOTUS_SECRET_TOOL_LOOKUP_RETRY_DELAY_SECONDS", "0.25")
    monkeypatch.setenv("TEEBOTUS_SECRET_TOOL_TIMEOUT_SECONDS", "0.75")

    provider_instance = runtime_secret_provider()

    assert provider_instance.lookup_retries == 2
    assert provider_instance.lookup_retry_delay_seconds == 0.25
    assert provider_instance.timeout_seconds == 0.75


def test_secret_tool_provider_keeps_explicit_zero_timeout(monkeypatch) -> None:
    provider_instance = SecretToolInstanceSecretProvider(timeout_seconds=0)

    assert provider_instance.timeout_seconds == 0.0


def test_secret_tool_provider_times_out_hung_secret_tool(monkeypatch) -> None:
    provider_instance = SecretToolInstanceSecretProvider(timeout_seconds=0.25)
    calls: dict[str, object] = {}
    timeouts: list[object] = []

    monkeypatch.setattr(provider_instance, "_secret_tool", lambda: "/usr/bin/secret-tool")

    class FakeProcess:
        pid = 12345
        returncode = -9

        def __init__(self, command):
            self.command = command

        def communicate(self, *, input=None, timeout=None):
            calls["timeout"] = timeout
            timeouts.append(timeout)
            if timeout is not None:
                raise subprocess.TimeoutExpired(self.command, timeout)
            return "", ""

        def kill(self) -> None:
            calls["kill"] = True

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        calls["command"] = command
        return FakeProcess(command)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    with pytest.raises(AccountStoreError, match="timed out"):
        provider_instance._run(["lookup", "application", "TeeBotus"])

    assert timeouts[0] == 0.25


def test_secret_tool_provider_short_circuits_after_service_timeout(monkeypatch) -> None:
    provider_instance = SecretToolInstanceSecretProvider(timeout_seconds=0.25)
    popen_calls = 0

    class FakeProcess:
        pid = 12345
        returncode = -9

        def communicate(self, *, input=None, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired(["secret-tool"], timeout)
            return "", ""

        def kill(self) -> None:
            return None

    def fake_popen(_command: list[str], **_kwargs: object) -> FakeProcess:
        nonlocal popen_calls
        popen_calls += 1
        return FakeProcess()

    monkeypatch.setattr(provider_instance, "_secret_tool", lambda: "/usr/bin/secret-tool")
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    with pytest.raises(AccountStoreError, match="timed out"):
        provider_instance._run(["lookup", "application", "TeeBotus"])
    with pytest.raises(AccountStoreError, match="timed out"):
        provider_instance._run(["lookup", "application", "TeeBotus"])

    assert popen_calls == 1


def test_secret_tool_provider_retries_transient_missing_lookup(monkeypatch) -> None:
    calls = 0
    provider_instance = SecretToolInstanceSecretProvider(
        create_if_missing=False,
        lookup_retries=2,
        lookup_retry_delay_seconds=0,
    )

    def lookup(_instance: str, _purpose: str) -> bytes | None:
        nonlocal calls
        calls += 1
        if calls < 3:
            return None
        return b"a" * 32

    monkeypatch.setattr(provider_instance, "_lookup", lookup)

    assert provider_instance.get_secret("Demo", "account_memory") == b"a" * 32
    assert calls == 3


def test_secret_tool_provider_retries_before_refusing_required_secret(monkeypatch) -> None:
    calls = 0
    provider_instance = SecretToolInstanceSecretProvider(
        create_if_missing=False,
        lookup_retries=2,
        lookup_retry_delay_seconds=0,
    )

    def lookup(_instance: str, _purpose: str) -> bytes | None:
        nonlocal calls
        calls += 1
        if calls < 3:
            return None
        return b"a" * 32

    monkeypatch.setattr(provider_instance, "_lookup", lookup)

    provider_instance.require_existing_secret("Demo", "account_memory", reason="account key manifest")
    assert calls == 3


def test_secret_tool_provider_only_treats_empty_rc1_lookup_as_missing(monkeypatch) -> None:
    provider_instance = SecretToolInstanceSecretProvider(create_if_missing=False)

    monkeypatch.setattr(
        provider_instance,
        "_run",
        lambda _args: subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
    )

    assert provider_instance._lookup("Demo", "account_memory") is None


def test_secret_tool_provider_refuses_to_autocreate_when_lookup_fails(monkeypatch) -> None:
    provider_instance = SecretToolInstanceSecretProvider()
    store_called = False

    monkeypatch.setattr(
        provider_instance,
        "_run",
        lambda _args: subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="Cannot autolaunch D-Bus"),
    )

    def fake_store(_instance: str, _purpose: str, _secret: bytes) -> None:
        nonlocal store_called
        store_called = True

    monkeypatch.setattr(provider_instance, "_store", fake_store)

    with pytest.raises(AccountStoreError, match="secret-tool lookup failed"):
        provider_instance.get_secret("Demo", "account_memory")

    assert store_called is False


def test_secret_tool_provider_refuses_empty_successful_lookup(monkeypatch) -> None:
    provider_instance = SecretToolInstanceSecretProvider(create_if_missing=False)

    monkeypatch.setattr(
        provider_instance,
        "_run",
        lambda _args: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    with pytest.raises(AccountStoreError, match="lookup returned an empty secret"):
        provider_instance._lookup("Demo", "account_memory")


def test_secret_tool_provider_refuses_ambiguous_lookup_matches(monkeypatch) -> None:
    provider_instance = SecretToolInstanceSecretProvider(create_if_missing=False)
    encoded = base64.urlsafe_b64encode(b"a" * 32).decode("ascii") + "\n"

    def fake_run(args: list[str], *, input_text: str = "") -> subprocess.CompletedProcess[str]:
        if args and args[0] == "lookup":
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=encoded, stderr="")
        if args and args[0] == "search":
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="[/31]\n[/32]\n", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=2, stdout="", stderr="unexpected")

    monkeypatch.setattr(provider_instance, "_run", fake_run)

    with pytest.raises(AccountStoreError, match="multiple matching instance secret items"):
        provider_instance.get_secret("Demo", "account_memory")


def test_secret_tool_provider_refuses_to_overwrite_existing_search_item(monkeypatch) -> None:
    provider_instance = SecretToolInstanceSecretProvider(create_if_missing=True)
    calls: list[tuple[str, ...]] = []

    def fake_run(args: list[str], *, input_text: str = "") -> subprocess.CompletedProcess[str]:
        calls.append(tuple(args))
        if args and args[0] == "lookup":
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")
        if args and args[0] == "search":
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="[/31]\nsecret = <redacted>\n", stderr="")
        if args and args[0] == "store":
            pytest.fail("store must not be called when search finds an existing item")
        return subprocess.CompletedProcess(args=args, returncode=2, stdout="", stderr="unexpected")

    monkeypatch.setattr(provider_instance, "_run", fake_run)

    with pytest.raises(AccountStoreError, match="refused to overwrite an existing instance secret item"):
        provider_instance.get_secret("Demo", "account_memory")

    assert any(call[0] == "search" for call in calls)


def test_account_store_refuses_to_autocreate_mapping_secret_for_existing_encrypted_metadata(tmp_path, monkeypatch) -> None:
    first = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    first.resolve_or_create_account(telegram_identity_key(395935293), display_label="Teladi")

    secret_provider = SecretToolInstanceSecretProvider(create_if_missing=True)
    monkeypatch.setattr(secret_provider, "_lookup", lambda _instance, _purpose: None)
    monkeypatch.setattr(
        secret_provider,
        "_store",
        lambda _instance, _purpose, _secret: pytest.fail("store must not be called for existing encrypted metadata"),
    )

    with pytest.raises(AccountStoreError, match="refusing to create missing instance secret for existing encrypted account metadata"):
        AccountStore(tmp_path / "accounts", "Depressionsbot", secret_provider, create_dirs=False)


def test_account_store_refuses_to_autocreate_memory_secret_for_existing_encrypted_state(tmp_path, monkeypatch) -> None:
    account_id = "a" * 128
    account_dir = tmp_path / "accounts" / "accounts" / account_id
    account_dir.mkdir(parents=True)
    EncryptedJsonVault(
        "Depressionsbot",
        provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
    ).write_json(account_dir / LLM_STATE_FILENAME, {"previous_response_id": "resp_1"})

    secret_provider = SecretToolInstanceSecretProvider(create_if_missing=True)
    monkeypatch.setattr(secret_provider, "_lookup", lambda _instance, _purpose: None)
    monkeypatch.setattr(
        secret_provider,
        "_store",
        lambda _instance, _purpose, _secret: pytest.fail("store must not be called for existing encrypted state"),
    )

    with pytest.raises(AccountStoreError, match="refusing to create missing instance secret for existing encrypted account memory/state"):
        AccountStore(tmp_path / "accounts", "Depressionsbot", secret_provider, create_dirs=False)


def test_account_store_refuses_to_autocreate_memory_secret_for_existing_encrypted_instance_state(tmp_path, monkeypatch) -> None:
    root = tmp_path / "accounts"
    EncryptedJsonVault(
        "Depressionsbot",
        provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
    ).write_json(tmp_path / "Version_Notifications.json", {"versions": {"1.0.3": {"sent_identities": []}}})

    secret_provider = SecretToolInstanceSecretProvider(create_if_missing=True)
    monkeypatch.setattr(secret_provider, "_lookup", lambda _instance, _purpose: None)
    monkeypatch.setattr(
        secret_provider,
        "_store",
        lambda _instance, _purpose, _secret: pytest.fail("store must not be called for existing encrypted instance state"),
    )

    with pytest.raises(AccountStoreError, match="refusing to create missing instance secret for existing encrypted account memory/state"):
        AccountStore(root, "Depressionsbot", secret_provider, create_dirs=False)


def test_account_store_refuses_to_autocreate_memory_secret_for_existing_encrypted_codex_outbox_state(tmp_path, monkeypatch) -> None:
    account_id = "a" * 128
    account_dir = tmp_path / "accounts" / "accounts" / account_id
    account_dir.mkdir(parents=True)
    EncryptedJsonVault(
        "Depressionsbot",
        provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
    ).write_jsonl(
        account_dir / CODEX_HISTORY_OUTBOX_FILENAME,
        [{"kind": "codex_run_summary", "id": "hist_existing", "status": "sent"}],
    )

    secret_provider = SecretToolInstanceSecretProvider(create_if_missing=True)
    monkeypatch.setattr(secret_provider, "_lookup", lambda _instance, _purpose: None)
    monkeypatch.setattr(
        secret_provider,
        "_store",
        lambda _instance, _purpose, _secret: pytest.fail("store must not be called for existing encrypted codex outbox state"),
    )

    with pytest.raises(AccountStoreError, match="refusing to create missing instance secret for existing encrypted account memory/state"):
        AccountStore(tmp_path / "accounts", "Depressionsbot", secret_provider, create_dirs=False)


def test_account_store_records_key_manifest_and_refuses_missing_manifest_secret(tmp_path, monkeypatch) -> None:
    root = tmp_path / "accounts"
    stored: dict[tuple[str, str], bytes] = {}
    secret_provider = SecretToolInstanceSecretProvider(create_if_missing=True)

    monkeypatch.setattr(secret_provider, "_lookup", lambda instance, purpose: stored.get((instance, purpose)))
    monkeypatch.setattr(secret_provider, "_store", lambda instance, purpose, secret: stored.__setitem__((instance, purpose), secret))

    first = AccountStore(root, "Depressionsbot", secret_provider, create_dirs=True)
    memory_key = first.account_memory_vault.key
    assert stored[("Depressionsbot", ACCOUNT_MEMORY_KEY_PURPOSE)] == memory_key
    assert (root / "Account_Keyring.json").exists()

    stored.pop(("Depressionsbot", ACCOUNT_MEMORY_KEY_PURPOSE))
    second_provider = SecretToolInstanceSecretProvider(create_if_missing=True)
    monkeypatch.setattr(second_provider, "_lookup", lambda instance, purpose: stored.get((instance, purpose)))
    monkeypatch.setattr(second_provider, "_store", lambda instance, purpose, secret: pytest.fail("missing manifest secret must not be recreated"))

    with pytest.raises(AccountStoreError, match="refusing to create missing instance secret for existing encrypted account key manifest"):
        AccountStore(root, "Depressionsbot", second_provider, create_dirs=False)


def test_account_store_refuses_changed_manifest_secret_before_memory_decryption(tmp_path, monkeypatch) -> None:
    root = tmp_path / "accounts"
    stored: dict[tuple[str, str], bytes] = {}
    first_provider = SecretToolInstanceSecretProvider(create_if_missing=True)

    monkeypatch.setattr(first_provider, "_lookup", lambda instance, purpose: stored.get((instance, purpose)))
    monkeypatch.setattr(first_provider, "_store", lambda instance, purpose, secret: stored.__setitem__((instance, purpose), secret))

    first = AccountStore(root, "Depressionsbot", first_provider, create_dirs=True)
    _memory_key = first.account_memory_vault.key
    stored[("Depressionsbot", ACCOUNT_MEMORY_KEY_PURPOSE)] = b"b" * 32
    second_provider = SecretToolInstanceSecretProvider(create_if_missing=True)
    monkeypatch.setattr(second_provider, "_lookup", lambda instance, purpose: stored.get((instance, purpose)))
    monkeypatch.setattr(second_provider, "_store", lambda instance, purpose, secret: pytest.fail("changed manifest secret must not be recreated"))

    with pytest.raises(AccountStoreError, match="instance secret verifier mismatch"):
        AccountStore(root, "Depressionsbot", second_provider, create_dirs=False)


def test_account_store_refuses_to_record_manifest_for_wrong_mapping_key(tmp_path, monkeypatch) -> None:
    root = tmp_path / "accounts"
    first = AccountStore(root, "Depressionsbot", provider())
    first.resolve_or_create_account(telegram_identity_key(395935293), display_label="Teladi")
    secret_provider = SecretToolInstanceSecretProvider(create_if_missing=True)

    monkeypatch.setattr(secret_provider, "_lookup", lambda _instance, _purpose: b"b" * 32)
    monkeypatch.setattr(secret_provider, "_store", lambda _instance, _purpose, _secret: pytest.fail("wrong key must not be stored"))

    with pytest.raises(AccountStoreError, match="account metadata is not decryptable with the current Secret Service key"):
        AccountStore(root, "Depressionsbot", secret_provider, create_dirs=False)

    assert not (root / ACCOUNT_KEYRING_FILENAME).exists()


def test_account_store_refuses_to_record_manifest_for_wrong_sqlite_memory_key(tmp_path, monkeypatch) -> None:
    root = tmp_path / "accounts"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    first = AccountStore(root, "Depressionsbot", provider())
    account_id = first.resolve_or_create_account(telegram_identity_key(395935293), display_label="Teladi")
    first.write_memory_entries(account_id, [{"id": "mem_keep", "user_text": "nicht ueberschreiben"}])
    first.write_memory_index(account_id, {"index": {"entries": {"mem_keep": {"kind": "observation"}}}})
    secret_provider = SecretToolInstanceSecretProvider(create_if_missing=True)

    def lookup(_instance: str, purpose: str) -> bytes | None:
        if purpose == INSTANCE_MAPPING_KEY_PURPOSE:
            return b"a" * 32
        if purpose == ACCOUNT_MEMORY_KEY_PURPOSE:
            return b"b" * 32
        return None

    monkeypatch.setattr(secret_provider, "_lookup", lookup)
    monkeypatch.setattr(secret_provider, "_store", lambda _instance, _purpose, _secret: pytest.fail("wrong key must not be stored"))

    with pytest.raises(AccountStoreError, match="SQLite account memory entries are not decryptable with the current Secret Service key"):
        AccountStore(root, "Depressionsbot", secret_provider, create_dirs=False)

    manifest = json.loads((root / ACCOUNT_KEYRING_FILENAME).read_text(encoding="utf-8"))
    assert INSTANCE_MAPPING_KEY_PURPOSE in manifest["purposes"]
    assert ACCOUNT_MEMORY_KEY_PURPOSE not in manifest["purposes"]


def test_account_store_refuses_to_autocreate_memory_secret_for_existing_sqlite_rows_without_env(tmp_path, monkeypatch) -> None:
    root = tmp_path / "accounts"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    store = AccountStore(root, "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(395935293), display_label="Teladi")
    store.write_memory_entries(account_id, [{"id": "mem_keep", "user_text": "nicht ueberschreiben"}])
    store.write_memory_index(account_id, {"index": {"entries": {"mem_keep": {"kind": "observation"}}}})

    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", raising=False)
    secret_provider = SecretToolInstanceSecretProvider(create_if_missing=True)
    monkeypatch.setattr(
        secret_provider,
        "_lookup",
        lambda _instance, purpose: b"a" * 32 if purpose == INSTANCE_MAPPING_KEY_PURPOSE else None,
    )
    monkeypatch.setattr(
        secret_provider,
        "_store",
        lambda _instance, _purpose, _secret: pytest.fail("store must not be called for existing SQLite memory"),
    )

    with pytest.raises(AccountStoreError, match="refusing to create missing instance secret for existing encrypted sqlite account memory"):
        AccountStore(root, "Depressionsbot", secret_provider, create_dirs=False)


def test_account_store_refuses_to_autocreate_pepper_for_existing_secret_verifiers(tmp_path, monkeypatch) -> None:
    root = tmp_path / "accounts"
    first = AccountStore(root, "Depressionsbot", provider())
    account_id = first.resolve_or_create_account(telegram_identity_key(395935293), display_label="Teladi")
    _account_id, _account_secret = first.register_account(account_id)

    secret_provider = SecretToolInstanceSecretProvider(create_if_missing=True)
    monkeypatch.setattr(
        secret_provider,
        "_lookup",
        lambda _instance, purpose: b"a" * 32 if purpose == INSTANCE_MAPPING_KEY_PURPOSE else None,
    )
    monkeypatch.setattr(
        secret_provider,
        "_store",
        lambda _instance, _purpose, _secret: pytest.fail("store must not be called for an existing verifier pepper"),
    )
    with pytest.raises(AccountStoreError, match="refusing to create missing instance secret for existing encrypted account secret verifiers"):
        AccountStore(root, "Depressionsbot", secret_provider, create_dirs=False)


def test_account_store_can_create_pepper_when_encrypted_account_secrets_are_empty(tmp_path, monkeypatch) -> None:
    root = tmp_path / "accounts"
    first = AccountStore(root, "Depressionsbot", provider())
    account_id = first.resolve_or_create_account(telegram_identity_key(395935293), display_label="Teladi")
    first.vault.write_json(first.secrets_path, {})
    stored: dict[tuple[str, str], bytes] = {("Depressionsbot", INSTANCE_MAPPING_KEY_PURPOSE): b"a" * 32}
    secret_provider = SecretToolInstanceSecretProvider(create_if_missing=True)

    def lookup(instance: str, purpose: str) -> bytes | None:
        return stored.get((instance, purpose))

    def store_secret(instance: str, purpose: str, secret: bytes) -> None:
        stored[(instance, purpose)] = secret

    monkeypatch.setattr(secret_provider, "_lookup", lookup)
    monkeypatch.setattr(secret_provider, "_store", store_secret)
    second = AccountStore(root, "Depressionsbot", secret_provider, create_dirs=False)

    returned_account_id, account_secret = second.register_account(account_id)

    assert returned_account_id == account_id
    assert ("Depressionsbot", INSTANCE_PEPPER_PURPOSE) in stored
    assert second.verify_secret(account_id, account_secret)


def test_account_store_bootstraps_runtime_pepper_for_first_secret_only(tmp_path, monkeypatch) -> None:
    root = tmp_path / "accounts"
    stored: dict[tuple[str, str], bytes] = {("Bote_der_Wahrheit", INSTANCE_MAPPING_KEY_PURPOSE): b"a" * 32}
    secret_provider = SecretToolInstanceSecretProvider(create_if_missing=False)

    def lookup(instance: str, purpose: str) -> bytes | None:
        return stored.get((instance, purpose))

    def store_secret(instance: str, purpose: str, secret: bytes) -> None:
        assert purpose == INSTANCE_PEPPER_PURPOSE
        stored[(instance, purpose)] = secret

    monkeypatch.setattr(secret_provider, "_lookup", lookup)
    monkeypatch.setattr(secret_provider, "_store", store_secret)
    store = AccountStore(root, "Bote_der_Wahrheit", secret_provider)
    account_id = store.resolve_or_create_account(telegram_identity_key(395935293), display_label="Teladi")

    returned_account_id, account_secret = store.register_account(account_id)

    assert returned_account_id == account_id
    assert ("Bote_der_Wahrheit", INSTANCE_PEPPER_PURPOSE) in stored
    assert store.verify_secret(account_id, account_secret)
    manifest = json.loads((root / ACCOUNT_KEYRING_FILENAME).read_text(encoding="utf-8"))
    assert INSTANCE_PEPPER_PURPOSE in manifest["purposes"]


def test_account_store_records_required_pepper_manifest_for_existing_verifier(tmp_path, monkeypatch) -> None:
    root = tmp_path / "accounts"
    first = AccountStore(root, "Depressionsbot", provider())
    account_id = first.resolve_or_create_account(telegram_identity_key(395935293), display_label="Teladi")
    first.register_account(account_id)
    stored: dict[tuple[str, str], bytes] = {
        ("Depressionsbot", INSTANCE_MAPPING_KEY_PURPOSE): b"a" * 32,
        ("Depressionsbot", INSTANCE_PEPPER_PURPOSE): b"a" * 32,
    }
    secret_provider = SecretToolInstanceSecretProvider(create_if_missing=True)

    monkeypatch.setattr(secret_provider, "_lookup", lambda instance, purpose: stored.get((instance, purpose)))
    monkeypatch.setattr(secret_provider, "_store", lambda _instance, _purpose, _secret: pytest.fail("existing verifier keys must not be recreated"))

    AccountStore(root, "Depressionsbot", secret_provider, create_dirs=False)

    manifest = json.loads((root / ACCOUNT_KEYRING_FILENAME).read_text(encoding="utf-8"))
    assert INSTANCE_PEPPER_PURPOSE in manifest["purposes"]


def test_account_store_refuses_to_autocreate_memory_secret_for_existing_postgres_rows(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "postgres")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_POSTGRES_DSN", "postgresql://localhost/teebotus_test")
    monkeypatch.setattr("TeeBotus.runtime.accounts._postgres_memory_has_instance_payload_rows", lambda _dsn, _instance, _timeout: True)
    secret_provider = SecretToolInstanceSecretProvider(create_if_missing=True)
    monkeypatch.setattr(secret_provider, "_lookup", lambda _instance, _purpose: None)
    monkeypatch.setattr(
        secret_provider,
        "_store",
        lambda _instance, _purpose, _secret: pytest.fail("store must not be called for existing PostgreSQL memory"),
    )

    with pytest.raises(AccountStoreError, match="refusing to create missing instance secret for existing encrypted postgres account memory"):
        AccountStore(tmp_path / "accounts", "Depressionsbot", secret_provider, create_dirs=False)


def test_account_store_refuses_to_record_manifest_for_wrong_postgres_memory_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "postgres")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_POSTGRES_DSN", "postgresql://localhost/teebotus_test")
    monkeypatch.setattr("TeeBotus.runtime.accounts._postgres_memory_has_instance_payload_rows", lambda _dsn, _instance, _timeout: True)
    monkeypatch.setattr("TeeBotus.runtime.accounts._postgres_memory_account_ids", lambda _dsn, _instance, _timeout: ("a" * 128,), raising=False)

    import TeeBotus.runtime.postgres_memory as postgres_memory

    class FakePostgresBackend:
        def __init__(self, *, instance_name, provider, purpose, config) -> None:
            self.instance_name = instance_name
            self.provider = provider
            self.purpose = purpose
            self.config = config
            self.last_entry_read_error = ""
            self.last_entry_skipped = 0
            self.last_index_read_error = ""

        def read_entries(self, _account_id: str) -> list[dict[str, str]]:
            if self.provider.get_secret(self.instance_name, self.purpose) != b"a" * 32:
                self.last_entry_read_error = "PostgreSQL account memory payload could not be decrypted"
                self.last_entry_skipped = 1
                return []
            return [{"id": "mem_keep"}]

        def read_index(self, _account_id: str) -> dict[str, object]:
            if self.provider.get_secret(self.instance_name, self.purpose) != b"a" * 32:
                self.last_index_read_error = "PostgreSQL account memory payload could not be decrypted"
                return {}
            return {"index": {"entries": {"mem_keep": {}}}}

    monkeypatch.setattr(postgres_memory, "PostgresAccountMemoryBackend", FakePostgresBackend)
    secret_provider = SecretToolInstanceSecretProvider(create_if_missing=True)

    def lookup(_instance: str, purpose: str) -> bytes | None:
        if purpose == ACCOUNT_MEMORY_KEY_PURPOSE:
            return b"b" * 32
        return None

    monkeypatch.setattr(secret_provider, "_lookup", lookup)
    monkeypatch.setattr(secret_provider, "_store", lambda _instance, _purpose, _secret: pytest.fail("wrong PostgreSQL key must not be stored"))

    with pytest.raises(AccountStoreError, match="PostgreSQL account memory entries are not decryptable with the current Secret Service key"):
        AccountStore(tmp_path / "accounts", "Depressionsbot", secret_provider, create_dirs=False)

    assert not (tmp_path / "accounts" / ACCOUNT_KEYRING_FILENAME).exists()


def test_first_contact_creates_account_and_encrypted_identity_mapping(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(395935293), display_label="Teladi")

    assert HEX_128.fullmatch(account_id)
    assert store.get_account_for_identity("telegram:user:395935293") == account_id
    raw_identity_file = (tmp_path / "accounts" / "Account_Identities.json").read_text(encoding="utf-8")
    assert account_id not in raw_identity_file
    assert "telegram:user:395935293" not in raw_identity_file
    assert "TMBMAP1" in raw_identity_file


def test_relative_account_store_root_does_not_nest_vault_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = AccountStore(Path("instances/Depressionsbot/data/accounts"), "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(395935293), display_label="Teladi")

    expected_profile = tmp_path / "instances" / "Depressionsbot" / "data" / "accounts" / "accounts" / account_id / "Account_Profile.json"
    nested_profile = (
        tmp_path
        / "instances"
        / "Depressionsbot"
        / "data"
        / "accounts"
        / "instances"
        / "Depressionsbot"
        / "data"
        / "accounts"
        / "accounts"
        / account_id
        / "Account_Profile.json"
    )
    assert expected_profile.exists()
    assert not nested_profile.exists()
    assert store.get_account_for_identity("telegram:user:395935293") == account_id


def test_account_id_convenience_lookup_and_optional_create(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    identity = telegram_identity_key(395935293)

    assert store.account_id(identity) is None
    created = store.account_id(identity, create=True, display_label="Teladi")

    assert created is not None
    assert HEX_128.fullmatch(created)
    assert store.account_id(identity) == created
    assert store.resolve_or_create_account(identity) == created


def test_list_account_ids_discovers_resolvable_accounts(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    first = store.resolve_or_create_account(telegram_identity_key(1))
    second = store.resolve_or_create_account(telegram_identity_key(2))
    profile = store._read_account_profile(second)
    profile["status"] = "tombstoned"
    store._write_account_profile(second, profile)

    assert store.list_account_ids() == (first,)
    assert set(store.list_account_ids(include_unresolvable=True)) == {first, second}


def test_telegram_identity_key_uses_username_and_display_fallbacks() -> None:
    assert telegram_identity_key(395935293, username="Teladi") == "telegram:user:395935293"
    assert telegram_identity_key("", username="@Teladi") == "telegram:username:teladi"
    display_key = telegram_identity_key("", display_name="Teladi Example")
    assert display_key.startswith("telegram:display:")
    assert len(display_key.removeprefix("telegram:display:")) == 64


def test_matrix_identity_key_uses_localpart_and_display_fallbacks() -> None:
    assert matrix_identity_key("@ada:example.org", localpart="ada") == "matrix:user:@ada:example.org"
    assert matrix_identity_key("", localpart="@Ada") == "matrix:localpart:ada"
    display_key = matrix_identity_key("", display_name="Ada Lovelace")
    assert display_key.startswith("matrix:display:")
    assert len(display_key.removeprefix("matrix:display:")) == 64


def test_signal_identity_key_normalizes_uuid_case() -> None:
    assert signal_identity_key(source_uuid="ABC-DEF") == "signal:uuid:abc-def"


def test_identity_lookup_normalizes_case_insensitive_fallback_keys(tmp_path) -> None:
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())

    signal_account = store.resolve_or_create_account("signal:uuid:ABC-DEF")
    telegram_account = store.resolve_or_create_account("telegram:username:@AdaUser")
    matrix_account = store.resolve_or_create_account("matrix:localpart:@Ada")

    assert store.get_account_for_identity("signal:uuid:abc-def") == signal_account
    assert store.resolve_or_create_account("signal:uuid:abc-def") == signal_account
    assert store.get_account_for_identity("telegram:username:adauser") == telegram_account
    assert store.resolve_or_create_account("telegram:username:ADAUSER") == telegram_account
    assert store.get_account_for_identity("matrix:localpart:ada") == matrix_account
    assert store.resolve_or_create_account("matrix:localpart:ADA") == matrix_account


def test_identity_lookup_migrates_legacy_case_variant_key(tmp_path) -> None:
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    canonical_key = "signal:uuid:abc-def"
    legacy_key = "signal:uuid:ABC-DEF"
    account_id = store.resolve_or_create_account(canonical_key)
    identities = store._load_identities()
    payload = identities.pop(canonical_key)
    payload["identity_key"] = legacy_key
    identities[legacy_key] = payload
    store._save_identities(identities)
    profile = store._read_account_profile(account_id)
    profile["linked_identities"] = [legacy_key]
    store._write_account_profile(account_id, profile)

    assert store.get_account_for_identity(canonical_key) == account_id
    assert store.resolve_or_create_account(canonical_key) == account_id

    migrated_identities = store._load_identities()
    assert canonical_key in migrated_identities
    assert legacy_key not in migrated_identities
    migrated_profile = store._read_account_profile(account_id)
    assert migrated_profile["linked_identities"] == [canonical_key]


def test_identity_alias_repair_rolls_back_on_identity_write_failure(tmp_path) -> None:
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    canonical_key = "signal:uuid:abc-def"
    legacy_key = "signal:uuid:ABC-DEF"
    account_id = store.resolve_or_create_account(canonical_key)
    identities = store._load_identities()
    payload = identities.pop(canonical_key)
    payload["identity_key"] = legacy_key
    identities[legacy_key] = payload
    store._save_identities(identities)
    profile = store._read_account_profile(account_id)
    profile["linked_identities"] = [legacy_key]
    store._write_account_profile(account_id, profile)
    previous_identity_bytes = store.identities_path.read_bytes()
    previous_profile_bytes = (store.account_dir(account_id) / "Account_Profile.json").read_bytes()
    previous_index_bytes = store.account_index_path.read_bytes()

    with patch.object(store, "_save_identities", side_effect=AccountStoreError("identity write failed")):
        with pytest.raises(AccountStoreError, match="identity write failed"):
            store.get_account_for_identity(canonical_key)

    assert store.identities_path.read_bytes() == previous_identity_bytes
    assert (store.account_dir(account_id) / "Account_Profile.json").read_bytes() == previous_profile_bytes
    assert store.account_index_path.read_bytes() == previous_index_bytes


def test_identity_lookup_removes_legacy_alias_when_canonical_key_exists(tmp_path) -> None:
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    canonical_key = "signal:uuid:abc-def"
    legacy_key = "signal:uuid:ABC-DEF"
    canonical_account = store.resolve_or_create_account(canonical_key)
    legacy_account = store.resolve_or_create_account("telegram:user:legacy")
    identities = store._load_identities()
    identities[legacy_key] = {
        "schema_version": 1,
        "instance": "Depressionsbot",
        "identity_key": legacy_key,
        "account_id": legacy_account,
        "first_seen_at": "2026-06-15T12:00:00+00:00",
        "last_seen_at": "2026-06-15T12:00:00+00:00",
    }
    store._save_identities(identities)
    legacy_profile = store._read_account_profile(legacy_account)
    legacy_profile["linked_identities"] = [legacy_key]
    store._write_account_profile(legacy_account, legacy_profile)

    assert store.get_account_for_identity(legacy_key) == canonical_account

    migrated_identities = store._load_identities()
    assert canonical_key in migrated_identities
    assert legacy_key not in migrated_identities
    canonical_profile = store._read_account_profile(canonical_account)
    legacy_profile = store._read_account_profile(legacy_account)
    assert canonical_profile["linked_identities"] == [canonical_key]
    assert legacy_profile["linked_identities"] == []
    assert legacy_profile["status"] == "orphaned"


def test_identity_lookup_prefers_resolvable_legacy_alias_over_stale_canonical_key(tmp_path) -> None:
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    canonical_key = "signal:uuid:abc-def"
    legacy_key = "signal:uuid:ABC-DEF"
    stale_account = store.resolve_or_create_account(canonical_key)
    valid_account = store.resolve_or_create_account("telegram:user:valid")
    stale_profile = store._read_account_profile(stale_account)
    stale_profile["status"] = "tombstoned"
    store._write_account_profile(stale_account, stale_profile)
    identities = store._load_identities()
    identities[legacy_key] = {
        "schema_version": 1,
        "instance": "Depressionsbot",
        "identity_key": legacy_key,
        "account_id": valid_account,
        "first_seen_at": "2026-06-15T12:00:00+00:00",
        "last_seen_at": "2026-06-15T12:00:00+00:00",
    }
    store._save_identities(identities)
    valid_profile = store._read_account_profile(valid_account)
    valid_profile["linked_identities"] = ["telegram:user:valid", legacy_key]
    store._write_account_profile(valid_account, valid_profile)

    assert store.get_account_for_identity(canonical_key) == valid_account
    assert store.resolve_or_create_account(canonical_key) == valid_account

    migrated_identities = store._load_identities()
    assert migrated_identities[canonical_key]["account_id"] == valid_account
    assert legacy_key not in migrated_identities
    migrated_valid_profile = store._read_account_profile(valid_account)
    assert canonical_key in migrated_valid_profile["linked_identities"]
    assert legacy_key not in migrated_valid_profile["linked_identities"]


def test_identity_route_is_stored_encrypted_and_read_back(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    identity = telegram_identity_key(395935293)
    store.resolve_or_create_account(identity, display_label="Teladi")

    store.update_identity_route(identity, channel="telegram", chat_id="395935293", chat_type="private", adapter_slot=2)

    route = store.get_identity_route(identity)
    assert route is not None
    assert route["adapter_slot"] == 2
    assert route["channel"] == "telegram"
    assert route["chat_id"] == "395935293"
    assert route["chat_type"] == "private"
    assert route["last_seen_at"]
    raw_identity_file = (tmp_path / "accounts" / "Account_Identities.json").read_text(encoding="utf-8")
    assert "395935293" not in raw_identity_file


def test_identity_route_normalizes_channel_and_chat_type(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    identity = signal_identity_key(source_uuid="abc")
    store.resolve_or_create_account(identity)

    store.update_identity_route(identity, channel="Signal", chat_id="+491", chat_type="Private", adapter_slot=1)

    route = store.get_identity_route(identity)
    assert route is not None
    assert route["channel"] == "signal"
    assert route["chat_type"] == "private"
    assert route["chat_id"] == "+491"


def test_privacy_confirmation_is_persisted_in_profile_and_reset_by_memory_reset(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(395935293), display_label="Teladi")

    assert store.has_privacy_confirmation(account_id) is False

    store.confirm_privacy(account_id, source="telegram")

    assert store.has_privacy_confirmation(account_id) is True

    store.reset_structured_memory(account_id)

    assert store.has_privacy_confirmation(account_id) is False


def test_confirm_privacy_rolls_back_profile_when_index_write_fails(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(395935293))
    profile_path = store.account_dir(account_id) / "Account_Profile.json"
    previous_profile = profile_path.read_bytes()
    previous_index = store.account_index_path.read_bytes()

    with patch.object(store, "_upsert_account_index", side_effect=AccountStoreError("index write failed")):
        with pytest.raises(AccountStoreError, match="index write failed"):
            store.confirm_privacy(account_id, source="telegram")

    assert profile_path.read_bytes() == previous_profile
    assert store.account_index_path.read_bytes() == previous_index
    assert store.has_privacy_confirmation(account_id) is False


def test_profile_identity_list_corruption_is_rejected_without_mutation(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(395935293))
    profile_path = store.account_dir(account_id) / "Account_Profile.json"
    profile = store._read_account_profile(account_id)
    profile["linked_identities"] = "telegram:user:corrupt"
    store._write_account_profile(account_id, profile)
    corrupted_profile = profile_path.read_bytes()
    previous_index = store.account_index_path.read_bytes()

    with pytest.raises(AccountStoreError, match="linked_identities must be a string list"):
        store.confirm_privacy(account_id, source="telegram")

    assert profile_path.read_bytes() == corrupted_profile
    assert store.account_index_path.read_bytes() == previous_index


def test_clear_privacy_confirmation_retry_repairs_index_after_write_failure(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(395935293))
    store.confirm_privacy(account_id, source="telegram")
    original_account_index = store._upsert_account_index
    failed = False
    profile_path = store.account_dir(account_id) / "Account_Profile.json"
    previous_profile = profile_path.read_bytes()
    previous_index = store.account_index_path.read_bytes()

    def fail_once(profile):
        nonlocal failed
        if not failed:
            failed = True
            raise AccountStoreError("index write failed")
        return original_account_index(profile)

    with patch.object(store, "_upsert_account_index", side_effect=fail_once):
        with pytest.raises(AccountStoreError, match="index write failed"):
            store.clear_privacy_confirmation(account_id)

    assert profile_path.read_bytes() == previous_profile
    assert store.account_index_path.read_bytes() == previous_index
    assert store.has_privacy_confirmation(account_id) is True
    store.clear_privacy_confirmation(account_id)
    assert store.has_privacy_confirmation(account_id) is False
    assert account_id in store._load_index().get("accounts", {})


def test_reset_structured_account_memory_writes_empty_schema_index(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(395935293), display_label="Teladi")
    store.append_structured_memory_entry(account_id, {"id": "mem_old", "user_text": "Mond", "bot_text": "Gemerkt."})

    store.reset_structured_memory(account_id)

    index_doc = store.read_memory_index(account_id)
    nested_index = index_doc["index"]
    assert index_doc["schema_version"] == 2
    assert index_doc["scope"] == "account"
    assert index_doc["account_id"] == account_id
    assert nested_index["recent_ids"] == []
    assert nested_index["accessed_ids"] == []
    assert nested_index["keywords"] == {}
    assert nested_index["entries"] == {}
    assert nested_index["graph"]["relations"] == []
    assert nested_index["semantic_cache"]["source"] == "User_Memory_Entries.jsonl"
    assert nested_index["semantic_cache"]["rebuildable"] is True
    assert nested_index["semantic_cache"]["entries"] == {}
    assert store.read_memory_entries(account_id) == []
    assert store.check_structured_memory_index(account_id).ok


def test_reset_structured_account_memory_rolls_back_entries_when_index_write_fails(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(395935293), display_label="Teladi")
    store.append_structured_memory_entry(account_id, {"id": "mem_old", "user_text": "Mond", "bot_text": "Gemerkt."})
    previous_rows = store.read_memory_entries(account_id)
    previous_index = store.read_memory_index(account_id)

    with patch.object(
        store,
        "write_memory_index",
        side_effect=[AccountStoreError("index write failed"), None],
    ):
        with pytest.raises(AccountStoreError, match="index write failed"):
            store.reset_structured_memory(account_id)

    assert store.read_memory_entries(account_id) == previous_rows
    assert store.read_memory_index(account_id) == previous_index


def test_reset_structured_memory_rolls_back_memory_when_privacy_clear_fails(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(395935293), display_label="Teladi")
    store.append_structured_memory_entry(account_id, {"id": "mem_old", "user_text": "Mond", "bot_text": "Gemerkt."})
    store.confirm_privacy(account_id, source="telegram")
    previous_rows = store.read_memory_entries(account_id)
    previous_index = store.read_memory_index(account_id)
    profile_path = store.account_dir(account_id) / "Account_Profile.json"
    previous_profile = profile_path.read_bytes()
    previous_account_index = store.account_index_path.read_bytes()

    with patch.object(store, "_upsert_account_index", side_effect=AccountStoreError("index write failed")):
        with pytest.raises(AccountStoreError, match="index write failed"):
            store.reset_structured_memory(account_id)

    assert store.read_memory_entries(account_id) == previous_rows
    assert store.read_memory_index(account_id) == previous_index
    assert profile_path.read_bytes() == previous_profile
    assert store.account_index_path.read_bytes() == previous_account_index
    assert store.has_privacy_confirmation(account_id) is True


def test_register_generates_single_secret_and_verifier_not_plaintext(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Bote_der_Wahrheit", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    returned_account_id, secret = store.register_account(account_id)

    assert returned_account_id == account_id
    assert HEX_128.fullmatch(secret)
    assert store.verify_secret(account_id, secret)
    secrets_raw = (tmp_path / "accounts" / "Account_Secrets.json").read_text(encoding="utf-8")
    assert secret not in secrets_raw

    with pytest.raises(AccountStoreError):
        store.register_account(account_id)


def test_register_holds_identity_lock_across_active_secret_check_and_rotation(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Bote_der_Wahrheit", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    lock_states: list[bool] = []

    @contextmanager
    def recording_lock():
        lock_states.append(True)
        try:
            yield
        finally:
            lock_states.pop()

    with patch.object(store, "account_identity_lock", recording_lock), patch.object(
        store,
        "rotate_secret",
        return_value=(account_id, "b" * 128),
    ) as rotate_secret:
        assert store.register_account(account_id) == (account_id, "b" * 128)

    rotate_secret.assert_called_once_with(account_id)
    assert lock_states == []


def test_memory_reads_hold_account_lock(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    lock_states: list[str] = []

    class Backend:
        def read_index(self, _account_id):
            assert lock_states == [account_id]
            return {"index": {}}

        def read_entries(self, _account_id):
            assert lock_states == [account_id]
            return [{"id": "memory-1"}]

        def read_entries_by_ids(self, _account_id, _memory_ids):
            assert lock_states == [account_id]
            return [{"id": "memory-1"}]

    @contextmanager
    def recording_lock(locked_account_id):
        lock_states.append(locked_account_id)
        try:
            yield
        finally:
            lock_states.pop()

    store._account_memory_backend = Backend()
    with patch.object(store, "account_memory_lock", recording_lock):
        assert store.read_memory_index(account_id) == {"index": {}}
        assert store.read_memory_entries(account_id) == [{"id": "memory-1"}]
        assert store.read_memory_entries_by_ids(account_id, ["memory-1"]) == [{"id": "memory-1"}]

    assert lock_states == []


def test_account_memory_backend_lazy_init_is_serialized(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    lock_states: list[bool] = []
    backend = object()

    class RecordingLock:
        def __enter__(self):
            lock_states.append(True)
            return self

        def __exit__(self, _exc_type, _exc_value, _traceback):
            lock_states.pop()
            return False

    def create_backend():
        assert lock_states == [True]
        return backend

    with patch("TeeBotus.runtime.accounts._ACCOUNT_MEMORY_BACKEND_LOCK", RecordingLock()), patch.object(
        store,
        "_create_account_memory_backend",
        side_effect=create_backend,
    ) as create:
        assert store.account_memory_backend is backend
        assert store.account_memory_backend is backend

    create.assert_called_once_with()
    assert lock_states == []


def test_memory_retrieval_holds_account_lock_across_snapshot(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    lock_states: list[str] = []

    @contextmanager
    def recording_lock(locked_account_id):
        lock_states.append(locked_account_id)
        try:
            yield
        finally:
            lock_states.pop()

    def read_entries(_account_id):
        assert lock_states == [account_id]
        return []

    def read_index(_account_id):
        assert lock_states == [account_id]
        return {}

    def read_entries_by_ids(_account_id, _memory_ids):
        assert lock_states == [account_id]
        return []

    with patch.object(store, "account_memory_lock", recording_lock), patch.object(
        store,
        "read_memory_entries",
        side_effect=read_entries,
    ), patch.object(store, "read_memory_index", side_effect=read_index), patch.object(
        store,
        "read_memory_entries_by_ids",
        side_effect=read_entries_by_ids,
    ):
        assert store.rank_structured_memory_ids(account_id) == ()
        assert store.select_structured_memory(account_id).selected_ids == ()
        assert store.select_structured_memory_by_ids(account_id, ["missing"], mark_accessed=False).selected_ids == ()

    assert lock_states == []


def test_rotate_secret_invalidates_old_secret(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Bote_der_Wahrheit", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    _, first_secret = store.register_account(account_id)
    _, second_secret = store.rotate_secret(account_id)

    assert first_secret != second_secret
    assert not store.verify_secret(account_id, first_secret)
    assert store.verify_secret(account_id, second_secret)


def test_rotate_secret_rolls_back_when_profile_write_fails(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Bote_der_Wahrheit", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    _, old_secret = store.register_account(account_id)
    previous_verifier = (store.account_dir(account_id) / "Secret_Verifier.json").read_bytes()
    previous_profile = store._read_account_profile(account_id)
    previous_index = store._load_index()
    original_write_profile = store._write_account_profile

    with patch.object(
        store,
        "_write_account_profile",
        side_effect=[AccountStoreError("profile write failed"), original_write_profile],
    ):
        with pytest.raises(AccountStoreError, match="profile write failed"):
            store.rotate_secret(account_id)

    assert store.verify_secret(account_id, old_secret)
    assert (store.account_dir(account_id) / "Secret_Verifier.json").read_bytes() == previous_verifier
    assert store._read_account_profile(account_id) == previous_profile
    assert store._load_index() == previous_index


def test_secret_tool_rotate_secret_preserves_instance_keys_and_memory(tmp_path, monkeypatch):
    stored: dict[tuple[str, str], bytes] = {}
    secret_provider = SecretToolInstanceSecretProvider(create_if_missing=True)
    monkeypatch.setattr(secret_provider, "_lookup", lambda instance, purpose: stored.get((instance, purpose)))
    monkeypatch.setattr(secret_provider, "_store", lambda instance, purpose, secret: stored.__setitem__((instance, purpose), secret))
    store = AccountStore(tmp_path / "accounts", "Bote_der_Wahrheit", secret_provider)
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.append_structured_memory_entry(account_id, {"id": "mem_1", "user_text": "Bitte merken."})
    _, first_secret = store.register_account(account_id)
    before_keys = dict(stored)

    _, second_secret = store.rotate_secret(account_id)

    assert first_secret != second_secret
    assert store.verify_secret(account_id, second_secret)
    assert stored == before_keys
    entries = store.read_memory_entries(account_id)
    assert [entry.get("id") for entry in entries] == ["mem_1"]


def test_resolve_or_create_account_repairs_index_after_partial_write(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    identity_key = telegram_identity_key(1)
    original_account_index = store._upsert_account_index

    with patch.object(store, "_upsert_account_index", side_effect=AccountStoreError("index write failed")):
        with pytest.raises(AccountStoreError, match="index write failed"):
            store.resolve_or_create_account(identity_key)

    assert store.get_account_for_identity(identity_key) is None
    assert store.list_account_ids(include_unresolvable=True) == ()

    with patch.object(store, "_upsert_account_index", side_effect=original_account_index):
        account_id = store.resolve_or_create_account(identity_key)
    assert account_id in store._load_index().get("accounts", {})


def test_resolve_or_create_account_removes_profile_when_identity_write_fails(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    identity_key = telegram_identity_key(1)

    with patch.object(store, "_save_identities", side_effect=AccountStoreError("identity write failed")):
        with pytest.raises(AccountStoreError, match="identity write failed"):
            store.resolve_or_create_account(identity_key)

    assert store.get_account_for_identity(identity_key) is None
    assert store.list_account_ids(include_unresolvable=True) == ()


def test_ensure_external_account_repairs_index_after_partial_write(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = "a" * 128
    original_account_index = store._upsert_account_index
    failed = False

    def fail_once(profile):
        nonlocal failed
        if not failed:
            failed = True
            raise AccountStoreError("index write failed")
        return original_account_index(profile)

    with patch.object(store, "_upsert_account_index", side_effect=fail_once):
        with pytest.raises(AccountStoreError, match="index write failed"):
            store.ensure_external_account(account_id, source_instance="Bote_der_Wahrheit")
        assert not (store.account_dir(account_id) / "Account_Profile.json").exists()
        assert account_id not in store._load_index().get("accounts", {})
        assert account_id not in store.list_account_ids(include_unresolvable=True)
        store.ensure_external_account(account_id, source_instance="Bote_der_Wahrheit")

    assert account_id in store._load_index().get("accounts", {})


def test_ensure_external_account_preserves_multiple_source_links(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = "a" * 128

    store.ensure_external_account(account_id, source_instance="Bote_der_Wahrheit", source_account_id="source-a")
    store.ensure_external_account(account_id, source_instance="TeeBotus_Logger", source_account_id="source-b")
    store.ensure_external_account(account_id, source_instance="Bote_der_Wahrheit", source_account_id="source-a")

    links = store._read_account_profile(account_id)["external_links"]
    assert [(link["source_instance"], link["source_account_id"]) for link in links] == [
        ("Bote_der_Wahrheit", "source-a"),
        ("TeeBotus_Logger", "source-b"),
    ]


def test_ensure_external_account_rolls_back_new_source_link_on_index_failure(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = "a" * 128
    store.ensure_external_account(account_id, source_instance="Bote_der_Wahrheit", source_account_id="source-a")
    profile_path = store.account_dir(account_id) / "Account_Profile.json"
    previous_profile = profile_path.read_bytes()
    previous_index = store.account_index_path.read_bytes()

    with patch.object(store, "_upsert_account_index", side_effect=AccountStoreError("index write failed")):
        with pytest.raises(AccountStoreError, match="index write failed"):
            store.ensure_external_account(account_id, source_instance="TeeBotus_Logger", source_account_id="source-b")

    assert profile_path.read_bytes() == previous_profile
    assert store.account_index_path.read_bytes() == previous_index


def test_link_identity_merges_temporary_memory_and_tombstones_temp(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    target = store.resolve_or_create_account(telegram_identity_key(1))
    _, secret = store.register_account(target)
    temp = store.resolve_or_create_account(signal_identity_key(source_uuid="abc"))

    temp_dir = store.account_dir(temp)
    target_dir = store.account_dir(target)
    store.write_memory_entries(temp, [{"text": "from signal"}])
    store.write_memory_entries(target, [{"text": "from telegram"}])
    (temp_dir / "User_Habbits_and_behave.md").write_text("temporary note", encoding="utf-8")
    (target_dir / "User_Habbits_and_behave.md").write_text("target note", encoding="utf-8")

    result = store.link_identity(signal_identity_key(source_uuid="abc"), target, secret, display_label="Signal")

    assert result["merged_from"] == temp
    assert store.get_account_for_identity("signal:uuid:abc") == target
    merged_entries = store.read_memory_entries(target)
    assert any(entry.get("text") == "from signal" for entry in merged_entries)
    assert any(entry.get("text") == "from telegram" for entry in merged_entries)
    raw_entries = (target_dir / "User_Memory_Entries.jsonl").read_text(encoding="utf-8")
    assert "from signal" not in raw_entries
    assert "TMBMAP1" in raw_entries
    merged_habits = (target_dir / "User_Habbits_and_behave.md").read_text(encoding="utf-8")
    assert "target note" in merged_habits
    assert "temporary note" in merged_habits
    assert (temp_dir / "Account_Tombstone.json").exists()
    assert not (temp_dir / "User_Memory_Entries.jsonl").exists()


def test_merge_accounts_retry_after_identity_write_failure_is_idempotent(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    target = store.resolve_or_create_account(telegram_identity_key(1))
    source_identity = signal_identity_key(source_uuid="retry-merge")
    source = store.resolve_or_create_account(source_identity)
    store.write_memory_entries(source, [{"id": "mem_source", "text": "einmal"}])
    store.write_account_text(source, "User_Habbits_and_behave.md", "Quelle")

    with patch.object(store, "_save_identities", side_effect=AccountStoreError("identity write failed")):
        with pytest.raises(AccountStoreError, match="identity write failed"):
            store.merge_accounts(source, target)

    store.merge_accounts(source, target)

    assert [row["id"] for row in store.read_memory_entries(target)] == ["mem_source"]
    habits = store.read_account_text(target, "User_Habbits_and_behave.md")
    assert habits.count("## Merged from") == 1
    assert store.get_account_for_identity(source_identity) == target
    assert not (store.account_dir(source) / USER_MEMORY_ENTRIES_FILENAME).exists()


def test_merge_accounts_locks_source_and_target_memory_during_read_merge_write(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider(), memory_backend_enabled=False)
    target = store.resolve_or_create_account(telegram_identity_key(1))
    source = store.resolve_or_create_account(signal_identity_key(source_uuid="locked-merge"))
    store.write_memory_entries(source, [{"id": "mem_source", "text": "Quelle"}])
    entered_merge = threading.Event()
    release_merge = threading.Event()
    append_started = threading.Event()
    append_finished = threading.Event()
    merge_errors: list[BaseException] = []
    append_errors: list[BaseException] = []
    original_merge_jsonl = store._merge_jsonl

    def block_merge(source_path, target_path, *, vault):
        entered_merge.set()
        assert release_merge.wait(2)
        return original_merge_jsonl(source_path, target_path, vault=vault)

    def run_merge():
        try:
            store.merge_accounts(source, target)
        except BaseException as exc:  # noqa: BLE001 - surface thread failures in assertions below.
            merge_errors.append(exc)

    def append_target_memory():
        append_started.set()
        try:
            store.append_structured_memory_entry(target, {"id": "mem_concurrent", "text": "Parallel"})
        except BaseException as exc:  # noqa: BLE001 - surface thread failures in assertions below.
            append_errors.append(exc)
        finally:
            append_finished.set()

    with patch.object(store, "_merge_jsonl", side_effect=block_merge):
        merge_thread = threading.Thread(target=run_merge)
        merge_thread.start()
        assert entered_merge.wait(2)
        append_thread = threading.Thread(target=append_target_memory)
        append_thread.start()
        assert append_started.wait(2)
        assert not append_finished.wait(0.2)
        release_merge.set()
        merge_thread.join(2)
        append_thread.join(2)

    assert not merge_thread.is_alive()
    assert not append_thread.is_alive()
    assert not merge_errors
    assert not append_errors
    assert {row["id"] for row in store.read_memory_entries(target)} == {"mem_source", "mem_concurrent"}


def test_merge_accounts_preserves_json_account_collections(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider(), memory_backend_enabled=False)
    target = store.resolve_or_create_account(telegram_identity_key(1))
    source = store.resolve_or_create_account(signal_identity_key(source_uuid="json-collections"))

    store.write_agent_state(source, {"proactive": {"enabled": True}})
    store.write_status_auth_state(source, {"authorized": True, "source": "test"})
    store.append_proactive_outbox_item(source, {"id": "pro_source", "message_text": "Proaktiv"})
    store.append_proactive_audit_event(source, {"id": "audit_source", "event_type": "test"})
    store.append_proactive_dispatch_result(source, {"id": "pro_dispatch", "status": "sent"})
    store.append_status_outbox_item(source, {"id": "status_source", "message_text": "Status"})
    store.append_status_dispatch_result(source, {"id": "status_dispatch", "status": "sent"})
    store.append_codex_history_item(source, {"id": "history_source", "summary": "Codex"})
    store.append_codex_history_dispatch_result(source, {"id": "history_dispatch", "status": "sent"})
    store.write_codex_history_projects(source, [{"id": "project_source", "repo": "TeeBotus"}])

    store.merge_accounts(source, target)

    assert store.read_agent_state(target)["proactive"]["enabled"] is True
    assert store.read_status_auth_state(target)["authorized"] is True
    assert store.read_proactive_outbox(target)[0]["id"] == "pro_source"
    assert store.read_proactive_audit(target)[0]["id"] == "audit_source"
    assert store.read_proactive_dispatch_results(target)[0]["id"] == "pro_dispatch"
    assert store.read_status_outbox(target)[0]["id"] == "status_source"
    assert store.read_status_dispatch_results(target)[0]["id"] == "status_dispatch"
    assert store.read_codex_history_outbox(target)[0]["id"] == "history_source"
    assert store.read_codex_history_dispatch_results(target)[0]["id"] == "history_dispatch"
    assert store.read_codex_history_projects(target)[0]["id"] == "project_source"
    assert not (store.account_dir(source) / PROACTIVE_OUTBOX_FILENAME).exists()


def test_merge_accounts_normalizes_source_before_retry_deduplication(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    target = store.resolve_or_create_account(telegram_identity_key(1))
    source = store.resolve_or_create_account(signal_identity_key(source_uuid="retry-legacy-row"))
    store.write_memory_entries(source, [{"text": "einmal ohne id"}])

    with patch.object(store, "_save_identities", side_effect=AccountStoreError("identity write failed")):
        with pytest.raises(AccountStoreError, match="identity write failed"):
            store.merge_accounts(source, target)

    store.merge_accounts(source, target)

    entries = store.read_memory_entries(target)
    assert len(entries) == 1
    assert entries[0]["text"] == "einmal ohne id"
    assert entries[0]["id"]


def test_merge_accounts_merges_and_clears_sql_memory(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "memory.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    target = store.resolve_or_create_account(telegram_identity_key(1))
    source = store.resolve_or_create_account(signal_identity_key(source_uuid="sql-merge"))
    store.append_structured_memory_entry(
        source,
        {
            "id": "mem_sql_source",
            "memory_type": "semantic",
            "user_text": "SQL-Quelle",
            "bot_text": "Uebernommen.",
        },
    )
    store.write_llm_state(
        source,
        {"previous_response_id": "resp-source", "updated_at": "2026-07-16T03:00:00+00:00"},
    )
    store.write_agent_state(source, {"proactive": {"enabled": True}})
    store.write_status_auth_state(source, {"authorized": True, "source": "test"})
    store.append_proactive_outbox_item(source, {"id": "pro_source", "message_text": "Proaktiv"})
    store.append_status_outbox_item(source, {"id": "status_source", "message_text": "Status"})
    store.append_codex_history_item(source, {"id": "history_source", "summary": "Codex"})

    store.merge_accounts(source, target)

    assert any(row["id"] == "mem_sql_source" for row in store.read_memory_entries(target))
    assert store.read_llm_state(target)["previous_response_id"] == "resp-source"
    assert store.read_agent_state(target)["proactive"]["enabled"] is True
    assert store.read_status_auth_state(target)["authorized"] is True
    assert store.read_proactive_outbox(target)[0]["id"] == "pro_source"
    assert store.read_status_outbox(target)[0]["id"] == "status_source"
    assert store.read_codex_history_outbox(target)[0]["id"] == "history_source"
    assert store.read_memory_entries(source) == []
    assert store.read_llm_state(source) == {}
    assert store.read_agent_state(source) == {}
    assert store.read_proactive_outbox(source) == []


def test_merge_accounts_resumes_tombstone_cleanup_after_failure(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    target = store.resolve_or_create_account(telegram_identity_key(1))
    source = store.resolve_or_create_account(signal_identity_key(source_uuid="cleanup-merge"))

    with patch.object(store, "_delete_dir_contents_except", side_effect=AccountStoreError("cleanup failed")):
        with pytest.raises(AccountStoreError, match="cleanup failed"):
            store.merge_accounts(source, target)

    assert (store.account_dir(source) / "Account_Tombstone.json").exists()
    assert source in store._load_index().get("accounts", {})
    store.merge_accounts(source, target)

    assert (store.account_dir(source) / "Account_Tombstone.json").exists()
    assert not (store.account_dir(source) / "Account_Profile.json").exists()
    assert source not in store._load_index().get("accounts", {})


def test_link_identity_merges_legacy_openai_state_into_llm_state(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    target = store.resolve_or_create_account(telegram_identity_key(1))
    _, secret = store.register_account(target)
    temp = store.resolve_or_create_account(signal_identity_key(source_uuid="abc"))

    store.write_llm_state(target, {"previous_response_id": "resp-target", "updated_at": "2026-06-01T00:00:00+00:00"})
    store.account_memory_vault.write_json(
        store.account_dir(temp) / OPENAI_STATE_FILENAME,
        {"previous_response_id": "resp-source", "updated_at": "2026-06-02T00:00:00+00:00"},
    )

    store.link_identity(signal_identity_key(source_uuid="abc"), target, secret, display_label="Signal")

    assert store.read_llm_state(target)["previous_response_id"] == "resp-source"
    assert (store.account_dir(target) / LLM_STATE_FILENAME).exists()


def test_read_llm_state_compares_timezone_aware_updated_at_by_instant(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))

    store.write_llm_state(account_id, {"previous_response_id": "resp-target", "updated_at": "2026-06-01T00:30:00+00:00"})
    store.account_memory_vault.write_json(
        store.account_dir(account_id) / OPENAI_STATE_FILENAME,
        {"previous_response_id": "resp-older-local-time", "updated_at": "2026-06-01T02:00:00+02:00"},
    )

    assert store.read_llm_state(account_id)["previous_response_id"] == "resp-target"


def test_read_llm_state_removes_newer_legacy_openai_state_after_plaintext_migration(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_llm_state(account_id, {"previous_response_id": "resp-target", "updated_at": "2026-06-01T00:00:00+00:00"})
    openai_path = store.account_dir(account_id) / OPENAI_STATE_FILENAME
    store.account_memory_vault.write_json(
        openai_path,
        {"previous_response_id": "resp-legacy", "updated_at": "2026-06-02T00:00:00+00:00"},
    )

    state = store.read_llm_state(account_id)

    assert state["previous_response_id"] == "resp-legacy"
    assert not openai_path.exists()
    assert store.account_memory_vault.read_json(store.account_dir(account_id) / LLM_STATE_FILENAME, {})["previous_response_id"] == "resp-legacy"


def test_read_llm_state_removes_older_legacy_openai_state_after_plaintext_migration(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_llm_state(account_id, {"previous_response_id": "resp-target", "updated_at": "2026-06-02T00:00:00+00:00"})
    openai_path = store.account_dir(account_id) / OPENAI_STATE_FILENAME
    store.account_memory_vault.write_json(
        openai_path,
        {"previous_response_id": "resp-legacy", "updated_at": "2026-06-01T00:00:00+00:00"},
    )

    state = store.read_llm_state(account_id)

    assert state["previous_response_id"] == "resp-target"
    assert not openai_path.exists()


def test_read_llm_state_migrates_newer_file_state_over_sql_state(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "memory.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_llm_state(
        account_id,
        {"previous_response_id": "resp-sql", "updated_at": "2026-06-01T00:00:00+00:00"},
    )
    llm_path = store.account_dir(account_id) / LLM_STATE_FILENAME
    store.account_memory_vault.write_json(
        llm_path,
        {"previous_response_id": "resp-file", "updated_at": "2026-06-02T00:00:00+00:00"},
    )

    state = store.read_llm_state(account_id)

    assert state["previous_response_id"] == "resp-file"
    assert not llm_path.exists()
    backend = store.account_memory_backend
    assert backend is not None
    assert backend.read_collection(account_id, "llm_state") == [state]


def test_unlink_identity_marks_orphaned_when_last_identity_removed(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))

    unlinked_account = store.unlink_identity(telegram_identity_key(1))

    assert unlinked_account == account_id
    summary = store.account_summary(account_id)
    assert summary["status"] == "orphaned"
    assert summary["linked_identities"] == []


def test_account_summary_holds_identity_lock_for_profile_snapshot(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    identity_key = telegram_identity_key(1)
    account_id = store.resolve_or_create_account(identity_key)
    lock_states: list[bool] = []
    original_read_profile = store._read_account_profile

    @contextmanager
    def recording_lock():
        lock_states.append(True)
        try:
            yield
        finally:
            lock_states.pop()

    def read_profile(profile_account_id):
        assert lock_states == [True]
        return original_read_profile(profile_account_id)

    with patch.object(store, "account_identity_lock", recording_lock), patch.object(
        store,
        "_read_account_profile",
        side_effect=read_profile,
    ):
        summary = store.account_summary(account_id)

    assert summary["account_id"] == account_id
    assert lock_states == []


def test_account_listing_reads_hold_identity_lock(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    identity_key = telegram_identity_key(1)
    account_id = store.resolve_or_create_account(identity_key)
    lock_states: list[bool] = []
    original_load_index = store._load_index
    original_read_profile = store._read_account_profile

    @contextmanager
    def recording_lock():
        lock_states.append(True)
        try:
            yield
        finally:
            lock_states.pop()

    def load_index():
        assert lock_states == [True]
        return original_load_index()

    def read_profile(profile_account_id):
        assert lock_states == [True]
        return original_read_profile(profile_account_id)

    with patch.object(store, "account_identity_lock", recording_lock), patch.object(
        store,
        "_load_index",
        side_effect=load_index,
    ), patch.object(store, "_read_account_profile", side_effect=read_profile):
        assert account_id in store.list_account_ids(include_unresolvable=True)
        assert store.list_identities_for_account(account_id) == [identity_key]

    assert lock_states == []


def test_secret_and_privacy_reads_hold_identity_lock(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    _, secret = store.register_account(account_id)
    store.confirm_privacy(account_id, source="telegram")
    lock_states: list[bool] = []

    @contextmanager
    def recording_lock():
        lock_states.append(True)
        try:
            yield
        finally:
            lock_states.pop()

    original_read_profile = store._read_account_profile

    def read_profile(profile_account_id):
        assert lock_states == [True]
        return original_read_profile(profile_account_id)

    with patch.object(store, "account_identity_lock", recording_lock), patch.object(
        store,
        "_read_account_profile",
        side_effect=read_profile,
    ):
        assert store.verify_secret(account_id, secret) is True
        assert store.has_privacy_confirmation(account_id) is True

    assert lock_states == []


@pytest.mark.parametrize(
    ("failing_method", "error_text"),
    [
        ("_write_account_profile", "profile write failed"),
        ("_upsert_account_index", "index write failed"),
        ("_save_identities", "identity write failed"),
    ],
)
def test_unlink_identity_retry_converges_after_partial_write_failure(tmp_path, failing_method, error_text):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    identity_key = telegram_identity_key(1)
    account_id = store.resolve_or_create_account(identity_key)
    metadata_paths = (
        store.identities_path,
        store.account_index_path,
        store.account_dir(account_id) / "Account_Profile.json",
    )
    previous_metadata = {path: path.read_bytes() for path in metadata_paths}

    with patch.object(store, failing_method, side_effect=AccountStoreError(error_text)):
        with pytest.raises(AccountStoreError, match=error_text):
            store.unlink_identity(identity_key)

    assert {path: path.read_bytes() for path in metadata_paths} == previous_metadata
    assert store.get_account_for_identity(identity_key) == account_id
    assert store.unlink_identity(identity_key) == account_id
    profile = store._read_account_profile(account_id)
    assert identity_key not in profile["linked_identities"]
    assert profile["status"] == "orphaned"


def test_link_identity_refuses_to_silently_merge_registered_source_account(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    target = store.resolve_or_create_account(telegram_identity_key(1))
    _, target_secret = store.register_account(target)
    source = store.resolve_or_create_account(signal_identity_key(source_uuid="abc"))
    store.register_account(source)

    with pytest.raises(AccountStoreError):
        store.link_identity(signal_identity_key(source_uuid="abc"), target, target_secret, display_label="Signal")

    assert store.get_account_for_identity("signal:uuid:abc") == source


def test_external_account_can_be_created_and_linked_without_local_secret(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = "a" * 128
    identity = telegram_identity_key(1)

    store.ensure_external_account(account_id, source_instance="Bote_der_Wahrheit")
    result = store.link_identity_to_account(identity, account_id, display_label="Admin")

    assert result["account_id"] == account_id
    assert store.get_account_for_identity(identity) == account_id
    summary = store.account_summary(account_id)
    assert summary["registered"] is False
    assert summary["secret_exists"] is False
    assert summary["linked_identities"] == [identity]
    profile = store._read_account_profile(account_id)
    assert profile["external_links"][0]["source_instance"] == "Bote_der_Wahrheit"


def test_link_identity_retry_repairs_profile_after_mapping_write_succeeds(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    identity_key = signal_identity_key(source_uuid="repair-me")

    with patch.object(store, "_add_identity_to_profile", side_effect=AccountStoreError("profile write failed")):
        with pytest.raises(AccountStoreError, match="profile write failed"):
            store.link_identity_to_account(identity_key, account_id, display_label="Signal")

    assert store.get_account_for_identity(identity_key) is None
    assert identity_key not in store._read_account_profile(account_id)["linked_identities"]

    result = store.link_identity_to_account(identity_key, account_id, display_label="Signal")

    assert result.get("already_linked") is not True
    assert identity_key in store._read_account_profile(account_id)["linked_identities"]


@pytest.mark.parametrize("failing_method", ["_write_account_profile", "_upsert_account_index", "_save_identities"])
def test_link_identity_rolls_back_all_metadata_after_partial_write(tmp_path, failing_method):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    identity_key = signal_identity_key(source_uuid=f"rollback-{failing_method}")
    metadata_paths = (
        store.identities_path,
        store.account_index_path,
        store.account_dir(account_id) / "Account_Profile.json",
    )
    previous_metadata = {path: path.read_bytes() for path in metadata_paths}

    with patch.object(store, failing_method, side_effect=AccountStoreError("identity metadata write failed")):
        with pytest.raises(AccountStoreError, match="identity metadata write failed"):
            store.link_identity_to_account(identity_key, account_id, display_label="Signal")

    assert {path: path.read_bytes() for path in metadata_paths} == previous_metadata
    assert store.get_account_for_identity(identity_key) is None
    assert identity_key not in store._read_account_profile(account_id)["linked_identities"]


def test_unlink_identity_and_rotate_secret_rolls_back_unlink_when_rotation_fails(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    identity_key = telegram_identity_key(1)
    account_id = store.resolve_or_create_account(identity_key)
    _, old_secret = store.register_account(account_id)

    with patch.object(store, "rotate_secret", side_effect=AccountStoreError("rotation failed")):
        with pytest.raises(AccountStoreError, match="rotation failed"):
            store.unlink_identity_and_rotate_secret(identity_key, account_id)

    assert store.get_account_for_identity(identity_key) == account_id
    assert identity_key in store._read_account_profile(account_id)["linked_identities"]
    assert store.verify_secret(account_id, old_secret)

    unlinked_account_id, new_secret = store.unlink_identity_and_rotate_secret(identity_key, account_id)
    assert unlinked_account_id == account_id
    assert store.get_account_for_identity(identity_key) is None
    assert store.verify_secret(account_id, new_secret)


def test_unlink_identity_and_rotate_secret_holds_identity_lock_across_steps(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    identity_key = telegram_identity_key(1)
    account_id = store.resolve_or_create_account(identity_key)
    lock_states: list[bool] = []

    @contextmanager
    def recording_lock():
        lock_states.append(True)
        try:
            yield
        finally:
            lock_states.pop()

    def unlink(_identity_key, _account_id):
        assert lock_states == [True]
        return account_id

    def rotate(_account_id):
        assert lock_states == [True]
        return account_id, "c" * 128

    with patch.object(store, "account_identity_lock", recording_lock), patch.object(
        store,
        "unlink_identity_if_linked_to",
        side_effect=unlink,
    ), patch.object(store, "rotate_secret", side_effect=rotate):
        assert store.unlink_identity_and_rotate_secret(identity_key, account_id) == (account_id, "c" * 128)

    assert lock_states == []


def test_encrypted_memory_with_wrong_instance_secret_does_not_fallback_to_envelope(tmp_path):
    first = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"a" * 32))
    account_id = first.resolve_or_create_account(telegram_identity_key(77))
    first.write_memory_index(account_id, {"keywords": {"tea": [1]}})

    second = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"b" * 32), create_dirs=False)

    with pytest.raises(AccountStoreError):
        second.read_memory_index(account_id)


def test_plaintext_structured_memory_does_not_bypass_instance_secret(tmp_path):
    first = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"a" * 32))
    account_id = first.resolve_or_create_account(telegram_identity_key(78))
    account_dir = first.account_dir(account_id)
    (account_dir / USER_MEMORY_INDEX_FILENAME).write_text('{"scope":"account"}\n', encoding="utf-8")
    (account_dir / USER_MEMORY_ENTRIES_FILENAME).write_text('{"id":"mem_plain"}\n', encoding="utf-8")

    second = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"b" * 32), create_dirs=False)

    with pytest.raises(AccountStoreError):
        second.read_memory_index(account_id)
    with pytest.raises(AccountStoreError):
        second.read_memory_entries(account_id)


def test_encrypted_vault_refuses_to_overwrite_existing_payload_with_wrong_secret(tmp_path):
    first = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"a" * 32))
    account_id = first.resolve_or_create_account(telegram_identity_key(77), display_label="Ada")
    profile_path = first.account_dir(account_id) / "Account_Profile.json"

    second = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"b" * 32), create_dirs=False)

    with pytest.raises(AccountStoreError, match="encrypted envelope authentication failed"):
        second.vault.write_json(profile_path, {"account_id": account_id, "status": "overwritten"})

    assert first._read_account_profile(account_id)["status"] == "active"


def test_account_tombstone_is_encrypted_after_merge(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    target = store.resolve_or_create_account(telegram_identity_key(10))
    _, secret = store.register_account(target)
    source = store.resolve_or_create_account(signal_identity_key(source_uuid="merge-me"))

    store.link_identity(signal_identity_key(source_uuid="merge-me"), target, secret)

    tombstone = store.account_dir(source) / "Account_Tombstone.json"
    raw = tombstone.read_text(encoding="utf-8")
    assert "TMBMAP1" in raw
    assert source not in raw


def test_account_text_helpers_reject_path_traversal(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))

    with pytest.raises(AccountStoreError):
        store.write_account_text(account_id, "../escape.md", "bad")
    with pytest.raises(AccountStoreError):
        store.read_account_text(account_id, "/tmp/escape.md")


def test_structured_account_memory_updates_profile_keyword_index_and_prompt(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_account_text(account_id, "User_Habbits_and_behave.md", "Ada bevorzugt knappe Antworten.")

    first_id = store.append_structured_memory_entry(
        account_id,
        {
            "channel": "telegram",
            "chat_type": "private",
            "source": {"chat_id": "1", "sender_id": "1"},
            "user_text": "Ich mag Mond Tee.",
            "bot_text": "Gemerkter Mond-Tee.",
        },
        profile_updates={
            "names": "Ada",
            "usernames": "@ada",
            "chat_ids": "1",
            "chat_titles": "Privat",
            "channels": "telegram",
        },
    )
    store.append_structured_memory_entry(
        account_id,
        {
            "channel": "signal",
            "chat_type": "private",
            "source": {"chat_id": "+491", "sender_id": "uuid"},
            "user_text": "Ich mag Kaffee.",
            "bot_text": "Gemerkter Kaffee.",
        },
        profile_updates={"channels": "signal"},
    )

    index = store.read_memory_index(account_id)
    assert index["scope"] == "account"
    assert index["profile"]["names"] == ["Ada"]
    assert index["profile"]["usernames"] == ["@ada"]
    assert index["profile"]["channels"] == ["telegram", "signal"]
    assert index["index"]["entries"][first_id]["kind"] == "observation"
    assert index["index"]["entries"][first_id]["importance"] == 3
    assert first_id in index["index"]["keywords"]["mond"]
    selection = store.select_structured_memory(account_id, query_text="mond", max_prompt_chars=12000, max_entry_chars=2000)

    assert selection.selected_ids[0] == first_id
    assert "Ada bevorzugt knappe Antworten." in selection.prompt_text
    assert '"scope": "account"' in selection.prompt_text
    assert '"kind": "observation"' in selection.prompt_text
    assert '"importance": 3' in selection.prompt_text
    assert '"user_text": "Ich mag Mond Tee."' in selection.prompt_text
    assert '"user_text": "Ich mag Kaffee."' in selection.prompt_text
    assert selection.selected_ids[-1] != first_id


def test_structured_account_memory_migrates_legacy_top_level_index(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_memory_entries(account_id, [{"id": "mem_legacy", "user_text": "Mond", "bot_text": "Tee"}])
    store.write_memory_index(account_id, {"keywords": {"mond": ["mem_legacy"]}, "recent_ids": ["mem_legacy"]})

    store.append_structured_memory_entry(account_id, {"id": "mem_new", "user_text": "Kaffee", "bot_text": "Tasse"})

    index = store.read_memory_index(account_id)
    assert "keywords" not in index
    assert index["schema_version"] == 2
    assert index["index"]["entries"]["mem_legacy"]["schema_version"] == 2
    assert index["index"]["keywords"]["mond"] == ["mem_legacy"]
    assert index["index"]["keywords"]["kaffee"] == ["mem_new"]


def test_append_structured_memory_repairs_missing_live_index_entries(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_memory_entries(
        account_id,
        [{"id": "mem_old", "user_text": "Mond", "bot_text": "Tee"}],
    )
    store.write_memory_index(account_id, {})

    store.append_structured_memory_entry(account_id, {"id": "mem_new", "user_text": "Kaffee", "bot_text": "Tasse"})

    index = store.read_memory_index(account_id)["index"]
    assert index["keywords"]["mond"] == ["mem_old"]
    assert index["keywords"]["kaffee"] == ["mem_new"]
    assert set(index["semantic_cache"]["entries"]) == {"mem_old", "mem_new"}


def test_structured_account_memory_rolls_back_entries_when_index_write_fails(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.append_structured_memory_entry(account_id, {"id": "mem_old", "user_text": "Mond", "bot_text": "Tee"})
    previous_rows = store.read_memory_entries(account_id)
    previous_index = store.read_memory_index(account_id)

    with patch.object(
        store,
        "write_memory_index",
        side_effect=[AccountStoreError("index write failed"), None],
    ):
        with pytest.raises(AccountStoreError, match="index write failed"):
            store.append_structured_memory_entry(account_id, {"id": "mem_new", "user_text": "Kaffee"})

    assert store.read_memory_entries(account_id) == previous_rows
    assert store.read_memory_index(account_id) == previous_index


def test_append_structured_account_memory_renames_duplicate_entry_id(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    first_id = store.append_structured_memory_entry(account_id, {"id": "mem_same", "user_text": "Mond", "bot_text": "Tee"})
    second_id = store.append_structured_memory_entry(account_id, {"id": "mem_same", "user_text": "Kaffee", "bot_text": "Tasse"})

    assert first_id == "mem_same"
    assert second_id != "mem_same"
    entries = store.read_memory_entries(account_id)
    assert [entry["id"] for entry in entries] == ["mem_same", second_id]
    index = store.read_memory_index(account_id)
    assert set(index["index"]["entries"]) == {"mem_same", second_id}
    assert index["index"]["keywords"]["kaffee"] == [second_id]


def test_rebuild_structured_account_memory_index_removes_stale_ids(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_memory_entries(
        account_id,
        [
            {
                "id": "mem_live",
                "channel": "telegram",
                "source": {"chat_id": "1"},
                "user_text": "Mond bleibt.",
                "bot_text": "Gemerkt.",
            }
        ],
    )
    store.write_memory_index(
        account_id,
        {
            "profile": {"names": ["Ada"]},
            "index": {
                "keywords": {"mond": ["mem_live", "mem_stale"], "stale": ["mem_stale"]},
                "recent_ids": ["mem_stale", "mem_live"],
                "entries": {"mem_live": {}, "mem_stale": {}},
            },
        },
    )

    store.rebuild_structured_memory_index(account_id)

    index = store.read_memory_index(account_id)
    assert index["profile"]["names"] == ["Ada"]
    assert index["index"]["recent_ids"] == ["mem_live"]
    assert index["index"]["keywords"]["mond"] == ["mem_live"]
    assert "stale" not in index["index"]["keywords"]
    assert list(index["index"]["entries"]) == ["mem_live"]
    entries = store.read_memory_entries(account_id)
    assert entries[0]["keywords"] == ["mond", "bleibt", "gemerkt"]
    assert entries[0]["kind"] == "observation"
    assert entries[0]["importance"] == 3


def test_rebuild_structured_account_memory_refuses_partial_sql_entries(tmp_path, monkeypatch):
    import sqlite3

    sqlite_path = tmp_path / "memory.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_memory_entries(
        account_id,
        [
            {"id": "mem_good", "user_text": "Mond", "bot_text": "Tee"},
            {"id": "mem_bad", "user_text": "Kaffee", "bot_text": "Tasse"},
        ],
    )
    with sqlite3.connect(sqlite_path) as connection:
        connection.execute(
            "UPDATE memory_entries SET payload_ciphertext = ? WHERE memory_id = ?",
            (b"broken", "mem_bad"),
        )
    store._account_memory_backend = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=sqlite_path, fallback_path=None),
    )

    with pytest.raises(AccountStoreError, match="entries are unreadable"):
        store.rebuild_structured_memory_index(account_id)
    with pytest.raises(AccountStoreError, match="cannot append structured memory"):
        store.append_structured_memory_entry(account_id, {"id": "mem_new", "user_text": "Neu"})

    with sqlite3.connect(sqlite_path) as connection:
        memory_ids = {
            str(row[0])
            for row in connection.execute(
                "SELECT memory_id FROM memory_entries WHERE account_id = ?",
                (account_id,),
            )
        }
    assert memory_ids == {"mem_good", "mem_bad"}


def test_account_memory_read_modify_and_retrieval_paths_refuse_partial_rows(tmp_path):
    class PartiallyUnreadableBackend:
        last_entry_read_error = "corrupt row"
        last_entry_skipped = 1
        last_index_read_error = ""
        write_entries_calls = 0

        def read_entries(self, _account_id):
            return [{"id": "mem_visible", "user_text": "Mond"}]

        def read_entries_by_ids(self, _account_id, _memory_ids):
            return [{"id": "mem_visible", "user_text": "Mond"}]

        def read_index(self, _account_id):
            return {}

        def write_entries(self, _account_id, _rows):
            self.write_entries_calls += 1

    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    backend = PartiallyUnreadableBackend()
    store._account_memory_backend = backend

    operations = (
        lambda: store.append_memory_entry(account_id, {"id": "mem_new"}),
        lambda: store.read_memory_entries_by_ids(account_id, ["mem_visible"]),
        lambda: store.rank_structured_memory_ids(account_id, query_text="Mond"),
        lambda: store.select_structured_memory(account_id, query_text="Mond"),
        lambda: store.select_structured_memory_by_ids(account_id, ["mem_visible"]),
        lambda: store.mark_structured_memory_accessed(account_id, ["mem_visible"]),
    )

    for operation in operations:
        with pytest.raises(AccountStoreError, match="entries are unreadable"):
            operation()
    assert backend.write_entries_calls == 0


def test_rebuild_structured_account_memory_rolls_back_entries_when_index_write_fails(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_memory_entries(account_id, [{"id": "mem_raw", "user_text": "Mond", "bot_text": "Tee"}])
    previous_rows = store.read_memory_entries(account_id)
    previous_index = store.read_memory_index(account_id)

    with patch.object(
        store,
        "write_memory_index",
        side_effect=[AccountStoreError("index write failed"), None],
    ):
        with pytest.raises(AccountStoreError, match="index write failed"):
            store.rebuild_structured_memory_index(account_id)

    assert store.read_memory_entries(account_id) == previous_rows
    assert store.read_memory_index(account_id) == previous_index


def test_structured_account_memory_importance_breaks_keyword_ties(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    low_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_low", "user_text": "Mond", "bot_text": "Tee", "importance": 1},
    )
    high_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_high", "user_text": "Mond", "bot_text": "Tasse", "kind": "preference", "importance": 5},
    )

    selection = store.select_structured_memory(account_id, query_text="mond", max_prompt_chars=12000, max_entry_chars=2000)

    assert selection.selected_ids[:2] == (high_id, low_id)
    index = store.read_memory_index(account_id)
    assert index["index"]["entries"][high_id]["kind"] == "preference"
    assert index["index"]["entries"][high_id]["importance"] == 5


def test_structured_account_memory_related_ids_boost_linked_entries(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    direct_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_direct", "user_text": "Mond", "bot_text": "Tee", "related_ids": ["mem_linked"]},
    )
    unrelated_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_unrelated", "user_text": "Kaffee", "bot_text": "Tasse"},
    )
    linked_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_linked", "user_text": "Blauer Planet", "bot_text": "Notiz"},
    )

    selection = store.select_structured_memory(account_id, query_text="mond", max_prompt_chars=12000, max_entry_chars=2000)

    assert selection.selected_ids[:3] == (direct_id, linked_id, unrelated_id)


def test_structured_account_memory_v2_keeps_entries_and_builds_graph_cache(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    anchor_id = store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_anchor",
            "kind": "risk_signal",
            "user_text": "Akute Krise bei Einsamkeit.",
            "bot_text": "Krise behutsam eingeordnet.",
            "importance": 5,
        },
    )
    hypothesis_id = store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_hypothesis",
            "kind": "psychoanalytic_hypothesis",
            "user_text": "Rueckzug wirkt wie Schutz vor Beschaemung.",
            "bot_text": "Hypothese nur vorsichtig nutzen.",
            "supports": [anchor_id],
            "contradicts": ["mem_old"],
        },
    )
    old_id = store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_old",
            "kind": "self_statement",
            "user_text": "Ich bin nie einsam.",
            "bot_text": "Als fruehere Selbstbeschreibung gemerkt.",
            "supersedes": [],
        },
    )

    index = store.read_memory_index(account_id)
    entries = store.read_memory_entries(account_id)

    assert index["schema_version"] == 2
    assert len(entries) == 3
    assert entries[0]["kind"] == "risk_signal"
    assert entries[0]["decay"]["policy"] == "retain"
    assert entries[1]["kind"] == "psychoanalytic_hypothesis"
    assert index["index"]["entries"][anchor_id]["salience"] == 8
    assert index["index"]["graph"]["links"]["supports"][hypothesis_id] == [anchor_id]
    assert index["index"]["graph"]["links"]["contradicts"][hypothesis_id] == [old_id]
    assert index["index"]["semantic_cache"]["rebuildable"] is True
    assert hypothesis_id in index["index"]["semantic_cache"]["entries"]


def test_structured_account_memory_accepts_clinical_note_kinds(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))

    examples = [
        ("mem_mse", "mse_mood", "MSE mood: niedergeschlagen.", "compact", 3),
        ("mem_risk", "suicidal_ideation", "Passive Suizidgedanken ohne Plan.", "retain", 6),
        ("mem_medication", "medication_adherence", "SSRI Einnahme meist regelmaessig.", "retain", 3),
        ("mem_process", "psychotherapy_process_note", "Vermeidung taucht bei Naehe auf.", "decay", 3),
        ("mem_hypothesis", "diagnostic_hypothesis", "Depressive Episode bleibt Hypothese.", "decay", 5),
        ("mem_treatment", "treatment_goal", "Schlafrhythmus stabilisieren.", "retain", 4),
    ]

    for memory_id, kind, user_text, expected_policy, expected_salience in examples:
        store.append_structured_memory_entry(
            account_id,
            {
                "id": memory_id,
                "kind": kind,
                "user_text": user_text,
                "bot_text": "Notiert.",
            },
        )

    entries = {entry["id"]: entry for entry in store.read_memory_entries(account_id)}
    index_entries = store.read_memory_index(account_id)["index"]["entries"]

    for memory_id, kind, _user_text, expected_policy, expected_salience in examples:
        assert entries[memory_id]["kind"] == kind
        assert entries[memory_id]["decay"]["policy"] == expected_policy
        assert index_entries[memory_id]["kind"] == kind
        assert index_entries[memory_id]["salience"] == expected_salience


def test_structured_account_memory_v2_has_no_default_entry_store_limit(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))

    for index in range(205):
        store.append_structured_memory_entry(account_id, {"id": f"mem_{index}", "user_text": f"Mond {index}", "bot_text": "Tee"})

    assert len(store.read_memory_entries(account_id)) == 205
    memory_index = store.read_memory_index(account_id)
    assert memory_index["index"]["retention"]["entry_store_limit"] is None
    assert memory_index["index"]["retention"]["storage_backend"] == "encrypted-jsonl-plus-json-index"
    assert memory_index["index"]["retention"]["next_backend_candidate"] == "sqlite-row-encrypted-projection"


def test_account_store_sqlite_backend_stores_memory_outside_json_files(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "memory.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))

    memory_id = store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_sqlite",
            "kind": "observation",
            "memory_type": "episodic",
            "user_text": "Mond SQLite geheim",
            "bot_text": "Notiert.",
            "keywords": ["mond", "sqlite"],
        },
    )

    assert memory_id == "mem_sqlite"
    entries = store.read_memory_entries(account_id)
    index = store.read_memory_index(account_id)
    assert entries[0]["id"] == "mem_sqlite"
    assert index["index"]["entries"]["mem_sqlite"]["kind"] == "observation"
    account_dir = store.account_dir(account_id)
    assert not (account_dir / "User_Memory_Entries.jsonl").exists()
    assert not (account_dir / "User_Memory_Index.json").exists()
    raw_db = sqlite_path.read_bytes()
    assert b"Mond SQLite geheim" not in raw_db


def test_account_store_sqlite_backend_migrates_proactive_jsonl_collections(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "memory.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    legacy_path = store.account_dir(account_id) / "Proactive_Outbox.jsonl"
    store.account_memory_vault.write_jsonl(
        legacy_path,
        [{"id": "pro_legacy", "message_text": "SQL Migration geheim", "status": "queued"}],
    )

    rows = store.read_proactive_outbox(account_id)

    assert rows == [{"id": "pro_legacy", "message_text": "SQL Migration geheim", "status": "queued"}]
    assert not legacy_path.exists()
    assert store.read_proactive_outbox(account_id) == rows
    store.write_proactive_audit(account_id, [{"id": "paud_1", "reason": "unsafe_message_text"}])
    store.append_proactive_dispatch_result(
        account_id,
        {"item_id": "pro_legacy", "status": "sent", "channel": "telegram", "message_ref": "42"},
    )
    assert not (store.account_dir(account_id) / "Proactive_Audit.jsonl").exists()
    assert not (store.account_dir(account_id) / "Proactive_Dispatch_Results.jsonl").exists()
    assert store.read_proactive_audit(account_id)[0]["reason"] == "unsafe_message_text"
    assert store.read_proactive_dispatch_results(account_id)[0]["message_ref"] == "42"
    agent_path = store.account_dir(account_id) / "Agent_State.json"
    store.account_memory_vault.write_json(agent_path, {"proactive": {"enabled": True}})
    assert store.read_agent_state(account_id)["proactive"]["enabled"] is True
    assert not agent_path.exists()
    store.write_llm_state(account_id, {"provider": "local", "thread_id": "state-geheim"})
    assert not (store.account_dir(account_id) / "LLM_State.json").exists()
    assert store.read_llm_state(account_id)["thread_id"] == "state-geheim"
    raw_db = sqlite_path.read_bytes()
    assert b"SQL Migration geheim" not in raw_db
    assert b"unsafe_message_text" not in raw_db
    assert b"state-geheim" not in raw_db


def test_append_proactive_audit_event_uses_outbox_lock(tmp_path, monkeypatch):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    calls: list[str] = []

    @contextmanager
    def tracked_lock(locked_account_id: str):
        calls.append(locked_account_id)
        yield

    monkeypatch.setattr(store, "proactive_outbox_lock", tracked_lock)

    event_id = store.append_proactive_audit_event(account_id, {"event_type": "test"})

    assert calls == [account_id]
    assert store.read_proactive_audit(account_id)[0]["id"] == event_id


def test_proactive_outbox_lock_is_reentrant(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))

    with store.proactive_outbox_lock(account_id):
        with store.proactive_outbox_lock(account_id):
            event_id = store.append_proactive_audit_event(account_id, {"event_type": "nested"})

    assert store.read_proactive_audit(account_id)[0]["id"] == event_id


def test_status_outbox_append_holds_memory_lock_across_read_modify_write(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_status_outbox(account_id, [{"id": "existing", "status": "queued"}])
    original_read = store.read_status_outbox
    first_read_started = threading.Event()
    release_first_read = threading.Event()
    writer_finished = threading.Event()
    read_count = [0]
    read_count_lock = threading.Lock()
    errors: list[BaseException] = []

    def blocking_read(target_account_id: str):
        rows = original_read(target_account_id)
        with read_count_lock:
            read_count[0] += 1
            is_first_read = read_count[0] == 1
        if is_first_read:
            first_read_started.set()
            if not release_first_read.wait(2):
                raise AssertionError("append read did not get released")
        return rows

    def append_item() -> None:
        try:
            store.append_status_outbox_item(account_id, {"id": "appended", "status": "queued"})
        except BaseException as exc:  # noqa: BLE001 - surface thread failures below.
            errors.append(exc)

    def append_directly() -> None:
        try:
            rows = store.read_status_outbox(account_id)
            rows.append({"id": "direct", "status": "queued"})
            store.write_status_outbox(account_id, rows)
        except BaseException as exc:  # noqa: BLE001 - surface thread failures below.
            errors.append(exc)
        finally:
            writer_finished.set()

    with patch.object(store, "read_status_outbox", side_effect=blocking_read):
        append_thread = threading.Thread(target=append_item)
        append_thread.start()
        assert first_read_started.wait(2)
        writer_thread = threading.Thread(target=append_directly)
        writer_thread.start()
        assert not writer_finished.wait(0.2)
        release_first_read.set()
        append_thread.join(2)
        writer_thread.join(2)

    assert not append_thread.is_alive()
    assert not writer_thread.is_alive()
    assert not errors
    assert {row["id"] for row in store.read_status_outbox(account_id)} == {"existing", "appended", "direct"}


@pytest.mark.parametrize(
    ("lock_method", "lock_filename"),
    (
        ("proactive_outbox_lock", f".{PROACTIVE_OUTBOX_FILENAME}.lock"),
        ("status_outbox_lock", f".{STATUS_OUTBOX_FILENAME}.lock"),
        ("codex_history_outbox_lock", f".{CODEX_HISTORY_OUTBOX_FILENAME}.lock"),
    ),
)
def test_account_scoped_locks_reject_redirected_lock_files(tmp_path, lock_method, lock_filename):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    account_dir = store.account_dir(account_id)
    outside = tmp_path / f"outside-{lock_method}"
    outside.write_bytes(b"keep")
    (account_dir / lock_filename).symlink_to(outside)

    with pytest.raises(AccountStoreError, match="unsafe account memory"):
        with getattr(store, lock_method)(account_id):
            pass

    assert outside.read_bytes() == b"keep"


def test_account_identity_lock_rejects_redirected_lock_file(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    outside = tmp_path / "outside-identity-lock"
    outside.write_bytes(b"keep")
    (store.root / ".Account_Identities.json.lock").symlink_to(outside)

    with pytest.raises(AccountStoreError, match="unsafe account memory identity lock"):
        with store.account_identity_lock():
            pass

    assert outside.read_bytes() == b"keep"


def test_atomic_write_rejects_symlinked_parent(tmp_path):
    outside = tmp_path / "outside-atomic-write"
    outside.mkdir()
    linked_parent = tmp_path / "linked-atomic-write"
    linked_parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(AccountStoreError, match="unsafe account memory atomic-write parent"):
        _atomic_write_text(linked_parent / "payload.txt", "must not escape")

    assert not (outside / "payload.txt").exists()


def test_account_json_document_falls_back_on_sql_diagnostics(tmp_path):
    class CorruptReadCollectionBackend:
        last_collection_read_error = "payload could not be decrypted"
        last_collection_skipped = 1

        def read_collection(self, _account_id: str, _collection: str) -> list[dict[str, object]]:
            return []

        def write_collection(self, _account_id: str, _collection: str, _rows: list[dict[str, object]]) -> None:
            raise AssertionError("diagnostic fallback must not rewrite collection")

    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store._account_memory_backend = CorruptReadCollectionBackend()
    legacy_path = store.account_dir(account_id) / STATUS_AUTH_STATE_FILENAME
    store.account_memory_vault.write_json(legacy_path, {"schema_version": 1, "authorized": True})

    assert store.read_status_auth_state(account_id) == {"schema_version": 1, "authorized": True}
    assert legacy_path.exists()


def test_account_json_document_refuses_sql_diagnostics_without_legacy(tmp_path):
    class CorruptReadCollectionBackend:
        last_collection_read_error = "payload could not be decrypted"
        last_collection_skipped = 1

        def read_collection(self, _account_id: str, _collection: str) -> list[dict[str, object]]:
            return []

        def write_collection(self, _account_id: str, _collection: str, _rows: list[dict[str, object]]) -> None:
            raise AssertionError("diagnostic failure must not rewrite collection")

    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store._account_memory_backend = CorruptReadCollectionBackend()

    with pytest.raises(AccountStoreError, match="status_auth"):
        store.read_status_auth_state(account_id)


def test_account_store_sqlite_backend_keeps_newer_legacy_jsonl_row_for_same_id(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "memory.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_proactive_outbox(
        account_id,
        [
            {
                "id": "pro_same",
                "message_text": "Bitte erinnern",
                "status": "queued",
                "created_at": "2026-06-15T08:00:00+00:00",
                "updated_at": "2026-06-15T08:00:00+00:00",
            }
        ],
    )
    legacy_path = store.account_dir(account_id) / "Proactive_Outbox.jsonl"
    store.account_memory_vault.write_jsonl(
        legacy_path,
        [
            {
                "id": "pro_same",
                "message_text": "Bitte erinnern",
                "status": "sent",
                "message_ref": "telegram:42",
                "created_at": "2026-06-15T08:00:00+00:00",
                "updated_at": "2026-06-15T09:00:00+00:00",
            }
        ],
    )

    rows = store.read_proactive_outbox(account_id)

    assert rows == [
        {
            "id": "pro_same",
            "message_text": "Bitte erinnern",
            "status": "sent",
            "message_ref": "telegram:42",
            "created_at": "2026-06-15T08:00:00+00:00",
            "updated_at": "2026-06-15T09:00:00+00:00",
        }
    ]
    assert not legacy_path.exists()
    assert store.read_proactive_outbox(account_id) == rows


def test_account_store_sqlite_backend_compacts_duplicate_jsonl_ids(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "memory.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    backend = store.account_memory_backend
    assert backend is not None
    backend.write_collection(
        account_id,
        "proactive_outbox",
        [
            {
                "id": "pro_same",
                "message_text": "Bitte erinnern",
                "status": "queued",
                "created_at": "2026-06-15T08:00:00+00:00",
                "updated_at": "2026-06-15T08:00:00+00:00",
            },
            {
                "id": "pro_same",
                "message_text": "Bitte erinnern",
                "status": "sent",
                "message_ref": "telegram:42",
                "created_at": "2026-06-15T08:00:00+00:00",
                "updated_at": "2026-06-15T09:00:00+00:00",
            },
        ],
    )
    legacy_path = store.account_dir(account_id) / "Proactive_Outbox.jsonl"
    store.account_memory_vault.write_jsonl(legacy_path, [])

    rows = store.read_proactive_outbox(account_id)

    assert rows == [
        {
            "id": "pro_same",
            "message_text": "Bitte erinnern",
            "status": "sent",
            "message_ref": "telegram:42",
            "created_at": "2026-06-15T08:00:00+00:00",
            "updated_at": "2026-06-15T09:00:00+00:00",
        }
    ]
    assert not legacy_path.exists()
    assert backend.read_collection(account_id, "proactive_outbox") == rows


def test_account_store_sqlite_backend_keeps_valid_timestamp_over_invalid_legacy_jsonl_row(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "memory.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_proactive_outbox(
        account_id,
        [
            {
                "id": "pro_same",
                "message_text": "Bitte erinnern",
                "status": "sent",
                "message_ref": "telegram:42",
                "created_at": "2026-06-15T08:00:00+00:00",
                "updated_at": "2026-06-15T09:00:00+00:00",
            }
        ],
    )
    legacy_path = store.account_dir(account_id) / "Proactive_Outbox.jsonl"
    store.account_memory_vault.write_jsonl(
        legacy_path,
        [
            {
                "id": "pro_same",
                "message_text": "Bitte erinnern",
                "status": "queued",
                "created_at": "broken",
                "updated_at": "zzzz",
            }
        ],
    )

    rows = store.read_proactive_outbox(account_id)

    assert rows[0]["status"] == "sent"
    assert rows[0]["message_ref"] == "telegram:42"
    assert rows[0]["updated_at"] == "2026-06-15T09:00:00+00:00"


def test_account_store_sqlite_backend_uses_valid_created_at_when_updated_at_is_invalid_jsonl_row(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "memory.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_proactive_outbox(
        account_id,
        [
            {
                "id": "pro_same",
                "message_text": "Bitte erinnern",
                "status": "queued",
                "created_at": "2026-06-15T08:00:00+00:00",
                "updated_at": "2026-06-15T08:00:00+00:00",
            }
        ],
    )
    legacy_path = store.account_dir(account_id) / "Proactive_Outbox.jsonl"
    store.account_memory_vault.write_jsonl(
        legacy_path,
        [
            {
                "id": "pro_same",
                "message_text": "Bitte erinnern",
                "status": "sent",
                "message_ref": "telegram:42",
                "created_at": "2026-06-15T09:00:00+00:00",
                "updated_at": "broken",
            }
        ],
    )

    rows = store.read_proactive_outbox(account_id)

    assert rows[0]["status"] == "sent"
    assert rows[0]["message_ref"] == "telegram:42"
    assert rows[0]["created_at"] == "2026-06-15T09:00:00+00:00"


def test_account_jsonl_collection_keeps_merged_rows_when_verify_read_reports_diagnostics(tmp_path):
    class DiagnosticAfterWriteBackend:
        def __init__(self) -> None:
            self.last_collection_read_error = ""
            self.last_collection_skipped = 0
            self.rows = [{"id": "pro_sql", "message_text": "SQL", "status": "queued"}]
            self.read_count = 0
            self.written_rows: list[dict[str, object]] = []

        def read_collection(self, _account_id: str, _collection: str) -> list[dict[str, object]]:
            self.read_count += 1
            if self.read_count == 1:
                self.last_collection_read_error = ""
                self.last_collection_skipped = 0
                return [dict(row) for row in self.rows]
            self.last_collection_read_error = "payload could not be decrypted"
            self.last_collection_skipped = 1
            return []

        def write_collection(self, _account_id: str, _collection: str, rows: list[dict[str, object]]) -> None:
            self.written_rows = [dict(row) for row in rows]

    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    backend = DiagnosticAfterWriteBackend()
    store._account_memory_backend = backend
    legacy_path = store.account_dir(account_id) / "Proactive_Outbox.jsonl"
    store.account_memory_vault.write_jsonl(
        legacy_path,
        [{"id": "pro_legacy", "message_text": "Legacy", "status": "queued"}],
    )

    rows = store.read_proactive_outbox(account_id)

    assert rows == [
        {"id": "pro_sql", "message_text": "SQL", "status": "queued"},
        {"id": "pro_legacy", "message_text": "Legacy", "status": "queued"},
    ]
    assert backend.written_rows == rows
    assert legacy_path.exists()


def test_account_jsonl_collection_discards_non_object_sql_rows(tmp_path):
    class MixedReadBackend:
        last_collection_read_error = ""
        last_collection_skipped = 0

        def read_collection(self, _account_id: str, _collection: str) -> list[object]:
            return ["corrupt row", {"id": "pro_valid", "status": "queued"}]

        def write_collection(self, _account_id: str, _collection: str, _rows: list[dict[str, object]]) -> None:
            raise AssertionError("invalid SQL rows must not trigger a rewrite")

    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store._account_memory_backend = MixedReadBackend()

    assert store.read_proactive_outbox(account_id) == [{"id": "pro_valid", "status": "queued"}]


@pytest.mark.parametrize(
    ("reader_name", "filename", "expected"),
    (
        (
            "read_llm_state",
            LLM_STATE_FILENAME,
            {"previous_response_id": "resp-sql", "updated_at": "2026-06-15T12:00:00+00:00"},
        ),
        (
            "read_agent_state",
            "Agent_State.json",
            {"proactive": {"enabled": True}, "updated_at": "2026-06-15T12:00:00+00:00"},
        ),
    ),
)
def test_account_json_document_uses_valid_rows_when_sql_diagnostics_are_partial(
    tmp_path, reader_name, filename, expected
):
    class PartialReadCollectionBackend:
        last_collection_read_error = "one payload could not be decrypted"
        last_collection_skipped = 1

        def read_collection(self, _account_id: str, _collection: str) -> list[dict[str, object]]:
            return [dict(expected)]

        def write_collection(self, _account_id: str, _collection: str, _rows: list[dict[str, object]]) -> None:
            pytest.fail("partial SQL read must not compact destructively")

    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    backend = PartialReadCollectionBackend()
    store._account_memory_backend = backend
    stale_path = store.account_dir(account_id) / filename
    store.account_memory_vault.write_json(stale_path, {"stale": True})
    legacy_path = store.account_dir(account_id) / OPENAI_STATE_FILENAME
    if reader_name == "read_llm_state":
        store.account_memory_vault.write_json(legacy_path, {"stale_legacy": True})

    state = getattr(store, reader_name)(account_id)

    assert state == expected
    assert stale_path.exists()
    if reader_name == "read_llm_state":
        assert legacy_path.exists()


def test_account_jsonl_collection_uses_valid_rows_when_sql_diagnostics_are_partial(tmp_path):
    class PartialReadCollectionBackend:
        last_collection_read_error = "one payload could not be decrypted"
        last_collection_skipped = 1

        def __init__(self) -> None:
            self.rows = [
                {
                    "id": "pro_sql",
                    "message_text": "SQL",
                    "status": "queued",
                    "updated_at": "2026-06-15T10:00:00+00:00",
                }
            ]

        def read_collection(self, _account_id: str, _collection: str) -> list[dict[str, object]]:
            return [dict(row) for row in self.rows]

        def write_collection(self, _account_id: str, _collection: str, _rows: list[dict[str, object]]) -> None:
            pytest.fail("partial SQL read must not compact destructively")

    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    backend = PartialReadCollectionBackend()
    store._account_memory_backend = backend
    legacy_path = store.account_dir(account_id) / PROACTIVE_OUTBOX_FILENAME
    store.account_memory_vault.write_jsonl(
        legacy_path,
        [
            {
                "id": "pro_sql",
                "message_text": "Legacy stale",
                "status": "sent",
                "updated_at": "2026-06-15T09:00:00+00:00",
            },
            {"id": "pro_legacy", "message_text": "Legacy", "status": "queued"},
        ],
    )

    rows = store.read_proactive_outbox(account_id)

    assert rows == [
        {
            "id": "pro_sql",
            "message_text": "SQL",
            "status": "queued",
            "updated_at": "2026-06-15T10:00:00+00:00",
        },
        {"id": "pro_legacy", "message_text": "Legacy", "status": "queued"},
    ]
    assert legacy_path.exists()


def test_account_jsonl_collection_keeps_legacy_after_silent_readback_loss(tmp_path):
    class SilentReadbackLossBackend:
        last_collection_read_error = ""
        last_collection_skipped = 0

        def __init__(self) -> None:
            self.read_count = 0

        def read_collection(self, _account_id: str, _collection: str) -> list[dict[str, object]]:
            self.read_count += 1
            if self.read_count == 1:
                return [{"id": "pro_sql", "message_text": "SQL", "status": "queued"}]
            return []

        def write_collection(self, _account_id: str, _collection: str, _rows: list[dict[str, object]]) -> None:
            return None

    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store._account_memory_backend = SilentReadbackLossBackend()
    legacy_path = store.account_dir(account_id) / PROACTIVE_OUTBOX_FILENAME
    store.account_memory_vault.write_jsonl(
        legacy_path,
        [{"id": "pro_legacy", "message_text": "Legacy", "status": "queued"}],
    )

    rows = store.read_proactive_outbox(account_id)

    assert rows == [
        {"id": "pro_sql", "message_text": "SQL", "status": "queued"},
        {"id": "pro_legacy", "message_text": "Legacy", "status": "queued"},
    ]
    assert legacy_path.exists()


def test_read_llm_state_keeps_legacy_after_silent_readback_loss(tmp_path):
    class SilentReadbackLossBackend:
        last_collection_read_error = ""
        last_collection_skipped = 0

        def __init__(self) -> None:
            self.read_count = 0

        def read_collection(self, _account_id: str, _collection: str) -> list[dict[str, object]]:
            self.read_count += 1
            if self.read_count == 1:
                return [{"previous_response_id": "resp-sql", "updated_at": "2026-06-15T08:00:00+00:00"}]
            return []

        def write_collection(self, _account_id: str, _collection: str, _rows: list[dict[str, object]]) -> None:
            return None

    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store._account_memory_backend = SilentReadbackLossBackend()
    legacy_path = store.account_dir(account_id) / LLM_STATE_FILENAME
    store.account_memory_vault.write_json(
        legacy_path,
        {"previous_response_id": "resp-legacy", "updated_at": "2026-06-15T09:00:00+00:00"},
    )

    state = store.read_llm_state(account_id)

    assert state["previous_response_id"] == "resp-legacy"
    assert legacy_path.exists()


def test_instance_json_state_uses_valid_rows_when_sql_diagnostics_are_partial(tmp_path):
    class PartialReadCollectionBackend:
        last_collection_read_error = "one payload could not be decrypted"
        last_collection_skipped = 1

        def read_collection(self, _account_id: str, _collection: str) -> list[dict[str, object]]:
            return [{"versions": {"2.0.0": {"sent_identities": ["telegram:user:222"]}}}]

        def write_collection(self, _account_id: str, _collection: str, _rows: list[dict[str, object]]) -> None:
            pytest.fail("partial SQL read must not compact destructively")

    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    backend = PartialReadCollectionBackend()
    store._account_memory_backend = backend
    legacy_path = tmp_path / "Version_Notifications.json"
    store.account_memory_vault.write_json(
        legacy_path,
        {"versions": {"1.0.0": {"sent_identities": ["telegram:user:111"]}}},
    )

    state = store.read_instance_json_state("Version_Notifications.json", "version_notifications", {"versions": {}})

    assert state == {"versions": {"2.0.0": {"sent_identities": ["telegram:user:222"]}}}
    assert legacy_path.exists()


def test_instance_json_state_keeps_legacy_after_silent_readback_loss(tmp_path):
    class SilentReadbackLossBackend:
        last_collection_read_error = ""
        last_collection_skipped = 0

        def __init__(self) -> None:
            self.read_count = 0

        def read_collection(self, _account_id: str, _collection: str) -> list[dict[str, object]]:
            self.read_count += 1
            if self.read_count == 1:
                return [{"versions": {"2.0.0": {"sent_identities": ["telegram:user:222"]}}}]
            return []

        def write_collection(self, _account_id: str, _collection: str, _rows: list[dict[str, object]]) -> None:
            return None

    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    store._account_memory_backend = SilentReadbackLossBackend()
    legacy_path = tmp_path / "Version_Notifications.json"
    store.account_memory_vault.write_json(
        legacy_path,
        {"versions": {"1.0.0": {"sent_identities": ["telegram:user:111"]}}},
    )

    state = store.read_instance_json_state("Version_Notifications.json", "version_notifications", {"versions": {}})

    assert state["versions"] == {
        "1.0.0": {"sent_identities": ["telegram:user:111"]},
        "2.0.0": {"sent_identities": ["telegram:user:222"]},
    }
    assert legacy_path.exists()


def test_account_store_sqlite_backend_merges_multiple_json_document_rows(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "memory.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    backend = store.account_memory_backend
    assert backend is not None
    backend.write_collection(
        account_id,
        "llm_state",
        [
            {
                "previous_response_ids": ["resp-a"],
                "profile": {"tone": "ruhig"},
                "updated_at": "2026-06-14T11:58:00+00:00",
            },
            {
                "previous_response_ids": ["resp-b"],
                "profile": {"provider": "gemini"},
                "updated_at": "2026-06-14T11:59:00+00:00",
            },
        ],
    )

    state = store.read_llm_state(account_id)

    assert state["previous_response_ids"] == ["resp-b", "resp-a"]
    assert state["profile"] == {"tone": "ruhig", "provider": "gemini"}
    assert state["updated_at"] == "2026-06-14T11:59:00+00:00"
    compacted = backend.read_collection(account_id, "llm_state")
    assert compacted == [state]


def test_read_llm_state_refuses_corrupt_sqlite_state_without_legacy(tmp_path, monkeypatch):
    import sqlite3

    sqlite_path = tmp_path / "memory.sqlite3"
    fallback_path = tmp_path / "memory.backup.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH", str(fallback_path))
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_llm_state(account_id, {"previous_response_id": "resp-sql", "updated_at": "2026-06-14T11:59:00+00:00"})
    for path in (sqlite_path, fallback_path):
        with sqlite3.connect(path) as connection:
            connection.execute(
                """
                UPDATE account_jsonl_collections
                SET payload_ciphertext = ?
                WHERE account_id = ? AND collection = ?
                """,
                (b"broken", account_id, "llm_state"),
            )

    with pytest.raises(AccountStoreError, match="llm_state"):
        store.read_llm_state(account_id)


def test_read_agent_state_refuses_corrupt_sqlite_state_without_legacy(tmp_path, monkeypatch):
    import sqlite3

    sqlite_path = tmp_path / "memory.sqlite3"
    fallback_path = tmp_path / "memory.backup.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH", str(fallback_path))
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_agent_state(account_id, {"proactive": {"enabled": True}, "updated_at": "2026-06-14T11:59:00+00:00"})
    for path in (sqlite_path, fallback_path):
        with sqlite3.connect(path) as connection:
            connection.execute(
                """
                UPDATE account_jsonl_collections
                SET payload_ciphertext = ?
                WHERE account_id = ? AND collection = ?
                """,
                (b"broken", account_id, "agent_state"),
            )

    with pytest.raises(AccountStoreError, match="agent_state"):
        store.read_agent_state(account_id)


def test_read_agent_state_uses_legacy_file_when_sql_state_is_corrupt(tmp_path, monkeypatch):
    import sqlite3

    sqlite_path = tmp_path / "memory.sqlite3"
    fallback_path = tmp_path / "memory.backup.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH", str(fallback_path))
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_agent_state(account_id, {"proactive": {"enabled": False}, "updated_at": "2026-06-14T11:59:00+00:00"})
    legacy_path = store.account_dir(account_id) / "Agent_State.json"
    store.account_memory_vault.write_json(legacy_path, {"proactive": {"enabled": True}})
    for path in (sqlite_path, fallback_path):
        with sqlite3.connect(path) as connection:
            connection.execute(
                """
                UPDATE account_jsonl_collections
                SET payload_ciphertext = ?
                WHERE account_id = ? AND collection = ?
                """,
                (b"broken", account_id, "agent_state"),
            )

    state = store.read_agent_state(account_id)

    assert state["proactive"]["enabled"] is True
    assert legacy_path.exists()


def test_account_store_sqlite_backend_keeps_valid_timestamp_over_invalid_legacy_json_document(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "memory.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_llm_state(account_id, {"previous_response_id": "resp-sql", "updated_at": "2026-06-14T11:59:00+00:00"})
    legacy_path = store.account_dir(account_id) / LLM_STATE_FILENAME
    store.account_memory_vault.write_json(legacy_path, {"previous_response_id": "resp-legacy", "updated_at": "zzzz"})

    state = store.read_llm_state(account_id)

    assert state["previous_response_id"] == "resp-sql"
    assert state["updated_at"] == "2026-06-14T11:59:00+00:00"
    assert not legacy_path.exists()


def test_account_store_sqlite_backend_uses_valid_created_at_when_updated_at_is_invalid_json_document(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "memory.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_llm_state(account_id, {"previous_response_id": "resp-sql", "updated_at": "2026-06-14T11:59:00+00:00"})
    legacy_path = store.account_dir(account_id) / LLM_STATE_FILENAME
    store.account_memory_vault.write_json(
        legacy_path,
        {
            "previous_response_id": "resp-legacy",
            "created_at": "2026-06-14T12:00:00+00:00",
            "updated_at": "broken",
        },
    )

    state = store.read_llm_state(account_id)

    assert state["previous_response_id"] == "resp-legacy"
    assert state["created_at"] == "2026-06-14T12:00:00+00:00"
    assert state["updated_at"] == "broken"
    assert not legacy_path.exists()


def test_instance_json_state_keeps_legacy_file_when_compaction_write_fails(tmp_path):
    class FailingCollectionBackend:
        def read_collection(self, _account_id: str, _collection: str) -> list[dict[str, object]]:
            return []

        def write_collection(self, _account_id: str, _collection: str, _rows: list[dict[str, object]]) -> None:
            raise AccountStoreError("collection write failed")

    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    store._account_memory_backend = FailingCollectionBackend()
    legacy_path = tmp_path / "Version_Notifications.json"
    store.account_memory_vault.write_json(
        legacy_path,
        {"versions": {"1.0.3": {"sent_identities": ["telegram:user:111"]}}},
    )

    with pytest.raises(AccountStoreError, match="collection write failed"):
        store.read_instance_json_state("Version_Notifications.json", "version_notifications", {"versions": {}})

    assert legacy_path.exists()
    assert store.account_memory_vault.read_json(legacy_path, {})["versions"]["1.0.3"]["sent_identities"] == [
        "telegram:user:111"
    ]


def test_account_json_state_keeps_legacy_file_when_compaction_write_fails(tmp_path):
    class FailingCollectionBackend:
        def read_collection(self, _account_id: str, _collection: str) -> list[dict[str, object]]:
            return []

        def write_collection(self, _account_id: str, _collection: str, _rows: list[dict[str, object]]) -> None:
            raise AccountStoreError("collection write failed")

    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store._account_memory_backend = FailingCollectionBackend()
    legacy_path = store.account_dir(account_id) / LLM_STATE_FILENAME
    store.account_memory_vault.write_json(
        legacy_path,
        {"previous_response_id": "resp-legacy", "updated_at": "2026-06-14T11:59:00+00:00"},
    )

    with pytest.raises(AccountStoreError, match="collection write failed"):
        store.read_llm_state(account_id)

    assert legacy_path.exists()
    assert store.account_memory_vault.read_json(legacy_path, {})["previous_response_id"] == "resp-legacy"


def test_instance_json_state_reads_legacy_file_when_collection_read_fails(tmp_path):
    class FailingReadCollectionBackend:
        def read_collection(self, _account_id: str, _collection: str) -> list[dict[str, object]]:
            raise AccountStoreError("collection read failed")

        def write_collection(self, _account_id: str, _collection: str, _rows: list[dict[str, object]]) -> None:
            raise AssertionError("read fallback must not write collection")

    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    store._account_memory_backend = FailingReadCollectionBackend()
    legacy_path = tmp_path / "Version_Notifications.json"
    store.account_memory_vault.write_json(
        legacy_path,
        {"versions": {"1.0.3": {"sent_identities": ["telegram:user:111"]}}},
    )

    state = store.read_instance_json_state("Version_Notifications.json", "version_notifications", {"versions": {}})

    assert state["versions"]["1.0.3"]["sent_identities"] == ["telegram:user:111"]
    assert legacy_path.exists()


def test_instance_json_state_reads_legacy_file_when_sql_diagnostics_fail(tmp_path):
    class CorruptReadCollectionBackend:
        last_collection_read_error = "payload could not be decrypted"
        last_collection_skipped = 1

        def read_collection(self, _account_id: str, _collection: str) -> list[dict[str, object]]:
            return []

        def write_collection(self, _account_id: str, _collection: str, _rows: list[dict[str, object]]) -> None:
            raise AssertionError("diagnostic fallback must not rewrite collection")

    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    store._account_memory_backend = CorruptReadCollectionBackend()
    legacy_path = tmp_path / "Version_Notifications.json"
    store.account_memory_vault.write_json(
        legacy_path,
        {"versions": {"1.0.3": {"sent_identities": ["telegram:user:111"]}}},
    )

    state = store.read_instance_json_state("Version_Notifications.json", "version_notifications", {"versions": {}})

    assert state["versions"]["1.0.3"]["sent_identities"] == ["telegram:user:111"]
    assert legacy_path.exists()


def test_instance_json_state_refuses_sql_diagnostics_without_legacy_file(tmp_path):
    class CorruptReadCollectionBackend:
        last_collection_read_error = "payload could not be decrypted"
        last_collection_skipped = 1

        def read_collection(self, _account_id: str, _collection: str) -> list[dict[str, object]]:
            return []

        def write_collection(self, _account_id: str, _collection: str, _rows: list[dict[str, object]]) -> None:
            raise AssertionError("diagnostic failure must not write collection")

    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    store._account_memory_backend = CorruptReadCollectionBackend()

    with pytest.raises(AccountStoreError, match="version_notifications"):
        store.read_instance_json_state("Version_Notifications.json", "version_notifications", {"versions": {}})


def test_account_json_state_reads_legacy_file_when_collection_read_fails(tmp_path):
    class FailingReadCollectionBackend:
        def read_collection(self, _account_id: str, _collection: str) -> list[dict[str, object]]:
            raise AccountStoreError("collection read failed")

        def write_collection(self, _account_id: str, _collection: str, _rows: list[dict[str, object]]) -> None:
            raise AssertionError("read fallback must not write collection")

    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store._account_memory_backend = FailingReadCollectionBackend()
    legacy_path = store.account_dir(account_id) / LLM_STATE_FILENAME
    store.account_memory_vault.write_json(
        legacy_path,
        {"previous_response_id": "resp-legacy", "updated_at": "2026-06-14T11:59:00+00:00"},
    )

    state = store.read_llm_state(account_id)

    assert state["previous_response_id"] == "resp-legacy"
    assert legacy_path.exists()


def test_agent_json_state_reads_legacy_file_when_collection_read_fails(tmp_path):
    class FailingReadCollectionBackend:
        def read_collection(self, _account_id: str, _collection: str) -> list[dict[str, object]]:
            raise AccountStoreError("collection read failed")

        def write_collection(self, _account_id: str, _collection: str, _rows: list[dict[str, object]]) -> None:
            raise AssertionError("read fallback must not write collection")

    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store._account_memory_backend = FailingReadCollectionBackend()
    legacy_path = store.account_dir(account_id) / "Agent_State.json"
    store.account_memory_vault.write_json(legacy_path, {"proactive": {"enabled": True}})

    state = store.read_agent_state(account_id)

    assert state["proactive"]["enabled"] is True
    assert legacy_path.exists()


def test_account_jsonl_collection_reads_legacy_file_when_collection_read_fails(tmp_path):
    class FailingReadCollectionBackend:
        def read_collection(self, _account_id: str, _collection: str) -> list[dict[str, object]]:
            raise AccountStoreError("collection read failed")

        def write_collection(self, _account_id: str, _collection: str, _rows: list[dict[str, object]]) -> None:
            raise AssertionError("read fallback must not write collection")

    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store._account_memory_backend = FailingReadCollectionBackend()
    legacy_path = store.account_dir(account_id) / "Proactive_Outbox.jsonl"
    store.account_memory_vault.write_jsonl(
        legacy_path,
        [{"id": "pro_legacy", "message_text": "Fallback lesen", "status": "queued"}],
    )

    rows = store.read_proactive_outbox(account_id)

    assert rows == [{"id": "pro_legacy", "message_text": "Fallback lesen", "status": "queued"}]
    assert legacy_path.exists()


def test_account_jsonl_collection_reads_legacy_file_when_sql_diagnostics_fail(tmp_path):
    class CorruptReadCollectionBackend:
        last_collection_read_error = "payload could not be decrypted"
        last_collection_skipped = 1

        def read_collection(self, _account_id: str, _collection: str) -> list[dict[str, object]]:
            return []

        def write_collection(self, _account_id: str, _collection: str, _rows: list[dict[str, object]]) -> None:
            raise AssertionError("diagnostic fallback must not rewrite collection")

    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store._account_memory_backend = CorruptReadCollectionBackend()
    legacy_path = store.account_dir(account_id) / "Proactive_Outbox.jsonl"
    store.account_memory_vault.write_jsonl(
        legacy_path,
        [{"id": "pro_legacy", "message_text": "Fallback lesen", "status": "queued"}],
    )

    rows = store.read_proactive_outbox(account_id)

    assert rows == [{"id": "pro_legacy", "message_text": "Fallback lesen", "status": "queued"}]
    assert legacy_path.exists()


def test_account_jsonl_collection_refuses_sql_diagnostics_without_legacy_file(tmp_path):
    class CorruptReadCollectionBackend:
        last_collection_read_error = ""
        last_collection_skipped = 1

        def read_collection(self, _account_id: str, _collection: str) -> list[dict[str, object]]:
            return []

        def write_collection(self, _account_id: str, _collection: str, _rows: list[dict[str, object]]) -> None:
            raise AssertionError("diagnostic failure must not write collection")

    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store._account_memory_backend = CorruptReadCollectionBackend()

    with pytest.raises(AccountStoreError, match="proactive_outbox"):
        store.read_proactive_outbox(account_id)


def test_sqlite_account_memory_refuses_destructive_write_with_wrong_secret(tmp_path):
    sqlite_path = tmp_path / "memory.sqlite3"
    account_id = "a" * 128
    first = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=StaticSecretProvider(b"a" * 32),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=sqlite_path, fallback_path=None),
    )
    first.write_entries(account_id, [{"id": "mem_keep", "user_text": "nicht loeschen"}])
    first.write_index(account_id, {"index": {"entries": {"mem_keep": {"kind": "observation"}}}})
    second = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=StaticSecretProvider(b"b" * 32),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=sqlite_path, fallback_path=None),
    )

    with pytest.raises(AccountStoreError, match="refusing destructive write"):
        second.write_entries(account_id, [{"id": "mem_new", "user_text": "falscher schluessel"}])
    with pytest.raises(AccountStoreError, match="refusing destructive write"):
        second.write_index(account_id, {"index": {"entries": {"mem_new": {}}}})

    assert first.read_entries(account_id) == [{"id": "mem_keep", "user_text": "nicht loeschen"}]
    assert first.read_index(account_id)["index"]["entries"] == {"mem_keep": {"kind": "observation"}}


def test_account_store_sqlite_backend_falls_back_to_secondary_with_warning(tmp_path, monkeypatch, caplog):
    provider_instance = provider()
    fallback_path = tmp_path / "fallback.sqlite3"
    fallback_backend = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider_instance,
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=fallback_path, fallback_path=None),
    )
    account_id = "a" * 128
    fallback_backend.write_entries(account_id, [{"id": "mem_backup", "user_text": "Backup"}])
    fallback_backend.write_index(account_id, {"index": {"entries": {"mem_backup": {}}}})
    broken_primary_path = tmp_path / "missing-primary.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(broken_primary_path))
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH", str(fallback_path))
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider_instance)

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        entries = store.read_memory_entries(account_id)

    assert entries == [{"id": "mem_backup", "user_text": "Backup"}]
    assert "ACCOUNT MEMORY PRIMARY DATABASE FAILED" in caplog.text


def test_sqlite_memory_recreates_schema_after_database_file_is_deleted(tmp_path):
    sqlite_path = tmp_path / "memory.sqlite3"
    backend = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=sqlite_path, fallback_path=None),
    )
    account_id = "a" * 128

    backend.write_entries(account_id, [{"id": "before"}])
    sqlite_path.unlink()
    for sidecar in (sqlite_path.with_name(f"{sqlite_path.name}-wal"), sqlite_path.with_name(f"{sqlite_path.name}-shm")):
        sidecar.unlink(missing_ok=True)

    backend.write_entries(account_id, [{"id": "after"}])

    assert backend.read_entries(account_id) == [{"id": "after"}]


def test_sqlite_memory_recreates_schema_after_table_is_removed(tmp_path):
    import sqlite3

    sqlite_path = tmp_path / "memory.sqlite3"
    backend = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=sqlite_path, fallback_path=None),
    )
    account_id = "a" * 128
    backend.write_entries(account_id, [{"id": "before"}])

    with sqlite3.connect(sqlite_path) as connection:
        connection.execute("DROP TABLE memory_entries")

    backend.write_entries(account_id, [{"id": "after"}])

    assert backend.read_entries(account_id) == [{"id": "after"}]


def test_sqlite_memory_serializes_concurrent_schema_initialization(tmp_path):
    backend = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=tmp_path / "memory.sqlite3", fallback_path=None),
    )
    first_started = threading.Event()
    second_started = threading.Event()
    release = threading.Event()
    state_lock = threading.Lock()
    active = 0
    max_active = 0

    class BlockingConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def executescript(self, _script):
            nonlocal active, max_active
            with state_lock:
                active += 1
                max_active = max(max_active, active)
                if active == 1:
                    first_started.set()
                elif active == 2:
                    second_started.set()
            assert release.wait(2)
            with state_lock:
                active -= 1

    backend._connect = lambda: BlockingConnection()
    errors = []

    def ensure_schema():
        try:
            backend._ensure_schema()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=ensure_schema) for _ in range(2)]
    for thread in threads:
        thread.start()
    assert first_started.wait(2)
    assert not second_started.wait(0.25)
    release.set()
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()

    assert errors == []
    assert max_active == 1


def test_sqlite_empty_entry_id_read_clears_previous_diagnostics(tmp_path):
    backend = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=tmp_path / "memory.sqlite3", fallback_path=None),
    )
    backend.last_entry_read_error = "stale error"
    backend.last_entry_skipped = 2
    backend.last_database_missing = True

    assert backend.read_entries_by_ids("a" * 128, []) == []
    assert backend.last_entry_read_error == ""
    assert backend.last_entry_skipped == 0
    assert backend.last_database_missing is False


def test_account_memory_fallback_empty_entry_id_read_clears_previous_diagnostics() -> None:
    backend = WarningFallbackAccountMemoryBackend(object(), object(), label="Demo:sqlite")
    backend.last_entry_read_error = "stale error"
    backend.last_entry_skipped = 2

    assert backend.read_entries_by_ids("a" * 128, []) == []
    assert backend.last_entry_read_error == ""
    assert backend.last_entry_skipped == 0


def test_account_memory_fallback_preserves_missing_database_diagnostic(tmp_path):
    primary_path = tmp_path / "primary.sqlite3"
    fallback_path = tmp_path / "fallback.sqlite3"
    primary = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=primary_path, fallback_path=fallback_path),
    )
    fallback = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=fallback_path, fallback_path=None),
    )
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    assert backend.read_collection("a" * 128, "proactive_outbox") == []
    assert backend.last_database_missing is True
    assert backend.last_fallback_sync_error == "read_collection:proactive_outbox: primary and fallback databases are not initialized"


def test_account_memory_fallback_refreshes_collection_name_diagnostics() -> None:
    class Backend:
        def __init__(self, names: tuple[str, ...], *, missing: bool) -> None:
            self.names = names
            self.last_database_missing = missing

        def read_collection_names(self, _account_id: str) -> tuple[str, ...]:
            if self.last_database_missing:
                raise AccountStoreError("database missing")
            return self.names

    primary = Backend((), missing=True)
    fallback = Backend(("proactive_outbox",), missing=False)
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")
    backend.last_database_missing = True

    assert backend.read_collection_names("a" * 128) == ("proactive_outbox",)
    assert backend.last_database_missing is False

    primary.last_database_missing = False
    primary.names = ("llm_state",)
    backend.last_database_missing = True

    assert backend.read_collection_names("a" * 128) == ("llm_state",)
    assert backend.last_database_missing is False


def test_sqlite_entry_id_read_chunks_large_requests(tmp_path):
    backend = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=tmp_path / "memory.sqlite3", fallback_path=None),
    )
    account_id = "a" * 128
    rows = [{"id": f"mem-{index:04d}", "user_text": str(index)} for index in range(1100)]
    backend.write_entries(account_id, rows)
    requested_ids = [f"mem-{index:04d}" for index in reversed(range(1100))]

    selected = backend.read_entries_by_ids(account_id, requested_ids)

    assert [row["id"] for row in selected] == requested_ids


def test_sqlite_entry_id_read_recovers_legacy_whitespace_ids(tmp_path):
    import sqlite3

    backend = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=tmp_path / "memory.sqlite3", fallback_path=None),
    )
    account_id = "a" * 128
    backend.write_entries(account_id, [{"id": "mem_legacy", "user_text": "Mond"}])
    legacy_row = {"id": " mem_legacy ", "user_text": "Mond"}
    nonce, ciphertext = backend._encrypt_json(account_id, " mem_legacy ", legacy_row)
    with sqlite3.connect(tmp_path / "memory.sqlite3") as connection:
        connection.execute(
            """
            UPDATE memory_entries
            SET memory_id = ?, payload_nonce = ?, payload_ciphertext = ?
            WHERE instance_name = ? AND account_id = ? AND memory_id = ?
            """,
            (" mem_legacy ", nonce, ciphertext, "Depressionsbot", account_id, "mem_legacy"),
        )

    selected = backend.read_entries_by_ids(account_id, ["mem_legacy"])

    assert selected == [legacy_row]


def test_sqlite_memory_config_resolves_relative_paths_under_instance_root(tmp_path):
    root = tmp_path / "instance" / "data" / "accounts"
    config = SQLiteMemoryConfig.from_env(
        root,
        env={
            "TEEBOTUS_ACCOUNT_MEMORY_BACKEND": "sqlite",
            "TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH": "primary.sqlite3",
            "TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH": "backups/secondary.sqlite3",
        },
    )

    assert config is not None
    assert config.path == root / "primary.sqlite3"
    assert config.fallback_path == root / "backups" / "secondary.sqlite3"


def test_sqlite_memory_config_rejects_identical_primary_and_fallback(tmp_path):
    with pytest.raises(AccountStoreError, match="must point to different files"):
        SQLiteMemoryConfig.from_env(
            tmp_path,
            env={
                "TEEBOTUS_ACCOUNT_MEMORY_BACKEND": "sqlite",
                "TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH": "same.sqlite3",
                "TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH": "same.sqlite3",
            },
        )


def test_sqlite_memory_config_rejects_hardlinked_primary_and_fallback(tmp_path):
    primary_path = tmp_path / "primary.sqlite3"
    fallback_path = tmp_path / "backup.sqlite3"
    primary_path.write_bytes(b"sqlite-placeholder")
    fallback_path.hardlink_to(primary_path)

    with pytest.raises(AccountStoreError, match="must not be hardlinks"):
        SQLiteMemoryConfig.from_env(
            tmp_path,
            env={
                "TEEBOTUS_ACCOUNT_MEMORY_BACKEND": "sqlite",
                "TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH": str(primary_path),
                "TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH": str(fallback_path),
            },
        )


def test_sqlite_backend_rejects_direct_hardlinked_config(tmp_path):
    primary_path = tmp_path / "primary.sqlite3"
    fallback_path = tmp_path / "backup.sqlite3"
    primary_path.write_bytes(b"sqlite-placeholder")
    fallback_path.hardlink_to(primary_path)
    config = SQLiteMemoryConfig(path=primary_path, fallback_path=fallback_path)

    with pytest.raises(AccountStoreError, match="must not be hardlinks"):
        SQLiteAccountMemoryBackend(
            instance_name="Depressionsbot",
            provider=provider(),
            purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
            config=config,
        )


def test_account_memory_fallback_warning_rate_limit_is_scoped_per_account(caplog) -> None:
    backend = WarningFallbackAccountMemoryBackend(object(), object(), label="Demo:sqlite")
    account_a = "a" * 128
    account_b = "b" * 128

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        backend._warn("read_entries", account_a, RuntimeError("primary A unavailable"))
        backend._warn("read_entries", account_a, RuntimeError("primary A still unavailable"))
        backend._clear_recovered_if_clean("read_entries", account_a)
        backend._warn("read_entries", account_a, RuntimeError("primary A failed again"))
        backend._warn("read_entries", account_b, RuntimeError("primary B unavailable"))

    warnings = [
        record.getMessage()
        for record in caplog.records
        if "ACCOUNT MEMORY PRIMARY DATABASE FAILED" in record.getMessage()
    ]
    assert len(warnings) == 3


def test_account_memory_fallback_marks_both_read_failures_as_unsafe(caplog) -> None:
    class Backend:
        def __init__(self, *, fail_read: bool = False) -> None:
            self.fail_read = fail_read

        def read_entries(self, _account_id: str) -> list[dict[str, str]]:
            if self.fail_read:
                raise OSError("database unavailable")
            return []

        def write_entries(self, _account_id: str, _rows: list[dict[str, str]]) -> None:
            return None

    account_id = "a" * 128
    backend = WarningFallbackAccountMemoryBackend(Backend(fail_read=True), Backend(fail_read=True), label="Demo:sqlite")

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        with pytest.raises(AccountStoreError, match="fallback read failed"):
            backend.read_entries(account_id)

    assert account_id in backend._stale_fallback_entries
    assert account_id in backend._fallback_sync_failed_entries
    assert backend.last_fallback_sync_error == "read_entries: fallback read failed: database unavailable"
    assert "FAILOVER IS BLOCKED" in caplog.text


def test_account_memory_fallback_keeps_sync_errors_separate_per_account() -> None:
    class Backend:
        def __init__(self) -> None:
            self.errors: dict[str, str] = {}
            self.entries: dict[str, list[dict[str, str]]] = {}

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            error = self.errors.get(account_id)
            if error:
                raise OSError(error)
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            self.entries[account_id] = [dict(row) for row in rows]

    account_a = "a" * 128
    account_b = "b" * 128
    primary = Backend()
    fallback = Backend()
    primary.errors.update({account_a: "primary A", account_b: "primary B"})
    fallback.errors.update({account_a: "fallback A", account_b: "fallback B"})
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    with pytest.raises(AccountStoreError, match="fallback A"):
        backend.read_entries(account_a)
    with pytest.raises(AccountStoreError, match="fallback B"):
        backend.read_entries(account_b)

    assert "fallback A" in backend.fallback_sync_error_for_account(account_a)
    assert "fallback B" in backend.fallback_sync_error_for_account(account_b)
    assert "fallback B" in backend.last_fallback_sync_error

    primary.errors.pop(account_a)
    fallback.errors.pop(account_a)
    backend.read_entries(account_a)

    assert backend.fallback_sync_error_for_account(account_a) == ""
    assert "fallback B" in backend.fallback_sync_error_for_account(account_b)


def test_account_memory_fallback_keeps_read_and_write_errors_separate() -> None:
    account_id = "a" * 128
    backend = WarningFallbackAccountMemoryBackend(object(), object(), label="Demo:sqlite")

    backend._set_fallback_sync_error("read_entries", account_id, "read failed")
    backend._set_fallback_sync_error("write_entries", account_id, "write failed")
    backend._clear_fallback_sync_error("read_entries", account_id)

    assert backend.fallback_sync_error_for_account(account_id) == "write failed"
    assert backend.last_fallback_sync_error == "write failed"


def test_account_memory_fallback_preserves_diagnostic_secondary_read_failure(caplog) -> None:
    class PrimaryBackend:
        last_entry_read_error = "corrupt primary row"
        last_entry_skipped = 1

        def read_entries(self, _account_id: str) -> list[dict[str, str]]:
            return [{"id": "partial"}]

    class FailingFallbackBackend:
        def read_entries(self, _account_id: str) -> list[dict[str, str]]:
            raise OSError("secondary unavailable")

    account_id = "a" * 128
    backend = WarningFallbackAccountMemoryBackend(PrimaryBackend(), FailingFallbackBackend(), label="Demo:sqlite")

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        with pytest.raises(AccountStoreError, match="fallback read failed"):
            backend.read_entries(account_id)

    assert account_id in backend._stale_fallback_entries
    assert account_id in backend._fallback_sync_failed_entries
    assert backend.last_fallback_sync_error == "read_entries: fallback read failed: secondary unavailable"


def test_account_memory_fallback_marks_both_collection_name_reads_as_unsafe(caplog) -> None:
    class Backend:
        def __init__(self, *, fail_read: bool = False) -> None:
            self.fail_read = fail_read

        def read_collection_names(self, _account_id: str) -> tuple[str, ...]:
            if self.fail_read:
                raise OSError("secondary unavailable")
            return ()

    account_id = "a" * 128
    primary = Backend(fail_read=True)
    fallback = Backend(fail_read=True)
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        with pytest.raises(AccountStoreError, match="fallback read failed"):
            backend.read_collection_names(account_id)

    assert account_id in backend._failed_collection_name_reads
    assert backend.last_fallback_sync_error == "read_collection_names: fallback read failed: secondary unavailable"
    assert "FAILOVER IS BLOCKED" in caplog.text

    primary.fail_read = False
    fallback.fail_read = False
    assert backend.read_collection_names(account_id) == ()
    assert account_id not in backend._failed_collection_name_reads
    assert backend.last_fallback_sync_error == ""


def test_account_memory_fallback_blocks_collection_names_when_secondary_is_missing() -> None:
    class Backend:
        def __init__(self, *, database_missing: bool) -> None:
            self.last_database_missing = database_missing

        def read_collection_names(self, _account_id: str) -> tuple[str, ...]:
            raise OSError("collection schema unavailable")

    account_id = "a" * 128
    primary = Backend(database_missing=False)
    fallback = Backend(database_missing=True)
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    with pytest.raises(AccountStoreError, match="fallback database is missing"):
        backend.read_collection_names(account_id)

    assert backend.last_fallback_sync_error == (
        "read_collection_names: fallback database is missing; no secondary data available"
    )
    assert account_id not in backend._failed_collection_name_reads


def test_account_memory_fallback_does_not_treat_empty_secondary_collection_names_as_recovered() -> None:
    class Backend:
        def __init__(self, *, fail_read: bool = False) -> None:
            self.fail_read = fail_read

        def read_collection_names(self, _account_id: str) -> tuple[str, ...]:
            if self.fail_read:
                raise OSError("primary unavailable")
            return ()

    account_id = "a" * 128
    backend = WarningFallbackAccountMemoryBackend(
        Backend(fail_read=True),
        Backend(),
        label="Demo:sqlite",
    )

    with pytest.raises(AccountStoreError, match="fallback has no recoverable data"):
        backend.read_collection_names(account_id)

    assert account_id in backend._failed_collection_name_reads


def test_account_memory_fallback_repairs_fallback_only_collection_after_name_read_recovery() -> None:
    class Backend:
        def __init__(self, *, fail_names: bool = False) -> None:
            self.fail_names = fail_names
            self.collections: dict[tuple[str, str], list[dict[str, str]]] = {}

        def read_collection(self, account_id: str, collection: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.collections.get((account_id, collection), [])]

        def write_collection(self, account_id: str, collection: str, rows: list[dict[str, str]]) -> None:
            self.collections[(account_id, collection)] = [dict(row) for row in rows]

        def read_collection_names(self, account_id: str) -> tuple[str, ...]:
            if self.fail_names:
                raise OSError("collection names unavailable")
            return tuple(sorted(collection for (item_account, collection) in self.collections if item_account == account_id))

    account_id = "a" * 128
    collection = "proactive_outbox"
    primary = Backend(fail_names=True)
    fallback = Backend(fail_names=True)
    fallback.collections[(account_id, collection)] = [{"id": "pro_fallback"}]
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    with pytest.raises(AccountStoreError, match="fallback read failed"):
        backend.read_collection_names(account_id)

    primary.fail_names = False
    fallback.fail_names = False

    assert backend.read_collection_names(account_id) == (collection,)
    assert primary.collections[(account_id, collection)] == [{"id": "pro_fallback"}]
    assert account_id not in backend._failed_collection_name_reads


def test_account_memory_fallback_keeps_name_failure_pending_until_final_read_succeeds() -> None:
    class Backend:
        def __init__(self, *, fail_names: bool = False, fail_on_call: int = 0) -> None:
            self.fail_names = fail_names
            self.fail_on_call = fail_on_call
            self.name_calls = 0

        def read_collection_names(self, _account_id: str) -> tuple[str, ...]:
            self.name_calls += 1
            if self.fail_names or self.name_calls == self.fail_on_call:
                raise OSError("collection names unavailable")
            return ()

    account_id = "a" * 128
    primary = Backend(fail_names=True)
    fallback = Backend(fail_names=True)
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    with pytest.raises(AccountStoreError, match="fallback read failed"):
        backend.read_collection_names(account_id)

    primary.fail_names = False
    primary.fail_on_call = 3
    fallback.fail_names = False
    with pytest.raises(AccountStoreError, match="read blocked"):
        backend.read_collection_names(account_id)
    assert account_id in backend._failed_collection_name_reads

    primary.fail_on_call = 0
    assert backend.read_collection_names(account_id) == ()
    assert account_id not in backend._failed_collection_name_reads


def test_account_memory_fallback_marks_both_write_failures_as_unsafe(caplog) -> None:
    class Backend:
        def __init__(self, *, fail_write: bool = False) -> None:
            self.fail_write = fail_write

        def write_entries(self, _account_id: str, _rows: list[dict[str, str]]) -> None:
            if self.fail_write:
                raise OSError("database unavailable")

    account_id = "a" * 128
    backend = WarningFallbackAccountMemoryBackend(Backend(fail_write=True), Backend(fail_write=True), label="Demo:sqlite")

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        with pytest.raises(AccountStoreError, match="fallback write failed"):
            backend.write_entries(account_id, [{"id": "mem"}])

    assert account_id in backend._stale_fallback_entries
    assert account_id in backend._fallback_sync_failed_entries
    assert backend.last_fallback_sync_error == "write_entries: fallback write failed: database unavailable"
    assert "FAILOVER IS BLOCKED" in caplog.text


def test_account_memory_fallback_syncs_dirty_entries_back_to_primary(caplog):
    class Backend:
        def __init__(self, *, fail_write: bool = False) -> None:
            self.fail_write = fail_write
            self.entries: dict[str, list[dict[str, str]]] = {}

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            if self.fail_write:
                raise OSError("primary unavailable")
            self.entries[account_id] = [dict(row) for row in rows]

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

    primary = Backend(fail_write=True)
    fallback = Backend()
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")
    account_id = "a" * 128

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        backend.write_entries(account_id, [{"id": "mem_fallback"}])
        primary.fail_write = False
        entries = backend.read_entries(account_id)

    assert entries == [{"id": "mem_fallback"}]
    assert primary.entries[account_id] == [{"id": "mem_fallback"}]
    assert "ACCOUNT MEMORY PRIMARY DATABASE FAILED" in caplog.text
    assert "primary backend recovered" in caplog.text


def test_account_memory_fallback_syncs_dirty_index_back_to_primary(caplog):
    class Backend:
        def __init__(self, *, fail_write: bool = False) -> None:
            self.fail_write = fail_write
            self.indexes: dict[str, dict[str, object]] = {}

        def read_entries(self, _account_id: str) -> list[dict[str, str]]:
            return []

        def write_entries(self, _account_id: str, _rows: list[dict[str, str]]) -> None:
            return None

        def read_index(self, account_id: str) -> dict[str, object]:
            return dict(self.indexes.get(account_id, {}))

        def write_index(self, account_id: str, data: dict[str, object]) -> None:
            if self.fail_write:
                raise OSError("primary unavailable")
            self.indexes[account_id] = dict(data)

    primary = Backend(fail_write=True)
    fallback = Backend()
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")
    account_id = "a" * 128

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        backend.write_index(account_id, {"index": {"entries": {"mem_fallback": {}}}})
        primary.fail_write = False
        index = backend.read_index(account_id)

    assert index == {"index": {"entries": {"mem_fallback": {}}}}
    assert primary.indexes[account_id] == {"index": {"entries": {"mem_fallback": {}}}}
    assert "ACCOUNT MEMORY PRIMARY DATABASE FAILED" in caplog.text
    assert "primary backend recovered" in caplog.text


def test_account_memory_fallback_syncs_dirty_collection_back_to_primary(caplog):
    class Backend:
        def __init__(self, *, fail_write: bool = False) -> None:
            self.fail_write = fail_write
            self.collections: dict[tuple[str, str], list[dict[str, str]]] = {}

        def read_entries(self, _account_id: str) -> list[dict[str, str]]:
            return []

        def write_entries(self, _account_id: str, _rows: list[dict[str, str]]) -> None:
            return None

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

        def read_collection(self, account_id: str, collection: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.collections.get((account_id, collection), [])]

        def write_collection(self, account_id: str, collection: str, rows: list[dict[str, str]]) -> None:
            if self.fail_write:
                raise OSError("primary unavailable")
            self.collections[(account_id, collection)] = [dict(row) for row in rows]

        def read_collection_names(self, account_id: str) -> tuple[str, ...]:
            return tuple(sorted(collection for item_account, collection in self.collections if item_account == account_id))

    primary = Backend(fail_write=True)
    fallback = Backend()
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")
    account_id = "a" * 128

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        backend.write_collection(account_id, "proactive_outbox", [{"id": "pro_fallback"}])
        primary.fail_write = False
        rows = backend.read_collection(account_id, "proactive_outbox")

    assert rows == [{"id": "pro_fallback"}]
    assert primary.collections[(account_id, "proactive_outbox")] == [{"id": "pro_fallback"}]
    assert "ACCOUNT MEMORY PRIMARY DATABASE FAILED" in caplog.text
    assert "primary backend recovered" in caplog.text


def test_account_memory_fallback_collection_names_sync_dirty_deletion() -> None:
    class Backend:
        def __init__(self, *, fail_write: bool = False) -> None:
            self.fail_write = fail_write
            self.collections: dict[tuple[str, str], list[dict[str, str]]] = {}

        def read_collection(self, account_id: str, collection: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.collections.get((account_id, collection), [])]

        def write_collection(self, account_id: str, collection: str, rows: list[dict[str, str]]) -> None:
            if self.fail_write:
                raise OSError("primary unavailable")
            self.collections[(account_id, collection)] = [dict(row) for row in rows]

        def read_collection_names(self, account_id: str) -> tuple[str, ...]:
            return tuple(
                sorted(
                    collection
                    for (item_account_id, collection), rows in self.collections.items()
                    if item_account_id == account_id and rows
                )
            )

    account_id = "a" * 128
    collection = "version_notifications"
    primary = Backend(fail_write=True)
    fallback = Backend()
    primary.collections[(account_id, collection)] = [{"id": "old"}]
    fallback.collections[(account_id, collection)] = [{"id": "old"}]
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    backend.write_collection(account_id, collection, [])
    primary.fail_write = False

    assert backend.read_collection_names(account_id) == ()
    assert primary.collections[(account_id, collection)] == []
    assert (account_id, collection) not in backend._dirty_collections


def test_account_memory_fallback_replace_reports_success_from_fallback() -> None:
    class Backend:
        def __init__(self, *, fail_replace: bool = False) -> None:
            self.fail_replace = fail_replace
            self.collections: dict[tuple[str, str], list[dict[str, str]]] = {}

        def read_collection(self, account_id: str, collection: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.collections.get((account_id, collection), [])]

        def write_collection(self, account_id: str, collection: str, rows: list[dict[str, str]]) -> None:
            self.collections[(account_id, collection)] = [dict(row) for row in rows]

        def replace_collection_item(self, account_id: str, collection: str, item_key: str, row: dict[str, str]) -> bool:
            if self.fail_replace:
                raise OSError("primary unavailable")
            existing_rows = self.collections.get((account_id, collection), [])
            for index, existing in enumerate(existing_rows):
                if str(existing.get("id") or "").strip() == item_key:
                    existing_rows[index] = dict(row)
                    return True
            return False

    account_id = "a" * 128
    collection = "codex_history_dispatch_results"
    primary = Backend(fail_replace=True)
    fallback = Backend()
    fallback.collections[(account_id, collection)] = [{"id": "row_1", "status": "pending"}]
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    assert backend.replace_collection_item(account_id, collection, "row_1", {"id": "row_1", "status": "sent"}) is True
    assert fallback.collections[(account_id, collection)] == [{"id": "row_1", "status": "sent"}]
    assert (account_id, collection) in backend._dirty_collections


@pytest.mark.parametrize("kind", ["entries", "index", "collection"])
def test_account_memory_fallback_does_not_promote_corrupt_dirty_data(kind: str) -> None:
    class Backend:
        def __init__(self, *, fail_write: bool = False) -> None:
            self.fail_write = fail_write
            self.entries: dict[str, list[dict[str, str]]] = {}
            self.indexes: dict[str, dict[str, object]] = {}
            self.collections: dict[tuple[str, str], list[dict[str, str]]] = {}
            self.last_entry_read_error = ""
            self.last_entry_skipped = 0
            self.last_index_read_error = ""
            self.last_collection_read_error = ""
            self.last_collection_skipped = 0

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            if self.fail_write:
                raise OSError("primary unavailable")
            self.entries[account_id] = [dict(row) for row in rows]

        def read_index(self, account_id: str) -> dict[str, object]:
            return dict(self.indexes.get(account_id, {}))

        def write_index(self, account_id: str, data: dict[str, object]) -> None:
            if self.fail_write:
                raise OSError("primary unavailable")
            self.indexes[account_id] = dict(data)

        def read_collection(self, account_id: str, collection: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.collections.get((account_id, collection), [])]

        def write_collection(self, account_id: str, collection: str, rows: list[dict[str, str]]) -> None:
            if self.fail_write:
                raise OSError("primary unavailable")
            self.collections[(account_id, collection)] = [dict(row) for row in rows]

    account_id = "a" * 128
    collection = "version_notifications"
    primary = Backend(fail_write=True)
    fallback = Backend()
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    if kind == "entries":
        backend.write_entries(account_id, [{"id": "pending_entry"}])
        fallback.last_entry_read_error = "payload could not be decrypted"
        fallback.last_entry_skipped = 1
        primary.fail_write = False
        with pytest.raises(AccountStoreError, match="read blocked"):
            backend.read_entries(account_id)
        assert account_id not in primary.entries
        assert account_id in backend._unrecoverable_fallback_entries
    elif kind == "index":
        backend.write_index(account_id, {"index": {"pending": {}}})
        fallback.last_index_read_error = "index could not be decrypted"
        primary.fail_write = False
        with pytest.raises(AccountStoreError, match="read blocked"):
            backend.read_index(account_id)
        assert account_id not in primary.indexes
        assert account_id in backend._unrecoverable_fallback_indexes
    else:
        backend.write_collection(account_id, collection, [{"id": "pending_row"}])
        fallback.last_collection_read_error = "collection could not be decrypted"
        fallback.last_collection_skipped = 1
        primary.fail_write = False
        with pytest.raises(AccountStoreError, match="read blocked"):
            backend.read_collection(account_id, collection)
        assert (account_id, collection) not in primary.collections
        assert (account_id, collection) in backend._unrecoverable_fallback_collections


def test_account_memory_fallback_blocks_collection_writes_after_unrecoverable_empty_fallback(caplog):
    class Backend:
        def __init__(self, *, fail_read: bool = False) -> None:
            self.fail_read = fail_read
            self.collections: dict[tuple[str, str], list[dict[str, str]]] = {}

        def read_entries(self, _account_id: str) -> list[dict[str, str]]:
            return []

        def write_entries(self, _account_id: str, _rows: list[dict[str, str]]) -> None:
            return None

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

        def read_collection(self, account_id: str, collection: str) -> list[dict[str, str]]:
            if self.fail_read:
                raise AccountStoreError("primary collection unavailable")
            return [dict(row) for row in self.collections.get((account_id, collection), [])]

        def write_collection(self, account_id: str, collection: str, rows: list[dict[str, str]]) -> None:
            self.collections[(account_id, collection)] = [dict(row) for row in rows]

        def read_collection_names(self, account_id: str) -> tuple[str, ...]:
            return tuple(sorted(collection for item_account, collection in self.collections if item_account == account_id))

    account_id = "a" * 128
    primary = Backend(fail_read=True)
    fallback = Backend()
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        rows = backend.read_collection(account_id, "version_notifications")
        with pytest.raises(AccountStoreError, match="write blocked because primary is unreadable and fallback has no recoverable data"):
            backend.write_collection(account_id, "version_notifications", [{"id": "version_state_new"}])

    assert rows == []
    assert (account_id, "version_notifications") not in primary.collections
    assert (account_id, "version_notifications") not in fallback.collections
    assert backend.stale_fallback_collection_account_ids == (account_id,)
    assert backend.last_fallback_sync_error.startswith("write_collection:version_notifications: write blocked")
    assert "ACCOUNT MEMORY WRITE BLOCKED" in caplog.text


def test_account_memory_fallback_repairs_empty_collection_fallback_after_primary_recovers(caplog):
    class Backend:
        def __init__(self, *, fail_read: bool = False) -> None:
            self.fail_read = fail_read
            self.collections: dict[tuple[str, str], list[dict[str, str]]] = {}

        def read_entries(self, _account_id: str) -> list[dict[str, str]]:
            return []

        def write_entries(self, _account_id: str, _rows: list[dict[str, str]]) -> None:
            return None

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

        def read_collection(self, account_id: str, collection: str) -> list[dict[str, str]]:
            if self.fail_read:
                raise AccountStoreError("primary collection unavailable")
            return [dict(row) for row in self.collections.get((account_id, collection), [])]

        def write_collection(self, account_id: str, collection: str, rows: list[dict[str, str]]) -> None:
            self.collections[(account_id, collection)] = [dict(row) for row in rows]

        def read_collection_names(self, account_id: str) -> tuple[str, ...]:
            return tuple(sorted(collection for item_account, collection in self.collections if item_account == account_id))

    account_id = "a" * 128
    primary = Backend(fail_read=True)
    fallback = Backend()
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    backend.read_collection(account_id, "version_notifications")
    primary.fail_read = False
    primary.collections[(account_id, "version_notifications")] = [{"id": "version_state_primary"}]

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        rows = backend.read_collection(account_id, "version_notifications")
        assert rows == [{"id": "version_state_primary"}]
        assert fallback.collections[(account_id, "version_notifications")] == [{"id": "version_state_primary"}]
        assert backend.stale_fallback_collection_account_ids == ()
        assert backend.last_fallback_sync_error == ""
        backend.write_collection(account_id, "version_notifications", [{"id": "version_state_new"}])

    assert primary.collections[(account_id, "version_notifications")] == [{"id": "version_state_new"}]
    assert fallback.collections[(account_id, "version_notifications")] == [{"id": "version_state_new"}]
    assert backend.stale_fallback_collection_account_ids == ()
    assert backend.last_fallback_sync_error == ""
    assert "primary backend recovered" in caplog.text


def test_account_memory_fallback_repairs_empty_entry_fallback_after_primary_recovers(caplog):
    class Backend:
        def __init__(self, *, fail_read: bool = False) -> None:
            self.fail_read = fail_read
            self.entries: dict[str, list[dict[str, str]]] = {}

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            if self.fail_read:
                raise AccountStoreError("primary entries unavailable")
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            self.entries[account_id] = [dict(row) for row in rows]

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

    account_id = "a" * 128
    primary = Backend(fail_read=True)
    fallback = Backend()
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        backend.read_entries(account_id)
        primary.fail_read = False
        primary.entries[account_id] = [{"id": "entry_primary"}]
        rows = backend.read_entries(account_id)

    assert rows == [{"id": "entry_primary"}]
    assert primary.entries[account_id] == [{"id": "entry_primary"}]
    assert fallback.entries[account_id] == [{"id": "entry_primary"}]
    assert backend.stale_fallback_entry_account_ids == ()
    assert backend.last_fallback_sync_error == ""
    assert "primary backend recovered" in caplog.text


def test_account_memory_fallback_repairs_entry_fallback_from_full_read_after_unrecoverable_partial_read(caplog):
    class Backend:
        def __init__(self, *, fail_read: bool = False) -> None:
            self.fail_read = fail_read
            self.entries: dict[str, list[dict[str, str]]] = {}

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            if self.fail_read:
                raise AccountStoreError("primary entries unavailable")
            return [dict(row) for row in self.entries.get(account_id, [])]

        def read_entries_by_ids(self, account_id: str, memory_ids: list[str]) -> list[dict[str, str]]:
            requested_ids = {memory_id for memory_id in memory_ids if memory_id}
            return [dict(row) for row in self.read_entries(account_id) if row.get("id") in requested_ids]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            self.entries[account_id] = [dict(row) for row in rows]

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

    account_id = "a" * 128
    primary = Backend(fail_read=True)
    fallback = Backend()
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    assert backend.read_entries(account_id) == []
    primary.fail_read = False
    primary.entries[account_id] = [{"id": "entry_1"}, {"id": "entry_2"}]

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        rows = backend.read_entries_by_ids(account_id, ["entry_1"])

    assert rows == [{"id": "entry_1"}]
    assert fallback.entries[account_id] == [{"id": "entry_1"}, {"id": "entry_2"}]
    assert backend.stale_fallback_entry_account_ids == ()
    assert backend.last_fallback_sync_error == ""


def test_account_memory_fallback_does_not_repair_secondary_from_partial_full_read() -> None:
    class Backend:
        def __init__(self, rows: list[dict[str, str]], *, fail_write: bool = False, partial_full_read: bool = False) -> None:
            self.entries = {"a" * 128: [dict(row) for row in rows]}
            self.fail_write = fail_write
            self.partial_full_read = partial_full_read
            self.last_entry_read_error = ""
            self.last_entry_skipped = 0
            self.last_index_read_error = ""

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            if self.partial_full_read:
                self.last_entry_read_error = "payload could not be decrypted"
                self.last_entry_skipped = 1
                return [dict(self.entries[account_id][0])]
            self.last_entry_read_error = ""
            self.last_entry_skipped = 0
            return [dict(row) for row in self.entries.get(account_id, [])]

        def read_entries_by_ids(self, account_id: str, memory_ids: list[str]) -> list[dict[str, str]]:
            self.last_entry_read_error = ""
            self.last_entry_skipped = 0
            requested = set(memory_ids)
            return [dict(row) for row in self.entries.get(account_id, []) if row.get("id") in requested]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            if self.fail_write:
                raise OSError("fallback unavailable")
            self.entries[account_id] = [dict(row) for row in rows]

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

    account_id = "a" * 128
    primary = Backend([{"id": "row_1"}, {"id": "row_2"}], partial_full_read=True)
    fallback = Backend([{"id": "row_1"}, {"id": "row_2"}], fail_write=True)
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    backend.write_entries(account_id, [{"id": "row_1"}, {"id": "row_2"}, {"id": "row_3"}])
    fallback.fail_write = False

    assert backend.read_entries_by_ids(account_id, ["row_1"]) == [{"id": "row_1"}]
    assert fallback.entries[account_id] == [{"id": "row_1"}, {"id": "row_2"}]
    assert account_id in backend._fallback_sync_failed_entries


def test_account_memory_fallback_recovers_primary_from_full_entries_after_entries_by_ids_diagnostic_error() -> None:
    class Backend:
        def __init__(self, *, force_read_error: bool = False) -> None:
            self.force_read_error = force_read_error
            self.entries: dict[str, list[dict[str, str]]] = {}
            self.last_entry_read_error = ""
            self.last_entry_skipped = 0
            self.last_index_read_error = ""

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.entries.get(account_id, [])]

        def read_entries_by_ids(self, account_id: str, memory_ids: list[str]) -> list[dict[str, str]]:
            requested_ids = {memory_id for memory_id in memory_ids if memory_id}
            if self.force_read_error:
                self.last_entry_read_error = "payload could not be decrypted"
                self.last_entry_skipped = 1
            else:
                self.last_entry_read_error = ""
                self.last_entry_skipped = 0
            return [dict(row) for row in self.read_entries(account_id) if row.get("id") in requested_ids]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            self.entries[account_id] = [dict(row) for row in rows]

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

    account_id = "a" * 128
    primary = Backend(force_read_error=True)
    fallback = Backend()
    primary.entries[account_id] = [{"id": "entry_1"}, {"id": "entry_2"}]
    fallback.entries[account_id] = [{"id": "entry_1"}, {"id": "entry_2"}]
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    rows = backend.read_entries_by_ids(account_id, ["entry_1"])

    assert rows == [{"id": "entry_1"}]
    assert primary.entries[account_id] == [{"id": "entry_1"}, {"id": "entry_2"}]
    assert backend.last_fallback_sync_error == ""


def test_account_memory_fallback_does_not_mark_unrecoverable_for_empty_entries_by_ids_result(caplog):
    class Backend:
        def __init__(self, *, fail_read: bool = False) -> None:
            self.fail_read = fail_read
            self.entries: dict[str, list[dict[str, str]]] = {}

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.entries.get(account_id, [])]

        def read_entries_by_ids(self, account_id: str, memory_ids: list[str]) -> list[dict[str, str]]:
            if self.fail_read:
                raise AccountStoreError("primary entries-by-ids unavailable")
            requested_ids = {memory_id for memory_id in memory_ids if memory_id}
            return [dict(row) for row in self.read_entries(account_id) if row.get("id") in requested_ids]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            self.entries[account_id] = [dict(row) for row in rows]

    account_id = "a" * 128
    primary = Backend(fail_read=True)
    fallback = Backend()
    fallback.entries[account_id] = [{"id": "entry_2"}, {"id": "entry_3"}]
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        rows = backend.read_entries_by_ids(account_id, ["entry_1"])

    assert rows == []
    assert primary.entries[account_id] == [{"id": "entry_2"}, {"id": "entry_3"}]
    assert backend.stale_fallback_entry_account_ids == ()
    assert backend.last_fallback_sync_error == ""
    assert (account_id in backend._unrecoverable_fallback_entries) is False


def test_account_memory_fallback_empty_entries_by_ids_result_from_empty_fallback_syncs_empty_primary(caplog):
    class Backend:
        def __init__(self, *, fail_read: bool = False) -> None:
            self.fail_read = fail_read
            self.entries: dict[str, list[dict[str, str]]] = {}

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            if self.fail_read:
                raise AccountStoreError("primary entries unavailable")
            return [dict(row) for row in self.entries.get(account_id, [])]

        def read_entries_by_ids(self, account_id: str, memory_ids: list[str]) -> list[dict[str, str]]:
            if self.fail_read:
                raise AccountStoreError("primary entries-by-ids unavailable")
            requested_ids = {memory_id for memory_id in memory_ids if memory_id}
            return [dict(row) for row in self.read_entries(account_id) if row.get("id") in requested_ids]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            self.entries[account_id] = [dict(row) for row in rows]

    account_id = "a" * 128
    primary = Backend(fail_read=True)
    fallback = Backend()
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        rows = backend.read_entries_by_ids(account_id, ["entry_missing"])

    assert rows == []
    assert primary.entries[account_id] == []
    assert backend.stale_fallback_entry_account_ids == ()
    assert backend.last_fallback_sync_error == ""


def test_account_memory_fallback_blocks_empty_secondary_after_partial_entries_by_ids_read() -> None:
    class Backend:
        def __init__(self, rows: list[dict[str, str]], *, partial_ids: bool = False) -> None:
            self.entries = {"a" * 128: [dict(row) for row in rows]}
            self.partial_ids = partial_ids
            self.last_entry_read_error = ""
            self.last_entry_skipped = 0
            self.last_index_read_error = ""

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.entries.get(account_id, [])]

        def read_entries_by_ids(self, account_id: str, memory_ids: list[str]) -> list[dict[str, str]]:
            if self.partial_ids:
                self.last_entry_read_error = "payload could not be decrypted"
                self.last_entry_skipped = 1
                return []
            requested = set(memory_ids)
            return [row for row in self.read_entries(account_id) if row.get("id") in requested]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            self.entries[account_id] = [dict(row) for row in rows]

    account_id = "a" * 128
    original_rows = [{"id": "mem_good"}, {"id": "mem_bad"}]
    primary = Backend(original_rows, partial_ids=True)
    fallback = Backend([])
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    assert backend.read_entries_by_ids(account_id, ["mem_bad"]) == []

    assert primary.entries[account_id] == original_rows
    assert account_id in backend._unrecoverable_fallback_entries
    assert backend.last_fallback_sync_error == "read_entries: fallback has no recoverable data"


def test_account_memory_fallback_repair_keeps_other_pending_errors_until_cleared(caplog):
    class Backend:
        def __init__(self, *, fail_read: bool = False) -> None:
            self.fail_read = fail_read
            self.entries: dict[str, list[dict[str, str]]] = {}

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            if self.fail_read:
                raise AccountStoreError("primary entries unavailable")
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            self.entries[account_id] = [dict(row) for row in rows]

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

    account_id_a = "a" * 128
    account_id_b = "b" * 128
    primary = Backend(fail_read=True)
    fallback = Backend()
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    rows_from_unrecoverable = backend.read_entries(account_id_a)
    assert rows_from_unrecoverable == []
    assert backend.last_fallback_sync_error == "read_entries: fallback has no recoverable data"
    assert account_id_a in backend.stale_fallback_entry_account_ids
    backend._fallback_sync_failed_entries.add(account_id_b)
    backend._fallback_active = True
    primary.fail_read = False
    primary.entries[account_id_a] = [{"id": "entry_primary"}]

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        rows = backend.read_entries(account_id_a)

    assert rows == [{"id": "entry_primary"}]
    assert backend.last_fallback_sync_error == "read_entries: fallback has no recoverable data"
    assert backend.fallback.read_entries(account_id_b) == []
    assert account_id_b in backend._fallback_sync_failed_entries
    assert account_id_a not in backend._fallback_sync_failed_entries
    assert account_id_a not in backend.stale_fallback_entry_account_ids
    assert "primary backend recovered" not in caplog.text


def test_account_memory_fallback_recovers_primary_entry_diagnostics(caplog):
    class Backend:
        def __init__(self, rows: list[dict[str, str]], *, skipped: int = 0, error: str = "") -> None:
            self.entries = {"a" * 128: [dict(row) for row in rows]}
            self.last_entry_skipped = skipped
            self.last_entry_read_error = error
            self.last_index_read_error = ""

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            self.entries[account_id] = [dict(row) for row in rows]
            self.last_entry_skipped = 0
            self.last_entry_read_error = ""

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

    account_id = "a" * 128
    primary = Backend([{"id": "mem_partial"}], skipped=2, error="payload could not be decrypted")
    fallback = Backend([{"id": "mem_clean"}])
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        entries = backend.read_entries(account_id)

    assert entries == [{"id": "mem_clean"}]
    assert primary.entries[account_id] == [{"id": "mem_clean"}]
    assert backend.last_entry_read_error == ""
    assert backend.last_entry_skipped == 0
    assert "ACCOUNT MEMORY PRIMARY DATABASE FAILED" in caplog.text


def test_account_memory_fallback_blocks_partial_corrupt_fallback_read() -> None:
    class Backend:
        def __init__(
            self,
            rows: list[dict[str, str]],
            *,
            fail_read: bool = False,
            skipped: int = 0,
            error: str = "",
        ) -> None:
            self.entries = {"a" * 128: [dict(row) for row in rows]}
            self.fail_read = fail_read
            self.last_entry_skipped = skipped
            self.last_entry_read_error = error
            self.last_index_read_error = ""

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            if self.fail_read:
                raise AccountStoreError("primary entries unavailable")
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            self.entries[account_id] = [dict(row) for row in rows]

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

    account_id = "a" * 128
    primary = Backend([{"id": "primary"}], fail_read=True)
    fallback = Backend(
        [{"id": "fallback_good"}],
        skipped=1,
        error="fallback payload could not be decrypted",
    )
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    with pytest.raises(AccountStoreError, match="fallback data has read diagnostics"):
        backend.read_entries(account_id)

    assert primary.entries[account_id] == [{"id": "primary"}]
    assert account_id in backend._unrecoverable_fallback_entries
    assert backend.last_entry_read_error == "fallback payload could not be decrypted"


def test_account_memory_fallback_keeps_warning_when_primary_repair_fails(caplog):
    class Backend:
        def __init__(
            self,
            rows: list[dict[str, str]],
            *,
            skipped: int = 0,
            error: str = "",
            fail_write: bool = False,
        ) -> None:
            self.entries = {"a" * 128: [dict(row) for row in rows]}
            self.last_entry_skipped = skipped
            self.last_entry_read_error = error
            self.last_index_read_error = ""
            self.fail_write = fail_write

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            if self.fail_write:
                raise AccountStoreError(
                    "existing SQLite account memory entries are not decryptable with the current key"
                )
            self.entries[account_id] = [dict(row) for row in rows]
            self.last_entry_skipped = 0
            self.last_entry_read_error = ""

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

    account_id = "a" * 128
    primary = Backend(
        [{"id": "mem_partial"}],
        skipped=2,
        error="payload could not be decrypted",
        fail_write=True,
    )
    fallback = Backend([{"id": "mem_clean"}])
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        entries = backend.read_entries(account_id)

    assert entries == [{"id": "mem_clean"}]
    assert primary.entries[account_id] == [{"id": "mem_partial"}]
    assert account_id in backend.stale_fallback_entry_account_ids
    assert "read_entries: primary repair failed" in backend.last_fallback_sync_error
    assert "ACCOUNT MEMORY PRIMARY DATABASE REPAIR FROM FALLBACK FAILED" in caplog.text
    assert "primary backend recovered" not in caplog.text


def test_account_memory_fallback_blocks_fallback_after_primary_repair_failure() -> None:
    class Backend:
        def __init__(
            self,
            rows: list[dict[str, str]],
            *,
            skipped: int = 0,
            error: str = "",
            fail_read: bool = False,
            fail_write: bool = False,
        ) -> None:
            self.entries = {"a" * 128: [dict(row) for row in rows]}
            self.last_entry_skipped = skipped
            self.last_entry_read_error = error
            self.last_index_read_error = ""
            self.fail_read = fail_read
            self.fail_write = fail_write

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            if self.fail_read:
                raise AccountStoreError("primary unavailable")
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            if self.fail_write:
                raise AccountStoreError("primary repair failed")
            self.entries[account_id] = [dict(row) for row in rows]
            self.last_entry_skipped = 0
            self.last_entry_read_error = ""

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

    account_id = "a" * 128
    primary = Backend(
        [{"id": "mem_partial"}],
        skipped=2,
        error="payload could not be decrypted",
        fail_write=True,
    )
    fallback = Backend([{"id": "mem_clean"}])
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    first_read = backend.read_entries(account_id)
    primary.fail_read = True
    with pytest.raises(AccountStoreError, match="read blocked because primary is unavailable"):
        backend.read_entries(account_id)

    assert first_read == [{"id": "mem_clean"}]
    assert account_id in backend.stale_fallback_entry_account_ids
    assert account_id in backend._fallback_sync_failed_entries


def test_account_memory_fallback_recovers_primary_index_diagnostics(caplog):
    class Backend:
        def __init__(self, index: dict[str, object], *, error: str = "") -> None:
            self.indexes = {"a" * 128: dict(index)}
            self.last_entry_skipped = 0
            self.last_entry_read_error = ""
            self.last_index_read_error = error

        def read_entries(self, _account_id: str) -> list[dict[str, str]]:
            return []

        def write_entries(self, _account_id: str, _rows: list[dict[str, str]]) -> None:
            return None

        def read_index(self, account_id: str) -> dict[str, object]:
            return dict(self.indexes.get(account_id, {}))

        def write_index(self, account_id: str, data: dict[str, object]) -> None:
            self.indexes[account_id] = dict(data)
            self.last_index_read_error = ""

    account_id = "a" * 128
    primary = Backend({}, error="index could not be decrypted")
    fallback = Backend({"index": {"entries": {"mem_clean": {}}}})
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        index = backend.read_index(account_id)

    assert index == {"index": {"entries": {"mem_clean": {}}}}
    assert primary.indexes[account_id] == {"index": {"entries": {"mem_clean": {}}}}
    assert backend.last_index_read_error == ""
    assert "ACCOUNT MEMORY PRIMARY DATABASE FAILED" in caplog.text


def test_account_memory_fallback_does_not_repair_corrupt_primary_from_empty_entries(caplog):
    class Backend:
        def __init__(self, rows: list[dict[str, str]], *, skipped: int = 0, error: str = "") -> None:
            self.entries = {"a" * 128: [dict(row) for row in rows]}
            self.last_entry_skipped = skipped
            self.last_entry_read_error = error
            self.last_index_read_error = ""

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            self.entries[account_id] = [dict(row) for row in rows]
            self.last_entry_skipped = 0
            self.last_entry_read_error = ""

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

    account_id = "a" * 128
    primary = Backend([{"id": "mem_primary"}], skipped=1, error="payload could not be decrypted")
    fallback = Backend([])
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        entries = backend.read_entries(account_id)

    assert entries == []
    assert primary.entries[account_id] == [{"id": "mem_primary"}]
    assert backend.last_entry_read_error == "payload could not be decrypted"
    assert backend.last_entry_skipped == 1
    assert account_id in backend.stale_fallback_entry_account_ids
    assert backend.last_fallback_sync_error == "read_entries: fallback has no recoverable data"
    assert "ACCOUNT MEMORY PRIMARY DATABASE FAILED" in caplog.text


def test_account_memory_fallback_blocks_writes_after_unrecoverable_empty_entries(caplog):
    class Backend:
        def __init__(self, rows: list[dict[str, str]], *, skipped: int = 0, error: str = "") -> None:
            self.entries = {"a" * 128: [dict(row) for row in rows]} if rows else {}
            self.last_entry_skipped = skipped
            self.last_entry_read_error = error
            self.last_index_read_error = ""

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            self.entries[account_id] = [dict(row) for row in rows]
            self.last_entry_skipped = 0
            self.last_entry_read_error = ""

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

    account_id = "a" * 128
    primary = Backend([{"id": "mem_primary"}], skipped=1, error="payload could not be decrypted")
    fallback = Backend([])
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    backend.read_entries(account_id)
    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        with pytest.raises(AccountStoreError, match="write blocked because primary is unreadable and fallback has no recoverable data"):
            backend.write_entries(account_id, [{"id": "mem_new"}])

    assert primary.entries[account_id] == [{"id": "mem_primary"}]
    assert account_id not in fallback.entries
    assert account_id in backend.stale_fallback_entry_account_ids
    assert "ACCOUNT MEMORY WRITE BLOCKED" in caplog.text


def test_account_memory_fallback_does_not_repair_corrupt_primary_from_empty_index(caplog):
    class Backend:
        def __init__(self, index: dict[str, object], *, error: str = "") -> None:
            self.indexes = {"a" * 128: dict(index)}
            self.last_entry_skipped = 0
            self.last_entry_read_error = ""
            self.last_index_read_error = error

        def read_entries(self, _account_id: str) -> list[dict[str, str]]:
            return []

        def write_entries(self, _account_id: str, _rows: list[dict[str, str]]) -> None:
            return None

        def read_index(self, account_id: str) -> dict[str, object]:
            return dict(self.indexes.get(account_id, {}))

        def write_index(self, account_id: str, data: dict[str, object]) -> None:
            self.indexes[account_id] = dict(data)
            self.last_index_read_error = ""

    account_id = "a" * 128
    primary = Backend({"index": {"entries": {"mem_primary": {}}}}, error="index could not be decrypted")
    fallback = Backend({})
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        index = backend.read_index(account_id)

    assert index == {}
    assert primary.indexes[account_id] == {"index": {"entries": {"mem_primary": {}}}}
    assert backend.last_index_read_error == "index could not be decrypted"
    assert account_id in backend.stale_fallback_index_account_ids
    assert backend.last_fallback_sync_error == "read_index: fallback has no recoverable data"
    assert "ACCOUNT MEMORY PRIMARY DATABASE FAILED" in caplog.text


def test_account_memory_fallback_mirrors_successful_primary_entry_writes() -> None:
    class Backend:
        def __init__(self) -> None:
            self.entries: dict[str, list[dict[str, str]]] = {}

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            self.entries[account_id] = [dict(row) for row in rows]

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

    primary = Backend()
    fallback = Backend()
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")
    account_id = "a" * 128

    backend.write_entries(account_id, [{"id": "mem_primary"}])

    assert primary.entries[account_id] == [{"id": "mem_primary"}]
    assert fallback.entries[account_id] == [{"id": "mem_primary"}]


def test_account_memory_fallback_mirrors_successful_primary_index_writes() -> None:
    class Backend:
        def __init__(self) -> None:
            self.indexes: dict[str, dict[str, object]] = {}

        def read_entries(self, _account_id: str) -> list[dict[str, str]]:
            return []

        def write_entries(self, _account_id: str, _rows: list[dict[str, str]]) -> None:
            return None

        def read_index(self, account_id: str) -> dict[str, object]:
            return dict(self.indexes.get(account_id, {}))

        def write_index(self, account_id: str, data: dict[str, object]) -> None:
            self.indexes[account_id] = dict(data)

    primary = Backend()
    fallback = Backend()
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")
    account_id = "a" * 128
    index = {"index": {"entries": {"mem_primary": {}}}}

    backend.write_index(account_id, index)

    assert primary.indexes[account_id] == index
    assert fallback.indexes[account_id] == index


def test_account_memory_fallback_warns_when_secondary_mirror_write_fails(caplog):
    class Backend:
        def __init__(self, *, fail_write: bool = False) -> None:
            self.fail_write = fail_write
            self.entries: dict[str, list[dict[str, str]]] = {}

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            if self.fail_write:
                raise OSError("fallback unavailable")
            self.entries[account_id] = [dict(row) for row in rows]

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

    primary = Backend()
    fallback = Backend(fail_write=True)
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")
    account_id = "a" * 128

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        backend.write_entries(account_id, [{"id": "mem_primary"}])

    assert primary.entries[account_id] == [{"id": "mem_primary"}]
    assert fallback.entries.get(account_id) is None
    assert "ACCOUNT MEMORY FALLBACK DATABASE SYNC FAILED" in caplog.text
    assert "FALLBACK MAY BE STALE" in caplog.text


def test_account_memory_fallback_repairs_stale_secondary_on_later_primary_read() -> None:
    class Backend:
        def __init__(self, *, fail_write: bool = False) -> None:
            self.fail_write = fail_write
            self.entries: dict[str, list[dict[str, str]]] = {}

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            if self.fail_write:
                raise OSError("fallback unavailable")
            self.entries[account_id] = [dict(row) for row in rows]

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

    account_id = "a" * 128
    primary = Backend()
    fallback = Backend(fail_write=True)
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    backend.write_entries(account_id, [{"id": "mem_primary"}])
    fallback.fail_write = False

    assert backend.read_entries(account_id) == [{"id": "mem_primary"}]
    assert fallback.entries[account_id] == [{"id": "mem_primary"}]
    assert backend.stale_fallback_entry_account_ids == ()
    assert backend.last_fallback_sync_error == ""


def test_account_memory_fallback_clear_resets_recovery_state() -> None:
    class Backend:
        def clear_account_unchecked(self, _account_id: str) -> None:
            return None

    account_id = "a" * 128
    backend = WarningFallbackAccountMemoryBackend(Backend(), Backend(), label="Demo:sqlite")
    backend._fallback_active = True
    backend._stale_fallback_entries.add(account_id)
    backend._fallback_sync_failed_indexes.add(account_id)
    backend.last_fallback_sync_error = "fallback unavailable"

    backend.clear_account_unchecked(account_id)

    assert backend._fallback_active is False
    assert backend.stale_fallback_entry_account_ids == ()
    assert backend.stale_fallback_index_account_ids == ()
    assert backend.last_fallback_sync_error == ""


def test_account_memory_fallback_clear_does_not_hide_other_account_failure() -> None:
    class Backend:
        def clear_account_unchecked(self, _account_id: str) -> None:
            return None

    account_a = "a" * 128
    account_b = "b" * 128
    backend = WarningFallbackAccountMemoryBackend(Backend(), Backend(), label="Demo:sqlite")
    backend._fallback_active = True
    backend._fallback_sync_failed_entries.add(account_a)
    backend.last_fallback_sync_error = "account A fallback unavailable"

    backend.clear_account_unchecked(account_b)

    assert backend._fallback_active is True
    assert account_a in backend._fallback_sync_failed_entries
    assert backend.last_fallback_sync_error == "account A fallback unavailable"


def test_account_memory_fallback_blocks_failover_when_secondary_clear_fails(caplog) -> None:
    class Backend:
        def __init__(self, *, fail_clear: bool = False) -> None:
            self.fail_clear = fail_clear

        def clear_account_unchecked(self, _account_id: str) -> None:
            if self.fail_clear:
                raise OSError("fallback clear unavailable")

    account_id = "a" * 128
    backend = WarningFallbackAccountMemoryBackend(Backend(), Backend(fail_clear=True), label="Demo:sqlite")

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        with pytest.raises(OSError, match="fallback clear unavailable"):
            backend.clear_account_unchecked(account_id)

    assert backend._fallback_active is True
    assert account_id in backend._fallback_sync_failed_entries
    assert account_id in backend._fallback_sync_failed_indexes
    assert backend.stale_fallback_collection_account_ids == (account_id,)
    assert backend._operation_has_unsafe_fallback("read_collection:codex_history_outbox", account_id) is True
    assert "FAILOVER IS BLOCKED" in caplog.text


def test_account_memory_fallback_blocks_collection_names_after_secondary_clear_failure() -> None:
    class Backend:
        def __init__(self, *, fail_clear: bool = False, fail_names: bool = False) -> None:
            self.fail_clear = fail_clear
            self.fail_names = fail_names
            self.collections = {"a" * 128: {"version_notifications"}}

        def clear_account_unchecked(self, account_id: str) -> None:
            if self.fail_clear:
                raise OSError("fallback clear unavailable")
            self.collections.pop(account_id, None)

        def read_collection_names(self, account_id: str) -> tuple[str, ...]:
            if self.fail_names:
                raise OSError("primary unavailable")
            return tuple(sorted(self.collections.get(account_id, set())))

    account_id = "a" * 128
    primary = Backend(fail_names=True)
    fallback = Backend(fail_clear=True)
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    with pytest.raises(OSError, match="fallback clear unavailable"):
        backend.clear_account_unchecked(account_id)
    with pytest.raises(AccountStoreError, match="read_collection_names: read blocked"):
        backend.read_collection_names(account_id)


def test_account_memory_fallback_serializes_diagnostic_capture_across_accounts() -> None:
    account_a = "a" * 128
    account_b = "b" * 128
    first_read_started = threading.Event()
    release_first_read = threading.Event()
    second_read_started = threading.Event()

    class Backend:
        def __init__(self, rows: dict[str, list[dict[str, str]]], *, block_account: str = "") -> None:
            self.rows = rows
            self.block_account = block_account
            self.last_entry_read_error = ""
            self.last_entry_skipped = 0
            self.last_index_read_error = ""
            self.last_collection_read_error = ""
            self.last_collection_skipped = 0

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            self.last_entry_read_error = ""
            self.last_entry_skipped = 0
            if account_id == self.block_account:
                self.last_entry_read_error = "corrupt row"
                self.last_entry_skipped = 1
                first_read_started.set()
                release_first_read.wait(timeout=2)
            elif account_id == account_b:
                second_read_started.set()
            return [dict(row) for row in self.rows.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            self.rows[account_id] = [dict(row) for row in rows]

    primary = Backend(
        {
            account_a: [{"id": "a-visible"}],
            account_b: [{"id": "b-visible"}],
        },
        block_account=account_a,
    )
    fallback = Backend(
        {
            account_a: [{"id": "a-visible"}, {"id": "a-omitted"}],
            account_b: [{"id": "b-visible"}],
        }
    )
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")
    results: dict[str, list[dict[str, str]]] = {}

    first_thread = threading.Thread(target=lambda: results.setdefault("a", backend.read_entries(account_a)))
    second_thread = threading.Thread(target=lambda: results.setdefault("b", backend.read_entries(account_b)))
    first_thread.start()
    assert first_read_started.wait(timeout=1)
    second_thread.start()

    # Without the wrapper lock, account B clears account A's diagnostics here.
    assert not second_read_started.wait(timeout=0.25)
    release_first_read.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert {row["id"] for row in results["a"]} == {"a-visible", "a-omitted"}
    assert results["b"] == [{"id": "b-visible"}]


def test_account_memory_fallback_retries_secondary_clear_before_collection_names() -> None:
    class Backend:
        def __init__(self, *, fail_clear: bool = False) -> None:
            self.fail_clear = fail_clear
            self.collections = {"a" * 128: {"version_notifications"}}

        def clear_account_unchecked(self, account_id: str) -> None:
            if self.fail_clear:
                raise OSError("fallback clear unavailable")
            self.collections.pop(account_id, None)

        def read_collection_names(self, account_id: str) -> tuple[str, ...]:
            return tuple(sorted(self.collections.get(account_id, set())))

    account_id = "a" * 128
    primary = Backend()
    fallback = Backend(fail_clear=True)
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    with pytest.raises(OSError, match="fallback clear unavailable"):
        backend.clear_account_unchecked(account_id)
    fallback.fail_clear = False

    assert backend.read_collection_names(account_id) == ()
    assert fallback.collections.get(account_id) is None
    assert backend.stale_fallback_collection_account_ids == ()
    assert backend.last_fallback_sync_error == ""


def test_account_memory_fallback_blocks_writes_until_secondary_clear_succeeds() -> None:
    class Backend:
        def __init__(self, *, fail_clear: bool = False) -> None:
            self.fail_clear = fail_clear
            self.entries: dict[str, list[dict[str, str]]] = {}

        def clear_account_unchecked(self, account_id: str) -> None:
            if self.fail_clear:
                raise OSError("fallback clear unavailable")
            self.entries.pop(account_id, None)

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            self.entries[account_id] = [dict(row) for row in rows]

    account_id = "a" * 128
    primary = Backend()
    fallback = Backend(fail_clear=True)
    primary.entries[account_id] = [{"id": "old_primary"}]
    fallback.entries[account_id] = [{"id": "old_fallback"}]
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    with pytest.raises(OSError, match="fallback clear unavailable"):
        backend.clear_account_unchecked(account_id)
    with pytest.raises(AccountStoreError, match="fallback account clear is pending"):
        backend.write_entries(account_id, [{"id": "new"}])

    assert primary.entries.get(account_id) is None
    assert fallback.entries[account_id] == [{"id": "old_fallback"}]

    fallback.fail_clear = False
    backend.write_entries(account_id, [{"id": "new"}])

    assert primary.entries[account_id] == [{"id": "new"}]
    assert fallback.entries[account_id] == [{"id": "new"}]
    assert backend.stale_fallback_collection_account_ids == ()
    assert backend.last_fallback_sync_error == ""


def test_account_memory_fallback_retries_full_secondary_clear_on_primary_read() -> None:
    class Backend:
        def __init__(self, *, fail_clear: bool = False) -> None:
            self.fail_clear = fail_clear
            self.entries: dict[str, list[dict[str, str]]] = {}
            self.indexes: dict[str, dict[str, object]] = {}
            self.collections: dict[tuple[str, str], list[dict[str, str]]] = {}

        def clear_account_unchecked(self, account_id: str) -> None:
            if self.fail_clear:
                raise OSError("fallback clear unavailable")
            self.entries.pop(account_id, None)
            self.indexes.pop(account_id, None)
            self.collections = {
                key: rows for key, rows in self.collections.items() if key[0] != account_id
            }

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            self.entries[account_id] = [dict(row) for row in rows]

        def read_index(self, account_id: str) -> dict[str, object]:
            return dict(self.indexes.get(account_id, {}))

        def write_index(self, account_id: str, data: dict[str, object]) -> None:
            self.indexes[account_id] = dict(data)

        def read_collection(self, account_id: str, collection: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.collections.get((account_id, collection), [])]

        def write_collection(self, account_id: str, collection: str, rows: list[dict[str, str]]) -> None:
            self.collections[(account_id, collection)] = [dict(row) for row in rows]

    account_id = "a" * 128
    primary = Backend()
    fallback = Backend(fail_clear=True)
    fallback.entries[account_id] = [{"id": "old_entry"}]
    fallback.indexes[account_id] = {"index": {"entries": {"old_entry": {}}}}
    fallback.collections[(account_id, "version_notifications")] = [{"id": "old_notification"}]
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    with pytest.raises(OSError, match="fallback clear unavailable"):
        backend.clear_account_unchecked(account_id)
    fallback.fail_clear = False

    assert backend.read_entries(account_id) == []
    assert account_id not in fallback.entries
    assert account_id not in fallback.indexes
    assert not any(key[0] == account_id for key in fallback.collections)
    assert backend.stale_fallback_collection_account_ids == ()
    assert backend.last_fallback_sync_error == ""


def test_account_memory_fallback_retries_stale_secondary_when_primary_is_available() -> None:
    class Backend:
        def __init__(self, *, fail_write: bool = False) -> None:
            self.fail_write = fail_write
            self.entries: dict[str, list[dict[str, str]]] = {}

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            if self.fail_write:
                raise OSError("backend unavailable")
            self.entries[account_id] = [dict(row) for row in rows]

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

    primary = Backend()
    fallback = Backend(fail_write=True)
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")
    account_id = "a" * 128

    backend.write_entries(account_id, [{"id": "mem_primary_1"}])
    fallback.fail_write = False
    backend.write_entries(account_id, [{"id": "mem_primary_2"}])

    assert primary.entries[account_id] == [{"id": "mem_primary_2"}]
    assert fallback.entries[account_id] == [{"id": "mem_primary_2"}]
    assert backend.stale_fallback_entry_account_ids == ()
    assert backend.last_fallback_sync_error == ""


def test_account_memory_fallback_blocks_stale_secondary_when_primary_fails() -> None:
    class Backend:
        def __init__(self, *, fail_write: bool = False) -> None:
            self.fail_write = fail_write
            self.entries: dict[str, list[dict[str, str]]] = {}

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            if self.fail_write:
                raise OSError("backend unavailable")
            self.entries[account_id] = [dict(row) for row in rows]

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

    primary = Backend()
    fallback = Backend(fail_write=True)
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")
    account_id = "a" * 128

    backend.write_entries(account_id, [{"id": "mem_primary"}])
    primary.fail_write = True
    fallback.fail_write = False

    with pytest.raises(AccountStoreError, match="fallback may be stale"):
        backend.write_entries(account_id, [{"id": "mem_blocked"}])

    assert fallback.entries.get(account_id) is None


def test_account_memory_fallback_blocks_reads_from_stale_secondary_when_primary_fails() -> None:
    class Backend:
        def __init__(self, *, fail_read: bool = False, fail_write: bool = False) -> None:
            self.fail_read = fail_read
            self.fail_write = fail_write
            self.entries: dict[str, list[dict[str, str]]] = {}

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            if self.fail_read:
                raise OSError("primary unavailable")
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            if self.fail_write:
                raise OSError("fallback unavailable")
            self.entries[account_id] = [dict(row) for row in rows]

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

    primary = Backend()
    fallback = Backend(fail_write=True)
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")
    account_id = "a" * 128

    backend.write_entries(account_id, [{"id": "mem_primary"}])
    primary.fail_read = True
    fallback.fail_write = False

    with pytest.raises(AccountStoreError, match="fallback may be stale"):
        backend.read_entries(account_id)

    assert fallback.entries.get(account_id) is None


def test_account_memory_fallback_retries_stale_collection_secondary_when_primary_is_available() -> None:
    class Backend:
        def __init__(self, *, fail_write: bool = False) -> None:
            self.fail_write = fail_write
            self.collections: dict[tuple[str, str], list[dict[str, str]]] = {}

        def read_entries(self, _account_id: str) -> list[dict[str, str]]:
            return []

        def write_entries(self, _account_id: str, _rows: list[dict[str, str]]) -> None:
            return None

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

        def read_collection(self, account_id: str, collection: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.collections.get((account_id, collection), [])]

        def write_collection(self, account_id: str, collection: str, rows: list[dict[str, str]]) -> None:
            if self.fail_write:
                raise OSError("backend unavailable")
            self.collections[(account_id, collection)] = [dict(row) for row in rows]

        def read_collection_names(self, account_id: str) -> tuple[str, ...]:
            return tuple(sorted(collection for item_account, collection in self.collections if item_account == account_id))

    primary = Backend()
    fallback = Backend(fail_write=True)
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")
    account_id = "a" * 128

    backend.write_collection(account_id, "version_notifications", [{"id": "version_state_1"}])
    fallback.fail_write = False
    backend.write_collection(account_id, "version_notifications", [{"id": "version_state_2"}])

    assert primary.collections[(account_id, "version_notifications")] == [{"id": "version_state_2"}]
    assert fallback.collections[(account_id, "version_notifications")] == [{"id": "version_state_2"}]
    assert backend.stale_fallback_collection_account_ids == ()
    assert backend.last_fallback_sync_error == ""


def test_account_memory_fallback_repairs_stale_append_collection_from_primary() -> None:
    class Backend:
        def __init__(self, *, fail_append: bool = False) -> None:
            self.fail_append = fail_append
            self.collections: dict[tuple[str, str], list[dict[str, str]]] = {}

        def read_entries(self, _account_id: str) -> list[dict[str, str]]:
            return []

        def write_entries(self, _account_id: str, _rows: list[dict[str, str]]) -> None:
            return None

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

        def read_collection(self, account_id: str, collection: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.collections.get((account_id, collection), [])]

        def write_collection(self, account_id: str, collection: str, rows: list[dict[str, str]]) -> None:
            self.collections[(account_id, collection)] = [dict(row) for row in rows]

        def append_collection_items(self, account_id: str, collection: str, rows: list[dict[str, str]]) -> None:
            if self.fail_append:
                raise OSError("fallback append unavailable")
            self.collections.setdefault((account_id, collection), []).extend(dict(row) for row in rows)

    account_id = "a" * 128
    primary = Backend()
    fallback = Backend(fail_append=True)
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    backend.append_collection_items(account_id, "codex_history_dispatch_results", [{"id": "row_1"}])
    assert backend.stale_fallback_collection_account_ids == (account_id,)

    fallback.fail_append = False
    backend.append_collection_items(account_id, "codex_history_dispatch_results", [{"id": "row_2"}])

    assert primary.collections[(account_id, "codex_history_dispatch_results")] == [{"id": "row_1"}, {"id": "row_2"}]
    assert fallback.collections[(account_id, "codex_history_dispatch_results")] == [
        {"id": "row_1"},
        {"id": "row_2"},
    ]
    assert backend.stale_fallback_collection_account_ids == ()


def test_account_memory_fallback_repairs_stale_replace_collection_from_primary() -> None:
    class Backend:
        def __init__(self, *, fail_write: bool = False) -> None:
            self.fail_write = fail_write
            self.collections: dict[tuple[str, str], list[dict[str, str]]] = {}

        def read_entries(self, _account_id: str) -> list[dict[str, str]]:
            return []

        def write_entries(self, _account_id: str, _rows: list[dict[str, str]]) -> None:
            return None

        def read_index(self, _account_id: str) -> dict[str, object]:
            return {}

        def write_index(self, _account_id: str, _data: dict[str, object]) -> None:
            return None

        def read_collection(self, account_id: str, collection: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.collections.get((account_id, collection), [])]

        def write_collection(self, account_id: str, collection: str, rows: list[dict[str, str]]) -> None:
            if self.fail_write:
                raise OSError("fallback unavailable")
            self.collections[(account_id, collection)] = [dict(row) for row in rows]

        def replace_collection_item(self, account_id: str, collection: str, item_key: str, row: dict[str, str]) -> bool:
            existing_rows = self.collections.get((account_id, collection), [])
            for index, existing in enumerate(existing_rows):
                if str(existing.get("id") or "").strip() == item_key:
                    existing_rows[index] = dict(row)
                    return True
            return False

    account_id = "a" * 128
    collection = "codex_history_dispatch_results"
    primary = Backend()
    fallback = Backend()
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    backend.write_collection(account_id, collection, [{"id": "row_1"}])
    fallback.fail_write = True
    backend.write_collection(account_id, collection, [{"id": "row_1"}, {"id": "row_2"}])
    assert backend.stale_fallback_collection_account_ids == (account_id,)
    fallback.fail_write = False

    assert backend.replace_collection_item(account_id, collection, "row_2", {"id": "row_2", "status": "sent"})

    assert fallback.collections[(account_id, collection)] == primary.collections[(account_id, collection)]
    assert backend.stale_fallback_collection_account_ids == ()


def test_account_store_sqlite_backend_skips_corrupt_rows(tmp_path, monkeypatch, caplog):
    sqlite_path = tmp_path / "memory.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_memory_entries(account_id, [{"id": "mem_ok", "user_text": "ok"}])
    import sqlite3

    con = sqlite3.connect(sqlite_path)
    with con:
        con.execute("update memory_entries set payload_ciphertext = ? where memory_id = ?", (b"broken", "mem_ok"))
    con.close()
    fallback_path = tmp_path / "accounts" / "Account_Memory.backup.sqlite3"
    con = sqlite3.connect(fallback_path)
    with con:
        con.execute("update memory_entries set payload_ciphertext = ? where memory_id = ?", (b"broken", "mem_ok"))
    con.close()

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        entries = store.read_memory_entries(account_id)

    assert entries == []
    assert "skipped corrupt rows" in caplog.text


def test_sqlite_missing_primary_schema_is_diagnostic_only_with_secondary(tmp_path, caplog):
    import sqlite3

    primary_path = tmp_path / "primary.sqlite3"
    secondary_path = tmp_path / "secondary.sqlite3"
    sqlite3.connect(primary_path).close()
    sqlite3.connect(secondary_path).close()
    backend = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=primary_path, fallback_path=secondary_path),
    )

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        assert backend.read_entries("a" * 128) == []
        assert backend.read_index("a" * 128) == {}
        assert backend.read_collection("a" * 128, "version_notifications") == []
        with pytest.raises(AccountStoreError, match="schema table is missing"):
            backend.read_collection_names("a" * 128)

    assert "schema table is missing" in backend.last_collection_read_error
    assert "schema table is missing" in caplog.text


def test_sqlite_first_run_without_secondary_keeps_missing_schema_empty(tmp_path):
    import sqlite3

    primary_path = tmp_path / "primary.sqlite3"
    sqlite3.connect(primary_path).close()
    backend = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=primary_path, fallback_path=None),
    )

    assert backend.read_entries("a" * 128) == []
    assert backend.read_collection_names("a" * 128) == ()
    assert backend.last_entry_read_error == ""
    assert backend.last_database_missing is False


def test_sqlite_missing_primary_schema_recovers_from_secondary(tmp_path):
    import sqlite3

    primary_path = tmp_path / "primary.sqlite3"
    secondary_path = tmp_path / "secondary.sqlite3"
    sqlite3.connect(primary_path).close()
    account_id = "a" * 128
    fallback = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=secondary_path, fallback_path=None),
    )
    fallback.write_entries(account_id, [{"id": "from-secondary", "user_text": "Backup"}])
    primary = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=primary_path, fallback_path=secondary_path),
    )
    backend = WarningFallbackAccountMemoryBackend(primary, fallback, label="Demo:sqlite")

    assert backend.read_entries(account_id) == [{"id": "from-secondary", "user_text": "Backup"}]
    assert primary.read_entries(account_id) == [{"id": "from-secondary", "user_text": "Backup"}]


def test_sqlite_write_refuses_schema_repair_when_secondary_exists(tmp_path):
    import sqlite3

    primary_path = tmp_path / "primary.sqlite3"
    secondary_path = tmp_path / "secondary.sqlite3"
    sqlite3.connect(primary_path).close()
    account_id = "a" * 128
    secondary = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=secondary_path, fallback_path=None),
    )
    secondary.write_entries(account_id, [{"id": "from-secondary", "user_text": "Backup"}])
    primary = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=primary_path, fallback_path=secondary_path),
    )

    with pytest.raises(AccountStoreError, match="schema table is missing"):
        primary.write_entries(account_id, [{"id": "new"}])

    with sqlite3.connect(primary_path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert "memory_entries" not in tables
    assert secondary.read_entries(account_id) == [{"id": "from-secondary", "user_text": "Backup"}]


def test_sqlite_write_refuses_primary_creation_when_secondary_exists(tmp_path):
    primary_path = tmp_path / "primary.sqlite3"
    secondary_path = tmp_path / "secondary.sqlite3"
    account_id = "a" * 128
    secondary = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=secondary_path, fallback_path=None),
    )
    secondary.write_entries(account_id, [{"id": "from-secondary", "user_text": "Backup"}])
    primary = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=primary_path, fallback_path=secondary_path),
    )

    with pytest.raises(AccountStoreError, match="database is missing"):
        primary.write_entries(account_id, [{"id": "new"}])

    assert not primary_path.exists()
    assert secondary.read_entries(account_id) == [{"id": "from-secondary", "user_text": "Backup"}]


def test_sqlite_write_refuses_missing_required_column_when_secondary_exists(tmp_path):
    import sqlite3

    primary_path = tmp_path / "primary.sqlite3"
    secondary_path = tmp_path / "secondary.sqlite3"
    account_id = "a" * 128
    primary_without_fallback = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=primary_path, fallback_path=None),
    )
    primary_without_fallback.write_entries(account_id, [{"id": "primary"}])
    with sqlite3.connect(primary_path) as connection:
        connection.execute("ALTER TABLE memory_entries DROP COLUMN last_accessed_at")
    secondary = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=secondary_path, fallback_path=None),
    )
    secondary.write_entries(account_id, [{"id": "from-secondary"}])
    primary = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=primary_path, fallback_path=secondary_path),
    )

    with pytest.raises(AccountStoreError, match="schema column is missing: memory_entries.last_accessed_at"):
        primary.write_entries(account_id, [{"id": "new"}])

    with sqlite3.connect(primary_path) as connection:
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(memory_entries)")}
    assert "last_accessed_at" not in columns


def test_structured_account_memory_semantic_cache_boosts_synced_signature(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    direct_id = store.append_structured_memory_entry(account_id, {"id": "mem_direct", "user_text": "Mond", "bot_text": "Tee"})
    semantic_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_semantic", "kind": "coping_strategy", "user_text": "Spaziergang hilft bei Druck.", "bot_text": "Ressource notiert."},
    )
    index = store.read_memory_index(account_id)
    index["index"]["keywords"].pop("spaziergang", None)
    store.write_memory_index(account_id, index)

    selection = store.select_structured_memory(account_id, query_text="spaziergang", max_prompt_chars=12000, max_entry_chars=2000)

    assert selection.selected_ids[:2] == (semantic_id, direct_id)


def test_structured_account_memory_semantic_embedding_matches_synonym(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    walk_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_walk", "kind": "coping_strategy", "user_text": "Spaziergang hilft bei Druck.", "bot_text": "Ressource notiert."},
    )
    other_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_other", "user_text": "Mond Tee.", "bot_text": "Notiz."},
    )

    selection = store.select_structured_memory(account_id, query_text="gehen stress", max_prompt_chars=12000, max_entry_chars=2000)

    assert selection.selected_ids[:2] == (walk_id, other_id)
    semantic_entry = store.read_memory_index(account_id)["index"]["semantic_cache"]["entries"][walk_id]
    assert len(semantic_entry["embedding"]) == 64


def test_memory_ranking_uses_entry_order_as_recent_fallback(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_memory_entries(
        account_id,
        [
            {"id": "mem_first", "user_text": "Mond", "keywords": ["mond"]},
            {"id": "mem_second", "user_text": "Mond", "keywords": ["mond"]},
        ],
    )
    store.write_memory_index(
        account_id,
        {
            "scope": "account",
            "index": {
                "recent_ids": [],
                "accessed_ids": [],
                "keywords": {"mond": ["mem_first", "mem_second"]},
                "entries": {},
            },
        },
    )

    assert store.rank_structured_memory_ids(account_id, query_text="mond", limit=2) == ("mem_second", "mem_first")


def test_memory_ranking_normalizes_legacy_id_whitespace(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())

    ranked = store._rank_structured_memory_entries(
        [{"id": " mem_legacy ", "user_text": "Mond", "keywords": ["mond"]}],
        {
            "index": {
                "recent_ids": ["mem_legacy"],
                "accessed_ids": [],
                "keywords": {"mond": ["mem_legacy"]},
                "semantic_cache": {"enabled": False, "entries": {}},
            }
        },
        "mond",
    )

    assert [entry["id"] for entry in ranked] == [" mem_legacy "]


def test_memory_ranking_does_not_double_score_duplicate_index_ids(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())

    ranked = store._rank_structured_memory_entries(
        [
            {"id": "mem_a", "user_text": "Mond", "keywords": ["mond"]},
            {"id": "mem_b", "user_text": "Mond", "keywords": ["mond"]},
        ],
        {
            "index": {
                "recent_ids": ["mem_a", "mem_b"],
                "accessed_ids": [],
                "keywords": {"mond": ["mem_a", " mem_a ", "mem_b"]},
                "semantic_cache": {"enabled": False, "entries": {}},
            }
        },
        "mond",
    )

    assert [entry["id"] for entry in ranked] == ["mem_b", "mem_a"]


def test_structured_account_memory_selection_can_exclude_loaded_ids(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    walk_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_walk", "kind": "coping_strategy", "user_text": "Spaziergang hilft bei Druck.", "bot_text": "Ressource notiert."},
    )
    tea_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_tea", "user_text": "Tee hilft beim Sortieren.", "bot_text": "Notiz."},
    )

    selection = store.select_structured_memory(
        account_id,
        query_text="gehen stress tee",
        max_prompt_chars=12000,
        max_entry_chars=2000,
        exclude_ids=(walk_id,),
    )

    assert walk_id not in selection.selected_ids
    assert tea_id in selection.selected_ids
    assert '"id": "mem_walk"' not in selection.prompt_text


def test_structured_account_memory_semantic_cache_can_be_disabled(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_memory_index(account_id, {"index": {"semantic_cache": {"enabled": False, "entries": {"stale": {}}}}})

    store.append_structured_memory_entry(
        account_id,
        {"id": "mem_walk", "kind": "coping_strategy", "user_text": "Spaziergang hilft bei Druck.", "bot_text": "Ressource notiert."},
    )

    semantic_cache = store.read_memory_index(account_id)["index"]["semantic_cache"]
    assert semantic_cache["enabled"] is False
    assert semantic_cache["entries"] == {}


def test_rebuild_structured_account_memory_keeps_semantic_cache_disabled(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.append_structured_memory_entry(
        account_id,
        {"id": "mem_walk", "kind": "coping_strategy", "user_text": "Spaziergang hilft bei Druck.", "bot_text": "Ressource notiert."},
    )
    index = store.read_memory_index(account_id)
    index["index"]["semantic_cache"]["enabled"] = False
    index["index"]["semantic_cache"]["entries"] = {"stale": {}}
    store.write_memory_index(account_id, index)

    store.rebuild_structured_memory_index(account_id)

    semantic_cache = store.read_memory_index(account_id)["index"]["semantic_cache"]
    assert semantic_cache["enabled"] is False
    assert semantic_cache["entries"] == {}


def test_structured_account_memory_records_access_recency(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    first_id = store.append_structured_memory_entry(account_id, {"id": "mem_first", "user_text": "Mond", "bot_text": "Tee"})
    second_id = store.append_structured_memory_entry(account_id, {"id": "mem_second", "user_text": "Kaffee", "bot_text": "Tasse"})

    selection = store.select_structured_memory(account_id, query_text="mond", max_prompt_chars=12000, max_entry_chars=2000)

    assert selection.selected_ids[:2] == (first_id, second_id)
    entries = {entry["id"]: entry for entry in store.read_memory_entries(account_id)}
    index = store.read_memory_index(account_id)["index"]
    assert entries[first_id]["access_count"] == 1
    assert entries[first_id]["last_accessed_at"]
    assert index["accessed_ids"][-2:] == [first_id, second_id]


def test_rebuild_structured_account_memory_restores_access_recency(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    first_id = store.append_structured_memory_entry(account_id, {"id": "mem_first", "user_text": "Mond", "bot_text": "Tee"})
    second_id = store.append_structured_memory_entry(account_id, {"id": "mem_second", "user_text": "Kaffee", "bot_text": "Tasse"})
    store.select_structured_memory(account_id, query_text="mond", max_prompt_chars=12000, max_entry_chars=2000)
    index = store.read_memory_index(account_id)
    index["index"]["accessed_ids"] = []
    store.write_memory_index(account_id, index)

    store.rebuild_structured_memory_index(account_id)

    rebuilt = store.read_memory_index(account_id)["index"]
    assert rebuilt["accessed_ids"][-2:] == [first_id, second_id]
    assert store.check_structured_memory_index(account_id).ok


def test_mark_structured_account_memory_accessed_deduplicates_requested_ids(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    memory_id = store.append_structured_memory_entry(account_id, {"id": "mem_first", "user_text": "Mond", "bot_text": "Tee"})

    store.mark_structured_memory_accessed(account_id, [memory_id, memory_id])

    index = store.read_memory_index(account_id)["index"]
    entries = {entry["id"]: entry for entry in store.read_memory_entries(account_id)}
    assert index["accessed_ids"] == [memory_id]
    assert entries[memory_id]["access_count"] == 1
    assert store.check_structured_memory_index(account_id).ok


def test_mark_structured_account_memory_rolls_back_entries_when_index_write_fails(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    memory_id = store.append_structured_memory_entry(account_id, {"id": "mem_first", "user_text": "Mond", "bot_text": "Tee"})
    previous_rows = store.read_memory_entries(account_id)
    previous_index = store.read_memory_index(account_id)

    with patch.object(
        store,
        "write_memory_index",
        side_effect=[AccountStoreError("index write failed"), None],
    ):
        with pytest.raises(AccountStoreError, match="index write failed"):
            store.mark_structured_memory_accessed(account_id, [memory_id])

    assert store.read_memory_entries(account_id) == previous_rows
    assert store.read_memory_index(account_id) == previous_index


def test_structured_account_memory_indexes_types_and_temporal_relations(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    source_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_episode", "memory_type": "episodic", "user_text": "Episode Druck.", "bot_text": "Notiert."},
    )
    fact_id = store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_fact",
            "kind": "fact",
            "memory_type": "semantic",
            "user_text": "Druck bessert sich durch Bewegung.",
            "bot_text": "Faktensignal notiert.",
            "valid_from": "2026-06-15",
            "relations": [
                {
                    "type": "derived_from",
                    "target_id": source_id,
                    "valid_from": "2026-06-15",
                    "provenance": {"source": "test"},
                    "confidence": 0.75,
                }
            ],
        },
    )

    index = store.read_memory_index(account_id)["index"]

    assert source_id in index["types"]["episodic"]
    assert fact_id in index["types"]["semantic"]
    assert index["entries"][fact_id]["valid_from"] == "2026-06-15"
    assert index["entries"][fact_id]["relations"][0]["type"] == "derived_from"
    assert {"source_id": fact_id, "target_id": source_id, "type": "derived_from", "valid_from": "2026-06-15", "valid_to": "", "provenance": {"source": "test"}, "confidence": 0.75} in index["graph"]["relations"]


def test_structured_account_memory_maintenance_consolidates_repeated_episodes(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    for index in range(3):
        store.append_structured_memory_entry(
            account_id,
            {
                "id": f"mem_episode_{index}",
                "memory_type": "episodic",
                "user_text": f"Spaziergang hilft gegen Druck {index}.",
                "bot_text": "Notiert.",
            },
        )

    created = store.run_memory_maintenance(account_id)

    assert len(created) == 1
    entries = {entry["id"]: entry for entry in store.read_memory_entries(account_id)}
    consolidated = entries[created[0]]
    assert consolidated["memory_type"] == "semantic"
    assert consolidated["kind"] == "summary"
    assert consolidated["supports"] == ["mem_episode_0", "mem_episode_1", "mem_episode_2"]


def test_structured_account_memory_consolidation_zero_limit_is_a_noop(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    for index in range(3):
        store.append_structured_memory_entry(
            account_id,
            {
                "id": f"mem_episode_{index}",
                "memory_type": "episodic",
                "user_text": f"Spaziergang hilft gegen Druck {index}.",
                "bot_text": "Notiert.",
            },
        )
    before_entries = store.read_memory_entries(account_id)
    before_index = store.read_memory_index(account_id)

    created = store.consolidate_structured_memory(account_id, max_new_entries=0)

    assert created == ()
    assert store.read_memory_entries(account_id) == before_entries
    assert store.read_memory_index(account_id) == before_index


def test_account_memory_merge_keeps_distinct_row_after_duplicate_id_replacement():
    merged = _merge_account_jsonl_rows(
        [{"id": "mem_same", "updated_at": "2026-07-01T10:00:00+00:00", "text": "alt"}],
        [
            {"id": "mem_same", "updated_at": "2026-07-01T11:00:00+00:00", "text": "neu"},
            {"id": "mem_other", "updated_at": "2026-07-01T12:00:00+00:00", "text": "alt"},
        ],
    )

    assert [row["id"] for row in merged] == ["mem_same", "mem_other"]
    assert merged[0]["text"] == "neu"


def test_rebuild_structured_account_memory_index_renames_duplicate_ids(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_memory_entries(
        account_id,
        [
            {"id": "mem_same", "user_text": "Mond", "bot_text": "Tee"},
            {"id": "mem_same", "user_text": "Kaffee", "bot_text": "Tasse"},
        ],
    )

    store.rebuild_structured_memory_index(account_id)

    entries = store.read_memory_entries(account_id)
    ids = [entry["id"] for entry in entries]
    assert ids[0] == "mem_same"
    assert ids[1] != "mem_same"
    assert len(set(ids)) == 2
    index = store.read_memory_index(account_id)
    assert set(index["index"]["entries"]) == set(ids)
    assert index["index"]["keywords"]["mond"] == [ids[0]]
    assert index["index"]["keywords"]["kaffee"] == [ids[1]]


def test_select_structured_account_memory_by_ids_preserves_order_and_habits(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_account_text(account_id, "User_Habbits_and_behave.md", "Ada mag knappe Antworten.")
    store.write_memory_entries(
        account_id,
        [
            {"id": "mem_sleep", "user_text": "Schlaf ist wichtig.", "bot_text": "Gemerkt.", "keywords": ["schlaf"]},
            {"id": "mem_plan", "user_text": "Morgens hilft eine kleine Struktur.", "bot_text": "Gemerkt.", "keywords": ["struktur"]},
        ],
    )

    selection = store.select_structured_memory_by_ids(account_id, ["mem_plan", "missing", "mem_sleep"], mark_accessed=False)

    assert selection.selected_ids == ("mem_plan", "mem_sleep")
    assert "Interne, admingepflegte Zusatzhinweise fuer diesen Account:" in selection.prompt_text
    assert "Ada mag knappe Antworten." in selection.prompt_text
    assert selection.prompt_text.index('"id": "mem_plan"') < selection.prompt_text.index('"id": "mem_sleep"')
    assert store.read_memory_entries_by_ids(account_id, ["mem_plan"])[0].get("access_count") is None


def test_structured_account_memory_index_health_reports_ok(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.append_structured_memory_entry(account_id, {"id": "mem_live", "user_text": "Mond", "bot_text": "Tee"})

    health = store.check_structured_memory_index(account_id)

    assert health.ok
    assert health.errors == ()


def test_structured_account_memory_index_health_accepts_empty_account(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))

    health = store.check_structured_memory_index(account_id)

    assert health.ok
    assert health.errors == ()


def test_structured_account_memory_index_health_rejects_empty_existing_json_artifact(tmp_path, monkeypatch):
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", raising=False)
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_POSTGRES_DSN", raising=False)
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.account_memory_vault.write_json(store.account_dir(account_id) / USER_MEMORY_INDEX_FILENAME, {})

    health = store.check_structured_memory_index(account_id)

    assert not health.ok
    assert "index scope is not account" in health.errors
    assert "index schema is not nested" in health.errors


def test_structured_memory_index_normalizes_legacy_id_whitespace(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.append_structured_memory_entry(
        account_id,
        {"id": "mem_legacy", "user_text": "Mond", "keywords": ["mond"]},
    )
    entries = store.read_memory_entries(account_id)
    entries[0]["id"] = " mem_legacy "
    store.write_memory_entries(account_id, entries)
    index = store.read_memory_index(account_id)
    nested_index = index["index"]
    nested_index["recent_ids"] = [" mem_legacy "]
    nested_index["keywords"] = {"mond": [" mem_legacy "]}
    nested_index["entries"] = {" mem_legacy ": nested_index["entries"]["mem_legacy"]}
    nested_index["semantic_cache"]["entries"] = {
        " mem_legacy ": nested_index["semantic_cache"]["entries"]["mem_legacy"]
    }
    store.write_memory_index(account_id, index)

    new_id = store.append_structured_memory_entry(
        account_id,
        {"id": "mem_new", "user_text": "Kaffee", "keywords": ["kaffee"]},
    )
    index = store.read_memory_index(account_id)["index"]

    assert new_id == "mem_new"
    assert set(index["entries"]) == {"mem_legacy", "mem_new"}
    assert index["recent_ids"][-2:] == ["mem_legacy", "mem_new"]
    assert set(index["semantic_cache"]["entries"]) == {"mem_legacy", "mem_new"}
    assert all(not memory_id.startswith(" ") for memory_id in index["entries"])

    store.mark_structured_memory_accessed(account_id, ["mem_legacy"])
    index = store.read_memory_index(account_id)["index"]

    assert index["accessed_ids"][-1] == "mem_legacy"
    assert " mem_legacy " not in index["entries"]


def test_structured_memory_index_health_normalizes_legacy_index_id_whitespace(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.append_structured_memory_entry(account_id, {"id": "mem_live", "user_text": "Mond"})
    index = store.read_memory_index(account_id)
    nested_index = index["index"]
    nested_index["recent_ids"] = [" mem_live "]
    nested_index["accessed_ids"] = [" mem_live "]
    nested_index["keywords"] = {"mond": [" mem_live "]}
    nested_index["entries"] = {" mem_live ": nested_index["entries"]["mem_live"]}
    for memory_type, values in nested_index["types"].items():
        nested_index["types"][memory_type] = [" mem_live "] if values else []
    nested_index["semantic_cache"]["entries"] = {
        " mem_live ": nested_index["semantic_cache"]["entries"]["mem_live"]
    }
    store.write_memory_index(account_id, index)

    health = store.check_structured_memory_index(account_id)

    assert health.ok
    assert health.errors == ()


def test_structured_account_memory_index_health_reports_database_decryption_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    first = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"a" * 32))
    account_id = first.resolve_or_create_account(telegram_identity_key(1))
    first.append_structured_memory_entry(account_id, {"id": "mem_live", "user_text": "Mond", "bot_text": "Tee"})
    second = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"b" * 32), create_dirs=False)

    health = second.check_structured_memory_index(account_id, require_resolvable=False)

    assert not health.ok
    error_text = "\n".join(health.errors)
    assert "database entries unreadable: skipped=1" in error_text
    assert "database index unreadable: SQLite account memory payload could not be decrypted" in error_text


def test_structured_account_memory_index_health_reports_broken_invariants(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_memory_entries(
        account_id,
        [
            {"id": "mem_live", "user_text": "Mond"},
            {"id": "mem_live", "user_text": "Kaffee"},
        ],
    )
    store.write_memory_index(
        account_id,
        {
            "scope": "legacy",
            "keywords": {"legacy": ["mem_live"]},
            "index": {
                "recent_ids": ["mem_live", "mem_live", "mem_missing_recent"],
                "accessed_ids": ["mem_live", "mem_live", "mem_missing_accessed"],
                "keywords": {"mond": ["mem_live", "mem_missing_keyword"]},
                "entries": {"mem_live": {}, "mem_missing_entry": {}},
                "graph": {"links": "invalid", "relations": []},
            },
        },
    )
    entries = store.read_memory_entries(account_id)
    entries[0]["related_ids"] = ["mem_missing_related"]
    entries[0]["supports"] = "invalid"
    entries[0]["relations"] = [{}]
    store.write_memory_entries(account_id, entries)

    health = store.check_structured_memory_index(account_id)

    assert not health.ok
    error_text = "\n".join(health.errors)
    assert "duplicate entry ids: mem_live" in error_text
    assert "index scope is not account" in error_text
    assert "legacy top-level keywords is present" in error_text
    assert "duplicate recent_ids: mem_live" in error_text
    assert "recent_ids missing entries: mem_missing_recent" in error_text
    assert "duplicate accessed_ids: mem_live" in error_text
    assert "accessed_ids missing entries: mem_missing_accessed" in error_text
    assert "keyword ids missing entries: mem_missing_keyword" in error_text
    assert "index.entries missing entries: mem_missing_entry" in error_text
    assert "graph.links is not an object" in error_text
    assert "related_ids missing entries: mem_missing_related" in error_text
    assert "entry mem_live supports is not a list" in error_text
    assert "entry mem_live relation type is empty" in error_text
    assert "entry mem_live relation target_id is empty" in error_text


def test_structured_account_memory_index_health_reports_malformed_entry_rows(tmp_path, monkeypatch):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    monkeypatch.setattr(store, "read_memory_entries", lambda _account_id: [{"id": ""}, "not-an-entry"])

    health = store.check_structured_memory_index(account_id)

    assert not health.ok
    error_text = "\n".join(health.errors)
    assert "entry 0 id is empty" in error_text
    assert "entry 1 is not an object" in error_text


def test_structured_account_memory_index_health_reports_stale_semantic_cache(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.append_structured_memory_entry(account_id, {"id": "mem_live", "user_text": "Mond", "bot_text": "Tee"})
    entries = store.read_memory_entries(account_id)
    entries[0]["user_text"] = "Kaffee"
    store.write_memory_entries(account_id, entries)

    health = store.check_structured_memory_index(account_id)

    assert not health.ok
    assert "semantic_cache entries stale: mem_live" in "\n".join(health.errors)


def test_structured_account_memory_index_health_reports_malformed_semantic_cache(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.append_structured_memory_entry(account_id, {"id": "mem_live", "user_text": "Mond", "bot_text": "Tee"})
    index = store.read_memory_index(account_id)
    index["index"]["semantic_cache"]["entries"]["mem_live"]["embedding"] = [1.0]
    index["index"]["semantic_cache"]["entries"]["mem_live"]["signature"] = "mond"
    store.write_memory_index(account_id, index)

    health = store.check_structured_memory_index(account_id)

    assert not health.ok
    assert "semantic_cache entries malformed: mem_live" in "\n".join(health.errors)


def test_structured_account_memory_index_health_reports_malformed_containers(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.append_structured_memory_entry(account_id, {"id": "mem_live", "user_text": "Mond", "bot_text": "Tee"})
    index = store.read_memory_index(account_id)
    index["index"]["graph"]["links"]["supports"] = "invalid"
    index["index"]["graph"]["links"]["related_ids"] = {"": [""]}
    index["index"]["graph"]["relations"] = [{}]
    index["index"]["semantic_cache"] = "invalid"
    store.write_memory_index(account_id, index)

    health = store.check_structured_memory_index(account_id)

    assert not health.ok
    error_text = "\n".join(health.errors)
    assert "graph.links.supports is not an object" in error_text
    assert "graph related_ids source is empty" in error_text
    assert "graph related_ids target is empty for" in error_text
    assert "graph relation source_id is empty" in error_text
    assert "graph relation target_id is empty" in error_text
    assert "graph relation type is empty" in error_text
    assert "index.semantic_cache is not an object" in error_text


def test_structured_account_memory_index_health_reports_empty_and_duplicate_ids(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.append_structured_memory_entry(account_id, {"id": "mem_live", "user_text": "Mond"})
    index = store.read_memory_index(account_id)
    nested_index = index["index"]
    nested_index["recent_ids"] = ["", "mem_live"]
    nested_index["accessed_ids"] = ["", "mem_live"]
    nested_index["keywords"] = {"mond": ["", "mem_live", " mem_live "]}
    nested_index["entries"] = {
        "mem_live": nested_index["entries"]["mem_live"],
        " mem_live ": nested_index["entries"]["mem_live"],
    }
    for memory_type, values in nested_index["types"].items():
        if values:
            nested_index["types"][memory_type] = ["mem_live", " mem_live "]
    semantic_entry = nested_index["semantic_cache"]["entries"]["mem_live"]
    nested_index["semantic_cache"]["entries"] = {
        "mem_live": semantic_entry,
        " mem_live ": semantic_entry,
        "": {},
    }
    store.write_memory_index(account_id, index)

    health = store.check_structured_memory_index(account_id)

    assert not health.ok
    error_text = "\n".join(health.errors)
    assert "index.recent_ids contains an empty id" in error_text
    assert "index.accessed_ids contains an empty id" in error_text
    assert "keyword mond contains an empty id" in error_text
    assert "duplicate keyword ids for mond: mem_live" in error_text
    assert "duplicate index.entries ids: mem_live" in error_text
    assert "duplicate index.types." in error_text
    assert "semantic_cache entries contain an empty id" in error_text
    assert "duplicate semantic_cache entry ids: mem_live" in error_text


def test_merge_rebuilds_structured_account_memory_index_from_merged_entries(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    target = store.resolve_or_create_account(telegram_identity_key(1))
    _, secret = store.register_account(target)
    source = store.resolve_or_create_account(signal_identity_key(source_uuid="abc"))
    store.write_memory_entries(
        target,
        [{"id": "mem_target", "user_text": "Telegram Mond.", "bot_text": "Gemerkt.", "channel": "telegram"}],
    )
    store.write_memory_entries(
        source,
        [{"id": "mem_source", "user_text": "Signal Kaffee.", "bot_text": "Gemerkt.", "channel": "signal"}],
    )
    store.write_memory_index(target, {"index": {"keywords": {"stale": ["mem_missing"]}, "recent_ids": ["mem_missing"], "entries": {"mem_missing": {}}}})
    store.write_memory_index(source, {"index": {"keywords": {"ghost": ["mem_ghost"]}, "recent_ids": ["mem_ghost"], "entries": {"mem_ghost": {}}}})

    store.link_identity(signal_identity_key(source_uuid="abc"), target, secret, display_label="Signal")

    index = store.read_memory_index(target)
    assert index["index"]["recent_ids"] == ["mem_target", "mem_source"]
    assert "stale" not in index["index"]["keywords"]
    assert "ghost" not in index["index"]["keywords"]
    assert index["index"]["keywords"]["mond"] == ["mem_target"]
    assert index["index"]["keywords"]["kaffee"] == ["mem_source"]
    assert set(index["index"]["entries"]) == {"mem_target", "mem_source"}
