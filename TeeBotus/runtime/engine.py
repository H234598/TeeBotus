from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from subprocess import TimeoutExpired
from typing import Callable, Iterable

from TeeBotus.core.youtube import (
    YOUTUBE_TRANSCRIPT_COMMANDS,
    YouTubeTranscriptError,
    _build_youtube_pipeline_text,
    _extract_youtube_url,
    _has_youtube_transcript_intent,
    _parse_youtube_local_options,
    transcribe_youtube_video,
)
from TeeBotus.core.registration import RegistrationAction, parse_registration_intent, redact_registration_secrets
from TeeBotus.core.status import build_status_reply
from TeeBotus.handlers import build_reply
from TeeBotus.instructions import BotInstructions
from TeeBotus.openai_client import OpenAIAPIError
from TeeBotus.runtime.accounts import AccountStore, AccountStoreError
from TeeBotus.runtime.actions import NotifyLinkedIdentity, SendAttachment, SendText, SendTyping, OutgoingAction
from TeeBotus.runtime.events import IncomingEvent
from TeeBotus.runtime.state import RuntimeState

PRIVATE_ONLY = "Bitte privat."
LINKED_NOTICE = "Ein neuer Kommunikationsweg wurde mit deinem TeeBotus-Account verbunden. Wenn du das nicht warst, schreibe innerhalb der Sicherheitsfrist: WTF?"
CURRENT_CHAT_CLEANUP_NOTE = "Ich lösche nur die in diesem aktuellen Chat gemerkten Botnachrichten, nicht Nachrichten in anderen Chats oder Messengern."
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class EngineResult:
    account_id: str
    actions: list[OutgoingAction]
    handled: bool = False


