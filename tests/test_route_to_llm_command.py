from __future__ import annotations

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.base import LLMResponse
from TeeBotus.llm.profiles import LLMProfile, LLMRoutingRule
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, telegram_identity_key
from TeeBotus.runtime.engine import TeeBotusEngine
from TeeBotus.runtime.events import IncomingEvent
from TeeBotus.runtime.llm_route_command import parse_route_to_command, resolve_route_to_target


def _store(tmp_path, instance_name: str = "Depressionsbot") -> AccountStore:
    return AccountStore(tmp_path / "accounts", instance_name, StaticSecretProvider(b"r" * 32))


def _event(identity_key: str, text: str, *, instance: str = "Depressionsbot") -> IncomingEvent:
    return IncomingEvent(
        event_id="telegram:1",
        instance=instance,
        channel="telegram",
        adapter_slot=1,
        account_id="",
        identity_key=identity_key,
        chat_id="chat-1",
        chat_type="private",
        sender_id=identity_key,
        sender_name="Admin",
        text=text,
        message_ref="1",
    )


def test_parse_route_to_command_accepts_alias_and_inline_prompt() -> None:
    parsed = parse_route_to_command("/RouteToOAI Sag kurz hallo")

    assert parsed is not None
    assert parsed.target == "OAI"
    assert parsed.prompt == "Sag kurz hallo"


def test_resolve_route_to_target_uses_aliases_profiles_and_purposes() -> None:
    profiles = {
        "openai_premium": LLMProfile("openai_premium", "openai", "gpt-test", api_key_env="OPENAI_API_KEY"),
        "hf_pool_default": LLMProfile("hf_pool_default", "hf_pool", "pool:default#normal_chat"),
        "local_ollama": LLMProfile("local_ollama", "litellm", "ollama_chat/llama3.2:3b", "http://127.0.0.1:11434"),
    }
    routing = {
        "structured_decision": LLMRoutingRule("structured_decision", "hf_pool_default", "local_ollama"),
    }

    openai = resolve_route_to_target("OAI", profiles=profiles, routing=routing)
    hf = resolve_route_to_target("HF", profiles=profiles, routing=routing)
    purpose = resolve_route_to_target("StructuredDecision", profiles=profiles, default_profile="local_ollama", routing=routing)

    assert openai.kind == "profile"
    assert openai.name == "openai_premium"
    assert hf.provider == "hf_pool"
    assert purpose.kind == "purpose"
    assert purpose.name == "structured_decision"
    assert purpose.provider == "hf_pool"


def test_route_to_llm_inline_prompt_is_admin_only_and_bypasses_normal_llm(tmp_path, monkeypatch) -> None:
    account_store = _store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    monkeypatch.setenv("TEEBOTUS_ADMIN_ACCOUNT_IDS_DEPRESSIONSBOT", account_id)
    calls: list[dict[str, object]] = []

    class FakeClient:
        def create_reply(self, user_text, _instructions, previous_response_id=None):
            calls.append({"user_text": user_text, "previous_response_id": previous_response_id})
            return LLMResponse("direkte antwort", provider="fake", model="fake-model")

    def factory(**kwargs):
        calls.append({"factory": kwargs})
        return FakeClient()

    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(llm_enabled=True),
        llm_client=FakeClient(),
        route_to_client_factory=factory,
    )

    actions = engine.process(_event(identity, "/RouteToOAI Was bist du?"))

    assert len(actions) == 2
    assert actions[1].text.startswith("[Profil openai_premium | openai /")
    assert "direkte antwort" in actions[1].text
    factory_call = calls[0]["factory"]
    assert isinstance(factory_call, dict)
    assert factory_call["profile"] == "openai_premium"
    routed_instructions = factory_call["instructions"]
    assert isinstance(routed_instructions, BotInstructions)
    assert routed_instructions.openai_instructions_text() == ""
    assert calls[1]["user_text"] == "Was bist du?"
    assert calls[1]["previous_response_id"] is None


def test_route_to_llm_rejects_non_admin(tmp_path) -> None:
    account_store = _store(tmp_path)
    identity = telegram_identity_key(1)
    engine = TeeBotusEngine(account_store=account_store)

    actions = engine.process(_event(identity, "/RouteToOAI Hallo"))

    assert len(actions) == 1
    assert "Nur Admin-Accounts" in actions[0].text


def test_route_to_llm_accepts_status_auth_admin(tmp_path) -> None:
    account_store = _store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.write_status_auth_state(
        account_id,
        {
            "schema_version": 1,
            "authorized": True,
            "admin_opt_out": False,
            "source": "runtime_admin_command",
        },
    )

    class FakeClient:
        def create_reply(self, user_text, _instructions, previous_response_id=None):
            return LLMResponse(f"direkt: {user_text}", provider="fake", model="fake-model")

    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(llm_enabled=True),
        route_to_client_factory=lambda **_kwargs: FakeClient(),
    )

    actions = engine.process(_event(identity, "/RouteToOAI Hallo"))

    assert len(actions) == 2
    assert "direkt: Hallo" in actions[1].text


def test_route_to_llm_without_prompt_routes_next_admin_message_once(tmp_path, monkeypatch) -> None:
    account_store = _store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    monkeypatch.setenv("TEEBOTUS_ADMIN_ACCOUNT_IDS_DEPRESSIONSBOT", account_id)
    prompts: list[str] = []

    class FakeClient:
        def create_reply(self, user_text, _instructions, previous_response_id=None):
            prompts.append(user_text)
            return LLMResponse("naechste antwort", provider="fake", model="fake-model")

    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(llm_enabled=True),
        route_to_client_factory=lambda **_kwargs: FakeClient(),
    )

    armed = engine.process(_event(identity, "/RouteToHF"))
    routed = engine.process(_event(identity, "direkt an hf bitte"))

    assert "Route bereit" in armed[0].text
    assert prompts == ["direkt an hf bitte"]
    assert "naechste antwort" in routed[1].text
    assert engine.state.get_pending_flow("Depressionsbot", account_id, "llm_route_to") is None
