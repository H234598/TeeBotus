from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from TeeBotus.core.registration import RegistrationAction, parse_registration_intent, redact_registration_secrets
from TeeBotus.runtime.accounts import AccountStore, AccountStoreError
from TeeBotus.runtime.actions import NotifyLinkedIdentity, SendText, OutgoingAction
from TeeBotus.runtime.events import IncomingEvent
from TeeBotus.runtime.state import RuntimeState

PRIVATE_ONLY = "Bitte privat."
LINKED_NOTICE = "Ein neuer Kommunikationsweg wurde mit deinem TeeBotus-Account verbunden. Wenn du das nicht warst, schreibe innerhalb der Sicherheitsfrist: WTF?"
CURRENT_CHAT_CLEANUP_NOTE = "Ich lösche nur die in diesem aktuellen Chat gemerkten Botnachrichten, nicht Nachrichten in anderen Chats oder Messengern."


@dataclass
class EngineResult:
    account_id: str
    actions: list[OutgoingAction]
    handled: bool = False


class TeeBotusEngine:
    """Channel-neutral first stage engine for account/registration commands.

    This intentionally handles only the identity-critical flows. Existing TeeBotus
    command/OpenAI logic can call this first and continue with Telegram behavior when
    ``handled`` is false.
    """

    def __init__(self, account_store: AccountStore, state: RuntimeState | None = None, message_tracker: object | None = None) -> None:
        self.account_store = account_store
        self.state = state or RuntimeState()
        self.message_tracker = message_tracker


    def process(self, event: IncomingEvent) -> list[OutgoingAction]:
        from TeeBotus.runtime.actions import DeleteTrackedMessages, SendText

        text = str(event.text or "").strip()
        command = _command_name(text)
        if command == "/cleanup":
            parsed = _parse_cleanup_count(text)
            if parsed is None:
                return [SendText(event.chat_id, "Nutzung: /cleanup N oder /cleanup all. Ich lösche dabei nur den aktuellen Chat.", track=False)]
            return [DeleteTrackedMessages(event.chat_id, parsed), SendText(event.chat_id, self.cleanup_scope_text(), track=False)]
        result = self.process_identity_flows(event)
        return result.actions

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
    first = stripped.split(maxsplit=1)[0].casefold()
    if "@" in first:
        first = first.split("@", maxsplit=1)[0]
    return first



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
