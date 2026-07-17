from __future__ import annotations

import json
import os
import re
import subprocess

import pytest

from TeeBotus import __version__
from TeeBotus.core import status as status_core
from TeeBotus.core.status import _account_memory_dir_from_store, _proactive_agent_status_lines, build_status_reply
from TeeBotus.core.youtube import _has_youtube_transcript_intent
from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.base import LLMResponse
from TeeBotus.llm.capabilities import GEMINI_INTERACTIONS_CAPABILITIES, LITELLM_TEXT_CAPABILITIES
from TeeBotus.openai_client import OpenAIAPIError, OpenAIResponse
from TeeBotus.runtime.accounts import (
    INSTANCE_STATE_ACCOUNT_ID,
    AccountStore,
    AccountStoreError,
    StaticSecretProvider,
    signal_identity_key,
    telegram_identity_key,
)
from TeeBotus.runtime.actions import DelaySeconds, DeleteTrackedMessages, ExportFile, NotifyLinkedIdentity, SendAttachment, SendText, SendTyping
from TeeBotus.runtime.admin_accounts import is_runtime_admin_account
from TeeBotus.runtime.status_auth import authorize_status_recipient, status_auth_instance_protected, status_auth_state_authorized
from TeeBotus.runtime.engine import (
    MEMORY_PAGE_LIMIT_NOTE,
    TELADI_EMERGENCY_CHAT_ID,
    TeeBotusEngine,
    _llm_conversation_scope,
    _pending_flow_matches_event,
    should_ignore_event_without_account,
)
from TeeBotus.runtime.events import IncomingAttachment, IncomingEvent, IncomingLinkPreview
from TeeBotus.runtime.qdrant import QdrantError
from TeeBotus.runtime.qdrant_memory import QdrantMemoryResult
from TeeBotus.runtime.state import RuntimeStateStore, pending_flow_scope
from TeeBotus.runtime.working_memory import WorkingMemoryStore


def store(tmp_path, instance_name: str = "Depressionsbot"):
    return AccountStore(tmp_path / "accounts", instance_name, StaticSecretProvider(b"e" * 32))


def event(
    identity_key: str,
    text: str,
    *,
    channel: str = "telegram",
    chat_type: str = "private",
    instance: str = "Depressionsbot",
    attachments: tuple[IncomingAttachment, ...] = (),
    link_previews: tuple[IncomingLinkPreview, ...] = (),
) -> IncomingEvent:
    return IncomingEvent(
        event_id=f"{channel}:1",
        instance=instance,
        channel=channel,  # type: ignore[arg-type]
        adapter_slot=1,
        account_id="",
        identity_key=identity_key,
        chat_id="chat-1",
        chat_type=chat_type,
        sender_id=identity_key,
        sender_name=identity_key,
        text=text,
        message_ref="1",
        attachments=attachments,
        link_previews=link_previews,
    )


def test_pending_flow_match_requires_original_identity() -> None:
    pending = {
        "chat_id": "chat-1",
        "channel": "telegram",
        "identity_key": "telegram:user:original",
    }

    assert _pending_flow_matches_event(pending, event("telegram:user:original", "ja"))
    assert not _pending_flow_matches_event(pending, event("telegram:user:other", "ja"))


def test_llm_conversation_scope_separates_channels_and_chat_routes() -> None:
    telegram_private = event("telegram:user:1", "Hallo", channel="telegram")
    signal_private = event("signal:uuid:1", "Hallo", channel="signal")
    telegram_group = event("telegram:user:1", "Hallo", channel="telegram", chat_type="group")

    assert _llm_conversation_scope(telegram_private) != _llm_conversation_scope(signal_private)
    assert _llm_conversation_scope(telegram_private) != _llm_conversation_scope(telegram_group)


def matrix_group_event(text: str, raw: object) -> IncomingEvent:
    return IncomingEvent(
        event_id="matrix:$event",
        instance="Depressionsbot",
        channel="matrix",
        adapter_slot=1,
        account_id="",
        identity_key="matrix:user:@alice:example",
        chat_id="!room:example",
        chat_type="group",
        sender_id="@alice:example",
        sender_name="@alice:example",
        text=text,
        message_ref="$event",
        raw=raw,
    )


def signal_group_event(text: str, raw: object) -> IncomingEvent:
    return IncomingEvent(
        event_id="signal:1",
        instance="Depressionsbot",
        channel="signal",
        adapter_slot=1,
        account_id="",
        identity_key="signal:uuid:alice",
        chat_id="group-1",
        chat_type="group",
        sender_id="alice",
        sender_name="Alice",
        text=text,
        message_ref="1",
        raw=raw,
    )


def _tokens(text: str) -> list[str]:
    return re.findall(r"\b[0-9a-f]{128}\b", text)


def test_status_auth_gate_silences_logger_user_until_code_seen(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    account_store = store(tmp_path, "TeeBotus_Logger")
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    assert engine.process(event(identity, "/help", instance="TeeBotus_Logger")) == []
    assert account_store.get_account_for_identity(identity) is None

    actions = engine.process(event(identity, "TBL, 18hhGfuu3 bitte Statuszugang aktivieren.", instance="TeeBotus_Logger"))

    assert len(actions) == 1
    assert "Statuszugang aktiviert" in actions[0].text
    account_id = account_store.get_account_for_identity(identity)
    assert account_id is not None
    assert account_store.read_status_auth_state(account_id)["authorized"] is True

    help_actions = engine.process(event(identity, "/help", instance="TeeBotus_Logger"))
    assert help_actions
    assert "Befehle" in help_actions[0].text


def test_status_auth_persistence_failure_fails_closed_in_engine(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    account_store = store(tmp_path, "TeeBotus_Logger")
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    def broken_authorize(*_args, **_kwargs):
        raise RuntimeError("auth state unavailable")

    monkeypatch.setattr("TeeBotus.runtime.status_auth.authorize_status_recipient", broken_authorize)

    actions = engine.process(event(identity, "18hhGfuu3", instance="TeeBotus_Logger"))

    assert actions == []
    account_id = account_store.get_account_for_identity(identity)
    assert account_id is not None
    assert status_auth_state_authorized(account_store, account_id) is False


def test_status_auth_identity_lookup_failure_fails_closed_in_engine(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    account_store = store(tmp_path, "TeeBotus_Logger")
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    monkeypatch.setattr(account_store, "get_account_for_identity", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("auth identity state unavailable")))

    assert engine.process(event(identity, "/help", instance="TeeBotus_Logger")) == []


def test_status_account_lookup_failure_keeps_status_available(tmp_path) -> None:
    class BrokenStatusStore:
        def get_account_for_identity(self, _identity):
            raise RuntimeError("status account lookup unavailable")

    text = build_status_reply(
        sender_id="1",
        instance_name="Depressionsbot",
        project_root=tmp_path,
        account_store=BrokenStatusStore(),  # type: ignore[arg-type]
    )

    assert "- Nutzermemory: Account nicht zugeordnet" in text


def test_status_account_directory_failure_is_diagnosed(tmp_path) -> None:
    class BrokenStatusStore:
        def account_dir(self, _account_id):
            raise RuntimeError("status account directory unavailable")

    assert _account_memory_dir_from_store(BrokenStatusStore(), "a" * 128) is None  # type: ignore[arg-type]


def test_status_proactive_health_failure_is_diagnosed() -> None:
    class BrokenStatusStore:
        def read_agent_state(self, _account_id):
            raise RuntimeError("proactive health unavailable")

    lines = _proactive_agent_status_lines(
        account_store=BrokenStatusStore(),  # type: ignore[arg-type]
        account_id="a" * 128,
        instance_name="Depressionsbot",
        proactive_model_planner="tool",
        env={},
    )

    assert "- Agent enabled: Fehler beim Lesen" in lines


def test_status_memory_backend_resolution_failure_is_diagnosed() -> None:
    class BrokenMemoryStore:
        @property
        def account_memory_backend(self):
            raise RuntimeError("memory backend unavailable")

    store_with_failure = BrokenMemoryStore()

    assert status_core.account_memory_payload_size(
        account_store=store_with_failure,  # type: ignore[arg-type]
        account_id="a" * 128,
        fallback_directory=None,
    ) is None
    assert status_core.memory_encryption_status(
        None,
        account_store=store_with_failure,  # type: ignore[arg-type]
        account_id="a" * 128,
    ) == "Datenbank-Backend nicht verfuegbar"


def test_status_memory_lock_resolution_failure_is_diagnosed() -> None:
    class BrokenMemoryStore:
        account_memory_backend = None

        def account_memory_lock(self, _account_id):
            raise RuntimeError("memory lock unavailable")

    assert status_core.account_memory_payload_size(
        account_store=BrokenMemoryStore(),  # type: ignore[arg-type]
        account_id="a" * 128,
        fallback_directory=None,
    ) is None


def test_status_index_health_reports_unexpected_account_index_failure(tmp_path, monkeypatch) -> None:
    original_store = status_core.AccountStore

    class BrokenHealthStore:
        def __init__(self, *_args, **_kwargs):
            pass

        def _read_account_profile(self, _account_id):
            return {}

        def check_structured_memory_index(self, *_args, **_kwargs):
            raise RuntimeError("structured index unavailable")

    monkeypatch.setattr(status_core, "AccountStore", BrokenHealthStore)
    account_id = "a" * 128
    account_dir = tmp_path / "instances" / "Demo" / "data" / "accounts" / "accounts" / account_id
    account_dir.mkdir(parents=True)

    lines = status_core.account_memory_index_health_lines(instance_name="Demo", project_root=tmp_path)

    assert any(account_id in line and "status=broken" in line for line in lines)
    assert status_core.AccountStore is BrokenHealthStore
    assert original_store is not status_core.AccountStore


def test_admin_flow_state_failure_is_user_visible_without_aborting_message_processing(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    calls = 0

    def fail_during_admin_flow(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        raise RuntimeError("admin flow state unavailable")

    monkeypatch.setattr(engine.state, "get_pending_flow", fail_during_admin_flow)

    result = engine.process_result(event(identity, "/ping"))

    assert result.handled is True
    assert result.actions[0].text == "Adminzugang konnte gerade nicht gelesen werden. Bitte spaeter erneut versuchen."


def test_process_result_dispatch_failure_is_user_visible_without_aborting_loop(tmp_path, monkeypatch) -> None:
    engine = TeeBotusEngine(account_store=store(tmp_path))
    identity = telegram_identity_key(1)

    monkeypatch.setattr(engine, "_process_result_inner", lambda _event: (_ for _ in ()).throw(RuntimeError("dispatcher unavailable")))

    result = engine.process_result(event(identity, "/ping"))

    assert result.handled is True
    assert result.actions[0].text == "Nachricht konnte gerade nicht verarbeitet werden. Bitte spaeter erneut versuchen."


def test_process_result_auth_gate_failure_fails_closed_without_reply(tmp_path, monkeypatch) -> None:
    engine = TeeBotusEngine(account_store=store(tmp_path))
    identity = telegram_identity_key(1)

    monkeypatch.setattr("TeeBotus.runtime.engine.evaluate_status_auth_gate", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("auth gate unavailable")))

    assert engine.process_result(event(identity, "/help")).actions == []


@pytest.mark.parametrize("state_method", ["get_previous_response_id", "set_previous_response_id"])
def test_llm_reply_survives_unexpected_local_response_state_failure(tmp_path, monkeypatch, state_method):
    class FakeOpenAIClient:
        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse("Antwort trotz Statefehler.", "resp-1", None)

    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(openai_enabled=True),
        openai_client=client,
        llm_client=client,
    )

    def fail_state(*_args, **_kwargs):
        raise RuntimeError("local response state unavailable")

    monkeypatch.setattr(engine.state, state_method, fail_state)

    actions = engine.process(event(telegram_identity_key(1), "Hallo"))

    assert any(getattr(action, "text", "") == "Antwort trotz Statefehler." for action in actions)


def test_observation_backend_failures_do_not_block_ping(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    monkeypatch.setattr("TeeBotus.runtime.engine.record_account_activity", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("activity unavailable")))
    monkeypatch.setattr("TeeBotus.runtime.engine.update_city_and_weather_context", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("weather unavailable")))
    monkeypatch.setattr("TeeBotus.runtime.engine.proactive_agent_instance_enabled", lambda _instance: True)

    actions = engine.process(event(identity, "/ping"))

    assert actions
    assert actions[0].text == "Pong"


def test_dialect_observation_backend_failure_does_not_block_addressed_message(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store, bot_address_names={"mondbot"})
    identity = telegram_identity_key(1)

    monkeypatch.setattr("TeeBotus.runtime.engine.maybe_update_tts_dialect_preference", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("dialect unavailable")))

    result = engine.process_result(event(identity, "Mondbot hallo"))

    assert len(result.actions) == 1
    assert result.actions[0].text == "Echo: Mondbot hallo"
    assert result.handled is True


