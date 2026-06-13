from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

from .instructions import BotInstructions

RESPONSES_URL = "https://api.openai.com/v1/responses"
SPEECH_URL = "https://api.openai.com/v1/audio/speech"
TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"
LOGGER = logging.getLogger("TeeBotus.openai_client")


class OpenAIAPIError(RuntimeError):
    """Raised when OpenAI returns an unsuccessful response."""


@dataclass(frozen=True)
class OpenAIResponse:
    text: str
    response_id: str | None
    service_tier: str | None


@dataclass(frozen=True)
class OpenAIVoice:
    audio: bytes
    filename: str
    content_type: str


class OpenAIClient:
    def __init__(self, api_key: str, timeout: int = 90) -> None:
        if not api_key:
            raise ValueError("OpenAI API key must not be empty")
        self.api_key = api_key
        self.timeout = timeout

    def create_reply(
        self,
        user_text: str,
        instructions: BotInstructions,
        previous_response_id: str | None = None,
    ) -> OpenAIResponse:
        payload = build_response_payload(user_text, instructions, previous_response_id)
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            RESPONSES_URL,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            timeout = instructions.openai_timeout_seconds or self.timeout
            with urllib.request.urlopen(request, timeout=timeout) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except TimeoutError as exc:
            raise OpenAIAPIError(f"OpenAI network timeout: {exc}") from exc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise OpenAIAPIError(f"OpenAI HTTP error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise OpenAIAPIError(f"OpenAI network error: {exc.reason}") from exc

        text = extract_output_text(response_payload)
        if not text:
            raise OpenAIAPIError(summarize_empty_response(response_payload, instructions.openai_max_output_tokens))
        service_tier = response_payload.get("service_tier")
        if (
            instructions.openai_service_tier
            and isinstance(service_tier, str)
            and service_tier != instructions.openai_service_tier
        ):
            LOGGER.warning(
                "Requested OpenAI service_tier=%s but API reported service_tier=%s.",
                instructions.openai_service_tier,
                service_tier,
            )
        return OpenAIResponse(
            text=text,
            response_id=response_payload.get("id"),
            service_tier=service_tier if isinstance(service_tier, str) else None,
        )

    def create_voice(self, text: str, instructions: BotInstructions) -> OpenAIVoice:
        payload = build_speech_payload(text, instructions)
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            SPEECH_URL,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            timeout = instructions.openai_timeout_seconds or self.timeout
            with urllib.request.urlopen(request, timeout=timeout) as response:
                audio = response.read()
                content_type = response.headers.get_content_type() or _voice_content_type(instructions.openai_voice_format)
        except TimeoutError as exc:
            raise OpenAIAPIError(f"OpenAI speech network timeout: {exc}") from exc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise OpenAIAPIError(f"OpenAI speech HTTP error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise OpenAIAPIError(f"OpenAI speech network error: {exc.reason}") from exc

        if not audio:
            raise OpenAIAPIError("OpenAI speech response did not contain audio data")
        return OpenAIVoice(
            audio=audio,
            filename=_voice_filename(instructions.openai_voice_format),
            content_type=content_type,
        )

    def transcribe_audio(
        self,
        audio: bytes,
        filename: str,
        instructions: BotInstructions,
        model: str | None = None,
    ) -> str:
        if not audio:
            raise OpenAIAPIError("OpenAI transcription request did not contain audio data")

        fields = build_transcription_fields(instructions, model=model)
        body, content_type = _encode_multipart_form_data(
            fields,
            [("file", filename, _audio_content_type(filename), audio)],
        )
        request = urllib.request.Request(
            TRANSCRIPTIONS_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": content_type,
            },
        )

        try:
            timeout = instructions.openai_timeout_seconds or self.timeout
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except TimeoutError as exc:
            raise OpenAIAPIError(f"OpenAI transcription network timeout: {exc}") from exc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise OpenAIAPIError(f"OpenAI transcription HTTP error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise OpenAIAPIError(f"OpenAI transcription network error: {exc.reason}") from exc

        if not isinstance(payload, dict):
            raise OpenAIAPIError("OpenAI transcription response was not a JSON object")
        if "text" not in payload:
            keys = ", ".join(sorted(str(key) for key in payload.keys()))
            raise OpenAIAPIError(f"OpenAI transcription response did not include a text field; keys={keys}")
        return extract_transcription_text(payload)


def build_response_payload(
    user_text: str,
    instructions: BotInstructions,
    previous_response_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": instructions.openai_model,
        "instructions": instructions.openai_instructions_text(),
        "input": user_text,
    }

    if previous_response_id:
        payload["previous_response_id"] = previous_response_id
    if instructions.openai_max_output_tokens is not None:
        payload["max_output_tokens"] = instructions.openai_max_output_tokens
    if instructions.openai_service_tier:
        payload["service_tier"] = instructions.openai_service_tier
    if instructions.openai_web_search:
        payload["tools"] = [
            {
                "type": "web_search",
                "search_context_size": instructions.openai_web_search_context_size,
            }
        ]
        payload["tool_choice"] = "required" if instructions.openai_web_search_required else "auto"
    if instructions.openai_reasoning_effort:
        payload["reasoning"] = {"effort": instructions.openai_reasoning_effort}
    if instructions.openai_verbosity:
        payload["text"] = {"verbosity": instructions.openai_verbosity}
    return payload


def build_speech_payload(text: str, instructions: BotInstructions) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": instructions.openai_voice_model,
        "input": text,
        "voice": instructions.openai_voice,
        "response_format": instructions.openai_voice_format,
        "speed": instructions.openai_voice_speed,
    }
    if instructions.openai_voice_instructions and instructions.openai_voice_model not in {"tts-1", "tts-1-hd"}:
        payload["instructions"] = instructions.openai_voice_instructions
    return payload


def build_transcription_fields(instructions: BotInstructions, model: str | None = None) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "model": (model or instructions.openai_transcription_model).strip(),
        "response_format": "json",
    }
    if instructions.openai_transcription_language.strip():
        fields["language"] = instructions.openai_transcription_language.strip()
    if instructions.openai_transcription_prompt.strip():
        fields["prompt"] = instructions.openai_transcription_prompt.strip()
    return fields


