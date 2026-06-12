from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .handlers import build_reply, should_use_openai
from .instructions import BotInstructions, InstructionStore, render_template
from .openai_client import OpenAIAPIError, OpenAIClient

LOGGER = logging.getLogger("telegram_bot")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_BASE = "https://api.telegram.org/bot{token}/{method}"
FILE_API_BASE = "https://api.telegram.org/file/bot{token}/{file_path}"
MAX_TRACKED_BOT_MESSAGES = 100
INITIAL_RETRY_DELAY_SECONDS = 5
MAX_RETRY_DELAY_SECONDS = 60
TELEGRAM_MESSAGE_CHUNK_SIZE = 3900
DEFAULT_INSTANCE_NAME = "Bote_der_Wahrheit"
BOT_INSTRUCTION_FILENAME = "Bot_Verhalten.md"
MULTI_BOT_POLL_TIMEOUT_SECONDS = 5
USER_MEMORY_INDEX_FILENAME = "User_Memory_Index.json"
USER_MEMORY_ENTRIES_FILENAME = "User_Memory_Entries.jsonl"
USER_HABITS_FILENAME = "User_Habbits_and_behave.md"
USER_HABITS_MAX_PROMPT_CHARS = 4000
WORKING_MEMORY_INDEX_FILENAME = "Working_Memorys.json"
WORKING_MEMORY_ENTRIES_FILENAME = "Working_Memorys.entries.jsonl"
WORKING_MEMORY_MAX_PROMPT_CHARS = 6000
WORKING_MEMORY_PRIVACY_NOTE = (
    "Instanzweites Arbeitsgedaechtnis. Darf keine User-IDs, Namen, Usernames, Chat-IDs, "
    "Chat-Titel, Rohzitate aus Usernachrichten oder eindeutig userbezogene Fakten enthalten."
)
DOTENV_RUNTIME_KEYS = {
    "LOG_LEVEL",
    "TELEGRAM_BOT_INSTANCE",
    "TELEGRAM_BOT_INSTANCES",
    "TELEGRAM_BOT_INSTANCES_DIR",
    "TELEGRAM_BOT_INSTRUCTIONS",
}
SOURCE_MARKER_RE = re.compile(
    r"https?://|www\.|\[[^\]]+\]\(https?://|quelle[n]?:|source[s]?:|beleg[e]?:|reference[s]?:|literatur:|【[^】]+†[^】]+】",
    re.IGNORECASE,
)
MEMORY_SCHEMA_VERSION = 1
MEMORY_RECENT_LIMIT = 200
MEMORY_KEYWORD_LIMIT = 24
MEMORY_KEYWORD_ENTRY_LIMIT = 250
MEMORY_STOPWORDS = {
    "aber",
    "alle",
    "alles",
    "als",
    "also",
    "auch",
    "auf",
    "aus",
    "bei",
    "bin",
    "bis",
    "bitte",
    "das",
    "dass",
    "dem",
    "den",
    "der",
    "des",
    "die",
    "dies",
    "dir",
    "doch",
    "ein",
    "eine",
    "einem",
    "einen",
    "einer",
    "eines",
    "er",
    "es",
    "hat",
    "hast",
    "ich",
    "ihm",
    "ihn",
    "ihr",
    "im",
    "in",
    "ist",
    "ja",
    "kann",
    "mal",
    "man",
    "mein",
    "mit",
    "mir",
    "mich",
    "nicht",
    "noch",
    "oder",
    "sich",
    "sie",
    "sind",
    "so",
    "und",
    "vom",
    "von",
    "war",
    "was",
    "wenn",
    "wer",
    "wie",
    "wir",
    "wird",
    "wo",
    "zu",
    "zum",
    "zur",
}


class TelegramAPIError(RuntimeError):
    """Raised when Telegram returns an unsuccessful response."""


class TelegramNetworkError(TelegramAPIError):
    """Raised when a transient network error prevents a Telegram request."""


@dataclass(frozen=True)
class BotIdentity:
    id: int | None = None
    first_name: str = ""
    username: str = ""

    @property
    def display_name(self) -> str:
        return _readable_bot_name(self.first_name, self.username)

    @property
    def mention(self) -> str:
        username = self.username.strip().lstrip("@")
        return f"@{username}" if username else ""

    def has_identity(self) -> bool:
        return bool(self.id is not None or self.first_name.strip() or self.username.strip())


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

    def get_me(self) -> BotIdentity:
        payload = self.request("getMe", {})
        result = payload.get("result")
        if not isinstance(result, dict):
            raise TelegramAPIError(f"Telegram getMe result is invalid: {payload}")
        bot_id = result.get("id")
        return BotIdentity(
            id=int(bot_id) if isinstance(bot_id, int) else None,
            first_name=str(result.get("first_name") or "").strip(),
            username=str(result.get("username") or "").strip().lstrip("@"),
        )

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
        self.seen_sender_ids: set[str] = set()

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

    def has_seen_sender(self, sender_id: str) -> bool:
        return sender_id in self.seen_sender_ids

    def mark_sender_seen(self, sender_id: str) -> None:
        if sender_id:
            self.seen_sender_ids.add(sender_id)


@dataclass(frozen=True)
class UserMemoryRecord:
    sender_id: str
    path: Path
    prompt_text: str
    selected_ids: tuple[str, ...]


@dataclass(frozen=True)
class WorkingMemoryRecord:
    path: Path
    prompt_text: str
    selected_ids: tuple[str, ...]


@dataclass(frozen=True)
class BotTokenConfig:
    label: str
    token: str
    openai_api_key: str


@dataclass(frozen=True)
class InstanceRunConfig:
    instance_name: str
    instruction_path: str
    token_configs: tuple[BotTokenConfig, ...]


class WorkingMemoryStore:
    def __init__(self, instance_name: str, instances_dir: str | Path | None = None) -> None:
        self.instance_name = instance_name
        self.instances_dir = Path(instances_dir) if instances_dir is not None else _resolve_instances_dir()
        self._lock = threading.Lock()

    def ensure(self) -> Path:
        path = self._path()
        with self._lock:
            data = self._load_or_initialize(path)
            _write_json_file(path, data)
            _working_memory_entries_path(path).touch(exist_ok=True)
        return path

    def prepare(self, query_text: str, max_chars: int = WORKING_MEMORY_MAX_PROMPT_CHARS) -> WorkingMemoryRecord:
        path = self._path()
        with self._lock:
            data = self._load_or_initialize(path)
            prompt_text, selected_ids = _select_working_memory_prompt(path, data, query_text, max_chars)
        return WorkingMemoryRecord(path=path, prompt_text=prompt_text, selected_ids=tuple(selected_ids))

    def append_manual(self, text: str, kind: str = "manual") -> str:
        sanitized = _sanitize_working_memory_text(text)
        if not sanitized:
            return ""

        path = self._path()
        timestamp = _utc_timestamp()
        entry = {
            "id": _new_working_memory_id(),
            "created_at": timestamp,
            "updated_at": timestamp,
            "kind": str(kind or "manual").strip() or "manual",
            "text": sanitized,
            "keywords": _memory_keywords(sanitized),
        }
        with self._lock:
            data = self._load_or_initialize(path)
            _store_working_memory_entry(path, data, entry)
            data["updated_at"] = timestamp
            _write_json_file(path, data)
        return str(entry["id"])

    def _path(self) -> Path:
        return self.instances_dir / self.instance_name / "data" / WORKING_MEMORY_INDEX_FILENAME

    def _load_or_initialize(self, path: Path) -> dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        entries_path = _working_memory_entries_path(path)
        if not path.exists():
            data = _new_working_memory_data(self.instance_name)
            _write_json_file(path, data)
            entries_path.touch(exist_ok=True)
            return data

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            LOGGER.exception("Failed to read instance working memory at %s.", path)
            payload = _new_working_memory_data(self.instance_name)
        if not isinstance(payload, dict):
            payload = _new_working_memory_data(self.instance_name)
        _normalize_working_memory_data(payload, self.instance_name)
        entries_path.touch(exist_ok=True)
        return payload


