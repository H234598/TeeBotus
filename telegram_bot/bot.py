from __future__ import annotations

import concurrent.futures
import io
import json
import logging
import os
import re
import select
import signal
import shutil
import subprocess
import sys
import threading
import time
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .handlers import build_reply, should_use_openai
from .instructions import BotInstructions, InstructionStore, render_template
from .openai_client import OpenAIAPIError, OpenAIClient
from .user_memory_crypto import (
    USER_MEMORY_KEY_FILENAME,
    UserMemoryCryptoError,
    ensure_user_memory_key,
    read_json as read_encrypted_user_memory_json,
    read_jsonl as read_encrypted_user_memory_jsonl,
    read_text as read_encrypted_user_memory_text,
    write_json as write_encrypted_user_memory_json,
    write_jsonl as write_encrypted_user_memory_jsonl,
    write_text as write_encrypted_user_memory_text,
)

LOGGER = logging.getLogger("telegram_bot")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_BASE = "https://api.telegram.org/bot{token}/{method}"
FILE_API_BASE = "https://api.telegram.org/file/bot{token}/{file_path}"
MAX_TRACKED_BOT_MESSAGES = 100
MAX_TRACKED_CHAT_MESSAGES = 1000
INITIAL_RETRY_DELAY_SECONDS = 5
MAX_RETRY_DELAY_SECONDS = 60
TELEGRAM_MESSAGE_CHUNK_SIZE = 3900
TELADI_EMERGENCY_CHAT_ID = 395935293
TELADI_EMERGENCY_COOLDOWN_SECONDS = 24 * 60 * 60
DEFAULT_INSTANCE_NAME = "Bote_der_Wahrheit"
BOT_INSTRUCTION_FILENAME = "Bot_Verhalten.md"
MULTI_BOT_POLL_TIMEOUT_SECONDS = 5
USER_MEMORY_INDEX_FILENAME = "User_Memory_Index.json"
USER_MEMORY_ENTRIES_FILENAME = "User_Memory_Entries.jsonl"
USER_HABITS_FILENAME = "User_Habbits_and_behave.md"
USER_AVATAR_BASENAME = "User_Avatar"
USER_AVATAR_ICON_FILENAME = "User_Avatar.icon"
USER_AVATAR_ICON_MARKER_FILENAME = ".User_Avatar_Icon_Set"
USER_AVATAR_CHECK_MARKER_FILENAME = ".User_Avatar_Checked"
USER_AVATAR_REFRESH_SECONDS = 7 * 24 * 60 * 60
USER_AVATAR_MISSING_RECHECK_SECONDS = 24 * 60 * 60
USER_HABITS_MAX_PROMPT_CHARS = 4000
YOUTUBE_TRANSCRIPT_COMMANDS = {"/youtube_transcript", "/yt_transcript"}
YOUTUBE_TRANSCRIPT_TIMEOUT_SECONDS = 15 * 60
YOUTUBE_WHISPER_TIMEOUT_SECONDS = 60 * 60
YOUTUBE_TRANSCRIPT_MAX_PIPELINE_CHARS = 60000
YOUTUBE_WHISPER_MODEL = "tiny"
YOUTUBE_FASTER_WHISPER_COMPUTE_TYPE = "int8"
YOUTUBE_FASTER_WHISPER_CPU_THREADS = 2
YOUTUBE_TRANSCRIPT_NICE_LEVEL = 19
YOUTUBE_LOCAL_TRANSCRIPTION_WORKERS = 1
YOUTUBE_LIVE_CHUNK_WORDS = 310
WORKING_MEMORY_INDEX_FILENAME = "Working_Memorys.json"
WORKING_MEMORY_ENTRIES_FILENAME = "Working_Memorys.entries.jsonl"
TELADI_CALL_STATE_FILENAME = "Teladi_Emergency_State.json"
WORKING_MEMORY_MAX_PROMPT_CHARS = 6000
WORKING_MEMORY_PRIVACY_NOTE = (
    "Instanzweites Arbeitsgedaechtnis. Darf keine User-IDs, Namen, Usernames, Chat-IDs, "
    "Chat-Titel, Rohzitate aus Usernachrichten oder eindeutig userbezogene Fakten enthalten."
)


class YouTubeTranscriptionJobRunner:
    def __init__(self, max_workers: int = YOUTUBE_LOCAL_TRANSCRIPTION_WORKERS) -> None:
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, max_workers),
            thread_name_prefix="youtube-transcript-job",
        )

    def submit(self, callback) -> concurrent.futures.Future[Any]:
        future = self._executor.submit(callback)
        future.add_done_callback(self._log_unhandled_exception)
        return future

    def shutdown(self, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)

    @staticmethod
    def _log_unhandled_exception(future: concurrent.futures.Future[Any]) -> None:
        try:
            future.result()
        except Exception:
            LOGGER.exception("Unhandled YouTube transcription job error.")


PROCESS_REGISTRY_FILENAME = "YouTube_Transcription_Processes.json"
_PROCESS_REGISTRY_LOCKS: dict[str, threading.Lock] = {}


