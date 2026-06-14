from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from TeeBotus.core.version_notifications import (
    build_version_notification_text,
    notify_recent_telegram_users_for_version,
    recent_telegram_recipients,
)
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider


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
    assert "ffmpeg" in sent[0][1]


def test_version_notification_text_does_not_expose_memory_files() -> None:
    text = build_version_notification_text(version="1.0.3", memory_text="User_Habbits_and_behave.md crypto secret")

    assert "User_Habbits_and_behave" not in text
    assert ".md" not in text
    assert "Version 1.0.3" in text
