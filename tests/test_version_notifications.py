from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from TeeBotus.core.version_notifications import (
    build_version_notification_text,
    github_repo_url,
    notify_recent_telegram_users_for_version,
    recent_telegram_recipients,
)
from TeeBotus.core.status import account_memory_index_health_lines, github_commit_history_url
from TeeBotus.runtime.accounts import ACCOUNT_MEMORY_KEY_PURPOSE, AccountStore, StaticSecretProvider
from TeeBotus.runtime.sqlite_memory import SQLiteAccountMemoryBackend, SQLiteMemoryConfig


def _store(tmp_path: Path) -> AccountStore:
    return AccountStore(
        tmp_path / "instances" / "Demo" / "data" / "accounts",
        "Demo",
        secret_provider=StaticSecretProvider(b"x" * 32),
    )


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


def test_github_commit_history_url_appends_commits_main(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("TeeBotus.core.status.github_repo_url", lambda _repo_root: "https://github.com/H234598/TeeBotus")

    assert github_commit_history_url(tmp_path) == "https://github.com/H234598/TeeBotus/commits/main"


def test_account_memory_index_health_lines_report_broken_account(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("TeeBotus.core.status.SecretToolInstanceSecretProvider", lambda: StaticSecretProvider(b"x" * 32))
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


def test_account_memory_index_health_uses_database_when_profile_envelope_is_stale(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setattr("TeeBotus.core.status.SecretToolInstanceSecretProvider", lambda: StaticSecretProvider(b"x" * 32))
    store = _store(tmp_path)
    account_id = store.resolve_or_create_account("telegram:user:111", display_label="Fresh")
    store.append_structured_memory_entry(account_id, {"id": "mem_live", "user_text": "Mond", "bot_text": "Tee"})
    stale_profile_store = AccountStore(
        tmp_path / "instances" / "Demo" / "data" / "accounts",
        "Demo",
        secret_provider=StaticSecretProvider(b"y" * 32),
        create_dirs=False,
    )
    stale_profile_store._write_account_profile(
        account_id,
        {"schema_version": 1, "instance": "Demo", "account_id": account_id, "status": "active"},
    )

    lines = account_memory_index_health_lines(instance_name="Demo", project_root=tmp_path)

    assert lines == [
        f"account_memory=Demo/{account_id} status=ok warning=profile_unreadable:encrypted envelope authentication failed"
    ]


def test_account_memory_index_health_suppresses_expected_database_decryption_logs(tmp_path: Path, monkeypatch, caplog) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setattr("TeeBotus.core.status.SecretToolInstanceSecretProvider", lambda: StaticSecretProvider(b"x" * 32))
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


def test_version_notification_text_does_not_expose_memory_files() -> None:
    text = build_version_notification_text(version="1.0.3", memory_text="User_Habbits_and_behave.md crypto secret")

    assert "User_Habbits_and_behave" not in text
    assert ".md" not in text
    assert "Version 1.0.3" in text
    assert "Repo: https://github.com/H234598/TeeBotus" in text