class _InstanceProcessRegistry:
    def __init__(self, instance_name: str) -> None:
        self.instance_name = instance_name.strip()
        self._lock = _PROCESS_REGISTRY_LOCKS.setdefault(self.instance_name, threading.Lock())

    def register(self, pid: int) -> None:
        if not self.instance_name or pid <= 0:
            return
        with self._lock:
            state = self._load_state()
            pids = state.setdefault("pids", [])
            if pid not in pids:
                pids.append(pid)
            state["updated_at"] = _utc_timestamp()
            self._write_state(state)

    def unregister(self, pid: int) -> None:
        if not self.instance_name or pid <= 0:
            return
        with self._lock:
            state = self._load_state()
            pids = state.get("pids")
            if isinstance(pids, list) and pid in pids:
                pids.remove(pid)
                state["updated_at"] = _utc_timestamp()
                self._write_state(state)

    def cleanup_orphans(self) -> None:
        if not self.instance_name:
            return
        with self._lock:
            state = self._load_state()
            pids = [int(pid) for pid in state.get("pids", []) if isinstance(pid, int) or str(pid).isdigit()]
            for pid in pids:
                self._terminate_process_group(pid)
            self._write_state({"pids": [], "updated_at": _utc_timestamp()})

    def _path(self) -> Path:
        return PROJECT_ROOT / "instances" / self.instance_name / "data" / PROCESS_REGISTRY_FILENAME

    def _load_state(self) -> dict[str, Any]:
        path = self._path()
        if not path.exists():
            return {"pids": []}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            LOGGER.debug("Failed to read process registry at %s.", path)
            return {"pids": []}
        if not isinstance(payload, dict):
            return {"pids": []}
        pids = payload.get("pids")
        if not isinstance(pids, list):
            payload["pids"] = []
        else:
            payload["pids"] = [pid for pid in pids if isinstance(pid, int) and pid > 0]
        return payload

    def _write_state(self, state: dict[str, Any]) -> None:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @staticmethod
    def _terminate_process_group(pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except OSError:
            LOGGER.debug("Failed to terminate process group %s with SIGTERM.", pid)
            return
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                os.killpg(pid, 0)
            except ProcessLookupError:
                return
            except OSError:
                return
            time.sleep(0.1)
        with suppress(ProcessLookupError, OSError):
            os.killpg(pid, signal.SIGKILL)

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
        except TimeoutError as exc:
            raise TelegramNetworkError(f"Telegram network timeout: {exc}") from exc
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
        except TimeoutError as exc:
            raise TelegramNetworkError(f"Telegram network timeout: {exc}") from exc
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

    def copy_message(self, chat_id: int, from_chat_id: int, message_id: int) -> int | None:
        payload = self.request(
            "copyMessage",
            {
                "chat_id": chat_id,
                "from_chat_id": from_chat_id,
                "message_id": message_id,
            },
        )
        result = payload.get("result")
        if not isinstance(result, dict):
            return None
        copied_message_id = result.get("message_id")
        return int(copied_message_id) if isinstance(copied_message_id, int) else None

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

    def get_user_profile_photo_file_id(self, user_id: int) -> str | None:
        payload = self.request("getUserProfilePhotos", {"user_id": user_id, "limit": 1})
        result = payload.get("result")
        if not isinstance(result, dict):
            raise TelegramAPIError(f"Telegram getUserProfilePhotos result is invalid: {payload}")
        photos = result.get("photos")
        if not isinstance(photos, list) or not photos:
            return None
        first_photo = photos[0]
        if not isinstance(first_photo, list) or not first_photo:
            return None
        best = max(
            (photo for photo in first_photo if isinstance(photo, dict)),
            key=lambda photo: int(photo.get("file_size") or 0) or int(photo.get("width") or 0) * int(photo.get("height") or 0),
            default=None,
        )
        if best is None:
            return None
        file_id = best.get("file_id")
        return str(file_id).strip() if isinstance(file_id, str) and file_id.strip() else None

    def download_file(self, file_path: str) -> bytes:
        quoted_path = urllib.parse.quote(file_path, safe="/")
        url = FILE_API_BASE.format(token=self.token, file_path=quoted_path)
        request = urllib.request.Request(url, method="GET")

        try:
            with urllib.request.urlopen(request, timeout=75) as response:
                return response.read()
        except TimeoutError as exc:
            raise TelegramNetworkError(f"Telegram file network timeout: {exc}") from exc
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
    def __init__(self, teladi_call_state_path: Path | None = None, instance_name: str = "") -> None:
        self._lock = threading.RLock()
        self.previous_response_ids: dict[int, str] = {}
        self.sent_message_ids: dict[int, list[int]] = {}
        self.recent_message_ids: dict[int, list[int]] = {}
        self.auto_voice_eligible_counts: dict[int, int] = {}
        self.seen_sender_ids: set[str] = set()
        self.depression_alert_signatures: set[str] = set()
        self.pending_user_memory_resets: set[tuple[int, str]] = set()
        self.pending_youtube_transcript_requests: set[tuple[int, str]] = set()
        self.pending_youtube_local_options: dict[tuple[int, str], str] = {}
        self.pending_teladi_calls: dict[str, int] = {}
        self.teladi_call_state_path = teladi_call_state_path
        self.instance_name = instance_name
        self.teladi_call_used_at: dict[str, float] = self._load_teladi_call_used_at()

    def get_previous_response_id(self, chat_id: int) -> str | None:
        with self._lock:
            return self.previous_response_ids.get(chat_id)

    def set_previous_response_id(self, chat_id: int, response_id: str | None) -> None:
        with self._lock:
            if response_id:
                self.previous_response_ids[chat_id] = response_id

    def reset(self, chat_id: int) -> None:
        with self._lock:
            self.previous_response_ids.pop(chat_id, None)

    def record_sent_message(self, chat_id: int, message_id: int | None) -> None:
        if message_id is None:
            return
        with self._lock:
            message_ids = self.sent_message_ids.setdefault(chat_id, [])
            message_ids.append(message_id)
            del message_ids[:-MAX_TRACKED_BOT_MESSAGES]
            self._record_recent_message_locked(chat_id, message_id)

    def record_received_message(self, chat_id: int, message_id: int | None) -> None:
        if message_id is None:
            return
        with self._lock:
            self._record_recent_message_locked(chat_id, message_id)

    def pop_last_sent_message(self, chat_id: int) -> int | None:
        with self._lock:
            message_ids = self.sent_message_ids.get(chat_id)
            if not message_ids:
                return None
            return message_ids.pop()

    def pop_sent_messages(self, chat_id: int, count: int) -> list[int]:
        with self._lock:
            message_ids = self.sent_message_ids.get(chat_id)
            if not message_ids:
                return []
            selected = message_ids[-count:]
            del message_ids[-count:]
            return list(reversed(selected))

    def discard_recent_message(self, chat_id: int, message_id: int | None) -> None:
        if message_id is None:
            return
        with self._lock:
            message_ids = self.recent_message_ids.get(chat_id)
            if not message_ids:
                return
            for index in range(len(message_ids) - 1, -1, -1):
                if message_ids[index] == message_id:
                    del message_ids[index]
                    break

    def pop_recent_messages(self, chat_id: int, count: int) -> list[int]:
        if count < 1:
            return []
        with self._lock:
            message_ids = self.recent_message_ids.get(chat_id)
            if not message_ids:
                return []
            selected = message_ids[-count:]
            del message_ids[-count:]
            return list(reversed(selected))

    def _record_recent_message_locked(self, chat_id: int, message_id: int) -> None:
        message_ids = self.recent_message_ids.setdefault(chat_id, [])
        message_ids.append(message_id)
        del message_ids[:-MAX_TRACKED_CHAT_MESSAGES]

    def should_send_auto_voice(self, chat_id: int, every: int) -> bool:
        if every < 1:
            return False
        count = self.auto_voice_eligible_counts.get(chat_id, 0) + 1
        self.auto_voice_eligible_counts[chat_id] = count
        return count % every == 0

    def has_seen_sender(self, sender_id: str) -> bool:
        with self._lock:
            return sender_id in self.seen_sender_ids

    def mark_sender_seen(self, sender_id: str) -> None:
        with self._lock:
            if sender_id:
                self.seen_sender_ids.add(sender_id)

    def claim_depression_alert_signature(self, signature: str) -> bool:
        with self._lock:
            if signature in self.depression_alert_signatures:
                return False
            self.depression_alert_signatures.add(signature)
            return True

    def request_user_memory_reset(self, chat_id: int, sender_id: str) -> None:
        if sender_id:
            self.pending_user_memory_resets.add((chat_id, sender_id))

    def has_pending_user_memory_reset(self, chat_id: int, sender_id: str) -> bool:
        return (chat_id, sender_id) in self.pending_user_memory_resets

    def clear_pending_user_memory_reset(self, chat_id: int, sender_id: str) -> None:
        self.pending_user_memory_resets.discard((chat_id, sender_id))

    def request_youtube_transcript_link(self, chat_id: int, sender_id: str) -> None:
        with self._lock:
            if sender_id:
                self.pending_youtube_transcript_requests.add((chat_id, sender_id))

    def has_pending_youtube_transcript_link(self, chat_id: int, sender_id: str) -> bool:
        with self._lock:
            return (chat_id, sender_id) in self.pending_youtube_transcript_requests

    def clear_pending_youtube_transcript_link(self, chat_id: int, sender_id: str) -> None:
        with self._lock:
            self.pending_youtube_transcript_requests.discard((chat_id, sender_id))

    def request_youtube_local_options(self, chat_id: int, sender_id: str, url: str) -> None:
        with self._lock:
            if sender_id and url:
                self.pending_youtube_local_options[(chat_id, sender_id)] = url

    def get_pending_youtube_local_options(self, chat_id: int, sender_id: str) -> str:
        with self._lock:
            return self.pending_youtube_local_options.get((chat_id, sender_id), "")

    def clear_pending_youtube_local_options(self, chat_id: int, sender_id: str) -> None:
        with self._lock:
            self.pending_youtube_local_options.pop((chat_id, sender_id), None)

    def request_teladi_call(self, chat_id: int, sender_id: str) -> None:
        if sender_id:
            self.pending_teladi_calls[sender_id] = chat_id

    def has_pending_teladi_call(self, chat_id: int, sender_id: str) -> bool:
        return self.pending_teladi_calls.get(sender_id) == chat_id

    def clear_pending_teladi_call(self, sender_id: str) -> None:
        self.pending_teladi_calls.pop(sender_id, None)

    def teladi_call_remaining_seconds(self, sender_id: str, now: float) -> int:
        self._refresh_teladi_call_used_at()
        used_at = self.teladi_call_used_at.get(sender_id)
        if used_at is None:
            return 0
        remaining = int(used_at + TELADI_EMERGENCY_COOLDOWN_SECONDS - now)
        return max(0, remaining)

    def mark_teladi_call_used(self, sender_id: str, now: float) -> None:
        if sender_id:
            self._refresh_teladi_call_used_at()
            self.teladi_call_used_at[sender_id] = now
            self._persist_teladi_call_used_at()

    def clear_teladi_call_used(self, sender_id: str) -> None:
        self._refresh_teladi_call_used_at()
        self.teladi_call_used_at.pop(sender_id, None)
        self._persist_teladi_call_used_at()

    def _refresh_teladi_call_used_at(self) -> None:
        if self.teladi_call_state_path is not None:
            self.teladi_call_used_at = self._load_teladi_call_used_at()

    def _load_teladi_call_used_at(self) -> dict[str, float]:
        if self.teladi_call_state_path is None or not self.teladi_call_state_path.exists():
            return {}
        try:
            payload = json.loads(self.teladi_call_state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            LOGGER.exception("Failed to read Teladi emergency state from %s.", self.teladi_call_state_path)
            return {}
        used_at = payload.get("used_at") if isinstance(payload, dict) else {}
        if not isinstance(used_at, dict):
            return {}
        parsed: dict[str, float] = {}
        for sender_id, timestamp in used_at.items():
            try:
                parsed[str(sender_id)] = float(timestamp)
            except (TypeError, ValueError):
                continue
        return parsed

    def _persist_teladi_call_used_at(self) -> None:
        if self.teladi_call_state_path is None:
            return
        _write_json_file(
            self.teladi_call_state_path,
            {
                "schema_version": 1,
                "used_at": self.teladi_call_used_at,
            },
        )


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
        api: TelegramAPI | None = None,
    ) -> UserMemoryRecord | None:
        if not instructions.user_memory_enabled:
            return None

        sender_id = _sender_identifier(message)
        if not sender_id:
            return None

        path = self._path_for_sender(sender_id, instructions)
        with self._lock:
            data = self._load_or_initialize(path, sender_id)
            _ensure_user_avatar_assets(api, path, message)
            key = _ensure_user_memory_key(path)
            habits_text = _load_user_habits_text(path, key, USER_HABITS_MAX_PROMPT_CHARS)
            memory_text, selected_ids = _select_user_memory_prompt(
                path,
                data,
                query_text,
                instructions.user_memory_max_prompt_chars,
                key,
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
            key = _ensure_user_memory_key(record.path)
            data = self._load_or_initialize(record.path, record.sender_id)
            _append_json_memory_interaction(
                record.path,
                data,
                message,
                user_text,
                bot_text,
                instructions.user_memory_max_entry_chars,
                record.selected_ids,
                key,
            )
            _write_user_memory_json(record.path, data, key)

    def reset_sender(self, sender_id: str, instructions: BotInstructions) -> Path:
        if not instructions.user_memory_enabled:
            raise ValueError("User memory is not enabled")
        if not sender_id:
            raise ValueError("sender_id must not be empty")

        path = self._path_for_sender(sender_id, instructions)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            key = _ensure_user_memory_key(path)
            _write_user_memory_json(path, _new_user_memory_data(sender_id), key)
            _write_user_memory_entries(path, [], key)
            for legacy_path in [*_legacy_json_memory_paths(path, sender_id), *_legacy_entries_memory_paths(path, sender_id)]:
                _unlink_file_if_exists(legacy_path)
            legacy_markdown_path = _legacy_markdown_memory_path(path, sender_id)
            if legacy_markdown_path.is_file():
                _unlink_file_if_exists(legacy_markdown_path)
        return path

    def has_sender(self, sender_id: str, instructions: BotInstructions) -> bool:
        if not instructions.user_memory_enabled or not sender_id:
            return False
        path = self._path_for_sender(sender_id, instructions)
        key_path = _user_memory_key_path(path)
        return (
            path.exists()
            or _memory_entries_path(path).exists()
            or _memory_habits_path(path).exists()
            or key_path.exists()
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
        key = _ensure_user_memory_key(path)
        if not path.exists():
            legacy_data = _load_legacy_user_memory(path, sender_id, key)
            if legacy_data is not None:
                _write_user_memory_json(path, legacy_data, key)
                _ensure_user_habits_file(path, key)
                return legacy_data
            legacy_markdown_path = _legacy_markdown_memory_path(path, sender_id)
            if legacy_markdown_path.is_file():
                data = _new_user_memory_data(sender_id)
                _store_memory_entry(path, data, _legacy_memory_entry(legacy_markdown_path.read_text(encoding="utf-8")), key)
                _write_user_memory_json(path, data, key)
                _ensure_user_habits_file(path, key)
                return data
            data = _new_user_memory_data(sender_id)
            _write_user_memory_json(path, data, key)
            _ensure_user_habits_file(path, key)
            return data

        try:
            payload, migrated = read_encrypted_user_memory_json(
                path,
                key,
                kind="user-memory-index",
                default=_new_user_memory_data(sender_id),
            )
        except (json.JSONDecodeError, OSError, UserMemoryCryptoError):
            LOGGER.exception("Failed to read JSON user memory for sender_id=%s.", sender_id)
            payload = _new_user_memory_data(sender_id)
            migrated = True
        if not isinstance(payload, dict) or str(payload.get("sender_id", "")) != sender_id:
            LOGGER.warning("Ignoring user memory with mismatched sender_id at %s.", path)
            payload = _new_user_memory_data(sender_id)
        elif isinstance(payload.get("memories"), list):
            payload = _migrate_inline_json_memory(path, payload, sender_id, key)
        _normalize_user_memory_data(payload, sender_id)
        if migrated:
            _write_user_memory_json(path, payload, key)
        _ensure_user_habits_file(path, key)
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
    youtube_job_runner: YouTubeTranscriptionJobRunner | None = None,
    instance_name: str = "",
) -> None:
    instructions = instructions or BotInstructions()
    chat_state = chat_state or ChatState()
    bot_identity = bot_identity or BotIdentity()
    message = update.get("message")
    if not isinstance(message, dict):
        return

    instance_name = ""
    if working_memory_store is not None:
        instance_name = working_memory_store.instance_name
    elif user_memory_store is not None:
        instance_name = user_memory_store.instance_name
    elif instance_name:
        instance_name = instance_name
    elif chat_state is not None:
        instance_name = chat_state.instance_name

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
    chat_state.record_received_message(chat_id, _message_id_or_none(message))

    text = str(message.get("text") or "").strip()
    first_contact = _is_first_contact(chat_state, user_memory_store, message, instructions)
    if _handle_pending_teladi_call_message(api, chat_state, chat_id, message, instructions, first_contact, bot_identity):
        return

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
            instance_name,
        )
        return

    if not _should_process_for_bot(message, text, bot_identity, first_contact):
        LOGGER.info(
            "Ignoring Telegram message chat_id=%s message_id=%s reason=not_addressed_to_bot",
            chat_id,
            message.get("message_id", "unknown"),
        )
        return
    user_memory = _prepare_user_memory(user_memory_store, message, instructions, text, api)
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
        youtube_job_runner,
        instance_name,
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
    youtube_job_runner: YouTubeTranscriptionJobRunner | None = None,
    instance_name: str = "",
) -> None:
    chat_state.mark_sender_seen(_sender_identifier(message))
    bot_identity = bot_identity or BotIdentity()
    _maybe_send_depression_alert(api, chat_state, chat_id, message, instructions, text, instance_name, "incoming")
    if text and _handle_teladi_call_flow(api, chat_state, chat_id, message, instructions, text, first_contact, bot_identity):
        return

    if text and _handle_user_memory_reset_flow(
        api,
        chat_state,
        chat_id,
        message,
        instructions,
        user_memory_store,
        text,
        bot_identity,
        first_contact,
    ):
        return

    if text and _normalize_command(text) == "/reset":
        chat_state.reset(chat_id)
        reply = _with_first_contact_intro(instructions.openai_reset, first_contact, bot_identity)
        _send_tracked_message(api, chat_state, chat_id, reply)
        _record_user_memory(user_memory_store, user_memory, message, text, reply, instructions)
        return

    if text and _normalize_command(text) == "/voice":
        _handle_voice_command(api, chat_state, chat_id, message, instructions, openai_client, text)
        return

    if text and _handle_pending_youtube_local_options(
        api,
        chat_state,
        chat_id,
        message,
        text,
        user_memory_store,
        user_memory,
        instructions,
        openai_client,
        bot_identity,
        first_contact,
        working_memory_store,
        youtube_job_runner,
        instance_name,
    ):
        return

    if text and _should_handle_youtube_transcript_request(chat_state, chat_id, message, text):
        _handle_youtube_transcript_request(
            api,
            chat_state,
            chat_id,
            message,
            text,
            user_memory_store,
            user_memory,
            instructions,
            openai_client,
            bot_identity,
            first_contact,
            working_memory_store,
            instance_name,
        )
        return

    if text and _handle_cleanup_command(api, chat_state, chat_id, message, instructions, text):
        return

    if text and _handle_codex_command(api, chat_state, chat_id, message, instructions, text, first_contact, bot_identity):
        return

    reply = build_reply(message, instructions, include_fallback=not instructions.openai_enabled)
    if reply:
        if _normalize_command(text) == "/start":
            reply = _with_bot_identity_intro(reply, bot_identity)
        else:
            reply = _with_first_contact_intro(reply, first_contact, bot_identity)
        _maybe_send_depression_alert(api, chat_state, chat_id, message, instructions, reply, instance_name, "reply")
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
            _maybe_send_depression_alert(api, chat_state, chat_id, message, instructions, reply, instance_name, "reply")
            _send_tracked_message(api, chat_state, chat_id, reply)
            _record_user_memory(user_memory_store, user_memory, message, text, reply, instructions)
            return
        chat_state.set_previous_response_id(chat_id, openai_response.response_id)
        reply = _with_first_contact_intro(openai_response.text, first_contact, bot_identity)
        _maybe_send_depression_alert(api, chat_state, chat_id, message, instructions, reply, instance_name, "reply")
        _send_openai_response(api, chat_state, chat_id, message, reply, instructions, openai_client)
        _record_user_memory(user_memory_store, user_memory, message, text, reply, instructions)
        return

    fallback = build_reply(message, instructions, include_fallback=True)
    if fallback:
        fallback = _with_first_contact_intro(fallback, first_contact, bot_identity)
        _maybe_send_depression_alert(api, chat_state, chat_id, message, instructions, fallback, instance_name, "reply")
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
    instance_name: str = "",
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
    except (TimeoutError, subprocess.TimeoutExpired) as exc:
        LOGGER.error("Transcription timed out: %s", exc)
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
    user_memory = _prepare_user_memory(user_memory_store, transcribed_message, instructions, transcribed_text, api)
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
        instance_name=instance_name,
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