def test_debug_level_warns_each_active_account_and_channel_once(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_LOG_LEVEL", "2")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    first_actions = engine.process(event(identity, "/ping"))
    second_actions = engine.process(event(identity, "/ping"))

    assert first_actions[0].text.startswith("Hinweis: Debug-Level 1/2 ist aktiv.")
    assert first_actions[1].text == "Pong"
    second_texts = [getattr(action, "text", "") for action in second_actions]
    assert "Pong" in second_texts
    assert not any(text.startswith("Hinweis: Debug-Level") for text in second_texts)


def test_status_auth_global_code_does_not_silence_non_logger_instances(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    actions = engine.process(event(identity, "/help"))

    assert actions
    assert "Befehle" in actions[0].text
    assert account_store.get_account_for_identity(identity) is not None


def test_status_auth_wildcard_protects_all_instances() -> None:
    assert status_auth_instance_protected(
        "Depressionsbot",
        env={"TEEBOTUS_STATUS_AUTH_INSTANCES": "*"},
    ) is True


def test_status_auth_does_not_trust_unverified_event_account_id(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    account_store = store(tmp_path, "TeeBotus_Logger")
    authorized_identity = telegram_identity_key(1)
    authorized_account_id = account_store.resolve_or_create_account(authorized_identity)
    authorize_status_recipient(account_store, authorized_account_id, event(authorized_identity, "authorized", instance="TeeBotus_Logger"))
    unlinked_identity = telegram_identity_key(2)
    engine = TeeBotusEngine(account_store=account_store)

    actions = engine.process(event(unlinked_identity, "/help", instance="TeeBotus_Logger").with_account(authorized_account_id))

    assert actions == []
    assert account_store.get_account_for_identity(unlinked_identity) is None


def test_free_text_status_auth_code_authorizes_runtime_admin_for_non_logger_instances(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    actions = engine.process(event(identity, "Hier ist das Secret: 18hhGfuu3"))

    account_id = account_store.get_account_for_identity(identity)
    assert account_id is not None
    assert len(actions) == 1
    assert actions[0].text == "Adminzugang aktiviert."
    assert status_auth_state_authorized(account_store, account_id) is True
    assert is_runtime_admin_account(account_store, account_id, instance_name="Depressionsbot", env={}) is True
    assert account_store.read_status_auth_state(account_id)["source"] == "runtime_admin_text_code"


def test_free_text_status_auth_code_requires_private_chat_for_non_logger_instances(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store, bot_address_names=("bot",))
    identity = telegram_identity_key(1)

    actions = engine.process(event(identity, "bot, hier ist das Secret: 18hhGfuu3", chat_type="group"))

    account_id = account_store.get_account_for_identity(identity)
    assert account_id is not None
    assert len(actions) == 1
    assert actions[0].text == "Bitte privat."
    assert status_auth_state_authorized(account_store, account_id) is False


def test_help_hides_admin_section_for_regular_accounts(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    actions = engine.process(event(identity, "/help"))

    assert len(actions) == 1
    assert "Befehle:" in actions[0].text
    assert "/admin yes|no" not in actions[0].text
    assert "/Admin-Befehle" not in actions[0].text
    assert "Admin-Befehle:" not in actions[0].text
    assert "/codex [Projekt] [Repo]" not in actions[0].text
    assert "/RouteToOpenAI" not in actions[0].text


def test_help_hides_admin_section_for_runtime_admin_accounts(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    engine.process(event(identity, "/admin yes 18hhGfuu3"))
    actions = engine.process(event(identity, "/help"))

    assert len(actions) == 1
    assert "Befehle:" in actions[0].text
    assert "/admin yes|no" not in actions[0].text
    assert "/Admin-Befehle" not in actions[0].text
    assert "Admin-Befehle:" not in actions[0].text
    assert "/codex [Projekt] [Repo]" not in actions[0].text
    assert "/RouteToOpenAI" not in actions[0].text


def test_admin_help_request_is_forbidden_for_regular_accounts(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    actions = engine.process(event(identity, "/admin-befehle"))

    assert len(actions) == 1
    assert actions[0].text == "Verboten."


def test_admin_help_request_shows_admin_section_for_runtime_admin_accounts(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    engine.process(event(identity, "/admin yes 18hhGfuu3"))
    actions = engine.process(event(identity, "/admin-befehle"))

    assert len(actions) == 1
    assert "Admin-Befehle:" in actions[0].text
    assert "/codex [Projekt] [Repo] <Prompt> - Codex in der aktuellen Session des zuletzt gemeldeten Repos fortsetzen." in actions[0].text
    assert "/RouteToOpenAI <Prompt> - Prompt direkt an OpenAI senden." in actions[0].text
    assert "/RouteToOAI <Prompt> - Kurzform fuer OpenAI-Routing." in actions[0].text
    assert "/RouteToHF <Prompt> - Prompt direkt an Hugging Face senden." in actions[0].text
    assert "/RouteToGemini <Prompt> - Prompt direkt an Gemini senden." in actions[0].text
    assert "/proactive_review - Proactive-Human-Review-Queue verwalten." in actions[0].text
    assert "/codex_index - Codex-History Index-/Obsidian-Export anstossen." in actions[0].text


def test_bare_admin_command_is_forbidden(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    actions = engine.process(event(identity, "/admin"))

    assert len(actions) == 1
    assert actions[0].text == "Verboten."


def test_account_command_shows_admin_status(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    regular_actions = engine.process(event(identity, "/account"))

    assert len(regular_actions) == 1
    assert "Admin: nein" in regular_actions[0].text

    engine.process(event(identity, "/admin yes 18hhGfuu3"))
    admin_actions = engine.process(event(identity, "/account"))

    assert len(admin_actions) == 1
    assert "Admin: ja" in admin_actions[0].text


@pytest.mark.parametrize("command", ["/account", "/linked_accounts"])
def test_account_summary_backend_failure_is_user_visible_without_aborting_flow(tmp_path, command):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    def fail_summary(_account_id):
        raise RuntimeError("summary backend unavailable")

    account_store.account_summary = fail_summary

    actions = engine.process(event(identity, command))

    assert len(actions) == 1
    assert actions[0].text == "Accountdaten konnten gerade nicht gelesen werden. Bitte spaeter erneut versuchen."


def test_direct_channel_unlink_backend_failure_is_user_visible_without_false_success(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)

    monkeypatch.setattr(account_store, "unlink_identity", lambda _identity: (_ for _ in ()).throw(RuntimeError("unlink backend unavailable")))

    result = engine.process_identity_flows(event(identity, "/unlink_this_channel"))

    assert result.account_id == account_id
    assert result.actions[0].text == "Kommunikationsweg konnte gerade nicht getrennt werden. Bitte spaeter erneut versuchen."
    assert account_store.get_account_for_identity(identity) == account_id


def test_confirmed_channel_unlink_backend_failure_keeps_pending_flow(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    engine.process_identity_flows(event(identity, "/account_edit"))
    engine.process_identity_flows(event(identity, "unlink"))

    monkeypatch.setattr(account_store, "unlink_identity", lambda _identity: (_ for _ in ()).throw(RuntimeError("unlink backend unavailable")))

    result = engine.process_identity_flows(event(identity, "ja"))

    assert result.account_id == account_id
    assert result.actions[0].text == "Kommunikationsweg konnte gerade nicht getrennt werden. Bitte spaeter erneut versuchen."
    assert engine.state.get_pending_flow("Depressionsbot", account_id, "account_edit")["step"] == "confirm_unlink"
    assert account_store.get_account_for_identity(identity) == account_id


def test_direct_channel_unlink_none_result_does_not_claim_success(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)

    monkeypatch.setattr(account_store, "unlink_identity", lambda _identity: None)

    result = engine.process_identity_flows(event(identity, "/unlink_this_channel"))

    assert result.account_id == account_id
    assert result.actions[0].text == "Kommunikationsweg konnte gerade nicht getrennt werden. Bitte spaeter erneut versuchen."
    assert account_store.get_account_for_identity(identity) == account_id


def test_confirmed_channel_unlink_none_result_keeps_pending_flow(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    engine.process_identity_flows(event(identity, "/account_edit"))
    engine.process_identity_flows(event(identity, "unlink"))
    monkeypatch.setattr(account_store, "unlink_identity", lambda _identity: None)

    result = engine.process_identity_flows(event(identity, "ja"))

    assert result.actions[0].text == "Kommunikationsweg konnte gerade nicht getrennt werden. Bitte spaeter erneut versuchen."
    assert engine.state.get_pending_flow("Depressionsbot", account_id, "account_edit")["step"] == "confirm_unlink"


def test_account_edit_pending_lookup_failure_is_user_visible(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    monkeypatch.setattr(
        engine.state,
        "get_pending_flow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("flow lookup unavailable")),
    )

    result = engine.process_identity_flows(event(identity, "normale Nachricht"))

    assert result.actions[0].text == "Account-Bearbeitung konnte gerade nicht gelesen oder vorbereitet werden. Bitte spaeter erneut versuchen."


def test_account_edit_cancel_does_not_claim_success_when_pending_state_disappears(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    engine.process_identity_flows(event(identity, "/account_edit"))

    monkeypatch.setattr(engine.state, "pop_pending_flow", lambda *_args, **_kwargs: None)

    result = engine.process_identity_flows(event(identity, "nein"))

    assert result.actions[0].text == "Account-Bearbeitung konnte gerade nicht gelesen oder vorbereitet werden. Bitte spaeter erneut versuchen."


def test_account_edit_rotation_reports_missing_cleanup_state(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    engine.process_identity_flows(event(identity, "/account_edit"))

    monkeypatch.setattr(engine.state, "pop_pending_flow", lambda *_args, **_kwargs: None)

    result = engine.process_identity_flows(event(identity, "rotate"))

    assert "Secret:" in result.actions[0].text
    assert "interne Account-Bearbeitungsstatus" in result.actions[0].text


def test_account_edit_unlink_reports_missing_cleanup_state(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    engine.process_identity_flows(event(identity, "/account_edit"))
    engine.process_identity_flows(event(identity, "unlink"))

    monkeypatch.setattr(engine.state, "pop_pending_flow", lambda *_args, **_kwargs: None)

    result = engine.process_identity_flows(event(identity, "ja"))

    assert "wurde vom Account getrennt" in result.actions[0].text
    assert "interne Bearbeitungsstatus" in result.actions[0].text
    assert account_store.get_account_for_identity(identity) is None


def test_account_edit_unknown_step_does_not_claim_reset_when_state_disappears(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    engine.state.set_pending_flow(
        "Depressionsbot",
        account_id,
        "account_edit",
        {"step": "unexpected", "chat_id": "chat-1", "channel": "telegram", "identity_key": identity},
    )
    monkeypatch.setattr(engine.state, "pop_pending_flow", lambda *_args, **_kwargs: None)

    result = engine.process_identity_flows(event(identity, "weiter"))

    assert result.actions[0].text == "Account-Bearbeitung konnte gerade nicht gelesen oder vorbereitet werden. Bitte spaeter erneut versuchen."


def test_account_edit_rotation_survives_pending_cleanup_failure(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    engine.process_identity_flows(event(identity, "/account_edit"))
    monkeypatch.setattr(engine.state, "pop_pending_flow", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("flow cleanup unavailable")))

    result = engine.process_identity_flows(event(identity, "rotate"))

    assert "Secret:" in result.actions[0].text
    assert "interne Account-Bearbeitungsstatus" in result.actions[0].text


def test_account_edit_unlink_survives_pending_cleanup_failure(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    engine.process_identity_flows(event(identity, "/account_edit"))
    engine.process_identity_flows(event(identity, "unlink"))
    monkeypatch.setattr(engine.state, "pop_pending_flow", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("flow cleanup unavailable")))

    result = engine.process_identity_flows(event(identity, "ja"))

    assert "wurde vom Account getrennt" in result.actions[0].text
    assert account_store.get_account_for_identity(identity) is None
    assert result.account_id == account_id


def test_account_edit_setup_failure_is_user_visible(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    monkeypatch.setattr(engine.state, "set_pending_flow", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("flow setup unavailable")))

    result = engine.process_identity_flows(event(identity, "/account_edit"))

    assert result.actions[0].text == "Account-Bearbeitung konnte gerade nicht gestartet werden. Bitte spaeter erneut versuchen."


def test_account_edit_unlink_confirmation_setup_failure_keeps_start_flow(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    engine.process_identity_flows(event(identity, "/account_edit"))
    monkeypatch.setattr(engine.state, "set_pending_flow", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("flow setup unavailable")))

    result = engine.process_identity_flows(event(identity, "unlink"))

    assert result.actions[0].text == "Account-Bearbeitung konnte gerade nicht gestartet werden. Bitte spaeter erneut versuchen."
    assert engine.state.get_pending_flow("Depressionsbot", account_id, "account_edit")["step"] == "start"


def test_help_admin_lookup_failure_fails_closed(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)

    def fail_admin_lookup(*_args, **_kwargs):
        raise RuntimeError("admin backend unavailable")

    monkeypatch.setattr("TeeBotus.runtime.engine.is_runtime_admin_account", fail_admin_lookup)

    assert engine._account_is_help_admin("Depressionsbot", account_id) is False


def test_account_identity_resolution_failure_is_user_visible_without_aborting_flow(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    def fail_resolution(*_args, **_kwargs):
        raise RuntimeError("identity backend unavailable")

    monkeypatch.setattr(account_store, "resolve_or_create_account", fail_resolution)

    result = engine.process_identity_flows(event(identity, "/help"))

    assert result.account_id == ""
    assert result.handled is True
    assert result.actions[0].text == "Accountdaten konnten gerade nicht geladen werden. Bitte spaeter erneut versuchen."


def test_login_malformed_backend_result_is_user_visible_without_aborting_flow(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    monkeypatch.setattr(account_store, "link_identity", lambda *_args, **_kwargs: {})

    result = engine.process_identity_flows(event(identity, f"/login {'a' * 128} {'b' * 128}"))

    assert result.actions[0].text == "Login konnte gerade nicht verarbeitet werden. Bitte spaeter erneut versuchen."


def test_login_notification_failure_does_not_negate_successful_link(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    old_identity = telegram_identity_key(1)
    new_identity = telegram_identity_key(2)
    registered = engine.process_identity_flows(event(old_identity, "/register"))
    account_id, secret = _tokens(registered.actions[0].text)

    monkeypatch.setattr(engine.state, "record_link_notification", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("notification state unavailable")))

    result = engine.process_identity_flows(event(new_identity, f"/login {account_id} {secret}"))

    assert result.actions[0].text == "Dieser Kommunikationsweg wurde mit deinem TeeBotus-Account verbunden."
    assert account_store.get_account_for_identity(new_identity) == account_id
    assert all(not isinstance(action, NotifyLinkedIdentity) for action in result.actions)


def test_wtf_notification_lookup_failure_is_user_visible_without_aborting_flow(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    monkeypatch.setattr(engine.state, "list_link_notifications", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("notification state unavailable")))

    result = engine.process_identity_flows(event(identity, "WTF?"))

    assert result.actions[0].text == "Die Sicherheitsaktion konnte gerade nicht abgeschlossen werden. Bitte spaeter erneut versuchen."


def test_wtf_notification_listing_failure_is_user_visible_without_false_noop(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    monkeypatch.setattr(engine.state, "pop_link_notification", lambda **_kwargs: None)
    monkeypatch.setattr(engine.state, "list_link_notifications", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("notification state unavailable")))

    result = engine.process_identity_flows(event(identity, "WTF?"))

    assert result.actions[0].text == "Die Sicherheitsaktion konnte gerade nicht abgeschlossen werden. Bitte spaeter erneut versuchen."


def test_status_auth_gate_is_case_insensitive_for_chat_type(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    account_store = store(tmp_path, "TeeBotus_Logger")
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    actions = engine.process(
        event(identity, "TBL, 18hhGfuu3 bitte Statuszugang aktivieren.", chat_type="Private", instance="TeeBotus_Logger")
    )

    assert len(actions) == 1
    assert "Statuszugang aktiviert" in actions[0].text


def test_status_auth_state_authorized_tolerates_non_mapping_state(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(telegram_identity_key(1))
    monkeypatch.setattr(account_store, "read_status_auth_state", lambda _account_id: [])

    assert status_auth_state_authorized(account_store, account_id) is False


def test_status_auth_opt_out_wins_over_contradictory_authorized_state(tmp_path) -> None:
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(telegram_identity_key(1))
    account_store.write_status_auth_state(
        account_id,
        {
            "schema_version": 1,
            "authorized": True,
            "admin_opt_out": True,
        },
    )

    assert status_auth_state_authorized(account_store, account_id) is False


def test_authorize_status_recipient_overwrites_non_mapping_state(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    monkeypatch.setattr(account_store, "read_status_auth_state", lambda _account_id: [])

    state = authorize_status_recipient(account_store, account_id, event(identity, "Statuszugang aktivieren"))

    assert state.get("authorized") is True
    persisted_store = AccountStore(account_store.root, account_store.instance_name, account_store.secret_provider)
    assert persisted_store.read_status_auth_state(account_id).get("authorized") is True


def test_status_auth_mutations_preserve_unreadable_state(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    writes: list[dict[str, object]] = []

    def unreadable(_account_id):
        raise RuntimeError("auth state unavailable")

    monkeypatch.setattr(account_store, "read_status_auth_state", unreadable)
    monkeypatch.setattr(account_store, "write_status_auth_state", lambda _account_id, state: writes.append(state))

    from TeeBotus.runtime.status_auth import status_auth_state_admin_opted_out

    assert status_auth_state_authorized(account_store, account_id) is False
    assert status_auth_state_admin_opted_out(account_store, account_id) is True

    with pytest.raises(RuntimeError, match="auth state unavailable"):
        authorize_status_recipient(account_store, account_id, event(identity, "Statuszugang aktivieren"))
    with pytest.raises(RuntimeError, match="auth state unavailable"):
        from TeeBotus.runtime.status_auth import deauthorize_status_recipient

        deauthorize_status_recipient(account_store, account_id, event(identity, "Adminzugang deaktivieren"))

    assert writes == []


def test_admin_command_direct_secret_authorizes_runtime_admin(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    actions = engine.process(event(identity, "/admin yes 18hhGfuu3"))

    account_id = account_store.get_account_for_identity(identity)
    assert account_id is not None
    assert len(actions) >= 1
    assert "Adminzugang aktiviert" in actions[0].text
    assert status_auth_state_authorized(account_store, account_id) is True
    assert is_runtime_admin_account(account_store, account_id, instance_name="Depressionsbot", env={}) is True
    assert account_store.read_status_auth_state(account_id)["source"] == "runtime_admin_command"


def test_admin_command_yes_waits_for_secret_and_accepts_next_private_message(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    armed = engine.process(event(identity, "/admin yes"))
    account_id = account_store.get_account_for_identity(identity)
    assert account_id is not None
    assert "Admin-Secret bitte senden" in armed[0].text
    assert engine.state.get_pending_flow("Depressionsbot", account_id, "admin_auth") is not None

    completed = engine.process(event(identity, "das secret ist 18hhGfuu3"))

    assert "Adminzugang aktiviert" in completed[0].text
    assert engine.state.get_pending_flow("Depressionsbot", account_id, "admin_auth") is None
    assert status_auth_state_authorized(account_store, account_id) is True


def test_admin_command_reports_pending_state_setup_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    monkeypatch.setattr(
        engine.state,
        "set_pending_flow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("pending state unavailable")),
    )

    actions = engine.process(event(identity, "/admin yes"))

    assert actions[0].text == "Adminzugang konnte gerade nicht gelesen oder vorbereitet werden. Bitte spaeter erneut versuchen."


def test_admin_command_does_not_authorize_when_pending_state_disappears(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    engine.process(event(identity, "/admin yes"))

    monkeypatch.setattr(engine.state, "pop_pending_flow", lambda *_args, **_kwargs: None)

    actions = engine.process(event(identity, "18hhGfuu3"))
    account_id = account_store.get_account_for_identity(identity)

    assert account_id is not None
    assert actions[0].text == "Adminzugang konnte gerade nicht gelesen oder vorbereitet werden. Bitte spaeter erneut versuchen."
    assert status_auth_state_authorized(account_store, account_id) is False


def test_admin_command_reports_pending_state_removal_failure_on_cancel(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    engine.process(event(identity, "/admin yes"))

    monkeypatch.setattr(
        engine.state,
        "pop_pending_flow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("pending state unavailable")),
    )

    actions = engine.process(event(identity, "/cancel"))

    assert actions[0].text == "Adminzugang konnte gerade nicht gelesen oder vorbereitet werden. Bitte spaeter erneut versuchen."


def test_admin_command_wrong_secret_does_not_authorize(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    actions = engine.process(event(identity, "/admin yes falsch"))

    account_id = account_store.get_account_for_identity(identity)
    assert account_id is not None
    assert "Admin-Secret stimmt nicht" in actions[0].text
    assert status_auth_state_authorized(account_store, account_id) is False
    assert is_runtime_admin_account(account_store, account_id, instance_name="Depressionsbot", env={}) is False


def test_admin_command_no_opts_out_static_admin(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    monkeypatch.setenv("TEEBOTUS_ADMIN_ACCOUNT_IDS_DEPRESSIONSBOT", account_id)

    assert is_runtime_admin_account(account_store, account_id, instance_name="Depressionsbot") is True

    actions = engine.process(event(identity, "/admin no"))

    assert "Adminzugang deaktiviert" in actions[0].text
    assert account_store.read_status_auth_state(account_id)["admin_opt_out"] is True
    assert is_runtime_admin_account(account_store, account_id, instance_name="Depressionsbot") is False


def test_admin_command_no_overrides_pending_admin_secret_flow(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    engine.process(event(identity, "/admin yes"))
    actions = engine.process(event(identity, "/admin no"))

    account_id = account_store.get_account_for_identity(identity)
    assert account_id is not None
    assert "Adminzugang deaktiviert" in actions[0].text
    assert engine.state.get_pending_flow("Depressionsbot", account_id, "admin_auth") is None
    assert account_store.read_status_auth_state(account_id)["admin_opt_out"] is True


def test_admin_can_link_account_from_other_instance(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    provider = StaticSecretProvider(b"e" * 32)
    source_store = AccountStore(
        tmp_path / "instances" / "Bote_der_Wahrheit" / "data" / "accounts",
        "Bote_der_Wahrheit",
        provider,
    )
    source_account_id = source_store.resolve_or_create_account(telegram_identity_key(999))
    _, source_secret = source_store.register_account(source_account_id)
    target_store = AccountStore(
        tmp_path / "instances" / "Depressionsbot" / "data" / "accounts",
        "Depressionsbot",
        provider,
    )
    engine = TeeBotusEngine(
        account_store=target_store,
        project_root=tmp_path,
        cross_instance_store_factory=lambda root, instance: AccountStore(root, instance, provider, create_dirs=False),
    )
    admin_identity = telegram_identity_key(1)

    engine.process(event(admin_identity, "/admin yes 18hhGfuu3"))
    actions = engine.process(event(admin_identity, f"/login {source_account_id} {source_secret}"))

    assert len(actions) == 1
    assert "instanzübergreifend" in actions[0].text
    assert "Bote_der_Wahrheit" in actions[0].text
    assert target_store.get_account_for_identity(admin_identity) == source_account_id
    summary = target_store.account_summary(source_account_id)
    assert summary["linked_identities"] == [admin_identity]
    assert summary["secret_exists"] is False


def test_non_admin_cannot_link_account_from_other_instance(tmp_path) -> None:
    provider = StaticSecretProvider(b"e" * 32)
    source_store = AccountStore(
        tmp_path / "instances" / "Bote_der_Wahrheit" / "data" / "accounts",
        "Bote_der_Wahrheit",
        provider,
    )
    source_account_id = source_store.resolve_or_create_account(telegram_identity_key(999))
    _, source_secret = source_store.register_account(source_account_id)
    target_store = AccountStore(
        tmp_path / "instances" / "Depressionsbot" / "data" / "accounts",
        "Depressionsbot",
        provider,
    )
    engine = TeeBotusEngine(
        account_store=target_store,
        project_root=tmp_path,
        cross_instance_store_factory=lambda root, instance: AccountStore(root, instance, provider, create_dirs=False),
    )
    identity = telegram_identity_key(1)

    actions = engine.process(event(identity, f"/login {source_account_id} {source_secret}"))

    assert len(actions) == 1
    assert "ID oder Secret stimmt nicht" in actions[0].text
    assert target_store.get_account_for_identity(identity) != source_account_id


def test_admin_cross_instance_login_survives_broken_source_backend(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEEBOTUS_STATUS_AUTH_CODE", "18hhGfuu3")
    provider = StaticSecretProvider(b"e" * 32)
    target_store = AccountStore(
        tmp_path / "instances" / "Depressionsbot" / "data" / "accounts",
        "Depressionsbot",
        provider,
    )
    source_accounts = tmp_path / "instances" / "Bote_der_Wahrheit" / "data" / "accounts"
    source_accounts.mkdir(parents=True)
    engine = TeeBotusEngine(
        account_store=target_store,
        project_root=tmp_path,
        cross_instance_store_factory=lambda _root, _instance: (_ for _ in ()).throw(RuntimeError("source unavailable")),
    )
    identity = telegram_identity_key(1)

    engine.process(event(identity, "/admin yes 18hhGfuu3"))
    actions = engine.process(event(identity, f"/login {'a' * 128} {'b' * 128}"))

    assert len(actions) == 1
    assert "ID oder Secret stimmt nicht" in actions[0].text


def test_login_survives_unexpected_primary_backend_failure(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    monkeypatch.setattr(account_store, "link_identity", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("login backend unavailable")))

    actions = engine.process(event(identity, f"/login {'a' * 128} {'b' * 128}"))

    assert len(actions) == 1
    assert "Login konnte gerade nicht verarbeitet werden" in actions[0].text
    assert account_store.get_account_for_identity(identity) != "a" * 128


def test_register_survives_unexpected_backend_failure_without_secret(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    monkeypatch.setattr(account_store, "register_account", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("secret backend unavailable")))

    actions = engine.process(event(identity, "/register"))

    assert len(actions) == 1
    assert "Store-/Crypto-Fehlers" in actions[0].text
    assert "Secret:" not in actions[0].text


def test_secret_rotation_commands_survive_unexpected_backend_failure(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)

    monkeypatch.setattr(account_store, "rotate_secret", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("secret backend unavailable")))

    direct = engine.process(event(identity, "/rotate_secret"))
    engine.process(event(identity, "/account_edit"))
    edited = engine.process(event(identity, "rotate"))

    assert direct[0].text == "Secret konnte gerade nicht rotiert werden. Bitte spaeter erneut versuchen."
    assert edited[0].text == direct[0].text
    assert account_store.get_account_for_identity(identity) == account_id


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


def test_wtf_security_mutation_failure_does_not_claim_success(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    first = engine.process_identity_flows(event(telegram_identity_key(1), "/register"))
    account_id, secret = _tokens(first.actions[0].text)
    old_signal = signal_identity_key(source_uuid="old-security-error")
    new_signal = signal_identity_key(source_uuid="new-security-error")

    engine.process_identity_flows(event(old_signal, f"/login {account_id} {secret}", channel="signal"))
    engine.process_identity_flows(event(new_signal, f"/login {account_id} {secret}", channel="signal"))
    monkeypatch.setattr(account_store, "unlink_identity_if_linked_to", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unlink unavailable")))

    result = engine.process_identity_flows(event(telegram_identity_key(1), "WTF?"))

    assert len(result.actions) == 1
    assert "nicht abgeschlossen" in result.actions[0].text
    assert "Neues Secret:" in result.actions[0].text
    assert account_store.get_account_for_identity(new_signal) == account_id
    assert engine.state.list_link_notifications(instance_name="Depressionsbot", account_id=account_id)


def test_wtf_does_not_claim_success_when_unlink_races_away(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    first = engine.process_identity_flows(event(telegram_identity_key(1), "/register"))
    account_id, secret = _tokens(first.actions[0].text)
    new_signal = signal_identity_key(source_uuid="new-race")

    engine.process_identity_flows(event(new_signal, f"/login {account_id} {secret}", channel="signal"))
    monkeypatch.setattr(account_store, "unlink_identity_if_linked_to", lambda *_args, **_kwargs: None)

    result = engine.process_identity_flows(event(telegram_identity_key(1), "WTF?"))

    assert "nicht abgeschlossen" in result.actions[0].text
    assert "Neues Secret:" in result.actions[0].text
    assert account_store.get_account_for_identity(new_signal) == account_id


def test_wtf_reports_secret_when_notification_cleanup_fails_after_mutation(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    first = engine.process_identity_flows(event(telegram_identity_key(1), "/register"))
    account_id, secret = _tokens(first.actions[0].text)
    new_signal = signal_identity_key(source_uuid="new-cleanup")

    engine.process_identity_flows(event(new_signal, f"/login {account_id} {secret}", channel="signal"))
    monkeypatch.setattr(engine.state, "clear_link_notifications_for_new_identity", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("cleanup unavailable")))

    result = engine.process_identity_flows(event(telegram_identity_key(1), "WTF?"))

    assert "Neues Secret:" in result.actions[0].text
    assert account_store.get_account_for_identity(new_signal) is None


def test_wtf_malformed_notification_does_not_rotate_secret(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    engine.state.record_link_notification(
        instance_name="Depressionsbot",
        account_id=account_id,
        new_identity_key="",
        old_identity_key=identity,
    )
    monkeypatch.setattr(account_store, "rotate_secret", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("malformed notification must not rotate")))

    result = engine.process_identity_flows(event(identity, "WTF?"))

    assert result.actions[0].text == "Die Sicherheitsaktion konnte gerade nicht abgeschlossen werden. Bitte spaeter erneut versuchen."


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


def test_matrix_group_event_with_structured_bot_mention_is_not_ignored() -> None:
    class Raw:
        source = {"content": {"m.mentions": {"user_ids": ["@bot:example"]}}}

    ignored = should_ignore_event_without_account(
        matrix_group_event("Kannst du helfen?", Raw()),
        bot_address_names=("@bot:example", "bot"),
    )

    assert ignored is False


def test_matrix_group_event_with_structured_other_mention_is_ignored() -> None:
    class Raw:
        source = {"content": {"m.mentions": {"user_ids": ["@other:example"]}}}

    ignored = should_ignore_event_without_account(
        matrix_group_event("Kannst du helfen?", Raw()),
        bot_address_names=("@bot:example", "bot"),
    )

    assert ignored is True


def test_signal_group_event_with_dict_bot_mention_is_not_ignored() -> None:
    class Raw:
        mentions = [{"uuid": "bot-uuid", "start": 0, "length": 4}]

    ignored = should_ignore_event_without_account(
        signal_group_event("Hallo", Raw()),
        bot_address_names=("bot-uuid",),
    )

    assert ignored is False


def test_signal_group_event_with_dict_other_mention_is_ignored() -> None:
    class Raw:
        mentions = [{"uuid": "other-uuid", "start": 0, "length": 4}]

    ignored = should_ignore_event_without_account(
        signal_group_event("Hallo", Raw()),
        bot_address_names=("bot-uuid",),
    )

    assert ignored is True


def test_engine_group_event_with_persistent_bot_alias_is_not_ignored(tmp_path) -> None:
    account_store = store(tmp_path)
    identity = matrix_group_event("Mondhase, kannst du helfen?", raw=None).identity_key
    account_id = account_store.resolve_or_create_account(identity)
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_bot_alias", "user_text": "Ich nenne dich ab jetzt Mondhase.", "bot_text": "Okay."},
    )
    engine = TeeBotusEngine(account_store=account_store, bot_address_names=("@bot:example", "bot"))

    ignored = engine.should_ignore_without_account(matrix_group_event("Mondhase, kannst du helfen?", raw=None))

    assert ignored is False


def test_engine_group_event_with_persistent_bot_abbreviation_is_not_ignored(tmp_path) -> None:
    account_store = store(tmp_path)
    incoming = signal_group_event("MH hilf mal kurz", raw=None)
    account_id = account_store.resolve_or_create_account(incoming.identity_key)
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_bot_abbrev", "user_text": "Deine Abkürzung ist MH.", "bot_text": "Okay."},
    )
    engine = TeeBotusEngine(account_store=account_store, bot_address_names=("signal:1",))

    assert engine.should_ignore_without_account(incoming) is False


def test_engine_group_event_with_generated_bot_initials_is_not_ignored(tmp_path) -> None:
    engine = TeeBotusEngine(account_store=store(tmp_path), bot_address_names=("Bote der Wahrheit",))

    ignored = engine.should_ignore_without_account(matrix_group_event("BdW, kannst du helfen?", raw=None))

    assert ignored is False


def test_engine_group_event_with_generated_two_letter_per_word_alias_is_not_ignored(tmp_path) -> None:
    engine = TeeBotusEngine(account_store=store(tmp_path), bot_address_names=("Bote der Wahrheit",))

    ignored = engine.should_ignore_without_account(matrix_group_event("BoDeWa, kannst du helfen?", raw=None))

    assert ignored is False


def test_engine_unknown_group_sender_with_alias_text_is_still_ignored(tmp_path) -> None:
    engine = TeeBotusEngine(account_store=store(tmp_path), bot_address_names=("@bot:example", "bot"))

    ignored = engine.should_ignore_without_account(matrix_group_event("Mondhase, kannst du helfen?", raw=None))

    assert ignored is True


def test_matrix_command_targeting_bot_full_user_id_is_not_ignored() -> None:
    ignored = should_ignore_event_without_account(
        matrix_group_event("/ping@bot:example", raw=None),
        bot_address_names=("@bot:example", "bot"),
    )

    assert ignored is False


def test_matrix_command_targeting_generated_initials_is_not_ignored() -> None:
    ignored = should_ignore_event_without_account(
        matrix_group_event("/ping@BdW", raw=None),
        bot_address_names=("Bote der Wahrheit",),
    )

    assert ignored is False


def test_matrix_command_targeting_other_full_user_id_is_ignored() -> None:
    ignored = should_ignore_event_without_account(
        matrix_group_event("/ping@other:example", raw=None),
        bot_address_names=("@bot:example", "bot"),
    )

    assert ignored is True


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

    assert len(actions) == 19
    assert [action.text for action in actions if isinstance(action, SendText)] == ["Pong"] * 10
    assert [action.seconds for action in actions if isinstance(action, DelaySeconds)] == [1.0] * 9


def test_engine_handles_providerfehler_builtin_reply_after_identity_flows(tmp_path):
    engine = TeeBotusEngine(account_store=store(tmp_path))

    actions = engine.process(event(telegram_identity_key(1), "/Providerfehler"))

    assert len(actions) == 1
    assert actions[0].text == "Provider machen keine Fehler."


def test_engine_call_a_teladi_prompts_and_forwards_text_message(tmp_path):
    account_store = store(tmp_path)
    instructions = BotInstructions()
    engine = TeeBotusEngine(account_store=account_store, instructions=instructions)
    identity = telegram_identity_key(1)

    prompt_actions = engine.process(event(identity, "/Call_a_Teladi"))

    account_id = account_store.get_account_for_identity(identity)
    assert account_id is not None
    assert len(prompt_actions) == 1
    assert prompt_actions[0].chat_id == "chat-1"
    assert prompt_actions[0].text == instructions.teladi_call_prompt
    assert engine.state.get_pending_flow("Depressionsbot", account_id, "teladi_emergency") is not None

    sent_actions = engine.process(event(identity, "Bitte sofort melden."))

    assert len(sent_actions) == 2
    assert sent_actions[0].chat_id == TELADI_EMERGENCY_CHAT_ID
    assert "Emergency message via /Call_a_Teladi" in sent_actions[0].text
    assert f"Account: {account_id}" in sent_actions[0].text
    assert "Identity: telegram:user:1" in sent_actions[0].text
    assert "Bitte sofort melden." in sent_actions[0].text
    assert sent_actions[1].chat_id == "chat-1"
    assert sent_actions[1].text == instructions.teladi_call_sent
    assert engine.state.get_pending_flow("Depressionsbot", account_id, "teladi_emergency") is None


def test_engine_call_a_teladi_fails_closed_when_cooldown_state_cannot_persist(tmp_path, monkeypatch):
    monkeypatch.setattr("TeeBotus.runtime.engine._mark_teladi_emergency_used", lambda *_args: False)
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    instructions = BotInstructions()
    engine = TeeBotusEngine(account_store=account_store, instructions=instructions)

    actions = engine.process(event(identity, "/Call_a_Teladi"))
    account_id = account_store.get_account_for_identity(identity)

    assert actions[0].text == instructions.teladi_call_error
    assert account_id is not None
    assert engine.state.get_pending_flow("Depressionsbot", account_id, "teladi_emergency") is None


def test_engine_call_a_teladi_does_not_dispatch_stale_pending_without_cooldown(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    instructions = BotInstructions()
    engine = TeeBotusEngine(account_store=account_store, instructions=instructions)
    monkeypatch.setattr("TeeBotus.runtime.engine._mark_teladi_emergency_used", lambda *_args: False)
    monkeypatch.setattr(
        engine.state,
        "pop_pending_flow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cleanup unavailable")),
    )

    first = engine.process(event(identity, "/Call_a_Teladi"))
    second = engine.process(event(identity, "trotzdem senden"))

    assert first[0].text == instructions.teladi_call_error
    assert second[0].text == instructions.teladi_call_error
    assert all(action.chat_id != TELADI_EMERGENCY_CHAT_ID for action in second)


def test_engine_call_a_teladi_does_not_dispatch_when_pending_cleanup_fails(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    instructions = BotInstructions()
    engine = TeeBotusEngine(account_store=account_store, instructions=instructions)
    engine.process(event(identity, "/Call_a_Teladi"))

    def broken_pop(*_args, **_kwargs):
        raise RuntimeError("pending state unavailable")

    monkeypatch.setattr(engine.state, "pop_pending_flow", broken_pop)

    actions = engine.process(event(identity, "Das ist die Notfallnachricht."))

    assert actions[0].text == instructions.teladi_call_error
    assert all(action.chat_id != TELADI_EMERGENCY_CHAT_ID for action in actions)


def test_engine_call_a_teladi_reports_pending_lookup_failure(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    instructions = BotInstructions()
    engine = TeeBotusEngine(account_store=account_store, instructions=instructions)
    identity = telegram_identity_key(1)
    original_get = engine.state.get_pending_flow

    def broken_get(instance, account_id, flow_type, **kwargs):
        if flow_type == "teladi_emergency":
            raise RuntimeError("pending state unavailable")
        return original_get(instance, account_id, flow_type, **kwargs)

    monkeypatch.setattr(engine.state, "get_pending_flow", broken_get)

    actions = engine.process(event(identity, "normale Nachricht"))

    assert actions[0].text == instructions.teladi_call_error


def test_engine_call_a_teladi_cancel_does_not_claim_success_when_pending_disappears(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    engine.process(event(identity, "/Call_a_Teladi"))
    account_id = account_store.get_account_for_identity(identity)
    assert account_id is not None
    monkeypatch.setattr(engine.state, "pop_pending_flow", lambda *_args, **_kwargs: None)

    actions = engine.process(event(identity, "/cancel"))

    assert actions[0].text == BotInstructions().teladi_call_error
    assert account_store.read_agent_state(account_id)["teladi_emergency"]["used_at"]


def test_engine_call_a_teladi_cancel_reports_cooldown_backend_exception(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    engine.process(event(identity, "/Call_a_Teladi"))

    monkeypatch.setattr(
        "TeeBotus.runtime.engine._clear_teladi_emergency_cooldown",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("cooldown unavailable")),
    )

    actions = engine.process(event(identity, "/cancel"))

    assert actions[0].text == BotInstructions().teladi_call_error


def test_engine_call_a_teladi_repeated_command_uses_cooldown_without_forwarding(tmp_path):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    engine.process(event(identity, "/Call_a_Teladi"))
    actions = engine.process(event(identity, "/call_a_teladi"))

    assert len(actions) == 1
    assert actions[0].chat_id == "chat-1"
    assert "Du kannst /Call_a_Teladi erst in" in actions[0].text
    assert all(action.chat_id != TELADI_EMERGENCY_CHAT_ID for action in actions)


def test_engine_call_a_teladi_cancel_clears_pending_flow_and_cooldown(tmp_path):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    engine.process(event(identity, "/teladi"))
    account_id = account_store.get_account_for_identity(identity)
    assert account_id is not None
    assert account_store.read_agent_state(account_id)["teladi_emergency"]["used_at"]

    cancel_actions = engine.process(event(identity, "/cancel"))

    assert cancel_actions[0].text == "Call_a_Teladi abgebrochen."
    assert "used_at" not in account_store.read_agent_state(account_id)["teladi_emergency"]
    retry_actions = engine.process(event(identity, "/notfall_teladi"))

    assert retry_actions[0].text == BotInstructions().teladi_call_prompt


def test_engine_call_a_teladi_rejects_non_telegram_channel(tmp_path):
    engine = TeeBotusEngine(account_store=store(tmp_path))

    actions = engine.process(event(signal_identity_key(source_uuid="sig"), "/Call_a_Teladi", channel="signal"))

    assert len(actions) == 1
    assert actions[0].text == "Call_a_Teladi ist aktuell nur ueber Telegram angebunden."


def test_engine_uses_configured_builtin_reply_after_identity_flows(tmp_path):
    instructions = BotInstructions(commands={"/custom": "Hallo {first_name}."})
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions)

    actions = engine.process(event(telegram_identity_key(1), "/custom"))

    assert len(actions) == 1
    assert actions[0].text == "Hallo telegram:user:1."


def test_engine_codex_command_is_admin_only(tmp_path):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)

    actions = engine.process(event(telegram_identity_key(1), "/codex mach weiter"))

    assert len(actions) == 1
    assert actions[0].text == "Nein."


def test_engine_codex_admin_resumes_latest_repo_session(tmp_path, monkeypatch):
    repo = tmp_path / "TeeBotus"
    repo.mkdir()
    session_root = tmp_path / ".codex" / "sessions"
    session_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    _write_codex_session(session_root, session_id, repo)
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(telegram_identity_key(1))
    authorize_status_recipient(account_store, account_id, event(telegram_identity_key(1), "Admin"))
    account_store.write_codex_history_outbox(
        INSTANCE_STATE_ACCOUNT_ID,
        [
            {
                "id": "hist-1",
                "created_at": "2026-06-19T12:00:00+00:00",
                "updated_at": "2026-06-19T12:00:00+00:00",
                "project": {"repo_name": "TeeBotus", "repo_root": str(repo), "remote_url": ""},
                "codex": {"session_id": session_id},
                "summary": {"title": "Letzte Nachricht", "markdown": "# Test"},
            }
        ],
    )
    monkeypatch.setattr("TeeBotus.runtime.codex_command.shutil.which", lambda _name: "/usr/bin/codex")
    calls: list[dict[str, object]] = []

    def runner(args, **kwargs):
        calls.append({"args": args, **kwargs})
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    engine = TeeBotusEngine(
        account_store=account_store,
        project_root=repo,
        codex_runner=runner,
        codex_session_roots=(session_root,),
    )

    actions = engine.process(event(telegram_identity_key(1), "/codex bitte Status pruefen"))

    assert len(actions) == 2
    assert isinstance(actions[0], SendTyping)
    assert actions[1].text.startswith("Codex -> TeeBotus\nSession: cccccccc-cccc-cccc-cccc-cccccccccccc")
    assert "ok" in actions[1].text
    assert calls[0]["args"] == ["codex", "exec", "resume", session_id, "-"]
    assert calls[0]["cwd"] == str(repo)
    assert calls[0]["input"] == "bitte Status pruefen"


def test_engine_status_uses_core_status_before_configured_commands(tmp_path, monkeypatch):
    class ActiveLLMClient:
        provider_name = "litellm"
        model = "gemini/gemini-3.5-flash"
        fallback_models = ("ollama_chat/llama3.1:8b",)
        service_tier = "flex"

    class ActiveStructuredRunner:
        llm_provider = "hf_pool"
        model_name = "pool:default#structured_decision"
        llm_fallback_model = "ollama_chat/llama3.1:8b"

    monkeypatch.setenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", "Depressionsbot")
    monkeypatch.setenv("TEEBOTUS_GEMINI_FREE_TIER_ENABLED", "true")
    instructions = BotInstructions(
        commands={"/status": "Configured status."},
        openai_enabled=True,
        llm_provider="ollama",
        llm_model="llama3.1:8b",
        llm_fallback_models=("groq/llama-3.3-70b-versatile",),
        mcp_tools={
            "bibliothekar.search": {"enabled": True, "read_only": True},
            "memory.search": {"enabled": False, "read_only": True},
            "codex.exec": {"enabled": True},
        },
    )
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(telegram_identity_key(1))
    account_store.write_agent_state(
        account_id,
        {
            "schema_version": 1,
            "proactive": {"enabled": True, "paused": False},
            "consent": {"categories": ["reminder"]},
        },
    )
    account_store.append_proactive_outbox_item(account_id, {"status": "queued", "category": "reminder", "message_text": "Ping"})
    account_store.append_proactive_outbox_item(account_id, {"status": "review_pending", "category": "reminder", "message_text": "Review"})
    account_store.append_proactive_outbox_item(account_id, {"status": "dispatching", "category": "reminder", "message_text": "In flight"})
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=instructions,
        project_root=tmp_path,
        llm_client=ActiveLLMClient(),
        structured_decision_runner=ActiveStructuredRunner(),
    )

    actions = engine.process(event(telegram_identity_key(1), "/status"))

    assert len(actions) == 1
    assert "Depressionsbot Status:" in actions[0].text
    assert f"- Version: {__version__} Commits https://github.com/H234598/TeeBotus/commits/main" in actions[0].text
    assert actions[0].text_mode == "html"
    assert '<a href="https://github.com/H234598/TeeBotus/commits/main">Commits</a>' in actions[0].formatted_text
    assert "Commits:" not in actions[0].text
    assert "Wirt" not in actions[0].text
    assert "Proactive Agent" in actions[0].text
    assert "- Agent enabled: ja" in actions[0].text
    assert "- Outbox queued: 1" in actions[0].text
    assert "- Review pending: 1" in actions[0].text
    assert "- Outbox dispatching: 1" in actions[0].text
    assert "- Scheduler enabled: ja" in actions[0].text
    assert "- Model planner: tool" in actions[0].text
    assert "[Aktive LLMs]" in actions[0].text
    assert "- Chat/Text: aktiv - litellm / gemini/gemini-3.5-flash service_tier=flex" in actions[0].text
    assert (
        "- Entscheidungen/Planner: aktiv - hf_pool / pool:default#structured_decision "
        "Ersatz bei Planner-Ausfall=ollama_chat/llama3.1:8b"
    ) in actions[0].text
    assert "- Bibliothekar/Antworten: aktiv - litellm_gemini_stateful / gemini/" in actions[0].text
    assert "- Ersatzmodelle: aktiv fuer Chat/Textantworten: ollama_chat/llama3.1:8b" in actions[0].text
    assert "[API, Limits und Kosten]" in actions[0].text
    assert "- Chat/Text: litellm / gemini/gemini-3.5-flash; Key: GEMINI_API_KEY fehlt" in actions[0].text
    assert "- Entscheidungen/Planner: hf_pool / pool:default#structured_decision" in actions[0].text
    assert "- Warnung (Bibliothekar/Antworten): Gemini Stateful + Free-Tier" in actions[0].text
    assert "MCP Tools" in actions[0].text
    assert "- Read-only allowlist: bibliothekar.search" in actions[0].text
    assert "- Deaktiviert: codex.exec (nicht read-only), export.account, memory.search, youtube.transcribe" in actions[0].text
    assert "Configured status." not in actions[0].text


def test_status_reports_codex_history_queue_and_failures(tmp_path):
    account_store = store(tmp_path)
    account_store.append_codex_history_item(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "status": "queued",
            "summary_prefix": "v1.8.0 #0001",
            "project": {"repo_name": "TeeBotus"},
            "summary": {"title": "Watcher import"},
        },
    )
    account_store.append_codex_history_item(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "status": "failed",
            "summary_prefix": "v1.8.0 #0002",
            "project": {"repo_name": "TeeBotus"},
            "summary": {"title": "Dispatch fehlgeschlagen"},
        },
    )

    text = build_status_reply(
        sender_id="1",
        instance_name="Depressionsbot",
        project_root=tmp_path,
        account_store=account_store,
    )

    assert "[Projekt-History]" in text
    assert (
        "- Codex-History: status=warning queued=1 failed=1 total=2 "
        "problem_statuses=failed:1,queued:1 latest=TeeBotus v1.8.0 #0002"
    ) in text


def test_status_warns_for_stateful_gemini_free_tier_interaction_retention(tmp_path):
    class StatefulGeminiClient:
        provider_name = "litellm_gemini_stateful"
        model = "gemini/gemini-3.5-flash"

    text = build_status_reply(
        sender_id="1",
        instance_name="Depressionsbot",
        project_root=tmp_path,
        llm_enabled=True,
        llm_client=StatefulGeminiClient(),
        bibliothekar_enabled=False,
        env={},
    )

    assert "[API, Limits und Kosten]" in text
    assert (
        "- Warnung (Chat/Text): Gemini Stateful + Free-Tier: Interactions werden mit "
        "store=true/previous_interaction_id providerseitig fortgefuehrt"
    ) in text
    assert "Free-Tier-Interaction-Retention" in text


def test_status_normalizes_gemini_interactions_alias_to_litellm_stateful(tmp_path):
    class AliasGeminiClient:
        provider_name = "gemini_stateful"
        model = "gemini/gemini-3.5-flash"

    text = build_status_reply(
        sender_id="1",
        instance_name="Depressionsbot",
        project_root=tmp_path,
        llm_enabled=True,
        llm_client=AliasGeminiClient(),
        bibliothekar_enabled=False,
        env={},
    )

    assert "- Chat/Text: litellm_gemini_stateful / gemini/gemini-3.5-flash" in text
    assert "gemini_interactions / gemini/gemini-3.5-flash" not in text


def test_status_api_budget_accepts_gemini_key_ring_without_single_key(tmp_path):
    class StatefulGeminiClient:
        provider_name = "litellm_gemini_stateful"
        model = "gemini/gemini-2.5-flash"

    text = build_status_reply(
        sender_id="1",
        instance_name="Depressionsbot",
        project_root=tmp_path,
        llm_enabled=True,
        llm_client=StatefulGeminiClient(),
        bibliothekar_enabled=True,
        env={
            "GEMINI_API_KEYS_ACCOUNT_1": "gemini-a1,gemini-a2",
            "GEMINI_API_KEYS_ACCOUNT_2": "gemini-b1",
        },
    )

    assert "- Chat/Text: litellm_gemini_stateful / gemini/gemini-2.5-flash; Key: Gemini-Keyring gesetzt (3)" in text
    assert "- Bibliothekar/Antworten:" in text
    assert "Key: Gemini-Keyring gesetzt (3)" in text
    assert "Key: GEMINI_API_KEY fehlt" not in text


def test_status_bibliothekar_service_tier_uses_instance_override(tmp_path):
    text = build_status_reply(
        instance_name="Depressionsbot",
        project_root=tmp_path,
        bibliothekar_enabled=True,
        env={
            "TEEBOTUS_GEMINI_SERVICE_TIER_DEPRESSIONSBOT": "flex",
            "TEEBOTUS_GEMINI_SERVICE_TIER": "none",
        },
    )

    assert "- Bibliothekar/Antworten: aktiv - litellm_gemini_stateful / gemini/gemini-3.5-flash service_tier=flex" in text
    assert "- Bibliothekar/Antworten: litellm_gemini_stateful / gemini/gemini-3.5-flash;" in text
    assert "; service_tier=flex" in text


def test_status_api_budget_prefers_gemini_key_ring_when_single_key_is_also_set(tmp_path):
    class GeminiClient:
        provider_name = "litellm_gemini_stateless"
        model = "gemini/gemini-3.5-flash"

    text = build_status_reply(
        sender_id="1",
        instance_name="Depressionsbot",
        project_root=tmp_path,
        llm_enabled=True,
        llm_client=GeminiClient(),
        bibliothekar_enabled=False,
        env={
            "GEMINI_API_KEY": "single-key",
            "GEMINI_API_KEYS_ACCOUNT_1": "ring-a,ring-b",
        },
    )

    assert "Key: Gemini-Keyring gesetzt (2)" in text
    assert "Key: GEMINI_API_KEY gesetzt" not in text


def test_status_api_budget_uses_decision_route_metadata(tmp_path):
    class DecisionRunner:
        llm_provider = "litellm"
        model_name = "openai/gpt-5.5"
        llm_route = type(
            "Route",
            (),
            {
                "api_key_env": "OPENAI_API_KEY_DEPRESSIONSBOT_PROACTIVE_DECISION",
                "service_tier": "flex",
            },
        )()

    text = build_status_reply(
        sender_id="1",
        instance_name="Depressionsbot",
        project_root=tmp_path,
        llm_enabled=False,
        structured_decision_runner=DecisionRunner(),
        bibliothekar_enabled=False,
        env={"OPENAI_API_KEY_DEPRESSIONSBOT_PROACTIVE_DECISION": "decision-key"},
    )

    assert (
        "- Entscheidungen/Planner: litellm / openai/gpt-5.5; "
        "Key: OPENAI_API_KEY_DEPRESSIONSBOT_PROACTIVE_DECISION gesetzt; "
        "Kosten/Limits: Provider-Billing nicht abgefragt; Verbrauch: Provider-Usage wenn vorhanden; "
        "service_tier=flex"
    ) in text


def test_status_omits_stateful_gemini_retention_warning_when_free_tier_guard_is_off(tmp_path):
    class StatefulGeminiClient:
        provider_name = "litellm_gemini_stateful"
        model = "gemini/gemini-3.5-flash"

    text = build_status_reply(
        sender_id="1",
        instance_name="Depressionsbot",
        project_root=tmp_path,
        llm_enabled=True,
        llm_client=StatefulGeminiClient(),
        bibliothekar_enabled=False,
        env={"TEEBOTUS_GEMINI_FREE_TIER_ENABLED": "false"},
    )

    assert "Gemini Stateful + Free-Tier" not in text
    assert "Free-Tier-Interaction-Retention" not in text


def test_status_marks_paid_stateful_gemini_without_free_tier_warning(tmp_path):
    class PaidStatefulGeminiClient:
        provider_name = "litellm_gemini_paid_stateful"
        model = "gemini/gemini-3.5-flash"

    text = build_status_reply(
        sender_id="1",
        instance_name="Depressionsbot",
        project_root=tmp_path,
        llm_enabled=True,
        llm_client=PaidStatefulGeminiClient(),
        bibliothekar_enabled=False,
        env={},
    )

    assert "Google-Billing: paid" in text
    assert "Paid/Billing beim Provider" in text
    assert "Gemini Stateful + Free-Tier" not in text


def test_status_normalizes_paid_gemini_interactions_alias(tmp_path):
    class PaidAliasGeminiClient:
        provider_name = "gemini_paid_interactions"
        model = "gemini/gemini-3.5-flash"

    text = build_status_reply(
        sender_id="1",
        instance_name="Depressionsbot",
        project_root=tmp_path,
        llm_enabled=True,
        llm_client=PaidAliasGeminiClient(),
        bibliothekar_enabled=False,
        env={},
    )

    assert "- Chat/Text: litellm_gemini_paid_stateful / gemini/gemini-3.5-flash" in text
    assert "Google-Billing: paid" in text
    assert "Gemini Stateful + Free-Tier" not in text


def test_status_uses_central_llm_provider_aliases(tmp_path):
    class HuggingFaceAliasClient:
        provider_name = "hugging_face"
        model = "huggingface/Qwen/Qwen2.5-7B-Instruct"

    text = build_status_reply(
        sender_id="1",
        instance_name="Depressionsbot",
        project_root=tmp_path,
        llm_enabled=True,
        llm_client=HuggingFaceAliasClient(),
        bibliothekar_enabled=False,
        env={},
    )

    assert "- Chat/Text: huggingface / huggingface/Qwen/Qwen2.5-7B-Instruct" in text
    assert "HUGGINGFACE_API_KEY fehlt" in text
    assert "hugging_face / huggingface/Qwen" not in text


def test_status_google_helpers_delegate_to_central_gemini_route_logic(monkeypatch):
    monkeypatch.setattr(
        status_core,
        "route_uses_google_gemini",
        lambda *, provider, model: provider == "future_google_alias" and model == "future-model",
    )
    monkeypatch.setattr(
        status_core,
        "provider_is_paid_google_gemini",
        lambda provider: provider == "future_paid_google_alias",
    )

    assert status_core._model_uses_google("future_google_alias", "future-model") is True
    assert status_core._default_api_key_env("future_google_alias", "future-model") == "GEMINI_API_KEY"
    assert status_core._provider_is_paid_gemini("future_paid_google_alias") is True
    assert status_core._default_api_key_env("vertex_ai", "vertex_ai/gemini-3.5-flash") == "GOOGLE_APPLICATION_CREDENTIALS"


def test_engine_help_carries_formatted_release_log_link(tmp_path):
    engine = TeeBotusEngine(account_store=store(tmp_path), project_root=tmp_path)

    actions = engine.process(event(telegram_identity_key(1), "/help"))

    assert len(actions) == 1
    assert "Release Log https://github.com/H234598/TeeBotus/releases" in actions[0].text
    assert actions[0].text_mode == "html"
    assert '<a href="https://github.com/H234598/TeeBotus/releases">Release Log</a>' in actions[0].formatted_text


def test_engine_info_alias_uses_core_status_before_configured_commands(tmp_path):
    instructions = BotInstructions(commands={"/info": "Configured info."})
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, project_root=tmp_path)

    actions = engine.process(event(telegram_identity_key(1), "/info"))

    assert len(actions) == 1
    assert "Depressionsbot Status:" in actions[0].text
    assert "Configured info." not in actions[0].text


def test_engine_status_reports_unmapped_account_instead_of_zero_memory(tmp_path):
    account_store = store(tmp_path)
    existing_account_id = "a" * 128
    account_dir = account_store.account_dir(existing_account_id)
    account_dir.mkdir(parents=True, exist_ok=True)
    (account_dir / "User_Memory_Index.json").write_text('{"entries": ["mem_1"]}\n', encoding="utf-8")

    text = build_status_reply(
        sender_id="1",
        instance_name="Depressionsbot",
        project_root=tmp_path,
        account_store=account_store,
        llm_enabled=False,
        llm_provider="litellm",
        llm_model="huggingface/meta-llama/Llama-3.1-8B-Instruct",
        llm_fallback_models="groq/llama-3.3-70b-versatile,openai/gpt-4.1-mini",
    )

    assert "- Nutzermemory: Account nicht zugeordnet" in text
    assert "- Nutzermemory: 0 B" not in text
    assert "- Chat/Text: aus - litellm / huggingface/meta-llama/Llama-3.1-8B-Instruct" in text
    assert (
        "- Ersatzmodelle: nicht aktiv; bei Chat/Textantwort-Fehlern konfiguriert: "
        "groq/llama-3.3-70b-versatile, openai/gpt-4.1-mini"
    ) in text


def test_status_uses_account_memory_backend_payload_size(tmp_path):
    class Backend:
        def read_entries(self, _account_id):
            return [{"id": "mem_db", "user_text": "Mond aus der Datenbank"}]

        def read_index(self, _account_id):
            return {"index": {"entries": {"mem_db": {"kind": "observation"}}}}

        def write_entries(self, _account_id, _rows):
            return None

        def write_index(self, _account_id, _data):
            return None

    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(telegram_identity_key(1))
    account_store._account_memory_backend = Backend()
    text = build_status_reply(
        account_id=account_id,
        instance_name="Depressionsbot",
        project_root=tmp_path,
        account_store=account_store,
    )

    assert "- Nutzermemory: 0 B" not in text
    assert "- Nutzermemory:" in text
    assert "- Userfiles: Datenbank-Backend, Payloads verschluesselt" in text


def test_memory_payload_size_reads_entries_and_index_under_one_lock():
    lock_states: list[str] = []

    class Store:
        account_memory_backend = object()

        class Lock:
            def __init__(self, account_id: str):
                self.account_id = account_id

            def __enter__(self):
                lock_states.append(self.account_id)
                return self

            def __exit__(self, _exc_type, _exc_value, _traceback):
                lock_states.pop()
                return False

        def account_memory_lock(self, account_id: str):
            return self.Lock(account_id)

        def read_memory_entries(self, _account_id):
            assert lock_states == ["account"]
            return [{"id": "mem"}]

        def read_memory_index(self, _account_id):
            assert lock_states == ["account"]
            return {"index": {}}

    size = status_core.account_memory_payload_size(
        account_store=Store(),
        account_id="account",
        fallback_directory=None,
    )

    assert size is not None
    assert lock_states == []


def test_status_does_not_fallback_to_legacy_files_when_memory_backend_fails(tmp_path):
    class FailingBackend:
        last_entry_read_error = "database unavailable"
        last_index_read_error = ""

        def read_entries(self, _account_id):
            return []

        def read_index(self, _account_id):
            return {}

    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(telegram_identity_key(1))
    account_store._account_memory_backend = FailingBackend()
    account_dir = account_store.account_dir(account_id)
    (account_dir / "User_Memory_Entries.jsonl").write_text("legacy payload", encoding="utf-8")

    text = build_status_reply(
        account_id=account_id,
        instance_name="Depressionsbot",
        project_root=tmp_path,
        account_store=account_store,
    )

    assert "- Nutzermemory: nicht verfuegbar (Memory-Backend-Fehler)" in text
    assert "- Nutzermemory: 13 B" not in text


def test_status_handles_memory_backend_diagnostic_property_failure(tmp_path):
    class BrokenDiagnosticsBackend:
        @property
        def last_entry_read_error(self):
            raise RuntimeError("diagnostics unavailable")

        last_index_read_error = ""

        def read_entries(self, _account_id):
            return [{"id": "mem_db", "user_text": "Mond"}]

        def read_index(self, _account_id):
            return {}

    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(telegram_identity_key(1))
    account_store._account_memory_backend = BrokenDiagnosticsBackend()

    text = build_status_reply(
        account_id=account_id,
        instance_name="Depressionsbot",
        project_root=tmp_path,
        account_store=account_store,
    )

    assert "- Nutzermemory: nicht verfuegbar (Memory-Backend-Fehler)" in text


def test_status_does_not_treat_invalid_explicit_account_id_as_resolved(tmp_path):
    text = build_status_reply(
        account_id="../outside",
        instance_name="Depressionsbot",
        project_root=tmp_path,
    )

    assert "- Nutzermemory: Account nicht zugeordnet" in text
    assert "- Nutzermemory: 0 B" not in text


def test_memory_payload_size_does_not_mask_unreadable_json_with_file_size(tmp_path):
    class FailingJsonStore:
        account_memory_backend = None

        def read_memory_entries(self, _account_id):
            raise AccountStoreError("invalid JSONL")

        def read_memory_index(self, _account_id):
            return {}

    memory_dir = tmp_path / "account"
    memory_dir.mkdir()
    (memory_dir / "User_Memory_Entries.jsonl").write_text("unreadable payload", encoding="utf-8")

    assert status_core.account_memory_payload_size(
        account_store=FailingJsonStore(),
        account_id="account",
        fallback_directory=memory_dir,
    ) is None


def test_memory_payload_size_reports_unavailable_for_unserializable_backend_data():
    class UnserializableStore:
        account_memory_backend = object()

        def read_memory_entries(self, _account_id):
            return [{"id": "mem", "invalid": {1, 2}}]

        def read_memory_index(self, _account_id):
            return {}

    assert status_core.account_memory_payload_size(
        account_store=UnserializableStore(),
        account_id="account",
        fallback_directory=None,
    ) is None


def test_memory_payload_size_reports_unavailable_for_invalid_backend_shape():
    class InvalidShapeStore:
        account_memory_backend = object()

        def read_memory_entries(self, _account_id):
            return None

        def read_memory_index(self, _account_id):
            return {}

    assert status_core.account_memory_payload_size(
        account_store=InvalidShapeStore(),
        account_id="account",
        fallback_directory=None,
    ) is None


def test_memory_payload_size_rejects_nonfinite_backend_values():
    class NonfiniteStore:
        account_memory_backend = object()

        def read_memory_entries(self, _account_id):
            return [{"id": "mem", "score": float("inf")}]

        def read_memory_index(self, _account_id):
            return {}

    assert status_core.account_memory_payload_size(
        account_store=NonfiniteStore(),
        account_id="account",
        fallback_directory=None,
    ) is None


def test_memory_files_size_reports_unavailable_on_directory_read_error(tmp_path, monkeypatch):
    directory = tmp_path / "account"
    directory.mkdir()

    def broken_rglob(_self, _pattern):
        raise PermissionError("permission denied")

    monkeypatch.setattr(type(directory), "rglob", broken_rglob)

    assert status_core.memory_files_size(directory) is None


def test_status_memory_path_helpers_reject_traversal(tmp_path):
    account_id = "a" * 128

    assert status_core.account_memory_dir_for_account(
        account_id,
        instance_name="../outside",
        project_root=tmp_path,
    ) is None
    assert status_core.account_memory_dir_for_account(
        "../outside",
        instance_name="Demo",
        project_root=tmp_path,
    ) is None
    assert status_core.account_memory_dir_for_sender(
        "sender",
        instance_name="../outside",
        project_root=tmp_path,
    ) is None


def test_account_memory_health_uses_normalized_instance_name(tmp_path):
    project_root = tmp_path / "TeeBotus"
    account_root = project_root / "instances" / "Demo" / "data" / "accounts"
    account_store = AccountStore(account_root, "Demo", secret_provider=StaticSecretProvider(b"c" * 32))
    account_id = account_store.resolve_or_create_account(telegram_identity_key("sender"))
    account_store.write_memory_entries(account_id, [])
    account_store.write_memory_index(account_id, {})

    lines = status_core.account_memory_index_health_lines(instance_name=" Demo ", project_root=project_root)

    assert any(line.startswith(f"account_memory=Demo/{account_id} ") for line in lines)
    assert not any(line.startswith(f"account_memory= Demo /{account_id} ") for line in lines)


@pytest.mark.parametrize("error", [AccountStoreError("postgres DSN missing"), ValueError("malformed backend")])
def test_memory_encryption_status_diagnoses_backend_resolution_failure(error):
    class FailingStore:
        @property
        def account_memory_backend(self):
            raise error

    assert status_core.memory_encryption_status(None, account_store=FailingStore(), account_id="account") == "Datenbank-Backend nicht verfuegbar"


def test_memory_payload_size_diagnoses_backend_value_error():
    class FailingStore:
        @property
        def account_memory_backend(self):
            raise ValueError("malformed backend")

    assert status_core.account_memory_payload_size(
        account_store=FailingStore(),
        account_id="account",
        fallback_directory=None,
    ) is None


def test_memory_encryption_status_diagnoses_unreadable_userfiles(tmp_path, monkeypatch):
    directory = tmp_path / "account"
    directory.mkdir()
    (directory / "User_Memory_Index.json").write_text("payload", encoding="utf-8")

    def broken_read_bytes(_self):
        raise PermissionError("permission denied")

    monkeypatch.setattr(type(directory / "User_Memory_Index.json"), "read_bytes", broken_read_bytes)

    assert status_core.memory_encryption_status(directory) == "Userfiles nicht verfuegbar (Lesefehler)"


def test_memory_fallback_status_diagnoses_backend_resolution_failure():
    class FailingStore:
        @property
        def account_memory_backend(self):
            raise AccountStoreError("postgres DSN missing")

    warning = status_core._account_memory_fallback_warning(FailingStore(), "account")

    assert warning == " warning=memory_backend_unavailable:postgres DSN missing"


def test_memory_fallback_status_uses_atomic_account_snapshot():
    class Backend:
        @property
        def stale_fallback_entry_account_ids(self):
            raise AssertionError("status must use atomic fallback snapshot")

        @property
        def stale_fallback_index_account_ids(self):
            raise AssertionError("status must use atomic fallback snapshot")

        @property
        def stale_fallback_collection_account_ids(self):
            raise AssertionError("status must use atomic fallback snapshot")

        def fallback_diagnostics_for_account(self, account_id: str):
            assert account_id == "account"
            return {"entries": True, "index": False, "collections": False, "error": "fallback broken"}

    class Store:
        account_memory_backend = Backend()

    assert status_core._account_memory_fallback_warning(Store(), "account") == (
        " warning=fallback_sync_stale:entries:fallback broken"
    )


def test_engine_proactive_command_requires_instance_enablement(tmp_path, monkeypatch):
    monkeypatch.delenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", raising=False)
    monkeypatch.delenv("TEEBOTUS_PROACTIVE_AGENT_DEPRESSIONSBOT", raising=False)
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)

    actions = engine.process(event(telegram_identity_key(1), "/proactive on"))

    account_id = account_store.get_account_for_identity(telegram_identity_key(1))
    assert account_id is not None
    assert "nicht freigeschaltet" in actions[0].text
    assert account_store.read_agent_state(account_id) == {}


def test_engine_does_not_send_slash_commands_to_structured_decision_runner(tmp_path):
    account_store = store(tmp_path)

    def fail_runner(_prompt, _schema):
        raise AssertionError("structured decision runner must not be called for slash commands")

    engine = TeeBotusEngine(account_store=account_store, project_root=tmp_path, structured_decision_runner=fail_runner)

    actions = engine.process(event(telegram_identity_key(1), "/status"))

    assert actions
    assert "Status" in actions[0].text


def test_engine_proactive_command_enables_private_account_agent_when_instance_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", "Depressionsbot")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)

    actions = engine.process(event(telegram_identity_key(1), "/proactive on"))

    account_id = account_store.get_account_for_identity(telegram_identity_key(1))
    assert account_id is not None
    assert "aktiviert" in actions[0].text
    assert account_store.read_agent_state(account_id)["proactive"]["enabled"] is True


def test_engine_proactive_command_reports_storage_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", "Depressionsbot")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)

    def fail_write(*_args, **_kwargs):
        raise OSError("agent state unavailable")

    monkeypatch.setattr(account_store, "write_agent_state", fail_write)
    actions = engine.process(event(telegram_identity_key(1), "/proactive on"))

    assert len(actions) == 1
    assert "nicht gelesen oder gespeichert" in actions[0].text


def test_engine_proactive_policy_commands_update_account_state(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", "Depressionsbot")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)

    engine.process(event(telegram_identity_key(1), "/proactive on"))
    category_reply = engine.process(event(telegram_identity_key(1), "/proactive category on analysis"))[0].text
    quiet_reply = engine.process(event(telegram_identity_key(1), "/proactive quiet 22 8"))[0].text
    interval_reply = engine.process(event(telegram_identity_key(1), "/proactive interval 180"))[0].text
    pause_reply = engine.process(event(telegram_identity_key(1), "/proactive pause"))[0].text
    status_reply = engine.process(event(telegram_identity_key(1), "/proactive status"))[0].text

    account_id = account_store.get_account_for_identity(telegram_identity_key(1))
    assert account_id is not None
    state = account_store.read_agent_state(account_id)
    assert "analysis" in state["consent"]["categories"]
    assert state["policy"]["allowed_hours"] == [8, 22]
    assert state["policy"]["min_minutes_between_messages"] == 180
    assert state["proactive"]["paused"] is True
    assert "Kategorien aktualisiert" in category_reply
    assert "Erlaubtes Zeitfenster: 8-22 Uhr" in quiet_reply
    assert "180 Minuten" in interval_reply
    assert "pausiert" in pause_reply
    assert "- pausiert: ja" in status_reply
    assert "- review_pending_items: 0" in status_reply


def test_engine_proactive_command_is_private_only(tmp_path):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    group = event(telegram_identity_key(1), "/proactive on")
    group = IncomingEvent(
        event_id=group.event_id,
        instance=group.instance,
        channel=group.channel,
        adapter_slot=group.adapter_slot,
        account_id=group.account_id,
        identity_key=group.identity_key,
        chat_id="group-1",
        chat_type="group",
        sender_id=group.sender_id,
        sender_name=group.sender_name,
        text=group.text,
        message_ref=group.message_ref,
    )

    actions = engine.process(group)

    account_id = account_store.get_account_for_identity(telegram_identity_key(1))
    assert account_id is not None
    assert actions[0].text == "Bitte privat."
    assert account_store.read_agent_state(account_id) == {}


def test_engine_natural_reminder_queues_private_proactive_message(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", "Depressionsbot")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="chat-1", chat_type="private", adapter_slot=1)

    actions = engine.process(event(identity, "Erinnere mich morgen um 9 an den Termin"))

    assert "Okay, ich erinnere dich" in actions[0].text
    state = account_store.read_agent_state(account_id)
    assert state["proactive"]["enabled"] is True
    assert state["consent"]["categories"] == ["reminder"]
    rows = account_store.read_proactive_outbox(account_id)
    assert len(rows) == 1
    assert rows[0]["category"] == "reminder"
    assert rows[0]["intent"] == "user_requested_reminder"
    assert rows[0]["message_text"] == "Du wolltest erinnert werden: den Termin"
    assert rows[0]["route"]["channel"] == "telegram"
    assert rows[0]["route"]["chat_id"] == "chat-1"


def test_engine_natural_reminder_reports_unexpected_backend_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", "Depressionsbot")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="chat-1", chat_type="private", adapter_slot=1)

    def fail_reminder(*_args, **_kwargs):
        raise RuntimeError("reminder backend unavailable")

    monkeypatch.setattr("TeeBotus.runtime.engine.maybe_queue_natural_reminder", fail_reminder)
    actions = engine.process(event(identity, "Erinnere mich morgen um 9 an den Termin"))

    assert account_id == account_store.get_account_for_identity(identity)
    assert actions
    assert "Erinnerung gerade nicht speichern" in actions[0].text


def test_engine_natural_reminder_requires_instance_enablement(tmp_path, monkeypatch):
    monkeypatch.delenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", raising=False)
    monkeypatch.delenv("TEEBOTUS_PROACTIVE_AGENT_DEPRESSIONSBOT", raising=False)
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    actions = engine.process(event(identity, "Erinnere mich morgen um 9 an den Termin"))

    account_id = account_store.get_account_for_identity(identity)
    assert account_id is not None
    assert "nicht freigeschaltet" in actions[0].text
    assert account_store.read_agent_state(account_id) == {}
    assert account_store.read_proactive_outbox(account_id) == []


def test_engine_natural_reminder_requires_private_route(tmp_path, monkeypatch):
    monkeypatch.setenv("TEEBOTUS_PROACTIVE_AGENT_INSTANCES", "Depressionsbot")
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="group-1", chat_type="group", adapter_slot=1)

    actions = engine.process(event(identity, "Erinnere mich morgen um 9 an den Termin"))

    assert "privaten Chat" in actions[0].text
    assert account_store.read_proactive_outbox(account_id) == []


def test_engine_export_account_data_as_json(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="export")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.write_memory_entries(account_id, [{"id": "mem_export", "user_text": "Exportiere mich."}])
    engine = TeeBotusEngine(account_store=account_store)

    actions = engine.process(event(identity, "/export", channel="signal"))

    assert len(actions) == 1
    assert isinstance(actions[0], ExportFile)
    assert actions[0].filename.startswith("TeeBotus_account_")
    assert actions[0].filename.endswith(".json")
    assert actions[0].content_type == "application/json"
    assert b"Exportiere mich." in actions[0].data
    assert b"TMBMAP1" not in actions[0].data


def test_engine_export_account_data_respects_format_argument(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="export-md")
    account_store.resolve_or_create_account(identity)
    engine = TeeBotusEngine(account_store=account_store)

    actions = engine.process(event(identity, "/account_export md", channel="matrix"))

    assert isinstance(actions[0], ExportFile)
    assert actions[0].filename.endswith(".md")
    assert actions[0].content_type == "text/markdown"


def test_engine_export_account_data_requires_private_chat(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="export-group")
    engine = TeeBotusEngine(account_store=account_store)
    incoming = IncomingEvent(
        event_id="signal:1",
        instance="Depressionsbot",
        channel="signal",
        adapter_slot=1,
        identity_key=identity,
        chat_id="group-chat",
        chat_type="group",
        sender_id=identity,
        sender_name=identity,
        text="/export",
        message_ref="1",
    )

    actions = engine.process(incoming)

    assert actions[0].text == "Bitte privat."


def test_engine_export_account_data_rejects_unknown_format(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="export-bad")
    engine = TeeBotusEngine(account_store=account_store)

    actions = engine.process(event(identity, "/export exe", channel="signal"))

    assert "Nutzung:" in actions[0].text


def test_engine_reports_missing_llm_key_for_free_text_when_llm_enabled(tmp_path):
    instructions = BotInstructions(openai_enabled=True, llm_missing_key="LLM-Key fehlt.")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions)

    actions = engine.process(event(telegram_identity_key(1), "Hallo"))

    assert len(actions) == 1
    assert actions[0].text == "LLM-Key fehlt."


def test_engine_uses_llm_client_for_free_text_when_enabled(tmp_path):
    class FakeLLMClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.calls.append((user_text, previous_response_id))
            return OpenAIResponse("Antwort.", "resp-1", "flex")

    client = FakeLLMClient()
    instructions = BotInstructions(openai_enabled=True)
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, llm_client=client)

    actions = engine.process(event(telegram_identity_key(1), "Hallo"))

    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "Antwort."
    assert "Telegram-Kontext:" in client.calls[0][0]
    assert "Nachricht:\nHallo" in client.calls[0][0]
    assert client.calls[0][1] is None


def test_engine_prefers_llm_client_for_free_text_when_configured(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.calls = 0

        def create_reply(self, *_args, **_kwargs):
            self.calls += 1
            return OpenAIResponse("OpenAI.", "resp-openai", "flex")

    class FakeLLMClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.calls.append(user_text)
            return OpenAIResponse("LiteLLM.", None, None)

    openai_client = FakeOpenAIClient()
    llm_client = FakeLLMClient()
    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(openai_enabled=True),
        openai_client=openai_client,
        llm_client=llm_client,
    )

    actions = engine.process(event(telegram_identity_key(1), "Hallo"))

    assert actions[1].text == "LiteLLM."
    assert llm_client.calls
    assert openai_client.calls == 0


def test_engine_llm_actions_are_provider_neutral_and_openai_alias_remains(tmp_path):
    class FakeLLMClient:
        def __init__(self) -> None:
            self.calls = 0

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.calls += 1
            assert "Nachricht:\nHallo" in user_text
            assert previous_response_id is None
            return OpenAIResponse("Neutral.", None, None)

    llm_client = FakeLLMClient()
    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(openai_enabled=True),
        llm_client=llm_client,
    )
    account_id = engine.account_store.resolve_or_create_account(telegram_identity_key(1))
    incoming = event(telegram_identity_key(1), "Hallo").with_account(account_id)

    llm_actions = engine._llm_actions(incoming, account_id, BotInstructions(openai_enabled=True))
    alias_actions = engine._openai_actions(incoming, account_id, BotInstructions(openai_enabled=False))

    assert llm_actions[1].text == "Neutral."
    assert alias_actions == []
    assert llm_client.calls == 1


def test_engine_llm_reply_survives_unexpected_memory_write_failure(tmp_path, monkeypatch):
    class FakeLLMClient:
        def create_reply(self, *_args, **_kwargs):
            return OpenAIResponse("Antwort trotz Memory-Fehler.", None, None)

    account_store = store(tmp_path)
    monkeypatch.setattr(account_store, "append_structured_memory_entry", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("memory unavailable")))
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, llm_provider="openai", openai_model="gpt-5.5"),
        llm_client=FakeLLMClient(),
    )

    actions = engine.process(event(telegram_identity_key(1), "Hallo"))

    assert actions[1].text == "Antwort trotz Memory-Fehler."


def test_engine_llm_reply_survives_unexpected_memory_classifier_failure(tmp_path):
    class FakeLLMClient:
        def create_reply(self, *_args, **_kwargs):
            return OpenAIResponse("Antwort trotz Classifier-Fehler.", None, None)

    def broken_classifier(*_args, **_kwargs):
        raise RuntimeError("classifier unavailable")

    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(openai_enabled=True),
        llm_client=FakeLLMClient(),
        structured_decision_runner=broken_classifier,
    )

    actions = engine.process(event(telegram_identity_key(1), "Hallo"))

    assert actions[1].text == "Antwort trotz Classifier-Fehler."


def test_engine_runtime_llm_disabled_override_skips_missing_key_and_model_call(tmp_path):
    class FakeLLMClient:
        def create_reply(self, *_args, **_kwargs):
            raise AssertionError("runtime-disabled LLM must not be called")

    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(openai_enabled=True, text_replies={"hallo": "Regelantwort."}),
        llm_client=FakeLLMClient(),
        llm_enabled_override="false",
    )

    actions = engine.process(event(telegram_identity_key(1), "Hallo"))

    assert actions[0].text == "Regelantwort."


def test_engine_turns_openai_file_block_into_attachment(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse(
                'Hier ist die Kalenderdatei.\n[[TEE_FILE filename="termin.ics" content_type="text/calendar" caption="Termin"]]\nBEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n[[/TEE_FILE]]',
                "resp-file",
                None,
            )

    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(openai_enabled=True),
        openai_client=client,
        llm_client=client,
    )

    actions = engine.process(event(telegram_identity_key(1), "Mach mir bitte eine ICS Datei fuer morgen."))

    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "Hier ist die Kalenderdatei."
    assert isinstance(actions[2], SendAttachment)
    assert actions[2].filename == "termin.ics"
    assert actions[2].content_type == "text/calendar"
    assert actions[2].data.startswith(b"BEGIN:VCALENDAR")
    assert "Dateiausgabe:" in client.user_text


def test_engine_turns_openai_image_block_into_generated_attachment(tmp_path):
    class FakeImage:
        data = b"png-bytes"
        filename = "wetter.png"
        content_type = "image/png"

    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.prompt = ""

        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse(
                'Das Wetter ist grau, hier ist ein kleines Bild dazu.\n'
                '[[TEE_IMAGE filename="wetter.png" caption="Ein ruhiger Wetterimpuls" purpose="weather_encouragement"]]\n'
                "Ein warmes, freundliches Bild: Regen am Fenster, Tee, weiches Morgenlicht.\n"
                "[[/TEE_IMAGE]]",
                "resp-image",
                None,
            )

        def generate_image(self, prompt, _instructions, *, filename="bild.png"):
            self.prompt = prompt
            return FakeImage()

    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(openai_enabled=True, openai_image_enabled=True),
        openai_client=client,
        llm_client=client,
    )

    actions = engine.process(event(telegram_identity_key(1), "Wie ist die Stimmung bei Regen?"))

    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "Das Wetter ist grau, hier ist ein kleines Bild dazu."
    assert isinstance(actions[2], SendAttachment)
    assert actions[2].filename == "wetter.png"
    assert actions[2].content_type == "image/png"
    assert actions[2].data == b"png-bytes"
    assert actions[2].caption == "Ein ruhiger Wetterimpuls"
    assert "Regen am Fenster" in client.prompt


def test_engine_image_provider_failure_keeps_text_response(tmp_path):
    class BrokenImageClient:
        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse(
                'Textantwort.\n[[TEE_IMAGE filename="bild.png" caption="Bild"]]\nEin Bild.\n[[/TEE_IMAGE]]',
                "resp-image-error",
                None,
            )

        def generate_image(self, _prompt, _instructions, *, filename="bild.png"):
            raise RuntimeError("image provider unavailable")

    instructions = BotInstructions(openai_enabled=True, openai_image_enabled=True)
    client = BrokenImageClient()
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=client, llm_client=client)

    actions = engine.process(event(telegram_identity_key(1), "Mach ein Bild."))

    assert len(actions) == 2
    assert actions[1].text == "Textantwort.\n" + instructions.openai_image_error


def test_engine_rate_limits_repeated_openai_image_generation(tmp_path):
    class FakeImage:
        data = b"png-bytes"
        filename = "bild.png"
        content_type = "image/png"

    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.generate_calls = 0

        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse(
                'Kurz dazu.\n[[TEE_IMAGE filename="bild.png" caption="Bild"]]\nEin freundliches Bild.\n[[/TEE_IMAGE]]',
                f"resp-{self.generate_calls}",
                None,
            )

        def generate_image(self, _prompt, _instructions, *, filename="bild.png"):
            self.generate_calls += 1
            return FakeImage()

    client = FakeOpenAIClient()
    instructions = BotInstructions(
        openai_enabled=True,
        openai_image_enabled=True,
        openai_image_min_interval_minutes=30,
        openai_image_rate_limited="Heute keine weiteren Bilder.",
    )
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=client, llm_client=client)
    identity = telegram_identity_key(1)

    first_actions = engine.process(event(identity, "Mach ein Wetterbild."))
    second_actions = engine.process(event(identity, "Noch ein Bild bitte."))

    assert client.generate_calls == 1
    assert isinstance(first_actions[2], SendAttachment)
    assert len(second_actions) == 2
    assert second_actions[1].text == "Kurz dazu.\nHeute keine weiteren Bilder."


def test_engine_passes_previous_openai_response_id_per_account(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.previous_ids: list[str | None] = []

        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            self.previous_ids.append(previous_response_id)
            return OpenAIResponse("Antwort.", f"resp-{len(self.previous_ids)}", None)

    client = FakeOpenAIClient()
    instructions = BotInstructions(openai_enabled=True)
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=client, llm_client=client)
    identity = telegram_identity_key(1)

    engine.process(event(identity, "Hallo"))
    engine.process(event(identity, "Noch mal"))

    assert client.previous_ids == [None, "resp-1"]


def test_engine_does_not_reuse_previous_response_id_after_provider_switch(tmp_path):
    provider = StaticSecretProvider(b"e" * 32)
    data_dir = tmp_path / "Depressionsbot" / "data"
    identity = telegram_identity_key(1)

    class FakeOpenAIClient:
        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse("OpenAI-Antwort.", "openai-1", None)

    first_engine = TeeBotusEngine(
        account_store=AccountStore(data_dir / "accounts", "Depressionsbot", provider),
        state=RuntimeStateStore(data_dir, instance_name="Depressionsbot", secret_provider=provider),
        instructions=BotInstructions(openai_enabled=True, llm_provider="openai", openai_model="gpt-5.5"),
        openai_client=FakeOpenAIClient(),
        llm_client=FakeOpenAIClient(),
    )
    first_engine.process(event(identity, "OpenAI"))

    class FakeGeminiClient:
        capabilities = GEMINI_INTERACTIONS_CAPABILITIES

        def __init__(self) -> None:
            self.previous_ids: list[str | None] = []

        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            self.previous_ids.append(previous_response_id)
            return LLMResponse(
                "Gemini-Antwort.",
                "gemini-1",
                provider="litellm_gemini_stateful",
                model="gemini/gemini-3.5-flash",
            )

    gemini = FakeGeminiClient()
    second_engine = TeeBotusEngine(
        account_store=AccountStore(data_dir / "accounts", "Depressionsbot", provider),
        state=RuntimeStateStore(data_dir, instance_name="Depressionsbot", secret_provider=provider),
        instructions=BotInstructions(
            openai_enabled=True,
            llm_provider="litellm_gemini_stateful",
            llm_model="gemini/gemini-3.5-flash",
        ),
        llm_client=gemini,
    )
    second_engine.process(event(identity, "Gemini"))

    assert gemini.previous_ids == [None]


def test_engine_scopes_stateful_response_ids_to_linked_chat_routes(tmp_path):
    class FakeGeminiClient:
        capabilities = GEMINI_INTERACTIONS_CAPABILITIES

        def __init__(self) -> None:
            self.previous_ids: list[str | None] = []

        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            self.previous_ids.append(previous_response_id)
            return LLMResponse(
                "Antwort.",
                f"gemini-{len(self.previous_ids)}",
                provider="litellm_gemini_stateful",
                model="gemini/gemini-3.5-flash",
            )

    provider = StaticSecretProvider(b"e" * 32)
    account_store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider)
    telegram_identity = telegram_identity_key(1)
    signal_identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(telegram_identity)
    account_store.link_identity_to_account(signal_identity, account_id)
    account_store.update_identity_route(telegram_identity, channel="telegram", chat_id="chat-1", chat_type="private", adapter_slot=1)
    account_store.update_identity_route(signal_identity, channel="signal", chat_id="chat-1", chat_type="private", adapter_slot=1)
    client = FakeGeminiClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        state=RuntimeStateStore(tmp_path / "data", instance_name="Depressionsbot", secret_provider=provider),
        instructions=BotInstructions(openai_enabled=True, llm_provider="litellm_gemini_stateful", llm_model="gemini/gemini-3.5-flash"),
        llm_client=client,
    )

    engine.process(event(telegram_identity, "Telegram eins", channel="telegram"))
    engine.process(event(signal_identity, "Signal eins", channel="signal"))
    engine.process(event(signal_identity, "/reset", channel="signal"))
    engine.process(event(telegram_identity, "Telegram zwei", channel="telegram"))

    assert client.previous_ids == [None, None, "gemini-1"]


def test_engine_recovers_once_from_stale_previous_openai_response_id(tmp_path):
    provider = StaticSecretProvider(b"e" * 32)
    data_dir = tmp_path / "Depressionsbot" / "data"
    account_store = AccountStore(data_dir / "accounts", "Depressionsbot", provider)
    state = RuntimeStateStore(data_dir, instance_name="Depressionsbot", secret_provider=provider)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    state.set_previous_response_id("Depressionsbot", account_id, "stale-response", provider="openai", model="gpt-5.5")

    class RecoveringOpenAIClient:
        def __init__(self) -> None:
            self.previous_ids: list[str | None] = []

        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            self.previous_ids.append(previous_response_id)
            if previous_response_id:
                raise OpenAIAPIError("OpenAI HTTP error 400: invalid previous_response_id: response not found")
            return OpenAIResponse("Wiederhergestellt.", "fresh-response", None)

    client = RecoveringOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        state=state,
        instructions=BotInstructions(openai_enabled=True, llm_provider="openai", openai_model="gpt-5.5"),
        openai_client=client,
        llm_client=client,
    )

    engine.process(event(identity, "Hallo"))

    assert client.previous_ids == ["stale-response", None]
    assert state.get_previous_response_id("Depressionsbot", account_id) == "fresh-response"


def test_engine_retries_stale_response_without_state_cleanup(tmp_path, monkeypatch):
    class RecoveringOpenAIClient:
        def __init__(self) -> None:
            self.previous_ids: list[str | None] = []

        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            self.previous_ids.append(previous_response_id)
            if previous_response_id:
                raise OpenAIAPIError("OpenAI HTTP error 400: invalid previous_response_id: response not found")
            return OpenAIResponse("Wiederhergestellt ohne Cleanup.", "fresh-response", None)

    identity = telegram_identity_key(1)
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(identity)
    client = RecoveringOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, llm_provider="openai", openai_model="gpt-5.5"),
        openai_client=client,
        llm_client=client,
    )
    engine.state.set_previous_response_id(
        "Depressionsbot",
        account_id,
        "stale-response",
        conversation_scope=_llm_conversation_scope(event(identity, "Hallo")),
        provider="openai",
        model="gpt-5.5",
    )
    monkeypatch.setattr(engine.state, "reset_previous_response_id", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("state cleanup unavailable")))

    actions = engine.process(event(identity, "Hallo"))

    assert client.previous_ids == ["stale-response", None]
    assert any(getattr(action, "text", "") == "Wiederhergestellt ohne Cleanup." for action in actions)


def test_youtube_llm_reply_survives_response_state_failure(tmp_path, monkeypatch):
    class FakeOpenAIClient:
        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse("YouTube-Antwort trotz Statefehler.", "youtube-response", None)

    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    client = FakeOpenAIClient()
    instructions = BotInstructions(openai_enabled=True, llm_provider="openai", openai_model="gpt-5.5")
    engine = TeeBotusEngine(account_store=account_store, instructions=instructions, llm_client=client, openai_client=client)
    monkeypatch.setattr(engine.state, "set_previous_response_id", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("state unavailable")))

    actions = engine._youtube_transcript_reply_actions(
        event(identity, "transkribiere"),
        account_id,
        instructions,
        "https://youtu.be/abc123",
        "Lokales Transkript",
        "local",
    )

    assert any(getattr(action, "text", "") == "YouTube-Antwort trotz Statefehler." for action in actions)


def test_llm_reset_state_failure_does_not_claim_success(tmp_path, monkeypatch):
    engine = TeeBotusEngine(account_store=store(tmp_path))
    identity = telegram_identity_key(1)

    monkeypatch.setattr(engine.state, "reset_previous_response_id", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("state reset unavailable")))

    actions = engine.process(event(identity, "/reset"))

    assert actions[0].text == "LLM-Kontext konnte gerade nicht zurückgesetzt werden. Bitte spaeter erneut versuchen."


def test_engine_keeps_state_on_non_stale_llm_error(tmp_path):
    provider = StaticSecretProvider(b"e" * 32)
    data_dir = tmp_path / "Depressionsbot" / "data"
    account_store = AccountStore(data_dir / "accounts", "Depressionsbot", provider)
    state = RuntimeStateStore(data_dir, instance_name="Depressionsbot", secret_provider=provider)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    state.set_previous_response_id("Depressionsbot", account_id, "keep-response", provider="openai", model="gpt-5.5")

    class FailingOpenAIClient:
        def __init__(self) -> None:
            self.calls = 0

        def create_reply(self, _user_text, _instructions, _previous_response_id=None):
            self.calls += 1
            raise OpenAIAPIError("OpenAI network timeout")

    client = FailingOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        state=state,
        instructions=BotInstructions(openai_enabled=True, llm_provider="openai", openai_model="gpt-5.5"),
        openai_client=client,
        llm_client=client,
    )

    engine.process(event(identity, "Hallo"))

    assert client.calls == 1
    assert state.get_previous_response_id("Depressionsbot", account_id) == "keep-response"


def test_engine_passes_previous_gemini_interaction_id_per_account_and_persists(tmp_path):
    class FakeGeminiClient:
        capabilities = GEMINI_INTERACTIONS_CAPABILITIES

        def __init__(self, prefix: str) -> None:
            self.prefix = prefix
            self.previous_ids: list[str | None] = []
            self.response_ids: list[str] = []

        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            self.previous_ids.append(previous_response_id)
            response_id = f"{self.prefix}-{len(self.previous_ids)}"
            self.response_ids.append(response_id)
            return LLMResponse("Antwort.", response_id, provider="litellm_gemini_stateful", model="gemini/gemini-3.5-flash")

    provider = StaticSecretProvider(b"e" * 32)
    data_dir = tmp_path / "Depressionsbot" / "data"
    instructions = BotInstructions(openai_enabled=True, llm_provider="litellm_gemini_stateful", llm_model="gemini/gemini-3.5-flash")
    first_client = FakeGeminiClient("gemini")
    first_account_store = AccountStore(data_dir / "accounts", "Depressionsbot", provider)
    first_state = RuntimeStateStore(data_dir, instance_name="Depressionsbot", secret_provider=provider)
    first_engine = TeeBotusEngine(
        account_store=first_account_store,
        state=first_state,
        instructions=instructions,
        llm_client=first_client,
    )
    identity_a = telegram_identity_key(1)
    identity_b = telegram_identity_key(2)

    first_engine.process(event(identity_a, "Hallo A"))
    first_engine.process(event(identity_a, "Noch mal A"))
    first_engine.process(event(identity_b, "Hallo B"))
    first_engine.process(event(identity_a, "Dritter Satz A"))
    account_a = first_account_store.get_account_for_identity(identity_a)
    account_b = first_account_store.get_account_for_identity(identity_b)

    assert first_client.previous_ids == [None, "gemini-1", None, "gemini-2"]
    assert account_a is not None
    assert account_b is not None
    assert first_state.get_previous_response_id("Depressionsbot", account_a) == "gemini-4"
    assert first_state.get_previous_response_id("Depressionsbot", account_b) == "gemini-3"

    second_client = FakeGeminiClient("gemini-reloaded")
    second_engine = TeeBotusEngine(
        account_store=AccountStore(data_dir / "accounts", "Depressionsbot", provider),
        state=RuntimeStateStore(data_dir, instance_name="Depressionsbot", secret_provider=provider),
        instructions=instructions,
        llm_client=second_client,
    )
    second_engine.process(event(identity_a, "Nach Reload"))

    assert second_client.previous_ids == ["gemini-4"]


def test_engine_persists_previous_response_id_for_stateful_gemini_alias(tmp_path):
    class FakeGeminiAliasClient:
        capabilities = GEMINI_INTERACTIONS_CAPABILITIES

        def __init__(self, prefix: str) -> None:
            self.prefix = prefix
            self.previous_ids: list[str | None] = []

        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            self.previous_ids.append(previous_response_id)
            response_id = f"{self.prefix}-{len(self.previous_ids)}"
            return LLMResponse("Antwort.", response_id, provider="gemini_paid_interactions", model="gemini/gemini-3.5-flash")

    provider = StaticSecretProvider(b"e" * 32)
    data_dir = tmp_path / "Depressionsbot" / "data"
    account_store = AccountStore(data_dir / "accounts", "Depressionsbot", provider)
    state = RuntimeStateStore(data_dir, instance_name="Depressionsbot", secret_provider=provider)
    instructions = BotInstructions(openai_enabled=True, llm_provider="gemini_paid_interactions", llm_model="gemini/gemini-3.5-flash")
    first_client = FakeGeminiAliasClient("paid-gemini")
    first_engine = TeeBotusEngine(account_store=account_store, state=state, instructions=instructions, llm_client=first_client)
    identity = telegram_identity_key(1)

    first_engine.process(event(identity, "Hallo"))
    first_engine.process(event(identity, "Noch mal"))
    account_id = account_store.get_account_for_identity(identity)

    assert first_client.previous_ids == [None, "paid-gemini-1"]
    assert account_id is not None
    assert state.get_previous_response_id("Depressionsbot", account_id) == "paid-gemini-2"


def test_engine_does_not_store_litellm_response_id_as_openai_previous_response(tmp_path):
    class FakeLiteLLMClient:
        def __init__(self) -> None:
            self.previous_ids: list[str | None] = []

        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            self.previous_ids.append(previous_response_id)
            return LLMResponse("Antwort.", "litellm-response-id", provider="litellm", model="ollama_chat/qwen")

    account_store = store(tmp_path)
    client = FakeLiteLLMClient()
    instructions = BotInstructions(openai_enabled=True, llm_provider="litellm", llm_model="ollama_chat/qwen")
    engine = TeeBotusEngine(account_store=account_store, instructions=instructions, llm_client=client)
    identity = telegram_identity_key(1)

    engine.process(event(identity, "Hallo"))
    engine.process(event(identity, "Noch mal"))
    account_id = account_store.get_account_for_identity(identity)

    assert client.previous_ids == [None, None]
    assert account_id is not None
    assert engine.state.get_previous_response_id("Depressionsbot", account_id) is None


def test_engine_restores_previous_openai_response_id_from_persistent_state(tmp_path):
    class FakeOpenAIClient:
        def __init__(self, response_id: str) -> None:
            self.response_id = response_id
            self.previous_ids: list[str | None] = []

        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            self.previous_ids.append(previous_response_id)
            return OpenAIResponse("Antwort.", self.response_id, None)

    provider = StaticSecretProvider(b"e" * 32)
    data_dir = tmp_path / "Depressionsbot" / "data"
    account_store = AccountStore(data_dir / "accounts", "Depressionsbot", provider)
    instructions = BotInstructions(openai_enabled=True)
    identity = telegram_identity_key(1)
    first_client = FakeOpenAIClient("resp-1")
    first_engine = TeeBotusEngine(
        account_store=account_store,
        state=RuntimeStateStore(data_dir, instance_name="Depressionsbot", secret_provider=provider),
        instructions=instructions,
        openai_client=first_client,
        llm_client=first_client,
    )

    first_engine.process(event(identity, "Hallo"))
    second_client = FakeOpenAIClient("resp-2")
    second_engine = TeeBotusEngine(
        account_store=AccountStore(data_dir / "accounts", "Depressionsbot", provider),
        state=RuntimeStateStore(data_dir, instance_name="Depressionsbot", secret_provider=provider),
        instructions=instructions,
        openai_client=second_client,
        llm_client=second_client,
    )
    second_engine.process(event(identity, "Noch mal"))

    assert first_client.previous_ids == [None]
    assert second_client.previous_ids == ["resp-1"]


def test_engine_does_not_pass_persisted_openai_response_id_to_litellm_client(tmp_path):
    class FakeOpenAIClient:
        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            assert previous_response_id is None
            return OpenAIResponse("Antwort.", "resp-openai-1", None)

    class FakeLiteLLMClient:
        capabilities = LITELLM_TEXT_CAPABILITIES

        def __init__(self) -> None:
            self.previous_ids: list[str | None] = []

        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            self.previous_ids.append(previous_response_id)
            return LLMResponse("Antwort.", "litellm-response-id", provider="litellm", model="ollama_chat/qwen")

    provider = StaticSecretProvider(b"e" * 32)
    data_dir = tmp_path / "Depressionsbot" / "data"
    identity = telegram_identity_key(1)
    first_engine = TeeBotusEngine(
        account_store=AccountStore(data_dir / "accounts", "Depressionsbot", provider),
        state=RuntimeStateStore(data_dir, instance_name="Depressionsbot", secret_provider=provider),
        instructions=BotInstructions(openai_enabled=True),
        openai_client=FakeOpenAIClient(),
        llm_client=FakeOpenAIClient(),
    )
    first_engine.process(event(identity, "Hallo"))

    litellm_client = FakeLiteLLMClient()
    second_engine = TeeBotusEngine(
        account_store=AccountStore(data_dir / "accounts", "Depressionsbot", provider),
        state=RuntimeStateStore(data_dir, instance_name="Depressionsbot", secret_provider=provider),
        instructions=BotInstructions(openai_enabled=True, llm_provider="litellm", llm_model="ollama_chat/qwen"),
        llm_client=litellm_client,
    )
    second_engine.process(event(identity, "Noch mal"))

    assert litellm_client.previous_ids == [None]


def test_engine_reset_clears_previous_text_llm_response_id(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.previous_ids: list[str | None] = []

        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            self.previous_ids.append(previous_response_id)
            return OpenAIResponse("Antwort.", "resp-1", None)

    client = FakeOpenAIClient()
    instructions = BotInstructions(openai_enabled=True, llm_reset="Kontext geloescht.")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=client, llm_client=client)
    identity = telegram_identity_key(1)

    engine.process(event(identity, "Hallo"))
    reset_actions = engine.process(event(identity, "/reset"))
    engine.process(event(identity, "Neu"))

    assert reset_actions[0].text == "Kontext geloescht."
    assert client.previous_ids == [None, None]


def test_engine_reports_llm_error_for_api_failure(tmp_path):
    class FakeOpenAIClient:
        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            raise OpenAIAPIError("boom")

    instructions = BotInstructions(openai_enabled=True, llm_error="LLM kaputt.")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=FakeOpenAIClient(), llm_client=FakeOpenAIClient())

    actions = engine.process(event(telegram_identity_key(1), "Hallo"))

    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "LLM kaputt."


def test_engine_transcribes_audio_attachment_for_openai_input(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""
            self.transcriptions: list[tuple[bytes, str]] = []

        def transcribe_audio(self, audio, filename, _instructions, model=None):
            self.transcriptions.append((audio, filename))
            return "Aehm also ich weiss nicht, ich bin nervoes und rede sehr schnell."

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort auf Audio.", "resp-audio", None)

    client = FakeOpenAIClient()
    instructions = BotInstructions(openai_enabled=True)
    attachment = IncomingAttachment(data=b"audio", filename="voice.ogg", content_type="audio/ogg")
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    engine = TeeBotusEngine(account_store=account_store, instructions=instructions, openai_client=client, llm_client=client)

    actions = engine.process(event(identity, "", attachments=(attachment,)))
    account_id = account_store.get_account_for_identity(identity)
    state = account_store.read_agent_state(account_id or "")

    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "Antwort auf Audio."
    assert client.transcriptions == [(b"audio", "voice.ogg")]
    assert "- attachments: 1" in client.user_text
    assert "Transkript: Aehm also ich weiss nicht" in client.user_text
    assert "Nachricht:\n<leer>" in client.user_text
    assert "tts_mimic_voice" in state
    assert "wirkt sprachlich leicht unsicher oder aengstlich" in str(state)
    assert "ich weiss nicht" not in str(state)


def test_engine_can_transcribe_audio_attachment_with_local_backend(tmp_path, monkeypatch):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""
            self.transcriptions: list[tuple[bytes, str]] = []

        def transcribe_audio(self, audio, filename, _instructions, model=None):
            self.transcriptions.append((audio, filename))
            return "Soll nicht genutzt werden."

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort auf lokales Audio.", "resp-audio", None)

    local_calls: list[tuple[bytes, str, str]] = []

    def fake_local_transcribe(audio, filename, *, model, language, instance_name=""):
        local_calls.append((audio, filename, model))
        return "Lokales Whisper Transkript."

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_local_audio", fake_local_transcribe)
    client = FakeOpenAIClient()
    instructions = BotInstructions(openai_enabled=True, openai_transcription_backend="local", local_transcription_model="tiny")
    attachment = IncomingAttachment(data=b"audio", filename="voice.ogg", content_type="audio/ogg")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=client, llm_client=client)

    actions = engine.process(event(telegram_identity_key(1), "", attachments=(attachment,)))

    assert actions[1].text == "Antwort auf lokales Audio."
    assert local_calls == [(b"audio", "voice.ogg", "tiny")]
    assert client.transcriptions == []
    assert "Transkript: Lokales Whisper Transkript." in client.user_text


def test_engine_continues_when_audio_attachment_transcription_raises_unexpected_error(tmp_path, monkeypatch):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort trotz Transkriptfehler.", "resp-audio-failure", None)

    def broken_local_transcribe(*_args, **_kwargs):
        raise RuntimeError("local transcription wrapper failed")

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_local_audio", broken_local_transcribe)
    client = FakeOpenAIClient()
    instructions = BotInstructions(openai_enabled=True, openai_transcription_backend="local")
    attachment = IncomingAttachment(data=b"audio", filename="voice.ogg", content_type="audio/ogg")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=client, llm_client=client)

    actions = engine.process(event(telegram_identity_key(1), "Trotzdem antworten.", attachments=(attachment,)))

    assert actions[1].text == "Antwort trotz Transkriptfehler."
    assert "Transkript: <Transkription fehlgeschlagen>" in client.user_text


def test_engine_respects_disabled_transcription_for_audio_attachment(tmp_path, monkeypatch):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""
            self.transcriptions: list[tuple[bytes, str]] = []

        def transcribe_audio(self, audio, filename, _instructions, model=None):
            self.transcriptions.append((audio, filename))
            return "Soll nicht genutzt werden."

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort ohne Transkript.", "resp-audio-disabled", None)

    def fake_local_transcribe(*_args, **_kwargs):
        raise AssertionError("local transcription must not run when transcription is disabled")

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_local_audio", fake_local_transcribe)
    client = FakeOpenAIClient()
    instructions = BotInstructions(
        openai_enabled=True,
        openai_transcription_enabled=False,
        openai_transcription_backend="local",
    )
    attachment = IncomingAttachment(data=b"audio", filename="voice.ogg", content_type="audio/ogg")
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    engine = TeeBotusEngine(account_store=account_store, instructions=instructions, openai_client=client, llm_client=client)

    actions = engine.process(event(identity, "", attachments=(attachment,)))
    account_id = account_store.get_account_for_identity(identity)
    state = account_store.read_agent_state(account_id or "")

    assert actions[1].text == "Antwort ohne Transkript."
    assert client.transcriptions == []
    assert "Transkript: <Transkription deaktiviert>" in client.user_text
    assert "tts_mimic_voice" not in state


def test_engine_does_not_transcribe_view_once_audio_attachment(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""
            self.transcriptions: list[tuple[bytes, str]] = []

        def transcribe_audio(self, audio, filename, _instructions, model=None):
            self.transcriptions.append((audio, filename))
            return "Soll nicht passieren."

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort ohne View-once-Transkript.", "resp-view-once", None)

    client = FakeOpenAIClient()
    instructions = BotInstructions(openai_enabled=True)
    attachment = IncomingAttachment(data=b"audio", filename="voice.ogg", content_type="audio/ogg", view_once=True)
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=client, llm_client=client)

    actions = engine.process(event(telegram_identity_key(1), "", attachments=(attachment,)))

    assert actions[1].text == "Antwort ohne View-once-Transkript."
    assert client.transcriptions == []
    assert "filename=voice.ogg content_type=audio/ogg bytes=5 view_once=true" in client.user_text
    assert "Transkript: <view-once nicht verarbeitet>" in client.user_text
    assert "Soll nicht passieren" not in client.user_text


def test_engine_includes_non_audio_attachment_metadata_for_openai_input(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort auf Datei.", "resp-file", None)

    client = FakeOpenAIClient()
    instructions = BotInstructions(openai_enabled=True)
    attachment = IncomingAttachment(data=b"pdf", filename="report.pdf", content_type="application/pdf")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=client, llm_client=client)

    actions = engine.process(event(telegram_identity_key(1), "Bitte ansehen", attachments=(attachment,)))

    assert actions[1].text == "Antwort auf Datei."
    assert "filename=report.pdf content_type=application/pdf bytes=3" in client.user_text
    assert "Nachricht:\nBitte ansehen" in client.user_text


def test_engine_includes_link_preview_metadata_for_openai_input(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort auf Link.", "resp-link", None)

    client = FakeOpenAIClient()
    instructions = BotInstructions(openai_enabled=True)
    preview = IncomingLinkPreview(
        title="TeeBotus",
        url="https://example.test/tee",
        description="Botlink",
        base64_thumbnail="aW1hZ2U=",
        id="preview-thumb",
    )
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=client, llm_client=client)

    actions = engine.process(event(telegram_identity_key(1), "Sieh mal", link_previews=(preview,)))

    assert actions[1].text == "Antwort auf Link."
    assert "- link_previews: 1" in client.user_text
    assert "Linkpreviews:" in client.user_text
    assert "title=TeeBotus" in client.user_text
    assert "url=https://example.test/tee" in client.user_text
    assert "thumbnail=yes" in client.user_text
    assert "Nachricht:\nSieh mal" in client.user_text


def test_engine_includes_reply_context_in_openai_input(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort.", "resp-reply", None)

    client = FakeOpenAIClient()
    instructions = BotInstructions(openai_enabled=True)
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=client, llm_client=client)
    incoming = event(telegram_identity_key(1), "Darauf antworte ich")
    incoming = IncomingEvent(
        event_id=incoming.event_id,
        instance=incoming.instance,
        channel=incoming.channel,
        adapter_slot=incoming.adapter_slot,
        account_id=incoming.account_id,
        identity_key=incoming.identity_key,
        chat_id=incoming.chat_id,
        chat_type=incoming.chat_type,
        sender_id=incoming.sender_id,
        sender_name=incoming.sender_name,
        sender_username=incoming.sender_username,
        sender_number=incoming.sender_number,
        text=incoming.text,
        message_ref=incoming.message_ref,
        reply_to_text="Vorherige Nachricht",
    )

    engine.process(incoming)

    assert "- reply_to_text: Vorherige Nachricht" in client.user_text


def test_engine_includes_account_memory_in_openai_input(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort.", "resp-memory", None)

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="mem")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.write_memory_entries(
        account_id,
        [
            {
                "id": "mem_old",
                "created_at": "2026-01-01T00:00:00+00:00",
                "channel": "signal",
                "keywords": ["mond"],
                "user_text": "Mein Lieblingswort ist Mond.",
                "bot_text": "Gemerkt.",
            }
        ],
    )
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True),
        openai_client=client,
        llm_client=client,
    )

    engine.process(event(identity, "Was weisst du noch?", channel="signal"))

    assert "Persistentes Account-Memory:" in client.user_text
    assert '"selected_memory_ids": [' in client.user_text
    assert '"mem_old"' in client.user_text
    assert "Mein Lieblingswort ist Mond." in client.user_text


def test_engine_includes_account_habits_in_openai_input_without_filename(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort.", "resp-habits", None)

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="habits")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.write_account_text(account_id, "User_Habbits_and_behave.md", "Ada mag knappe Antworten.")
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True),
        openai_client=client,
        llm_client=client,
    )

    engine.process(event(identity, "Wie sollst du antworten?", channel="signal"))

    assert "Persistentes Account-Memory:" in client.user_text
    assert "Interne, admingepflegte Zusatzhinweise fuer diesen Account:" in client.user_text
    assert "Ada mag knappe Antworten." in client.user_text
    assert "User_Habbits_and_behave" not in client.user_text


def test_engine_prefers_keyword_matched_account_memory_over_recent(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort.", "resp-memory", None)

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="memory-ranking")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.write_memory_entries(
        account_id,
        [
            {
                "id": "mem_moon",
                "created_at": "2026-01-01T00:00:00+00:00",
                "channel": "signal",
                "keywords": ["mond"],
                "user_text": "Mein Lieblingswort ist Mond.",
                "bot_text": "Gemerkt.",
            },
            {
                "id": "mem_tea",
                "created_at": "2026-01-02T00:00:00+00:00",
                "channel": "matrix",
                "keywords": ["tee"],
                "user_text": "Ich trinke gerne Tee.",
                "bot_text": "Gemerkt.",
            },
        ],
    )
    account_store.write_memory_index(
        account_id,
        {
            "keywords": {"mond": ["mem_moon"], "tee": ["mem_tea"]},
            "recent_ids": ["mem_moon", "mem_tea"],
        },
    )
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True),
        openai_client=client,
        llm_client=client,
    )

    engine.process(event(identity, "Was weisst du ueber Mond?", channel="signal"))

    assert '"id": "mem_moon"' in client.user_text
    assert '"id": "mem_tea"' in client.user_text
    assert client.user_text.index('"id": "mem_moon"') < client.user_text.index('"id": "mem_tea"')
    assert '"selected_memory_ids": [\n    "mem_moon",\n    "mem_tea"\n  ]' in client.user_text


