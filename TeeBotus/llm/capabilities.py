from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LLMCapabilities:
    text: bool = True
    previous_response_id: bool = False
    voice: bool = False
    image: bool = False
    transcription: bool = False
    tool_calls: bool = False


OPENAI_CAPABILITIES = LLMCapabilities(
    text=True,
    previous_response_id=True,
    voice=True,
    image=True,
    transcription=True,
    tool_calls=True,
)

LITELLM_TEXT_CAPABILITIES = LLMCapabilities(text=True)