def _handle_teladi_call_flow(
    api: TelegramAPI,
    chat_state: ChatState,
    chat_id: int,
    message: dict[str, Any],
    instructions: BotInstructions,
    text: str,
    first_contact: bool,
    bot_identity: BotIdentity,
) -> bool:
    sender_id = _sender_identifier(message)
    if not sender_id:
        return False

    command = _normalize_command(text)
    now = time.time()
    if chat_state.has_pending_teladi_call(chat_id, sender_id):
        return _handle_pending_teladi_call_message(api, chat_state, chat_id, message, instructions, first_contact, bot_identity)

    if command != "/call_a_teladi":
        return False
    return _start_teladi_call(api, chat_state, chat_id, message, instructions, sender_id, now, first_contact, bot_identity)


def _handle_pending_teladi_call_message(
    api: TelegramAPI,
    chat_state: ChatState,
    chat_id: int,
    message: dict[str, Any],
    instructions: BotInstructions,
    first_contact: bool,
    bot_identity: BotIdentity,
) -> bool:
    sender_id = _sender_identifier(message)
    if not sender_id or not chat_state.has_pending_teladi_call(chat_id, sender_id):
        return False

    raw_text = str(message.get("text") or "")
    now = time.time()
    if _normalize_command(raw_text) == "/call_a_teladi":
        return _start_teladi_call(api, chat_state, chat_id, message, instructions, sender_id, now, first_contact, bot_identity)

    chat_state.clear_pending_teladi_call(sender_id)
    try:
        _send_untracked_message(api, TELADI_EMERGENCY_CHAT_ID, _build_teladi_emergency_header(message))
        _copy_untracked_message(api, TELADI_EMERGENCY_CHAT_ID, chat_id, _message_id(message))
    except (TelegramAPIError, ValueError):
        LOGGER.exception("Failed to send Teladi emergency message.")
        chat_state.clear_teladi_call_used(sender_id)
        reply = _with_first_contact_intro(instructions.teladi_call_error, first_contact, bot_identity)
        _send_tracked_message(api, chat_state, chat_id, reply)
        return True

    reply = _with_first_contact_intro(instructions.teladi_call_sent, first_contact, bot_identity)
    _send_tracked_message(api, chat_state, chat_id, reply)
    return True


def _start_teladi_call(
    api: TelegramAPI,
    chat_state: ChatState,
    chat_id: int,
    message: dict[str, Any],
    instructions: BotInstructions,
    sender_id: str,
    now: float,
    first_contact: bool,
    bot_identity: BotIdentity,
) -> bool:
    remaining_seconds = chat_state.teladi_call_remaining_seconds(sender_id, now)
    if remaining_seconds > 0:
        reply = render_template(
            instructions.teladi_call_cooldown,
            message,
            str(message.get("text") or ""),
            {"remaining": _format_remaining_seconds(remaining_seconds)},
        )
        reply = _with_first_contact_intro(reply, first_contact, bot_identity)
        _send_tracked_message(api, chat_state, chat_id, reply)
        return True

    chat_state.request_teladi_call(chat_id, sender_id)
    chat_state.mark_teladi_call_used(sender_id, now)
    reply = _with_first_contact_intro(instructions.teladi_call_prompt, first_contact, bot_identity)
    _send_tracked_message(api, chat_state, chat_id, reply)
    return True


def _build_teladi_emergency_header(message: dict[str, Any]) -> str:
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    sender_chat = message.get("sender_chat") if isinstance(message.get("sender_chat"), dict) else {}
    sender_name = _sender_display_name(sender, sender_chat)
    sender_username = _username(sender.get("username") if sender else sender_chat.get("username"))
    sender_bits = [bit for bit in (sender_name, sender_username) if bit]
    sender_label = " ".join(sender_bits) if sender_bits else "unbekannt"
    chat_title = _metadata_value(chat.get("title"))
    chat_type = _metadata_value(chat.get("type"))
    chat_id = _metadata_value(chat.get("id"))
    sender_id = _metadata_value(sender.get("id") if sender else sender_chat.get("id"))
    return "\n".join(
        [
            "Emergency message via /Call_a_Teladi",
            f"From: {sender_label} (sender_id: {sender_id})",
            f"Chat: {chat_title} (type: {chat_type}, chat_id: {chat_id})",
        ]
    )


def _message_id(message: dict[str, Any]) -> int:
    value = message.get("message_id")
    if isinstance(value, int):
        return value
    raise ValueError("Telegram message has no message_id to copy")


def _message_id_or_none(message: dict[str, Any]) -> int | None:
    value = message.get("message_id")
    return value if isinstance(value, int) else None