def test_engine_uses_semantic_memory_search_only_when_explicitly_enabled(tmp_path, monkeypatch):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort.", "resp-semantic-memory", None)

    class FakeQdrantMemoryIndex:
        calls: list[tuple[str, str, str, int]] = []

        def __init__(self, *, url=None, **_kwargs) -> None:
            self.url = url

        def search(self, *, instance_name: str, account_id: str, query: str, limit: int):
            self.calls.append((instance_name, account_id, query, limit))
            return (
                QdrantMemoryResult(
                    memory_id="mem_plan",
                    account_id=account_id,
                    instance_name=instance_name,
                    score=2.0,
                    payload={"memory_id": "mem_plan", "account_id": account_id, "instance_name": instance_name},
                    ),
                )

        def index_memory(self, **_kwargs) -> str:
            return "point-id"

    monkeypatch.setattr("TeeBotus.runtime.engine.QdrantMemoryIndex", FakeQdrantMemoryIndex)
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="semantic-memory")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_sleep", "keywords": ["schlaf"], "user_text": "Schlaf stabilisiert.", "bot_text": "Gemerkt."},
    )
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_plan", "keywords": ["struktur"], "user_text": "Morgens hilft eine kleine Struktur.", "bot_text": "Gemerkt."},
    )
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(
            openai_enabled=True,
            user_memory_enabled=True,
            memory_search_semantic_enabled=True,
            memory_search_semantic_backend="qdrant",
            memory_search_local_limit=1,
            memory_search_semantic_limit=1,
            memory_search_qdrant_url="http://localhost:6334",
        ),
        openai_client=client,
        llm_client=client,
    )

    engine.process(event(identity, "Was hilft bei Schlaf?", channel="signal"))

    assert FakeQdrantMemoryIndex.calls == [("Depressionsbot", account_id, "Was hilft bei Schlaf?", 1)]
    assert '"id": "mem_plan"' in client.user_text
    assert client.user_text.index('"id": "mem_plan"') < client.user_text.index('"id": "mem_sleep"')


