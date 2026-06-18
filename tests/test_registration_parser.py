from __future__ import annotations

from TeeBotus.core.registration import RegistrationAction, parse_registration_intent, redact_registration_secrets

TOKEN_A = "a" * 128
TOKEN_B = "b" * 128


def test_login_command_extracts_id_and_secret():
    intent = parse_registration_intent(f"/login {TOKEN_A} {TOKEN_B}")

    assert intent.action == RegistrationAction.LOGIN
    assert intent.account_id == TOKEN_A
    assert intent.account_secret == TOKEN_B
    assert not intent.needs_followup


def test_login_command_extracts_id_and_secret_from_wrappers_and_labels():
    intent = parse_registration_intent(f"/login <ID: {TOKEN_A}> <Secret: {TOKEN_B}>")

    assert intent.action == RegistrationAction.LOGIN
    assert intent.account_id == TOKEN_A
    assert intent.account_secret == TOKEN_B
    assert not intent.needs_followup


def test_free_text_registration_and_linking_intents():
    assert parse_registration_intent("Ich möchte mich registrieren").action == RegistrationAction.REGISTER
    link_intent = parse_registration_intent("Ich möchte meinen Account verbinden")
    assert link_intent.action == RegistrationAction.LOGIN
    assert link_intent.needs_followup


def test_account_commands_and_wtf():
    assert parse_registration_intent("/account").action == RegistrationAction.ACCOUNT
    assert parse_registration_intent("/rotate_secret").action == RegistrationAction.ROTATE_SECRET
    assert parse_registration_intent("WTF?").action == RegistrationAction.WTF_UNLINK


def test_redacts_sha512_tokens():
    redacted = redact_registration_secrets(f"Meine ID ist {TOKEN_A} und Secret ist {TOKEN_B}")

    assert TOKEN_A not in redacted
    assert TOKEN_B not in redacted
    assert "REDACTED" in redacted