def _format_remaining_seconds(seconds: int) -> str:
    seconds = max(1, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds and not hours:
        parts.append(f"{seconds}s")
    return " ".join(parts) if parts else "1s"


def _maybe_send_depression_alert(
    api: TelegramAPI,
    chat_state: ChatState,
    chat_id: int,
    message: dict[str, Any],
    instructions: BotInstructions,
    text: str,
    instance_name: str,
    source: str,
) -> None:
    if instance_name != "Depressionsbot":
        return

    reason = _detect_depression_alert_reason(text)
    if reason is None:
        return

    sender_id = _sender_identifier(message) or f"chat:{chat_id}"
    signature = f"{instance_name}:{chat_id}:{sender_id}:{reason}"
    if not chat_state.claim_depression_alert_signature(signature):
        return

    try:
        _send_untracked_message(
            api,
            TELADI_EMERGENCY_CHAT_ID,
            _build_depression_alert_message(message, chat_id, text, reason, source),
        )
    except TelegramAPIError:
        LOGGER.exception("Failed to send Depressionsbot crisis alert.")


def _detect_depression_alert_reason(text: str) -> str | None:
    normalized = _normalize_depression_alert_text(text)
    if not normalized:
        return None

    suicide_patterns = (
        r"\bsuizid\b",
        r"\bselbstmord\b",
        r"\bselbst toeten\b",
        r"\bmir etwas antun\b",
        r"\bmich umbringen\b",
        r"\bleben beenden\b",
        r"\bnicht mehr leben\b",
        r"\bsterben wollen\b",
        r"\bsuizidgefahr\b",
    )
    if any(re.search(pattern, normalized) for pattern in suicide_patterns):
        return "suizid"

    stress_patterns = (
        r"\bstress(?:stufe|level)?\s*(?:[:=]|ist|bei)?\s*10\b",
        r"\b10\s*/\s*10\b",
        r"\bhoechste stressstufe\b",
        r"\bhöchste stressstufe\b",
        r"\bmaximale stressstufe\b",
    )
    if any(re.search(pattern, normalized) for pattern in stress_patterns):
        return "stress_10"

    return None


def _normalize_depression_alert_text(text: str) -> str:
    normalized = str(text or "").casefold()
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
    }
    for source, replacement in replacements.items():
        normalized = normalized.replace(source, replacement)
    normalized = re.sub(r"[_-]+", " ", normalized)
    normalized = re.sub(r"[^0-9a-z@/]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _build_depression_alert_message(
    message: dict[str, Any],
    chat_id: int,
    text: str,
    reason: str,
    source: str,
) -> str:
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    sender_chat = message.get("sender_chat") if isinstance(message.get("sender_chat"), dict) else {}
    sender_name = _sender_display_name(sender, sender_chat)
    sender_username = _username(sender.get("username") if sender else sender_chat.get("username"))
    sender_bits = [bit for bit in (sender_name, sender_username) if bit]
    sender_label = " ".join(sender_bits) if sender_bits else "unbekannt"
    alert_text = text.strip()
    if len(alert_text) > 1200:
        alert_text = f"{alert_text[:1200]}..."
    return "\n".join(
        [
            "Depressionsbot Krisenalarm",
            f"Grund: {'Suizid' if reason == 'suizid' else 'Stressstufe 10'}",
            f"Quelle: {source}",
            f"Chat: {_metadata_value(chat.get('title'))} (type: {_metadata_value(chat.get('type'))}, chat_id: {_metadata_value(chat.get('id'))})",
            f"Sender: {sender_label} (sender_id: {_metadata_value(sender.get('id') if sender else sender_chat.get('id'))})",
            f"Text: {alert_text or 'unbekannt'}",
        ]
    )


def _handle_user_memory_reset_flow(
    api: TelegramAPI,
    chat_state: ChatState,
    chat_id: int,
    message: dict[str, Any],
    instructions: BotInstructions,
    user_memory_store: UserMemoryStore | None,
    text: str,
    bot_identity: BotIdentity,
    first_contact: bool,
) -> bool:
    sender_id = _sender_identifier(message)
    if not sender_id:
        return False

    if chat_state.has_pending_user_memory_reset(chat_id, sender_id):
        if _is_user_memory_reset_confirmation(text):
            chat_state.clear_pending_user_memory_reset(chat_id, sender_id)
            reply = _reset_current_user_memory(user_memory_store, sender_id, instructions)
            reply = _with_first_contact_intro(reply, first_contact, bot_identity)
            _send_tracked_message(api, chat_state, chat_id, reply)
            return True
        if _is_user_memory_reset_cancellation(text):
            chat_state.clear_pending_user_memory_reset(chat_id, sender_id)
            reply = _with_first_contact_intro(instructions.user_memory_reset_cancelled, first_contact, bot_identity)
            _send_tracked_message(api, chat_state, chat_id, reply)
            return True
        if _is_user_memory_reset_intent(text):
            if _user_memory_reset_targets_forbidden(text, bot_identity):
                chat_state.clear_pending_user_memory_reset(chat_id, sender_id)
                reply = _with_first_contact_intro(instructions.user_memory_reset_only_own, first_contact, bot_identity)
                _send_tracked_message(api, chat_state, chat_id, reply)
                return True
            reply = _with_first_contact_intro(instructions.user_memory_reset_confirm, first_contact, bot_identity)
            _send_tracked_message(api, chat_state, chat_id, reply)
            return True
        chat_state.clear_pending_user_memory_reset(chat_id, sender_id)
        return False

    if not _is_user_memory_reset_intent(text):
        return False

    if _user_memory_reset_targets_forbidden(text, bot_identity):
        reply = _with_first_contact_intro(instructions.user_memory_reset_only_own, first_contact, bot_identity)
        _send_tracked_message(api, chat_state, chat_id, reply)
        return True

    if user_memory_store is None or not instructions.user_memory_enabled:
        reply = _with_first_contact_intro(instructions.user_memory_reset_unavailable, first_contact, bot_identity)
        _send_tracked_message(api, chat_state, chat_id, reply)
        return True

    chat_state.request_user_memory_reset(chat_id, sender_id)
    reply = _with_first_contact_intro(instructions.user_memory_reset_confirm, first_contact, bot_identity)
    _send_tracked_message(api, chat_state, chat_id, reply)
    return True


def _reset_current_user_memory(
    user_memory_store: UserMemoryStore | None,
    sender_id: str,
    instructions: BotInstructions,
) -> str:
    if user_memory_store is None or not instructions.user_memory_enabled:
        return instructions.user_memory_reset_unavailable
    try:
        user_memory_store.reset_sender(sender_id, instructions)
    except (OSError, ValueError):
        LOGGER.exception("Failed to reset user memory for sender_id=%s.", sender_id)
        return instructions.user_memory_reset_error
    return instructions.user_memory_reset_success


def _is_user_memory_reset_confirmation(text: str) -> bool:
    normalized = _normalize_memory_reset_text(text)
    return bool(re.fullmatch(r"(ja|ja bitte|jep|yes|y|ok|okay|bestaetige|bestatige|loeschen|loesch es|mach das)", normalized))


def _is_user_memory_reset_cancellation(text: str) -> bool:
    normalized = _normalize_memory_reset_text(text)
    return bool(re.fullmatch(r"(nein|no|n|abbrechen|stop|stopp|nicht loeschen|lass es|behalten)", normalized))


def _is_user_memory_reset_intent(text: str) -> bool:
    normalized = _normalize_memory_reset_text(text)
    command = _normalize_command(text)
    if command in {"/reset_memorys", "/forget_me", "/forgetme", "/delete_memory", "/memory_reset", "/reset_memory"}:
        return True
    if _is_negated_memory_reset_request(normalized):
        return False
    if not _has_memory_reset_action(normalized):
        return False
    if _has_memory_reset_memory_reference(normalized):
        return True
    if re.search(r"\b(vergiss|vergessen|loesch(?:e|en)?|reset(?:te|ten)?|wipe|clear|delete)\b", normalized) and re.search(
        r"\b(mich|mir|alles|all das|alles ueber mich|alles von mir)\b",
        normalized,
    ):
        return True
    return False


def _has_memory_reset_action(normalized_text: str) -> bool:
    return bool(
        re.search(
            r"\b("
            r"loesch(?:e|en|t)?|geloescht|vergiss|vergessen|entfern(?:e|en|t)?|"
            r"reset(?:te|ten)?|zuruecksetz(?:e|en|t)?|wipe|clear|delete"
            r")\b",
            normalized_text,
        )
    )


def _is_negated_memory_reset_request(normalized_text: str) -> bool:
    action_pattern = r"(loesch(?:e|en|t)?|vergiss|vergessen|entfern(?:e|en|t)?|reset(?:te|ten)?|delete)"
    return bool(
        re.search(rf"\bnicht\b.{{0,40}}\b{action_pattern}\b", normalized_text)
        or re.search(rf"\b{action_pattern}\b.{{0,40}}\bnicht\b", normalized_text)
    )


def _has_memory_reset_memory_reference(normalized_text: str) -> bool:
    if re.search(r"\b(memory|memories|erinnerung(?:en)?|gedaechtnis|speicher|daten)\b", normalized_text):
        return True
    return bool(re.search(r"\b(alles|all das)\b.*\b(ueber mich|von mir|zu mir|an mich|mich)\b", normalized_text))


def _user_memory_reset_targets_forbidden(text: str, bot_identity: BotIdentity) -> bool:
    normalized = _normalize_memory_reset_text(text)
    if re.search(r"\b(instanz|arbeitsgedaechtnis|working memory|global(?:e|en)?|alle user|alle nutzer|fremde|andere)\b", normalized):
        return True

    bot_username = bot_identity.username.strip().lstrip("@").casefold()
    for username in re.findall(r"@([A-Za-z0-9_]{3,})", text):
        if username.casefold() != bot_username:
            return True

    if _has_self_memory_reference(normalized):
        return False
    if re.search(
        r"\b(seine|seinen|seinem|seiner|ihre|ihren|ihrem|ihrer|dessen|deren)\s+"
        r"(memory|memories|erinnerung(?:en)?|gedaechtnis|speicher|daten)\b",
        normalized,
    ):
        return True
    if re.search(
        r"\b(?!meine?\b|meinen\b|meinem\b|meiner\b|deine?\b|deinen\b|deinem\b|deiner\b)[a-z0-9_@-]{3,}s\s+"
        r"(memory|memories|erinnerung(?:en)?|gedaechtnis|speicher|daten)\b",
        normalized,
    ):
        return True
    return bool(re.search(r"\b(?:von|ueber|an|fuer)\s+(?!mir\b|mich\b|meine?\b|meinen\b|meinem\b|selbst\b)[a-z0-9_@-]{3,}\b", normalized))


def _has_self_memory_reference(normalized_text: str) -> bool:
    return bool(re.search(r"\b(mein(?:e|en|em|er)?|mich|mir|ueber mich|von mir|an mich|zu mir|fuer mich|selbst)\b", normalized_text))


def _normalize_memory_reset_text(text: str) -> str:
    normalized = str(text or "").casefold()
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
    }
    for source, replacement in replacements.items():
        normalized = normalized.replace(source, replacement)
    normalized = re.sub(r"[_-]+", " ", normalized)
    normalized = re.sub(r"[^0-9a-z@/]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


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
    api: TelegramAPI | None = None,
) -> UserMemoryRecord | None:
    if user_memory_store is None:
        return None
    try:
        return user_memory_store.prepare(message, instructions, query_text, api)
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
    if not first_contact:
        return text
    return _with_bot_identity_intro(text, bot_identity)


def _with_bot_identity_intro(text: str, bot_identity: BotIdentity) -> str:
    display_name = bot_identity.display_name
    if not display_name:
        return text
    intro = f"Ich bin {display_name}."
    stripped = text.strip()
    if not stripped:
        return intro
    if stripped.casefold().startswith(intro.casefold()):
        return text
    text = _strip_embedded_identity_intro(text)
    stripped = text.strip()
    if not stripped:
        return intro
    return f"{intro}\n\n{stripped}"