def test_engine_semantic_memory_search_falls_back_to_local_candidates(tmp_path, monkeypatch):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort.", "resp-semantic-fallback", None)

    class FailingQdrantMemoryIndex:
        def __init__(self, **_kwargs) -> None:
            pass

        def search(self, **_kwargs):
            raise QdrantError("qdrant down")

        def index_memory(self, **_kwargs) -> str:
            return "point-id"

    monkeypatch.setattr("TeeBotus.runtime.engine.QdrantMemoryIndex", FailingQdrantMemoryIndex)
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="semantic-memory-fallback")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_sleep", "keywords": ["schlaf"], "user_text": "Schlaf stabilisiert.", "bot_text": "Gemerkt."},
    )
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_plan", "keywords": ["struktur"], "user_text": "Morgens hilft eine kleine Struktur.", "bot_text": "Gemerkt."},
    )
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(
            openai_enabled=True,
            user_memory_enabled=True,
            memory_search_semantic_enabled=True,
            memory_search_semantic_backend="qdrant",
            memory_search_local_limit=1,
            memory_search_semantic_limit=1,
        ),
        openai_client=client,
        llm_client=client,
    )

    engine.process(event(identity, "Was hilft bei Schlaf?", channel="signal"))

    assert '"id": "mem_sleep"' in client.user_text
    assert '"id": "mem_plan"' not in client.user_text


