from __future__ import annotations

from pathlib import Path
from typing import Any

from TeeBotus.core.account_commands import AccountCommandHandler, AccountCommandResult
from TeeBotus.runtime.accounts import AccountStore, InstanceSecretProvider, SecretToolInstanceSecretProvider, telegram_identity_key
from TeeBotus.runtime.actions import (
    DeleteTrackedMessages,
    ExportFile,
    NotifyLinkedIdentity,
    SendAttachment,
    SendEdit,
    SendPoll,
    SendReaction,
    SendReceipt,
    SendText,
    SendTyping,
    SetMatrixState,
    UpdateSignalContact,
    UpdateSignalGroup,
)
from TeeBotus.runtime.engine import TeeBotusEngine
from TeeBotus.runtime.events import IncomingEvent
from TeeBotus.runtime.message_tracking import MessageTracker, SentMessageRef
from TeeBotus.runtime.state import RuntimeStateStore


def build_telegram_event_from_message(
    message: dict[str, Any],
    *,
    instance_name: str,
    adapter_slot: int = 1,
    account_id: str = "",
) -> IncomingEvent | None:
    """Convert a Telegram Bot API message dict into the new runtime event model.

    This helper is intentionally dependency-free so the existing monolithic
    ``TeeBotus.adapters.telegram_polling`` module can call it before the full adapter refactor is done.
    """
    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    sender_id = str(sender.get("id") or "").strip()
    chat_id = str(chat.get("id") or "").strip()
    if not chat_id:
        return None
    first_name = str(sender.get("first_name") or "").strip()
    last_name = str(sender.get("last_name") or "").strip()
    sender_name = " ".join(part for part in (first_name, last_name) if part)
    sender_username = str(sender.get("username") or "").strip()
    try:
        identity_key = telegram_identity_key(sender_id, username=sender_username, display_name=sender_name)
    except Exception:
        return None
    return IncomingEvent(
        event_id=f"telegram:{message.get('message_id', '')}",
        instance=instance_name,
        channel="telegram",
        adapter_slot=adapter_slot,
        account_id=account_id,
        identity_key=identity_key,
        chat_id=chat_id,
        chat_type=_normalize_telegram_chat_type(str(chat.get("type") or "unknown")),
        sender_id=sender_id,
        sender_name=sender_name,
        sender_username=sender_username,
        sender_number="",
        text=str(message.get("text") or message.get("caption") or ""),
        message_ref=str(message.get("message_id") or ""),
        attachments=(),
        raw=message,
    )