class TeeBotusEngine:
    """Channel-neutral first stage engine for account/registration and built-in commands.

    Telegram still owns the broader YouTube and memory stack. Signal and Matrix use
    this engine as their channel-neutral baseline so configured replies, OpenAI
    text/voice handling, and identity-critical commands share the same behavior.
    """

    def __init__(
        self,
        account_store: AccountStore,
        state: RuntimeState | None = None,
        message_tracker: object | None = None,
        instructions: BotInstructions | Callable[[], BotInstructions] | None = None,
        project_root: Path | None = None,
        openai_client: object | None = None,
        bot_address_names: Iterable[str] = (),
    ) -> None:
        self.account_store = account_store
        self.state = state or RuntimeState()
        self.message_tracker = message_tracker
        self._instructions = instructions
        self.project_root = project_root or PROJECT_ROOT
        self.openai_client = openai_client
        self.bot_address_names = frozenset(_normalize_address_name(name) for name in bot_address_names if str(name or "").strip())


    def process(self, event: IncomingEvent) -> list[OutgoingAction]:
        from TeeBotus.runtime.actions import DeleteTrackedMessages, SendText

        text = str(event.text or "").strip()
        command = _command_name(text)
        if _command_targets_other_bot(text, self.bot_address_names):
            return []
        if command == "/cleanup":
            parsed = _parse_cleanup_count(text)
            if parsed is None:
                return [SendText(event.chat_id, "Nutzung: /cleanup N oder /cleanup all. Ich lösche dabei nur den aktuellen Chat.", track=False)]
            return [DeleteTrackedMessages(event.chat_id, parsed), SendText(event.chat_id, self.cleanup_scope_text(), track=False)]
        result = self.process_identity_flows(event)
        if result.handled or result.actions:
            return result.actions
        if command == "/status":
            return [
                SendText(
                    event.chat_id,
                    build_status_reply(account_id=result.account_id, instance_name=event.instance, project_root=self.project_root),
                )
            ]
        if command == "/reset":
            self.state.reset_previous_response_id(event.instance, result.account_id)
            return [SendText(event.chat_id, self._current_instructions().openai_reset)]
        if command == "/voice":
            return self._voice_actions(event, self._current_instructions())
        if command in YOUTUBE_TRANSCRIPT_COMMANDS:
            return self._youtube_transcript_actions(event, result.account_id, self._current_instructions())
        if not _event_is_addressed_to_bot(event, command, self.bot_address_names):
            return []
        instructions = self._current_instructions()
        if _has_youtube_transcript_intent(text):
            return self._youtube_transcript_actions(event, result.account_id, instructions)
        reply = build_reply(_event_to_handler_message(event), instructions, include_fallback=not instructions.openai_enabled)
        if reply is None:
            openai_actions = self._openai_actions(event, result.account_id, instructions)
            if openai_actions:
                return openai_actions
            return []
        return [SendText(event.chat_id, reply)]

    def process_identity_flows(self, event: IncomingEvent) -> EngineResult:
        account_id = self.account_store.resolve_or_create_account(event.identity_key, display_label=event.sender_name)
        intent = parse_registration_intent(event.text)
        if intent.action in {
            RegistrationAction.ACCOUNT,
            RegistrationAction.REGISTER,
            RegistrationAction.LOGIN,
            RegistrationAction.ROTATE_SECRET,
            RegistrationAction.UNLINK_THIS_CHANNEL,
            RegistrationAction.ACCOUNT_EDIT,
            RegistrationAction.LINKED_ACCOUNTS,
            RegistrationAction.WTF_UNLINK,
        } and event.chat_type != "private":
            return EngineResult(account_id, [SendText(event.chat_id, PRIVATE_ONLY, track=False)], handled=True)

        pending_account_edit = self.state.get_pending_flow(event.instance, account_id, "account_edit")
        if pending_account_edit is not None and event.chat_type != "private":
            return EngineResult(account_id, [SendText(event.chat_id, PRIVATE_ONLY, track=False)], handled=True)

        if intent.action == RegistrationAction.NONE:
            if pending_account_edit is not None:
                return self._handle_account_edit_step(event, account_id, pending_account_edit)
            return EngineResult(account_id, [], handled=False)
        if intent.action == RegistrationAction.ACCOUNT:
            return EngineResult(account_id, [SendText(event.chat_id, self._account_text(account_id), track=False)], handled=True)
        if intent.action == RegistrationAction.LINKED_ACCOUNTS:
            return EngineResult(account_id, [SendText(event.chat_id, self._linked_accounts_text(account_id), track=False)], handled=True)
        if intent.action == RegistrationAction.REGISTER:
            return EngineResult(account_id, [SendText(event.chat_id, self._register_text(account_id), track=False)], handled=True)
        if intent.action == RegistrationAction.ROTATE_SECRET:
            _, secret = self.account_store.rotate_secret(account_id)
            return EngineResult(account_id, [SendText(event.chat_id, self._secret_text(account_id, secret, rotated=True), track=False)], handled=True)
        if intent.action == RegistrationAction.UNLINK_THIS_CHANNEL:
            unlinked_account = self.account_store.unlink_identity(event.identity_key) or account_id
            return EngineResult(unlinked_account, [SendText(event.chat_id, "Dieser Kommunikationsweg wurde vom Account getrennt.", track=False)], handled=True)
        if intent.action == RegistrationAction.WTF_UNLINK:
            return self._handle_wtf(event, account_id)
        if intent.action == RegistrationAction.LOGIN:
            if intent.needs_followup or not intent.account_id or not intent.account_secret:
                return EngineResult(
                    account_id,
                    [SendText(event.chat_id, "Bitte sende: /login <account_id> <secret>", track=False)],
                    handled=True,
                )
            return self._handle_login(event, current_account_id=account_id, target_account_id=intent.account_id, secret=intent.account_secret)
        if intent.action == RegistrationAction.ACCOUNT_EDIT:
            self.state.set_pending_flow(event.instance, account_id, "account_edit", {"step": "start"})
            return EngineResult(
                account_id,
                [SendText(event.chat_id, "Account-Bearbeitung gestartet. Was möchtest du ändern: unlink, link oder rotate_secret?", track=False)],
                handled=True,
            )
        return EngineResult(account_id, [], handled=False)

    def _handle_account_edit_step(self, event: IncomingEvent, account_id: str, pending: dict[str, object]) -> EngineResult:
        text = str(event.text or "").strip().casefold()
        step = str(pending.get("step") or "start")
        cancel_words = {"nein", "no", "cancel", "abbrechen", "stop"}
        yes_words = {"ja", "yes", "confirm", "bestätigen", "bestaetigen"}
        if text in cancel_words:
            self.state.pop_pending_flow(event.instance, account_id, "account_edit")
            return EngineResult(account_id, [SendText(event.chat_id, "Okay, ich trenne nichts.", track=False)], handled=True)
        if step == "start":
            if text in {"unlink", "trennen", "kanal trennen", "diesen kanal trennen"}:
                self.state.set_pending_flow(event.instance, account_id, "account_edit", {"step": "confirm_unlink"})
                return EngineResult(
                    account_id,
                    [SendText(event.chat_id, "Soll ich diesen Kommunikationsweg wirklich vom Account trennen? Antworte mit ja oder nein.", track=False)],
                    handled=True,
                )
            if text in {"rotate", "rotate_secret", "secret", "secret rotieren"}:
                _, secret = self.account_store.rotate_secret(account_id)
                self.state.pop_pending_flow(event.instance, account_id, "account_edit")
                return EngineResult(account_id, [SendText(event.chat_id, self._secret_text(account_id, secret, rotated=True), track=False)], handled=True)
            return EngineResult(
                account_id,
                [SendText(event.chat_id, "Bitte antworte mit unlink, rotate_secret oder abbrechen.", track=False)],
                handled=True,
            )
        if step == "confirm_unlink":
            if text in yes_words:
                unlinked_account = self.account_store.unlink_identity(event.identity_key) or account_id
                self.state.pop_pending_flow(event.instance, account_id, "account_edit")
                return EngineResult(unlinked_account, [SendText(event.chat_id, "Dieser Kommunikationsweg wurde vom Account getrennt.", track=False)], handled=True)
            return EngineResult(account_id, [SendText(event.chat_id, "Bitte antworte mit ja oder nein.", track=False)], handled=True)
        self.state.pop_pending_flow(event.instance, account_id, "account_edit")
        return EngineResult(account_id, [SendText(event.chat_id, "Account-Bearbeitung wurde zurückgesetzt.", track=False)], handled=True)

    def _account_text(self, account_id: str) -> str:
        summary = self.account_store.account_summary(account_id)
        identities = "\n".join(f"- {identity}" for identity in summary.get("linked_identities", [])) or "- keine"
        registered = "ja" if summary.get("secret_exists") else "nein"
        return f"Deine TeeBotus-Account-ID:\n{account_id}\n\nSecret vorhanden: {registered}\n\nVerknüpfte Kommunikationswege:\n{identities}"

    def _linked_accounts_text(self, account_id: str) -> str:
        summary = self.account_store.account_summary(account_id)
        identities = "\n".join(f"- {identity}" for identity in summary.get("linked_identities", [])) or "- keine"
        return f"Verknüpfte Kommunikationswege für deinen TeeBotus-Account:\n{identities}"

    def _register_text(self, account_id: str) -> str:
        try:
            _, secret = self.account_store.register_account(account_id)
        except AccountStoreError as exc:
            if "already has an active secret" not in str(exc):
                return "Account konnte wegen eines Store-/Crypto-Fehlers nicht registriert werden. Bitte spaeter erneut versuchen."
            return "Für diesen Account existiert bereits ein Secret. Ich zeige es nicht erneut. Sende /rotate_secret, wenn du ein neues Secret erzeugen willst."
        return self._secret_text(account_id, secret, rotated=False)

    def _secret_text(self, account_id: str, secret: str, *, rotated: bool) -> str:
        prefix = "Dein neues Account-Secret wurde erzeugt." if rotated else "Dein Account wurde registriert."
        return f"{prefix}\n\nAccount-ID:\n{account_id}\n\nSecret:\n{secret}\n\nSpeichere beides privat. Ich zeige dir das Secret später nicht erneut."

    def _handle_login(self, event: IncomingEvent, *, current_account_id: str, target_account_id: str, secret: str) -> EngineResult:
        try:
            result = self.account_store.link_identity(event.identity_key, target_account_id, secret, display_label=event.sender_name)
        except AccountStoreError as exc:
            if "already linked" in str(exc) or "account_edit" in str(exc):
                return EngineResult(current_account_id, [SendText(event.chat_id, "Dieser Kommunikationsweg ist bereits mit einem anderen Account verbunden. Sende /account_edit, wenn du wechseln möchtest.", track=False)], handled=True)
            return EngineResult(current_account_id, [SendText(event.chat_id, "ID oder Secret stimmt nicht.", track=False)], handled=True)
        linked_account_id = str(result["account_id"])
        if result.get("already_linked") is True:
            return EngineResult(
                linked_account_id,
                [SendText(event.chat_id, "Dieser Kommunikationsweg ist bereits mit diesem TeeBotus-Account verbunden.", track=False)],
                handled=True,
            )
        actions: list[OutgoingAction] = [
            SendText(event.chat_id, "Dieser Kommunikationsweg wurde mit deinem TeeBotus-Account verbunden.", track=False)
        ]
        old_identities = [str(value) for value in result.get("old_identity_keys", [])]
        for identity_key in old_identities:
            self.state.record_link_notification(
                instance_name=event.instance,
                account_id=linked_account_id,
                new_identity_key=event.identity_key,
                old_identity_key=identity_key,
            )
            actions.append(
                NotifyLinkedIdentity(
                    identity_key=identity_key,
                    text=LINKED_NOTICE,
                    account_id=linked_account_id,
                    new_identity_key=event.identity_key,
                )
            )
        return EngineResult(linked_account_id, actions, handled=True)

    def _handle_wtf(self, event: IncomingEvent, account_id: str) -> EngineResult:
        notification = self.state.pop_link_notification(
            instance_name=event.instance,
            account_id=account_id,
            old_identity_key=event.identity_key,
        )
        if not notification:
            if self.state.list_link_notifications(instance_name=event.instance, account_id=account_id):
                return EngineResult(
                    account_id,
                    [SendText(event.chat_id, "WTF? kann nur über einen bereits bestehenden Kommunikationsweg bestätigt werden.", track=False)],
                    handled=True,
                )
            return EngineResult(account_id, [SendText(event.chat_id, "Ich habe keine frische Account-Verknüpfung gefunden, die ich zurücknehmen kann.", track=False)], handled=True)
        new_identity = notification.get("new_identity_key", "")
        if new_identity:
            if self.account_store.get_account_for_identity(new_identity) != account_id:
                self.state.clear_link_notifications_for_new_identity(
                    instance_name=event.instance,
                    account_id=account_id,
                    new_identity_key=new_identity,
                )
                return EngineResult(
                    account_id,
                    [SendText(event.chat_id, "Die gemeldete Verknüpfung ist nicht mehr mit diesem Account verbunden; ich ändere nichts.", track=False)],
                    handled=True,
                )
            # Rotate first. If secret rotation cannot complete, keep the suspicious
            # communication path linked instead of half-unlinking without issuing a new secret.
            _, new_secret = self.account_store.rotate_secret(account_id)
            self.account_store.unlink_identity_if_linked_to(new_identity, account_id)
            self.state.clear_link_notifications_for_new_identity(
                instance_name=event.instance,
                account_id=account_id,
                new_identity_key=new_identity,
            )
        else:
            _, new_secret = self.account_store.rotate_secret(account_id)
        return EngineResult(
            account_id,
            [SendText(event.chat_id, f"Die neue Verknüpfung wurde getrennt und dein Secret wurde rotiert.\n\nNeues Secret:\n{new_secret}", track=False)],
            handled=True,
        )

    def cleanup_scope_text(self) -> str:
        return CURRENT_CHAT_CLEANUP_NOTE

    def _current_instructions(self) -> BotInstructions:
        if self._instructions is None:
            return BotInstructions()
        if callable(self._instructions):
            return self._instructions()
        return self._instructions

    def _openai_actions(self, event: IncomingEvent, account_id: str, instructions: BotInstructions) -> list[OutgoingAction]:
        text = str(event.text or "").strip()
        if not instructions.openai_enabled or (not text and not event.attachments) or text.startswith("/"):
            return []
        if self.openai_client is None:
            return [SendText(event.chat_id, instructions.openai_missing_key)]
        create_reply = getattr(self.openai_client, "create_reply", None)
        if not callable(create_reply):
            return [SendText(event.chat_id, instructions.openai_error)]
        try:
            attachment_context = _build_attachment_context(event, self.openai_client, instructions)
            response = create_reply(
                _build_openai_user_input(event, text, attachment_context),
                instructions,
                self.state.get_previous_response_id(event.instance, account_id),
            )
        except OpenAIAPIError:
            return [SendTyping(event.chat_id), SendText(event.chat_id, instructions.openai_error)]
        response_id = getattr(response, "response_id", None)
        if isinstance(response_id, str):
            self.state.set_previous_response_id(event.instance, account_id, response_id)
        response_text = str(getattr(response, "text", "") or "").strip()
        if not response_text:
            return [SendTyping(event.chat_id), SendText(event.chat_id, instructions.openai_error)]
        return [SendTyping(event.chat_id), SendText(event.chat_id, response_text)]

    def _voice_actions(self, event: IncomingEvent, instructions: BotInstructions) -> list[OutgoingAction]:
        if not instructions.openai_voice_enabled:
            return [SendText(event.chat_id, instructions.openai_voice_error)]
        if self.openai_client is None:
            return [SendText(event.chat_id, instructions.openai_missing_key)]
        create_voice = getattr(self.openai_client, "create_voice", None)
        if not callable(create_voice):
            return [SendText(event.chat_id, instructions.openai_voice_error)]
        voice_text = _extract_voice_text(event)
        if not voice_text:
            return [SendText(event.chat_id, instructions.openai_voice_usage)]
        if len(voice_text) > instructions.openai_voice_max_input_chars:
            return [
                SendText(
                    event.chat_id,
                    instructions.openai_voice_too_long.format(max_chars=instructions.openai_voice_max_input_chars),
                )
            ]
        try:
            voice = create_voice(voice_text, instructions)
        except OpenAIAPIError:
            return [SendTyping(event.chat_id), SendText(event.chat_id, instructions.openai_voice_error)]
        audio = getattr(voice, "audio", b"")
        if not isinstance(audio, bytes) or not audio:
            return [SendTyping(event.chat_id), SendText(event.chat_id, instructions.openai_voice_error)]
        filename = str(getattr(voice, "filename", "") or "voice.ogg")
        content_type = str(getattr(voice, "content_type", "") or "audio/ogg")
        return [SendTyping(event.chat_id), SendAttachment(event.chat_id, audio, filename, content_type)]

    def _youtube_transcript_actions(self, event: IncomingEvent, account_id: str, instructions: BotInstructions) -> list[OutgoingAction]:
        url = _extract_youtube_url(event.text)
        if not url:
            return [SendText(event.chat_id, "Schick mir bitte den YouTube-Link, den ich transkribieren soll.")]
        try:
            transcript, source = transcribe_youtube_video(url, local_allowed=False, instance_name=event.instance)
        except YouTubeTranscriptError as exc:
            if exc.needs_local_transcription:
                local_actions = self._youtube_local_transcript_actions(event, account_id, instructions, url)
                if local_actions is not None:
                    return local_actions
                return [
                    SendText(
                        event.chat_id,
                        "Keine YouTube-Untertitel gefunden. Lokale Transkription ist noetig.\n"
                        "Moechtest Du den Text live ausgegeben haben?\n"
                        f"Moechtest Du, dass das Ganze an dein LLM {instructions.openai_model} geht?\n"
                        "Antworte z. B. mit: /youtube_transcript <URL> live nein, llm ja",
                    )
                ]
            return [SendText(event.chat_id, f"YouTube-Transkript fehlgeschlagen: {exc}")]
        except (TimeoutError, TimeoutExpired) as exc:
            return [SendText(event.chat_id, f"YouTube-Transkript fehlgeschlagen: Timeout bei der Transkription ({exc}).")]
        return self._youtube_transcript_reply_actions(event, account_id, instructions, url, transcript, source)

    def _youtube_local_transcript_actions(
        self,
        event: IncomingEvent,
        account_id: str,
        instructions: BotInstructions,
        url: str,
    ) -> list[OutgoingAction] | None:
        live_enabled, llm_enabled = _parse_youtube_local_options(event.text, instance_name=event.instance)
        if live_enabled is None or llm_enabled is None:
            return None
        try:
            transcript, source = transcribe_youtube_video(url, local_allowed=True, live_callback=None, instance_name=event.instance)
        except YouTubeTranscriptError as exc:
            return [SendText(event.chat_id, f"YouTube-Transkript fehlgeschlagen: {exc}")]
        except (TimeoutError, TimeoutExpired) as exc:
            return [SendText(event.chat_id, f"YouTube-Transkript fehlgeschlagen: Timeout bei der Transkription ({exc}).")]
        if llm_enabled:
            return self._youtube_transcript_reply_actions(event, account_id, instructions, url, transcript, source)
        return [SendTyping(event.chat_id), SendText(event.chat_id, f"YouTube-Transkript ({source}):\n\n{transcript}")]

    def _youtube_transcript_reply_actions(
        self,
        event: IncomingEvent,
        account_id: str,
        instructions: BotInstructions,
        url: str,
        transcript: str,
        source: str,
    ) -> list[OutgoingAction]:
        if not instructions.openai_enabled:
            return [SendTyping(event.chat_id), SendText(event.chat_id, f"YouTube-Transkript ({source}):\n\n{transcript}")]
        if self.openai_client is None:
            return [SendTyping(event.chat_id), SendText(event.chat_id, instructions.openai_missing_key)]
        create_reply = getattr(self.openai_client, "create_reply", None)
        if not callable(create_reply):
            return [SendTyping(event.chat_id), SendText(event.chat_id, instructions.openai_error)]
        try:
            response = create_reply(
                _build_youtube_pipeline_text(event.text, transcript, source, url),
                instructions,
                self.state.get_previous_response_id(event.instance, account_id),
            )
        except OpenAIAPIError:
            return [SendTyping(event.chat_id), SendText(event.chat_id, instructions.openai_error)]
        response_id = getattr(response, "response_id", None)
        if isinstance(response_id, str):
            self.state.set_previous_response_id(event.instance, account_id, response_id)
        response_text = str(getattr(response, "text", "") or "").strip()
        if not response_text:
            return [SendTyping(event.chat_id), SendText(event.chat_id, instructions.openai_error)]
        return [SendTyping(event.chat_id), SendText(event.chat_id, response_text)]

    def _other_identities(self, account_id: str, current_identity_key: str) -> Iterable[str]:
        summary = self.account_store.account_summary(account_id)
        for identity_key in summary.get("linked_identities", []):
            if identity_key != current_identity_key:
                yield str(identity_key)