def test_engine_pages_account_memory_when_model_requests_it(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.calls.append((user_text, previous_response_id))
            if len(self.calls) == 1:
                return OpenAIResponse('[[TEE_MEMORY_PAGE query="kaffee" exclude="mem_moon"]]', "resp-page-request", None)
            return OpenAIResponse("Kaffee ist nachgeladen.", "resp-final", None)

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="memory-paging")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_moon", "keywords": ["mond"], "user_text": "Mein Lieblingswort ist Mond.", "bot_text": "Gemerkt."},
    )
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_coffee", "keywords": ["kaffee"], "user_text": "Kaffee beruhigt beim Sortieren.", "bot_text": "Gemerkt."},
    )
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True, user_memory_max_prompt_chars=1200),
        openai_client=client,
        llm_client=client,
    )

    actions = engine.process(event(identity, "Was weisst du ueber Mond?", channel="signal"))

    assert len(client.calls) == 2
    assert "Persistentes Account-Memory:" in client.calls[0][0]
    assert '[[TEE_MEMORY_PAGE query="kurze Suchphrase" exclude="id1,id2"]]' in client.calls[0][0]
    assert client.calls[1][1] == "resp-page-request"
    assert "Aktive Account-Memory-Page:" in client.calls[1][0]
    assert '"id": "mem_coffee"' in client.calls[1][0]
    assert '"id": "mem_moon"' not in client.calls[1][0]
    assert actions[-1].text == "Kaffee ist nachgeladen."


