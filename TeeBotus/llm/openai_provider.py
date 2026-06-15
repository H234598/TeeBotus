from __future__ import annotations

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.base import LLMImage, LLMResponse, LLMVoice
from TeeBotus.openai_client import OpenAIClient


class OpenAIProvider:
    """Provider-neutral wrapper around the existing OpenAIClient.

    The wrapped client keeps owning OpenAI-specific features such as
    previous_response_id, web search, image generation, TTS, and transcription.
    This class only maps payload types into the neutral LLM surface.
    """

    provider = "openai"

    def __init__(self, client: OpenAIClient) -> None:
        self.client = client

    def create_reply(
        self,
        user_text: str,
        instructions: BotInstructions,
        previous_response_id: str | None = None,
    ) -> LLMResponse:
        response = self.client.create_reply(user_text, instructions, previous_response_id)
        return LLMResponse(
            text=response.text,
            response_id=response.response_id,
            provider=self.provider,
            model=instructions.openai_model,
            service_tier=response.service_tier,
        )

    def create_voice(self, text: str, instructions: BotInstructions) -> LLMVoice:
        voice = self.client.create_voice(text, instructions)
        return LLMVoice(audio=voice.audio, filename=voice.filename, content_type=voice.content_type)

    def generate_image(self, prompt: str, instructions: BotInstructions, *, filename: str = "bild.png") -> LLMImage:
        image = self.client.generate_image(prompt, instructions, filename=filename)
        return LLMImage(data=image.data, filename=image.filename, content_type=image.content_type)

    def transcribe_audio(
        self,
        audio: bytes,
        filename: str,
        instructions: BotInstructions,
        model: str | None = None,
    ) -> str:
        return self.client.transcribe_audio(audio, filename, instructions, model=model)
