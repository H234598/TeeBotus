from __future__ import annotations

import base64
import json
import logging
import re
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

from TeeBotus.runtime.accounts import (
    ACCOUNT_KEYRING_FILENAME,
    ACCOUNT_MEMORY_KEY_PURPOSE,
    CODEX_HISTORY_OUTBOX_FILENAME,
    INSTANCE_MAPPING_KEY_PURPOSE,
    INSTANCE_PEPPER_PURPOSE,
    EncryptedJsonVault,
    AccountStore,
    AccountStoreError,
    LLM_STATE_FILENAME,
    OPENAI_STATE_FILENAME,
    SecretToolInstanceSecretProvider,
    StaticSecretProvider,
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

    monkeypatch.setattr(provider_instance, "_secret_tool", lambda: "/usr/bin/secret-tool")

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls["command"] = command
        calls["timeout"] = kwargs.get("timeout")
        raise subprocess.TimeoutExpired(command, kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(AccountStoreError, match="timed out"):
        provider_instance._run(["lookup", "application", "TeeBotus"])

    assert calls["timeout"] == 0.25


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


def test_rotate_secret_invalidates_old_secret(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Bote_der_Wahrheit", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    _, first_secret = store.register_account(account_id)
    _, second_secret = store.rotate_secret(account_id)

    assert first_secret != second_secret
    assert not store.verify_secret(account_id, first_secret)
    assert store.verify_secret(account_id, second_secret)


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


def test_unlink_identity_marks_orphaned_when_last_identity_removed(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))

    unlinked_account = store.unlink_identity(telegram_identity_key(1))

    assert unlinked_account == account_id
    summary = store.account_summary(account_id)
    assert summary["status"] == "orphaned"
    assert summary["linked_identities"] == []


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


def test_encrypted_memory_with_wrong_instance_secret_does_not_fallback_to_envelope(tmp_path):
    first = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"a" * 32))
    account_id = first.resolve_or_create_account(telegram_identity_key(77))
    first.write_memory_index(account_id, {"keywords": {"tea": [1]}})

    second = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"b" * 32), create_dirs=False)

    with pytest.raises(AccountStoreError):
        second.read_memory_index(account_id)


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
    broken_primary_path = tmp_path / "broken-primary.sqlite3"
    broken_primary_path.mkdir()
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(broken_primary_path))
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH", str(fallback_path))
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider_instance)

    with caplog.at_level(logging.CRITICAL, logger="TeeBotus"):
        entries = store.read_memory_entries(account_id)

    assert entries == [{"id": "mem_backup", "user_text": "Backup"}]
    assert "ACCOUNT MEMORY PRIMARY DATABASE FAILED" in caplog.text


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


def test_account_memory_fallback_keeps_reading_clean_fallback_after_primary_repair_failure() -> None:
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
    second_read = backend.read_entries(account_id)

    assert first_read == [{"id": "mem_clean"}]
    assert second_read == [{"id": "mem_clean"}]
    assert account_id in backend.stale_fallback_entry_account_ids
    assert account_id not in backend._fallback_sync_failed_entries


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
            },
        },
    )
    entries = store.read_memory_entries(account_id)
    entries[0]["related_ids"] = ["mem_missing_related"]
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
    assert "related_ids missing entries: mem_missing_related" in error_text


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
