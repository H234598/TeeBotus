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


def _event(
    identity_key: str,
    text: str,
    *,
    instance: str = "Depressionsbot",
    chat_id: str = "chat-1",
    channel: str = "telegram",
    adapter_slot: int = 1,
) -> IncomingEvent:
    return IncomingEvent(
        event_id="telegram:1",
        instance=instance,
        channel=channel,
        adapter_slot=adapter_slot,
        account_id="",
        identity_key=identity_key,
        chat_id=chat_id,
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
        "gemini_2_5_flash_stateful": LLMProfile(
            "gemini_2_5_flash_stateful",
            "litellm_gemini_stateful",
            "gemini/gemini-2.5-flash",
            api_key_env="GEMINI_API_KEY",
        ),
        "local_ollama": LLMProfile("local_ollama", "litellm", "ollama_chat/llama3.2:3b", "http://127.0.0.1:11434"),
    }
    routing = {
        "structured_decision": LLMRoutingRule("structured_decision", "hf_pool_default", "local_ollama"),
    }

    openai = resolve_route_to_target("OAI", profiles=profiles, routing=routing)
    hf = resolve_route_to_target("HF", profiles=profiles, routing=routing)
    gemini25 = resolve_route_to_target("Gemini25", profiles=profiles, routing=routing)
    purpose = resolve_route_to_target("StructuredDecision", profiles=profiles, default_profile="local_ollama", routing=routing)
    explicit_purpose = resolve_route_to_target(
        "purpose:structured_decision",
        profiles=profiles,
        default_profile="local_ollama",
        routing=routing,
    )

    assert openai.kind == "profile"
    assert openai.name == "openai_premium"
    assert hf.provider == "hf_pool"
    assert gemini25.kind == "profile"
    assert gemini25.name == "gemini_2_5_flash_stateful"
    assert gemini25.model == "gemini/gemini-2.5-flash"
    assert purpose.kind == "purpose"
    assert purpose.name == "structured_decision"
    assert purpose.provider == "hf_pool"
    assert explicit_purpose.kind == "purpose"
    assert explicit_purpose.name == "structured_decision"


def test_resolve_route_to_target_displays_litellm_openai_profile_as_openai() -> None:
    profiles = {
        "openai_premium": LLMProfile("openai_premium", "litellm", "openai/gpt-5.5", api_key_env="OPENAI_API_KEY"),
    }

    target = resolve_route_to_target("OAI", profiles=profiles, routing={})

    assert target.provider == "openai"
    assert target.model == "openai/gpt-5.5"


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
        openai_api_key="runtime-openai-key",
        route_to_client_factory=factory,
    )

    actions = engine.process(_event(identity, "/RouteToOAI Was bist du?"))

    assert len(actions) == 2
    assert actions[1].text.startswith("[Profil openai_premium | openai /")
    assert "direkte antwort" in actions[1].text
    factory_call = calls[0]["factory"]
    assert isinstance(factory_call, dict)
    assert factory_call["profile"] == "openai_premium"
    assert factory_call["allow_local_ollama_offload"] is False
    assert factory_call["default_api_key"] == "runtime-openai-key"
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


def test_route_to_llm_factory_failure_is_user_visible(tmp_path) -> None:
    account_store = _store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.write_status_auth_state(account_id, {"schema_version": 1, "authorized": True, "admin_opt_out": False})

    def broken_factory(**_kwargs):
        raise RuntimeError("route backend unavailable")

    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(llm_enabled=True),
        route_to_client_factory=broken_factory,
    )

    actions = engine.process(_event(identity, "/RouteToOAI Hallo"))

    assert len(actions) == 1
    assert "konnte nicht initialisiert werden" in actions[0].text
    assert "RuntimeError" in actions[0].text


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


def test_route_to_llm_reports_pending_state_setup_failure(tmp_path, monkeypatch) -> None:
    account_store = _store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    monkeypatch.setenv("TEEBOTUS_ADMIN_ACCOUNT_IDS_DEPRESSIONSBOT", account_id)
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions())

    monkeypatch.setattr(
        engine.state,
        "set_pending_flow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("pending state unavailable")),
    )

    actions = engine.process(_event(identity, "/RouteToHF"))

    assert actions[0].text == "RouteTo konnte gerade nicht gelesen oder vorbereitet werden. Bitte spaeter erneut versuchen."


