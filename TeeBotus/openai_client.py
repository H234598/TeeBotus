from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
import uuid
import base64
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from .instructions import BotInstructions
from TeeBotus.runtime.log_context import logging_context, next_llm_call_id

RESPONSES_URL = "https://api.openai.com/v1/responses"
IMAGES_URL = "https://api.openai.com/v1/images/generations"
SPEECH_URL = "https://api.openai.com/v1/audio/speech"
TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"
LOGGER = logging.getLogger("TeeBotus.openai_client")
_SAFE_PATH_SEGMENT_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*)")


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


@dataclass(frozen=True)
class OpenAIImage:
    data: bytes
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
        payload = build_response_payload(user_text, instructions, previous_response_id, cache_scope="reply")
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

        call_id = next_llm_call_id("openai")
        timeout = instructions.openai_timeout_seconds or self.timeout
        with logging_context(
            component="openai_client",
            operation="reply",
            llm_call_id=call_id,
            provider="openai",
            model=instructions.openai_model,
            api_base="https://api.openai.com/v1",
        ):
            started_at = time.perf_counter()
            LOGGER.info(
                "OpenAI reply request started call_id=%s model=%s timeout_seconds=%s request_chars=%s previous_response=%s",
                call_id,
                instructions.openai_model,
                timeout,
                len(user_text),
                bool(previous_response_id),
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    response_payload = json.loads(response.read().decode("utf-8"))
            except TimeoutError as exc:
                raise OpenAIAPIError(f"OpenAI network timeout: {exc}") from exc
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise OpenAIAPIError(f"OpenAI HTTP error {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                raise OpenAIAPIError(f"OpenAI network error: {exc.reason}") from exc

            log_openai_usage("reply", payload, response_payload)
            text = extract_output_text(response_payload)
            LOGGER.info(
                "OpenAI reply request finished call_id=%s elapsed_ms=%s response_id=%s response_chars=%s",
                call_id,
                int((time.perf_counter() - started_at) * 1000),
                response_payload.get("id") if isinstance(response_payload, dict) else None,
                len(text),
            )
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

    def generate_image(self, prompt: str, instructions: BotInstructions, *, filename: str = "bild.png") -> OpenAIImage:
        payload = build_image_payload(prompt, instructions)
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            IMAGES_URL,
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
            raise OpenAIAPIError(f"OpenAI image network timeout: {exc}") from exc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise OpenAIAPIError(f"OpenAI image HTTP error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise OpenAIAPIError(f"OpenAI image network error: {exc.reason}") from exc

        log_openai_usage("image", payload, response_payload)
        image_data = extract_image_bytes(response_payload)
        if not image_data:
            raise OpenAIAPIError("OpenAI image response did not contain image data")
        content_type = _image_content_type(instructions.openai_image_format)
        return OpenAIImage(data=image_data, filename=_image_filename(filename, instructions.openai_image_format), content_type=content_type)

    def create_tool_calls(
        self,
        user_text: str,
        instructions: BotInstructions,
        tools: list[dict[str, Any]],
        previous_response_id: str | None = None,
    ) -> dict[str, Any]:
        payload = build_response_payload(user_text, instructions, previous_response_id, cache_scope="tool")
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
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
            raise OpenAIAPIError(f"OpenAI tool-call network timeout: {exc}") from exc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise OpenAIAPIError(f"OpenAI tool-call HTTP error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise OpenAIAPIError(f"OpenAI tool-call network error: {exc.reason}") from exc
        if not isinstance(response_payload, dict):
            raise OpenAIAPIError("OpenAI tool-call response was not a JSON object")
        log_openai_usage("tool", payload, response_payload)
        return response_payload

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
        log_openai_usage("speech", payload, None, extra={"response_bytes": len(audio), "content_type": content_type})
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
        log_openai_usage("transcription", fields, payload)
        if "text" not in payload:
            keys = ", ".join(sorted(str(key) for key in payload.keys()))
            raise OpenAIAPIError(f"OpenAI transcription response did not include a text field; keys={keys}")
        return extract_transcription_text(payload)


def build_response_payload(
    user_text: str,
    instructions: BotInstructions,
    previous_response_id: str | None = None,
    *,
    cache_scope: str = "reply",
) -> dict[str, Any]:
    instruction_text = instructions.openai_instructions_text()
    payload: dict[str, Any] = {
        "model": instructions.openai_model,
        "instructions": instruction_text,
        "input": user_text,
        "prompt_cache_key": build_prompt_cache_key(instructions.openai_model, instruction_text, cache_scope),
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


def build_prompt_cache_key(model: str, instruction_text: str, scope: str = "reply") -> str:
    normalized_scope = "".join(char for char in str(scope or "reply").casefold() if char.isalnum() or char in {"_", "-"})[:24] or "reply"
    digest = sha256(f"{model}\n{normalized_scope}\n{instruction_text}".encode("utf-8")).hexdigest()[:24]
    return f"teebotus-{normalized_scope}-{digest}"


def log_openai_usage(
    operation: str,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any] | None,
    *,
    extra: dict[str, Any] | None = None,
) -> None:
    usage = response_payload.get("usage") if isinstance(response_payload, dict) and isinstance(response_payload.get("usage"), dict) else {}
    event: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "operation": operation,
        "model": request_payload.get("model"),
        "service_tier_requested": request_payload.get("service_tier"),
        "service_tier_reported": response_payload.get("service_tier") if isinstance(response_payload, dict) else None,
        "response_id": response_payload.get("id") if isinstance(response_payload, dict) else None,
        "prompt_cache_key": request_payload.get("prompt_cache_key"),
        "request_chars": len(json.dumps(request_payload, ensure_ascii=False, sort_keys=True)),
        "request_token_estimate": _rough_token_estimate(request_payload),
        "tools_count": len(request_payload.get("tools") or []) if isinstance(request_payload.get("tools"), list) else 0,
        "tool_choice": request_payload.get("tool_choice"),
        "usage": dict(usage),
        "input_tokens": _first_int(usage, ("input_tokens", "prompt_tokens")),
        "cached_tokens": _cached_token_count(usage),
        "output_tokens": _first_int(usage, ("output_tokens", "completion_tokens")),
        "reasoning_tokens": _nested_int(usage, ("output_tokens_details", "reasoning_tokens")),
    }
    if extra:
        event.update(extra)
    LOGGER.info("openai_usage %s", json.dumps(event, ensure_ascii=False, sort_keys=True))
    path = _openai_usage_log_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    except OSError as exc:
        LOGGER.warning("Could not append OpenAI usage log %s: %s", path, exc)


def _openai_usage_log_path() -> Path | None:
    configured = os.environ.get("TEEBOTUS_OPENAI_USAGE_LOG", "").strip()
    if configured.casefold() in {"0", "false", "off", "none", "disabled"}:
        return None
    if configured:
        safe_state_home = _safe_state_home()
        if safe_state_home is None:
            return None
        if "\x00" in configured or "\r" in configured or "\n" in configured or "\t" in configured:
            return None
        if "\\" in configured:
            return None
        is_absolute, parts = _split_safe_relative_parts(configured, operation="openai usage log path")
        if is_absolute:
            return None
        if not parts:
            return None
        try:
            candidate = (safe_state_home / Path(*parts)).resolve()
        except OSError:
            return None
        try:
            candidate.relative_to(safe_state_home)
        except ValueError:
            return None
        if candidate.exists() and candidate.is_dir():
            return None
        return candidate
    state_home = _safe_state_home()
    if state_home is None:
        return None
    return state_home / "TeeBotus" / "openai_usage.jsonl"


def _safe_state_home() -> Path | None:
    configured_state_home = os.environ.get("XDG_STATE_HOME", "").strip()
    if not configured_state_home:
        return Path.home() / ".local" / "state"
    if "\x00" in configured_state_home or "\r" in configured_state_home or "\n" in configured_state_home or "\t" in configured_state_home:
        return None
    if "\\" in configured_state_home:
        return None
    is_absolute, parts = _split_safe_relative_parts(configured_state_home, operation="xdg state home")
    if not parts:
        return None
    try:
        return (Path("/").joinpath(*parts) if is_absolute else Path.cwd().joinpath(*parts)).resolve()
    except OSError:
        return None


def _split_safe_relative_parts(value: str, *, operation: str) -> tuple[bool, tuple[str, ...]]:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{operation} must not be empty")
    if text == "/":
        return True, tuple()
    if "\x00" in text or "\r" in text or "\n" in text or "\t" in text:
        raise ValueError(f"{operation} contains invalid control character")
    is_absolute = text.startswith("/")
    normalized = text[1:] if is_absolute else text
    if not normalized:
        raise ValueError(f"{operation} must not be empty")
    parts: list[str] = []
    for part in normalized.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise ValueError(f"{operation} contains forbidden relative segment")
        if not _SAFE_PATH_SEGMENT_RE.fullmatch(part):
            raise ValueError(f"{operation} contains invalid path segment")
        parts.append(part)
    return is_absolute, tuple(parts)


def _rough_token_estimate(payload: dict[str, Any]) -> int:
    return max(1, (len(json.dumps(payload, ensure_ascii=False, sort_keys=True)) + 3) // 4)


def _first_int(mapping: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, int) and value >= 0:
            return value
    return None


def _nested_int(mapping: dict[str, Any], path: tuple[str, str]) -> int | None:
    outer = mapping.get(path[0])
    if not isinstance(outer, dict):
        return None
    value = outer.get(path[1])
    return value if isinstance(value, int) and value >= 0 else None


def _cached_token_count(usage: dict[str, Any]) -> int | None:
    for outer_key in ("input_tokens_details", "prompt_tokens_details"):
        value = _nested_int(usage, (outer_key, "cached_tokens"))
        if value is not None:
            return value
    return None


def build_image_payload(prompt: str, instructions: BotInstructions) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": instructions.openai_image_model,
        "prompt": str(prompt or "").strip()[: instructions.openai_image_max_prompt_chars],
        "size": instructions.openai_image_size,
    }
    if instructions.openai_image_quality:
        payload["quality"] = instructions.openai_image_quality
    if instructions.openai_image_format:
        payload["output_format"] = instructions.openai_image_format
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


def _image_filename(filename: str, image_format: str) -> str:
    safe_name = str(filename or "").rsplit("/", maxsplit=1)[-1].strip() or "bild.png"
    format_extension = {"jpeg": "jpg", "jpg": "jpg", "png": "png", "webp": "webp"}.get(image_format.casefold(), "png")
    if "." not in safe_name:
        return f"{safe_name}.{format_extension}"
    stem, _dot, _ext = safe_name.rpartition(".")
    return f"{stem or 'bild'}.{format_extension}"


def _image_content_type(image_format: str) -> str:
    return {
        "jpeg": "image/jpeg",
        "jpg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }.get(image_format.casefold(), "image/png")


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


def extract_image_bytes(response_payload: dict[str, Any]) -> bytes:
    data = response_payload.get("data")
    if not isinstance(data, list):
        return b""
    for item in data:
        if not isinstance(item, dict):
            continue
        b64_json = item.get("b64_json")
        if isinstance(b64_json, str) and b64_json.strip():
            try:
                return base64.b64decode(b64_json, validate=True)
            except (ValueError, TypeError):
                continue
        image_base64 = item.get("base64")
        if isinstance(image_base64, str) and image_base64.strip():
            try:
                return base64.b64decode(image_base64, validate=True)
            except (ValueError, TypeError):
                continue
        url = item.get("url")
        if isinstance(url, str) and url.startswith("https://"):
            try:
                with urllib.request.urlopen(url, timeout=60) as response:
                    return response.read()
            except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError):
                continue
    return b""


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
