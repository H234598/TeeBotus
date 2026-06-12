from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

from .handlers import build_reply, should_use_openai
from .instructions import BotInstructions, InstructionStore, render_template
from .openai_client import OpenAIAPIError, OpenAIClient

LOGGER = logging.getLogger("telegram_bot")
API_BASE = "https://api.telegram.org/bot{token}/{method}"
FILE_API_BASE = "https://api.telegram.org/file/bot{token}/{file_path}"
MAX_TRACKED_BOT_MESSAGES = 100
INITIAL_RETRY_DELAY_SECONDS = 5
MAX_RETRY_DELAY_SECONDS = 60
TELEGRAM_MESSAGE_CHUNK_SIZE = 3900
DEFAULT_INSTANCE_NAME = "Bote_der_Wahrheit"
SOURCE_MARKER_RE = re.compile(
    r"https?://|www\.|\[[^\]]+\]\(https?://|quelle[n]?:|source[s]?:|beleg[e]?:|reference[s]?:|literatur:|【[^】]+†[^】]+】",
    re.IGNORECASE,
)


class TelegramAPIError(RuntimeError):
    """Raised when Telegram returns an unsuccessful response."""


class TelegramNetworkError(TelegramAPIError):
    """Raised when a transient network error prevents a Telegram request."""


