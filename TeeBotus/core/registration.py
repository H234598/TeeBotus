from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

SHA512_HEX_RE = re.compile(r"(?<![0-9a-fA-F])([0-9a-fA-F]{128})(?![0-9a-fA-F])")
SENSITIVE_PAIR_RE = re.compile(
    r"(?P<id>[0-9a-fA-F]{128}).{0,80}?(?P<secret>[0-9a-fA-F]{128})",
    re.DOTALL,
)


class RegistrationAction(str, Enum):
    NONE = "none"
    ACCOUNT = "account"
    REGISTER = "register"
    LOGIN = "login"
    ROTATE_SECRET = "rotate_secret"
    UNLINK_THIS_CHANNEL = "unlink_this_channel"
    ACCOUNT_EDIT = "account_edit"
    LINKED_ACCOUNTS = "linked_accounts"
    WTF_UNLINK = "wtf_unlink"


@dataclass(frozen=True)
class RegistrationIntent:
    action: RegistrationAction
    account_id: str = ""
    account_secret: str = ""
    needs_followup: bool = False


def parse_registration_intent(text: str) -> RegistrationIntent:
    value = str(text or "").strip()
    if not value:
        return RegistrationIntent(RegistrationAction.NONE)

    command = _command_name(value)
    if command in {"/account", "/konto"}:
        return RegistrationIntent(RegistrationAction.ACCOUNT)
    if command in {"/register", "/registrieren"}:
        return RegistrationIntent(RegistrationAction.REGISTER)
    if command in {"/rotate_secret", "/secret_rotieren"}:
        return RegistrationIntent(RegistrationAction.ROTATE_SECRET)
    if command in {"/unlink_this_channel", "/kanal_trennen"}:
        return RegistrationIntent(RegistrationAction.UNLINK_THIS_CHANNEL)
    if command in {"/account_edit", "/konto_bearbeiten"}:
        return RegistrationIntent(RegistrationAction.ACCOUNT_EDIT)
    if command in {"/linked_accounts", "/verknuepfungen", "/verknüpfungen"}:
        return RegistrationIntent(RegistrationAction.LINKED_ACCOUNTS)
    if command in {"/login", "/link", "/anmelden", "/verknuepfen", "/verknüpfen"}:
        tokens = _sha512_tokens(value)
        if len(tokens) >= 2:
            return RegistrationIntent(RegistrationAction.LOGIN, tokens[0], tokens[1])
        return RegistrationIntent(RegistrationAction.LOGIN, needs_followup=True)

    if _is_wtf(value):
        return RegistrationIntent(RegistrationAction.WTF_UNLINK)

    tokens = _sha512_tokens(value)
    lowered = value.casefold()
    if len(tokens) >= 2 and _contains_any(lowered, ["secret", "geheim", "account", "konto", "id", "verbinden", "verknuepf", "verknüpf", "login", "anmelden"]):
        return RegistrationIntent(RegistrationAction.LOGIN, tokens[0], tokens[1])
    if _contains_any(lowered, ["registrier", "registrieren", "account erstellen", "konto erstellen", "konto anlegen"]):
        return RegistrationIntent(RegistrationAction.REGISTER)
    if _contains_any(lowered, ["account verbinden", "konto verbinden", "messenger verbinden", "verknuepf", "verknüpf", "id und secret", "id und geheim"]):
        return RegistrationIntent(RegistrationAction.LOGIN, needs_followup=len(tokens) < 2)
    if _contains_any(lowered, ["account anzeigen", "konto anzeigen", "meine account id", "meine konto id"]):
        return RegistrationIntent(RegistrationAction.ACCOUNT)
    return RegistrationIntent(RegistrationAction.NONE)


def redact_registration_secrets(text: str) -> str:
    """Redact likely account id/secret pairs from logs and learned parser traces."""
    value = str(text or "")

    def redact_pair(match: re.Match[str]) -> str:
        return "<ACCOUNT_ID_REDACTED> <ACCOUNT_SECRET_REDACTED>"

    value = SENSITIVE_PAIR_RE.sub(redact_pair, value)
    tokens = _sha512_tokens(value)
    for token in tokens:
        value = value.replace(token, "<SHA512_TOKEN_REDACTED>")
        value = value.replace(token.upper(), "<SHA512_TOKEN_REDACTED>")
    return value


def _command_name(text: str) -> str:
    first = text.split(maxsplit=1)[0].strip().casefold()
    if "@" in first:
        first = first.split("@", maxsplit=1)[0]
    return first


def _sha512_tokens(text: str) -> list[str]:
    return [match.group(1).lower() for match in SHA512_HEX_RE.finditer(text)]


def _contains_any(value: str, needles: list[str]) -> bool:
    return any(needle in value for needle in needles)


def _is_wtf(value: str) -> bool:
    normalized = re.sub(r"[^a-zA-ZäöüÄÖÜß?]+", " ", value).strip().casefold()
    return normalized in {"wtf", "wtf?", "das war ich nicht", "ich war das nicht"}
