from __future__ import annotations

import base64

import pytest

from TeeBotus.adapters.signal import signal_context_to_event
from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, StaticSecretProvider, signal_identity_key, telegram_identity_key
from TeeBotus.runtime.config import RuntimeConfigError, resolve_channels, resolve_openai_key, resolve_signal_accounts
from TeeBotus.runtime.engine import TeeBotusEngine
from TeeBotus.runtime.events import IncomingEvent


def provider() -> StaticSecretProvider:
    return StaticSecretProvider(b"r" * 32)


def event(identity_key: str, text: str, *, channel: str = "telegram", chat_type: str = "private") -> IncomingEvent:
    return IncomingEvent(
        event_id="round5",
        instance_name="Depressionsbot",
        channel=channel,
        adapter_slot=1,
        account_label=f"{channel}:1",
        identity_key=identity_key,
        chat_id="123",
        chat_type=chat_type,
        sender_id="sender",
        sender_name="Sender",
        sender_username="sender",
        sender_number="",
        text=text,
        message_ref="1",
    )


def test_account_text_helpers_reject_path_traversal(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(1))

    with pytest.raises(AccountStoreError):
        store.write_account_text(account_id, "../escape.md", "nope")
    with pytest.raises(AccountStoreError):
        store.read_account_text(account_id, "nested/file.md")

    assert not (tmp_path / "escape.md").exists()


def test_tombstoned_account_cannot_receive_login_or_secret_rotation(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    target = store.resolve_or_create_account(telegram_identity_key(1))
    _, target_secret = store.register_account(target)
    source = store.resolve_or_create_account(signal_identity_key(source_uuid="temp"))

    store.link_identity(signal_identity_key(source_uuid="temp"), target, target_secret)

    with pytest.raises(AccountStoreError):
        store.rotate_secret(source)
    with pytest.raises(AccountStoreError):
        store.link_identity(signal_identity_key(source_uuid="new"), source, target_secret)


def test_channel_level_openai_key_beats_instance_slot_key():
    env = {
        "OPENAI_API_KEY_DEPRESSIONSBOT_SIGNAL": "sk-signal-channel",
        "OPENAI_API_KEY_DEPRESSIONSBOT_1": "sk-instance-slot",
        "OPENAI_API_KEY_DEPRESSIONSBOT": "sk-instance",
    }

    assert resolve_openai_key("Depressionsbot", "signal", 1, env) == "sk-signal-channel"


def test_duplicate_channels_raise_instead_of_duplicate_adapter_start():
    with pytest.raises(RuntimeConfigError):
        resolve_channels({}, cli_channels="telegram,telegram")


def test_duplicate_signal_phone_numbers_raise(tmp_path):
    env = {
        "SIGNAL_BOT_SERVICES_DEPRESSIONSBOT": "127.0.0.1:8080,127.0.0.1:8081",
        "SIGNAL_BOT_PHONE_NUMBERS_DEPRESSIONSBOT": "+491,+491",
    }

    with pytest.raises(RuntimeConfigError):
        resolve_signal_accounts("Depressionsbot", env)


def test_signal_attachment_without_local_filename_is_preserved():
    class Message:
        source_uuid = "uuid"
        source_number = "+491"
        source = "+491"
        timestamp = 1
        text = ""
        group = None
        base64_attachments = [base64.b64encode(b"payload").decode("ascii")]
        attachments_local_filenames: list[str] = []

        def recipient(self):
            return self.source

    class Context:
        message = Message()

    event = signal_context_to_event(context=Context(), instance_name="Bot", adapter_slot=1, account_label="signal:1")

    assert len(event.attachments) == 1
    assert event.attachments[0].filename == "signal-attachment-1.bin"
    assert event.attachments[0].data == b"payload"
