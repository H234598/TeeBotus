from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from TeeBotus.core.registration import RegistrationAction, RegistrationIntent, parse_registration_intent
from TeeBotus.runtime.accounts import AccountStore, AccountStoreError
from TeeBotus.runtime.actions import NotifyLinkedIdentity, OutgoingAction, SendText
from TeeBotus.runtime.events import IncomingEvent
from TeeBotus.runtime.state import RuntimeStateStore

LINK_WTF_FLOW = "link_wtf"
LINKED_NOTICE = "Ein neuer Kommunikationsweg wurde mit deinem TeeBotus-Account verbunden. Wenn du das nicht warst, schreibe innerhalb der Sicherheitsfrist: WTF?"


@dataclass(frozen=True)
class AccountCommandResult:
    handled: bool
    actions: tuple[OutgoingAction, ...] = ()


class AccountCommandHandler:
    def __init__(self, store: AccountStore, state: RuntimeStateStore, admin_checker: Callable[[str, str], bool] | None = None) -> None:
        self.store = store
        self.state = state
        self.admin_checker = admin_checker

    @staticmethod
    def _reply(chat_id: str, text: str) -> SendText:
        return SendText(chat_id, text, track=False)

    def handle(self, event: IncomingEvent) -> AccountCommandResult:
        if not event.account_id:
            event = event.with_account(self.store.resolve_or_create_account(event.identity_key, display_label=event.sender_name))
        intent = parse_registration_intent(event.text)
        if intent.action == RegistrationAction.WTF_UNLINK and not event.is_private:
            return AccountCommandResult(True, (self._reply(event.chat_id, "Bitte privat."),))
        if intent.action == RegistrationAction.WTF_UNLINK:
            return self._handle_wtf(event)
        if intent.action == RegistrationAction.NONE:
            return AccountCommandResult(False)
        if not event.is_private and intent.action in {
            RegistrationAction.ACCOUNT,
            RegistrationAction.REGISTER,
            RegistrationAction.LOGIN,
            RegistrationAction.ROTATE_SECRET,
            RegistrationAction.ACCOUNT_EDIT,
            RegistrationAction.LINKED_ACCOUNTS,
            RegistrationAction.UNLINK_THIS_CHANNEL,
        }:
            return AccountCommandResult(True, (self._reply(event.chat_id, "Bitte privat."),))
        if intent.action == RegistrationAction.ACCOUNT:
            return self._account(event)
        if intent.action == RegistrationAction.REGISTER:
            return self._register(event)
        if intent.action == RegistrationAction.LOGIN:
            return self._login(event, intent)
        if intent.action == RegistrationAction.ROTATE_SECRET:
            return self._rotate_secret(event)
        if intent.action == RegistrationAction.UNLINK_THIS_CHANNEL:
            return self._unlink(event)
        if intent.action == RegistrationAction.ACCOUNT_EDIT:
            self.state.set_pending_flow(event.instance, event.account_id, "account_edit", {"step": "start", "identity_key": event.identity_key, "chat_id": event.chat_id})
            return AccountCommandResult(True, (self._reply(event.chat_id, "Account-Bearbeitung gestartet. Welchen Kommunikationsweg möchtest du ändern?"),))
        if intent.action == RegistrationAction.LINKED_ACCOUNTS:
            return self._linked(event)
        if intent.needs_followup:
            return AccountCommandResult(True, (self._reply(event.chat_id, "Bitte sende deine Account-ID und dein Secret im Privatchat."),))
        return AccountCommandResult(False)

    def _account(self, event: IncomingEvent) -> AccountCommandResult:
        summary = self.store.account_summary(event.account_id)
        lines = [f"Account-ID: {event.account_id}", "", "Verknüpfte Kommunikationswege:"]
        linked = summary.get("linked_identities", [])
        if isinstance(linked, list) and linked:
            lines.extend(f"- {identity}" for identity in linked)
        else:
            lines.append("- keine")
        lines.append("")
        lines.append("Secret vorhanden: ja" if summary.get("secret_exists") else "Secret vorhanden: nein")
        admin_status = False
        if self.admin_checker is not None:
            try:
                admin_status = bool(self.admin_checker(event.instance, event.account_id))
            except (AccountStoreError, OSError, ValueError):
                admin_status = False
        lines.append("Admin: ja" if admin_status else "Admin: nein")
        return AccountCommandResult(True, (self._reply(event.chat_id, "\n".join(lines)),))

    def _register(self, event: IncomingEvent) -> AccountCommandResult:
        try:
            _, secret = self.store.register_account(event.account_id)
        except AccountStoreError as exc:
            if "active secret" in str(exc):
                return AccountCommandResult(True, (self._reply(event.chat_id, "Für diesen Account existiert bereits ein Secret. Ich zeige es nicht erneut. Sende /rotate_secret, wenn du ein neues Secret erzeugen willst."),))
            return AccountCommandResult(True, (self._reply(event.chat_id, "Account-Registrierung konnte gerade nicht abgeschlossen werden."),))
        return AccountCommandResult(True, (self._reply(event.chat_id, f"Deine TeeBotus-Account-ID:\n{event.account_id}\n\nDein privates Account-Secret:\n{secret}\n\nSpeichere beides privat. Ich zeige dir das Secret später nicht erneut."),))

    def _login(self, event: IncomingEvent, intent: RegistrationIntent) -> AccountCommandResult:
        if intent.needs_followup or not intent.account_id or not intent.account_secret:
            return AccountCommandResult(True, (self._reply(event.chat_id, "Bitte sende im Privatchat: /login <account_id> <secret>"),))
        if self.store.get_account_for_identity(event.identity_key) == intent.account_id:
            if self.store.verify_secret(intent.account_id, intent.account_secret):
                return AccountCommandResult(True, (self._reply(event.chat_id, "Dieser Kommunikationsweg ist bereits mit diesem TeeBotus-Account verbunden."),))
        try:
            result = self.store.link_identity(event.identity_key, intent.account_id, intent.account_secret, display_label=event.identity_key)
        except AccountStoreError as exc:
            if "already linked" in str(exc) or "account_edit" in str(exc):
                return AccountCommandResult(True, (self._reply(event.chat_id, "Dieser Kommunikationsweg ist bereits mit einem anderen Account verbunden. Sende /account_edit, wenn du wechseln möchtest."),))
            return AccountCommandResult(
                True,
                (
                    self._reply(
                        event.chat_id,
                        "ID oder Secret stimmt nicht. Account-IDs und Secrets gelten pro Bot-Instanz; nutze die Daten aus genau diesem Bot.",
                    ),
                ),
            )
        if result.get("already_linked") is True:
            return AccountCommandResult(True, (self._reply(event.chat_id, "Dieser Kommunikationsweg ist bereits mit diesem TeeBotus-Account verbunden."),))
        actions: list[OutgoingAction] = [self._reply(event.chat_id, "Dieser Kommunikationsweg wurde mit deinem TeeBotus-Account verbunden.")]
        for old_identity in result.get("old_identity_keys", []):
            self.state.record_link_notification(
                instance_name=event.instance,
                account_id=str(result["account_id"]),
                new_identity_key=event.identity_key,
                old_identity_key=str(old_identity),
            )
            actions.append(
                NotifyLinkedIdentity(
                    identity_key=str(old_identity),
                    text=LINKED_NOTICE,
                    account_id=str(result["account_id"]),
                    new_identity_key=event.identity_key,
                )
            )
        return AccountCommandResult(True, tuple(actions))

    def _rotate_secret(self, event: IncomingEvent) -> AccountCommandResult:
        _, secret = self.store.rotate_secret(event.account_id)
        return AccountCommandResult(True, (self._reply(event.chat_id, f"Neues Account-Secret:\n{secret}\n\nDas alte Secret ist ab sofort ungültig."),))

    def _unlink(self, event: IncomingEvent) -> AccountCommandResult:
        account_id = self.store.unlink_identity(event.identity_key)
        if account_id is None:
            return AccountCommandResult(True, (self._reply(event.chat_id, "Dieser Kommunikationsweg war mit keinem Account verknüpft."),))
        return AccountCommandResult(True, (self._reply(event.chat_id, "Dieser Kommunikationsweg wurde vom Account getrennt."),))

    def _linked(self, event: IncomingEvent) -> AccountCommandResult:
        return self._account(event)

    def _handle_wtf(self, event: IncomingEvent) -> AccountCommandResult:
        notification = self.state.pop_link_notification(
            instance_name=event.instance,
            account_id=event.account_id,
            old_identity_key=event.identity_key,
        )
        if not notification:
            if self.state.list_link_notifications(instance_name=event.instance, account_id=event.account_id):
                return AccountCommandResult(True, (self._reply(event.chat_id, "WTF? kann nur über einen bereits bestehenden Kommunikationsweg bestätigt werden."),))
            return AccountCommandResult(True, (self._reply(event.chat_id, "Ich habe keine frische Account-Verknüpfung gefunden, die ich zurücknehmen kann."),))
        linked_identity = str(notification.get("new_identity_key") or "")
        if linked_identity:
            linked_account = self.store.get_account_for_identity(linked_identity)
            if linked_account != event.account_id:
                self.state.clear_link_notifications_for_new_identity(
                    instance_name=event.instance,
                    account_id=event.account_id,
                    new_identity_key=linked_identity,
                )
                return AccountCommandResult(True, (self._reply(event.chat_id, "Diese neue Verknüpfung ist nicht mehr mit diesem Account verbunden. Ich habe nichts getrennt und dein Secret nicht rotiert."),))
            # Rotate first. If secret rotation cannot complete, keep the suspicious
            # link intact instead of half-unlinking the account without issuing a new secret.
            _, secret = self.store.rotate_secret(event.account_id)
            self.store.unlink_identity(linked_identity)
            self.state.clear_link_notifications_for_new_identity(
                instance_name=event.instance,
                account_id=event.account_id,
                new_identity_key=linked_identity,
            )
        else:
            _, secret = self.store.rotate_secret(event.account_id)
        self.state.append_security_event({"event": "wtf_unlink", "instance": event.instance, "account_id": event.account_id, "linked_identity": linked_identity})
        return AccountCommandResult(True, (self._reply(event.chat_id, f"Der neue Kommunikationsweg wurde getrennt. Dein Secret wurde automatisch rotiert. Neues Secret:\n{secret}"),))


def _is_wtf(text: str) -> bool:
    return str(text or "").strip().casefold() in {"wtf", "wtf?", "das war ich nicht", "ich war das nicht"}