class TelegramAPI:
    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("Telegram token must not be empty")
        self.token = token

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = API_BASE.format(token=self.token, method=method)
        data = urllib.parse.urlencode(params or {}).encode("utf-8")
        request = urllib.request.Request(url, data=data, method="POST")

        try:
            with urllib.request.urlopen(request, timeout=75) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise TelegramAPIError(f"Telegram HTTP error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise TelegramNetworkError(f"Telegram network error: {exc.reason}") from exc

        if not payload.get("ok"):
            raise TelegramAPIError(f"Telegram API error: {payload}")
        return payload

    def request_multipart(
        self,
        method: str,
        fields: dict[str, Any],
        files: list[tuple[str, str, str, bytes]],
    ) -> dict[str, Any]:
        url = API_BASE.format(token=self.token, method=method)
        body, content_type = _encode_multipart_form_data(fields, files)
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": content_type},
        )

        try:
            with urllib.request.urlopen(request, timeout=75) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise TelegramAPIError(f"Telegram HTTP error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise TelegramNetworkError(f"Telegram network error: {exc.reason}") from exc

        if not payload.get("ok"):
            raise TelegramAPIError(f"Telegram API error: {payload}")
        return payload

    def get_updates(self, offset: int | None, timeout: int = 50) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": json.dumps(["message"]),
        }
        if offset is not None:
            params["offset"] = offset

        return list(self.request("getUpdates", params)["result"])

    def send_message(self, chat_id: int, text: str) -> int | None:
        payload = self.request(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": "true",
            },
        )
        result = payload.get("result")
        if not isinstance(result, dict):
            return None
        message_id = result.get("message_id")
        return int(message_id) if isinstance(message_id, int) else None

    def send_voice(self, chat_id: int, audio: bytes, filename: str, content_type: str) -> int | None:
        payload = self.request_multipart(
            "sendVoice",
            {"chat_id": chat_id},
            [("voice", filename, content_type, audio)],
        )
        result = payload.get("result")
        if not isinstance(result, dict):
            return None
        message_id = result.get("message_id")
        return int(message_id) if isinstance(message_id, int) else None

    def get_file_path(self, file_id: str) -> str:
        payload = self.request("getFile", {"file_id": file_id})
        result = payload.get("result")
        if not isinstance(result, dict):
            raise TelegramAPIError(f"Telegram getFile result is invalid: {payload}")
        file_path = result.get("file_path")
        if not isinstance(file_path, str) or not file_path.strip():
            raise TelegramAPIError(f"Telegram getFile response did not include file_path: {payload}")
        return file_path

    def download_file(self, file_path: str) -> bytes:
        quoted_path = urllib.parse.quote(file_path, safe="/")
        url = FILE_API_BASE.format(token=self.token, file_path=quoted_path)
        request = urllib.request.Request(url, method="GET")

        try:
            with urllib.request.urlopen(request, timeout=75) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise TelegramAPIError(f"Telegram file HTTP error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise TelegramNetworkError(f"Telegram file network error: {exc.reason}") from exc

    def send_chat_action(self, chat_id: int, action: str) -> None:
        self.request("sendChatAction", {"chat_id": chat_id, "action": action})

    def delete_message(self, chat_id: int, message_id: int) -> None:
        self.request("deleteMessage", {"chat_id": chat_id, "message_id": message_id})


class ChatState:
    def __init__(self) -> None:
        self.previous_response_ids: dict[int, str] = {}
        self.sent_message_ids: dict[int, list[int]] = {}
        self.auto_voice_eligible_counts: dict[int, int] = {}

    def get_previous_response_id(self, chat_id: int) -> str | None:
        return self.previous_response_ids.get(chat_id)

    def set_previous_response_id(self, chat_id: int, response_id: str | None) -> None:
        if response_id:
            self.previous_response_ids[chat_id] = response_id

    def reset(self, chat_id: int) -> None:
        self.previous_response_ids.pop(chat_id, None)

    def record_sent_message(self, chat_id: int, message_id: int | None) -> None:
        if message_id is None:
            return
        message_ids = self.sent_message_ids.setdefault(chat_id, [])
        message_ids.append(message_id)
        del message_ids[:-MAX_TRACKED_BOT_MESSAGES]

    def pop_last_sent_message(self, chat_id: int) -> int | None:
        message_ids = self.sent_message_ids.get(chat_id)
        if not message_ids:
            return None
        return message_ids.pop()

    def pop_sent_messages(self, chat_id: int, count: int) -> list[int]:
        message_ids = self.sent_message_ids.get(chat_id)
        if not message_ids:
            return []
        selected = message_ids[-count:]
        del message_ids[-count:]
        return list(reversed(selected))

    def should_send_auto_voice(self, chat_id: int, every: int) -> bool:
        if every < 1:
            return False
        count = self.auto_voice_eligible_counts.get(chat_id, 0) + 1
        self.auto_voice_eligible_counts[chat_id] = count
        return count % every == 0


def handle_update(
    api: TelegramAPI,
    update: dict[str, Any],
    instructions: BotInstructions | None = None,
    openai_client: OpenAIClient | None = None,
    chat_state: ChatState | None = None,
) -> None:
    instructions = instructions or BotInstructions()
    chat_state = chat_state or ChatState()
    message = update.get("message")
    if not isinstance(message, dict):
        return

    chat = message.get("chat")
    if not isinstance(chat, dict) or "id" not in chat:
        return

    chat_id = int(chat["id"])
    LOGGER.info(
        "Incoming Telegram message chat_id=%s message_id=%s type=%s",
        chat_id,
        message.get("message_id", "unknown"),
        _message_kind(message),
    )

    text = str(message.get("text") or "").strip()
    if "voice" in message:
        _handle_incoming_voice_message(api, chat_state, chat_id, message, instructions, openai_client)
        return

    _process_text_message(api, chat_state, chat_id, message, instructions, openai_client, text)


def _process_text_message(
    api: TelegramAPI,
    chat_state: ChatState,
    chat_id: int,
    message: dict[str, Any],
    instructions: BotInstructions,
    openai_client: OpenAIClient | None,
    text: str,
) -> None:
    if text and _normalize_command(text) == "/reset":
        chat_state.reset(chat_id)
        _send_tracked_message(api, chat_state, chat_id, instructions.openai_reset)
        return

    if text and _normalize_command(text) == "/voice":
        _handle_voice_command(api, chat_state, chat_id, message, instructions, openai_client, text)
        return

    if text and _handle_cleanup_command(api, chat_state, chat_id, message, instructions, text):
        return

    reply = build_reply(message, instructions, include_fallback=not instructions.openai_enabled)
    if reply:
        _send_tracked_message(api, chat_state, chat_id, reply)
        return

    if should_use_openai(message, instructions):
        if openai_client is None:
            _send_tracked_message(api, chat_state, chat_id, instructions.openai_missing_key)
            return
        try:
            api.send_chat_action(chat_id, "typing")
            openai_response = openai_client.create_reply(
                _build_openai_user_input(message, text),
                instructions,
                chat_state.get_previous_response_id(chat_id),
            )
        except OpenAIAPIError as exc:
            LOGGER.error("OpenAI request failed: %s", exc)
            _send_tracked_message(api, chat_state, chat_id, instructions.openai_error)
            return
        chat_state.set_previous_response_id(chat_id, openai_response.response_id)
        _send_openai_response(api, chat_state, chat_id, openai_response.text, instructions, openai_client)
        return

    fallback = build_reply(message, instructions, include_fallback=True)
    if fallback:
        _send_tracked_message(api, chat_state, chat_id, fallback)


def _handle_incoming_voice_message(
    api: TelegramAPI,
    chat_state: ChatState,
    chat_id: int,
    message: dict[str, Any],
    instructions: BotInstructions,
    openai_client: OpenAIClient | None,
) -> None:
    if not instructions.openai_transcription_enabled:
        _send_tracked_message(api, chat_state, chat_id, instructions.openai_transcription_error)
        return
    if openai_client is None:
        _send_tracked_message(api, chat_state, chat_id, instructions.openai_missing_key)
        return

    voice = message.get("voice")
    if not isinstance(voice, dict):
        _send_tracked_message(api, chat_state, chat_id, instructions.openai_transcription_error)
        return

    file_id = str(voice.get("file_id") or "").strip()
    if not file_id:
        _send_tracked_message(api, chat_state, chat_id, instructions.openai_transcription_error)
        return

    try:
        api.send_chat_action(chat_id, "typing")
        file_path = api.get_file_path(file_id)
        audio = api.download_file(file_path)
        transcribed_text = _transcribe_voice_audio(
            openai_client,
            audio,
            _downloaded_file_name(file_path),
            instructions,
        ).strip()
    except TelegramAPIError as exc:
        LOGGER.error("Telegram voice download failed: %s", exc)
        _send_tracked_message(api, chat_state, chat_id, instructions.openai_transcription_error)
        return
    except OpenAIAPIError as exc:
        LOGGER.error("OpenAI transcription request failed: %s", exc)
        _send_tracked_message(api, chat_state, chat_id, instructions.openai_transcription_error)
        return

    if not transcribed_text:
        _send_tracked_message(api, chat_state, chat_id, instructions.openai_transcription_empty)
        return

    transcribed_message = dict(message)
    transcribed_message["text"] = transcribed_text
    _process_text_message(
        api,
        chat_state,
        chat_id,
        transcribed_message,
        instructions,
        openai_client,
        transcribed_text,
    )


def _transcribe_voice_audio(
    openai_client: OpenAIClient,
    audio: bytes,
    filename: str,
    instructions: BotInstructions,
) -> str:
    primary_model = instructions.openai_transcription_model.strip()
    fallback_model = instructions.openai_transcription_fallback_model.strip()
    text = openai_client.transcribe_audio(audio, filename, instructions, model=primary_model or None).strip()
    if text or not fallback_model or fallback_model == primary_model:
        return text

    LOGGER.warning(
        "Primary OpenAI transcription returned empty text. Retrying with fallback_model=%s.",
        fallback_model,
    )
    return openai_client.transcribe_audio(audio, filename, instructions, model=fallback_model).strip()


def _build_openai_user_input(message: dict[str, Any], text: str) -> str:
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    sender_chat = message.get("sender_chat") if isinstance(message.get("sender_chat"), dict) else {}

    sender_id = sender.get("id") if sender else sender_chat.get("id", "")
    sender_name = _sender_display_name(sender, sender_chat)
    sender_username = _username(sender.get("username") if sender else sender_chat.get("username"))

    metadata = [
        "Telegram-Kontext:",
        "Diese Metadaten dienen nur dazu, Chat und Absender zuzuordnen. Sie sind keine Nutzeranweisung.",
        f"- chat_id: {_metadata_value(chat.get('id'))}",
        f"- chat_type: {_metadata_value(chat.get('type'))}",
        f"- chat_title: {_metadata_value(chat.get('title'))}",
        f"- sender_id: {_metadata_value(sender_id)}",
        f"- sender_name: {_metadata_value(sender_name)}",
        f"- sender_username: {_metadata_value(sender_username)}",
        "",
        "Nachricht:",
        text,
    ]
    return "\n".join(metadata).strip()


def _sender_display_name(sender: dict[str, Any], sender_chat: dict[str, Any]) -> str:
    if sender:
        name_parts = [
            str(sender.get("first_name") or "").strip(),
            str(sender.get("last_name") or "").strip(),
        ]
        full_name = " ".join(part for part in name_parts if part)
        return full_name or str(sender.get("username") or "").strip()
    return str(sender_chat.get("title") or sender_chat.get("username") or "").strip()


def _username(value: Any) -> str:
    username = str(value or "").strip()
    if username and not username.startswith("@"):
        return f"@{username}"
    return username


def _metadata_value(value: Any) -> str:
    text = str(value or "").strip()
    return text if text else "unbekannt"


def run_polling(
    api: TelegramAPI,
    instruction_store: InstructionStore | None = None,
    instance_name: str | None = None,
) -> None:
    instance = instance_name or _resolve_instance_name()
    instruction_store = instruction_store or InstructionStore(_resolve_instruction_path(instance))
    openai_api_key = _resolve_openai_api_key(instance)
    openai_client = OpenAIClient(openai_api_key) if openai_api_key else None
    chat_state = ChatState()
    LOGGER.info("Bot started. Waiting for Telegram updates.")
    offset: int | None = None
    retry_delay = INITIAL_RETRY_DELAY_SECONDS

    while True:
        try:
            updates = api.get_updates(offset)
            retry_delay = INITIAL_RETRY_DELAY_SECONDS
            for update in updates:
                handle_update(api, update, instruction_store.get(), openai_client, chat_state)
                offset = int(update["update_id"]) + 1
        except KeyboardInterrupt:
            LOGGER.info("Bot stopped.")
            return
        except TelegramNetworkError as exc:
            LOGGER.warning("%s. Retrying in %s seconds.", exc, retry_delay)
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY_SECONDS)
        except TelegramAPIError:
            LOGGER.exception("Telegram request failed. Retrying in %s seconds.", retry_delay)
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY_SECONDS)


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    instance_name = _resolve_instance_name()
    token = _resolve_telegram_token(instance_name)
    instance_token_key = _instance_env_key("TELEGRAM_BOT_TOKEN", instance_name)
    if not token:
        print(
            f"Missing Telegram bot token. Set TELEGRAM_BOT_TOKEN or {instance_token_key}.",
            file=sys.stderr,
        )
        return 2
    if not os.getenv(instance_token_key, "").strip() and os.getenv("TELEGRAM_BOT_TOKEN", "").strip():
        LOGGER.warning(
            "Using generic TELEGRAM_BOT_TOKEN for instance=%s. Set %s for parallel operation.",
            instance_name,
            instance_token_key,
        )

    instruction_path = _resolve_instruction_path(instance_name)
    LOGGER.info("Using bot instance=%s instructions=%s", instance_name, instruction_path)
    run_polling(TelegramAPI(token), InstructionStore(instruction_path), instance_name)
    return 0