def test_engine_does_not_leak_repeated_memory_page_request(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.calls = 0

        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            self.calls += 1
            if self.calls == 1:
                return OpenAIResponse('[[TEE_MEMORY_PAGE query="kaffee" exclude="mem_moon"]]', "resp-page-request", None)
            return OpenAIResponse('[[TEE_MEMORY_PAGE query="noch mehr" exclude="mem_coffee"]]', "resp-repeated-page", None)

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="memory-paging-repeat")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.append_structured_memory_entry(account_id, {"id": "mem_moon", "keywords": ["mond"], "user_text": "Mond", "bot_text": "Gemerkt."})
    account_store.append_structured_memory_entry(account_id, {"id": "mem_coffee", "keywords": ["kaffee"], "user_text": "Kaffee", "bot_text": "Gemerkt."})
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True, user_memory_max_prompt_chars=1200),
        openai_client=FakeOpenAIClient(),
        llm_client=FakeOpenAIClient(),
    )

    actions = engine.process(event(identity, "Was weisst du ueber Mond?", channel="signal"))

    assert actions[-1].text == MEMORY_PAGE_LIMIT_NOTE
    assert "TEE_MEMORY_PAGE" not in actions[-1].text


def test_engine_does_not_leak_unexpected_memory_page_request(tmp_path):
    class FakeOpenAIClient:
        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse('[[TEE_MEMORY_PAGE query="kaffee" exclude="mem_moon"]]', "resp-unexpected-page", None)

    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=False),
        openai_client=FakeOpenAIClient(),
        llm_client=FakeOpenAIClient(),
    )

    actions = engine.process(event(signal_identity_key(source_uuid="unexpected-page"), "Hallo", channel="signal"))

    assert actions[-1].text == MEMORY_PAGE_LIMIT_NOTE
    assert "TEE_MEMORY_PAGE" not in actions[-1].text


def test_engine_includes_working_memory_in_openai_input_without_auto_writes(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.user_text = ""

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.user_text = user_text
            return OpenAIResponse("Antwort.", "resp-working-memory", None)

    instances_dir = tmp_path / "instances"
    working_store = WorkingMemoryStore("Depressionsbot", instances_dir)
    working_store.append_manual("Allgemeine Instanzregel: bei Architekturfragen erst kurz strukturieren.")
    entries_path = instances_dir / "Depressionsbot" / "data" / "Working_Memorys.entries.jsonl"
    before = entries_path.read_text(encoding="utf-8")
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(openai_enabled=True),
        openai_client=client,
        llm_client=client,
        working_memory_store=working_store,
    )

    engine.process(event(signal_identity_key(source_uuid="working-memory"), "Bitte eine Architekturfrage strukturieren.", channel="signal"))

    assert "Instanz-Arbeitsgedaechtnis:" in client.user_text
    assert "Allgemeine Instanzregel" in client.user_text
    assert "Persistentes Account-Memory:" not in client.user_text
    assert entries_path.read_text(encoding="utf-8") == before


def test_engine_appends_account_memory_after_openai_reply(tmp_path):
    class FakeOpenAIClient:
        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse("Antwort mit Mond.", "resp-memory", None)

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="write-memory")
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True),
        openai_client=FakeOpenAIClient(),
        llm_client=FakeOpenAIClient(),
    )

    engine.process(event(identity, "Merke Mond.", channel="signal"))
    account_id = account_store.get_account_for_identity(identity)

    assert account_id is not None
    entries = account_store.read_memory_entries(account_id)
    assert entries[-1]["channel"] == "signal"
    assert entries[-1]["user_text"] == "Merke Mond."
    assert entries[-1]["bot_text"] == "Antwort mit Mond."
    index = account_store.read_memory_index(account_id)
    assert entries[-1]["id"] in index["index"]["recent_ids"]
    assert "mond" in index["index"]["keywords"]


def test_engine_appends_new_account_memory_to_qdrant_cache_when_semantic_enabled(tmp_path, monkeypatch):
    class FakeOpenAIClient:
        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse("Antwort mit Mond.", "resp-memory-qdrant", None)

    class FakeQdrantMemoryIndex:
        search_calls: list[tuple[str, str, str, int]] = []
        index_calls: list[tuple[str, str, str | None, dict[str, object]]] = []

        def __init__(self, *, url=None, **_kwargs) -> None:
            self.url = url

        def search(self, *, instance_name: str, account_id: str, query: str, limit: int):
            self.search_calls.append((instance_name, account_id, query, limit))
            return ()

        def index_memory(self, *, instance_name: str, account_id: str, entry: dict[str, object]) -> str:
            self.index_calls.append((instance_name, account_id, self.url, dict(entry)))
            return "point-id"

    monkeypatch.setattr("TeeBotus.runtime.engine.QdrantMemoryIndex", FakeQdrantMemoryIndex)
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="write-memory-qdrant")
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(
            openai_enabled=True,
            user_memory_enabled=True,
            memory_search_semantic_enabled=True,
            memory_search_semantic_backend="qdrant",
            memory_search_qdrant_url="http://localhost:6334",
        ),
        openai_client=FakeOpenAIClient(),
        llm_client=FakeOpenAIClient(),
    )

    engine.process(event(identity, "Merke Mond.", channel="signal"))
    account_id = account_store.get_account_for_identity(identity)

    assert account_id is not None
    assert FakeQdrantMemoryIndex.search_calls == [("Depressionsbot", account_id, "Merke Mond.", 8)]
    assert len(FakeQdrantMemoryIndex.index_calls) == 1
    instance_name, indexed_account, url, entry = FakeQdrantMemoryIndex.index_calls[0]
    assert instance_name == "Depressionsbot"
    assert indexed_account == account_id
    assert url == "http://localhost:6334"
    assert entry["user_text"] == "Merke Mond."
    assert entry["bot_text"] == "Antwort mit Mond."


def test_engine_qdrant_cache_index_failure_does_not_block_account_memory_write(tmp_path, monkeypatch):
    class FakeOpenAIClient:
        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse("Antwort.", "resp-memory-qdrant-fail", None)

    class FailingQdrantMemoryIndex:
        def __init__(self, **_kwargs) -> None:
            pass

        def search(self, **_kwargs):
            return ()

        def index_memory(self, **_kwargs) -> str:
            raise QdrantError("qdrant down")

    monkeypatch.setattr("TeeBotus.runtime.engine.QdrantMemoryIndex", FailingQdrantMemoryIndex)
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="write-memory-qdrant-fail")
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(
            openai_enabled=True,
            user_memory_enabled=True,
            memory_search_semantic_enabled=True,
            memory_search_semantic_backend="qdrant",
        ),
        openai_client=FakeOpenAIClient(),
        llm_client=FakeOpenAIClient(),
    )

    actions = engine.process(event(identity, "Merke Mond.", channel="signal"))
    account_id = account_store.get_account_for_identity(identity)

    assert actions[-1].text == "Antwort."
    assert account_id is not None
    assert account_store.read_memory_entries(account_id)[-1]["user_text"] == "Merke Mond."


def test_engine_uses_structured_memory_candidate_for_safe_semantic_memory(tmp_path):
    class FakeOpenAIClient:
        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse("Ich merke mir, dass kurze Antworten gut sind.", "resp-memory", None)

    calls = []

    def structured_runner(prompt, schema):
        calls.append((prompt, schema))
        if schema.__name__ == "ReminderDecision":
            return {"should_create": False, "text": "", "datetime_iso": None, "recurrence": None, "confidence": 0.0}
        return {
            "should_store": True,
            "memory_type": "preference",
            "text": "User bevorzugt kurze Antworten.",
            "sensitivity": "low",
            "confidence": 0.91,
        }

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="structured-memory")
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True),
        openai_client=FakeOpenAIClient(),
        llm_client=FakeOpenAIClient(),
        structured_decision_runner=structured_runner,
    )

    engine.process(event(identity, "Ich mag kurze Antworten.", channel="signal"))
    account_id = account_store.get_account_for_identity(identity)

    assert account_id is not None
    entries = account_store.read_memory_entries(account_id)
    assert [call[1].__name__ for call in calls] == ["MemoryCandidate"]
    assert entries[-1]["kind"] == "preference"
    assert entries[-1]["memory_type"] == "semantic"
    assert entries[-1]["user_text"] == "User bevorzugt kurze Antworten."
    assert entries[-1]["structured_decision"] == {
        "schema": "MemoryCandidate",
        "memory_type": "preference",
        "sensitivity": "low",
        "confidence": 0.91,
    }


def test_engine_structured_memory_candidate_accepts_clinical_memory_kind(tmp_path):
    class FakeOpenAIClient:
        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse("Ich merke mir das als Ziel.", "resp-memory-clinical", None)

    def structured_runner(_prompt, schema):
        if schema.__name__ == "ReminderDecision":
            return {"should_create": False, "text": "", "datetime_iso": None, "recurrence": None, "confidence": 0.0}
        return {
            "should_store": True,
            "memory_type": "therapy_goal",
            "text": "User moechte morgens einen kurzen Spaziergang als Therapieaufgabe testen.",
            "sensitivity": "medium",
            "confidence": 0.88,
        }

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="structured-memory-clinical")
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True),
        openai_client=FakeOpenAIClient(),
        llm_client=FakeOpenAIClient(),
        structured_decision_runner=structured_runner,
    )

    engine.process(event(identity, "Ich will morgens spazieren gehen ueben.", channel="signal"))
    account_id = account_store.get_account_for_identity(identity)

    assert account_id is not None
    entries = account_store.read_memory_entries(account_id)
    assert entries[-1]["kind"] == "therapy_goal"
    assert entries[-1]["memory_type"] == "semantic"
    assert entries[-1]["structured_decision"]["memory_type"] == "therapy_goal"


def test_engine_structured_memory_candidate_can_skip_memory_write(tmp_path):
    class FakeOpenAIClient:
        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse("Smalltalk.", "resp-memory", None)

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="structured-memory-skip")
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True),
        openai_client=FakeOpenAIClient(),
        llm_client=FakeOpenAIClient(),
        structured_decision_runner=lambda _prompt, schema: (
            {"should_create": False, "text": "", "datetime_iso": None, "recurrence": None, "confidence": 0.0}
            if schema.__name__ == "ReminderDecision"
            else {
                "should_store": False,
                "memory_type": "none",
                "text": "",
                "sensitivity": "low",
                "confidence": 0.95,
            }
        ),
    )

    engine.process(event(identity, "Wie geht es dir?", channel="signal"))
    account_id = account_store.get_account_for_identity(identity)

    assert account_id is not None
    assert account_store.read_memory_entries(account_id) == []


def test_engine_structured_memory_candidate_invalid_payload_blocks_legacy_auto_write(tmp_path):
    class FakeOpenAIClient:
        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse("Ich wuerde ohne strukturiertes Gate etwas speichern.", "resp-memory-invalid", None)

    def structured_runner(_prompt, schema):
        if schema.__name__ == "ReminderDecision":
            return {"should_create": False, "text": "", "datetime_iso": None, "recurrence": None, "confidence": 0.0}
        return {
            "should_store": True,
            "memory_type": "unsupported_private_blob",
            "text": "Soll nicht in den Legacy-Pfad fallen.",
            "sensitivity": "low",
            "confidence": 0.95,
        }

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="structured-memory-invalid")
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True),
        openai_client=FakeOpenAIClient(),
        llm_client=FakeOpenAIClient(),
        structured_decision_runner=structured_runner,
    )

    engine.process(event(identity, "Das ist eine unklare Memory-Aussage.", channel="signal"))
    account_id = account_store.get_account_for_identity(identity)

    assert account_id is not None
    assert account_store.read_memory_entries(account_id) == []


def test_engine_structured_memory_candidate_blocks_high_sensitivity_auto_write(tmp_path):
    class FakeOpenAIClient:
        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse("Ich gehe vorsichtig damit um.", "resp-memory", None)

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="structured-memory-high")
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True),
        openai_client=FakeOpenAIClient(),
        llm_client=FakeOpenAIClient(),
        structured_decision_runner=lambda _prompt, schema: (
            {"should_create": False, "text": "", "datetime_iso": None, "recurrence": None, "confidence": 0.0}
            if schema.__name__ == "ReminderDecision"
            else {
                "should_store": True,
                "memory_type": "profile",
                "text": "Sehr sensible Gesundheitsinformation.",
                "sensitivity": "high",
                "confidence": 0.99,
            }
        ),
    )

    engine.process(event(identity, "Ich erzaehle dir etwas sehr Privates.", channel="signal"))
    account_id = account_store.get_account_for_identity(identity)

    assert account_id is not None
    assert account_store.read_memory_entries(account_id) == []


