from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from TeeBotus.core.version_notifications import (
    _normalize_state,
    build_version_notification_text,
    github_has_version,
    github_repo_url,
    notify_recent_telegram_users_for_version,
    recent_telegram_recipients,
)
from TeeBotus.core.status import account_identity_health_lines, account_memory_index_health_lines, account_secret_health_lines, github_commit_history_url
from TeeBotus.runtime.accounts import (
    ACCOUNT_KEYRING_FILENAME,
    ACCOUNT_MEMORY_KEY_PURPOSE,
    INSTANCE_MAPPING_KEY_PURPOSE,
    INSTANCE_PEPPER_PURPOSE,
    INSTANCE_STATE_ACCOUNT_ID,
    AccountStore,
    AccountStoreError,
    SecretToolInstanceSecretProvider,
    StaticSecretProvider,
    _instance_secret_fingerprint,
)
from TeeBotus.runtime.sqlite_memory import SQLiteAccountMemoryBackend, SQLiteMemoryConfig


def _store(tmp_path: Path) -> AccountStore:
    return AccountStore(
        tmp_path / "instances" / "Demo" / "data" / "accounts",
        "Demo",
        secret_provider=StaticSecretProvider(b"x" * 32),
    )


def _make_instance(tmp_path: Path) -> None:
    instance_dir = tmp_path / "instances" / "Demo"
    instance_dir.mkdir(parents=True, exist_ok=True)
    (instance_dir / "Bot_Verhalten.md").write_text("", encoding="utf-8")


class FakeSecretStatusProvider:
    def __init__(self, present: set[str] | None = None, errors: dict[str, str] | None = None, **_kwargs: object) -> None:
        self.present = set(present or ())
        self.errors = dict(errors or {})

    def has_secret(self, _instance_name: str, purpose: str) -> bool:
        if purpose in self.errors:
            raise AccountStoreError(self.errors[purpose])
        return purpose in self.present

    def get_secret(self, _instance_name: str, purpose: str) -> bytes:
        if not self.has_secret(_instance_name, purpose):
            raise AccountStoreError(f"instance secret is missing for purpose={purpose}")
        return b"x" * 32


class FlakyRequiredSecretProvider:
    def has_secret(self, _instance_name: str, purpose: str) -> bool:
        return purpose == INSTANCE_MAPPING_KEY_PURPOSE

    def get_secret(self, _instance_name: str, purpose: str) -> bytes:
        if purpose in {INSTANCE_MAPPING_KEY_PURPOSE, ACCOUNT_MEMORY_KEY_PURPOSE}:
            return b"x" * 32
        raise AccountStoreError(f"instance secret is missing for purpose={purpose}")


def test_account_identity_health_warns_when_signal_runtime_has_no_linked_identity(tmp_path: Path, monkeypatch) -> None:
    _make_instance(tmp_path)
    monkeypatch.setattr("TeeBotus.core.status.SecretToolInstanceSecretProvider", lambda **_kwargs: StaticSecretProvider(b"x" * 32))
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    env = {
        "TELEGRAM_BOT_TOKEN_DEMO": "telegram-token",
        "SIGNAL_BOT_SERVICE_DEMO": "127.0.0.1:8080",
        "SIGNAL_BOT_PHONE_NUMBER_DEMO": "+491",
    }

    lines = account_identity_health_lines(instance_name="Demo", project_root=tmp_path, env=env)

    assert lines[0] == (
        "account_identity=Demo status=warning identity_warnings=1 "
        "runtime_slots=signal:1,telegram:1 identities=telegram:1"
    )
    assert any(
        "account_identity_warning=Demo code=runtime_channel_without_identity channel=signal" in line
        and "configured_runtime_slots=1" in line
        and "runtime_labels=signal:1" in line
        and "identity_channels=telegram:1" in line
        and "action=First run /register or /rotate_secret in an already linked private chat" in line
        and "then open a private signal chat and link the existing account with /login <account_id> <secret>" in line
        and "separate account until the user links it" in line
        for line in lines
    )


def test_account_identity_health_does_not_require_memory_secret(tmp_path: Path, monkeypatch) -> None:
    _make_instance(tmp_path)
    store = _store(tmp_path)
    account_id = store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    store.write_llm_state(account_id, {"previous_response_id": "resp_1"})
    provider = SecretToolInstanceSecretProvider(create_if_missing=False)

    def lookup(_instance: str, purpose: str) -> bytes | None:
        if purpose == INSTANCE_MAPPING_KEY_PURPOSE:
            return b"x" * 32
        if purpose == ACCOUNT_MEMORY_KEY_PURPOSE:
            return None
        raise AssertionError(f"unexpected secret purpose requested: {purpose}")

    monkeypatch.setattr(provider, "_lookup", lookup)
    monkeypatch.setattr("TeeBotus.core.status.SecretToolInstanceSecretProvider", lambda **_kwargs: provider)
    env = {
        "TELEGRAM_BOT_TOKEN_DEMO": "telegram-token",
        "SIGNAL_BOT_SERVICE_DEMO": "127.0.0.1:8080",
        "SIGNAL_BOT_PHONE_NUMBER_DEMO": "+491",
    }

    lines = account_identity_health_lines(instance_name="Demo", project_root=tmp_path, env=env)

    assert lines[0] == (
        "account_identity=Demo status=warning identity_warnings=1 "
        "runtime_slots=signal:1,telegram:1 identities=telegram:1"
    )


def test_account_identity_health_is_ok_when_signal_identity_is_linked(tmp_path: Path, monkeypatch) -> None:
    _make_instance(tmp_path)
    monkeypatch.setattr("TeeBotus.core.status.SecretToolInstanceSecretProvider", lambda **_kwargs: StaticSecretProvider(b"x" * 32))
    store = _store(tmp_path)
    account_id = store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    _, secret = store.register_account(account_id)
    store.link_identity("signal:uuid:abc", account_id, secret)
    env = {
        "TELEGRAM_BOT_TOKEN_DEMO": "telegram-token",
        "SIGNAL_BOT_SERVICE_DEMO": "127.0.0.1:8080",
        "SIGNAL_BOT_PHONE_NUMBER_DEMO": "+491",
    }

    lines = account_identity_health_lines(instance_name="Demo", project_root=tmp_path, env=env)

    assert lines == [
        "account_identity=Demo status=ok identity_warnings=0 runtime_slots=signal:1,telegram:1 identities=signal:1,telegram:1"
    ]


