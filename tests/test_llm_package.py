from __future__ import annotations

import pytest

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm import (
    LLMError,
    LLMImage,
    LLMResponse,
    LLMVoice,
    LiteLLMTextClient,
    OpenAIProvider,
    build_text_llm_client,
    normalize_llm_provider,
)
from TeeBotus.llm.capabilities import LITELLM_TEXT_CAPABILITIES, OPENAI_CAPABILITIES
from TeeBotus.llm.config import load_llm_profiles, load_llm_routing, select_llm_route
from TeeBotus.openai_client import OpenAIAPIError, OpenAIImage, OpenAIResponse, OpenAIVoice


def test_plan1_llm_package_exports_existing_router_and_litellm_adapter() -> None:
    assert normalize_llm_provider("lite-llm") == "litellm"
    assert build_text_llm_client(instructions=BotInstructions(), openai_client="openai-client") == "openai-client"
    assert LiteLLMTextClient.__name__ == "LiteLLMTextClient"
    assert LITELLM_TEXT_CAPABILITIES.text is True
    assert LITELLM_TEXT_CAPABILITIES.voice is False
    assert OPENAI_CAPABILITIES.previous_response_id is True
    assert OPENAI_CAPABILITIES.transcription is True


def test_plan2_llm_config_module_loads_profiles_and_routes() -> None:
    profiles = load_llm_profiles()
    default_profile, routing = load_llm_routing()

    assert default_profile == "local_ollama"
    assert {"local_ollama", "hf_mistral", "groq_fast", "gemini_flash", "openai_premium"} <= set(profiles)
    assert {"normal_chat", "structured_decision", "bibliothekar_answer"} <= set(routing)

    normal = select_llm_route("normal chat", profiles=profiles, default_profile=default_profile, routing=routing)
    structured = select_llm_route(
        "structured decision",
        profiles=profiles,
        default_profile=default_profile,
        routing=routing,
        allow_remote_fallback=True,
    )

    assert normal.profile_name == "local_ollama"
    assert normal.provider == "litellm"
    assert normal.base_url == "http://127.0.0.1:11434"
    assert structured.profile_name == "local_ollama"
    assert structured.fallback_profile_name == "groq_fast"
    assert structured.fallback_models == ("groq/llama-3.1-8b-instant",)


def test_openai_provider_maps_existing_client_payloads_to_neutral_types() -> None:
    class FakeOpenAIClient:
        reply_calls = []
        voice_calls = []
        image_calls = []
        transcription_calls = []

        def create_reply(self, user_text, instructions, previous_response_id=None):
            self.reply_calls.append((user_text, instructions.openai_model, previous_response_id))
            return OpenAIResponse("Antwort.", "resp-1", "default")

        def create_voice(self, text, instructions):
            self.voice_calls.append((text, instructions.openai_voice))
            return OpenAIVoice(b"voice", "voice.ogg", "audio/ogg")

        def generate_image(self, prompt, instructions, *, filename="bild.png"):
            self.image_calls.append((prompt, instructions.openai_image_model, filename))
            return OpenAIImage(b"png", "bild.png", "image/png")

        def transcribe_audio(self, audio, filename, instructions, model=None):
            self.transcription_calls.append((audio, filename, instructions.openai_transcription_language, model))
            return "Transkript."

    instructions = BotInstructions(openai_model="gpt-test", openai_voice="onyx", openai_image_model="gpt-image-test")
    fake_client = FakeOpenAIClient()
    provider = OpenAIProvider(fake_client)  # type: ignore[arg-type]

    response = provider.create_reply("Ping", instructions, "resp-old")
    voice = provider.create_voice("Sag Hallo", instructions)
    image = provider.generate_image("Bild", instructions, filename="custom.png")
    transcript = provider.transcribe_audio(b"audio", "voice.ogg", instructions, model="whisper-test")

    assert response == LLMResponse(
        text="Antwort.",
        response_id="resp-1",
        provider="openai",
        model="gpt-test",
        service_tier="default",
    )
    assert voice == LLMVoice(b"voice", "voice.ogg", "audio/ogg")
    assert image == LLMImage(b"png", "bild.png", "image/png")
    assert transcript == "Transkript."
    assert fake_client.reply_calls == [("Ping", "gpt-test", "resp-old")]
    assert fake_client.voice_calls == [("Sag Hallo", "onyx")]
    assert fake_client.image_calls == [("Bild", "gpt-image-test", "custom.png")]
    assert fake_client.transcription_calls == [(b"audio", "voice.ogg", "de", "whisper-test")]


@pytest.mark.parametrize(
    ("method_name", "args", "kwargs"),
    [
        ("create_reply", ("Ping", BotInstructions(), None), {}),
        ("create_voice", ("Sag Hallo", BotInstructions()), {}),
        ("generate_image", ("Bild", BotInstructions()), {"filename": "bild.png"}),
        ("transcribe_audio", (b"audio", "voice.ogg", BotInstructions()), {"model": "whisper-test"}),
    ],
)
def test_openai_provider_wraps_openai_api_errors_as_neutral_llm_errors(method_name, args, kwargs) -> None:
    class BrokenOpenAIClient:
        def __getattr__(self, _name):
            def fail(*_args, **_kwargs):
                raise OpenAIAPIError("openai boom")

            return fail

    provider = OpenAIProvider(BrokenOpenAIClient())  # type: ignore[arg-type]

    with pytest.raises(LLMError, match="openai boom") as error:
        getattr(provider, method_name)(*args, **kwargs)

    assert isinstance(error.value.__cause__, OpenAIAPIError)