def test_engine_structured_memory_candidate_blocks_low_confidence_auto_write(tmp_path):
    class FakeOpenAIClient:
        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse("Ich speichere das nur bei hoher Sicherheit.", "resp-memory", None)

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="structured-memory-low-confidence")
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True),
        openai_client=FakeOpenAIClient(),
        llm_client=FakeOpenAIClient(),
        structured_decision_runner=lambda _prompt, schema: (
            {"should_create": False, "text": "", "datetime_iso": None, "recurrence": None, "confidence": 0.0}
            if schema.__name__ == "ReminderDecision"
            else {
                "should_store": True,
                "memory_type": "preference",
                "text": "Unsichere Praeferenz.",
                "sensitivity": "low",
                "confidence": 0.69,
            }
        ),
    )

    engine.process(event(identity, "Vielleicht mag ich kurze Antworten.", channel="signal"))
    account_id = account_store.get_account_for_identity(identity)

    assert account_id is not None
    assert account_store.read_memory_entries(account_id) == []


def test_engine_does_not_write_account_memory_when_disabled(tmp_path):
    class FakeOpenAIClient:
        def create_reply(self, _user_text, _instructions, previous_response_id=None):
            return OpenAIResponse("Antwort.", "resp-memory", None)

    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="no-memory")
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=False),
        openai_client=FakeOpenAIClient(),
        llm_client=FakeOpenAIClient(),
    )

    engine.process(event(identity, "Nicht speichern.", channel="signal"))
    account_id = account_store.get_account_for_identity(identity)

    assert account_id is not None
    assert account_store.read_memory_entries(account_id) == []


def test_engine_account_memory_reset_requires_confirmation_and_resets_structured_memory(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="reset-memory")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.write_memory_index(account_id, {"keywords": {"mond": ["mem_old"]}})
    account_store.write_memory_entries(account_id, [{"id": "mem_old", "user_text": "Mond"}])
    account_store.write_account_text(account_id, "User_Habbits_and_behave.md", "Adminhinweis bleibt.")
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(user_memory_enabled=True))

    confirm_actions = engine.process(event(identity, "/reset_memorys", channel="signal"))
    done_actions = engine.process(event(identity, "ja", channel="signal"))

    assert confirm_actions[0].text == BotInstructions().user_memory_reset_confirm
    assert [button.label for button in confirm_actions[0].buttons] == ["Ja, loeschen", "Nein"]
    assert done_actions[0].text == BotInstructions().user_memory_reset_success
    reset_index = account_store.read_memory_index(account_id)
    assert reset_index["scope"] == "account"
    assert reset_index["account_id"] == account_id
    assert reset_index["index"]["recent_ids"] == []
    assert reset_index["index"]["entries"] == {}
    assert reset_index["index"]["semantic_cache"]["entries"] == {}
    assert account_store.read_memory_entries(account_id) == []
    assert account_store.read_account_text(account_id, "User_Habbits_and_behave.md") == "Adminhinweis bleibt."


def _write_codex_session(root, session_id: str, cwd) -> None:
    path = root / "2026" / "06" / "19" / f"rollout-2026-06-19T12-00-00-{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "timestamp": "2026-06-19T12:00:00Z",
                "type": "session_meta",
                "payload": {"id": session_id, "cwd": str(cwd)},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    os.utime(path, (10, 10))


def test_engine_account_memory_reset_deletes_semantic_qdrant_cache_when_enabled(tmp_path, monkeypatch):
    calls: list[tuple[str, str, str | None]] = []

    class FakeQdrantMemoryIndex:
        def __init__(self, *, url=None, **_kwargs) -> None:
            self.url = url

        def delete_account(self, *, instance_name: str, account_id: str) -> None:
            calls.append((instance_name, account_id, self.url))

    monkeypatch.setattr("TeeBotus.runtime.engine.QdrantMemoryIndex", FakeQdrantMemoryIndex)
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="reset-memory-qdrant")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.write_memory_entries(account_id, [{"id": "mem_old", "user_text": "Mond"}])
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(
            user_memory_enabled=True,
            memory_search_semantic_enabled=True,
            memory_search_semantic_backend="qdrant",
            memory_search_qdrant_url="http://localhost:6334",
        ),
    )

    engine.process(event(identity, "/reset_memorys", channel="signal"))
    done_actions = engine.process(event(identity, "ja", channel="signal"))

    assert done_actions[0].text == BotInstructions().user_memory_reset_success
    assert calls == [("Depressionsbot", account_id, "http://localhost:6334")]
    assert account_store.read_memory_entries(account_id) == []


def test_engine_account_memory_reset_reports_error_when_semantic_cache_delete_fails(tmp_path, monkeypatch):
    class FailingQdrantMemoryIndex:
        def __init__(self, **_kwargs) -> None:
            pass

        def delete_account(self, **_kwargs) -> None:
            raise QdrantError("qdrant down")

    monkeypatch.setattr("TeeBotus.runtime.engine.QdrantMemoryIndex", FailingQdrantMemoryIndex)
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="reset-memory-qdrant-fail")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.write_memory_entries(account_id, [{"id": "mem_old", "user_text": "Mond"}])
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(
            user_memory_enabled=True,
            memory_search_semantic_enabled=True,
            memory_search_semantic_backend="qdrant",
        ),
    )

    engine.process(event(identity, "/reset_memorys", channel="signal"))
    error_actions = engine.process(event(identity, "ja", channel="signal"))

    assert error_actions[0].text == BotInstructions().user_memory_reset_error
    assert account_store.read_memory_entries(account_id) == [{"id": "mem_old", "user_text": "Mond"}]


def test_engine_privacy_confirmation_is_persistent_until_memory_reset(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="privacy")
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(user_memory_enabled=True))

    confirmed = engine.process(event(identity, "Datenschutz bestätigt", channel="signal"))
    account_id = account_store.get_account_for_identity(identity)

    assert account_id is not None
    assert confirmed[0].text.startswith("Datenschutz ist bestätigt.")
    assert account_store.has_privacy_confirmation(account_id) is True

    engine.process(event(identity, "/reset_memorys", channel="signal"))
    reset_done = engine.process(event(identity, "ja", channel="signal"))

    assert reset_done[0].text == BotInstructions().user_memory_reset_success
    assert account_store.has_privacy_confirmation(account_id) is False


def test_engine_privacy_confirmation_storage_failure_is_explicit(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="privacy-storage-error")
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(user_memory_enabled=True))

    monkeypatch.setattr(account_store, "confirm_privacy", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("profile unavailable")))

    actions = engine.process(event(identity, "Datenschutz bestätigt", channel="signal"))

    assert len(actions) == 1
    assert actions[0].text == "Datenschutz konnte gerade nicht gespeichert werden."
    account_id = account_store.get_account_for_identity(identity)
    assert account_id is not None
    assert account_store.has_privacy_confirmation(account_id) is False


def test_engine_memory_reset_backend_failure_is_explicit(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="memory-reset-storage-error")
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(user_memory_enabled=True))

    armed = engine.process(event(identity, "/reset_memorys", channel="signal"))
    assert armed

    monkeypatch.setattr(account_store, "reset_structured_memory", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("memory backend unavailable")))

    actions = engine.process(event(identity, "ja", channel="signal"))

    assert len(actions) == 1
    assert actions[0].text == BotInstructions().user_memory_reset_error


def test_engine_memory_reset_does_not_mutate_when_confirmation_state_disappears(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="memory-reset-state-disappears")
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(user_memory_enabled=True))

    engine.process(event(identity, "/reset_memorys", channel="signal"))
    monkeypatch.setattr(engine.state, "pop_pending_flow", lambda *_args, **_kwargs: None)
    reset_calls: list[str] = []
    monkeypatch.setattr(account_store, "reset_structured_memory", lambda account_id: reset_calls.append(account_id))

    actions = engine.process(event(identity, "ja", channel="signal"))

    assert actions[0].text == BotInstructions().user_memory_reset_error
    assert reset_calls == []


def test_engine_memory_reset_cancel_does_not_claim_success_when_state_disappears(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="memory-reset-cancel-state-disappears")
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(user_memory_enabled=True))
    engine.process(event(identity, "/reset_memorys", channel="signal"))
    monkeypatch.setattr(engine.state, "pop_pending_flow", lambda *_args, **_kwargs: None)

    actions = engine.process(event(identity, "nein", channel="signal"))

    assert actions[0].text == BotInstructions().user_memory_reset_error


def test_engine_memory_reset_forbidden_target_does_not_hide_state_failure(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="memory-reset-forbidden-state-failure")
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(user_memory_enabled=True))
    engine.process(event(identity, "/reset_memorys", channel="signal"))
    monkeypatch.setattr(engine.state, "pop_pending_flow", lambda *_args, **_kwargs: None)

    actions = engine.process(event(identity, "loesche alle user memorys", channel="signal"))

    assert actions[0].text == BotInstructions().user_memory_reset_error


def test_engine_memory_reset_pending_cleanup_failure_does_not_fall_through_to_llm(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="memory-reset-fallback-state-failure")
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(user_memory_enabled=True))
    engine.process(event(identity, "/reset_memorys", channel="signal"))
    monkeypatch.setattr(
        engine.state,
        "pop_pending_flow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("pending state unavailable")),
    )

    actions = engine.process(event(identity, "etwas anderes", channel="signal"))

    assert actions[0].text == BotInstructions().user_memory_reset_error


def test_engine_start_survives_privacy_button_state_failure(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="start-privacy-state-error")
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(user_memory_enabled=True))

    monkeypatch.setattr(account_store, "has_privacy_confirmation", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("profile unavailable")))

    actions = engine.process(event(identity, "/start", channel="signal"))

    assert actions
    assert actions[0].buttons == ()


def test_bot_alias_lookup_survives_unexpected_memory_backend_failure(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    account_id = account_store.resolve_or_create_account(signal_identity_key(source_uuid="alias-state-error"))

    monkeypatch.setattr(account_store, "read_agent_state", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("state unavailable")))

    from TeeBotus.runtime.engine import account_bot_address_names

    assert account_bot_address_names(account_store, account_id) == frozenset()


def test_voice_preference_commands_survive_unexpected_backend_failures(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = signal_identity_key(source_uuid="voice-settings-error")

    monkeypatch.setattr("TeeBotus.runtime.engine.handle_tts_voice_model_command", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("voice state unavailable")))
    monkeypatch.setattr("TeeBotus.runtime.engine.handle_tts_mimic_voice_command", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("mimic state unavailable")))

    voice_actions = engine.process(event(identity, "/voicemodel", channel="signal"))
    mimic_actions = engine.process(event(identity, "/mimic_voice", channel="signal"))

    assert voice_actions[0].text == "Ich konnte deine Voice-Einstellung gerade nicht speichern."
    assert mimic_actions[0].text == "Ich konnte deine Sprechweisen-Einstellung gerade nicht speichern."


def test_account_export_survives_unexpected_backend_failure(tmp_path, monkeypatch):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = signal_identity_key(source_uuid="export-backend-error")

    monkeypatch.setattr("TeeBotus.runtime.engine.export_account_data_from_store", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("export unavailable")))

    actions = engine.process(event(identity, "/export json", channel="signal"))

    assert len(actions) == 1
    assert actions[0].text == "Account-Export konnte nicht erzeugt werden."


def test_engine_start_adds_legal_consent_buttons_until_privacy_is_confirmed(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="legal-buttons")
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(user_memory_enabled=True))

    start_actions = engine.process(event(identity, "/start", channel="signal"))
    account_id = account_store.get_account_for_identity(identity)

    assert account_id is not None
    assert [button.label for button in start_actions[0].buttons] == [
        "Alter 16+ bestaetigen",
        "AGB",
        "Datenschutz bestaetigen",
    ]
    confirmed = engine.process(event(identity, start_actions[0].buttons[0].text, channel="signal"))
    profile = account_store._read_account_profile(account_id)

    assert confirmed[0].text.startswith("Datenschutz ist bestätigt.")
    assert profile["privacy"]["confirmed"] is True
    assert profile["privacy"]["age_over_16_confirmed"] is True
    assert profile["privacy"]["terms_accepted"] is True

    later_start = engine.process(event(identity, "/start", channel="signal"))

    assert later_start[0].buttons == ()


def test_engine_account_memory_reset_can_be_cancelled(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="cancel-memory")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.write_memory_entries(account_id, [{"id": "mem_old", "user_text": "Mond"}])
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(user_memory_enabled=True))

    engine.process(event(identity, "/reset_memorys", channel="signal"))
    actions = engine.process(event(identity, "nein", channel="signal"))

    assert actions[0].text == BotInstructions().user_memory_reset_cancelled
    assert account_store.read_memory_entries(account_id) == [{"id": "mem_old", "user_text": "Mond"}]


def test_engine_account_memory_reset_reports_unavailable_when_disabled(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="disabled-memory")
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(user_memory_enabled=False))

    actions = engine.process(event(identity, "/reset_memorys", channel="signal"))

    assert actions[0].text == BotInstructions().user_memory_reset_unavailable
    account_id = account_store.get_account_for_identity(identity)
    assert account_id is not None
    assert engine.state.get_pending_flow("Depressionsbot", account_id, "memory_reset") is None


def test_engine_account_memory_reset_confirmation_is_scoped_to_chat(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="scoped-memory")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.write_memory_entries(account_id, [{"id": "mem_old", "user_text": "Mond"}])
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(user_memory_enabled=True))
    first_chat = event(identity, "/reset_memorys", channel="signal")
    other_chat = IncomingEvent(
        event_id="signal:2",
        instance="Depressionsbot",
        channel="signal",
        adapter_slot=1,
        identity_key=identity,
        chat_id="other-chat",
        chat_type="private",
        sender_id=identity,
        sender_name=identity,
        text="/ping",
        message_ref="2",
    )

    engine.process(first_chat)
    actions = engine.process(other_chat)

    assert [action.text for action in actions if isinstance(action, SendText)] == ["Pong"] * 10
    assert account_store.read_memory_entries(account_id) == [{"id": "mem_old", "user_text": "Mond"}]


def test_engine_keeps_same_memory_reset_flow_per_chat(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="parallel-scoped-memory")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.write_memory_entries(account_id, [{"id": "mem_old", "user_text": "Mond"}])
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(user_memory_enabled=True))
    first_chat = event(identity, "/reset_memorys", channel="signal")
    second_chat = IncomingEvent(
        event_id="signal:2",
        instance="Depressionsbot",
        channel="signal",
        adapter_slot=1,
        identity_key=identity,
        chat_id="other-chat",
        chat_type="private",
        sender_id=identity,
        sender_name=identity,
        text="/reset_memorys",
        message_ref="2",
    )

    engine.process(first_chat)
    engine.process(second_chat)
    done_actions = engine.process(event(identity, "ja", channel="signal"))

    assert done_actions[0].text == BotInstructions().user_memory_reset_success
    assert account_store.read_memory_entries(account_id) == []
    assert engine.state.get_pending_flow(
        "Depressionsbot",
        account_id,
        "memory_reset",
        conversation_scope=pending_flow_scope(
            channel=second_chat.channel,
            adapter_slot=second_chat.adapter_slot,
            chat_type=second_chat.chat_type,
            chat_id=second_chat.chat_id,
            identity_key=second_chat.identity_key,
        ),
    ) is not None


def test_engine_account_memory_reset_refuses_global_targets(tmp_path):
    account_store = store(tmp_path)
    identity = signal_identity_key(source_uuid="global-memory")
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(user_memory_enabled=True))

    actions = engine.process(event(identity, "loesche alle user memorys", channel="signal"))

    assert actions[0].text == BotInstructions().user_memory_reset_only_own


def test_engine_reports_missing_llm_key_for_attachment_only_message(tmp_path):
    instructions = BotInstructions(openai_enabled=True, llm_missing_key="LLM-Key fehlt.")
    attachment = IncomingAttachment(data=b"audio", filename="voice.ogg", content_type="audio/ogg")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions)

    actions = engine.process(event(telegram_identity_key(1), "", attachments=(attachment,)))

    assert len(actions) == 1
    assert actions[0].text == "LLM-Key fehlt."


def test_engine_voice_command_sends_generated_attachment(tmp_path):
    class FakeVoice:
        audio = b"voice-bytes"
        filename = "voice.opus"
        content_type = "audio/ogg"

    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.voice_texts: list[str] = []

        def create_voice(self, text, _instructions):
            self.voice_texts.append(text)
            return FakeVoice()

    client = FakeOpenAIClient()
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions(), openai_client=client, llm_client=client)

    actions = engine.process(event(telegram_identity_key(1), "/voice Hallo Welt", channel="signal"))

    assert client.voice_texts == ["Hallo Welt"]
    assert isinstance(actions[0], SendTyping)
    assert isinstance(actions[1], SendAttachment)
    assert actions[1].data == b"voice-bytes"
    assert actions[1].filename == "voice.opus"
    assert actions[1].content_type == "audio/ogg"


def test_engine_voice_command_survives_unexpected_provider_failure(tmp_path):
    class BrokenVoiceClient:
        def create_voice(self, _text, _instructions):
            raise RuntimeError("voice provider unavailable")

    instructions = BotInstructions()
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=BrokenVoiceClient())

    actions = engine.process(event(telegram_identity_key(1), "/voice Hallo Welt", channel="signal"))

    assert len(actions) == 2
    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == instructions.openai_voice_error


def test_engine_voice_command_uses_account_tts_dialect(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.voice_instructions: list[str] = []

        def create_voice(self, _text, instructions):
            self.voice_instructions.append(instructions.openai_voice_instructions)
            return type("Voice", (), {"audio": b"voice", "filename": "voice.ogg", "content_type": "audio/ogg"})()

    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_voice_instructions="Basisstimme."),
        openai_client=FakeOpenAIClient(),
        llm_client=FakeOpenAIClient(),
    )

    engine.process(event(identity, "Ich bin in Nürnberg geboren.", channel="signal"))
    engine.process(event(identity, "/voice Hallo", channel="signal"))

    client = engine.openai_client
    assert client is not None
    assert "Basisstimme." in client.voice_instructions[0]
    assert "Nürnberg" in client.voice_instructions[0]


def test_engine_voice_model_command_persists_openai_voice_alias(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.voice_names: list[str] = []

        def create_voice(self, _text, instructions):
            self.voice_names.append(instructions.openai_voice)
            return type("Voice", (), {"audio": b"voice", "filename": "voice.ogg", "content_type": "audio/ogg"})()

    account_store = store(tmp_path)
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions(), openai_client=client, llm_client=client)
    identity = signal_identity_key(source_uuid="voice-model")

    set_actions = engine.process(event(identity, "/voicemodel onys", channel="signal"))
    voice_actions = engine.process(event(identity, "/voice Hallo", channel="signal"))

    assert "OpenAI-Stimme onyx" in set_actions[0].text
    assert "https://platform.openai.com/docs/guides/text-to-speech#voice-options" in set_actions[0].text
    assert client.voice_names == ["onyx"]
    assert isinstance(voice_actions[1], SendAttachment)


def test_engine_voice_model_command_lists_openai_voices(tmp_path):
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions())

    actions = engine.process(event(telegram_identity_key(1), "/voicemodel", channel="matrix"))

    assert "Aktuelle Stimme:" in actions[0].text
    assert "onyx" in actions[0].text
    assert "https://platform.openai.com/docs/guides/text-to-speech#voice-options" in actions[0].text


def test_engine_mimic_voice_command_controls_voice_instruction_order(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.voice_instructions: list[str] = []

        def create_voice(self, _text, instructions):
            self.voice_instructions.append(instructions.openai_voice_instructions)
            return type("Voice", (), {"audio": b"voice", "filename": "voice.ogg", "content_type": "audio/ogg"})()

    from TeeBotus.runtime.tts_dialect import record_tts_voice_style_observation

    account_store = store(tmp_path)
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_voice_instructions="Basisstimme."),
        openai_client=client,
        llm_client=client,
    )
    identity = signal_identity_key(source_uuid="mimic-engine")
    account_id = account_store.resolve_or_create_account(identity)

    engine.process(event(identity, "Ich bin in Dresden geboren.", channel="signal"))
    record_tts_voice_style_observation(
        account_store,
        account_id,
        "Aehm also isch rede sehr schnell und bin nervoes.",
        duration_seconds=3,
    )
    set_actions = engine.process(event(identity, "/mimic_voice before", channel="signal"))
    voice_actions = engine.process(event(identity, "/voice Hallo", channel="signal"))

    assert "vor dem Dialekt" in set_actions[0].text
    assert client.voice_instructions[0].index("beobachtete Sprechweise") < client.voice_instructions[0].index("Dresden")
    assert isinstance(voice_actions[1], SendAttachment)


def test_engine_voice_command_uses_reply_text(tmp_path):
    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.voice_texts: list[str] = []

        def create_voice(self, text, _instructions):
            self.voice_texts.append(text)
            return type("Voice", (), {"audio": b"voice", "filename": "voice.ogg", "content_type": "audio/ogg"})()

    client = FakeOpenAIClient()
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions(), openai_client=client, llm_client=client)
    incoming = event(telegram_identity_key(1), "/voice", channel="matrix")
    incoming = IncomingEvent(
        event_id=incoming.event_id,
        instance=incoming.instance,
        channel=incoming.channel,
        adapter_slot=incoming.adapter_slot,
        account_id=incoming.account_id,
        identity_key=incoming.identity_key,
        chat_id=incoming.chat_id,
        chat_type=incoming.chat_type,
        sender_id=incoming.sender_id,
        sender_name=incoming.sender_name,
        sender_username=incoming.sender_username,
        sender_number=incoming.sender_number,
        text=incoming.text,
        message_ref=incoming.message_ref,
        reply_to_text="Aus Reply",
    )

    actions = engine.process(incoming)

    assert client.voice_texts == ["Aus Reply"]
    assert isinstance(actions[1], SendAttachment)


def test_engine_voice_command_requires_openai_client(tmp_path):
    instructions = BotInstructions(openai_missing_key="Key fehlt.")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions)

    actions = engine.process(event(telegram_identity_key(1), "/voice Hallo"))

    assert actions[0].text == "Key fehlt."


def test_engine_voice_command_requires_text(tmp_path):
    class FakeOpenAIClient:
        def create_voice(self, _text, _instructions):
            raise AssertionError("create_voice must not be called")

    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions(), openai_client=FakeOpenAIClient(), llm_client=FakeOpenAIClient())

    actions = engine.process(event(telegram_identity_key(1), "/voice"))

    assert actions[0].text == "Nutzung: /voice Text fuer die Sprachnachricht"


def test_engine_voice_command_respects_disabled_voice(tmp_path):
    class FakeOpenAIClient:
        def create_voice(self, _text, _instructions):
            raise AssertionError("create_voice must not be called")

    instructions = BotInstructions(openai_voice_enabled=False, openai_voice_error="Voice aus.")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=FakeOpenAIClient(), llm_client=FakeOpenAIClient())

    actions = engine.process(event(telegram_identity_key(1), "/voice Hallo"))

    assert actions[0].text == "Voice aus."


def test_engine_voice_command_rejects_too_long_text(tmp_path):
    class FakeOpenAIClient:
        def create_voice(self, _text, _instructions):
            raise AssertionError("create_voice must not be called")

    instructions = BotInstructions(openai_voice_max_input_chars=5)
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=FakeOpenAIClient(), llm_client=FakeOpenAIClient())

    actions = engine.process(event(telegram_identity_key(1), "/voice zu lang"))

    assert actions[0].text == "Der Text ist zu lang fuer eine Sprachnachricht. Maximum: 5 Zeichen."


def test_engine_voice_command_reports_openai_error(tmp_path):
    class FakeOpenAIClient:
        def create_voice(self, _text, _instructions):
            raise OpenAIAPIError("boom")

    instructions = BotInstructions(openai_voice_error="Voice kaputt.")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions, openai_client=FakeOpenAIClient(), llm_client=FakeOpenAIClient())

    actions = engine.process(event(telegram_identity_key(1), "/voice Hallo"))

    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "Voice kaputt."


def test_engine_youtube_transcript_command_sends_transcript(monkeypatch, tmp_path):
    calls = []

    def fake_transcribe(url, **kwargs):
        calls.append((url, kwargs))
        return "Transcript text.", "YouTube-Untertitel"

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions())

    actions = engine.process(event(telegram_identity_key(1), "/youtube_transcript https://youtu.be/abc123", channel="signal"))

    assert calls == [("https://youtu.be/abc123", {"local_allowed": False, "instance_name": "Depressionsbot"})]
    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "YouTube-Transkript (YouTube-Untertitel):\n\nTranscript text."