def redact_engine_text_for_logs(text: str) -> str:
    return redact_registration_secrets(text)


def _command_name(text: str) -> str:
    stripped = str(text or "").strip()
    if not stripped:
        return ""
    if not stripped.startswith("/"):
        return ""
    first = stripped.split(maxsplit=1)[0].casefold()
    if "@" in first:
        first = first.split("@", maxsplit=1)[0]
    return first


def _command_targets_other_bot(text: str, bot_address_names: frozenset[str]) -> bool:
    parts = str(text or "").strip().split(maxsplit=1)
    if not parts:
        return False
    first = parts[0]
    if not first.startswith("/") or "@" not in first or not bot_address_names:
        return False
    target = _normalize_address_name(first.rsplit("@", maxsplit=1)[-1])
    return bool(target and target not in bot_address_names)


def _event_is_addressed_to_bot(event: IncomingEvent, command: str, bot_address_names: frozenset[str]) -> bool:
    if event.chat_type != "group":
        return True
    if command:
        return True
    return _text_addresses_bot(event.text, bot_address_names) or _signal_mentions_bot(event.raw, bot_address_names)


def _text_addresses_bot(text: str, bot_address_names: frozenset[str]) -> bool:
    if not text.strip() or not bot_address_names:
        return False
    normalized_text = f" {_normalize_address_text(text)} "
    for name in bot_address_names:
        if len(name) >= 3 and f" {name} " in normalized_text:
            return True
    return False