def test_route_to_llm_reports_pending_state_lookup_failure(tmp_path, monkeypatch) -> None:
    account_store = _store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    monkeypatch.setenv("TEEBOTUS_ADMIN_ACCOUNT_IDS_DEPRESSIONSBOT", account_id)
    engine = TeeBotusEngine(account_store=account_store, instructions=BotInstructions())
    original_get = engine.state.get_pending_flow

    def broken_get(instance, current_account_id, flow_type, **kwargs):
        if flow_type == "llm_route_to":
            raise RuntimeError("pending state unavailable")
        return original_get(instance, current_account_id, flow_type, **kwargs)

    monkeypatch.setattr(engine.state, "get_pending_flow", broken_get)

    actions = engine.process(_event(identity, "normale Nachricht"))

    assert actions[0].text == "RouteTo konnte gerade nicht gelesen oder vorbereitet werden. Bitte spaeter erneut versuchen."


def test_route_to_llm_does_not_route_when_pending_state_consumption_fails(tmp_path, monkeypatch) -> None:
    account_store = _store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    monkeypatch.setenv("TEEBOTUS_ADMIN_ACCOUNT_IDS_DEPRESSIONSBOT", account_id)
    prompts: list[str] = []

    class FakeClient:
        def create_reply(self, user_text, _instructions, previous_response_id=None):
            prompts.append(user_text)
            return LLMResponse("unerwartete route", provider="fake", model="fake-model")

    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(llm_enabled=True),
        route_to_client_factory=lambda **_kwargs: FakeClient(),
    )
    armed = engine.process(_event(identity, "/RouteToHF"))
    monkeypatch.setattr(
        engine.state,
        "pop_pending_flow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("pending state unavailable")),
    )

    actions = engine.process(_event(identity, "direkt an hf bitte"))

    assert "Route bereit" in armed[0].text
    assert actions[0].text == "RouteTo konnte gerade nicht gelesen oder vorbereitet werden. Bitte spaeter erneut versuchen."
    assert prompts == []


def test_route_to_llm_pending_prompt_is_bound_to_the_originating_chat(tmp_path, monkeypatch) -> None:
    account_store = _store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    monkeypatch.setenv("TEEBOTUS_ADMIN_ACCOUNT_IDS_DEPRESSIONSBOT", account_id)
    prompts: list[str] = []

    class FakeClient:
        def create_reply(self, user_text, _instructions, previous_response_id=None):
            prompts.append(user_text)
            return LLMResponse("falscher chat", provider="fake", model="fake-model")

    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(llm_enabled=True),
        route_to_client_factory=lambda **_kwargs: FakeClient(),
    )

    armed = engine.process(_event(identity, "/RouteToHF", chat_id="chat-1"))
    other_chat = engine.process(_event(identity, "nicht an den anderen chat", chat_id="chat-2"))

    assert "Route bereit" in armed[0].text
    assert prompts == []
    assert "falscher chat" not in "\n".join(action.text for action in other_chat if hasattr(action, "text"))
    pending = engine.state.get_pending_flow("Depressionsbot", account_id, "llm_route_to")
    assert pending is not None
    assert pending["context"]["chat_id"] == "chat-1"


def test_route_to_llm_cancel_is_bound_to_the_originating_chat(tmp_path, monkeypatch) -> None:
    account_store = _store(tmp_path)
    identity = telegram_identity_key(1)
    account_id = account_store.resolve_or_create_account(identity)
    monkeypatch.setenv("TEEBOTUS_ADMIN_ACCOUNT_IDS_DEPRESSIONSBOT", account_id)
    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(llm_enabled=True),
        route_to_client_factory=lambda **_kwargs: object(),
    )

    armed = engine.process(_event(identity, "/RouteToHF", chat_id="chat-1"))
    foreign_cancel = engine.process(_event(identity, "/cancel", chat_id="chat-2"))

    assert "Route bereit" in armed[0].text
    assert all("RouteTo abgebrochen" not in getattr(action, "text", "") for action in foreign_cancel)
    assert engine.state.get_pending_flow("Depressionsbot", account_id, "llm_route_to") is not None

    local_cancel = engine.process(_event(identity, "/cancel", chat_id="chat-1"))

    assert local_cancel[0].text == "RouteTo abgebrochen."
    assert engine.state.get_pending_flow("Depressionsbot", account_id, "llm_route_to") is None