class UserMemoryStore:
    def __init__(self, instance_name: str) -> None:
        self.instance_name = instance_name
        self._lock = threading.Lock()

    def prepare(
        self,
        message: dict[str, Any],
        instructions: BotInstructions,
        query_text: str,
    ) -> UserMemoryRecord | None:
        if not instructions.user_memory_enabled:
            return None

        sender_id = _sender_identifier(message)
        if not sender_id:
            return None

        path = self._path_for_sender(sender_id, instructions)
        with self._lock:
            data = self._load_or_initialize(path, sender_id)
            habits_text = _load_user_habits_text(path, USER_HABITS_MAX_PROMPT_CHARS)
            memory_text, selected_ids = _select_user_memory_prompt(
                path,
                data,
                query_text,
                instructions.user_memory_max_prompt_chars,
            )
            prompt_text = _combine_user_memory_prompt(habits_text, memory_text)
        return UserMemoryRecord(
            sender_id=sender_id,
            path=path,
            prompt_text=prompt_text,
            selected_ids=tuple(selected_ids),
        )

    def append_interaction(
        self,
        record: UserMemoryRecord,
        message: dict[str, Any],
        user_text: str,
        bot_text: str,
        instructions: BotInstructions,
    ) -> None:
        with self._lock:
            data = self._load_or_initialize(record.path, record.sender_id)
            _append_json_memory_interaction(
                record.path,
                data,
                message,
                user_text,
                bot_text,
                instructions.user_memory_max_entry_chars,
                record.selected_ids,
            )
            _write_json_file(record.path, data)

    def has_sender(self, sender_id: str, instructions: BotInstructions) -> bool:
        if not instructions.user_memory_enabled or not sender_id:
            return False
        path = self._path_for_sender(sender_id, instructions)
        return (
            path.exists()
            or _memory_entries_path(path).exists()
            or _memory_habits_path(path).exists()
            or any(legacy_path.exists() for legacy_path in _legacy_json_memory_paths(path, sender_id))
            or any(legacy_path.exists() for legacy_path in _legacy_entries_memory_paths(path, sender_id))
            or _legacy_markdown_memory_path(path, sender_id).is_file()
        )

    def _path_for_sender(self, sender_id: str, instructions: BotInstructions) -> Path:
        directory = instructions.user_memory_dir.strip() or "instances/{instance}/data/users"
        directory = directory.replace("{instance}", self.instance_name)
        return Path(directory) / _safe_memory_filename(sender_id) / USER_MEMORY_INDEX_FILENAME

    def _load_or_initialize(self, path: Path, sender_id: str) -> dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            legacy_data = _load_legacy_user_memory(path, sender_id)
            if legacy_data is not None:
                _write_json_file(path, legacy_data)
                _ensure_user_habits_file(path)
                return legacy_data
            legacy_markdown_path = _legacy_markdown_memory_path(path, sender_id)
            if legacy_markdown_path.is_file():
                data = _new_user_memory_data(sender_id)
                _store_memory_entry(path, data, _legacy_memory_entry(legacy_markdown_path.read_text(encoding="utf-8")))
                _write_json_file(path, data)
                _ensure_user_habits_file(path)
                return data
            data = _new_user_memory_data(sender_id)
            _write_json_file(path, data)
            _ensure_user_habits_file(path)
            return data

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            LOGGER.exception("Failed to read JSON user memory for sender_id=%s.", sender_id)
            payload = _new_user_memory_data(sender_id)
        if not isinstance(payload, dict) or str(payload.get("sender_id", "")) != sender_id:
            LOGGER.warning("Ignoring user memory with mismatched sender_id at %s.", path)
            payload = _new_user_memory_data(sender_id)
        elif isinstance(payload.get("memories"), list):
            payload = _migrate_inline_json_memory(path, payload, sender_id)
        _normalize_user_memory_data(payload, sender_id)
        _ensure_user_habits_file(path)
        return payload


def handle_update(
    api: TelegramAPI,
    update: dict[str, Any],
    instructions: BotInstructions | None = None,
    openai_client: OpenAIClient | None = None,
    chat_state: ChatState | None = None,
    user_memory_store: UserMemoryStore | None = None,
    bot_identity: BotIdentity | None = None,
    working_memory_store: WorkingMemoryStore | None = None,
) -> None:
    instructions = instructions or BotInstructions()
    chat_state = chat_state or ChatState()
    bot_identity = bot_identity or BotIdentity()
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
        _handle_incoming_voice_message(
            api,
            chat_state,
            chat_id,
            message,
            instructions,
            openai_client,
            user_memory_store,
            bot_identity,
            working_memory_store,
        )
        return

    first_contact = _is_first_contact(chat_state, user_memory_store, message, instructions)
    if not _should_process_for_bot(message, text, bot_identity, first_contact):
        LOGGER.info(
            "Ignoring Telegram message chat_id=%s message_id=%s reason=not_addressed_to_bot",
            chat_id,
            message.get("message_id", "unknown"),
        )
        return
    user_memory = _prepare_user_memory(user_memory_store, message, instructions, text)
    _process_text_message(
        api,
        chat_state,
        chat_id,
        message,
        instructions,
        openai_client,
        text,
        user_memory_store,
        user_memory,
        bot_identity,
        first_contact,
        working_memory_store,
    )


def _process_text_message(
    api: TelegramAPI,
    chat_state: ChatState,
    chat_id: int,
    message: dict[str, Any],
    instructions: BotInstructions,
    openai_client: OpenAIClient | None,
    text: str,
    user_memory_store: UserMemoryStore | None = None,
    user_memory: UserMemoryRecord | None = None,
    bot_identity: BotIdentity | None = None,
    first_contact: bool = False,
    working_memory_store: WorkingMemoryStore | None = None,
) -> None:
    chat_state.mark_sender_seen(_sender_identifier(message))
    bot_identity = bot_identity or BotIdentity()
    if text and _normalize_command(text) == "/reset":
        chat_state.reset(chat_id)
        reply = _with_first_contact_intro(instructions.openai_reset, first_contact, bot_identity)
        _send_tracked_message(api, chat_state, chat_id, reply)
        _record_user_memory(user_memory_store, user_memory, message, text, reply, instructions)
        return

    if text and _normalize_command(text) == "/voice":
        _handle_voice_command(api, chat_state, chat_id, message, instructions, openai_client, text)
        return

    if text and _handle_cleanup_command(api, chat_state, chat_id, message, instructions, text):
        return

    reply = build_reply(message, instructions, include_fallback=not instructions.openai_enabled)
    if reply:
        reply = _with_first_contact_intro(reply, first_contact, bot_identity)
        _send_tracked_message(api, chat_state, chat_id, reply)
        _record_user_memory(user_memory_store, user_memory, message, text, reply, instructions)
        return

    if should_use_openai(message, instructions):
        if openai_client is None:
            reply = _with_first_contact_intro(instructions.openai_missing_key, first_contact, bot_identity)
            _send_tracked_message(api, chat_state, chat_id, reply)
            _record_user_memory(user_memory_store, user_memory, message, text, reply, instructions)
            return
        try:
            api.send_chat_action(chat_id, "typing")
            working_memory = _prepare_working_memory(working_memory_store, text)
            openai_response = openai_client.create_reply(
                _build_openai_user_input(
                    message,
                    text,
                    user_memory.prompt_text if user_memory else "",
                    bot_identity,
                    working_memory.prompt_text if working_memory else "",
                ),
                instructions,
                chat_state.get_previous_response_id(chat_id),
            )
        except OpenAIAPIError as exc:
            LOGGER.error("OpenAI request failed: %s", exc)
            reply = _with_first_contact_intro(instructions.openai_error, first_contact, bot_identity)
            _send_tracked_message(api, chat_state, chat_id, reply)
            _record_user_memory(user_memory_store, user_memory, message, text, reply, instructions)
            return
        chat_state.set_previous_response_id(chat_id, openai_response.response_id)
        reply = _with_first_contact_intro(openai_response.text, first_contact, bot_identity)
        _send_openai_response(api, chat_state, chat_id, reply, instructions, openai_client)
        _record_user_memory(user_memory_store, user_memory, message, text, reply, instructions)
        return

    fallback = build_reply(message, instructions, include_fallback=True)
    if fallback:
        fallback = _with_first_contact_intro(fallback, first_contact, bot_identity)
        _send_tracked_message(api, chat_state, chat_id, fallback)
        _record_user_memory(user_memory_store, user_memory, message, text, fallback, instructions)