def _resolve_instance_name() -> str:
    return os.getenv("TELEGRAM_BOT_INSTANCE", DEFAULT_INSTANCE_NAME).strip() or DEFAULT_INSTANCE_NAME


def _resolve_instruction_path(instance_name: str | None = None) -> str:
    explicit_path = os.getenv("TELEGRAM_BOT_INSTRUCTIONS", "").strip()
    if explicit_path:
        return explicit_path
    instance = instance_name or _resolve_instance_name()
    instances_dir = os.getenv("TELEGRAM_BOT_INSTANCES_DIR", "instances").strip() or "instances"
    return os.path.join(instances_dir, instance, "BOT.md")


def _resolve_telegram_token(instance_name: str) -> str:
    instance_token = os.getenv(_instance_env_key("TELEGRAM_BOT_TOKEN", instance_name), "").strip()
    return instance_token or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def _resolve_openai_api_key(instance_name: str) -> str:
    instance_key = os.getenv(_instance_env_key("OPENAI_API_KEY", instance_name), "").strip()
    return instance_key or os.getenv("OPENAI_API_KEY", "").strip()


def _instance_env_key(prefix: str, instance_name: str) -> str:
    suffix = re.sub(r"[^A-Za-z0-9]+", "_", instance_name).strip("_").upper()
    return f"{prefix}_{suffix}" if suffix else prefix