class TelegramRuntimeBridge:
    """Small bridge that lets the current Telegram loop use Plan-3 account flows.

    It handles only identity/account commands and cleanup action planning. When it
    returns ``False`` the existing TeeBotus message logic should continue unchanged.
    """

    def __init__(
        self,
        *,
        instance_name: str,
        data_dir: str | Path,
        secret_provider: InstanceSecretProvider | None = None,
    ) -> None:
        self.instance_name = instance_name
        raw_path = Path(data_dir)
        self.instance_dir = raw_path.parent if raw_path.name == "data" else raw_path
        self.data_dir = raw_path if raw_path.name == "data" else raw_path / "data"
        resolved_secret_provider = secret_provider or SecretToolInstanceSecretProvider()
        self.account_store = AccountStore(self.data_dir / "accounts", self.instance_name, secret_provider=resolved_secret_provider)
        self.state_store = RuntimeStateStore(self.data_dir, instance_name=self.instance_name, secret_provider=resolved_secret_provider)
        self.message_tracker = MessageTracker(self.data_dir / "runtime" / "Sent_Message_Refs.json")
        self.engine = TeeBotusEngine(self.account_store, state=self.state_store, message_tracker=self.message_tracker)
        self.account_commands = AccountCommandHandler(self.account_store, self.state_store)

    def event_from_message(self, message: dict[str, Any], *, adapter_slot: int = 1) -> IncomingEvent | None:
        event = build_telegram_event_from_message(
            message,
            instance_name=self.instance_name,
            adapter_slot=adapter_slot,
        )
        if event is None:
            return None
        account_id = self.account_store.resolve_or_create_account(event.identity_key, display_label=event.sender_name)
        return IncomingEvent(
            event_id=event.event_id,
            instance=event.instance,
            channel=event.channel,
            adapter_slot=event.adapter_slot,
            account_id=account_id,
            identity_key=event.identity_key,
            chat_id=event.chat_id,
            chat_type=event.chat_type,
            sender_id=event.sender_id,
            sender_name=event.sender_name,
            sender_username=event.sender_username,
            sender_number=event.sender_number,
            text=event.text,
            message_ref=event.message_ref,
            attachments=event.attachments,
            link_previews=event.link_previews,
            reply_to_text=event.reply_to_text,
            raw=event.raw,
        )

    def handle_message(self, message: dict[str, Any], sender, *, adapter_slot: int = 1) -> bool:
        """Return True if the bridge handled the message.

        ``sender`` is any object exposing ``send_message(text)``. This mirrors the
        simple shape already present in TeeBotus helpers and keeps this bridge free
        of Telegram API details.
        """
        event = self.event_from_message(message, adapter_slot=adapter_slot)
        if event is None:
            return False
        result = self.account_commands.handle(event)
        if not result.handled:
            actions = self.engine.process(event)
        else:
            actions = list(result.actions)
        if not actions:
            return False
        self.dispatch_to_sender(sender, event, actions)
        return True

    def dispatch_to_sender(self, sender, event: IncomingEvent, actions: list[Any]) -> None:
        for action in actions:
            if isinstance(action, SendText):
                sender.send_message(action.text)
                if action.track:
                    self.message_tracker.record(
                        SentMessageRef(
                            channel=event.channel,
                            instance_name=event.instance,
                            account_id=event.account_id,
                            chat_id=event.chat_id,
                            message_ref="telegram-unknown",
                            ref_kind="telegram_message_id",
                        )
                    )
            elif isinstance(action, NotifyLinkedIdentity):
                # The Telegram bridge has no cross-identity router; production adapters must deliver this.
                continue
            elif isinstance(action, DeleteTrackedMessages):
                note = "Ich lösche nur die in diesem aktuellen Chat gemerkten Botnachrichten, nicht Nachrichten in anderen Chats oder Messengern."
                sender.send_message(note)
            elif isinstance(action, ExportFile):
                sender.send_message(f"Export erzeugt: {action.filename}")
            elif isinstance(action, SendAttachment):
                sender.send_message(action.caption or f"Datei erzeugt: {action.filename}")
            elif isinstance(action, SendTyping):
                continue
            elif isinstance(action, SendEdit):
                edit_message = getattr(sender, "edit_message", None)
                if callable(edit_message):
                    edit_message(action.message_ref, action.text)
                else:
                    sender.send_message(action.text)
            elif isinstance(action, SendPoll):
                send_poll = getattr(sender, "send_poll", None)
                answers = [str(answer or "").strip() for answer in action.answers if str(answer or "").strip()]
                if callable(send_poll) and len(answers) >= 2:
                    send_poll(action.question, answers, allow_multiple_selections=action.allow_multiple_selections)
                else:
                    sender.send_message(_poll_text_fallback(action.question, answers))
                if action.track:
                    self.message_tracker.record(
                        SentMessageRef(
                            channel=event.channel,
                            instance_name=event.instance,
                            account_id=event.account_id,
                            chat_id=event.chat_id,
                            message_ref="telegram-unknown",
                            ref_kind="telegram_message_id",
                        )
                    )
            elif isinstance(action, (SendReaction, SendReceipt, SetMatrixState, UpdateSignalContact, UpdateSignalGroup)):
                continue


def maybe_handle_account_runtime_message(
    message: dict[str, Any],
    sender,
    *,
    instance_name: str,
    data_dir: str | Path,
    adapter_slot: int = 1,
) -> bool:
    bridge = TelegramRuntimeBridge(instance_name=instance_name, data_dir=data_dir)
    return bridge.handle_message(message, sender, adapter_slot=adapter_slot)


def _normalize_telegram_chat_type(value: str) -> str:
    normalized = str(value or "unknown").strip().casefold()
    if normalized == "private":
        return "private"
    if normalized in {"group", "supergroup", "channel"}:
        return "group"
    return "unknown"


def _poll_text_fallback(question: str, answers: list[str]) -> str:
    clean_question = str(question or "").strip() or "Umfrage"
    if not answers:
        return clean_question
    options = "\n".join(f"{index}. {answer}" for index, answer in enumerate(answers, start=1))
    return f"{clean_question}\n{options}"