def _strip_embedded_identity_intro(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        prefix = match.group("prefix")
        name = match.group("name").strip()
        if not name or not name[0].isupper():
            return match.group(0)
        return prefix

    pattern = re.compile(r"(?P<prefix>^|[.!?]\s+)Ich bin (?P<name>[^.!?\n]{1,80})\.\s*")
    return pattern.sub(replace, text).strip()


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
    parts = text.strip().split(maxsplit=1)
    if not parts:
        return False
    command = parts[0]
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
    key: bytes,
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

    _store_memory_entry(index_path, data, entry, key)
    _append_profile_value(data, "names", sender_name)
    _append_profile_value(data, "usernames", sender_username)
    _append_profile_value(data, "chat_ids", chat_id)
    _append_profile_value(data, "chat_titles", chat_title)
    data["updated_at"] = timestamp


def _select_user_memory_prompt(
    index_path: Path,
    data: dict[str, Any],
    query_text: str,
    max_chars: int,
    key: bytes,
) -> tuple[str, list[str]]:
    if max_chars < 1:
        return "", []

    scores: dict[str, int] = {}
    index = data.get("index") if isinstance(data.get("index"), dict) else {}
    entry_index = index.get("entries") if isinstance(index.get("entries"), dict) else {}
    if not entry_index:
        return "", []
    entries_by_id = {
        str(entry.get("id", "")): entry
        for entry in _load_user_memory_entries(index_path, key)
        if isinstance(entry, dict) and str(entry.get("id", ""))
    }
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
        memory = entries_by_id.get(memory_id)
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


def _store_memory_entry(index_path: Path, data: dict[str, Any], entry: dict[str, Any], key: bytes) -> None:
    _normalize_user_memory_data(data, str(data.get("sender_id", "")))
    memory_id = str(entry.get("id") or _new_memory_id())
    entry["id"] = memory_id
    keywords = entry.get("keywords")
    if not isinstance(keywords, list) or not all(isinstance(keyword, str) for keyword in keywords):
        keywords = _memory_keywords(f"{entry.get('user_text', '')}\n{entry.get('bot_text', '')}")
        entry["keywords"] = keywords

    entries = _load_user_memory_entries(index_path, key)
    entries.append(entry)
    _write_user_memory_entries(index_path, entries, key)

    index = data.setdefault("index", {})
    entry_index = index.setdefault("entries", {})
    if not isinstance(entry_index, dict):
        entry_index = {}
        index["entries"] = entry_index
    entry_index[memory_id] = {
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


def _read_memory_entry(index_path: Path, data: dict[str, Any], memory_id: str, key: bytes) -> dict[str, Any] | None:
    entries = _load_user_memory_entries(index_path, key)
    try:
        for payload in entries:
            if isinstance(payload, dict) and str(payload.get("id", "")) == memory_id:
                return payload
    except Exception:
        LOGGER.exception("Failed to read JSONL user memory entry id=%s.", memory_id)
    return None


def _migrate_inline_json_memory(index_path: Path, payload: dict[str, Any], sender_id: str, key: bytes) -> dict[str, Any]:
    data = _new_user_memory_data(sender_id)
    data["created_at"] = str(payload.get("created_at") or data["created_at"])
    data["updated_at"] = str(payload.get("updated_at") or data["updated_at"])
    profile = payload.get("profile")
    if isinstance(profile, dict):
        data["profile"] = profile
    memories: list[dict[str, Any]] = []
    for memory in payload.get("memories", []):
        if isinstance(memory, dict):
            memories.append(memory)
            _store_memory_entry(index_path, data, memory, key)
    _write_user_memory_json(index_path, data, key)
    if not memories:
        _write_user_memory_entries(index_path, [], key)
    return data


def _memory_entries_path(index_path: Path) -> Path:
    return index_path.parent / USER_MEMORY_ENTRIES_FILENAME


def _memory_habits_path(index_path: Path) -> Path:
    return index_path.parent / USER_HABITS_FILENAME


def _memory_avatar_icon_path(index_path: Path) -> Path:
    return index_path.parent / USER_AVATAR_ICON_FILENAME


def _memory_avatar_icon_marker_path(index_path: Path) -> Path:
    return index_path.parent / USER_AVATAR_ICON_MARKER_FILENAME


def _memory_avatar_check_marker_path(index_path: Path) -> Path:
    return index_path.parent / USER_AVATAR_CHECK_MARKER_FILENAME


def _memory_avatar_paths(index_path: Path) -> list[Path]:
    return sorted(
        path
        for path in index_path.parent.glob(f"{USER_AVATAR_BASENAME}.*")
        if path.name not in {USER_AVATAR_ICON_FILENAME, USER_AVATAR_ICON_MARKER_FILENAME, USER_AVATAR_CHECK_MARKER_FILENAME}
    )


def _ensure_user_habits_file(index_path: Path, key: bytes) -> None:
    habits_path = _memory_habits_path(index_path)
    if not habits_path.exists():
        _write_user_memory_text(habits_path, "", key, kind="user-memory-habits")


def _ensure_user_avatar_assets(api: TelegramAPI | None, index_path: Path, message: dict[str, Any]) -> None:
    if api is None:
        return

    avatar_paths = _memory_avatar_paths(index_path)
    icon_path = _memory_avatar_icon_path(index_path)
    if avatar_paths and not _avatar_needs_refresh(avatar_paths[0]) and icon_path.exists():
        _ensure_user_folder_icon(index_path)
        return
    if not avatar_paths and not _avatar_missing_recheck_due(index_path):
        return

    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    user_id = sender.get("id")
    if not isinstance(user_id, int):
        return

    try:
        _mark_user_avatar_checked(index_path)
        file_id = api.get_user_profile_photo_file_id(user_id)
        if not file_id:
            return
        file_path = api.get_file_path(file_id)
        image_bytes = api.download_file(file_path)
        avatar_path = _write_user_avatar(index_path, file_path, image_bytes)
        _write_user_avatar_icon(avatar_path, icon_path)
        _ensure_user_folder_icon(index_path)
    except (OSError, TelegramAPIError, ValueError) as exc:
        LOGGER.debug("Failed to prepare user avatar for user_id=%s: %s", user_id, exc)


def _avatar_needs_refresh(path: Path) -> bool:
    try:
        return time.time() - path.stat().st_mtime > USER_AVATAR_REFRESH_SECONDS
    except FileNotFoundError:
        return True


def _avatar_missing_recheck_due(index_path: Path) -> bool:
    marker_path = _memory_avatar_check_marker_path(index_path)
    try:
        return time.time() - marker_path.stat().st_mtime > USER_AVATAR_MISSING_RECHECK_SECONDS
    except FileNotFoundError:
        return True


def _mark_user_avatar_checked(index_path: Path) -> None:
    _memory_avatar_check_marker_path(index_path).write_text(str(int(time.time())), encoding="utf-8")


def _write_user_avatar(index_path: Path, file_path: str, image_bytes: bytes) -> Path:
    extension = _avatar_extension(file_path, image_bytes)
    avatar_path = index_path.parent / f"{USER_AVATAR_BASENAME}.{extension}"
    for existing_path in _memory_avatar_paths(index_path):
        if existing_path != avatar_path:
            _unlink_file_if_exists(existing_path)
    avatar_path.write_bytes(image_bytes)
    _unlink_file_if_exists(_memory_avatar_icon_marker_path(index_path))
    _unlink_file_if_exists(_memory_avatar_check_marker_path(index_path))
    return avatar_path


def _avatar_extension(file_path: str, image_bytes: bytes) -> str:
    suffix = Path(file_path).suffix.lower().lstrip(".")
    if suffix in {"jpg", "jpeg", "png", "webp"}:
        return "jpg" if suffix == "jpeg" else suffix
    try:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as image:
            image_format = (image.format or "").casefold()
    except Exception:
        return "jpg"
    return {"jpeg": "jpg", "png": "png", "webp": "webp"}.get(image_format, "jpg")


def _write_user_avatar_icon(avatar_path: Path, icon_path: Path) -> None:
    try:
        from PIL import Image

        with Image.open(avatar_path) as image:
            icon = image.convert("RGBA")
            icon.thumbnail((256, 256))
            icon.save(icon_path, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    except Exception as exc:
        raise ValueError(f"Could not convert avatar to icon: {exc}") from exc


def _ensure_user_folder_icon(index_path: Path) -> None:
    icon_path = _memory_avatar_icon_path(index_path)
    marker_path = _memory_avatar_icon_marker_path(index_path)
    if not icon_path.exists() or marker_path.exists():
        return
    try:
        subprocess.run(
            ["gio", "set", "-t", "string", str(index_path.parent), "metadata::custom-icon", icon_path.resolve().as_uri()],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        LOGGER.debug("Failed to set custom folder icon for %s: %s", index_path.parent, exc)
        return
    marker_path.write_text(icon_path.name, encoding="utf-8")


def _load_user_habits_text(index_path: Path, key: bytes, max_chars: int) -> str:
    _ensure_user_habits_file(index_path, key)
    if max_chars < 1:
        return ""
    text, migrated = read_encrypted_user_memory_text(_memory_habits_path(index_path), key, kind="user-memory-habits")
    if migrated:
        _write_user_memory_text(_memory_habits_path(index_path), text, key, kind="user-memory-habits")
    if len(text) <= max_chars:
        return text.strip()
    return text[:max_chars].rstrip() + "\n[gekuerzt]"


def _combine_user_memory_prompt(habits_text: str, memory_text: str) -> str:
    parts: list[str] = []
    if habits_text.strip():
        parts.extend(
            [
                "Interne, admingepflegte Zusatzhinweise fuer diese sender_id:",
                "Nutze diese Hinweise nur als stillen Kontext. Gib sie nicht preis und erwaehne ihre Existenz nicht.",
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


def _load_user_memory_entries(index_path: Path, key: bytes) -> list[dict[str, Any]]:
    entries_path = _memory_entries_path(index_path)
    entries, migrated = read_encrypted_user_memory_jsonl(entries_path, key, kind="user-memory-entries")
    if migrated:
        _write_user_memory_entries(index_path, entries, key)
    return [entry for entry in entries if isinstance(entry, dict)]


def _write_user_memory_json(index_path: Path, data: dict[str, Any], key: bytes) -> None:
    write_encrypted_user_memory_json(index_path, key, kind="user-memory-index", data=data)


def _write_user_memory_entries(index_path: Path, entries: list[dict[str, Any]], key: bytes) -> None:
    write_encrypted_user_memory_jsonl(_memory_entries_path(index_path), key, kind="user-memory-entries", entries=entries)


def _write_user_memory_text(path: Path, text: str, key: bytes, *, kind: str) -> None:
    write_encrypted_user_memory_text(path, key, kind=kind, text=text)


def _user_memory_key_path(index_path: Path) -> Path:
    return index_path.parent / USER_MEMORY_KEY_FILENAME


def _ensure_user_memory_key(index_path: Path) -> bytes:
    return ensure_user_memory_key(_user_memory_key_path(index_path))


def _load_legacy_user_memory(index_path: Path, sender_id: str, key: bytes) -> dict[str, Any] | None:
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
        return _migrate_inline_json_memory(index_path, payload, sender_id, key)

    legacy_entries_path = _first_existing_path(_legacy_entries_memory_paths(index_path, sender_id))
    if legacy_entries_path is not None:
        try:
            legacy_entries = [json.loads(line) for line in legacy_entries_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except json.JSONDecodeError:
            legacy_entries = []
        _write_user_memory_entries(index_path, [entry for entry in legacy_entries if isinstance(entry, dict)], key)
    else:
        _write_user_memory_entries(index_path, [], key)
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


def _unlink_file_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except IsADirectoryError:
        LOGGER.warning("Refusing to delete directory while resetting user memory: %s.", path)


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
    youtube_job_runner: YouTubeTranscriptionJobRunner | None = None,
) -> None:
    owns_youtube_job_runner = youtube_job_runner is None
    youtube_job_runner = youtube_job_runner or YouTubeTranscriptionJobRunner()
    instance = instance_name or _resolve_instance_name()
    instruction_store = instruction_store or InstructionStore(_resolve_instruction_path(instance))
    resolved_openai_api_key = openai_api_key if openai_api_key is not None else _resolve_openai_api_key(instance)
    openai_client = OpenAIClient(resolved_openai_api_key) if resolved_openai_api_key else None
    bot_identity = bot_identity or _resolve_bot_identity(api)
    user_memory_store = UserMemoryStore(instance)
    working_memory_store = WorkingMemoryStore(instance)
    working_memory_store.ensure()
    chat_state = ChatState(_teladi_call_state_path(instance), instance)
    process_registry = _InstanceProcessRegistry(instance)
    process_registry.cleanup_orphans()
    LOGGER.info(
        "Bot started instance=%s token_slot=%s bot_name=%s bot_username=%s. Waiting for Telegram updates.",
        instance,
        token_label,
        bot_identity.display_name or "unknown",
        bot_identity.mention or "unknown",
    )
    offset: int | None = None
    retry_delay = INITIAL_RETRY_DELAY_SECONDS

    try:
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
                        youtube_job_runner,
                        instance,
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
    finally:
        if owns_youtube_job_runner:
            youtube_job_runner.shutdown(wait=False)
        process_registry.cleanup_orphans()


def run_polling_many(configs: list[BotTokenConfig], instruction_path: str, instance_name: str) -> None:
    run_polling_all([InstanceRunConfig(instance_name, instruction_path, tuple(configs))])


def run_polling_all(instance_configs: list[InstanceRunConfig]) -> None:
    stop_event = threading.Event()
    threads: list[threading.Thread] = []
    youtube_job_runner = YouTubeTranscriptionJobRunner()
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
                    "youtube_job_runner": youtube_job_runner,
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
    finally:
        youtube_job_runner.shutdown(wait=False)


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


def _teladi_call_state_path(instance_name: str) -> Path:
    return _resolve_instances_dir() / instance_name / "data" / TELADI_CALL_STATE_FILENAME


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


def _send_untracked_message(api: TelegramAPI, chat_id: int, text: str) -> None:
    chunks = split_telegram_message(text)
    for index, chunk in enumerate(chunks, start=1):
        message_id = api.send_message(chat_id, chunk)
        LOGGER.info(
            "Outgoing Telegram message chat_id=%s message_id=%s type=text chars=%s chunk=%s/%s tracked=false",
            chat_id,
            message_id if message_id is not None else "unknown",
            len(chunk),
            index,
            len(chunks),
        )


def _copy_untracked_message(api: TelegramAPI, chat_id: int, from_chat_id: int, message_id: int) -> None:
    copied_message_id = api.copy_message(chat_id, from_chat_id, message_id)
    LOGGER.info(
        "Outgoing Telegram message chat_id=%s message_id=%s type=copy source_chat_id=%s source_message_id=%s tracked=false",
        chat_id,
        copied_message_id if copied_message_id is not None else "unknown",
        from_chat_id,
        message_id,
    )


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
    message: dict[str, Any],
    text: str,
    instructions: BotInstructions,
    openai_client: OpenAIClient,
) -> None:
    _maybe_send_depression_alert(api, chat_state, chat_id, message, instructions, text, chat_state.instance_name, "reply")
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


def _should_handle_youtube_transcript_request(chat_state: ChatState, chat_id: int, message: dict[str, Any], text: str) -> bool:
    sender_id = _sender_identifier(message)
    if _normalize_command(text) in YOUTUBE_TRANSCRIPT_COMMANDS:
        return True
    if sender_id and chat_state.has_pending_youtube_transcript_link(chat_id, sender_id) and _extract_youtube_url(text):
        return True
    return _has_youtube_transcript_intent(text)


def _handle_youtube_transcript_request(
    api: TelegramAPI,
    chat_state: ChatState,
    chat_id: int,
    message: dict[str, Any],
    text: str,
    user_memory_store: UserMemoryStore | None,
    user_memory: UserMemoryRecord | None,
    instructions: BotInstructions,
    openai_client: OpenAIClient | None,
    bot_identity: BotIdentity,
    first_contact: bool,
    working_memory_store: WorkingMemoryStore | None,
    instance_name: str,
) -> None:
    sender_id = _sender_identifier(message)
    url = _extract_youtube_url(text)
    if not url:
        if sender_id:
            chat_state.request_youtube_transcript_link(chat_id, sender_id)
        reply = "Schick mir bitte den YouTube-Link, den ich transkribieren soll."
        _send_tracked_message(api, chat_state, chat_id, reply)
        _record_user_memory(user_memory_store, user_memory, message, text, reply, instructions)
        return

    if sender_id:
        chat_state.clear_pending_youtube_transcript_link(chat_id, sender_id)

    try:
        api.send_chat_action(chat_id, "typing")
        transcribe_kwargs: dict[str, Any] = {"local_allowed": False}
        if instance_name:
            transcribe_kwargs["instance_name"] = instance_name
        transcript, source = transcribe_youtube_video(url, **transcribe_kwargs)
    except YouTubeTranscriptError as exc:
        if exc.needs_local_transcription:
            if sender_id:
                chat_state.request_youtube_local_options(chat_id, sender_id, url)
            reply = (
                "Keine YouTube-Untertitel gefunden. Lokale Transkription ist noetig.\n"
                "Moechtest Du den Text live ausgegeben haben?\n"
                f"Moechtest Du, dass das Ganze an dein LLM {instructions.openai_model} geht?\n"
                "Antworte z. B. mit: live ja, llm ja"
            )
            _send_tracked_message(api, chat_state, chat_id, reply)
            _record_user_memory(user_memory_store, user_memory, message, text, reply, instructions)
            return
        reply = f"YouTube-Transkript fehlgeschlagen: {exc}"
        _send_tracked_message(api, chat_state, chat_id, reply)
        _record_user_memory(user_memory_store, user_memory, message, text, reply, instructions)
        return
    except (TimeoutError, subprocess.TimeoutExpired) as exc:
        reply = f"YouTube-Transkript fehlgeschlagen: Timeout bei der Transkription ({exc})."
        _send_tracked_message(api, chat_state, chat_id, reply)
        _record_user_memory(user_memory_store, user_memory, message, text, reply, instructions)
        return

    if instructions.openai_enabled and openai_client is not None:
        _send_youtube_transcript_to_openai_pipeline(
            api,
            chat_state,
            chat_id,
            message,
            text,
            transcript,
            source,
            url,
            instructions,
            openai_client,
            user_memory_store,
            user_memory,
            bot_identity,
            first_contact,
            working_memory_store,
        )
        return

    if instructions.openai_enabled and openai_client is None:
        reply = _with_first_contact_intro(instructions.openai_missing_key, first_contact, bot_identity)
    else:
        reply = f"YouTube-Transkript ({source}):\n\n{transcript}"

    _send_tracked_message(api, chat_state, chat_id, reply)
    _record_user_memory(user_memory_store, user_memory, message, text, reply, instructions)


def _handle_pending_youtube_local_options(
    api: TelegramAPI,
    chat_state: ChatState,
    chat_id: int,
    message: dict[str, Any],
    text: str,
    user_memory_store: UserMemoryStore | None,
    user_memory: UserMemoryRecord | None,
    instructions: BotInstructions,
    openai_client: OpenAIClient | None,
    bot_identity: BotIdentity,
    first_contact: bool,
    working_memory_store: WorkingMemoryStore | None,
    youtube_job_runner: YouTubeTranscriptionJobRunner | None = None,
    instance_name: str = "",
) -> bool:
    sender_id = _sender_identifier(message)
    url = chat_state.get_pending_youtube_local_options(chat_id, sender_id)
    if not url:
        return False

    live_enabled, llm_enabled = _parse_youtube_local_options(text)
    if live_enabled is None or llm_enabled is None:
        reply = "Bitte antworte z. B. mit: live ja, llm ja"
        _send_tracked_message(api, chat_state, chat_id, reply)
        _record_user_memory(user_memory_store, user_memory, message, text, reply, instructions)
        return True

    chat_state.clear_pending_youtube_local_options(chat_id, sender_id)
    if youtube_job_runner is not None:
        youtube_job_runner.submit(
            lambda: _run_youtube_local_transcription_job(
                api,
                chat_state,
                chat_id,
                dict(message),
                text,
                url,
                live_enabled,
                llm_enabled,
                user_memory_store,
                user_memory,
                instructions,
                openai_client,
                bot_identity,
                first_contact,
                working_memory_store,
                instance_name,
            )
        )
        reply = "Lokale YouTube-Transkription gestartet. Ich melde mich, sobald sie fertig ist."
        if live_enabled:
            reply += " Live-Ausgabe ist aktiviert."
        _send_tracked_message(api, chat_state, chat_id, reply)
        _record_user_memory(user_memory_store, user_memory, message, text, reply, instructions)
        return True

    _run_youtube_local_transcription_job(
        api,
        chat_state,
        chat_id,
        message,
        text,
        url,
        live_enabled,
        llm_enabled,
        user_memory_store,
        user_memory,
        instructions,
        openai_client,
        bot_identity,
        first_contact,
        working_memory_store,
        instance_name,
    )
    return True


def _run_youtube_local_transcription_job(
    api: TelegramAPI,
    chat_state: ChatState,
    chat_id: int,
    message: dict[str, Any],
    text: str,
    url: str,
    live_enabled: bool,
    llm_enabled: bool,
    user_memory_store: UserMemoryStore | None,
    user_memory: UserMemoryRecord | None,
    instructions: BotInstructions,
    openai_client: OpenAIClient | None,
    bot_identity: BotIdentity,
    first_contact: bool,
    working_memory_store: WorkingMemoryStore | None,
    instance_name: str = "",
) -> None:
    try:
        api.send_chat_action(chat_id, "typing")
        live_callback = _build_youtube_live_callback(api, chat_state, chat_id) if live_enabled else None
        transcribe_kwargs: dict[str, Any] = {
            "local_allowed": True,
            "live_callback": live_callback,
        }
        if instance_name:
            transcribe_kwargs["instance_name"] = instance_name
        transcript, source = transcribe_youtube_video(url, **transcribe_kwargs)
    except TelegramAPIError as exc:
        LOGGER.warning("Telegram request failed during YouTube transcription: %s", exc)
        return
    except (YouTubeTranscriptError, TimeoutError, subprocess.TimeoutExpired) as exc:
        reply = f"YouTube-Transkript fehlgeschlagen: {exc}"
        try:
            _send_tracked_message(api, chat_state, chat_id, reply)
        except TelegramAPIError as send_exc:
            LOGGER.warning("Telegram request failed while reporting YouTube transcription error: %s", send_exc)
        _record_user_memory(user_memory_store, user_memory, message, text, reply, instructions)
        return

    if llm_enabled and instructions.openai_enabled and openai_client is not None:
        _send_youtube_transcript_to_openai_pipeline(
            api,
            chat_state,
            chat_id,
            message,
            text,
            transcript,
            source,
            url,
            instructions,
            openai_client,
            user_memory_store,
            user_memory,
            bot_identity,
            first_contact,
            working_memory_store,
        )
        return

    if llm_enabled and instructions.openai_enabled and openai_client is None:
        reply = _with_first_contact_intro(instructions.openai_missing_key, first_contact, bot_identity)
    elif live_enabled:
        reply = "Lokale YouTube-Transkription abgeschlossen."
    else:
        reply = f"YouTube-Transkript ({source}):\n\n{transcript}"
    try:
        _send_tracked_message(api, chat_state, chat_id, reply)
    except TelegramAPIError as exc:
        LOGGER.warning("Telegram request failed while sending YouTube transcription completion: %s", exc)
    _record_user_memory(user_memory_store, user_memory, message, text, reply, instructions)


def _parse_youtube_local_options(text: str) -> tuple[bool | None, bool | None]:
    normalized = text.casefold()
    yes_words = r"ja|yes|jup|ok|okay|y"
    no_words = r"nein|no|n|nee"
    live_match = re.search(rf"live\s+({yes_words}|{no_words})", normalized)
    llm_match = re.search(rf"llm\s+({yes_words}|{no_words})", normalized)
    if live_match and llm_match:
        return _yes_no_value(live_match.group(1)), _yes_no_value(llm_match.group(1))
    tokens = re.findall(rf"\b({yes_words}|{no_words})\b", normalized)
    if len(tokens) >= 2:
        return _yes_no_value(tokens[0]), _yes_no_value(tokens[1])
    return None, None


def _yes_no_value(value: str) -> bool:
    return value.casefold() in {"ja", "yes", "jup", "ok", "okay", "y"}


def _build_youtube_live_callback(api: TelegramAPI, chat_state: ChatState, chat_id: int):
    buffer: list[str] = []
    disabled = False

    def emit(text: str, force: bool = False) -> None:
        nonlocal disabled
        if disabled:
            return
        buffer.extend(re.findall(r"\S+", text))
        while len(buffer) >= YOUTUBE_LIVE_CHUNK_WORDS or (force and buffer):
            count = min(len(buffer), YOUTUBE_LIVE_CHUNK_WORDS)
            chunk_words = buffer[:count]
            del buffer[:count]
            try:
                _send_tracked_message(api, chat_state, chat_id, " ".join(chunk_words))
            except TelegramAPIError as exc:
                disabled = True
                LOGGER.warning("Telegram request failed while sending YouTube live output: %s", exc)
                buffer.clear()
                return

    return emit


def _send_youtube_transcript_to_openai_pipeline(
    api: TelegramAPI,
    chat_state: ChatState,
    chat_id: int,
    message: dict[str, Any],
    user_text: str,
    transcript: str,
    source: str,
    url: str,
    instructions: BotInstructions,
    openai_client: OpenAIClient,
    user_memory_store: UserMemoryStore | None,
    user_memory: UserMemoryRecord | None,
    bot_identity: BotIdentity,
    first_contact: bool,
    working_memory_store: WorkingMemoryStore | None,
) -> None:
    pipeline_text = _build_youtube_pipeline_text(user_text, transcript, source, url)
    try:
        api.send_chat_action(chat_id, "typing")
        working_memory = _prepare_working_memory(working_memory_store, pipeline_text)
        openai_response = openai_client.create_reply(
            _build_openai_user_input(
                message,
                pipeline_text,
                user_memory.prompt_text if user_memory else "",
                bot_identity,
                working_memory.prompt_text if working_memory else "",
            ),
            instructions,
            chat_state.get_previous_response_id(chat_id),
        )
    except OpenAIAPIError as exc:
        LOGGER.error("OpenAI request failed after YouTube transcript: %s", exc)
        reply = _with_first_contact_intro(instructions.openai_error, first_contact, bot_identity)
        try:
            _send_tracked_message(api, chat_state, chat_id, reply)
        except TelegramAPIError as send_exc:
            LOGGER.warning("Telegram request failed while reporting OpenAI transcript error: %s", send_exc)
        _record_user_memory(user_memory_store, user_memory, message, user_text, reply, instructions)
        return
    except TelegramAPIError as exc:
        LOGGER.warning("Telegram request failed during YouTube transcript OpenAI pipeline: %s", exc)
        return

    chat_state.set_previous_response_id(chat_id, openai_response.response_id)
    reply = _with_first_contact_intro(openai_response.text, first_contact, bot_identity)
    try:
        _send_openai_response(api, chat_state, chat_id, message, reply, instructions, openai_client)
    except TelegramAPIError as exc:
        LOGGER.warning("Telegram request failed while sending YouTube transcript response: %s", exc)
    _record_user_memory(user_memory_store, user_memory, message, user_text, reply, instructions)


def _build_youtube_pipeline_text(user_text: str, transcript: str, source: str, url: str) -> str:
    clipped_transcript = transcript
    if len(clipped_transcript) > YOUTUBE_TRANSCRIPT_MAX_PIPELINE_CHARS:
        clipped_transcript = clipped_transcript[:YOUTUBE_TRANSCRIPT_MAX_PIPELINE_CHARS].rstrip() + "\n[Transkript gekuerzt]"
    return (
        f"{user_text.strip()}\n\n"
        "YouTube-Transkript:\n"
        f"- Quelle: {url}\n"
        f"- Transkriptquelle: {source}\n"
        f"{clipped_transcript}"
    ).strip()


class YouTubeTranscriptError(RuntimeError):
    """Raised when a YouTube transcript cannot be produced locally."""

    def __init__(self, message: str, *, needs_local_transcription: bool = False) -> None:
        super().__init__(message)
        self.needs_local_transcription = needs_local_transcription


def transcribe_youtube_video(
    url: str,
    local_allowed: bool = True,
    live_callback=None,
    instance_name: str = "",
) -> tuple[str, str]:
    if shutil.which("yt-dlp") is None:
        raise YouTubeTranscriptError("yt-dlp ist nicht installiert.")
    normalized_url = _validated_youtube_url(url)

    with tempfile.TemporaryDirectory(prefix="telegram-bot-youtube-") as directory:
        workdir = Path(directory)
        subtitle_text = _download_youtube_subtitles(normalized_url, workdir, instance_name=instance_name)
        if subtitle_text:
            return subtitle_text, "YouTube-Untertitel"
        if not local_allowed:
            raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True)
        whisper_text = _transcribe_youtube_audio_with_whisper(
            normalized_url,
            workdir,
            live_callback=live_callback,
            instance_name=instance_name,
        )
        if whisper_text:
            return whisper_text, "lokales Whisper"
    raise YouTubeTranscriptError("kein Transkript erzeugt.")


def _extract_youtube_url(text: str) -> str:
    parts = text.split(maxsplit=1)
    search_text = parts[1] if len(parts) >= 2 and _normalize_command(text) in YOUTUBE_TRANSCRIPT_COMMANDS else text
    for candidate in re.findall(r"https?://\S+", search_text):
        try:
            return _validated_youtube_url(candidate.rstrip(".,;)>]\"'"))
        except YouTubeTranscriptError:
            continue
    return ""


def _has_youtube_transcript_intent(text: str) -> bool:
    normalized = text.casefold()
    mentions_youtube = bool(re.search(r"\byoutube\b|youtu\.be|youtube\.com", normalized))
    mentions_transcript = bool(
        re.search(
            r"transkrib|transcript|transkript|untertitel|abschrift|verschriftlich|mitschrift",
            normalized,
        )
    )
    return mentions_youtube and mentions_transcript


def _validated_youtube_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    host = parsed.netloc.casefold().removeprefix("www.")
    if parsed.scheme not in {"http", "https"} or host not in {"youtube.com", "m.youtube.com", "youtu.be", "youtube-nocookie.com"}:
        raise YouTubeTranscriptError("bitte eine gueltige YouTube-URL angeben.")
    return urllib.parse.urlunparse(parsed)


def _download_youtube_subtitles(url: str, workdir: Path, instance_name: str = "") -> str:
    result = _run_local_command(
        [
            "yt-dlp",
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            "en.*,de.*",
            "--convert-subs",
            "srt",
            "-o",
            "%(id)s.%(ext)s",
            url,
        ],
        workdir,
        YOUTUBE_TRANSCRIPT_TIMEOUT_SECONDS,
        instance_name=instance_name,
    )
    if result.returncode != 0 and not list(workdir.glob("*.srt")):
        LOGGER.debug("yt-dlp subtitle download failed: %s", result.stderr.strip())
    return _read_first_srt_as_text(workdir)


def _transcribe_youtube_audio_with_whisper(
    url: str,
    workdir: Path,
    live_callback=None,
    instance_name: str = "",
) -> str:
    audio_result = _run_local_command(
        ["yt-dlp", "-x", "--audio-format", "mp3", "-o", "youtube-audio.%(ext)s", url],
        workdir,
        YOUTUBE_TRANSCRIPT_TIMEOUT_SECONDS,
        instance_name=instance_name,
    )
    if audio_result.returncode != 0:
        raise YouTubeTranscriptError(f"Audio konnte nicht geladen werden: {_short_process_error(audio_result)}")

    audio_files = sorted(workdir.glob("youtube-audio*.mp3"))
    if not audio_files:
        raise YouTubeTranscriptError("Audio wurde nicht als MP3 erzeugt.")

    if _has_python_module("faster_whisper"):
        return _transcribe_audio_with_faster_whisper(
            audio_files[0],
            workdir,
            live_callback=live_callback,
            instance_name=instance_name,
        )
    if shutil.which("whisper") is None:
        raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden und weder faster-whisper noch whisper ist installiert.")
    return _transcribe_audio_with_openai_whisper_cli(audio_files[0], workdir, instance_name=instance_name)


def _transcribe_audio_with_faster_whisper(
    audio_path: Path,
    workdir: Path,
    live_callback=None,
    instance_name: str = "",
) -> str:
    return _transcribe_audio_with_faster_whisper_model(
        audio_path,
        workdir,
        YOUTUBE_WHISPER_MODEL,
        live_callback=live_callback,
        instance_name=instance_name,
    )


def _transcribe_audio_with_faster_whisper_model(
    audio_path: Path,
    workdir: Path,
    model_name: str,
    live_callback=None,
    instance_name: str = "",
) -> str:
    code = """
import sys
from pathlib import Path
from faster_whisper import WhisperModel

audio_path = Path(sys.argv[1])
model_name = sys.argv[2]
compute_type = sys.argv[3]
cpu_threads = int(sys.argv[4])
model = WhisperModel(model_name, device="cpu", compute_type=compute_type, cpu_threads=cpu_threads, num_workers=1)
segments, _ = model.transcribe(str(audio_path))
for segment in segments:
    text = segment.text.strip()
    if text:
        print(text, flush=True)
"""
    command = [
        sys.executable,
        "-c",
        code,
        str(audio_path),
        model_name,
        YOUTUBE_FASTER_WHISPER_COMPUTE_TYPE,
        str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
    ]
    result = _run_local_command_streaming(
        command,
        workdir,
        YOUTUBE_WHISPER_TIMEOUT_SECONDS,
        line_callback=live_callback,
        instance_name=instance_name,
    )
    if result.returncode != 0:
        raise YouTubeTranscriptError(f"faster-whisper konnte nicht transkribieren: {_short_process_error(result)}")
    text = result.stdout.strip()
    if not text:
        raise YouTubeTranscriptError("faster-whisper hat kein Transkript erzeugt.")
    if live_callback is not None:
        live_callback("", force=True)
    return text


def _transcribe_audio_with_openai_whisper_cli(audio_path: Path, workdir: Path, instance_name: str = "") -> str:
    whisper_result = _run_local_command(
        [
            "whisper",
            str(audio_path),
            "--model",
            YOUTUBE_WHISPER_MODEL,
            "--language",
            "English",
            "--output_format",
            "srt",
            "--output_dir",
            str(workdir),
        ],
        workdir,
        YOUTUBE_WHISPER_TIMEOUT_SECONDS,
        instance_name=instance_name,
    )
    if whisper_result.returncode != 0:
        raise YouTubeTranscriptError(f"Whisper konnte nicht transkribieren: {_short_process_error(whisper_result)}")
    return _read_first_srt_as_text(workdir)


def _has_python_module(module_name: str) -> bool:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _run_local_command(
    command: list[str],
    workdir: Path,
    timeout: int,
    instance_name: str = "",
) -> subprocess.CompletedProcess[str]:
    registry = _InstanceProcessRegistry(instance_name)
    process: subprocess.Popen[str] | None = None
    env = os.environ.copy()
    env.update(
        {
            "OMP_NUM_THREADS": str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
            "OPENBLAS_NUM_THREADS": str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
            "MKL_NUM_THREADS": str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
            "NUMEXPR_NUM_THREADS": str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
            "VECLIB_MAXIMUM_THREADS": str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
        }
    )
    try:
        process = subprocess.Popen(
            _lowest_priority_command(command),
            cwd=workdir,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            start_new_session=True,
        )
        registry.register(process.pid)
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(command, process.returncode or 0, stdout, stderr)
    except TimeoutError as exc:
        raise YouTubeTranscriptError(f"lokaler Prozess lief in ein Timeout: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(process)
        raise YouTubeTranscriptError(f"lokaler Prozess lief laenger als {timeout} Sekunden.") from exc
    except OSError as exc:
        raise YouTubeTranscriptError(f"lokaler Prozess konnte nicht gestartet werden: {exc}") from exc
    finally:
        if process is not None:
            registry.unregister(process.pid)


def _run_local_command_streaming(
    command: list[str],
    workdir: Path,
    timeout: int,
    line_callback=None,
    instance_name: str = "",
) -> subprocess.CompletedProcess[str]:
    registry = _InstanceProcessRegistry(instance_name)
    stdout_lines: list[str] = []
    stderr = ""
    start = time.monotonic()
    process: subprocess.Popen[str] | None = None
    try:
        env = os.environ.copy()
        env.update(
            {
                "OMP_NUM_THREADS": str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
                "OPENBLAS_NUM_THREADS": str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
                "MKL_NUM_THREADS": str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
                "NUMEXPR_NUM_THREADS": str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
                "VECLIB_MAXIMUM_THREADS": str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
            }
        )
        process = subprocess.Popen(
            _lowest_priority_command(command),
            cwd=workdir,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            start_new_session=True,
        )
        registry.register(process.pid)
        assert process.stdout is not None
        while True:
            if time.monotonic() - start > timeout:
                _terminate_process_group(process)
                _, stderr = process.communicate()
                raise YouTubeTranscriptError(f"lokaler Prozess lief laenger als {timeout} Sekunden.")
            ready, _, _ = select.select([process.stdout], [], [], 0.1)
            if ready:
                line = process.stdout.readline()
                if line:
                    stdout_lines.append(line)
                    if line_callback is not None:
                        line_callback(line)
                    continue
            if process.poll() is not None:
                break
        remaining_stdout, stderr = process.communicate(timeout=5)
        if remaining_stdout:
            stdout_lines.append(remaining_stdout)
            if line_callback is not None:
                for line in remaining_stdout.splitlines():
                    line_callback(line)
    except subprocess.TimeoutExpired:
        _terminate_process_group(process)
        _, stderr = process.communicate()
        raise YouTubeTranscriptError(f"lokaler Prozess lief laenger als {timeout} Sekunden.")
    finally:
        if process is not None:
            registry.unregister(process.pid)
    returncode = process.returncode if process is not None and process.returncode is not None else 0
    return subprocess.CompletedProcess(command, returncode, "".join(stdout_lines), stderr)


def _terminate_process_group(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.pid <= 0:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        LOGGER.debug("Failed to terminate process group %s with SIGTERM.", process.pid)
        return
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        except OSError:
            return
        time.sleep(0.1)
    with suppress(ProcessLookupError, OSError):
        os.killpg(process.pid, signal.SIGKILL)


def _lowest_priority_command(command: list[str]) -> list[str]:
    wrapped = list(command)
    if shutil.which("ionice") is not None:
        wrapped = ["ionice", "-c", "3", *wrapped]
    if shutil.which("nice") is not None:
        wrapped = ["nice", "-n", str(YOUTUBE_TRANSCRIPT_NICE_LEVEL), *wrapped]
    return wrapped


def _read_first_srt_as_text(workdir: Path) -> str:
    for path in sorted(workdir.glob("*.srt")):
        text = _srt_to_plain_text(path.read_text(encoding="utf-8", errors="replace"))
        if text:
            return text
    return ""


def _srt_to_plain_text(srt_text: str) -> str:
    lines: list[str] = []
    previous = ""
    for raw_line in srt_text.splitlines():
        line = raw_line.strip()
        if not line or line.isdigit() or "-->" in line:
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line or line == previous:
            continue
        lines.append(line)
        previous = line
    return "\n".join(lines).strip()


def _short_process_error(result: subprocess.CompletedProcess[str]) -> str:
    text = (result.stderr or result.stdout or "").strip()
    if not text:
        return f"Exitcode {result.returncode}"
    return text[-500:]


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

        message_ids = chat_state.pop_recent_messages(chat_id, count)
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


def _handle_codex_command(
    api: TelegramAPI,
    chat_state: ChatState,
    chat_id: int,
    message: dict[str, Any],
    instructions: BotInstructions,
    text: str,
    first_contact: bool,
    bot_identity: BotIdentity,
) -> bool:
    if not instructions.codex_enabled:
        return False
    if _normalize_command(text) != "/codex":
        return False

    sender_id = _sender_identifier(message)
    if not sender_id or not _is_allowed_codex_sender(sender_id, instructions):
        reply = _with_first_contact_intro(instructions.codex_unauthorized, first_contact, bot_identity)
        _send_tracked_message(api, chat_state, chat_id, reply)
        return True

    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        reply = _with_first_contact_intro(instructions.codex_usage, first_contact, bot_identity)
        _send_tracked_message(api, chat_state, chat_id, reply)
        return True

    prompt = parts[1].strip()
    codex_command = "codex"
    if shutil.which(codex_command) is None:
        reply = _with_first_contact_intro(instructions.codex_not_found, first_contact, bot_identity)
        _send_tracked_message(api, chat_state, chat_id, reply)
        return True

    try:
        api.send_chat_action(chat_id, "typing")
        result = subprocess.run(
            [codex_command, "exec", prompt],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=instructions.codex_timeout_seconds,
            check=False,
        )
    except TimeoutError as exc:
        LOGGER.error("Codex request timed out: %s", exc)
        reply = _with_first_contact_intro(instructions.codex_error.format(error=str(exc)), first_contact, bot_identity)
        _send_tracked_message(api, chat_state, chat_id, reply)
        return True
    except subprocess.TimeoutExpired as exc:
        LOGGER.error("Codex request timed out: %s", exc)
        reply = _with_first_contact_intro(instructions.codex_error.format(error=f"Timeout nach {instructions.codex_timeout_seconds}s"), first_contact, bot_identity)
        _send_tracked_message(api, chat_state, chat_id, reply)
        return True
    except OSError as exc:
        LOGGER.error("Codex request could not be started: %s", exc)
        reply = _with_first_contact_intro(instructions.codex_error.format(error=str(exc)), first_contact, bot_identity)
        _send_tracked_message(api, chat_state, chat_id, reply)
        return True

    output = (result.stdout or "").strip() or (result.stderr or "").strip()
    if result.returncode != 0:
        error = _short_process_error(result)
        LOGGER.error("Codex CLI failed with exit code %s: %s", result.returncode, error)
        reply = _with_first_contact_intro(instructions.codex_error.format(error=error), first_contact, bot_identity)
        _send_tracked_message(api, chat_state, chat_id, reply)
        return True
    if not output:
        reply = _with_first_contact_intro(instructions.codex_empty, first_contact, bot_identity)
        _send_tracked_message(api, chat_state, chat_id, reply)
        return True

    reply = _with_first_contact_intro(output, first_contact, bot_identity)
    _send_tracked_message(api, chat_state, chat_id, reply)
    return True


def _is_allowed_codex_sender(sender_id: str, instructions: BotInstructions) -> bool:
    allowed_sender_ids = {value.strip() for value in instructions.codex_allowed_sender_ids if value.strip()}
    return sender_id in allowed_sender_ids


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
