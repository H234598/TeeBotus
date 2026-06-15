from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from TeeBotus.instructions import BotInstructions


class LLMError(RuntimeError):
    """Provider-neutral LLM error."""


class LLMAPIError(LLMError):
    """Backward-compatible text LLM error alias."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    response_id: str | None = None
    provider: str = ""
    model: str = ""
    service_tier: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class LLMVoice:
    audio: bytes
    filename: str
    content_type: str


@dataclass(frozen=True)
class LLMImage:
    data: bytes
    filename: str
    content_type: str


class BaseLLMClient(Protocol):
    def create_reply(
        self,
        user_text: str,
        instructions: BotInstructions,
        previous_response_id: str | None = None,
    ) -> LLMResponse:
        ...

    def create_voice(self, text: str, instructions: BotInstructions) -> LLMVoice:
        ...

    def generate_image(self, prompt: str, instructions: BotInstructions, *, filename: str = "bild.png") -> LLMImage:
        ...

    def transcribe_audio(
        self,
        audio: bytes,
        filename: str,
        instructions: BotInstructions,
        model: str | None = None,
    ) -> str:
        ...
