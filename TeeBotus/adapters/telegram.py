from __future__ import annotations

from typing import Any

from TeeBotus.runtime.accounts import telegram_identity_key
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
from TeeBotus.runtime.events import IncomingEvent


def telegram_message_to_event(
    message: dict[str, Any] | None = None,
    *,
    update: dict[str, Any] | None = None,
    instance: str | None = None,
    instance_name: str | None = None,
    adapter_slot: int,
    account_id: str = "",
    account_label: str = "telegram:1",
) -> IncomingEvent | None:
    if message is None and update is not None:
        message = telegram_update_message(update)
    if not message:
        return None
    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    sender_chat = message.get("sender_chat") if isinstance(message.get("sender_chat"), dict) else {}
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    sender_id = str((sender.get("id") if sender else sender_chat.get("id")) or "")
    chat_id = str(chat.get("id") or "")
    if not chat_id:
        return None
    text = str(message.get("text") or message.get("caption") or "")
    sender_name = _telegram_sender_name(sender, sender_chat)
    sender_username = str((sender.get("username") if sender else sender_chat.get("username")) or "")
    try:
        identity_key = telegram_identity_key(sender_id, username=sender_username, display_name=sender_name)
    except Exception:
        return None
    return IncomingEvent(
        event_id=f"telegram:{message.get('message_id', '')}",
        instance=instance_name or instance or "",
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
        text=text,
        message_ref=str(message.get("message_id") or ""),
        attachments=(),
        raw=message if update is None else update,
    )


def telegram_update_message(update: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("message", "channel_post"):
        value = update.get(key)
        if isinstance(value, dict):
            return value
    return None


def _telegram_sender_name(sender: dict[str, Any], sender_chat: dict[str, Any]) -> str:
    if sender:
        return " ".join(part for part in [str(sender.get("first_name") or "").strip(), str(sender.get("last_name") or "").strip()] if part)
    return str(sender_chat.get("title") or sender_chat.get("first_name") or "").strip()


def send_telegram_actions(api: Any, actions: list[Any]) -> list[int | None]:
    sent: list[int | None] = []
    for action in actions:
        if isinstance(action, SendText):
            sent.append(
                _send_telegram_text(
                    api,
                    action.chat_id,
                    action.text,
                    text_mode=action.text_mode,
                    formatted_text=action.formatted_text,
                )
            )
        elif isinstance(action, SendTyping):
            api.send_chat_action(action.chat_id, "typing")
            sent.append(None)
        elif isinstance(action, (SendReaction, SendReceipt)):
            sent.append(None)
        elif isinstance(action, SendEdit):
            edit_message_text = getattr(api, "edit_message_text", None)
            if callable(edit_message_text):
                sent.append(edit_message_text(action.chat_id, action.message_ref, action.text))
            else:
                sent.append(None)
        elif isinstance(action, SendPoll):
            send_poll = getattr(api, "send_poll", None)
            answers = [str(answer or "").strip() for answer in action.answers if str(answer or "").strip()]
            if callable(send_poll) and len(answers) >= 2:
                sent.append(
                    send_poll(
                        action.chat_id,
                        action.question,
                        answers,
                        allows_multiple_answers=action.allow_multiple_selections,
                    )
                )
            else:
                sent.append(api.send_message(action.chat_id, _poll_text_fallback(action.question, answers)))
        elif isinstance(action, SendAttachment):
            if action.content_type.startswith("audio/") and hasattr(api, "send_voice"):
                sent.append(api.send_voice(action.chat_id, action.data, action.filename, action.content_type))
            elif hasattr(api, "send_document"):
                sent.append(api.send_document(action.chat_id, action.data, action.filename, action.content_type, caption=action.caption))
            else:
                sent.append(api.send_message(action.chat_id, action.caption or f"Datei: {action.filename}"))
        elif isinstance(action, ExportFile):
            send_document = getattr(api, "send_document", None)
            if callable(send_document):
                sent.append(send_document(action.chat_id, action.data, action.filename, action.content_type, caption=action.caption))
            else:
                sent.append(api.send_message(action.chat_id, f"Export erzeugt: {action.filename}"))
        elif isinstance(action, NotifyLinkedIdentity):
            # Routing a notification by identity requires the production identity router;
            # the adapter keeps it explicit instead of leaking the notice to the wrong chat.
            sent.append(None)
        elif isinstance(action, DeleteTrackedMessages):
            sent.append(None)
        elif isinstance(action, SetMatrixState):
            sent.append(None)
        elif isinstance(action, (UpdateSignalContact, UpdateSignalGroup)):
            sent.append(None)
        else:
            sent.append(None)
    return sent


def _send_telegram_text(api: Any, chat_id: Any, text: str, *, text_mode: str = "", formatted_text: str = "") -> int | None:
    if text_mode or formatted_text:
        try:
            return api.send_message(chat_id, text, text_mode=text_mode, formatted_text=formatted_text)
        except TypeError as exc:
            if "text_mode" not in str(exc) and "formatted_text" not in str(exc):
                raise
            return api.send_message(chat_id, text)
    return api.send_message(chat_id, text)


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