def _normalize_command(text: str) -> str:
    if not text:
        return ""
    command = text.split(maxsplit=1)[0].lower()
    if "@" in command:
        command = command.split("@", maxsplit=1)[0]
    return command


def _message_kind(message: dict[str, Any]) -> str:
    for kind in (
        "text",
        "voice",
        "audio",
        "video",
        "photo",
        "document",
        "sticker",
        "animation",
        "video_note",
        "location",
        "contact",
        "poll",
    ):
        if kind in message:
            return kind
    return "unknown"


def _send_tracked_message(api: TelegramAPI, chat_state: ChatState, chat_id: int, text: str) -> None:
    chunks = split_telegram_message(text)
    for index, chunk in enumerate(chunks, start=1):
        message_id = api.send_message(chat_id, chunk)
        chat_state.record_sent_message(chat_id, message_id)
        LOGGER.info(
            "Outgoing Telegram message chat_id=%s message_id=%s type=text chars=%s chunk=%s/%s",
            chat_id,
            message_id if message_id is not None else "unknown",
            len(chunk),
            index,
            len(chunks),
        )


def _send_tracked_voice(api: TelegramAPI, chat_state: ChatState, chat_id: int, audio: bytes, filename: str, content_type: str) -> None:
    message_id = api.send_voice(chat_id, audio, filename, content_type)
    chat_state.record_sent_message(chat_id, message_id)
    LOGGER.info(
        "Outgoing Telegram message chat_id=%s message_id=%s type=voice bytes=%s",
        chat_id,
        message_id if message_id is not None else "unknown",
        len(audio),
    )