def test_account_memory_index_health_uses_read_only_secret_provider(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    provider_kwargs: list[dict[str, object]] = []

    def fake_secret_provider(**kwargs: object) -> StaticSecretProvider:
        provider_kwargs.append(dict(kwargs))
        return StaticSecretProvider(b"x" * 32)

    monkeypatch.setattr("TeeBotus.core.status.SecretToolInstanceSecretProvider", fake_secret_provider)

    account_memory_index_health_lines(instance_name="Demo", project_root=tmp_path)

    assert provider_kwargs
    assert all(kwargs.get("create_if_missing") is False for kwargs in provider_kwargs)


def test_account_secret_health_reports_missing_required_memory_secret(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    store = _store(tmp_path)
    account_id = store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    store.write_memory_entries(account_id, [{"id": "mem_live", "user_text": "Mond"}])
    monkeypatch.setattr(
        "TeeBotus.core.status.SecretToolInstanceSecretProvider",
        lambda **kwargs: FakeSecretStatusProvider({INSTANCE_MAPPING_KEY_PURPOSE}, **kwargs),
    )

    lines = account_secret_health_lines(instance_name="Demo", project_root=tmp_path)

    assert lines == [
        "account_crypto=Demo status=broken mapping=present memory=missing_required pepper=not_required keyring=broken error=keyring:missing_manifest; memory:missing"
    ]


def test_account_secret_health_confirms_required_secret_before_reporting_missing(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    account_id = store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    store.write_llm_state(account_id, {"previous_response_id": "resp_1"})
    accounts_root = tmp_path / "instances" / "Demo" / "data" / "accounts"
    (accounts_root / ACCOUNT_KEYRING_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "instance": "Demo",
                "purposes": {
                    INSTANCE_MAPPING_KEY_PURPOSE: {
                        "algorithm": "HMAC-SHA256",
                        "fingerprint": _instance_secret_fingerprint("Demo", INSTANCE_MAPPING_KEY_PURPOSE, b"x" * 32),
                        "purpose": INSTANCE_MAPPING_KEY_PURPOSE,
                    },
                    ACCOUNT_MEMORY_KEY_PURPOSE: {
                        "algorithm": "HMAC-SHA256",
                        "fingerprint": _instance_secret_fingerprint("Demo", ACCOUNT_MEMORY_KEY_PURPOSE, b"x" * 32),
                        "purpose": ACCOUNT_MEMORY_KEY_PURPOSE,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("TeeBotus.core.status.SecretToolInstanceSecretProvider", lambda **_kwargs: FlakyRequiredSecretProvider())

    lines = account_secret_health_lines(instance_name="Demo", project_root=tmp_path)

    assert lines == [
        "account_crypto=Demo status=ok mapping=present memory=present pepper=not_required keyring=ok"
    ]


def test_account_secret_health_does_not_require_pepper_for_empty_secret_container(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    store.vault.write_json(store.secrets_path, {})
    monkeypatch.setattr(
        "TeeBotus.core.status.SecretToolInstanceSecretProvider",
        lambda **kwargs: FakeSecretStatusProvider({INSTANCE_MAPPING_KEY_PURPOSE}, **kwargs),
    )

    lines = account_secret_health_lines(instance_name="Demo", project_root=tmp_path)

    assert lines == [
        "account_crypto=Demo status=broken mapping=present memory=not_required pepper=not_required keyring=broken error=keyring:missing_manifest"
    ]


def test_account_secret_health_reports_missing_required_pepper(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    account_id = store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    store.register_account(account_id)
    monkeypatch.setattr(
        "TeeBotus.core.status.SecretToolInstanceSecretProvider",
        lambda **kwargs: FakeSecretStatusProvider({INSTANCE_MAPPING_KEY_PURPOSE}, **kwargs),
    )

    lines = account_secret_health_lines(instance_name="Demo", project_root=tmp_path)

    assert lines == [
        "account_crypto=Demo status=broken mapping=present memory=not_required pepper=missing_required keyring=broken error=keyring:missing_manifest; pepper:missing"
    ]


def test_account_secret_health_reports_lookup_error_without_leaking_secret(tmp_path: Path, monkeypatch) -> None:
    _make_instance(tmp_path)
    accounts_root = tmp_path / "instances" / "Demo" / "data" / "accounts"
    accounts_root.mkdir(parents=True)
    leaked = "sk-" + "A" * 24
    monkeypatch.setattr(
        "TeeBotus.core.status.SecretToolInstanceSecretProvider",
        lambda **kwargs: FakeSecretStatusProvider(errors={INSTANCE_MAPPING_KEY_PURPOSE: f"secret-tool lookup failed {leaked}"}, **kwargs),
    )

    lines = account_secret_health_lines(instance_name="Demo", project_root=tmp_path)

    assert lines == [
        "account_crypto=Demo status=broken mapping=error memory=not_required pepper=not_required keyring=not_required error=mapping:AccountStoreError: secret-tool lookup failed sk-<redacted>"
    ]
    assert leaked not in lines[0]


def test_account_secret_health_reports_keyring_mismatch_without_leaking_secret(tmp_path: Path, monkeypatch) -> None:
    _make_instance(tmp_path)
    accounts_root = tmp_path / "instances" / "Demo" / "data" / "accounts"
    accounts_root.mkdir(parents=True)
    wrong_fingerprint = _instance_secret_fingerprint("Demo", INSTANCE_MAPPING_KEY_PURPOSE, b"y" * 32)
    (accounts_root / ACCOUNT_KEYRING_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "instance": "Demo",
                "purposes": {
                    INSTANCE_MAPPING_KEY_PURPOSE: {
                        "algorithm": "HMAC-SHA256",
                        "fingerprint": wrong_fingerprint,
                        "purpose": INSTANCE_MAPPING_KEY_PURPOSE,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "TeeBotus.core.status.SecretToolInstanceSecretProvider",
        lambda **kwargs: FakeSecretStatusProvider({INSTANCE_MAPPING_KEY_PURPOSE}, **kwargs),
    )

    lines = account_secret_health_lines(instance_name="Demo", project_root=tmp_path)

    assert lines == [
        "account_crypto=Demo status=broken mapping=present memory=not_required pepper=not_required keyring=broken error=keyring:account-identity-mapping-key:mismatch"
    ]
    assert wrong_fingerprint not in lines[0]


def test_account_secret_health_reports_partial_keyring_for_required_memory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    store = _store(tmp_path)
    account_id = store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    store.write_memory_entries(account_id, [{"id": "mem_live", "user_text": "Mond"}])
    accounts_root = tmp_path / "instances" / "Demo" / "data" / "accounts"
    mapping_fingerprint = _instance_secret_fingerprint("Demo", INSTANCE_MAPPING_KEY_PURPOSE, b"x" * 32)
    (accounts_root / ACCOUNT_KEYRING_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "instance": "Demo",
                "purposes": {
                    INSTANCE_MAPPING_KEY_PURPOSE: {
                        "algorithm": "HMAC-SHA256",
                        "fingerprint": mapping_fingerprint,
                        "purpose": INSTANCE_MAPPING_KEY_PURPOSE,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "TeeBotus.core.status.SecretToolInstanceSecretProvider",
        lambda **kwargs: FakeSecretStatusProvider({INSTANCE_MAPPING_KEY_PURPOSE, ACCOUNT_MEMORY_KEY_PURPOSE}, **kwargs),
    )

    lines = account_secret_health_lines(instance_name="Demo", project_root=tmp_path)

    assert lines == [
        "account_crypto=Demo status=broken mapping=present memory=present pepper=not_required keyring=partial error=keyring:missing_required_purpose:account-structured-memory-key"
    ]
    assert mapping_fingerprint not in lines[0]


def test_recent_telegram_recipients_filters_last_seen_window(tmp_path: Path) -> None:
    store = _store(tmp_path)
    fresh = store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    stale = store.resolve_or_create_account("telegram:user:222", display_label="Stale")
    identities = store._load_identities()
    identities["telegram:user:111"]["last_seen_at"] = "2026-06-14T10:00:00+00:00"
    identities["telegram:user:222"]["last_seen_at"] = "2026-06-01T10:00:00+00:00"
    store._save_identities(identities)

    recipients = recent_telegram_recipients(
        store,
        instance_name="Demo",
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert [recipient.chat_id for recipient in recipients] == [111]
    assert recipients[0].account_id == fresh
    assert stale != fresh


def test_recent_telegram_recipients_can_filter_by_adapter_slot(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Slot1")
    store.resolve_or_create_account("telegram:user:222", display_label="Slot2")
    store.update_identity_route("telegram:user:111", channel="telegram", chat_id="111", chat_type="private", adapter_slot=1)
    store.update_identity_route("telegram:user:222", channel="telegram", chat_id="222", chat_type="private", adapter_slot=2)

    recipients = recent_telegram_recipients(
        store,
        instance_name="Demo",
        adapter_slot=2,
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert [(recipient.chat_id, recipient.adapter_slot) for recipient in recipients] == [(222, 2)]


def test_recent_telegram_recipients_ignores_invalid_adapter_slot_filter(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Fresh")

    recipients = recent_telegram_recipients(
        store,
        instance_name="Demo",
        adapter_slot="telegram:broken",  # type: ignore[arg-type]
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert recipients == []


def test_recent_telegram_recipients_skips_non_private_chat_routes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Private")
    store.resolve_or_create_account("telegram:user:222", display_label="Group")
    store.resolve_or_create_account("telegram:user:333", display_label="Legacy")
    store.update_identity_route("telegram:user:111", channel="telegram", chat_id="111", chat_type="private", adapter_slot=1)
    store.update_identity_route("telegram:user:222", channel="telegram", chat_id="222", chat_type="group", adapter_slot=1)

    recipients = recent_telegram_recipients(
        store,
        instance_name="Demo",
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert [(recipient.identity_key, recipient.chat_id) for recipient in recipients] == [
        ("telegram:user:111", 111),
        ("telegram:user:333", 333),
    ]


def test_recent_telegram_recipients_accepts_routed_telegram_fallback_identity(tmp_path: Path) -> None:
    store = _store(tmp_path)
    account_id = store.resolve_or_create_account("telegram:username:ada", display_label="Ada")
    store.update_identity_route("telegram:username:ada", channel="telegram", chat_id="111", chat_type="private", adapter_slot=1)

    recipients = recent_telegram_recipients(
        store,
        instance_name="Demo",
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert [(recipient.identity_key, recipient.account_id, recipient.chat_id) for recipient in recipients] == [
        ("telegram:username:ada", account_id, 111)
    ]


def test_recent_telegram_recipients_deduplicates_same_account_route(tmp_path: Path) -> None:
    store = _store(tmp_path)
    account_id = store.resolve_or_create_account("telegram:user:111", display_label="Ada")
    identities = store._load_identities()
    username_payload = dict(identities["telegram:user:111"])
    username_payload["identity_key"] = "telegram:username:ada"
    identities["telegram:username:ada"] = username_payload
    store._save_identities(identities)
    store.update_identity_route("telegram:user:111", channel="telegram", chat_id="111", chat_type="private", adapter_slot=1)
    store.update_identity_route("telegram:username:ada", channel="telegram", chat_id="111", chat_type="private", adapter_slot=1)

    recipients = recent_telegram_recipients(
        store,
        instance_name="Demo",
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert [(recipient.identity_key, recipient.account_id, recipient.chat_id) for recipient in recipients] == [
        ("telegram:user:111", account_id, 111)
    ]


def test_recent_telegram_recipients_deduplicates_account_slot_to_newest_route(tmp_path: Path) -> None:
    store = _store(tmp_path)
    account_id = store.resolve_or_create_account("telegram:user:111", display_label="Ada")
    identities = store._load_identities()
    user_payload = dict(identities["telegram:user:111"])
    user_payload["last_seen_at"] = "2026-06-13T12:00:00+00:00"
    user_payload["last_route"] = {
        "channel": "telegram",
        "chat_id": "111",
        "chat_type": "private",
        "adapter_slot": 1,
    }
    username_payload = dict(user_payload)
    username_payload["identity_key"] = "telegram:username:ada"
    username_payload["last_seen_at"] = "2026-06-14T11:59:00+00:00"
    username_payload["last_route"] = {
        "channel": "telegram",
        "chat_id": "222",
        "chat_type": "private",
        "adapter_slot": 1,
    }
    identities["telegram:user:111"] = user_payload
    identities["telegram:username:ada"] = username_payload
    store._save_identities(identities)

    recipients = recent_telegram_recipients(
        store,
        instance_name="Demo",
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert [(recipient.identity_key, recipient.account_id, recipient.chat_id) for recipient in recipients] == [
        ("telegram:username:ada", account_id, 222)
    ]


def test_notify_recent_telegram_users_for_version_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    account_id = store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    store.write_memory_index(account_id, {"memories": [{"text": "youtube transkript"}]})
    sent: list[tuple[int, str]] = []

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, text: sent.append((chat_id, text)),
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )
    count_again = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, text: sent.append((chat_id, text)),
        now=datetime(2026, 6, 14, 12, 1, tzinfo=timezone.utc),
    )

    assert count == 1
    assert count_again == 0
    assert len(sent) == 1
    assert sent[0][0] == 111
    assert "Version 1.0.3" in sent[0][1]
    assert "https://github.com/H234598/TeeBotus" in sent[0][1]
    assert "ffmpeg" in sent[0][1]


def test_notify_recent_telegram_users_normalizes_version_key(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    sent: list[tuple[int, str]] = []

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, text: sent.append((chat_id, text)),
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )
    count_again = notify_recent_telegram_users_for_version(
        version="v1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, text: sent.append((chat_id, text)),
        now=datetime(2026, 6, 14, 12, 1, tzinfo=timezone.utc),
    )
    state = json.loads((tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json").read_text(encoding="utf-8"))

    assert count == 1
    assert count_again == 0
    assert len(sent) == 1
    assert list(state["versions"]) == ["1.0.3"]
    assert "Version 1.0.3" in sent[0][1]


def test_notify_recent_telegram_users_skips_empty_normalized_version(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    state_path = tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json"
    sent: list[int] = []
    skips: list[str] = []

    count = notify_recent_telegram_users_for_version(
        version="v",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, _text: sent.append(chat_id),
        on_skip=skips.append,
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert count == 0
    assert sent == []
    assert skips == ["version is empty"]
    assert not state_path.exists()


def test_notify_recent_telegram_users_drops_empty_legacy_version_keys(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    state_path = tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "versions": {
                    "": {"sent_identities": ["telegram:user:999"], "failed_identities": {}},
                    "v": {"sent_identities": ["telegram:user:888"], "failed_identities": {}},
                }
            }
        ),
        encoding="utf-8",
    )
    sent: list[int] = []

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, _text: sent.append(chat_id),
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert count == 1
    assert sent == [111]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert list(state["versions"]) == ["1.0.3"]
    assert state["versions"]["1.0.3"]["sent_identities"] == ["telegram:user:111"]


def test_version_notification_state_normalization_prefers_exact_version_metadata() -> None:
    state = _normalize_state(
        {
            "versions": {
                "1.0.3": {
                    "sent_identities": ["telegram:user:111"],
                    "failed_identities": {},
                    "updated_at": "2026-06-14T12:00:00+00:00",
                },
                "v1.0.3": {
                    "sent_identities": ["telegram:user:222"],
                    "failed_identities": {},
                    "updated_at": "2026-06-14T11:00:00+00:00",
                },
            }
        }
    )

    assert list(state["versions"]) == ["1.0.3"]
    assert state["versions"]["1.0.3"]["sent_identities"] == ["telegram:user:111", "telegram:user:222"]
    assert state["versions"]["1.0.3"]["updated_at"] == "2026-06-14T12:00:00+00:00"


def test_version_notification_state_normalization_cleans_nested_identity_state() -> None:
    state = _normalize_state(
        {
            "versions": {
                "1.0.3": {
                    "sent_identities": [" telegram:user:111 ", "", 123],
                    "failed_identities": {
                        " telegram:user:222 ": {
                            "account_id": "b" * 128,
                            "adapter_slot": 1,
                            "chat_id": 222,
                        },
                        "": {"chat_id": 999},
                        123: {"chat_id": 123},
                    },
                }
            }
        }
    )

    version_state = state["versions"]["1.0.3"]
    assert version_state["sent_identities"] == ["telegram:user:111"]
    assert list(version_state["failed_identities"]) == ["telegram:user:222"]


def test_version_notification_state_normalization_drops_malformed_failure_payloads() -> None:
    state = _normalize_state(
        {
            "versions": {
                "1.0.3": {
                    "failed_identities": {
                        "telegram:user:111": "broken",
                        "telegram:user:222": {"reason": "legacy route missing"},
                    }
                }
            }
        }
    )

    failures = state["versions"]["1.0.3"]["failed_identities"]
    assert list(failures) == ["telegram:user:222"]
    assert failures["telegram:user:222"]["reason"] == "legacy route missing"


def test_version_notification_state_normalization_keeps_complete_failure_payload() -> None:
    state = _normalize_state(
        {
            "versions": {
                "v1.0.3": {
                    "failed_identities": {
                        "telegram:user:111": {
                            "adapter_slot": 1,
                            "chat_id": 111,
                            "reason": "chat not found",
                        }
                    }
                },
                "1.0.3": {
                    "failed_identities": {
                        "telegram:user:111": {
                            "reason": "legacy row without route",
                        }
                    }
                },
            }
        }
    )

    failure = state["versions"]["1.0.3"]["failed_identities"]["telegram:user:111"]
    assert failure["chat_id"] == 111
    assert failure["adapter_slot"] == 1
    assert failure["reason"] == "chat not found"


def test_notify_recent_telegram_users_migrates_legacy_prefixed_version_key(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    state_path = tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "versions": {
                    "v1.0.3": {
                        "sent_identities": ["telegram:user:111"],
                        "failed_identities": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    sent: list[int] = []

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, text: sent.append(chat_id),
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert count == 0
    assert sent == []
    assert list(state["versions"]) == ["1.0.3"]
    assert state["versions"]["1.0.3"]["sent_identities"] == ["telegram:user:111"]


def test_notify_recent_telegram_users_continues_after_send_error(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Broken")
    store.resolve_or_create_account("telegram:user:222", display_label="Working")
    sent: list[int] = []
    errors: list[str] = []

    def send_message(chat_id: int, text: str) -> None:
        if chat_id == 111:
            raise RuntimeError("chat not found")
        sent.append(chat_id)

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=send_message,
        on_error=lambda recipient, exc: errors.append(f"{recipient.identity_key}: {exc}"),
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert count == 1
    assert sent == [222]
    assert errors == ["telegram:user:111: chat not found"]


def test_notify_recent_telegram_users_does_not_retry_permanent_delivery_error(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Broken")
    attempts: list[int] = []

    def send_message(chat_id: int, text: str) -> None:
        attempts.append(chat_id)
        raise RuntimeError('Telegram HTTP error 400: {"description":"Bad Request: chat not found"}')

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=send_message,
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )
    count_again = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=send_message,
        now=datetime(2026, 6, 14, 12, 1, tzinfo=timezone.utc),
    )
    state = json.loads((tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json").read_text(encoding="utf-8"))

    assert count == 0
    assert count_again == 0
    assert attempts == [111]
    failed = state["versions"]["1.0.3"]["failed_identities"]["telegram:user:111"]
    assert failed["account_id"] == store.get_account_for_identity("telegram:user:111")
    assert failed["chat_id"] == 111
    assert failed["adapter_slot"] == 1
    assert "chat not found" in failed["reason"]


def test_notify_recent_telegram_users_normalizes_sent_identity_state(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    state_path = tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"versions": {"1.0.3": {"sent_identities": [" telegram:user:111 "], "failed_identities": {}}}}),
        encoding="utf-8",
    )
    sent: list[int] = []

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, text: sent.append(chat_id),
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert count == 0
    assert sent == []
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["versions"]["1.0.3"]["sent_identities"] == ["telegram:user:111"]


def test_notify_recent_telegram_users_normalizes_failed_identity_keys(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    state_path = tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "versions": {
                    "1.0.3": {
                        "sent_identities": [],
                        "failed_identities": {
                            " telegram:user:111 ": {
                                "adapter_slot": 1,
                                "chat_id": 111,
                                "reason": "chat not found",
                            }
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    sent: list[int] = []

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, text: sent.append(chat_id),
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert count == 0
    assert sent == []
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert list(state["versions"]["1.0.3"]["failed_identities"]) == ["telegram:user:111"]


def test_notify_recent_telegram_users_stores_state_in_sqlite_when_available(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "memory.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    state_path = tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "versions": {
                    "1.0.3": {
                        "sent_identities": ["telegram:user:111"],
                        "failed_identities": {},
                        "updated_at": "2026-06-14T11:59:00+00:00",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    sent: list[int] = []

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, text: sent.append(chat_id),
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert count == 0
    assert sent == []
    assert not state_path.exists()
    state = store.read_instance_json_state("Version_Notifications.json", "version_notifications", {"versions": {}})
    assert state["versions"]["1.0.3"]["sent_identities"] == ["telegram:user:111"]
    raw_db = sqlite_path.read_bytes()
    assert b"telegram:user:111" not in raw_db


def test_notify_recent_telegram_users_migrates_legacy_state_to_sqlite_before_github_tag_gate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sqlite_path = tmp_path / "memory.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    monkeypatch.setattr("TeeBotus.core.version_notifications.github_has_version", lambda _repo_root, _version: False)
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    state_path = tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "versions": {
                    "1.0.3": {
                        "sent_identities": ["telegram:user:111"],
                        "failed_identities": {},
                        "updated_at": "2026-06-14T11:59:00+00:00",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    sent: list[int] = []
    skips: list[str] = []

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, _text: sent.append(chat_id),
        repo_root=tmp_path,
        repo_url="https://github.com/example/project",
        on_skip=skips.append,
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert count == 0
    assert sent == []
    assert skips == ["GitHub tag v1.0.3 not found on remote"]
    assert not state_path.exists()
    state = store.read_instance_json_state("Version_Notifications.json", "version_notifications", {"versions": {}})
    assert state["versions"]["1.0.3"]["sent_identities"] == ["telegram:user:111"]
    raw_db = sqlite_path.read_bytes()
    assert b"telegram:user:111" not in raw_db


def test_notify_recent_telegram_users_ignores_malformed_plaintext_legacy_state_when_sqlite_is_available(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sqlite_path = tmp_path / "memory.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    state_path = tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{not-json", encoding="utf-8")
    sent: list[int] = []

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, text: sent.append(chat_id),
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert count == 1
    assert sent == [111]
    assert not state_path.exists()
    state = store.read_instance_json_state("Version_Notifications.json", "version_notifications", {"versions": {}})
    assert state["versions"]["1.0.3"]["sent_identities"] == ["telegram:user:111"]


def test_notify_recent_telegram_users_merges_sqlite_and_legacy_sent_identities(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "memory.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    store = _store(tmp_path)
    for sender_id in ("111", "222", "333"):
        store.resolve_or_create_account(f"telegram:user:{sender_id}", display_label=f"User {sender_id}")
    store.write_instance_json_state(
        "Version_Notifications.json",
        "version_notifications",
        {
            "versions": {
                "1.0.3": {
                    "sent_identities": ["telegram:user:222"],
                    "failed_identities": {},
                    "updated_at": "2026-06-14T11:58:00+00:00",
                }
            }
        },
    )
    state_path = tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "versions": {
                    "1.0.3": {
                        "sent_identities": ["telegram:user:111"],
                        "failed_identities": {},
                        "updated_at": "2026-06-14T11:59:00+00:00",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    sent: list[int] = []

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, text: sent.append(chat_id),
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert count == 1
    assert sent == [333]
    state = store.read_instance_json_state("Version_Notifications.json", "version_notifications", {"versions": {}})
    assert state["versions"]["1.0.3"]["sent_identities"] == [
        "telegram:user:111",
        "telegram:user:222",
        "telegram:user:333",
    ]


def test_notify_recent_telegram_users_merges_multiple_sqlite_state_rows(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "memory.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    store = _store(tmp_path)
    for sender_id in ("111", "222", "333"):
        store.resolve_or_create_account(f"telegram:user:{sender_id}", display_label=f"User {sender_id}")
    backend = store.account_memory_backend
    assert backend is not None
    backend.write_collection(
        INSTANCE_STATE_ACCOUNT_ID,
        "version_notifications",
        [
            {
                "versions": {
                    "1.0.3": {
                        "sent_identities": ["telegram:user:111"],
                        "failed_identities": {},
                        "updated_at": "2026-06-14T11:58:00+00:00",
                    }
                }
            },
            {
                "versions": {
                    "1.0.3": {
                        "sent_identities": ["telegram:user:222"],
                        "failed_identities": {},
                        "updated_at": "2026-06-14T11:59:00+00:00",
                    }
                }
            },
        ],
    )
    sent: list[int] = []

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, text: sent.append(chat_id),
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert count == 1
    assert sent == [333]
    state = store.read_instance_json_state("Version_Notifications.json", "version_notifications", {"versions": {}})
    assert state["versions"]["1.0.3"]["sent_identities"] == [
        "telegram:user:111",
        "telegram:user:222",
        "telegram:user:333",
    ]
    compacted = backend.read_collection(INSTANCE_STATE_ACCOUNT_ID, "version_notifications")
    assert compacted == [state]


def test_notify_recent_telegram_users_records_permanent_error_when_on_error_fails(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Broken")
    attempts: list[int] = []

    def send_message(chat_id: int, text: str) -> None:
        attempts.append(chat_id)
        raise RuntimeError('Telegram HTTP error 400: {"description":"Bad Request: chat not found"}')

    def broken_error_hook(_recipient, _exc) -> None:
        raise RuntimeError("logger failed")

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=send_message,
        on_error=broken_error_hook,
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )
    count_again = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=send_message,
        on_error=broken_error_hook,
        now=datetime(2026, 6, 14, 12, 1, tzinfo=timezone.utc),
    )
    state = json.loads((tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json").read_text(encoding="utf-8"))

    assert count == 0
    assert count_again == 0
    assert attempts == [111]
    assert "telegram:user:111" in state["versions"]["1.0.3"]["failed_identities"]


def test_notify_recent_telegram_users_retries_transient_delivery_error(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Flaky")
    attempts: list[int] = []

    def send_message(chat_id: int, text: str) -> None:
        attempts.append(chat_id)
        raise RuntimeError("temporary network timeout")

    notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=send_message,
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )
    notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=send_message,
        now=datetime(2026, 6, 14, 12, 1, tzinfo=timezone.utc),
    )
    state = json.loads((tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json").read_text(encoding="utf-8"))

    assert attempts == [111, 111]
    assert state["versions"]["1.0.3"]["failed_identities"] == {}


def test_notify_recent_telegram_users_retries_when_failed_route_changes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Moved")
    attempts: list[int] = []
    sent: list[int] = []

    def send_message(chat_id: int, text: str) -> None:
        attempts.append(chat_id)
        if chat_id == 111:
            raise RuntimeError('Telegram HTTP error 400: {"description":"Bad Request: chat not found"}')
        sent.append(chat_id)

    notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=send_message,
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )
    store.update_identity_route("telegram:user:111", channel="telegram", chat_id="222", chat_type="private", adapter_slot=2)
    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=send_message,
        adapter_slot=2,
        now=datetime(2026, 6, 14, 12, 1, tzinfo=timezone.utc),
    )

    assert attempts == [111, 222]
    assert sent == [222]
    assert count == 1
    state = json.loads((tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json").read_text(encoding="utf-8"))
    assert state["versions"]["1.0.3"]["failed_identities"] == {}


def test_notify_recent_telegram_users_clears_alias_failure_after_successful_delivery(tmp_path: Path) -> None:
    store = _store(tmp_path)
    account_id = store.resolve_or_create_account("telegram:user:111", display_label="Moved")
    identities = store._load_identities()
    username_payload = dict(identities["telegram:user:111"])
    username_payload["identity_key"] = "telegram:username:ada"
    username_payload["account_id"] = account_id
    identities["telegram:username:ada"] = username_payload
    store._save_identities(identities)
    store.update_identity_route("telegram:user:111", channel="telegram", chat_id="222", chat_type="private", adapter_slot=2)
    store.update_identity_route("telegram:username:ada", channel="telegram", chat_id="111", chat_type="private", adapter_slot=1)
    state_path = tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "versions": {
                    "1.0.3": {
                        "sent_identities": [],
                        "failed_identities": {
                            "telegram:username:ada": {
                                "adapter_slot": 1,
                                "chat_id": 111,
                                "reason": "chat not found",
                            }
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    sent: list[int] = []

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, text: sent.append(chat_id),
        adapter_slot=2,
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert count == 1
    assert sent == [222]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["versions"]["1.0.3"]["failed_identities"] == {}


def test_notify_recent_telegram_users_skips_failed_route_across_identity_alias(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Moved")
    state_path = tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "versions": {
                    "1.0.3": {
                        "sent_identities": [],
                        "failed_identities": {
                            "telegram:username:ada": {
                                "adapter_slot": 1,
                                "chat_id": 111,
                                "reason": "chat not found",
                            }
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    attempts: list[int] = []

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, text: attempts.append(chat_id),
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert count == 0
    assert attempts == []
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "telegram:username:ada" in state["versions"]["1.0.3"]["failed_identities"]


def test_notify_recent_telegram_users_does_not_skip_failure_from_different_account(tmp_path: Path) -> None:
    store = _store(tmp_path)
    account_id = store.resolve_or_create_account("telegram:user:111", display_label="Ada")
    other_account_id = "b" * 128
    state_path = tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "versions": {
                    "1.0.3": {
                        "sent_identities": [],
                        "failed_identities": {
                            "telegram:user:222": {
                                "account_id": other_account_id,
                                "adapter_slot": 1,
                                "chat_id": 111,
                                "reason": "chat not found",
                            }
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    sent: list[int] = []

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, _text: sent.append(chat_id),
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert count == 1
    assert sent == [111]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["versions"]["1.0.3"]["sent_identities"] == ["telegram:user:111"]
    assert state["versions"]["1.0.3"]["failed_identities"]["telegram:user:222"]["account_id"] == other_account_id
    assert account_id != other_account_id


def test_notify_recent_telegram_users_skips_sent_account_across_identity_alias(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Ada")
    identities = store._load_identities()
    username_payload = dict(identities["telegram:user:111"])
    username_payload["identity_key"] = "telegram:username:ada"
    identities["telegram:username:ada"] = username_payload
    store._save_identities(identities)
    store.update_identity_route("telegram:user:111", channel="telegram", chat_id="111", chat_type="private", adapter_slot=1)
    store.update_identity_route("telegram:username:ada", channel="telegram", chat_id="111", chat_type="private", adapter_slot=1)
    state_path = tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"versions": {"1.0.3": {"sent_identities": ["telegram:username:ada"], "failed_identities": {}}}}),
        encoding="utf-8",
    )
    attempts: list[int] = []

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, text: attempts.append(chat_id),
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert count == 0
    assert attempts == []
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["versions"]["1.0.3"]["sent_identities"] == ["telegram:user:111", "telegram:username:ada"]


def test_notify_recent_telegram_users_clears_failure_for_already_sent_identity(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Ada")
    state_path = tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "versions": {
                    "1.0.3": {
                        "sent_identities": ["telegram:user:111"],
                        "failed_identities": {
                            "telegram:user:111": {
                                "adapter_slot": 1,
                                "chat_id": 111,
                                "reason": "chat not found",
                            }
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    attempts: list[int] = []

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, _text: attempts.append(chat_id),
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert count == 0
    assert attempts == []
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["versions"]["1.0.3"]["failed_identities"] == {}


def test_notify_recent_telegram_users_retries_malformed_route_failure(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Moved")
    state_path = tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "versions": {
                    "1.0.3": {
                        "sent_identities": [],
                        "failed_identities": {"telegram:user:111": {"reason": "chat not found"}},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    sent: list[int] = []

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, text: sent.append(chat_id),
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert count == 1
    assert sent == [111]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["versions"]["1.0.3"]["failed_identities"] == {}


def test_notify_recent_telegram_users_recovers_malformed_version_state(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    state_path = tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"versions": {"1.0.3": ["not", "an", "object"]}}), encoding="utf-8")
    sent: list[int] = []

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, text: sent.append(chat_id),
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert count == 1
    assert sent == [111]
    assert state["versions"]["1.0.3"]["sent_identities"] == ["telegram:user:111"]
    assert state["versions"]["1.0.3"]["failed_identities"] == {}


def test_notify_recent_telegram_users_recovers_malformed_sent_identity_list(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    state_path = tmp_path / "instances" / "Demo" / "data" / "Version_Notifications.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"versions": {"1.0.3": {"sent_identities": "telegram:user:111", "failed_identities": {}}}}),
        encoding="utf-8",
    )
    sent: list[int] = []

    count = notify_recent_telegram_users_for_version(
        version="1.0.3",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, text: sent.append(chat_id),
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert count == 1
    assert sent == [111]
    assert state["versions"]["1.0.3"]["sent_identities"] == ["telegram:user:111"]
    assert "t" not in state["versions"]["1.0.3"]["sent_identities"]


def test_notify_recent_telegram_users_requires_github_version_when_repo_root_is_given(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    sent: list[int] = []
    skips: list[str] = []

    monkeypatch.setattr("TeeBotus.core.version_notifications.github_has_version", lambda repo_root, version: False)

    count = notify_recent_telegram_users_for_version(
        version="1.0.99",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, text: sent.append(chat_id),
        repo_root=tmp_path,
        on_skip=lambda reason: skips.append(reason),
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert count == 0
    assert sent == []
    assert skips == ["GitHub tag v1.0.99 not found on remote"]


def test_notify_recent_telegram_users_includes_normalized_github_repo_link(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    sent: list[str] = []

    monkeypatch.setattr("TeeBotus.core.version_notifications.github_has_version", lambda repo_root, version: True)
    monkeypatch.setattr("TeeBotus.core.version_notifications.github_repo_url", lambda repo_root: "https://github.com/example/project")

    count = notify_recent_telegram_users_for_version(
        version="1.0.99",
        instances_dir=tmp_path / "instances",
        instance_name="Demo",
        account_store=store,
        send_message=lambda chat_id, text: sent.append(text),
        repo_root=tmp_path,
        now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert count == 1
    assert "Repo: https://github.com/example/project" in sent[0]


def test_github_has_version_normalizes_uppercase_version_prefix(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = "refs/tags/v1.0.3"

    def fake_run(args, **_kwargs):
        calls.append(list(args))
        return Result()

    monkeypatch.setattr("TeeBotus.core.version_notifications.subprocess.run", fake_run)

    assert github_has_version(tmp_path, "V1.0.3") is True
    assert calls[0][-1] == "v1.0.3"


def test_github_repo_url_normalizes_https_remote(tmp_path: Path, monkeypatch) -> None:
    class Result:
        returncode = 0
        stdout = "https://github.com/H234598/TeeBotus.git\n"

    monkeypatch.setattr("TeeBotus.core.version_notifications.subprocess.run", lambda *args, **kwargs: Result())

    assert github_repo_url(tmp_path) == "https://github.com/H234598/TeeBotus"


def test_github_repo_url_strips_https_remote_credentials(tmp_path: Path, monkeypatch) -> None:
    leaked_token = "github_pat_" + "A" * 24

    class Result:
        returncode = 0
        stdout = f"https://user:{leaked_token}@github.com/H234598/TeeBotus.git?token={leaked_token}#frag\n"

    monkeypatch.setattr("TeeBotus.core.version_notifications.subprocess.run", lambda *args, **kwargs: Result())

    repo_url = github_repo_url(tmp_path)
    commit_url = github_commit_history_url(tmp_path)

    assert repo_url == "https://github.com/H234598/TeeBotus"
    assert commit_url == "https://github.com/H234598/TeeBotus/commits/main"
    assert leaked_token not in repo_url
    assert leaked_token not in commit_url


def test_github_repo_url_strips_ssh_remote_query_and_fragment(tmp_path: Path, monkeypatch) -> None:
    leaked_token = "github_pat_" + "B" * 24

    class Result:
        returncode = 0
        stdout = f"ssh://git@github.com/H234598/TeeBotus.git?token={leaked_token}#{leaked_token}\n"

    monkeypatch.setattr("TeeBotus.core.version_notifications.subprocess.run", lambda *args, **kwargs: Result())

    repo_url = github_repo_url(tmp_path)

    assert repo_url == "https://github.com/H234598/TeeBotus"
    assert leaked_token not in repo_url


def test_github_repo_url_uses_default_for_local_remote_paths(tmp_path: Path, monkeypatch) -> None:
    class Result:
        returncode = 0
        stdout = "/home/teladi/private/TeeBotus.git\n"

    monkeypatch.setattr("TeeBotus.core.version_notifications.subprocess.run", lambda *args, **kwargs: Result())

    repo_url = github_repo_url(tmp_path)

    assert repo_url == "https://github.com/H234598/TeeBotus"
    assert "/home/teladi" not in repo_url


def test_github_repo_url_uses_default_for_non_github_https_remotes(tmp_path: Path, monkeypatch) -> None:
    class Result:
        returncode = 0
        stdout = "https://gitlab.internal.example/H234598/TeeBotus.git\n"

    monkeypatch.setattr("TeeBotus.core.version_notifications.subprocess.run", lambda *args, **kwargs: Result())

    repo_url = github_repo_url(tmp_path)

    assert repo_url == "https://github.com/H234598/TeeBotus"
    assert "gitlab.internal" not in repo_url


def test_version_notification_text_strips_repo_url_credentials() -> None:
    leaked_token = "github_pat_" + "A" * 24

    text = build_version_notification_text(
        version="1.0.3",
        repo_url=f"https://user:{leaked_token}@github.com/H234598/TeeBotus.git?token={leaked_token}#frag",
    )

    assert "Repo: https://github.com/H234598/TeeBotus" in text
    assert leaked_token not in text
    assert "user:" not in text


def test_github_commit_history_url_appends_commits_main(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("TeeBotus.core.status.github_repo_url", lambda _repo_root: "https://github.com/H234598/TeeBotus")

    assert github_commit_history_url(tmp_path) == "https://github.com/H234598/TeeBotus/commits/main"


def test_account_memory_index_health_lines_report_broken_account(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("TeeBotus.core.status.SecretToolInstanceSecretProvider", lambda **_kwargs: StaticSecretProvider(b"x" * 32))
    store = _store(tmp_path)
    account_id = store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    store.write_memory_entries(account_id, [{"id": "mem_live", "user_text": "Mond"}])
    store.write_memory_index(
        account_id,
        {
            "scope": "legacy",
            "index": {
                "recent_ids": ["mem_missing"],
                "keywords": {"mond": ["mem_live"]},
                "entries": {"mem_live": {}, "mem_missing": {}},
            },
        },
    )

    lines = account_memory_index_health_lines(instance_name="Demo", project_root=tmp_path)

    assert len(lines) == 2
    assert lines[0].startswith(f"account_memory=Demo/{account_id} status=broken error=")
    assert "index scope is not account" in lines[0]
    assert "recent_ids missing entries: mem_missing" in lines[0]
    assert "index.entries missing entries: mem_missing" in lines[0]
    assert lines[1] == (
        f'account_memory_recovery=Demo status=needed command="python3 -m TeeBotus.admin memory-recovery --instances-dir {tmp_path / "instances"} --instances Demo"'
    )


def test_account_memory_index_health_sqlite_env_does_not_create_missing_database(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("TeeBotus.core.status.SecretToolInstanceSecretProvider", lambda **_kwargs: StaticSecretProvider(b"x" * 32))
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", raising=False)
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", raising=False)
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH", raising=False)
    store = _store(tmp_path)
    account_id = store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    store.write_memory_entries(account_id, [{"id": "mem_live", "user_text": "Mond"}])
    store.write_memory_index(
        account_id,
        {
            "scope": "legacy",
            "index": {
                "recent_ids": ["mem_missing"],
                "keywords": {"mond": ["mem_live"]},
                "entries": {"mem_live": {}, "mem_missing": {}},
            },
        },
    )
    accounts_root = tmp_path / "instances" / "Demo" / "data" / "accounts"
    primary = accounts_root / "Account_Memory.sqlite3"
    fallback = accounts_root / "Account_Memory.backup.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")

    lines = account_memory_index_health_lines(instance_name="Demo", project_root=tmp_path)

    assert any("index scope is not account" in line for line in lines)
    assert not primary.exists()
    assert not fallback.exists()


def test_account_memory_index_health_uses_database_when_profile_envelope_is_stale(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setattr("TeeBotus.core.status.SecretToolInstanceSecretProvider", lambda **_kwargs: StaticSecretProvider(b"x" * 32))
    store = _store(tmp_path)
    account_id = store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    store.append_structured_memory_entry(account_id, {"id": "mem_live", "user_text": "Mond", "bot_text": "Tee"})
    stale_profile_store = AccountStore(
        tmp_path / "instances" / "Demo" / "data" / "accounts",
        "Demo",
        secret_provider=StaticSecretProvider(b"y" * 32),
        create_dirs=False,
    )
    profile_path = stale_profile_store.account_dir(account_id) / "Account_Profile.json"
    stale_profile = {"schema_version": 1, "instance": "Demo", "account_id": account_id, "status": "active"}
    profile_path.write_bytes(
        stale_profile_store.vault.encrypt(
            json.dumps(stale_profile, sort_keys=True).encode("utf-8"),
            kind="Account_Profile.json",
        )
    )

    lines = account_memory_index_health_lines(instance_name="Demo", project_root=tmp_path)

    assert lines == [
        f"account_memory_metadata=Demo status=broken item=accounts_dir path={tmp_path / 'instances' / 'Demo' / 'data' / 'accounts' / 'accounts'} accounts={account_id[:12]} error=encrypted envelope authentication failed",
        f"account_memory=Demo/{account_id} status=broken error=profile_unreadable:encrypted envelope authentication failed",
        f'account_memory_recovery=Demo status=needed command="python3 -m TeeBotus.admin memory-recovery --instances-dir {tmp_path / "instances"} --instances Demo"',
    ]


def test_account_memory_index_health_reports_unreadable_account_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setattr("TeeBotus.core.status.SecretToolInstanceSecretProvider", lambda **_kwargs: StaticSecretProvider(b"x" * 32))
    accounts_root = tmp_path / "instances" / "Demo" / "data" / "accounts"
    bad_store = AccountStore(accounts_root, "Demo", secret_provider=StaticSecretProvider(b"y" * 32))
    account_id = bad_store.resolve_or_create_account("telegram:user:111", display_label="Stale")
    bad_store.vault.write_json(accounts_root / "Account_Secrets.json", {"schema_version": 1, "secrets": {}})

    lines = account_memory_index_health_lines(instance_name="Demo", project_root=tmp_path)

    assert any("account_memory_metadata=Demo status=broken item=account_index" in line for line in lines)
    assert any("account_memory_metadata=Demo status=broken item=identity_mapping" in line for line in lines)
    assert any("account_memory_metadata=Demo status=broken item=account_secrets" in line for line in lines)
    assert any(f"account_memory_metadata=Demo status=broken item=accounts_dir" in line and f"accounts={account_id[:12]}" in line for line in lines)
    assert any(
        line == f"account_memory=Demo/{account_id} status=broken error=profile_unreadable:encrypted envelope authentication failed"
        for line in lines
    )
    assert lines[-1] == (
        f'account_memory_recovery=Demo status=needed command="python3 -m TeeBotus.admin memory-recovery --instances-dir {tmp_path / "instances"} --instances Demo"'
    )


def test_account_memory_index_health_reports_recovery_when_store_open_fails(tmp_path: Path, monkeypatch) -> None:
    account_id = "a" * 128
    account_dir = tmp_path / "instances" / "Demo" / "data" / "accounts" / "accounts" / account_id
    account_dir.mkdir(parents=True)

    class FailingStore:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AccountStoreError("instance secret is missing")

    monkeypatch.setattr("TeeBotus.core.status.AccountStore", FailingStore)

    lines = account_memory_index_health_lines(instance_name="Demo", project_root=tmp_path)

    assert lines == [
        "account_memory=Demo status=broken error=AccountStoreError: instance secret is missing",
        f"account_memory=Demo/{account_id} status=broken error=account_store_unavailable:AccountStoreError: instance secret is missing",
        f'account_memory_recovery=Demo status=needed command="python3 -m TeeBotus.admin memory-recovery --instances-dir {tmp_path / "instances"} --instances Demo"',
    ]


def test_account_memory_index_health_suppresses_expected_database_decryption_logs(tmp_path: Path, monkeypatch, caplog) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setattr("TeeBotus.core.status.SecretToolInstanceSecretProvider", lambda **_kwargs: StaticSecretProvider(b"x" * 32))
    store = _store(tmp_path)
    account_id = store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    old_backend = SQLiteAccountMemoryBackend(
        instance_name="Demo",
        provider=StaticSecretProvider(b"y" * 32),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(
            path=tmp_path / "instances" / "Demo" / "data" / "accounts" / "Account_Memory.sqlite3",
            fallback_path=None,
        ),
    )
    old_backend.write_entries(account_id, [{"id": "mem_live", "user_text": "Mond"}])
    old_backend.write_index(account_id, {"scope": "account", "index": {}})

    with caplog.at_level("CRITICAL", logger="TeeBotus"):
        lines = account_memory_index_health_lines(instance_name="Demo", project_root=tmp_path)

    assert len(lines) == 2
    assert "status=broken" in lines[0]
    assert "database entries unreadable" in lines[0]
    assert "database index unreadable" in lines[0]
    assert lines[1].startswith("account_memory_recovery=Demo status=needed")
    assert "SQLite account-memory skipped corrupt rows" not in caplog.text
    assert "SQLite account-memory index could not be decrypted" not in caplog.text


def test_account_memory_index_health_reports_stale_fallback_sync(tmp_path: Path, monkeypatch) -> None:
    account_id = "a" * 128
    account_dir = tmp_path / "instances" / "Demo" / "data" / "accounts" / "accounts" / account_id
    account_dir.mkdir(parents=True)

    class Backend:
        stale_fallback_entry_account_ids = (account_id,)
        stale_fallback_index_account_ids: tuple[str, ...] = ()
        last_fallback_sync_error = "write_entries: fallback unavailable"

    class FakeStore:
        account_memory_backend = Backend()

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def _read_account_profile(self, _account_id: str) -> dict[str, object]:
            return {"status": "active"}

        def check_structured_memory_index(self, _account_id: str, *, require_resolvable: bool = True) -> object:
            return SimpleNamespace(ok=True, errors=())

    monkeypatch.setattr("TeeBotus.core.status.AccountStore", FakeStore)

    lines = account_memory_index_health_lines(instance_name="Demo", project_root=tmp_path)

    assert lines == [
        f"account_memory=Demo/{account_id} status=ok warning=fallback_sync_stale:entries:write_entries: fallback unavailable"
    ]


def test_account_memory_index_health_reports_stale_instance_collection_sync(tmp_path: Path, monkeypatch) -> None:
    account_id = "a" * 128
    account_dir = tmp_path / "instances" / "Demo" / "data" / "accounts" / "accounts" / account_id
    account_dir.mkdir(parents=True)

    class Backend:
        stale_fallback_entry_account_ids: tuple[str, ...] = ()
        stale_fallback_index_account_ids: tuple[str, ...] = ()
        stale_fallback_collection_account_ids = (INSTANCE_STATE_ACCOUNT_ID,)
        last_fallback_sync_error = "write_collection:version_notifications: fallback unavailable"

    class FakeStore:
        account_memory_backend = Backend()

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def _read_account_profile(self, _account_id: str) -> dict[str, object]:
            return {"status": "active"}

        def check_structured_memory_index(self, _account_id: str, *, require_resolvable: bool = True) -> object:
            return SimpleNamespace(ok=True, errors=())

    monkeypatch.setattr("TeeBotus.core.status.AccountStore", FakeStore)

    lines = account_memory_index_health_lines(instance_name="Demo", project_root=tmp_path)

    assert lines == [
        "account_memory=Demo/__instance_state status=warning "
        "warning=fallback_sync_stale:collections:write_collection:version_notifications: fallback unavailable",
        f"account_memory=Demo/{account_id} status=ok",
    ]


def test_account_memory_index_health_reports_none_without_accounts_or_instance_state(tmp_path: Path, monkeypatch) -> None:
    class Backend:
        stale_fallback_entry_account_ids: tuple[str, ...] = ()
        stale_fallback_index_account_ids: tuple[str, ...] = ()
        stale_fallback_collection_account_ids: tuple[str, ...] = ()
        last_fallback_sync_error = ""

    class FakeStore:
        account_memory_backend = Backend()

        def __init__(self, *_args, **_kwargs) -> None:
            pass

    monkeypatch.setattr("TeeBotus.core.status.AccountStore", FakeStore)

    lines = account_memory_index_health_lines(instance_name="Demo", project_root=tmp_path)

    assert lines == ["account_memory=Demo status=none"]


def test_account_memory_index_health_reports_stale_instance_collection_without_account_dirs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class Backend:
        stale_fallback_entry_account_ids: tuple[str, ...] = ()
        stale_fallback_index_account_ids: tuple[str, ...] = ()
        stale_fallback_collection_account_ids = (INSTANCE_STATE_ACCOUNT_ID,)
        last_fallback_sync_error = "write_collection:version_notifications: fallback unavailable"

    class FakeStore:
        account_memory_backend = Backend()

        def __init__(self, *_args, **_kwargs) -> None:
            pass

    monkeypatch.setattr("TeeBotus.core.status.AccountStore", FakeStore)

    lines = account_memory_index_health_lines(instance_name="Demo", project_root=tmp_path)

    assert lines == [
        "account_memory=Demo/__instance_state status=warning "
        "warning=fallback_sync_stale:collections:write_collection:version_notifications: fallback unavailable"
    ]


def test_version_notification_text_does_not_expose_memory_files() -> None:
    text = build_version_notification_text(version="1.0.3", memory_text="User_Habbits_and_behave.md crypto secret")

    assert "User_Habbits_and_behave" not in text
    assert ".md" not in text
    assert "Version 1.0.3" in text
    assert "Repo: https://github.com/H234598/TeeBotus" in text