def test_engine_youtube_transcript_command_records_account_memory(monkeypatch, tmp_path):
    def fake_transcribe(_url, **_kwargs):
        return "Transcript text.", "YouTube-Untertitel"

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(user_memory_enabled=True),
    )

    engine.process(event(identity, "/youtube_transcript https://youtu.be/abc123", channel="signal"))

    entries = account_store.read_memory_entries(account_id)
    assert len(entries) == 1
    assert entries[0]["channel"] == "signal"
    assert entries[0]["user_text"] == "/youtube_transcript https://youtu.be/abc123"
    assert entries[0]["bot_text"] == "YouTube-Transkript (YouTube-Untertitel):\n\nTranscript text."


def test_engine_youtube_transcript_natural_request_uses_llm_pipeline(monkeypatch, tmp_path):
    class FakeLLMClient:
        def __init__(self) -> None:
            self.reply_inputs: list[str] = []

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.reply_inputs.append(user_text)
            return OpenAIResponse("AI summary.", "resp-youtube", None)

    monkeypatch.setattr(
        "TeeBotus.runtime.engine.transcribe_youtube_video",
        lambda _url, **_kwargs: ("Transcript text.", "YouTube-Untertitel"),
    )
    client = FakeLLMClient()
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions(openai_enabled=True), llm_client=client)

    actions = engine.process(event(telegram_identity_key(1), "Bitte transkribiere dieses YouTube Video https://youtu.be/abc123", channel="matrix"))

    assert "YouTube-Transkript:" in client.reply_inputs[0]
    assert "Transcript text." in client.reply_inputs[0]
    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "AI summary."


def test_engine_youtube_transcript_llm_pipeline_reports_neutral_missing_key(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "TeeBotus.runtime.engine.transcribe_youtube_video",
        lambda _url, **_kwargs: ("Transcript text.", "YouTube-Untertitel"),
    )
    instructions = BotInstructions(openai_enabled=True, llm_missing_key="LLM-Key fehlt.")
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=instructions)

    actions = engine.process(event(telegram_identity_key(1), "Bitte transkribiere dieses YouTube Video https://youtu.be/abc123", channel="matrix"))

    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "LLM-Key fehlt."


def test_engine_youtube_llm_pipeline_includes_working_memory(monkeypatch, tmp_path):
    class FakeLLMClient:
        def __init__(self) -> None:
            self.reply_inputs: list[str] = []

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.reply_inputs.append(user_text)
            return OpenAIResponse("AI summary.", "resp-youtube", None)

    monkeypatch.setattr(
        "TeeBotus.runtime.engine.transcribe_youtube_video",
        lambda _url, **_kwargs: ("Architektur Transcript.", "YouTube-Untertitel"),
    )
    instances_dir = tmp_path / "instances"
    working_store = WorkingMemoryStore("Depressionsbot", instances_dir)
    working_store.append_manual("Architekturfragen zuerst kurz strukturieren.")
    client = FakeLLMClient()
    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(openai_enabled=True),
        llm_client=client,
        working_memory_store=working_store,
    )

    engine.process(event(telegram_identity_key(1), "/youtube_transcript https://youtu.be/abc123 Architektur", channel="matrix"))

    assert "Instanz-Arbeitsgedaechtnis:" in client.reply_inputs[0]
    assert "Architekturfragen zuerst kurz strukturieren" in client.reply_inputs[0]
    assert "YouTube-Transkript:" in client.reply_inputs[0]


def test_engine_youtube_llm_pipeline_includes_account_weather_and_library_context(monkeypatch, tmp_path):
    class FakeLLMClient:
        def __init__(self) -> None:
            self.reply_inputs: list[str] = []

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.reply_inputs.append(user_text)
            return OpenAIResponse("AI summary.", "resp-youtube", None)

    class FakeBibliothekarStore:
        def select(self, query_text, **_kwargs):
            assert "YouTube-Transkript:" in query_text
            return type("Selection", (), {"prompt_text": "Quelle: therapie.txt chunk_id=chunk-1"})()

    monkeypatch.setattr(
        "TeeBotus.runtime.engine.transcribe_youtube_video",
        lambda _url, **_kwargs: ("Therapie Transcript.", "YouTube-Untertitel"),
    )
    monkeypatch.setattr("TeeBotus.runtime.engine.weather_context_text", lambda _store, _account_id: "Berlin: 12 C")
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_therapy", "keywords": ["therapie"], "user_text": "Therapie lieber strukturiert.", "bot_text": "Gemerkt."},
    )
    client = FakeLLMClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True, bibliothekar_enabled=True),
        llm_client=client,
        bibliothekar_store=FakeBibliothekarStore(),
    )

    engine.process(event(identity, "/youtube_transcript https://youtu.be/abc123 Therapie", channel="signal"))

    assert "Persistentes Account-Memory:" in client.reply_inputs[0]
    assert "Therapie lieber strukturiert." in client.reply_inputs[0]
    assert "Lokaler Wetterkontext:" in client.reply_inputs[0]
    assert "Berlin: 12 C" in client.reply_inputs[0]
    assert "Bibliothekar-Quellenkontext:" in client.reply_inputs[0]
    assert "therapie.txt" in client.reply_inputs[0]


def test_engine_youtube_llm_pipeline_supports_active_memory_page(monkeypatch, tmp_path):
    class FakeLLMClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.calls.append((user_text, previous_response_id))
            if len(self.calls) == 1:
                return OpenAIResponse('[[TEE_MEMORY_PAGE query="kaffee" exclude="mem_moon"]]', "resp-page-request", None)
            return OpenAIResponse("Kaffee ist nachgeladen.", "resp-final", None)

    monkeypatch.setattr(
        "TeeBotus.runtime.engine.transcribe_youtube_video",
        lambda _url, **_kwargs: ("Mond Transcript.", "YouTube-Untertitel"),
    )
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_moon", "keywords": ["mond"], "user_text": "Mein Lieblingswort ist Mond.", "bot_text": "Gemerkt."},
    )
    account_store.append_structured_memory_entry(
        account_id,
        {"id": "mem_coffee", "keywords": ["kaffee"], "user_text": "Kaffee beruhigt beim Sortieren.", "bot_text": "Gemerkt."},
    )
    client = FakeLLMClient()
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True, user_memory_enabled=True, user_memory_max_prompt_chars=1200),
        llm_client=client,
    )

    actions = engine.process(event(identity, "/youtube_transcript https://youtu.be/abc123 Mond", channel="matrix"))

    assert len(client.calls) == 2
    assert "Persistentes Account-Memory:" in client.calls[0][0]
    assert '[[TEE_MEMORY_PAGE query="kurze Suchphrase" exclude="id1,id2"]]' in client.calls[0][0]
    assert client.calls[1][1] == "resp-page-request"
    assert "Aktive Account-Memory-Page:" in client.calls[1][0]
    assert '"id": "mem_coffee"' in client.calls[1][0]
    assert '"id": "mem_moon"' not in client.calls[1][0]
    assert "YouTube-Transkript:" in client.calls[1][0]
    assert actions[-1].text == "Kaffee ist nachgeladen."


def test_engine_youtube_transcript_requires_link(tmp_path):
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions())

    actions = engine.process(event(telegram_identity_key(1), "/youtube_transcript"))

    assert actions[0].text == "Schick mir bitte den YouTube-Link, den ich transkribieren soll."


def test_engine_youtube_transcript_reports_pending_state_failure(tmp_path, monkeypatch):
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions())

    def broken_set(*_args, **_kwargs):
        raise RuntimeError("pending state unavailable")

    monkeypatch.setattr(engine.state, "set_pending_flow", broken_set)

    actions = engine.process(event(telegram_identity_key(1), "/youtube_transcript"))

    assert actions[0].text == "YouTube-Transkript konnte gerade nicht vorbereitet werden."


@pytest.mark.parametrize(
    "text",
    [
        "alter mach aus dem Video text!",
        "digga das yt, texte!",
        "VERDAMMT TRANSKRIBIER DIESES VIDEO!",
        "digga, video: output!",
        "DeDeWa! Moege das Orm dir die Beine wegaetzen. Transkribier diesen Scheiss! : zeit: 0 - letzte Minute nein.",
        "transcribiere dieses Video:",
        "transcribiere das video:",
    ],
)
def test_engine_youtube_transcript_freeform_phrases_request_link(tmp_path, text):
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions())

    actions = engine.process(event(telegram_identity_key(1), text))

    assert actions[0].text == "Schick mir bitte den YouTube-Link, den ich transkribieren soll."


def test_youtube_transcript_intent_does_not_trigger_on_plain_transcript_noun():
    assert _has_youtube_transcript_intent("das Transkript ist gut, danke") is False
    assert _has_youtube_transcript_intent("ich lese das Transcript nachher") is False
    assert _has_youtube_transcript_intent("den Untertitel finde ich komisch") is False
    assert _has_youtube_transcript_intent("transkribier das bitte") is True


def test_engine_youtube_transcript_uses_pending_link_followup(monkeypatch, tmp_path):
    calls = []

    def fake_transcribe(url, **kwargs):
        calls.append((url, kwargs))
        return "Transcript text.", "YouTube-Untertitel"

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions())
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)

    first = engine.process(event(identity, "/youtube_transcript", channel="signal"))
    second = engine.process(event(identity, "https://youtu.be/abc123", channel="signal"))

    assert first[0].text == "Schick mir bitte den YouTube-Link, den ich transkribieren soll."
    assert calls == [("https://youtu.be/abc123", {"local_allowed": False, "instance_name": "Depressionsbot"})]
    assert isinstance(second[0], SendTyping)
    assert second[1].text == "YouTube-Transkript (YouTube-Untertitel):\n\nTranscript text."
    assert engine.state.get_pending_flow("Depressionsbot", account_id, "youtube_link") is None


def test_engine_youtube_transcript_does_not_start_when_pending_link_pop_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "TeeBotus.runtime.engine.transcribe_youtube_video",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("transcription must not start")),
    )
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions())
    identity = telegram_identity_key(1)
    engine.process(event(identity, "/youtube_transcript", channel="signal"))

    def broken_pop(*_args, **_kwargs):
        raise RuntimeError("pending state unavailable")

    monkeypatch.setattr(engine.state, "pop_pending_flow", broken_pop)

    actions = engine.process(event(identity, "https://youtu.be/abc123", channel="signal"))

    assert actions[0].text == "YouTube-Transkript konnte gerade nicht fortgesetzt werden."


def test_engine_youtube_transcript_starts_local_by_default_when_no_subtitles(monkeypatch, tmp_path):
    from TeeBotus.core.youtube import YouTubeTranscriptError

    calls = []

    def fake_transcribe(url, **kwargs):
        calls.append((url, kwargs))
        if kwargs.get("local_allowed") is False:
            raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True)
        return "Local transcript.", "lokales Whisper"

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions(openai_model="gpt-test"))

    actions = engine.process(event(telegram_identity_key(1), "/youtube_transcript https://youtu.be/abc123"))

    assert calls == [
        ("https://youtu.be/abc123", {"local_allowed": False, "instance_name": "Depressionsbot"}),
        ("https://youtu.be/abc123", {"local_allowed": True, "live_callback": None, "instance_name": "Depressionsbot"}),
    ]
    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "YouTube-Transkript (lokales Whisper):\n\nLocal transcript."


def test_engine_youtube_transcript_uses_pending_local_options_followup(monkeypatch, tmp_path):
    from TeeBotus.core.youtube import YouTubeTranscriptError

    calls = []

    def fake_transcribe(url, **kwargs):
        calls.append((url, kwargs))
        if kwargs.get("local_allowed") is False:
            raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True)
        return "Local transcript.", "lokales Whisper"

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions())
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)

    engine.state.set_pending_flow(
        "Depressionsbot",
        account_id,
        "youtube_options",
        {
            "chat_id": "chat-1",
            "channel": "matrix",
            "url": "https://youtu.be/abc123",
            "original_text": "/youtube_transcript https://youtu.be/abc123",
        },
    )
    second = engine.process(event(identity, "live nein, llm nein", channel="matrix"))

    assert calls == [
        ("https://youtu.be/abc123", {"local_allowed": True, "live_callback": None, "instance_name": "Depressionsbot"}),
    ]
    assert isinstance(second[0], SendTyping)
    assert second[1].text == "YouTube-Transkript (lokales Whisper):\n\nLocal transcript."
    assert engine.state.get_pending_flow("Depressionsbot", account_id, "youtube_options") is None


@pytest.mark.parametrize("pop_result", [None, RuntimeError("pending state unavailable")])
def test_engine_youtube_transcript_reports_missing_url_state_cleanup_failure(monkeypatch, tmp_path, pop_result):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions())
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    engine.state.set_pending_flow(
        "Depressionsbot",
        account_id,
        "youtube_options",
        {"chat_id": "chat-1", "channel": "telegram", "original_text": "YouTube"},
    )
    if isinstance(pop_result, Exception):
        monkeypatch.setattr(engine.state, "pop_pending_flow", lambda *_args, **_kwargs: (_ for _ in ()).throw(pop_result))
    else:
        monkeypatch.setattr(engine.state, "pop_pending_flow", lambda *_args, **_kwargs: pop_result)

    actions = engine.process(event(identity, "live nein, llm nein"))

    assert actions[0].text == "YouTube-Transkript konnte gerade nicht fortgesetzt werden."


def test_engine_youtube_transcript_runs_local_when_options_are_explicit(monkeypatch, tmp_path):
    from TeeBotus.core.youtube import YouTubeTranscriptError

    calls = []

    def fake_transcribe(url, **kwargs):
        calls.append((url, kwargs))
        if kwargs.get("local_allowed") is False:
            raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True)
        return "Local transcript.", "lokales Whisper"

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions())

    actions = engine.process(event(telegram_identity_key(1), "/youtube_transcript https://youtu.be/abc123 live nein, llm nein"))

    assert calls == [
        ("https://youtu.be/abc123", {"local_allowed": False, "instance_name": "Depressionsbot"}),
        ("https://youtu.be/abc123", {"local_allowed": True, "live_callback": None, "instance_name": "Depressionsbot"}),
    ]
    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "YouTube-Transkript (lokales Whisper):\n\nLocal transcript."


def test_engine_youtube_local_transcription_can_run_as_background_job(monkeypatch, tmp_path):
    from TeeBotus.core.youtube import YouTubeTranscriptError

    class FakeRunner:
        def __init__(self) -> None:
            self.callbacks = []

        def submit(self, callback):
            self.callbacks.append(callback)
            callback()
            return object()

    background: list[list[str]] = []
    calls = []

    def fake_transcribe(url, **kwargs):
        calls.append((url, kwargs))
        if kwargs.get("local_allowed") is False:
            raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True)
        live_callback = kwargs.get("live_callback")
        if live_callback is not None:
            live_callback("eins zwei drei", force=True)
        return "Local transcript.", "lokales Whisper"

    def dispatch(_event, actions):
        background.append([action.text for action in actions if hasattr(action, "text")])

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    runner = FakeRunner()
    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(),
        youtube_job_runner=runner,
        background_action_dispatcher=dispatch,
    )

    actions = engine.process(event(telegram_identity_key(1), "/youtube_transcript https://youtu.be/abc123 live ja, llm nein", channel="signal"))

    assert actions[0].text == "Lokale YouTube-Transkription gestartet. Ich melde mich, sobald sie fertig ist. Live-Ausgabe ist aktiviert."
    assert len(runner.callbacks) == 1
    assert calls[0] == ("https://youtu.be/abc123", {"local_allowed": False, "instance_name": "Depressionsbot"})
    assert calls[1][0] == "https://youtu.be/abc123"
    assert calls[1][1]["local_allowed"] is True
    assert calls[1][1]["instance_name"] == "Depressionsbot"
    assert callable(calls[1][1]["live_callback"])
    assert background == [["eins zwei drei"], ["YouTube-Transkript (lokales Whisper):\n\nLocal transcript."]]


def test_engine_youtube_reports_background_submission_failure(monkeypatch, tmp_path):
    from TeeBotus.core.youtube import YouTubeTranscriptError

    class FailingRunner:
        def submit(self, _callback):
            raise RuntimeError("executor stopped")

    def fake_transcribe(_url, **kwargs):
        if kwargs.get("local_allowed") is False:
            raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True)
        raise AssertionError("local transcription must not run before job submission")

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(),
        youtube_job_runner=FailingRunner(),
        background_action_dispatcher=lambda _event, _actions: None,
    )

    actions = engine.process(event(telegram_identity_key(1), "/youtube_transcript https://youtu.be/abc123 live ja, llm nein"))

    assert actions[0].text == "Lokale YouTube-Transkription konnte nicht gestartet werden."


def test_engine_youtube_background_off_off_dispatches_finished_transcript(monkeypatch, tmp_path):
    from TeeBotus.core.youtube import YouTubeTranscriptError

    class FakeRunner:
        def __init__(self) -> None:
            self.callbacks = []

        def submit(self, callback):
            self.callbacks.append(callback)
            callback()
            return object()

    background: list[list[str]] = []
    calls = []

    def fake_transcribe(url, **kwargs):
        calls.append((url, kwargs))
        if kwargs.get("local_allowed") is False:
            raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True)
        return "Local transcript.", "lokales Whisper"

    def dispatch(_event, actions):
        background.append([action.text for action in actions if hasattr(action, "text")])

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    runner = FakeRunner()
    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(),
        youtube_job_runner=runner,
        background_action_dispatcher=dispatch,
    )

    actions = engine.process(event(telegram_identity_key(1), "/youtube_transcript https://youtu.be/abc123 live nein, llm nein", channel="signal"))

    assert actions[0].text == "Lokale YouTube-Transkription gestartet. Ich melde mich, sobald sie fertig ist."
    assert len(runner.callbacks) == 1
    assert calls == [
        ("https://youtu.be/abc123", {"local_allowed": False, "instance_name": "Depressionsbot"}),
        ("https://youtu.be/abc123", {"local_allowed": True, "live_callback": None, "instance_name": "Depressionsbot"}),
    ]
    assert background == [["YouTube-Transkript (lokales Whisper):\n\nLocal transcript."]]


def test_engine_youtube_background_live_records_start_and_full_transcript(monkeypatch, tmp_path):
    from TeeBotus.core.youtube import YouTubeTranscriptError

    class FakeRunner:
        def submit(self, callback):
            callback()
            return object()

    def fake_transcribe(_url, **kwargs):
        if kwargs.get("local_allowed") is False:
            raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True)
        live_callback = kwargs.get("live_callback")
        if live_callback is not None:
            live_callback("eins zwei drei", force=True)
        return "Full local transcript.", "lokales Whisper"

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    account_store = store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(user_memory_enabled=True),
        youtube_job_runner=FakeRunner(),
        background_action_dispatcher=lambda _event, _actions: None,
    )

    engine.process(event(identity, "/youtube_transcript https://youtu.be/abc123 live ja, llm nein", channel="signal"))

    bot_texts = [entry["bot_text"] for entry in account_store.read_memory_entries(account_id)]
    assert "Lokale YouTube-Transkription gestartet. Ich melde mich, sobald sie fertig ist. Live-Ausgabe ist aktiviert." in bot_texts
    assert "YouTube-Transkript (lokales Whisper):\n\nFull local transcript." in bot_texts


def test_engine_youtube_local_options_uses_llm_fallback(monkeypatch, tmp_path):
    from TeeBotus.core.youtube import YouTubeTranscriptError

    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.reply_inputs: list[str] = []

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.reply_inputs.append(user_text)
            if len(self.reply_inputs) == 1:
                return OpenAIResponse('{"live_output": false, "send_to_llm": true, "confidence": 0.91}', "resp-options", None)
            return OpenAIResponse("AI summary.", "resp-youtube", None)

    calls = []

    def fake_transcribe(url, **kwargs):
        calls.append((url, kwargs))
        if kwargs.get("local_allowed") is False:
            raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True)
        return "Local transcript.", "lokales Whisper"

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    monkeypatch.setattr("TeeBotus.runtime.engine._parse_youtube_local_options", lambda _text, **_kwargs: (None, None))
    monkeypatch.setattr("TeeBotus.runtime.engine._record_youtube_parser_miss", lambda *_args, **_kwargs: None)
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(openai_enabled=True, youtube_option_llm_fallback=True),
        openai_client=client,
        llm_client=client,
    )

    actions = engine.process(event(telegram_identity_key(1), "/youtube_transcript https://youtu.be/abc123 mach bitte die passende variante", channel="signal"))

    assert calls == [
        ("https://youtu.be/abc123", {"local_allowed": False, "instance_name": "Depressionsbot"}),
        ("https://youtu.be/abc123", {"local_allowed": True, "live_callback": None, "instance_name": "Depressionsbot"}),
    ]
    assert "Klassifiziere ausschliesslich die Optionen" in client.reply_inputs[0]
    assert "YouTube-Transkript:" in client.reply_inputs[1]
    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "AI summary."


def test_engine_youtube_local_options_do_not_use_llm_fallback_by_default(monkeypatch, tmp_path):
    from TeeBotus.core.youtube import YouTubeTranscriptError

    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.reply_inputs: list[str] = []

        def create_reply(self, user_text, _instructions, previous_response_id=None):
            self.reply_inputs.append(user_text)
            return OpenAIResponse("unexpected", "resp-unexpected", None)

    calls = []

    def fake_transcribe(url, **kwargs):
        calls.append((url, kwargs))
        if kwargs.get("local_allowed") is False:
            raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True)
        return "Local transcript.", "lokales Whisper"

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    monkeypatch.setattr("TeeBotus.runtime.engine._parse_youtube_local_options", lambda _text, **_kwargs: (None, None))
    monkeypatch.setattr("TeeBotus.runtime.engine._record_youtube_parser_miss", lambda *_args, **_kwargs: None)
    client = FakeOpenAIClient()
    engine = TeeBotusEngine(
        account_store=store(tmp_path),
        instructions=BotInstructions(openai_enabled=True),
        openai_client=client,
        llm_client=client,
    )

    actions = engine.process(event(telegram_identity_key(1), "/youtube_transcript https://youtu.be/abc123 mach bitte die passende variante", channel="signal"))

    assert calls == [
        ("https://youtu.be/abc123", {"local_allowed": False, "instance_name": "Depressionsbot"}),
        ("https://youtu.be/abc123", {"local_allowed": True, "live_callback": None, "instance_name": "Depressionsbot"}),
    ]
    assert client.reply_inputs == []
    assert isinstance(actions[0], SendTyping)
    assert actions[1].text == "YouTube-Transkript (lokales Whisper):\n\nLocal transcript."


def test_engine_youtube_natural_group_request_must_address_bot(monkeypatch, tmp_path):
    def fake_transcribe(_url, **_kwargs):
        raise AssertionError("transcribe_youtube_video must not be called")

    monkeypatch.setattr("TeeBotus.runtime.engine.transcribe_youtube_video", fake_transcribe)
    engine = TeeBotusEngine(account_store=store(tmp_path), instructions=BotInstructions())
    incoming = IncomingEvent(
        event_id="matrix:1",
        instance="Depressionsbot",
        channel="matrix",
        adapter_slot=1,
        identity_key=telegram_identity_key(1),
        chat_id="chat-1",
        chat_type="group",
        sender_id="alice",
        text="Bitte transkribiere dieses YouTube Video https://youtu.be/abc123",
        message_ref="1",
    )

    actions = engine.process(incoming)

    assert actions == []


def test_account_edit_sets_pending_flow(tmp_path):
    account_store = store(tmp_path)
    engine = TeeBotusEngine(account_store=account_store)
    identity = telegram_identity_key(1)

    result = engine.process_identity_flows(event(identity, "/account_edit"))
    account_id = account_store.get_account_for_identity(identity)

    assert result.handled is True
    assert account_id is not None
    assert engine.state.get_pending_flow("Depressionsbot", account_id, "account_edit") == {
        "step": "start",
        "chat_id": "chat-1",
        "channel": "telegram",
        "identity_key": identity,
    }


def test_register_reports_real_store_error_separately_from_existing_secret():
    class Store:
        def register_account(self, account_id):
            raise AccountStoreError("secret backend unavailable")

    text = TeeBotusEngine(account_store=Store())._register_text("a" * 128)  # type: ignore[arg-type]

    assert "Store-/Crypto-Fehlers" in text
    assert "existiert bereits" not in text