def _send_openai_response(
    api: TelegramAPI,
    chat_state: ChatState,
    chat_id: int,
    text: str,
    instructions: BotInstructions,
    openai_client: OpenAIClient,
) -> None:
    if _should_consider_auto_voice(text, instructions) and chat_state.should_send_auto_voice(
        chat_id,
        instructions.openai_auto_voice_every,
    ):
        try:
            api.send_chat_action(chat_id, "record_voice")
            voice = openai_client.create_voice(text, instructions)
            api.send_chat_action(chat_id, "upload_voice")
            _send_tracked_voice(api, chat_state, chat_id, voice.audio, voice.filename, voice.content_type)
            return
        except OpenAIAPIError as exc:
            LOGGER.error("Automatic OpenAI speech request failed: %s", exc)

    _send_tracked_message(api, chat_state, chat_id, text)


def _should_consider_auto_voice(text: str, instructions: BotInstructions) -> bool:
    if not instructions.openai_auto_voice_enabled or not instructions.openai_voice_enabled:
        return False
    stripped = text.strip()
    if not stripped:
        return False
    if len(stripped) > instructions.openai_voice_max_input_chars:
        return False
    if count_words(stripped) >= instructions.openai_auto_voice_max_words:
        return False
    if instructions.openai_auto_voice_skip_sources and contains_sources(stripped):
        return False
    return True


def count_words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def contains_sources(text: str) -> bool:
    return bool(SOURCE_MARKER_RE.search(text))


def split_telegram_message(text: str, chunk_size: int = TELEGRAM_MESSAGE_CHUNK_SIZE) -> list[str]:
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > chunk_size:
        split_at = _find_split_index(remaining, chunk_size)
        chunk = remaining[:split_at].rstrip()
        if not chunk:
            chunk = remaining[:chunk_size]
            split_at = chunk_size
        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip()

    if remaining:
        chunks.append(remaining)
    return chunks