def _handle_incoming_voice_message(
    api: TelegramAPI,
    chat_state: ChatState,
    chat_id: int,
    message: dict[str, Any],
    instructions: BotInstructions,
    openai_client: OpenAIClient | None,
    user_memory_store: UserMemoryStore | None = None,
    bot_identity: BotIdentity | None = None,
    working_memory_store: WorkingMemoryStore | None = None,
) -> None:
    bot_identity = bot_identity or BotIdentity()
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
    first_contact = _is_first_contact(chat_state, user_memory_store, transcribed_message, instructions)
    if not _should_process_for_bot(transcribed_message, transcribed_text, bot_identity, first_contact):
        LOGGER.info(
            "Ignoring Telegram voice message chat_id=%s message_id=%s reason=not_addressed_to_bot",
            chat_id,
            message.get("message_id", "unknown"),
        )
        return
    user_memory = _prepare_user_memory(user_memory_store, transcribed_message, instructions, transcribed_text)
    _process_text_message(
        api,
        chat_state,
        chat_id,
        transcribed_message,
        instructions,
        openai_client,
        transcribed_text,
        user_memory_store,
        user_memory,
        bot_identity,
        first_contact,
        working_memory_store,
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


def _prepare_working_memory(
    working_memory_store: WorkingMemoryStore | None,
    query_text: str,
) -> WorkingMemoryRecord | None:
    if working_memory_store is None:
        return None
    try:
        return working_memory_store.prepare(query_text)
    except OSError:
        LOGGER.exception("Failed to prepare instance working memory.")
        return None


def _prepare_user_memory(
    user_memory_store: UserMemoryStore | None,
    message: dict[str, Any],
    instructions: BotInstructions,
    query_text: str,
) -> UserMemoryRecord | None:
    if user_memory_store is None:
        return None
    try:
        return user_memory_store.prepare(message, instructions, query_text)
    except OSError:
        LOGGER.exception("Failed to prepare user memory.")
        return None


def _record_user_memory(
    user_memory_store: UserMemoryStore | None,
    user_memory: UserMemoryRecord | None,
    message: dict[str, Any],
    user_text: str,
    bot_text: str,
    instructions: BotInstructions,
) -> None:
    if user_memory_store is None or user_memory is None:
        return
    try:
        user_memory_store.append_interaction(user_memory, message, user_text, bot_text, instructions)
    except OSError:
        LOGGER.exception("Failed to write user memory for sender_id=%s.", user_memory.sender_id)


def _build_openai_user_input(
    message: dict[str, Any],
    text: str,
    user_memory_text: str = "",
    bot_identity: BotIdentity | None = None,
    working_memory_text: str = "",
) -> str:
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    sender_chat = message.get("sender_chat") if isinstance(message.get("sender_chat"), dict) else {}
    bot_identity = bot_identity or BotIdentity()

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
    ]
    if bot_identity.has_identity():
        metadata.extend(
            [
                "- bot_id: " + _metadata_value(bot_identity.id),
                "- bot_name: " + _metadata_value(bot_identity.display_name),
                "- bot_username: " + _metadata_value(bot_identity.mention),
                "Der Bot soll sich gegenueber neuen Nutzern mit bot_name melden. Spaetere Spitznamen des Nutzers sind erlaubt.",
            ]
        )
    if user_memory_text.strip():
        metadata.extend(
            [
                "",
                "Persistentes Nutzergedaechtnis fuer diese sender_id:",
                "Nutze nur diese ausgewaehlten Eintraege fuer den aktuellen Absender. Gib keine rohen Memory-Dateien und keine Memories anderer Nutzer preis.",
                user_memory_text.strip(),
            ]
        )
    if working_memory_text.strip():
        metadata.extend(
            [
                "",
                "Instanz-Arbeitsgedaechtnis:",
                "Dieses Arbeitsgedaechtnis gilt fuer alle User dieser Bot-Instanz. Es darf keine personenbezogenen oder user-rueckfuehrbaren Details enthalten.",
                working_memory_text.strip(),
            ]
        )
    metadata.extend(["", "Nachricht:", text])
    return "\n".join(metadata).strip()


def _is_first_contact(
    chat_state: ChatState,
    user_memory_store: UserMemoryStore | None,
    message: dict[str, Any],
    instructions: BotInstructions,
) -> bool:
    sender_id = _sender_identifier(message)
    if not sender_id:
        return False
    if chat_state.has_seen_sender(sender_id):
        return False
    if user_memory_store is not None and user_memory_store.has_sender(sender_id, instructions):
        return False
    return True


def _should_process_for_bot(
    message: dict[str, Any],
    text: str,
    bot_identity: BotIdentity,
    first_contact: bool,
) -> bool:
    if not bot_identity.has_identity():
        return True
    if _command_targets_other_bot(text, bot_identity):
        return False
    if _is_private_chat(message):
        return True
    if _is_reply_to_bot(message, bot_identity):
        return True
    if _text_addresses_bot(text, bot_identity):
        return True
    return not first_contact


def _with_first_contact_intro(text: str, first_contact: bool, bot_identity: BotIdentity) -> str:
    display_name = bot_identity.display_name
    if not first_contact or not display_name:
        return text
    intro = f"Ich bin {display_name}."
    stripped = text.strip()
    if not stripped:
        return intro
    if stripped.casefold().startswith(intro.casefold()):
        return text
    return f"{intro}\n\n{text}"


def _is_private_chat(message: dict[str, Any]) -> bool:
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    return str(chat.get("type") or "").casefold() == "private"


def _is_reply_to_bot(message: dict[str, Any], bot_identity: BotIdentity) -> bool:
    if bot_identity.id is None:
        return False
    reply = message.get("reply_to_message")
    if not isinstance(reply, dict):
        return False
    sender = reply.get("from")
    if not isinstance(sender, dict):
        return False
    return sender.get("id") == bot_identity.id


def _command_targets_other_bot(text: str, bot_identity: BotIdentity) -> bool:
    command = text.strip().split(maxsplit=1)[0]
    if not command.startswith("/") or "@" not in command:
        return False
    target = command.rsplit("@", maxsplit=1)[-1].strip().casefold()
    username = bot_identity.username.strip().lstrip("@").casefold()
    return bool(target and username and target != username)


def _text_addresses_bot(text: str, bot_identity: BotIdentity) -> bool:
    if not text.strip():
        return False
    username = bot_identity.username.strip().lstrip("@")
    if username and f"@{username}".casefold() in text.casefold():
        return True
    normalized_text = f" {_normalize_bot_address_text(text)} "
    for name in _bot_known_names(bot_identity):
        normalized_name = _normalize_bot_address_text(name)
        if len(normalized_name) >= 3 and f" {normalized_name} " in normalized_text:
            return True
    return False