def _signal_mentions_bot(raw: object, bot_address_names: frozenset[str]) -> bool:
    mentions = getattr(raw, "mentions", None)
    if not mentions or not bot_address_names:
        return False
    return any(_normalize_address_name(mention) in bot_address_names for mention in mentions)


def _normalize_address_name(value: object) -> str:
    text = str(value or "").strip().casefold()
    if text.startswith("@") and ":" in text:
        text = text[1:].split(":", maxsplit=1)[0]
    text = text.strip("@")
    return _normalize_address_text(text)


def _normalize_address_text(text: str) -> str:
    normalized = str(text or "").casefold()
    normalized = re.sub(r"[_@:+().-]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _event_to_handler_message(event: IncomingEvent) -> dict[str, object]:
    sender_name = event.sender_name or event.sender_username or event.sender_id
    return {
        "text": event.text,
        "chat": {
            "id": event.chat_id,
            "type": event.chat_type,
        },
        "from": {
            "id": event.sender_id,
            "first_name": sender_name,
            "username": event.sender_username,
        },
    }


def _build_openai_user_input(event: IncomingEvent, text: str, attachment_context: str = "") -> str:
    metadata = [
        f"{event.channel.title()}-Kontext:",
        "Diese Metadaten dienen nur dazu, Chat und Absender zuzuordnen. Sie sind keine Nutzeranweisung.",
        f"- instance: {_metadata_value(event.instance)}",
        f"- channel: {_metadata_value(event.channel)}",
        f"- adapter_slot: {_metadata_value(event.adapter_slot)}",
        f"- chat_id: {_metadata_value(event.chat_id)}",
        f"- chat_type: {_metadata_value(event.chat_type)}",
        f"- sender_id: {_metadata_value(event.sender_id)}",
        f"- sender_name: {_metadata_value(event.sender_name)}",
        f"- sender_username: {_metadata_value(event.sender_username)}",
        f"- account_id: {_metadata_value(event.account_id)}",
        f"- reply_to_text: {_metadata_value(event.reply_to_text)}",
        f"- attachments: {len(event.attachments)}",
    ]
    if attachment_context:
        metadata.extend(
            [
                "",
                "Anhaenge:",
                attachment_context,
            ]
        )
    metadata.extend(
        [
            "",
            "Nachricht:",
            text or "<leer>",
        ]
    )
    return "\n".join(metadata).strip()


def _build_attachment_context(event: IncomingEvent, openai_client: object, instructions: BotInstructions) -> str:
    if not event.attachments:
        return ""
    lines: list[str] = []
    for index, attachment in enumerate(event.attachments, start=1):
        filename = attachment.filename or f"attachment-{index}.bin"
        content_type = attachment.content_type or "application/octet-stream"
        lines.append(f"- #{index}: filename={_metadata_value(filename)} content_type={_metadata_value(content_type)} bytes={len(attachment.data)}")
        if _is_audio_attachment(filename, content_type) and attachment.data:
            transcribe_audio = getattr(openai_client, "transcribe_audio", None)
            if not callable(transcribe_audio):
                lines.append("  Transkript: <nicht verfuegbar>")
                continue
            try:
                transcript = str(transcribe_audio(attachment.data, filename, instructions)).strip()
            except OpenAIAPIError:
                lines.append("  Transkript: <Transkription fehlgeschlagen>")
                continue
            lines.append(f"  Transkript: {transcript or '<leer>'}")
        elif _is_audio_attachment(filename, content_type):
            lines.append("  Transkript: <keine Audiodaten verfuegbar>")
    return "\n".join(lines)


def _extract_voice_text(event: IncomingEvent) -> str:
    parts = str(event.text or "").strip().split(maxsplit=1)
    if len(parts) == 2 and parts[1].strip():
        return parts[1].strip()
    return str(event.reply_to_text or "").strip()


def _is_audio_attachment(filename: str, content_type: str) -> bool:
    normalized_content_type = str(content_type or "").casefold()
    if normalized_content_type.startswith("audio/"):
        return True
    lower_name = str(filename or "").casefold()
    return lower_name.endswith((".aac", ".flac", ".m4a", ".mp3", ".oga", ".ogg", ".opus", ".wav", ".webm"))


def _metadata_value(value: object) -> str:
    text = str(value if value is not None else "").strip()
    return text if text else "<leer>"



def _is_yes(text: str) -> bool:
    return str(text or "").strip().casefold() in {"ja", "j", "yes", "y", "ok", "okay", "bitte", "mach", "do it"}


def _is_no(text: str) -> bool:
    return str(text or "").strip().casefold() in {"nein", "n", "no", "abbrechen", "cancel", "stop"}

def _parse_cleanup_count(text: str) -> int | str | None:
    parts = str(text or "").strip().split(maxsplit=1)
    if len(parts) == 1:
        return "all"
    argument = parts[1].strip().casefold()
    if argument == "all":
        return "all"
    try:
        count = int(argument)
    except ValueError:
        return None
    if count < 1:
        return None
    return count