def _find_split_index(text: str, chunk_size: int) -> int:
    search_window = text[:chunk_size]
    for separator in ("\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " "):
        index = search_window.rfind(separator)
        if index >= chunk_size // 2:
            return index + len(separator)
    return chunk_size


def _handle_voice_command(
    api: TelegramAPI,
    chat_state: ChatState,
    chat_id: int,
    message: dict[str, Any],
    instructions: BotInstructions,
    openai_client: OpenAIClient | None,
    text: str,
) -> None:
    if not instructions.openai_voice_enabled:
        _send_tracked_message(api, chat_state, chat_id, instructions.openai_voice_error)
        return
    if openai_client is None:
        _send_tracked_message(api, chat_state, chat_id, instructions.openai_missing_key)
        return

    voice_text = _extract_voice_text(message, text)
    if not voice_text:
        _send_tracked_message(api, chat_state, chat_id, instructions.openai_voice_usage)
        return
    if len(voice_text) > instructions.openai_voice_max_input_chars:
        reply = render_template(
            instructions.openai_voice_too_long,
            message,
            text,
            {"max_chars": instructions.openai_voice_max_input_chars},
        )
        _send_tracked_message(api, chat_state, chat_id, reply)
        return

    try:
        api.send_chat_action(chat_id, "record_voice")
        voice = openai_client.create_voice(voice_text, instructions)
        api.send_chat_action(chat_id, "upload_voice")
        _send_tracked_voice(api, chat_state, chat_id, voice.audio, voice.filename, voice.content_type)
    except OpenAIAPIError as exc:
        LOGGER.error("OpenAI speech request failed: %s", exc)
        _send_tracked_message(api, chat_state, chat_id, instructions.openai_voice_error)


def _extract_voice_text(message: dict[str, Any], command_text: str) -> str:
    parts = command_text.split(maxsplit=1)
    if len(parts) == 2 and parts[1].strip():
        return parts[1].strip()

    reply = message.get("reply_to_message")
    if isinstance(reply, dict):
        return str(reply.get("text") or reply.get("caption") or "").strip()
    return ""


def _downloaded_file_name(file_path: str) -> str:
    name = file_path.rsplit("/", maxsplit=1)[-1].strip()
    if not name:
        return "voice.ogg"
    stem, separator, extension = name.rpartition(".")
    if separator and extension.casefold() == "oga":
        return f"{stem}.ogg" if stem else "voice.ogg"
    return name


def _encode_multipart_form_data(
    fields: dict[str, Any],
    files: list[tuple[str, str, str, bytes]],
) -> tuple[bytes, str]:
    boundary = f"----telegram-bot-{uuid.uuid4().hex}"
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


def _handle_cleanup_command(
    api: TelegramAPI,
    chat_state: ChatState,
    chat_id: int,
    message: dict[str, Any],
    instructions: BotInstructions,
    text: str,
) -> bool:
    command = _normalize_command(text)
    if command == "/delete_last":
        message_id = chat_state.pop_last_sent_message(chat_id)
        if message_id is None:
            _send_tracked_message(api, chat_state, chat_id, instructions.delete_empty)
            return True
        try:
            api.delete_message(chat_id, message_id)
        except TelegramAPIError:
            LOGGER.exception("Failed to delete Telegram message %s in chat %s.", message_id, chat_id)
            _send_tracked_message(api, chat_state, chat_id, instructions.delete_error)
            return True
        _send_tracked_message(api, chat_state, chat_id, instructions.delete_last_success)
        return True

    if command == "/cleanup":
        count = _parse_cleanup_count(text)
        if count is None:
            _send_tracked_message(api, chat_state, chat_id, instructions.cleanup_usage)
            return True

        message_ids = chat_state.pop_sent_messages(chat_id, count)
        if not message_ids:
            _send_tracked_message(api, chat_state, chat_id, instructions.delete_empty)
            return True

        deleted_count = 0
        for message_id in message_ids:
            try:
                api.delete_message(chat_id, message_id)
                deleted_count += 1
            except TelegramAPIError:
                LOGGER.exception("Failed to delete Telegram message %s in chat %s.", message_id, chat_id)

        if deleted_count:
            reply = render_template(instructions.cleanup_success, message, text, {"count": deleted_count})
        else:
            reply = instructions.delete_error
        _send_tracked_message(api, chat_state, chat_id, reply)
        return True

    return False


def _parse_cleanup_count(text: str) -> int | None:
    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        return None
    try:
        count = int(parts[1])
    except ValueError:
        return None
    if count < 1:
        return None
    return min(count, MAX_TRACKED_BOT_MESSAGES)