def _voice_filename(response_format: str) -> str:
    extension = {
        "opus": "ogg",
        "mp3": "mp3",
        "aac": "aac",
        "flac": "flac",
        "wav": "wav",
        "pcm": "pcm",
    }.get(response_format, response_format or "ogg")
    return f"voice.{extension}"


def _voice_content_type(response_format: str) -> str:
    return {
        "opus": "audio/ogg",
        "mp3": "audio/mpeg",
        "aac": "audio/aac",
        "flac": "audio/flac",
        "wav": "audio/wav",
        "pcm": "audio/pcm",
    }.get(response_format, "application/octet-stream")


def _audio_content_type(filename: str) -> str:
    extension = filename.rsplit(".", maxsplit=1)[-1].casefold() if "." in filename else ""
    return {
        "aac": "audio/aac",
        "flac": "audio/flac",
        "m4a": "audio/mp4",
        "mp3": "audio/mpeg",
        "mp4": "audio/mp4",
        "oga": "audio/ogg",
        "ogg": "audio/ogg",
        "opus": "audio/ogg",
        "wav": "audio/wav",
        "webm": "audio/webm",
    }.get(extension, "application/octet-stream")


def extract_output_text(response_payload: dict[str, Any]) -> str:
    direct_text = response_payload.get("output_text")
    if isinstance(direct_text, str) and direct_text.strip():
        return direct_text.strip()

    parts: list[str] = []
    for output_item in response_payload.get("output", []):
        if not isinstance(output_item, dict):
            continue
        for content_item in output_item.get("content", []):
            if not isinstance(content_item, dict):
                continue
            if content_item.get("type") == "output_text":
                text = content_item.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif content_item.get("type") == "refusal":
                refusal = content_item.get("refusal")
                if isinstance(refusal, str):
                    parts.append(refusal)

    return "\n".join(part.strip() for part in parts if part.strip())


def extract_transcription_text(response_payload: dict[str, Any]) -> str:
    text = response_payload.get("text")
    if isinstance(text, str):
        return text.strip()
    return ""


def _encode_multipart_form_data(
    fields: dict[str, Any],
    files: list[tuple[str, str, str, bytes]],
) -> tuple[bytes, str]:
    boundary = f"----telegram-bot-openai-{uuid.uuid4().hex}"
    body = bytearray()

    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")

    for field_name, filename, content_type, data in files:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            (
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
        )
        body.extend(data)
        body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def summarize_empty_response(response_payload: dict[str, Any], max_output_tokens: int | None) -> str:
    response_id = response_payload.get("id")
    status = response_payload.get("status")
    incomplete_details = response_payload.get("incomplete_details")
    service_tier = response_payload.get("service_tier")
    usage = response_payload.get("usage") if isinstance(response_payload.get("usage"), dict) else {}
    output_tokens = usage.get("output_tokens")
    output_details = usage.get("output_tokens_details")
    reasoning_tokens = None
    if isinstance(output_details, dict):
        reasoning_tokens = output_details.get("reasoning_tokens")

    parts = [
        "OpenAI response did not contain output text",
        f"id={response_id!r}",
        f"status={status!r}",
        f"service_tier={service_tier!r}",
    ]
    if incomplete_details:
        parts.append(f"incomplete_details={incomplete_details!r}")
    if output_tokens is not None:
        parts.append(f"output_tokens={output_tokens!r}")
    if reasoning_tokens is not None:
        parts.append(f"reasoning_tokens={reasoning_tokens!r}")
    if max_output_tokens is not None:
        parts.append(f"configured_max_output_tokens={max_output_tokens!r}")
        if reasoning_tokens == max_output_tokens:
            parts.append("reasoning consumed the full output budget; increase max_output_tokens or lower reasoning_effort")
    return "; ".join(parts)