def _bot_known_names(bot_identity: BotIdentity) -> set[str]:
    names = {
        bot_identity.first_name.strip(),
        bot_identity.username.strip().lstrip("@"),
        bot_identity.display_name.strip(),
    }
    return {name for name in names if name}


def _readable_bot_name(first_name: str, username: str) -> str:
    base = first_name.strip() or username.strip().lstrip("@")
    base = re.sub(r"[_-]+", " ", base).strip()
    base = re.sub(r"\s+", " ", base)
    base = re.sub(r"\s+bot$", "", base, flags=re.IGNORECASE).strip()
    return base


def _normalize_bot_address_text(text: str) -> str:
    normalized = str(text or "").casefold()
    normalized = re.sub(r"[_-]+", " ", normalized)
    normalized = re.sub(r"[^0-9a-zäöüß]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _sender_identifier(message: dict[str, Any]) -> str:
    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    sender_chat = message.get("sender_chat") if isinstance(message.get("sender_chat"), dict) else {}
    value = sender.get("id") if sender else sender_chat.get("id")
    return str(value).strip() if value is not None else ""


def _safe_memory_filename(sender_id: str) -> str:
    value = sender_id.strip()
    if re.fullmatch(r"-?\d+", value):
        return value
    sanitized = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return sanitized or "unknown"


def _new_user_memory_data(sender_id: str) -> dict[str, Any]:
    timestamp = _utc_timestamp()
    return {
        "schema_version": MEMORY_SCHEMA_VERSION,
        "sender_id": sender_id,
        "created_at": timestamp,
        "updated_at": timestamp,
        "entry_store": USER_MEMORY_ENTRIES_FILENAME,
        "profile": {
            "names": [],
            "usernames": [],
            "chat_ids": [],
            "chat_titles": [],
        },
        "index": {
            "keywords": {},
            "recent_ids": [],
            "entries": {},
        },
    }


def _normalize_user_memory_data(data: dict[str, Any], sender_id: str) -> None:
    data["schema_version"] = MEMORY_SCHEMA_VERSION
    data["sender_id"] = sender_id
    data.setdefault("created_at", _utc_timestamp())
    data.setdefault("updated_at", data["created_at"])
    profile = data.setdefault("profile", {})
    if not isinstance(profile, dict):
        profile = {}
        data["profile"] = profile
    for key in ("names", "usernames", "chat_ids", "chat_titles"):
        if not isinstance(profile.get(key), list):
            profile[key] = []
    data["entry_store"] = USER_MEMORY_ENTRIES_FILENAME
    index = data.setdefault("index", {})
    if not isinstance(index, dict):
        index = {}
        data["index"] = index
    if not isinstance(index.get("keywords"), dict):
        index["keywords"] = {}
    if not isinstance(index.get("recent_ids"), list):
        index["recent_ids"] = []
    if not isinstance(index.get("entries"), dict):
        index["entries"] = {}
    data.pop("memories", None)


def _new_working_memory_data(instance_name: str) -> dict[str, Any]:
    timestamp = _utc_timestamp()
    return {
        "schema_version": MEMORY_SCHEMA_VERSION,
        "scope": "instance",
        "instance_name": instance_name,
        "privacy": WORKING_MEMORY_PRIVACY_NOTE,
        "created_at": timestamp,
        "updated_at": timestamp,
        "entry_store": WORKING_MEMORY_ENTRIES_FILENAME,
        "index": {
            "keywords": {},
            "recent_ids": [],
            "entries": {},
        },
    }


def _normalize_working_memory_data(data: dict[str, Any], instance_name: str) -> None:
    data["schema_version"] = MEMORY_SCHEMA_VERSION
    data["scope"] = "instance"
    data["instance_name"] = str(data.get("instance_name") or instance_name)
    data["privacy"] = WORKING_MEMORY_PRIVACY_NOTE
    data.setdefault("created_at", _utc_timestamp())
    data.setdefault("updated_at", data["created_at"])
    data["entry_store"] = WORKING_MEMORY_ENTRIES_FILENAME
    index = data.setdefault("index", {})
    if not isinstance(index, dict):
        index = {}
        data["index"] = index
    if not isinstance(index.get("keywords"), dict):
        index["keywords"] = {}
    if not isinstance(index.get("recent_ids"), list):
        index["recent_ids"] = []
    if not isinstance(index.get("entries"), dict):
        index["entries"] = {}
    data.pop("sender_id", None)
    data.pop("profile", None)
    data.pop("memories", None)


def _select_working_memory_prompt(index_path: Path, data: dict[str, Any], query_text: str, max_chars: int) -> tuple[str, list[str]]:
    if max_chars < 1:
        return "", []

    _normalize_working_memory_data(data, str(data.get("instance_name", "")))
    index = data.get("index") if isinstance(data.get("index"), dict) else {}
    entry_index = index.get("entries") if isinstance(index.get("entries"), dict) else {}
    if not entry_index:
        return "", []

    scores: dict[str, int] = {}
    keyword_index = index.get("keywords") if isinstance(index.get("keywords"), dict) else {}
    for keyword in _memory_keywords(query_text):
        for memory_id in keyword_index.get(keyword, []):
            if memory_id in entry_index:
                scores[memory_id] = scores.get(memory_id, 0) + 1

    recent_ids = [str(memory_id) for memory_id in index.get("recent_ids", [])] if isinstance(index.get("recent_ids"), list) else []
    if scores:
        ordered_ids = sorted(
            scores,
            key=lambda memory_id: (
                scores[memory_id],
                recent_ids.index(memory_id) if memory_id in recent_ids else -1,
            ),
            reverse=True,
        )
    else:
        ordered_ids = list(reversed(recent_ids))
    if not ordered_ids:
        ordered_ids = list(reversed(list(entry_index.keys())))

    selected: list[dict[str, Any]] = []
    selected_ids: list[str] = []
    for memory_id in ordered_ids:
        memory = _read_working_memory_entry(index_path, data, memory_id)
        if memory is None or memory_id in selected_ids:
            continue
        candidate = _compact_working_memory_for_prompt(memory)
        candidate_payload = _working_memory_prompt_payload(data, [*selected_ids, memory_id], [*selected, candidate])
        candidate_text = json.dumps(candidate_payload, ensure_ascii=False, indent=2)
        if len(candidate_text) > max_chars:
            if selected:
                break
            candidate["text"] = _clip_memory_text(str(candidate.get("text", "")), max(200, max_chars // 2))
            candidate_payload = _working_memory_prompt_payload(data, [memory_id], [candidate])
            candidate_text = json.dumps(candidate_payload, ensure_ascii=False, indent=2)
            if len(candidate_text) > max_chars:
                break
        selected.append(candidate)
        selected_ids.append(memory_id)

    if not selected:
        return "", []
    return json.dumps(_working_memory_prompt_payload(data, selected_ids, selected), ensure_ascii=False, indent=2), selected_ids


def _working_memory_prompt_payload(
    data: dict[str, Any],
    selected_ids: list[str],
    selected: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "scope": "instance",
        "instance_name": str(data.get("instance_name", "")),
        "privacy": WORKING_MEMORY_PRIVACY_NOTE,
        "selected_working_memory_ids": selected_ids,
        "memories": selected,
    }


def _store_working_memory_entry(index_path: Path, data: dict[str, Any], entry: dict[str, Any]) -> None:
    _normalize_working_memory_data(data, str(data.get("instance_name", "")))
    memory_id = str(entry.get("id") or _new_working_memory_id())
    entry["id"] = memory_id
    entry["text"] = _sanitize_working_memory_text(str(entry.get("text", "")))
    keywords = _memory_keywords(str(entry.get("text", "")))
    entry["keywords"] = keywords

    entries_path = _working_memory_entries_path(index_path)
    entries_path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    with entries_path.open("ab") as file:
        offset = file.tell()
        file.write(line)

    index = data.setdefault("index", {})
    entry_index = index.setdefault("entries", {})
    if not isinstance(entry_index, dict):
        entry_index = {}
        index["entries"] = entry_index
    entry_index[memory_id] = {
        "offset": offset,
        "length": len(line),
        "created_at": str(entry.get("created_at", "")),
        "updated_at": str(entry.get("updated_at", "")),
        "kind": str(entry.get("kind", "")),
        "keywords": keywords,
    }

    keyword_index = index.setdefault("keywords", {})
    if not isinstance(keyword_index, dict):
        keyword_index = {}
        index["keywords"] = keyword_index
    for keyword in keywords[:MEMORY_KEYWORD_LIMIT]:
        entries = keyword_index.setdefault(keyword, [])
        if not isinstance(entries, list):
            entries = []
            keyword_index[keyword] = entries
        if memory_id not in entries:
            entries.append(memory_id)
            del entries[:-MEMORY_KEYWORD_ENTRY_LIMIT]

    recent_ids = index.setdefault("recent_ids", [])
    if not isinstance(recent_ids, list):
        recent_ids = []
        index["recent_ids"] = recent_ids
    if memory_id in recent_ids:
        recent_ids.remove(memory_id)
    recent_ids.append(memory_id)
    del recent_ids[:-MEMORY_RECENT_LIMIT]


def _read_working_memory_entry(index_path: Path, data: dict[str, Any], memory_id: str) -> dict[str, Any] | None:
    index = data.get("index") if isinstance(data.get("index"), dict) else {}
    entries = index.get("entries") if isinstance(index.get("entries"), dict) else {}
    metadata = entries.get(memory_id)
    if not isinstance(metadata, dict):
        return None
    try:
        offset = int(metadata.get("offset"))
        length = int(metadata.get("length"))
    except (TypeError, ValueError):
        return None
    try:
        with _working_memory_entries_path(index_path).open("rb") as file:
            file.seek(offset)
            payload = json.loads(file.read(length).decode("utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.exception("Failed to read JSONL instance working memory entry id=%s.", memory_id)
        return None
    if not isinstance(payload, dict) or str(payload.get("id", "")) != memory_id:
        return None
    return payload


def _working_memory_entries_path(index_path: Path) -> Path:
    return index_path.parent / WORKING_MEMORY_ENTRIES_FILENAME


def _compact_working_memory_for_prompt(memory: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(memory.get("id", "")),
        "created_at": str(memory.get("created_at", "")),
        "kind": str(memory.get("kind", "")),
        "keywords": memory.get("keywords", []) if isinstance(memory.get("keywords"), list) else [],
        "text": str(memory.get("text", "")),
    }


def _sanitize_working_memory_text(text: str) -> str:
    sanitized = str(text or "").strip()
    sanitized = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[email entfernt]", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"(?<!\w)@[A-Za-z0-9_]{3,}", "[handle entfernt]", sanitized)
    sanitized = re.sub(r"https?://\S+|www\.\S+", "[url entfernt]", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\b\+?\d[\d\s()./-]{4,}\d\b", "[zahl entfernt]", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized


def _legacy_memory_entry(text: str) -> dict[str, Any]:
    timestamp = _utc_timestamp()
    clipped = _clip_memory_text(text, 12000)
    return {
        "id": _new_memory_id(),
        "created_at": timestamp,
        "updated_at": timestamp,
        "source": {
            "chat_id": "legacy",
            "chat_type": "legacy",
            "chat_title": "Legacy Markdown Import",
            "message_type": "legacy",
        },
        "sender": {},
        "keywords": _memory_keywords(clipped),
        "related_ids": [],
        "user_text": "",
        "bot_text": clipped,
    }


def _append_json_memory_interaction(
    index_path: Path,
    data: dict[str, Any],
    message: dict[str, Any],
    user_text: str,
    bot_text: str,
    max_entry_chars: int,
    related_ids: tuple[str, ...],
) -> None:
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    sender_chat = message.get("sender_chat") if isinstance(message.get("sender_chat"), dict) else {}
    timestamp = _utc_timestamp()
    sender_id = _sender_identifier(message)
    sender_name = _sender_display_name(sender, sender_chat)
    sender_username = _username(sender.get("username") if sender else sender_chat.get("username"))
    chat_id = _metadata_value(chat.get("id"))
    chat_title = _metadata_value(chat.get("title"))
    clipped_user_text = _clip_memory_text(user_text, max_entry_chars)
    clipped_bot_text = _clip_memory_text(bot_text, max_entry_chars)
    entry = {
        "id": _new_memory_id(),
        "created_at": timestamp,
        "updated_at": timestamp,
        "source": {
            "chat_id": chat_id,
            "chat_type": _metadata_value(chat.get("type")),
            "chat_title": chat_title,
            "message_type": _message_kind(message),
        },
        "sender": {
            "sender_id": sender_id,
            "sender_name": sender_name,
            "sender_username": sender_username,
        },
        "keywords": _memory_keywords(f"{clipped_user_text}\n{clipped_bot_text}"),
        "related_ids": [memory_id for memory_id in related_ids if memory_id],
        "user_text": clipped_user_text,
        "bot_text": clipped_bot_text,
    }

    _store_memory_entry(index_path, data, entry)
    _append_profile_value(data, "names", sender_name)
    _append_profile_value(data, "usernames", sender_username)
    _append_profile_value(data, "chat_ids", chat_id)
    _append_profile_value(data, "chat_titles", chat_title)
    data["updated_at"] = timestamp


def _select_user_memory_prompt(index_path: Path, data: dict[str, Any], query_text: str, max_chars: int) -> tuple[str, list[str]]:
    if max_chars < 1:
        return "", []

    scores: dict[str, int] = {}
    index = data.get("index") if isinstance(data.get("index"), dict) else {}
    entry_index = index.get("entries") if isinstance(index.get("entries"), dict) else {}
    if not entry_index:
        return "", []
    keyword_index = index.get("keywords") if isinstance(index.get("keywords"), dict) else {}
    for keyword in _memory_keywords(query_text):
        for memory_id in keyword_index.get(keyword, []):
            if memory_id in entry_index:
                scores[memory_id] = scores.get(memory_id, 0) + 1

    recent_ids = [str(memory_id) for memory_id in index.get("recent_ids", [])] if isinstance(index.get("recent_ids"), list) else []
    if scores:
        ordered_ids = sorted(
            scores,
            key=lambda memory_id: (
                scores[memory_id],
                recent_ids.index(memory_id) if memory_id in recent_ids else -1,
            ),
            reverse=True,
        )
    else:
        ordered_ids = list(reversed(recent_ids))

    if not ordered_ids:
        ordered_ids = list(reversed(list(entry_index.keys())))

    selected: list[dict[str, Any]] = []
    selected_ids: list[str] = []
    for memory_id in ordered_ids:
        memory = _read_memory_entry(index_path, data, memory_id)
        if memory is None or memory_id in selected_ids:
            continue
        candidate = _compact_memory_for_prompt(memory)
        candidate_payload = {
            "sender_id": str(data.get("sender_id", "")),
            "selected_memory_ids": [*selected_ids, memory_id],
            "memories": [*selected, candidate],
        }
        candidate_text = json.dumps(candidate_payload, ensure_ascii=False, indent=2)
        if len(candidate_text) > max_chars:
            if selected:
                break
            candidate["user_text"] = _clip_memory_text(str(candidate.get("user_text", "")), max(200, max_chars // 3))
            candidate["bot_text"] = _clip_memory_text(str(candidate.get("bot_text", "")), max(200, max_chars // 3))
            candidate_payload = {
                "sender_id": str(data.get("sender_id", "")),
                "selected_memory_ids": [memory_id],
                "memories": [candidate],
            }
            candidate_text = json.dumps(candidate_payload, ensure_ascii=False, indent=2)
            if len(candidate_text) > max_chars:
                break
        selected.append(candidate)
        selected_ids.append(memory_id)

    if not selected:
        return "", []
    payload = {
        "sender_id": str(data.get("sender_id", "")),
        "selected_memory_ids": selected_ids,
        "memories": selected,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2), selected_ids


def _store_memory_entry(index_path: Path, data: dict[str, Any], entry: dict[str, Any]) -> None:
    _normalize_user_memory_data(data, str(data.get("sender_id", "")))
    memory_id = str(entry.get("id") or _new_memory_id())
    entry["id"] = memory_id
    keywords = entry.get("keywords")
    if not isinstance(keywords, list) or not all(isinstance(keyword, str) for keyword in keywords):
        keywords = _memory_keywords(f"{entry.get('user_text', '')}\n{entry.get('bot_text', '')}")
        entry["keywords"] = keywords

    entries_path = _memory_entries_path(index_path)
    entries_path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    with entries_path.open("ab") as file:
        offset = file.tell()
        file.write(line)

    index = data.setdefault("index", {})
    entry_index = index.setdefault("entries", {})
    if not isinstance(entry_index, dict):
        entry_index = {}
        index["entries"] = entry_index
    entry_index[memory_id] = {
        "offset": offset,
        "length": len(line),
        "created_at": str(entry.get("created_at", "")),
        "updated_at": str(entry.get("updated_at", "")),
        "keywords": keywords,
        "source": entry.get("source", {}) if isinstance(entry.get("source"), dict) else {},
    }

    keyword_index = index.setdefault("keywords", {})
    if not isinstance(keyword_index, dict):
        keyword_index = {}
        index["keywords"] = keyword_index
    for keyword in keywords[:MEMORY_KEYWORD_LIMIT]:
        entries = keyword_index.setdefault(keyword, [])
        if not isinstance(entries, list):
            entries = []
            keyword_index[keyword] = entries
        if memory_id not in entries:
            entries.append(memory_id)
            del entries[:-MEMORY_KEYWORD_ENTRY_LIMIT]

    recent_ids = index.setdefault("recent_ids", [])
    if not isinstance(recent_ids, list):
        recent_ids = []
        index["recent_ids"] = recent_ids
    if memory_id in recent_ids:
        recent_ids.remove(memory_id)
    recent_ids.append(memory_id)
    del recent_ids[:-MEMORY_RECENT_LIMIT]


def _read_memory_entry(index_path: Path, data: dict[str, Any], memory_id: str) -> dict[str, Any] | None:
    index = data.get("index") if isinstance(data.get("index"), dict) else {}
    entries = index.get("entries") if isinstance(index.get("entries"), dict) else {}
    metadata = entries.get(memory_id)
    if not isinstance(metadata, dict):
        return None
    try:
        offset = int(metadata.get("offset"))
        length = int(metadata.get("length"))
    except (TypeError, ValueError):
        return None
    try:
        with _memory_entries_path(index_path).open("rb") as file:
            file.seek(offset)
            payload = json.loads(file.read(length).decode("utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.exception("Failed to read JSONL user memory entry id=%s.", memory_id)
        return None
    if not isinstance(payload, dict) or str(payload.get("id", "")) != memory_id:
        return None
    return payload


def _migrate_inline_json_memory(index_path: Path, payload: dict[str, Any], sender_id: str) -> dict[str, Any]:
    data = _new_user_memory_data(sender_id)
    data["created_at"] = str(payload.get("created_at") or data["created_at"])
    data["updated_at"] = str(payload.get("updated_at") or data["updated_at"])
    profile = payload.get("profile")
    if isinstance(profile, dict):
        data["profile"] = profile
    entries_path = _memory_entries_path(index_path)
    entries_path.parent.mkdir(parents=True, exist_ok=True)
    entries_path.write_bytes(b"")
    for memory in payload.get("memories", []):
        if isinstance(memory, dict):
            _store_memory_entry(index_path, data, memory)
    _write_json_file(index_path, data)
    return data


def _memory_entries_path(index_path: Path) -> Path:
    return index_path.parent / USER_MEMORY_ENTRIES_FILENAME


def _memory_habits_path(index_path: Path) -> Path:
    return index_path.parent / USER_HABITS_FILENAME


def _ensure_user_habits_file(index_path: Path) -> None:
    habits_path = _memory_habits_path(index_path)
    if not habits_path.exists():
        habits_path.write_text("", encoding="utf-8")


def _load_user_habits_text(index_path: Path, max_chars: int) -> str:
    _ensure_user_habits_file(index_path)
    if max_chars < 1:
        return ""
    return _read_limited_text(_memory_habits_path(index_path), max_chars).strip()


def _combine_user_memory_prompt(habits_text: str, memory_text: str) -> str:
    parts: list[str] = []
    if habits_text.strip():
        parts.extend(
            [
                f"Inhalt aus {USER_HABITS_FILENAME} fuer diese sender_id:",
                habits_text.strip(),
            ]
        )
    if memory_text.strip():
        parts.extend(
            [
                "Ausgewaehlte Memory-Eintraege fuer diese sender_id:",
                memory_text.strip(),
            ]
        )
    return "\n\n".join(parts)


def _read_limited_text(path: Path, max_chars: int) -> str:
    try:
        with path.open("r", encoding="utf-8") as file:
            text = file.read(max_chars + 1)
    except FileNotFoundError:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n[gekuerzt]"


def _load_legacy_user_memory(index_path: Path, sender_id: str) -> dict[str, Any] | None:
    legacy_json_path = _first_existing_path(_legacy_json_memory_paths(index_path, sender_id))
    if legacy_json_path is None:
        return None
    try:
        payload = json.loads(legacy_json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        LOGGER.exception("Failed to read legacy JSON user memory for sender_id=%s.", sender_id)
        return None
    if not isinstance(payload, dict) or str(payload.get("sender_id", "")) != sender_id:
        LOGGER.warning("Ignoring legacy user memory with mismatched sender_id at %s.", legacy_json_path)
        return None
    if isinstance(payload.get("memories"), list):
        return _migrate_inline_json_memory(index_path, payload, sender_id)

    entries_path = _memory_entries_path(index_path)
    entries_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_entries_path = _first_existing_path(_legacy_entries_memory_paths(index_path, sender_id))
    if legacy_entries_path is not None:
        entries_path.write_bytes(legacy_entries_path.read_bytes())
    else:
        entries_path.write_bytes(b"")
    _normalize_user_memory_data(payload, sender_id)
    return payload


def _first_existing_path(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _legacy_json_memory_paths(index_path: Path, sender_id: str) -> list[Path]:
    safe_sender_id = _safe_memory_filename(sender_id)
    paths = [index_path.parent.parent / f"{safe_sender_id}.json"]
    instance_name = _instance_name_from_memory_path(index_path)
    if instance_name:
        paths.append(Path("data") / instance_name / "users" / f"{safe_sender_id}.json")
    return paths


def _legacy_entries_memory_paths(index_path: Path, sender_id: str) -> list[Path]:
    safe_sender_id = _safe_memory_filename(sender_id)
    paths = [index_path.parent.parent / f"{safe_sender_id}.entries.jsonl"]
    instance_name = _instance_name_from_memory_path(index_path)
    if instance_name:
        paths.append(Path("data") / instance_name / "users" / f"{safe_sender_id}.entries.jsonl")
    return paths


def _legacy_markdown_memory_path(index_path: Path, sender_id: str) -> Path:
    return index_path.parent.parent / _safe_memory_filename(sender_id)


def _instance_name_from_memory_path(index_path: Path) -> str:
    parts = index_path.parts
    for index, part in enumerate(parts):
        if part == "instances" and index + 1 < len(parts):
            return parts[index + 1]
    return ""


def _compact_memory_for_prompt(memory: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(memory.get("id", "")),
        "created_at": str(memory.get("created_at", "")),
        "source": memory.get("source", {}) if isinstance(memory.get("source"), dict) else {},
        "keywords": memory.get("keywords", []) if isinstance(memory.get("keywords"), list) else [],
        "user_text": str(memory.get("user_text", "")),
        "bot_text": str(memory.get("bot_text", "")),
    }


def _write_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_profile_value(data: dict[str, Any], key: str, value: str) -> None:
    value = str(value or "").strip()
    if not value or value == "unbekannt":
        return
    profile = data.setdefault("profile", {})
    if not isinstance(profile, dict):
        profile = {}
        data["profile"] = profile
    values = profile.setdefault(key, [])
    if not isinstance(values, list):
        values = []
        profile[key] = values
    if value not in values:
        values.append(value)
        del values[:-MEMORY_RECENT_LIMIT]


def _memory_keywords(text: str) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"\b\w{3,}\b", str(text or "").casefold(), re.UNICODE):
        keyword = match.group(0).strip("_")
        if not keyword or keyword in MEMORY_STOPWORDS or keyword.isdigit():
            continue
        if keyword in seen:
            continue
        seen.add(keyword)
        keywords.append(keyword)
        if len(keywords) >= MEMORY_KEYWORD_LIMIT:
            break
    return keywords


def _new_memory_id() -> str:
    return f"mem_{uuid.uuid4().hex}"


def _new_working_memory_id() -> str:
    return f"wm_{uuid.uuid4().hex}"


def _clip_memory_text(text: str, max_chars: int) -> str:
    stripped = str(text or "").strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[:max_chars].rstrip() + "\n[gekuerzt]"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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
    stop_event: threading.Event | None = None,
    poll_timeout: int = 50,
    token_label: str = "1",
    openai_api_key: str | None = None,
    bot_identity: BotIdentity | None = None,
) -> None:
    instance = instance_name or _resolve_instance_name()
    instruction_store = instruction_store or InstructionStore(_resolve_instruction_path(instance))
    resolved_openai_api_key = openai_api_key if openai_api_key is not None else _resolve_openai_api_key(instance)
    openai_client = OpenAIClient(resolved_openai_api_key) if resolved_openai_api_key else None
    bot_identity = bot_identity or _resolve_bot_identity(api)
    user_memory_store = UserMemoryStore(instance)
    working_memory_store = WorkingMemoryStore(instance)
    working_memory_store.ensure()
    chat_state = ChatState()
    LOGGER.info(
        "Bot started instance=%s token_slot=%s bot_name=%s bot_username=%s. Waiting for Telegram updates.",
        instance,
        token_label,
        bot_identity.display_name or "unknown",
        bot_identity.mention or "unknown",
    )
    offset: int | None = None
    retry_delay = INITIAL_RETRY_DELAY_SECONDS

    while stop_event is None or not stop_event.is_set():
        try:
            updates = api.get_updates(offset, timeout=poll_timeout)
            retry_delay = INITIAL_RETRY_DELAY_SECONDS
            for update in updates:
                handle_update(
                    api,
                    update,
                    instruction_store.get(),
                    openai_client,
                    chat_state,
                    user_memory_store,
                    bot_identity,
                    working_memory_store,
                )
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


def run_polling_many(configs: list[BotTokenConfig], instruction_path: str, instance_name: str) -> None:
    run_polling_all([InstanceRunConfig(instance_name, instruction_path, tuple(configs))])


def run_polling_all(instance_configs: list[InstanceRunConfig]) -> None:
    stop_event = threading.Event()
    threads: list[threading.Thread] = []
    for instance_config in instance_configs:
        for config in instance_config.token_configs:
            thread = threading.Thread(
                target=run_polling,
                kwargs={
                    "api": TelegramAPI(config.token),
                    "instruction_store": InstructionStore(instance_config.instruction_path),
                    "instance_name": instance_config.instance_name,
                    "stop_event": stop_event,
                    "poll_timeout": MULTI_BOT_POLL_TIMEOUT_SECONDS,
                    "token_label": config.label,
                    "openai_api_key": config.openai_api_key,
                },
                name=f"telegram-bot-{instance_config.instance_name}-{config.label}",
                daemon=True,
            )
            threads.append(thread)
            thread.start()

    LOGGER.info("Started %s Telegram bot token slots across %s instance(s).", len(threads), len(instance_configs))
    try:
        while any(thread.is_alive() for thread in threads):
            for thread in threads:
                thread.join(timeout=0.5)
    except KeyboardInterrupt:
        LOGGER.info("Stopping %s Telegram bot token slots.", len(threads))
        stop_event.set()
        for thread in threads:
            thread.join(timeout=MULTI_BOT_POLL_TIMEOUT_SECONDS + 1)


def main(argv: list[str] | None = None) -> int:
    _load_dotenv(PROJECT_ROOT / ".env")
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    args = list(sys.argv[1:] if argv is None else argv)
    if any(arg != "--all" for arg in args):
        print("Usage: python3 -m telegram_bot [--all]", file=sys.stderr)
        return 2
    if "--all" in args or _resolve_instance_name().casefold() == "all":
        return _main_all_instances()

    instance_name = _resolve_instance_name()
    configs = _resolve_bot_token_configs(instance_name)
    instance_token_key = _instance_env_key("TELEGRAM_BOT_TOKEN", instance_name)
    if not configs:
        print(
            f"Missing Telegram bot token. Set TELEGRAM_BOT_TOKEN, {instance_token_key}, or {_instance_env_key('TELEGRAM_BOT_TOKENS', instance_name)}.",
            file=sys.stderr,
        )
        return 2
    config_error = _bot_token_config_error(configs)
    if config_error:
        print(config_error, file=sys.stderr)
        return 2
    if not _has_instance_telegram_tokens(instance_name) and os.getenv("TELEGRAM_BOT_TOKEN", "").strip():
        LOGGER.warning(
            "Using generic TELEGRAM_BOT_TOKEN for instance=%s. Set %s for parallel operation.",
            instance_name,
            instance_token_key,
        )

    instruction_path = _resolve_instruction_path(instance_name)
    LOGGER.info("Using bot instance=%s instructions=%s token_count=%s", instance_name, instruction_path, len(configs))
    if len(configs) == 1:
        config = configs[0]
        run_polling(
            TelegramAPI(config.token),
            InstructionStore(instruction_path),
            instance_name,
            token_label=config.label,
            openai_api_key=config.openai_api_key,
        )
    else:
        run_polling_many(configs, instruction_path, instance_name)
    return 0


def _main_all_instances() -> int:
    instance_names = _discover_instance_names()
    if not instance_names:
        print(
            f"No bot instances found. Expected directories under TELEGRAM_BOT_INSTANCES_DIR with {BOT_INSTRUCTION_FILENAME}.",
            file=sys.stderr,
        )
        return 2

    instance_configs: list[InstanceRunConfig] = []
    errors: list[str] = []
    for instance_name in instance_names:
        configs = _resolve_bot_token_configs(instance_name)
        if not configs:
            LOGGER.warning("Skipping instance=%s because no Telegram token is configured.", instance_name)
            continue
        config_error = _bot_token_config_error(configs)
        if config_error:
            errors.append(f"{instance_name}: {config_error}")
            continue
        instance_configs.append(
            InstanceRunConfig(
                instance_name=instance_name,
                instruction_path=_resolve_instruction_path(instance_name),
                token_configs=tuple(configs),
            )
        )

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 2
    duplicate_error = _duplicate_telegram_token_error(instance_configs)
    if duplicate_error:
        print(duplicate_error, file=sys.stderr)
        return 2
    if not instance_configs:
        print("No configured bot instances found with Telegram tokens.", file=sys.stderr)
        return 2

    LOGGER.info(
        "Starting all configured bot instances: %s",
        ", ".join(config.instance_name for config in instance_configs),
    )
    run_polling_all(instance_configs)
    return 0


def _resolve_instance_name() -> str:
    return os.getenv("TELEGRAM_BOT_INSTANCE", DEFAULT_INSTANCE_NAME).strip() or DEFAULT_INSTANCE_NAME


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        key = key.strip()
        if not key:
            continue
        if key in DOTENV_RUNTIME_KEYS and key in os.environ:
            continue
        os.environ[key] = value.strip()


def _duplicate_telegram_token_error(instance_configs: list[InstanceRunConfig]) -> str:
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for instance_config in instance_configs:
        for token_config in instance_config.token_configs:
            label = f"{instance_config.instance_name}:{token_config.label}"
            previous_label = seen.get(token_config.token)
            if previous_label is None:
                seen[token_config.token] = label
            else:
                duplicates.append(f"{previous_label} / {label}")
    if not duplicates:
        return ""
    return (
        "Duplicate Telegram bot token configured across bot slots. "
        "Each Telegram name needs its own BotFather token. Duplicate slot pairs: "
        + ", ".join(duplicates)
    )


def _resolve_bot_identity(api: TelegramAPI) -> BotIdentity:
    get_me = getattr(api, "get_me", None)
    if not callable(get_me):
        return BotIdentity()
    try:
        return get_me()
    except TelegramAPIError as exc:
        LOGGER.warning("Could not resolve Telegram bot identity via getMe: %s", exc)
        return BotIdentity()


def _resolve_instruction_path(instance_name: str | None = None) -> str:
    explicit_path = os.getenv("TELEGRAM_BOT_INSTRUCTIONS", "").strip()
    if explicit_path:
        return explicit_path
    instance = instance_name or _resolve_instance_name()
    return os.path.join(str(_resolve_instances_dir()), instance, BOT_INSTRUCTION_FILENAME)


def _resolve_instances_dir() -> Path:
    return Path(os.getenv("TELEGRAM_BOT_INSTANCES_DIR", "instances").strip() or "instances")


def _discover_instance_names() -> list[str]:
    explicit_instances = _split_env_tokens(os.getenv("TELEGRAM_BOT_INSTANCES", ""))
    if explicit_instances:
        return explicit_instances

    instances_dir = _resolve_instances_dir()
    if not instances_dir.exists():
        return []
    return sorted(
        path.name
        for path in instances_dir.iterdir()
        if path.is_dir() and (path / BOT_INSTRUCTION_FILENAME).exists()
    )


def _resolve_telegram_token(instance_name: str) -> str:
    tokens = _resolve_telegram_tokens(instance_name)
    return tokens[0] if tokens else ""


def _resolve_telegram_tokens(instance_name: str) -> list[str]:
    instance_token_key = _instance_env_key("TELEGRAM_BOT_TOKEN", instance_name)
    instance_tokens_key = _instance_env_key("TELEGRAM_BOT_TOKENS", instance_name)
    candidates: list[str] = []
    candidates.extend(_split_env_tokens(os.getenv(instance_tokens_key, "")))
    candidates.extend(_split_env_tokens(os.getenv(instance_token_key, "")))
    candidates.extend(_indexed_env_tokens(instance_token_key))
    if not candidates:
        candidates.extend(_split_env_tokens(os.getenv("TELEGRAM_BOT_TOKENS", "")))
        candidates.extend(_split_env_tokens(os.getenv("TELEGRAM_BOT_TOKEN", "")))
    return _dedupe_tokens(candidates)


def _has_instance_telegram_tokens(instance_name: str) -> bool:
    instance_token_key = _instance_env_key("TELEGRAM_BOT_TOKEN", instance_name)
    instance_tokens_key = _instance_env_key("TELEGRAM_BOT_TOKENS", instance_name)
    return bool(
        _split_env_tokens(os.getenv(instance_tokens_key, ""))
        or _split_env_tokens(os.getenv(instance_token_key, ""))
        or _indexed_env_tokens(instance_token_key)
    )


def _resolve_openai_api_key(instance_name: str) -> str:
    keys = _resolve_openai_api_keys(instance_name, 1)
    return keys[0] if keys else ""


def _resolve_bot_token_configs(instance_name: str) -> list[BotTokenConfig]:
    tokens = _resolve_telegram_tokens(instance_name)
    keys = _resolve_openai_api_keys(instance_name, len(tokens))
    return [
        BotTokenConfig(label=str(index), token=token, openai_api_key=keys[index - 1] if index - 1 < len(keys) else "")
        for index, token in enumerate(tokens, start=1)
    ]


def _resolve_openai_api_keys(instance_name: str, count: int) -> list[str]:
    if count < 1:
        return []

    keys = [""] * count
    instance_key = _instance_env_key("OPENAI_API_KEY", instance_name)
    instance_keys_key = _instance_env_key("OPENAI_API_KEYS", instance_name)

    for index, value in enumerate(_split_env_tokens(os.getenv(instance_keys_key, ""))[:count]):
        keys[index] = value

    base_value = os.getenv(instance_key, "").strip()
    if base_value and not keys[0]:
        keys[0] = base_value

    for index, value in _indexed_env_items(instance_key):
        if 1 <= index <= count and not keys[index - 1]:
            keys[index - 1] = value

    if count == 1 and not keys[0]:
        keys[0] = os.getenv("OPENAI_API_KEY", "").strip()
    return keys


def _bot_token_config_error(configs: list[BotTokenConfig]) -> str:
    if len(configs) <= 1:
        return ""

    missing = [config.label for config in configs if not config.openai_api_key]
    if missing:
        return (
            "Missing OpenAI API key for Telegram bot token slot(s): "
            f"{', '.join(missing)}. Set matching OPENAI_API_KEY_<INSTANCE>[_N] or OPENAI_API_KEYS_<INSTANCE>."
        )

    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for config in configs:
        previous_label = seen.get(config.openai_api_key)
        if previous_label is not None:
            duplicates.append(f"{previous_label}/{config.label}")
        else:
            seen[config.openai_api_key] = config.label
    if duplicates:
        return (
            "Multiple Telegram bot token slots for one instance must not share the same OpenAI API key. "
            f"Duplicate slot pairs: {', '.join(duplicates)}."
        )
    return ""


def _split_env_tokens(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[\s,;]+", value.strip()) if part.strip()]


def _indexed_env_tokens(base_key: str) -> list[str]:
    return [value for _, value in _indexed_env_items(base_key)]


def _indexed_env_items(base_key: str) -> list[tuple[int, str]]:
    matches: list[tuple[int, str]] = []
    prefix = f"{base_key}_"
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        suffix = key[len(prefix) :]
        if suffix.isdigit() and value.strip():
            matches.append((int(suffix), value.strip()))
    return sorted(matches)


def _dedupe_tokens(tokens: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped


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
        "voice",
        "text",
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
