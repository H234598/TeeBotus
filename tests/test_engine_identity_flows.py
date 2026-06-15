from __future__ import annotations

import re

from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, StaticSecretProvider, signal_identity_key, telegram_identity_key
from TeeBotus.runtime.actions import DeleteTrackedMessages
from TeeBotus.runtime.engine import TeeBotusEngine
from TeeBotus.runtime.events import IncomingEvent
from TeeBotus.instructions import BotInstructions


def store(tmp_path):
    return AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"e" * 32))


def event(identity_key: str, text: str, *, channel: str = "telegram") -> IncomingEvent:
    return IncomingEvent(
        event_id=f"{channel}:1",
        instance="Depressionsbot",
        channel=channel,  # type: ignore[arg-type]
        adapter_slot=1,
        account_id="",
        identity_key=identity_key,
        chat_id="chat-1",
        chat_type="private",
        sender_id=identity_key,
        sender_name=identity_key,
        text=text,
        message_ref="1",
    )


def _tokens(text: str) -> list[str]:
    return re.findall(r"\b[0-9a-f]{128}\b", text)


def test_wtf_can_be_confirmed_by_any_existing_identity_after_multi_identity_link(tmp_path):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    first = engine.process_identity_flows(event(telegram_identity_key(1), "/register"))
    account_id, secret = _tokens(first.actions[0].text)
    old_signal = signal_identity_key(source_uuid="old")
    new_signal = signal_identity_key(source_uuid="new")

    engine.process_identity_flows(event(old_signal, f"/login {account_id} {secret}", channel="signal"))
    engine.process_identity_flows(event(new_signal, f"/login {account_id} {secret}", channel="signal"))
    wtf_from_first_telegram = engine.process_identity_flows(event(telegram_identity_key(1), "WTF?"))

    assert "Secret wurde rotiert" in wtf_from_first_telegram.actions[0].text
    assert account_store.get_account_for_identity(new_signal) is None
    assert account_store.get_account_for_identity(old_signal) == account_id


def test_new_identity_cannot_use_wtf_notification_for_itself(tmp_path):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    registered = engine.process_identity_flows(event(telegram_identity_key(1), "/register"))
    account_id, secret = _tokens(registered.actions[0].text)
    new_signal = signal_identity_key(source_uuid="new")

    engine.process_identity_flows(event(new_signal, f"/login {account_id} {secret}", channel="signal"))
    result = engine.process_identity_flows(event(new_signal, "WTF?", channel="signal"))

    assert result.handled is True
    assert "bereits bestehenden Kommunikationsweg" in result.actions[0].text
    assert account_store.get_account_for_identity(new_signal) == account_id


def test_cleanup_requires_exact_command_and_valid_count(tmp_path):
    engine = TeeBotusEngine(account_store=store(tmp_path))

    unknown = engine.process(event(telegram_identity_key(1), "/cleanupfoo"))
    bad = engine.process(event(telegram_identity_key(1), "/cleanup banana"))
    good = engine.process(event(telegram_identity_key(1), "/cleanup 2"))

    assert "Diesen Befehl kenne ich nicht" in unknown[0].text
    assert "Nutzung:" in bad[0].text
    assert isinstance(good[0], DeleteTrackedMessages)
    assert good[0].count == 2


def test_engine_handles_default_builtin_reply_after_identity_flows(tmp_path):
    engine = TeeBotusEngine(account_store=store(tmp_path))

    actions = engine.process(event(telegram_identity_key(1), "/ping"))

    assert len(actions) == 1
    assert actions[0].text == "pong"


def test_engine_uses_configured_builtin_reply_after_identity_flows(tmp_path):
    instructions = BotInstructions(commands={"/custom": "Hallo {first_name}."})
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions)

    actions = engine.process(event(telegram_identity_key(1), "/custom"))

    assert len(actions) == 1
    assert actions[0].text == "Hallo telegram:user:1."


def test_account_edit_sets_pending_flow(tmp_path):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    result = engine.process_identity_flows(event(identity, "/account_edit"))
    account_id = account_store.get_account_for_identity(identity)

    assert result.handled is True
    assert account_id is not None
    assert engine.state.get_pending_flow("Depressionsbot", account_id, "account_edit") == {"step": "start"}


def test_register_reports_real_store_error_separately_from_existing_secret():
    class Store:
        def register_account(self, account_id):
            raise AccountStoreError("secret backend unavailable")

    text = TeeBotusEngine(account_store=Store())._register_text("a" * 128)  # type: ignore[arg-type]

    assert "Store-/Crypto-Fehlers" in text
    assert "existiert bereits" not in text
