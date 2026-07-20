import base64
import io
import json
import os
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from TeeBotus.bot import (
    BotIdentity,
    BotTokenConfig,
    ChatState,
    InstanceRunConfig,
    _InstanceProcessRegistry,
    TELADI_EMERGENCY_CHAT_ID,
    TELEGRAM_MESSAGE_CHUNK_SIZE,
    TelegramAPI,
    TelegramAPIError,
    TelegramNetworkError,
    UserMemoryRecord,
    WorkingMemoryStore,
    _build_openai_user_input,
    _bot_token_config_error,
    build_telegram_runtime_context,
    _discover_instance_names,
    _duplicate_telegram_token_error,
    _downloaded_file_name,
    _encode_multipart_form_data,
    _instance_env_key,
    _lowest_priority_command,
    _load_dotenv,
    _prepare_user_memory,
    _prepare_weather_context,
    _parse_youtube_local_options_from_llm_response,
    _parse_youtube_local_options,
    _record_user_memory,
    _resolve_bot_token_configs,
    _resolve_instruction_path,
    _resolve_openai_api_key,
    _resolve_openai_api_keys,
    _load_runtime_config_defaults,
    _read_runtime_config_defaults,
    _resolve_telegram_token,
    _resolve_telegram_tokens,
    _is_telegram_getupdates_conflict,
    _short_process_error,
    _srt_to_plain_text,
    _transcribe_audio_with_faster_whisper_model,
    _run_youtube_local_transcription_job,
    _transcribe_voice_audio,
    _transcription_process_health_error,
    contains_sources,
    count_words,
    handle_update,
    run_polling,
    split_telegram_message,
    transcribe_youtube_video,
)
from TeeBotus import __version__
from TeeBotus.adapters.telegram_runtime import (
    _expand_telegram_text_actions,
    _handle_update_with_runtime_context,
    _with_telegram_reply_context,
)
from TeeBotus.instructions import BotInstructions
from TeeBotus.openai_client import OpenAIAPIError, OpenAIResponse, OpenAIVoice
from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, INSTANCE_STATE_ACCOUNT_ID, StaticSecretProvider, telegram_identity_key
from TeeBotus.runtime.message_tracking import MessageTracker
from TeeBotus.runtime.state import RuntimeStateStore


class FakeAPI:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[int, str]] = []
        self.chat_actions: list[tuple[int, str]] = []
        self.deleted_messages: list[tuple[int, int]] = []
        self.copied_messages: list[tuple[int, int, int]] = []
        self.sent_voices: list[tuple[int, bytes, str, str]] = []
        self.callback_answers: list[tuple[str, str]] = []
        self.file_paths: dict[str, str] = {}
        self.file_data: dict[str, bytes] = {}
        self.file_path_requests: list[str] = []
        self.download_requests: list[str] = []
        self.profile_photo_file_ids: dict[int, str | None] = {}
        self.profile_photo_requests: list[int] = []
        self.next_message_id = 100

    def send_message(self, chat_id: int, text: str) -> int:
        self.sent_messages.append((chat_id, text))
        self.next_message_id += 1
        return self.next_message_id

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        self.callback_answers.append((callback_query_id, text))

    def send_chat_action(self, chat_id: int, action: str) -> None:
        self.chat_actions.append((chat_id, action))

    def delete_message(self, chat_id: int, message_id: int) -> None:
        self.deleted_messages.append((chat_id, message_id))

    def copy_message(self, chat_id: int, from_chat_id: int, message_id: int) -> int:
        self.copied_messages.append((chat_id, from_chat_id, message_id))
        self.next_message_id += 1
        return self.next_message_id

    def send_voice(self, chat_id: int, audio: bytes, filename: str, content_type: str) -> int:
        self.sent_voices.append((chat_id, audio, filename, content_type))
        self.next_message_id += 1
        return self.next_message_id

    def get_file_path(self, file_id: str) -> str:
        self.file_path_requests.append(file_id)
        return self.file_paths[file_id]

    def get_user_profile_photo_file_id(self, user_id: int) -> str | None:
        self.profile_photo_requests.append(user_id)
        return self.profile_photo_file_ids.get(user_id)

    def download_file(self, file_path: str) -> bytes:
        self.download_requests.append(file_path)
        return self.file_data.get(file_path, b"voice-audio")


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.previous_response_ids: list[str | None] = []
        self.reply_inputs: list[str] = []
        self.voice_texts: list[str] = []
        self.voice_instruction_texts: list[str] = []
        self.voice_names: list[str] = []
        self.transcribed_audios: list[tuple[bytes, str]] = []
        self.transcription_models: list[str | None] = []
        self.transcription_text = "Was ist los?"
        self.transcription_texts: list[str] = []

    def create_reply(self, user_text, instructions, previous_response_id=None):
        self.previous_response_ids.append(previous_response_id)
        self.reply_inputs.append(user_text)
        message_text = user_text.rsplit("\nNachricht:\n", maxsplit=1)[-1]
        return OpenAIResponse(text=f"AI: {message_text}", response_id="resp_123", service_tier="flex")

    def create_voice(self, text, instructions):
        self.voice_texts.append(text)
        self.voice_instruction_texts.append(instructions.openai_voice_instructions)
        self.voice_names.append(instructions.openai_voice)
        return OpenAIVoice(audio=b"voice-bytes", filename="voice.ogg", content_type="audio/ogg")

    def transcribe_audio(self, audio, filename, instructions, model=None):
        self.transcribed_audios.append((audio, filename))
        self.transcription_models.append(model)
        if self.transcription_texts:
            return self.transcription_texts.pop(0)
        return self.transcription_text


class FailingAccountMemoryStore:
    instance_name = "Depressionsbot"

    def get_account_for_identity(self, *args, **kwargs):
        raise AccountStoreError("account memory backend unavailable")

    def resolve_or_create_account(self, *args, **kwargs):
        raise AccountStoreError("account memory backend unavailable")

    def append_structured_memory_entry(self, *args, **kwargs):
        raise AccountStoreError("account memory backend unavailable")


class SequenceOpenAIClient(FakeOpenAIClient):
    def __init__(self, replies: list[str]) -> None:
        super().__init__()
        self.replies = replies

    def create_reply(self, user_text, instructions, previous_response_id=None):
        self.previous_response_ids.append(previous_response_id)
        self.reply_inputs.append(user_text)
        return OpenAIResponse(text=self.replies.pop(0), response_id="resp_seq", service_tier="flex")


class LongReplyOpenAIClient:
    def create_reply(self, user_text, instructions, previous_response_id=None):
        return OpenAIResponse(text=("Absatz.\n\n" * 900), response_id="resp_long", service_tier="flex")


class FailingOpenAIClient:
    def create_reply(self, user_text, instructions, previous_response_id=None):
        raise OpenAIAPIError("short failure")


class FakeJobRunner:
    def __init__(self) -> None:
        self.jobs = []

    def submit(self, callback):
        self.jobs.append(callback)


class FakeInstructionStore:
    def get(self):
        from TeeBotus.instructions import BotInstructions

        return BotInstructions()


class FlakyPollingAPI(FakeAPI):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def get_updates(self, offset, timeout=50):
        self.calls += 1
        if self.calls == 1:
            raise TelegramNetworkError("Telegram network error: reset")
        raise KeyboardInterrupt


class OneUpdatePollingAPI(FakeAPI):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def get_updates(self, offset, timeout=50):
        self.calls += 1
        if self.calls == 1:
            return [{"update_id": 7, "message": {"message_id": 1, "text": "/ping", "chat": {"id": 123}, "from": {"id": 456}}}]
        raise KeyboardInterrupt


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_user_memory_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def account_memory_store(directory: str, instance_name: str = "Depressionsbot") -> AccountStore:
    return AccountStore(
        Path(directory) / "instances" / instance_name / "data" / "accounts",
        instance_name,
        secret_provider=StaticSecretProvider(b"t" * 32),
    )


def account_memory_id(store: AccountStore, sender_id: int | str) -> str:
    account_id = store.get_account_for_identity(telegram_identity_key(sender_id))
    assert account_id is not None
    return account_id


def account_memory_dir(store: AccountStore, sender_id: int | str) -> Path:
    return store.account_dir(account_memory_id(store, sender_id))


def read_account_memory_entries(store: AccountStore, sender_id: int | str) -> list[dict]:
    return store.read_memory_entries(account_memory_id(store, sender_id))


def read_account_memory_index(store: AccountStore, sender_id: int | str) -> dict:
    return store.read_memory_index(account_memory_id(store, sender_id))


class BotTests(unittest.TestCase):
    AVATAR_PNG = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR4nGP8z8BQDwAFgwJ/lwQ+0gAAAABJRU5ErkJggg=="
    )

    def test_default_instruction_path_uses_bote_der_wahrheit_instance(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(_resolve_instruction_path(), "instances/Bote_der_Wahrheit/Bot_Verhalten.md")

    def test_default_instruction_path_prefers_teebotus_instances_dir(self) -> None:
        with patch.dict("os.environ", {"TEEBOTUS_INSTANCES_DIR": "/tmp/teebotus-instances"}, clear=True):
            self.assertEqual(_resolve_instruction_path(), "/tmp/teebotus-instances/Bote_der_Wahrheit/Bot_Verhalten.md")

    def test_pre_account_sender_memory_payload_is_not_touched_by_account_store_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            memory_path = Path(directory) / "instances" / "Depressionsbot" / "data" / "accounts" / "pre_account_sender_memory" / "456" / "User_Memory_Index.json"
            memory_path.parent.mkdir(parents=True, exist_ok=True)
            memory_path.write_text(
                json.dumps({"schema_version": 1, "sender_id": "456", "profile": {}, "memories": [], "memory_index": {}, "recent_memory_ids": []}),
                encoding="utf-8",
            )
            original_payload = memory_path.read_bytes()

            store = account_memory_store(directory)
            message = {"chat": {"id": 123}, "from": {"id": 456, "first_name": "Ada"}}
            api = FakeAPI()
            instructions = BotInstructions(user_memory_enabled=True)

            record = _prepare_user_memory(store, message, instructions, "Hallo", api)

            self.assertIsNotNone(record)
            self.assertEqual(memory_path.read_bytes(), original_payload)
            self.assertEqual(api.sent_messages, [])

    def test_prepare_user_memory_records_activity_profile_when_proactive_instance_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = account_memory_store(directory)
            message = {"message_id": 7, "text": "Hallo", "chat": {"id": 123, "type": "private"}, "from": {"id": 456, "first_name": "Ada"}}
            instructions = BotInstructions(user_memory_enabled=True)

            with patch.dict(os.environ, {"TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot"}, clear=True):
                record = _prepare_user_memory(store, message, instructions, "Hallo", None)

            self.assertIsNotNone(record)
            account_id = store.get_account_for_identity("telegram:user:456")
            self.assertIsNotNone(account_id)
            observations = store.read_agent_state(account_id or "")["activity_profile"]["observations"]
            self.assertEqual(len(observations), 1)
            self.assertEqual(observations[0]["channel"], "telegram")
            self.assertEqual(observations[0]["text_length"], len("Hallo"))

    def test_prepare_user_memory_handles_crypto_errors_without_crashing(self) -> None:
        message = {"chat": {"id": 123}, "from": {"id": 456, "first_name": "Ada"}}
        api = FakeAPI()
        instructions = BotInstructions(user_memory_enabled=True)

        with self.assertLogs("TeeBotus", level="ERROR"):
            record = _prepare_user_memory(
                FailingAccountMemoryStore(),
                message,
                instructions,
                "Hallo",
                api,
            )

        self.assertIsNone(record)
        self.assertEqual(api.sent_messages, [(123, instructions.user_memory_error)])

    def test_logger_status_auth_silences_legacy_telegram_memory_errors_before_secret(self) -> None:
        message = {
            "message": {
                "message_id": 1,
                "text": "/help",
                "chat": {"id": 123, "type": "private"},
                "from": {"id": 456, "first_name": "Ada"},
            }
        }
        api = FakeAPI()
        instructions = BotInstructions(user_memory_enabled=True)
        store = FailingAccountMemoryStore()
        store.instance_name = "TeeBotus_Logger"

        with patch.dict(os.environ, {"TEEBOTUS_STATUS_AUTH_CODE": "18hhGfuu3"}, clear=True):
            handle_update(api, message, instructions, None, ChatState(), store)

        self.assertEqual(api.sent_messages, [])

    def test_logger_status_auth_silences_runtime_context_memory_errors_before_secret(self) -> None:
        message = {
            "message": {
                "message_id": 1,
                "text": "/help",
                "chat": {"id": 123, "type": "private"},
                "from": {"id": 456, "first_name": "Ada"},
            }
        }
        api = FakeAPI()
        store = FailingAccountMemoryStore()
        store.instance_name = "TeeBotus_Logger"
        context = SimpleNamespace(
            instance_name="TeeBotus_Logger",
            adapter_slot=1,
            api=api,
            account_store=store,
        )

        with patch.dict(os.environ, {"TEEBOTUS_STATUS_AUTH_CODE": "18hhGfuu3"}, clear=True):
            handled = _handle_update_with_runtime_context(context, message, ChatState())

        self.assertTrue(handled)
        self.assertEqual(api.sent_messages, [])

    def test_logger_status_auth_pre_gate_authorizes_secret_in_legacy_telegram_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            store = account_memory_store(directory, instance_name="TeeBotus_Logger")
            instructions = BotInstructions(user_memory_enabled=True)
            message = {
                "message": {
                    "message_id": 1,
                    "text": "tl 18hhGfuu3 bitte freischalten",
                    "chat": {"id": 123, "type": "private"},
                    "from": {"id": 456, "first_name": "Ada"},
                }
            }

            with patch.dict(os.environ, {"TEEBOTUS_STATUS_AUTH_CODE": "18hhGfuu3"}, clear=True):
                handle_update(api, message, instructions, None, ChatState(), store)

            self.assertEqual(api.sent_messages, [("123", "Statuszugang aktiviert.")])
            account_id = store.get_account_for_identity(telegram_identity_key(456))
            self.assertIsNotNone(account_id)
            self.assertTrue(store.read_status_auth_state(account_id or "").get("authorized"))

    def test_record_user_memory_handles_crypto_errors_without_crashing(self) -> None:
        record = UserMemoryRecord(
            sender_id="456",
            path=Path("instances/Demo/data/accounts/accounts/" + ("a" * 128) + "/User_Memory_Index.json"),
            prompt_text="",
            selected_ids=(),
        )
        api = FakeAPI()
        instructions = BotInstructions(user_memory_enabled=True)

        with self.assertLogs("TeeBotus", level="ERROR"):
            _record_user_memory(
                FailingAccountMemoryStore(),
                record,
                {"chat": {"id": 123}, "from": {"id": 456}},
                "Hallo",
                "Antwort",
                instructions,
                api,
            )
        self.assertEqual(api.sent_messages, [(123, instructions.user_memory_error)])

    def test_record_user_memory_uses_explicit_account_id_not_legacy_path_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = account_memory_store(directory)
            account_id = store.resolve_or_create_account("telegram:user:456", display_label="Ada")
            misleading_path_account_id = "b" * 128
            record = UserMemoryRecord(
                sender_id="456",
                path=Path("instances/Demo/data/accounts/accounts") / misleading_path_account_id / "User_Memory_Index.json",
                prompt_text="",
                selected_ids=(),
                account_id=account_id,
            )
            instructions = BotInstructions(user_memory_enabled=True)

            _record_user_memory(
                store,
                record,
                {"message_id": 9, "chat": {"id": 123, "type": "private"}, "from": {"id": 456, "first_name": "Ada"}},
                "Hallo",
                "Antwort",
                instructions,
            )

            self.assertEqual(len(store.read_memory_entries(account_id)), 1)
            self.assertEqual(store.read_memory_entries(misleading_path_account_id), [])

    def test_telegram_request_timeout_is_network_error(self) -> None:
        api = TelegramAPI("123:test-token")

        with patch("TeeBotus.bot.urllib.request.urlopen", side_effect=TimeoutError("read timed out")):
            with self.assertRaises(TelegramNetworkError):
                api.request("getUpdates", {})

    def test_telegram_remote_disconnect_is_network_error(self) -> None:
        import http.client

        api = TelegramAPI("123:test-token")

        with patch(
            "TeeBotus.bot.urllib.request.urlopen",
            side_effect=http.client.RemoteDisconnected("Remote end closed connection without response"),
        ):
            with self.assertRaises(TelegramNetworkError):
                api.request("getUpdates", {})

    def test_telegram_http_rate_limit_exposes_retry_after(self) -> None:
        import urllib.error

        api = TelegramAPI("123:test-token")
        response = io.BytesIO(
            b'{"ok":false,"error_code":429,"description":"Too Many Requests","parameters":{"retry_after":137}}'
        )
        error = urllib.error.HTTPError("https://api.telegram.org", 429, "Too Many Requests", {}, response)

        with patch("TeeBotus.bot.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(TelegramAPIError) as raised:
                api.request("getUpdates", {})

        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.retry_after, 137)

    def test_telegram_api_rate_limit_exposes_retry_after(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self):
                return b'{"ok":false,"error_code":429,"description":"Too Many Requests","parameters":{"retry_after":23}}'

        api = TelegramAPI("123:test-token")
        with patch("TeeBotus.bot.urllib.request.urlopen", return_value=Response()):
            with self.assertRaises(TelegramAPIError) as raised:
                api.get_updates(None)

        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.retry_after, 23)

    def test_telegram_invalid_json_is_api_error(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self):
                return b"{not-json"

        api = TelegramAPI("123:test-token")
        with patch("TeeBotus.bot.urllib.request.urlopen", return_value=Response()):
            with self.assertRaises(TelegramAPIError) as raised:
                api.request("getUpdates", {})

        self.assertIn("not valid JSON", str(raised.exception))

    def test_telegram_get_updates_requires_update_list(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self):
                return b'{"ok":true,"result":{"update_id":1}}'

        api = TelegramAPI("123:test-token")
        with patch("TeeBotus.bot.urllib.request.urlopen", return_value=Response()):
            with self.assertRaises(TelegramAPIError):
                api.get_updates(None)

    def test_telegram_get_updates_requests_channel_posts(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self):
                return b'{"ok":true,"result":[]}'

        import urllib.parse

        api = TelegramAPI("123:test-token")
        with patch("TeeBotus.bot.urllib.request.urlopen", return_value=Response()) as urlopen:
            self.assertEqual(api.get_updates(None), [])

        request = urlopen.call_args.args[0]
        params = urllib.parse.parse_qs(request.data.decode("utf-8"))
        self.assertEqual(json.loads(params["allowed_updates"][0]), ["message", "channel_post", "callback_query"])

    def test_telegram_send_message_includes_reply_parameters(self) -> None:
        api = TelegramAPI("telegram-token")
        with patch.object(api, "request", return_value={"ok": True, "result": {"message_id": 88}}) as request:
            self.assertEqual(api.send_message(123, "Antwort", reply_parameters='{"message_id":77}'), 88)

        request.assert_called_once_with(
            "sendMessage",
            {
                "chat_id": 123,
                "text": "Antwort",
                "disable_web_page_preview": "true",
                "reply_parameters": '{"message_id":77}',
            },
        )

    def test_legacy_telegram_text_fallback_does_not_swallow_real_type_error(self) -> None:
        from TeeBotus.adapters.telegram_runtime import _send_telegram_message

        class API:
            def send_message(self, chat_id, text, **kwargs):
                raise TypeError("text_mode must be html")

        with self.assertRaisesRegex(TypeError, "text_mode must be html"):
            _send_telegram_message(API(), 123, "Antwort", text_mode="html", formatted_text="<b>Antwort</b>")

    def test_legacy_telegram_text_fallback_keeps_old_signature_usable(self) -> None:
        from TeeBotus.adapters.telegram_runtime import _send_telegram_message

        api = FakeAPI()
        self.assertEqual(_send_telegram_message(api, 123, "Antwort", text_mode="html"), 101)
        self.assertEqual(api.sent_messages, [(123, "Antwort")])

    def test_telegram_multipart_timeout_is_network_error(self) -> None:
        api = TelegramAPI("123:test-token")

        with patch("TeeBotus.bot.urllib.request.urlopen", side_effect=TimeoutError("read timed out")):
            with self.assertRaises(TelegramNetworkError):
                api.request_multipart("sendVoice", {"chat_id": 123}, [("voice", "voice.ogg", "audio/ogg", b"data")])

    def test_telegram_file_download_timeout_is_network_error(self) -> None:
        api = TelegramAPI("123:test-token")

        with patch("TeeBotus.bot.urllib.request.urlopen", side_effect=TimeoutError("read timed out")):
            with self.assertRaises(TelegramNetworkError):
                api.download_file("voice/file.oga")

    def test_srt_to_plain_text_removes_indices_timestamps_and_tags(self) -> None:
        srt = "1\n00:00:00,000 --> 00:00:01,000\n<i>Hello</i>\n\n2\n00:00:01,000 --> 00:00:02,000\nWorld\n"

        self.assertEqual(_srt_to_plain_text(srt), "Hello\nWorld")

    def test_youtube_transcript_uses_subtitles_before_whisper(self) -> None:
        calls: list[list[str]] = []

        def run(command, workdir, timeout, instance_name=""):
            calls.append(command)
            Path(workdir, "video.en.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nSubtitle text.\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as directory:
            with patch("TeeBotus.core.youtube.runtime_dir", return_value=Path(directory) / "runtime"):
                with patch("TeeBotus.core.youtube.shutil.which", return_value="/usr/bin/tool"):
                    with patch("TeeBotus.core.youtube._run_local_command", side_effect=run):
                        transcript, source = transcribe_youtube_video("https://www.youtube.com/watch?v=abc123")

        self.assertEqual(transcript, "Subtitle text.")
        self.assertEqual(source, "YouTube-Untertitel")
        self.assertEqual(len(calls), 1)
        self.assertIn("--write-auto-subs", calls[0])

    def test_youtube_transcript_uses_global_runtime_cache_before_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime_dir = Path(directory) / "runtime"
            cache_path = runtime_dir / "youtube_transcripts" / "abc123.txt"
            cache_path.parent.mkdir(parents=True)
            cache_path.write_text("Cached transcript.\n", encoding="utf-8")

            with patch("TeeBotus.core.youtube.runtime_dir", return_value=runtime_dir):
                with patch("TeeBotus.core.youtube.shutil.which", side_effect=AssertionError("yt-dlp should not be checked")):
                    transcript, source = transcribe_youtube_video("https://youtu.be/abc123")

        self.assertEqual(transcript, "Cached transcript.")
        self.assertEqual(source, "Cache")

    def test_youtube_transcript_writes_global_runtime_cache_after_success(self) -> None:
        def run(command, workdir, timeout, instance_name=""):
            Path(workdir, "video.en.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nSubtitle text.\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as directory:
            runtime_dir = Path(directory) / "runtime"
            with patch("TeeBotus.core.youtube.runtime_dir", return_value=runtime_dir):
                with patch("TeeBotus.core.youtube.shutil.which", return_value="/usr/bin/tool"):
                    with patch("TeeBotus.core.youtube._run_local_command", side_effect=run):
                        transcript, source = transcribe_youtube_video("https://www.youtube.com/watch?v=abc123")

            cache_path = runtime_dir / "youtube_transcripts" / "abc123.txt"
            self.assertEqual(cache_path.read_text(encoding="utf-8"), "Subtitle text.\n")

        self.assertEqual(transcript, "Subtitle text.")
        self.assertEqual(source, "YouTube-Untertitel")

    def test_youtube_transcript_failure_leaves_no_cache_file(self) -> None:
        from TeeBotus.bot import YouTubeTranscriptError

        def run(command, workdir, timeout, instance_name=""):
            return subprocess.CompletedProcess(command, 1, "", "no subtitles")

        with tempfile.TemporaryDirectory() as directory:
            runtime_dir = Path(directory) / "runtime"
            with patch("TeeBotus.core.youtube.runtime_dir", return_value=runtime_dir):
                with patch("TeeBotus.core.youtube.shutil.which", return_value="/usr/bin/tool"):
                    with patch("TeeBotus.core.youtube._run_local_command", side_effect=run):
                        with self.assertRaises(YouTubeTranscriptError):
                            transcribe_youtube_video("https://www.youtube.com/watch?v=abc123")

            cache_dir = runtime_dir / "youtube_transcripts"
            self.assertFalse((cache_dir / "abc123.txt").exists())
            self.assertEqual(list(cache_dir.glob("*.tmp")) if cache_dir.exists() else [], [])

    def test_youtube_transcript_cache_write_is_atomic_and_removes_temp_file_on_failure(self) -> None:
        from TeeBotus.core.youtube import _write_cached_youtube_transcript

        with tempfile.TemporaryDirectory() as directory:
            runtime_dir = Path(directory) / "runtime"
            with patch("TeeBotus.core.youtube.runtime_dir", return_value=runtime_dir):
                with patch("TeeBotus.core.youtube.os.replace", side_effect=OSError("replace failed")):
                    _write_cached_youtube_transcript("https://youtu.be/abc123", "Partial transcript.")

            cache_dir = runtime_dir / "youtube_transcripts"
            self.assertFalse((cache_dir / "abc123.txt").exists())
            self.assertEqual(list(cache_dir.glob("*.tmp")), [])

    def test_youtube_transcript_uses_faster_whisper_when_no_subtitles_exist(self) -> None:
        calls: list[list[str]] = []

        def run(command, workdir, timeout, instance_name=""):
            calls.append(command)
            if command[:2] == ["yt-dlp", "-x"]:
                Path(workdir, "youtube-audio.mp3").write_bytes(b"mp3")
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as directory:
            with patch("TeeBotus.core.youtube.runtime_dir", return_value=Path(directory) / "runtime"):
                with patch("TeeBotus.core.youtube.shutil.which", return_value="/usr/bin/tool"):
                    with patch("TeeBotus.core.youtube._has_python_module", return_value=True):
                        with patch("TeeBotus.core.youtube._run_local_command", side_effect=run):
                            with patch(
                                "TeeBotus.core.youtube._run_local_command_streaming",
                                return_value=subprocess.CompletedProcess(["python3"], 0, "Faster text.\n", ""),
                            ) as streaming:
                                transcript, source = transcribe_youtube_video("https://youtu.be/abc123")

        self.assertEqual(transcript, "Faster text.")
        self.assertEqual(source, "lokales Whisper")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][:2], ["yt-dlp", "-x"])
        self.assertIn("-c", streaming.call_args.args[0])
        self.assertIn("tiny", streaming.call_args.args[0])
        self.assertIn("2", streaming.call_args.args[0])

    def test_resource_tracker_warning_is_filtered_from_process_error(self) -> None:
        result = subprocess.CompletedProcess(
            ["python3"],
            1,
            "",
            "/usr/lib64/python3.14/multiprocessing/resource_tracker.py:475: UserWarning: resource_tracker: There appear to be 1 leaked semaphore objects to clean up at shutdown: {'/mp-test'}\n"
            "  warnings.warn(\n",
        )

        self.assertEqual(_short_process_error(result), "Exitcode 1")

    def test_faster_whisper_reports_signal_abort_instead_of_resource_tracker_warning(self) -> None:
        from TeeBotus.bot import YouTubeTranscriptError

        result = subprocess.CompletedProcess(
            ["python3"],
            -15,
            "",
            "/usr/lib64/python3.14/multiprocessing/resource_tracker.py:475: UserWarning: resource_tracker: There appear to be 1 leaked semaphore objects to clean up at shutdown: {'/mp-test'}\n",
        )

        with patch("TeeBotus.core.youtube._run_local_command_streaming", return_value=result):
            with self.assertRaises(YouTubeTranscriptError) as caught:
                _transcribe_audio_with_faster_whisper_model(Path("audio.mp3"), Path("."), "tiny")

        self.assertEqual(str(caught.exception), "faster-whisper wurde abgebrochen (SIGTERM).")

    def test_youtube_transcript_command_runs_with_lowest_priority_wrappers(self) -> None:
        with patch("TeeBotus.core.youtube.shutil.which", side_effect=lambda name: f"/usr/bin/{name}" if name in {"nice", "ionice"} else None):
            command = _lowest_priority_command(["python3", "-c", "print('x')"])

        self.assertEqual(command[:6], ["nice", "-n", "19", "ionice", "-c", "3"])
        self.assertEqual(command[6:], ["python3", "-c", "print('x')"])

    def test_transcription_process_health_detects_exit_reused_pid_and_zombie(self) -> None:
        class FakeProcess:
            pid = 111

            def __init__(self, returncode=None) -> None:
                self._returncode = returncode

            def poll(self):
                return self._returncode

        self.assertIn("exit=2", _transcription_process_health_error(FakeProcess(2), 12345))

        with patch("TeeBotus.core.youtube._read_process_start_time", return_value=54321), patch("TeeBotus.core.youtube._read_process_state", return_value="S (sleeping)"):
            self.assertEqual(_transcription_process_health_error(FakeProcess(None), 12345), "PID wurde wiederverwendet")

        with patch("TeeBotus.core.youtube._read_process_start_time", return_value=12345), patch("TeeBotus.core.youtube._read_process_state", return_value="Z (zombie)"):
            self.assertEqual(_transcription_process_health_error(FakeProcess(None), 12345), "Prozess ist Zombie")

        with patch("TeeBotus.core.youtube._read_process_start_time", return_value=12345), patch("TeeBotus.core.youtube._read_process_state", return_value="S (sleeping)"):
            self.assertEqual(_transcription_process_health_error(FakeProcess(None), 12345), "")

    def test_process_registry_skips_pid_reuse_and_only_cleans_matching_processes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            registry = _InstanceProcessRegistry("Demo")

            def fake_killpg(pid: int, sig: int) -> None:
                if pid != 333:
                    raise ProcessLookupError

            with patch.dict(os.environ, {"TELEGRAM_BOT_INSTANCES_DIR": str(project_root / "instances")}, clear=False):
                with patch("TeeBotus.core.youtube.os.getpid", return_value=999), patch(
                    "TeeBotus.core.youtube._read_process_start_time",
                    side_effect=lambda pid: {111: 12345, 222: 67890, 999: 77777}.get(pid),
                ):
                    registry.register(111)
                    state_path = project_root / "instances" / "Demo" / "data" / "YouTube_Transcription_Processes.json"
                    payload = json.loads(state_path.read_text(encoding="utf-8"))
                    self.assertEqual(
                        payload["processes"],
                        [{"pid": 111, "start_time": 12345, "owner_pid": 999, "owner_start_time": 77777}],
                    )

                    state_path.write_text(
                        json.dumps(
                            {
                                "processes": [
                                    {"pid": 111, "start_time": 12345},
                                    {"pid": 222, "start_time": 67890},
                                    {"pid": 333, "start_time": 99999},
                                ],
                                "updated_at": "2026-06-13T00:00:00Z",
                            },
                            indent=2,
                            sort_keys=True,
                        )
                        + "\n",
                        encoding="utf-8",
                    )

                    with patch.object(_InstanceProcessRegistry, "_terminate_process_group") as terminate:
                        with patch(
                            "TeeBotus.core.youtube._read_process_start_time",
                            side_effect=lambda pid: {111: 12345, 222: 11111}.get(pid),
                        ), patch("TeeBotus.core.youtube.os.killpg", side_effect=fake_killpg):
                            registry.cleanup_orphans()

                    self.assertEqual(terminate.call_args_list, [call(111)])
                    payload = json.loads(state_path.read_text(encoding="utf-8"))
                    self.assertEqual(payload["processes"], [{"pid": 333, "start_time": 99999}])

    def test_process_registry_keeps_processes_owned_by_live_bot_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            registry = _InstanceProcessRegistry("Demo")
            state_path = project_root / "instances" / "Demo" / "data" / "YouTube_Transcription_Processes.json"

            with patch.dict(os.environ, {"TELEGRAM_BOT_INSTANCES_DIR": str(project_root / "instances")}, clear=False):
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(
                    json.dumps(
                        {
                            "processes": [
                                {"pid": 111, "start_time": 12345, "owner_pid": 999, "owner_start_time": 77777},
                            ],
                            "updated_at": "2026-06-13T00:00:00Z",
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )

                with patch("TeeBotus.core.youtube._read_process_start_time", side_effect=lambda pid: {111: 12345, 999: 77777}.get(pid)):
                    with patch.object(_InstanceProcessRegistry, "_terminate_process_group") as terminate:
                        registry.cleanup_orphans()

            terminate.assert_not_called()
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["processes"],
                [{"pid": 111, "start_time": 12345, "owner_pid": 999, "owner_start_time": 77777}],
            )

    def test_process_registry_can_cleanup_current_owner_on_owned_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            registry = _InstanceProcessRegistry("Demo")
            state_path = project_root / "instances" / "Demo" / "data" / "YouTube_Transcription_Processes.json"

            with patch.dict(os.environ, {"TELEGRAM_BOT_INSTANCES_DIR": str(project_root / "instances")}, clear=False), patch("TeeBotus.core.youtube.os.getpid", return_value=999):
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(
                    json.dumps(
                        {
                            "processes": [
                                {"pid": 111, "start_time": 12345, "owner_pid": 999, "owner_start_time": 77777},
                            ],
                            "updated_at": "2026-06-13T00:00:00Z",
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )

                with patch("TeeBotus.core.youtube._read_process_start_time", side_effect=lambda pid: {111: 12345, 999: 77777}.get(pid)):
                    with patch.object(_InstanceProcessRegistry, "_terminate_process_group") as terminate:
                        registry.cleanup_orphans(include_current_owner=True)

            self.assertEqual(terminate.call_args_list, [call(111)])
            self.assertFalse(state_path.exists())

    def test_process_registry_unregister_only_removes_matching_start_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            registry = _InstanceProcessRegistry("Demo")
            state_path = project_root / "instances" / "Demo" / "data" / "YouTube_Transcription_Processes.json"

            with patch.dict(os.environ, {"TELEGRAM_BOT_INSTANCES_DIR": str(project_root / "instances")}, clear=False):
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(
                    json.dumps(
                        {
                            "processes": [
                                {"pid": 111, "start_time": 12345},
                                {"pid": 111, "start_time": 54321},
                                {"pid": 222, "start_time": 67890},
                            ],
                            "updated_at": "2026-06-13T00:00:00Z",
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )

                registry.unregister(111, 12345)

            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["processes"],
                [{"pid": 111, "start_time": 54321}, {"pid": 222, "start_time": 67890}],
            )

    def test_process_registry_serializes_updates_across_registry_instances(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            registry_a = _InstanceProcessRegistry("Demo")
            registry_b = _InstanceProcessRegistry("Demo")
            registry_a._lock = threading.Lock()
            registry_b._lock = threading.Lock()
            first_loaded = threading.Event()
            release_first = threading.Event()
            second_loaded = threading.Event()
            original_load_a = registry_a._load_state
            original_load_b = registry_b._load_state

            def blocking_load() -> dict[str, object]:
                first_loaded.set()
                assert release_first.wait(timeout=2)
                return original_load_a()

            def marked_load() -> dict[str, object]:
                second_loaded.set()
                return original_load_b()

            registry_a._load_state = blocking_load  # type: ignore[method-assign]
            registry_b._load_state = marked_load  # type: ignore[method-assign]

            with patch.dict(os.environ, {"TELEGRAM_BOT_INSTANCES_DIR": str(project_root / "instances")}, clear=False), patch(
                "TeeBotus.core.youtube._read_process_start_time",
                side_effect=lambda pid: pid,
            ):
                first = threading.Thread(target=registry_a.register, args=(111,))
                second = threading.Thread(target=registry_b.register, args=(222,))
                first.start()
                self.assertTrue(first_loaded.wait(timeout=2))
                second.start()
                self.assertFalse(second_loaded.wait(timeout=0.1))
                release_first.set()
                first.join(timeout=2)
                second.join(timeout=2)

            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            state_path = project_root / "instances" / "Demo" / "data" / "YouTube_Transcription_Processes.json"
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual({entry["pid"] for entry in payload["processes"]}, {111, 222})

    def test_process_registry_deletes_file_when_last_process_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            registry = _InstanceProcessRegistry("Demo")
            state_path = project_root / "instances" / "Demo" / "data" / "YouTube_Transcription_Processes.json"

            with patch.dict(os.environ, {"TELEGRAM_BOT_INSTANCES_DIR": str(project_root / "instances")}, clear=False):
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(
                    json.dumps({"processes": [{"pid": 111, "start_time": 12345}], "updated_at": "2026-06-13T00:00:00Z"}) + "\n",
                    encoding="utf-8",
                )

                registry.unregister(111, 12345)

            self.assertFalse(state_path.exists())

    def test_process_registry_deletes_file_when_cleanup_leaves_no_processes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            registry = _InstanceProcessRegistry("Demo")
            state_path = project_root / "instances" / "Demo" / "data" / "YouTube_Transcription_Processes.json"

            with patch.dict(os.environ, {"TELEGRAM_BOT_INSTANCES_DIR": str(project_root / "instances")}, clear=False):
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(
                    json.dumps({"processes": [{"pid": 111, "start_time": 12345}], "updated_at": "2026-06-13T00:00:00Z"}) + "\n",
                    encoding="utf-8",
                )
                with patch("TeeBotus.core.youtube._read_process_start_time", return_value=None), patch("TeeBotus.core.youtube.os.killpg", side_effect=ProcessLookupError):
                    registry.cleanup_orphans()

            self.assertFalse(state_path.exists())

    def test_instruction_path_uses_selected_instance(self) -> None:
        with patch.dict("os.environ", {"TELEGRAM_BOT_INSTANCE": "Depressionsbot"}, clear=True):
            self.assertEqual(_resolve_instruction_path(), "instances/Depressionsbot/Bot_Verhalten.md")

    def test_explicit_instruction_path_still_overrides_instance(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "TELEGRAM_BOT_INSTANCE": "Depressionsbot",
                "TELEGRAM_BOT_INSTRUCTIONS": "custom/Bot_Verhalten.md",
            },
            clear=True,
        ):
            self.assertEqual(_resolve_instruction_path(), "custom/Bot_Verhalten.md")

    def test_dotenv_does_not_override_existing_environment_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "\n".join(
                    [
                        "TELEGRAM_BOT_INSTANCE=FromDotenv",
                        "TELEGRAM_BOT_TOKEN=dotenv-token",
                        "OPENAI_API_KEY=dotenv-key",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.dict(
                "os.environ",
                {
                    "TELEGRAM_BOT_INSTANCE": "FromEnv",
                    "TELEGRAM_BOT_TOKEN": "env-token",
                    "OPENAI_API_KEY": "env-key",
                },
                clear=True,
            ):
                _load_dotenv(path)
                self.assertEqual(os.environ["TELEGRAM_BOT_INSTANCE"], "FromEnv")
                self.assertEqual(os.environ["TELEGRAM_BOT_TOKEN"], "env-token")
                self.assertEqual(os.environ["OPENAI_API_KEY"], "env-key")

    def test_dotenv_sets_missing_environment_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("TELEGRAM_BOT_TOKEN=dotenv-token\n", encoding="utf-8")

            with patch.dict("os.environ", {}, clear=True):
                _load_dotenv(path)
                self.assertEqual(os.environ["TELEGRAM_BOT_TOKEN"], "dotenv-token")

    def test_dotenv_unquotes_fully_quoted_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                'TELEGRAM_BOT_INSTANCE="Depressionsbot"\nTELEGRAM_BOT_TOKEN=\'quoted-token\'\n',
                encoding="utf-8",
            )

            with patch.dict("os.environ", {}, clear=True):
                _load_dotenv(path)
                self.assertEqual(os.environ["TELEGRAM_BOT_INSTANCE"], "Depressionsbot")
                self.assertEqual(os.environ["TELEGRAM_BOT_TOKEN"], "quoted-token")

    def test_dotenv_uses_shared_parser_for_export_and_inline_comments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "export TELEGRAM_BOT_INSTANCE=Depressionsbot\n"
                "TELEGRAM_BOT_TOKEN=token-value # documentation comment\n",
                encoding="utf-8",
            )

            with patch.dict("os.environ", {}, clear=True):
                _load_dotenv(path)
                self.assertEqual(os.environ["TELEGRAM_BOT_INSTANCE"], "Depressionsbot")
                self.assertEqual(os.environ["TELEGRAM_BOT_TOKEN"], "token-value")

    def test_reads_runtime_config_defaults_from_all_bots_default_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ALL_BOTS_DEFAULT.md"
            path.write_text(
                """
                ## Laufzeitkonfiguration

                - LOG_LEVEL: DEBUG
                - TELEGRAM_BOT_INSTANCE: Demo
                - TELEGRAM_BOT_INSTANCES: leer
                - ignored-lowercase: nope
                """,
                encoding="utf-8",
            )

            defaults = _read_runtime_config_defaults(path)

        self.assertEqual(defaults["LOG_LEVEL"], "DEBUG")
        self.assertEqual(defaults["TELEGRAM_BOT_INSTANCE"], "Demo")
        self.assertNotIn("TELEGRAM_BOT_INSTANCES", defaults)
        self.assertNotIn("ignored-lowercase", defaults)

    def test_runtime_config_defaults_do_not_override_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ALL_BOTS_DEFAULT.md"
            path.write_text(
                """
                ## Laufzeitkonfiguration

                - TELEGRAM_BOT_INSTANCE: FromMarkdown
                - LOG_LEVEL: DEBUG
                """,
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"TELEGRAM_BOT_INSTANCE": "FromEnv"}, clear=True):
                _load_runtime_config_defaults(path)
                self.assertEqual(os.environ["TELEGRAM_BOT_INSTANCE"], "FromEnv")
                self.assertEqual(os.environ["LOG_LEVEL"], "DEBUG")

    def test_discovers_instances_from_bot_verhalten_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            instances_dir = Path(directory)
            (instances_dir / "Bote_der_Wahrheit").mkdir()
            (instances_dir / "Bote_der_Wahrheit" / "Bot_Verhalten.md").write_text("", encoding="utf-8")
            (instances_dir / "Depressionsbot").mkdir()
            (instances_dir / "Depressionsbot" / "Bot_Verhalten.md").write_text("", encoding="utf-8")
            (instances_dir / "Ignoriert").mkdir()

            with patch.dict("os.environ", {"TELEGRAM_BOT_INSTANCES_DIR": str(instances_dir)}, clear=True):
                self.assertEqual(_discover_instance_names(), ["Bote_der_Wahrheit", "Depressionsbot"])

    def test_discovers_instances_from_teebotus_instances_dir(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            instances_dir = Path(directory)
            (instances_dir / "Bote_der_Wahrheit").mkdir()
            (instances_dir / "Bote_der_Wahrheit" / "Bot_Verhalten.md").write_text("", encoding="utf-8")
            (instances_dir / "Depressionsbot").mkdir()
            (instances_dir / "Depressionsbot" / "Bot_Verhalten.md").write_text("", encoding="utf-8")

            with patch.dict("os.environ", {"TEEBOTUS_INSTANCES_DIR": str(instances_dir)}, clear=True):
                self.assertEqual(_discover_instance_names(), ["Bote_der_Wahrheit", "Depressionsbot"])

    def test_instance_token_overrides_generic_token(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "TELEGRAM_BOT_TOKEN": "generic",
                "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT": "depression-token",
            },
            clear=True,
        ):
            self.assertEqual(_resolve_telegram_token("Depressionsbot"), "depression-token")

    def test_resolve_telegram_tokens_accepts_plural_and_indexed_values(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "TELEGRAM_BOT_TOKENS_DEPRESSIONSBOT": "depression-a, depression-b",
                "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT_2": "depression-c",
                "TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT_1": "depression-b",
            },
            clear=True,
        ):
            self.assertEqual(_resolve_telegram_tokens("Depressionsbot"), ["depression-a", "depression-b", "depression-c"])

    def test_instance_openai_key_overrides_generic_key(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "generic-key",
                "OPENAI_API_KEY_DEPRESSIONSBOT": "depression-key",
            },
            clear=True,
        ):
            self.assertEqual(_resolve_openai_api_key("Depressionsbot"), "depression-key")

    def test_generic_openai_key_is_fallback(self) -> None:
        with patch.dict("os.environ", {"OPENAI_API_KEY": "generic-key"}, clear=True):
            self.assertEqual(_resolve_openai_api_key("Depressionsbot"), "generic-key")

    def test_openai_keys_accept_plural_and_indexed_values(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEYS_DEPRESSIONSBOT": "depression-key-a, depression-key-b",
                "OPENAI_API_KEY_DEPRESSIONSBOT_3": "depression-key-c",
            },
            clear=True,
        ):
            self.assertEqual(_resolve_openai_api_keys("Depressionsbot", 3), ["depression-key-a", "depression-key-b", "depression-key-c"])

    def test_bot_token_configs_couple_token_slots_to_openai_key_slots(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "TELEGRAM_BOT_TOKENS_DEPRESSIONSBOT": "depression-token-a, depression-token-b",
                "OPENAI_API_KEYS_DEPRESSIONSBOT": "depression-key-a, depression-key-b",
            },
            clear=True,
        ):
            configs = _resolve_bot_token_configs("Depressionsbot")

        self.assertEqual([(config.label, config.token, config.openai_api_key) for config in configs], [
            ("1", "depression-token-a", "depression-key-a"),
            ("2", "depression-token-b", "depression-key-b"),
        ])
        self.assertEqual(_bot_token_config_error(configs), "")

    def test_multi_token_config_requires_distinct_openai_keys(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "TELEGRAM_BOT_TOKENS_DEPRESSIONSBOT": "depression-token-a, depression-token-b",
                "OPENAI_API_KEY_DEPRESSIONSBOT": "shared-key",
                "OPENAI_API_KEY_DEPRESSIONSBOT_2": "shared-key",
            },
            clear=True,
        ):
            configs = _resolve_bot_token_configs("Depressionsbot")

        self.assertIn("must not share the same OpenAI API key", _bot_token_config_error(configs))

    def test_all_instances_reject_duplicate_telegram_tokens(self) -> None:
        error = _duplicate_telegram_token_error(
            [
                InstanceRunConfig(
                    "Bote_der_Wahrheit",
                    "instances/Bote_der_Wahrheit/Bot_Verhalten.md",
                    (BotTokenConfig("1", "same-token", "key-a"),),
                ),
                InstanceRunConfig(
                    "Depressionsbot",
                    "instances/Depressionsbot/Bot_Verhalten.md",
                    (BotTokenConfig("1", "same-token", "key-b"),),
                ),
            ]
        )

        self.assertIn("Duplicate Telegram bot token", error)
        self.assertIn("Bote_der_Wahrheit:1 / Depressionsbot:1", error)

    def test_instance_env_key_normalizes_instance_name(self) -> None:
        self.assertEqual(_instance_env_key("TELEGRAM_BOT_TOKEN", "Bote_der_Wahrheit"), "TELEGRAM_BOT_TOKEN_BOTE_DER_WAHRHEIT")

    def test_user_memory_file_is_account_scoped_and_follows_openai_across_chats(self) -> None:
        from TeeBotus.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            openai_client = FakeOpenAIClient()
            instructions = BotInstructions(
                openai_enabled=True,
                user_memory_enabled=True,
            )
            memory_store = account_memory_store(directory)

            handle_update(
                api,
                {
                    "message": {
                        "text": "Mein Lieblingswort ist Mond.",
                        "chat": {"id": -1001, "type": "group", "title": "Gruppe A"},
                        "from": {"id": 456, "first_name": "Ada", "username": "ada_l"},
                    }
                },
                instructions,
                openai_client,
                ChatState(),
                memory_store,
                llm_client=openai_client,
            )

            memory_path = account_memory_dir(memory_store, 456) / "User_Memory_Index.json"
            self.assertTrue(memory_path.exists())
            self.assertIn("TMBMAP1", memory_path.read_text(encoding="utf-8"))
            payload = read_account_memory_index(memory_store, 456)
            self.assertEqual(payload["scope"], "account")
            self.assertIn("mond", payload["index"]["keywords"])
            entries = read_account_memory_entries(memory_store, 456)
            self.assertIn("Mein Lieblingswort ist Mond.", entries[0]["user_text"])
            habits_path = account_memory_dir(memory_store, 456) / "User_Habbits_and_behave.md"
            if habits_path.exists():
                self.assertNotIn(b"Mond", habits_path.read_bytes())

            handle_update(
                api,
                {
                    "message": {
                        "text": "Was weisst du noch?",
                        "chat": {"id": -1002, "type": "group", "title": "Gruppe B"},
                        "from": {"id": 456, "first_name": "Ada", "username": "ada_l"},
                    }
                },
                instructions,
                openai_client,
                ChatState(),
                memory_store,
                llm_client=openai_client,
            )

            self.assertIn("Persistentes Nutzergedaechtnis fuer diesen Account", openai_client.reply_inputs[-1])
            self.assertNotIn("Persistentes Nutzergedaechtnis fuer diese sender_id", openai_client.reply_inputs[-1])
            self.assertIn("selected_memory_ids", openai_client.reply_inputs[-1])
            self.assertIn("Mein Lieblingswort ist Mond.", openai_client.reply_inputs[-1])

    def test_user_memory_downloads_avatar_icon_and_sets_folder_icon(self) -> None:
        from TeeBotus.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            api.profile_photo_file_ids[456] = "avatar_file_id"
            api.file_paths["avatar_file_id"] = "photos/avatar.jpg"
            api.file_data["photos/avatar.jpg"] = self.AVATAR_PNG
            instructions = BotInstructions(
                user_memory_enabled=True,
            )
            memory_store = account_memory_store(directory)

            with patch("TeeBotus.bot.subprocess.run") as run:
                handle_update(
                    api,
                    {
                        "message": {
                            "message_id": 1,
                            "text": "/ping",
                            "chat": {"id": 123, "type": "private"},
                            "from": {"id": 456, "first_name": "Ada"},
                        }
                    },
                    instructions,
                    None,
                    ChatState(),
                    memory_store,
                    BotIdentity(id=99, first_name="Mondbot", username="MondBot"),
                )

            user_dir = account_memory_dir(memory_store, 456)
            avatar_path = user_dir / "User_Avatar.jpg"
            icon_path = user_dir / "User_Avatar.icon"
            marker_path = user_dir / ".User_Avatar_Icon_Set"
            self.assertEqual(api.profile_photo_requests, [])
            self.assertEqual(api.file_path_requests, [])
            self.assertEqual(api.download_requests, [])
            self.assertFalse(avatar_path.exists())
            self.assertFalse(icon_path.exists())
            self.assertFalse(marker_path.exists())
            run.assert_not_called()

    def test_user_memory_rechecks_missing_avatar_only_once_per_day(self) -> None:
        from TeeBotus.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            instructions = BotInstructions(
                user_memory_enabled=True,
                openai_enabled=True,
                llm_provider="huggingface",
                llm_model="meta-llama/Llama-3.1-8B-Instruct",
                llm_fallback_models=("groq/llama-3.3-70b-versatile", "openai/gpt-4.1-mini"),
            )
            memory_store = account_memory_store(directory)
            message = {
                "message": {
                    "message_id": 1,
                    "text": "/ping",
                    "chat": {"id": 123, "type": "private"},
                    "from": {"id": 456, "first_name": "Ada"},
                }
            }

            handle_update(api, message, instructions, None, ChatState(), memory_store)
            handle_update(api, message, instructions, None, ChatState(), memory_store)

            user_dir = account_memory_dir(memory_store, 456)
            self.assertEqual(api.profile_photo_requests, [])
            self.assertFalse((user_dir / ".User_Avatar_Checked").exists())
            self.assertFalse((user_dir / "User_Avatar.jpg").exists())
            self.assertFalse((user_dir / "User_Avatar.icon").exists())

    def test_status_reports_version_and_current_user_memory_size(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            instructions = BotInstructions(
                user_memory_enabled=True,
                openai_enabled=True,
                llm_provider="huggingface",
                llm_model="meta-llama/Llama-3.1-8B-Instruct",
                llm_fallback_models=("groq/llama-3.3-70b-versatile", "openai/gpt-4.1-mini"),
                mcp_tools={
                    "bibliothekar.search": {"enabled": True, "read_only": True},
                    "memory.search": {"enabled": True, "read_only": True, "private_chat_only": True},
                    "codex.exec": {"enabled": True, "read_only": False},
                },
            )
            memory_store = account_memory_store(directory)
            account_id = memory_store.resolve_or_create_account(telegram_identity_key(456))
            memory_store.write_agent_state(
                account_id,
                {
                    "schema_version": 1,
                    "proactive": {"enabled": True, "paused": False},
                    "consent": {"categories": ["reminder"]},
                },
            )
            memory_store.append_proactive_outbox_item(account_id, {"status": "queued", "category": "reminder", "message_text": "Ping"})
            memory_store.append_proactive_outbox_item(account_id, {"status": "review_pending", "category": "reminder", "message_text": "Review"})
            memory_store.append_proactive_outbox_item(account_id, {"status": "dispatching", "category": "reminder", "message_text": "In flight"})
            user_dir = memory_store.account_dir(account_id)
            user_dir.mkdir(parents=True, exist_ok=True)
            encrypted_payload = b'{"magic":"TMBMAP1","ciphertext":"abc"}\n'
            (user_dir / "User_Memory_Index.json").write_bytes(encrypted_payload)
            (user_dir / "User_Memory_Entries.jsonl").write_bytes(encrypted_payload)
            (user_dir / "User_Habbits_and_behave.md").write_bytes(b"z" * 512)
            (user_dir / "Secret_Verifier.json").write_bytes(b"not counted")

            with patch.dict(os.environ, {"TEEBOTUS_PROACTIVE_AGENT_INSTANCES": "Depressionsbot"}):
                handle_update(
                    api,
                    {
                        "message": {
                            "message_id": 1,
                            "text": "/status",
                            "chat": {"id": 123, "type": "private"},
                            "from": {"id": 456, "first_name": "Ada"},
                        }
                    },
                    instructions,
                    None,
                    ChatState(),
                    memory_store,
                )

            self.assertEqual(len(api.sent_messages), 1)
            reply = api.sent_messages[0][1]
            self.assertIn("Depressionsbot Status:", reply)
            self.assertIn("- Laufzeit: laeuft", reply)
            self.assertIn(f"- Version: {__version__} Commits https://github.com/H234598/TeeBotus/commits/main", reply)
            self.assertNotIn("Commits:", reply)
            self.assertNotIn("Wirt", reply)
            self.assertIn("- Nutzermemory:", reply)
            self.assertIn("- Userfiles:", reply)
            self.assertIn("verschluesselt", reply)
            self.assertIn("[Aktive LLMs]", reply)
            self.assertIn("- Chat/Text: aktiv - huggingface / meta-llama/Llama-3.1-8B-Instruct", reply)
            self.assertIn("[API, Limits und Kosten]", reply)
            self.assertIn("- Chat/Text: huggingface / meta-llama/Llama-3.1-8B-Instruct", reply)
            self.assertIn(
                "- Ersatzmodelle: nicht aktiv; bei Chat/Textantwort-Fehlern konfiguriert: groq/llama-3.3-70b-versatile, openai/gpt-4.1-mini",
                reply,
            )
            self.assertIn("MCP Tools", reply)
            self.assertIn("- Read-only allowlist: bibliothekar.search, memory.search (private)", reply)
            self.assertIn("- Deaktiviert: codex.exec (nicht read-only), export.account, youtube.transcribe", reply)
            self.assertIn("Proactive Agent", reply)
            self.assertIn("- Agent enabled: ja", reply)
            self.assertIn("- Outbox queued: 1", reply)
            self.assertIn("- Review pending: 1", reply)
            self.assertIn("- Outbox dispatching: 1", reply)
            self.assertIn("- Scheduler enabled: ja", reply)
            self.assertIn("- Model planner: tool", reply)

    def test_info_alias_reports_status_before_configured_command(self) -> None:
        api = FakeAPI()
        instructions = BotInstructions(commands={"/info": "Configured info."})

        handle_update(
            api,
            {
                "message": {
                    "message_id": 1,
                    "text": "/info",
                    "chat": {"id": 123, "type": "private"},
                    "from": {"id": 456, "first_name": "Ada"},
                }
            },
            instructions,
            None,
            ChatState(),
            None,
        )

        self.assertEqual(len(api.sent_messages), 1)
        reply = api.sent_messages[0][1]
        self.assertIn("Status:", reply)
        self.assertIn("- Version:", reply)
        self.assertNotIn("Configured info.", reply)

    def test_user_memory_does_not_leak_between_accounts(self) -> None:
        from TeeBotus.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            openai_client = FakeOpenAIClient()
            instructions = BotInstructions(
                openai_enabled=True,
                user_memory_enabled=True,
            )
            memory_store = account_memory_store(directory)

            handle_update(
                api,
                {
                    "message": {
                        "text": "Geheimnis fuer Ada: Mondstein.",
                        "chat": {"id": -1001, "type": "group", "title": "Gruppe A"},
                        "from": {"id": 456, "first_name": "Ada"},
                    }
                },
                instructions,
                openai_client,
                ChatState(),
                memory_store,
                llm_client=openai_client,
            )
            handle_update(
                api,
                {
                    "message": {
                        "text": "Was weisst du ueber Mondstein?",
                        "chat": {"id": -1002, "type": "group", "title": "Gruppe B"},
                        "from": {"id": 789, "first_name": "Bob"},
                    }
                },
                instructions,
                openai_client,
                ChatState(),
                memory_store,
                llm_client=openai_client,
            )

            self.assertTrue((account_memory_dir(memory_store, 456) / "User_Memory_Index.json").exists())
            self.assertTrue((account_memory_dir(memory_store, 789) / "User_Memory_Index.json").exists())
            self.assertNotIn("Geheimnis fuer Ada", openai_client.reply_inputs[-1])

    def test_user_habits_file_is_included_for_same_account(self) -> None:
        from TeeBotus.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            openai_client = FakeOpenAIClient()
            instructions = BotInstructions(
                openai_enabled=True,
                user_memory_enabled=True,
            )
            memory_store = account_memory_store(directory)

            handle_update(
                api,
                {
                    "message": {
                        "text": "Lege Memory an.",
                        "chat": {"id": -1001, "type": "group", "title": "Gruppe A"},
                        "from": {"id": 456, "first_name": "Ada"},
                    }
                },
                instructions,
                openai_client,
                ChatState(),
                memory_store,
                llm_client=openai_client,
            )
            habits_path = account_memory_dir(memory_store, 456) / "User_Habbits_and_behave.md"
            habits_path.write_text("Ada mag knappe Antworten.", encoding="utf-8")

            handle_update(
                api,
                {
                    "message": {
                        "text": "Was gilt fuer mich?",
                        "chat": {"id": -1002, "type": "group", "title": "Gruppe B"},
                        "from": {"id": 456, "first_name": "Ada"},
                    }
                },
                instructions,
                openai_client,
                ChatState(),
                memory_store,
                llm_client=openai_client,
            )

            self.assertIn("Interne, admingepflegte Zusatzhinweise", openai_client.reply_inputs[-1])
            self.assertIn("Nutze diese Hinweise nur als stillen Kontext", openai_client.reply_inputs[-1])
            self.assertNotIn("User_Habbits_and_behave.md", openai_client.reply_inputs[-1])
            self.assertIn("Ada mag knappe Antworten.", openai_client.reply_inputs[-1])

    def test_user_memory_reset_requires_confirmation_and_resets_only_current_account(self) -> None:
        from TeeBotus.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            openai_client = FakeOpenAIClient()
            chat_state = ChatState()
            instructions = BotInstructions(
                openai_enabled=True,
                user_memory_enabled=True,
            )
            memory_store = account_memory_store(directory)

            handle_update(
                api,
                {
                    "message": {
                        "text": "Merke dir: Mein Codewort ist Mond.",
                        "chat": {"id": 123, "type": "private"},
                        "from": {"id": 456, "first_name": "Ada"},
                    }
                },
                instructions,
                openai_client,
                chat_state,
                memory_store,
                llm_client=openai_client,
            )
            handle_update(
                api,
                {
                    "message": {
                        "text": "Bitte loesche alle Erinnerungen ueber mich.",
                        "chat": {"id": 123, "type": "private"},
                        "from": {"id": 456, "first_name": "Ada"},
                    }
                },
                instructions,
                openai_client,
                chat_state,
                memory_store,
                llm_client=openai_client,
            )

            memory_dir = account_memory_dir(memory_store, 456)
            habits_path = memory_dir / "User_Habbits_and_behave.md"
            habits_path.write_text("Ada mag knappe Antworten.", encoding="utf-8")
            self.assertEqual(api.sent_messages[-1], (123, instructions.user_memory_reset_confirm))
            self.assertNotIn("User_Habbits", api.sent_messages[-1][1])
            self.assertEqual(len(read_account_memory_entries(memory_store, 456)), 1)
            self.assertEqual(len(openai_client.reply_inputs), 1)

            handle_update(
                api,
                {
                    "message": {
                        "text": "ja",
                        "chat": {"id": 123, "type": "private"},
                        "from": {"id": 456, "first_name": "Ada"},
                    }
                },
                instructions,
                openai_client,
                chat_state,
                memory_store,
                llm_client=openai_client,
            )

            payload = read_account_memory_index(memory_store, 456)
            self.assertEqual(api.sent_messages[-1], (123, instructions.user_memory_reset_success))
            self.assertNotIn("User_Habbits", api.sent_messages[-1][1])
            self.assertEqual(payload["scope"], "account")
            self.assertEqual(payload["index"]["recent_ids"], [])
            self.assertEqual(payload["index"]["entries"], {})
            self.assertEqual(payload["index"]["semantic_cache"]["entries"], {})
            self.assertEqual(read_account_memory_entries(memory_store, 456), [])
            self.assertEqual(read_user_memory_text(habits_path), "Ada mag knappe Antworten.")
            self.assertEqual(len(openai_client.reply_inputs), 1)

    def test_user_memory_reset_uses_telegram_username_fallback_identity(self) -> None:
        from TeeBotus.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            openai_client = FakeOpenAIClient()
            chat_state = ChatState()
            instructions = BotInstructions(openai_enabled=True, user_memory_enabled=True)
            memory_store = account_memory_store(directory)
            message_base = {
                "chat": {"id": 123, "type": "private"},
                "from": {"username": "AdaUser", "first_name": "Ada"},
            }

            handle_update(
                api,
                {"message": {**message_base, "text": "Merke dir: Mein Codewort ist Mond."}},
                instructions,
                openai_client,
                chat_state,
                memory_store,
                llm_client=openai_client,
            )
            account_id = memory_store.get_account_for_identity(telegram_identity_key("", username="AdaUser"))
            self.assertIsNotNone(account_id)
            self.assertEqual(len(memory_store.read_memory_entries(account_id)), 1)

            handle_update(
                api,
                {"message": {**message_base, "text": "/reset_memorys"}},
                instructions,
                openai_client,
                chat_state,
                memory_store,
                llm_client=openai_client,
            )
            handle_update(
                api,
                {"message": {**message_base, "text": "ja"}},
                instructions,
                openai_client,
                chat_state,
                memory_store,
                llm_client=openai_client,
            )

            self.assertEqual(api.sent_messages[-1], (123, instructions.user_memory_reset_success))
            payload = memory_store.read_memory_index(account_id)
            self.assertEqual(payload["scope"], "account")
            self.assertEqual(payload["index"]["recent_ids"], [])
            self.assertEqual(payload["index"]["entries"], {})
            self.assertEqual(payload["index"]["semantic_cache"]["entries"], {})
            self.assertEqual(memory_store.read_memory_entries(account_id), [])
            self.assertEqual(len(openai_client.reply_inputs), 1)

    def test_user_memory_reset_can_be_cancelled(self) -> None:
        from TeeBotus.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            openai_client = FakeOpenAIClient()
            chat_state = ChatState()
            instructions = BotInstructions(
                openai_enabled=True,
                user_memory_enabled=True,
            )
            memory_store = account_memory_store(directory)

            handle_update(
                api,
                {
                    "message": {
                        "text": "Merke dir: Mein Codewort ist Sonne.",
                        "chat": {"id": 123, "type": "private"},
                        "from": {"id": 456, "first_name": "Ada"},
                    }
                },
                instructions,
                openai_client,
                chat_state,
                memory_store,
            )
            handle_update(
                api,
                {
                    "message": {
                        "text": "/reset_memorys",
                        "chat": {"id": 123, "type": "private"},
                        "from": {"id": 456, "first_name": "Ada"},
                    }
                },
                instructions,
                openai_client,
                chat_state,
                memory_store,
            )
            handle_update(
                api,
                {
                    "message": {
                        "text": "nein",
                        "chat": {"id": 123, "type": "private"},
                        "from": {"id": 456, "first_name": "Ada"},
                    }
                },
                instructions,
                openai_client,
                chat_state,
                memory_store,
            )

            self.assertEqual(api.sent_messages[-1], (123, instructions.user_memory_reset_cancelled))
            self.assertEqual(len(read_account_memory_entries(memory_store, 456)), 1)

    def test_user_memory_reset_rejects_foreign_and_instance_memory_targets(self) -> None:
        from TeeBotus.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            openai_client = FakeOpenAIClient()
            chat_state = ChatState()
            instructions = BotInstructions(
                openai_enabled=True,
                user_memory_enabled=True,
            )
            memory_store = account_memory_store(directory)
            working_store = WorkingMemoryStore("Depressionsbot", Path(directory) / "instances")
            working_store.append_manual("Allgemeine Regel: sachlich bleiben.")

            for sender_id, name, text in (
                (456, "Ada", "Adas privates Codewort ist Mond."),
                (789, "Bob", "Bobs privates Codewort ist Sonne."),
            ):
                handle_update(
                    api,
                    {
                        "message": {
                            "text": text,
                            "chat": {"id": 123, "type": "private"},
                            "from": {"id": sender_id, "first_name": name},
                        }
                    },
                    instructions,
                    openai_client,
                    chat_state,
                    memory_store,
                    None,
                    working_store,
                    llm_client=openai_client,
                )

            handle_update(
                api,
                {
                    "message": {
                        "text": "Loesche Bobs Erinnerungen.",
                        "chat": {"id": 123, "type": "private"},
                        "from": {"id": 456, "first_name": "Ada"},
                    }
                },
                instructions,
                openai_client,
                chat_state,
                memory_store,
                None,
                working_store,
                llm_client=openai_client,
            )

            self.assertIn("nur deine eigenen Erinnerungen", api.sent_messages[-1][1])
            self.assertIn("keine userbezogenen Daten", api.sent_messages[-1][1])
            bob_entries = read_account_memory_entries(memory_store, 789)
            self.assertEqual(len(bob_entries), 1)

            handle_update(
                api,
                {
                    "message": {
                        "text": "Loesche seine Erinnerungen.",
                        "chat": {"id": 123, "type": "private"},
                        "from": {"id": 456, "first_name": "Ada"},
                    }
                },
                instructions,
                openai_client,
                chat_state,
                memory_store,
                None,
                working_store,
                llm_client=openai_client,
            )

            self.assertIn("nur deine eigenen Erinnerungen", api.sent_messages[-1][1])

            handle_update(
                api,
                {
                    "message": {
                        "text": "Loesch das Instanzgedaechtnis.",
                        "chat": {"id": 123, "type": "private"},
                        "from": {"id": 456, "first_name": "Ada"},
                    }
                },
                instructions,
                openai_client,
                chat_state,
                memory_store,
                None,
                working_store,
                llm_client=openai_client,
            )

            self.assertIn("Instanz-/Arbeitsgedaechtnis enthaelt keine userbezogenen Daten", api.sent_messages[-1][1])
            working_entries = read_jsonl(Path(directory) / "instances" / "Depressionsbot" / "data" / "Working_Memorys.entries.jsonl")
            self.assertEqual(len(working_entries), 1)

    def test_user_memory_reset_ignores_negated_delete_requests(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        openai_client = FakeOpenAIClient()
        instructions = BotInstructions(openai_enabled=True)

        handle_update(
            api,
            {
                "message": {
                    "text": "Bitte loesche meine Erinnerungen nicht.",
                    "chat": {"id": 123, "type": "private"},
                    "from": {"id": 456, "first_name": "Ada"},
                }
            },
            instructions,
            openai_client,
            ChatState(),
            llm_client=openai_client,
        )

        self.assertEqual(api.sent_messages, [(123, "AI: Bitte loesche meine Erinnerungen nicht.")])

    def test_working_memory_files_are_instance_scoped_and_sanitize_manual_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            instances_dir = Path(directory) / "instances"
            store = WorkingMemoryStore("Depressionsbot", instances_dir)

            index_path = store.ensure()
            self.assertEqual(index_path, instances_dir / "Depressionsbot" / "data" / "Working_Memorys.json")
            self.assertTrue((instances_dir / "Depressionsbot" / "data" / "Working_Memorys.entries.jsonl").exists())

            memory_id = store.append_manual(
                "Allgemeine Regel: kurze Antworten. Kontakt @ada, ada@example.com, https://example.com/user/456 und 123456789."
            )

            payload = json.loads(index_path.read_text(encoding="utf-8"))
            entries = read_jsonl(instances_dir / "Depressionsbot" / "data" / "Working_Memorys.entries.jsonl")
            entry_text = entries[0]["text"]
            self.assertTrue(memory_id.startswith("wm_"))
            self.assertEqual(payload["scope"], "instance")
            self.assertNotIn("sender_id", payload)
            self.assertNotIn("profile", payload)
            self.assertIn(memory_id, payload["index"]["entries"])
            self.assertNotIn("@ada", entry_text)
            self.assertNotIn("ada@example.com", entry_text)
            self.assertNotIn("https://example.com", entry_text)
            self.assertNotIn("123456789", entry_text)

    def test_working_memory_corrupt_index_is_preserved_without_traceback_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            instances_dir = Path(directory) / "instances"
            index_path = instances_dir / "Depressionsbot" / "data" / "Working_Memorys.json"
            index_path.parent.mkdir(parents=True)
            index_path.write_text("", encoding="utf-8")
            store = WorkingMemoryStore("Depressionsbot", instances_dir)

            with self.assertLogs("TeeBotus", level="WARNING") as logs:
                store.ensure()

            self.assertTrue(any("Resetting invalid instance working memory" in message for message in logs.output))
            self.assertFalse(any("Traceback" in message for message in logs.output))
            backups = list(index_path.parent.glob("Working_Memorys.json.corrupt.*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "")
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["scope"], "instance")

    def test_working_memory_unreadable_index_is_not_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            instances_dir = Path(directory) / "instances"
            store = WorkingMemoryStore("Depressionsbot", instances_dir)
            index_path = store.ensure()
            original = index_path.read_bytes()

            with patch("TeeBotus.adapters.telegram_runtime.Path.read_text", side_effect=OSError("permission denied")):
                with self.assertLogs("TeeBotus", level="WARNING") as logs:
                    self.assertEqual(store.ensure(), index_path)

            self.assertEqual(index_path.read_bytes(), original)
            self.assertTrue(any("existing data preserved" in message for message in logs.output))

    def test_working_memory_is_included_in_openai_input_without_auto_writes(self) -> None:
        from TeeBotus.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            instances_dir = Path(directory) / "instances"
            api = FakeAPI()
            openai_client = FakeOpenAIClient()
            instructions = BotInstructions(openai_enabled=True)
            working_store = WorkingMemoryStore("Depressionsbot", instances_dir)
            working_store.append_manual("Allgemeine Instanzregel: bei Architekturfragen erst kurz strukturieren.")

            handle_update(
                api,
                {
                    "message": {
                        "text": "Bitte eine Architekturfrage strukturieren.",
                        "chat": {"id": -1001, "type": "group", "title": "Gruppe A"},
                        "from": {"id": 456, "first_name": "Ada", "username": "ada_l"},
                    }
                },
                instructions,
                openai_client,
                ChatState(),
                None,
                None,
                working_store,
                llm_client=openai_client,
            )

            openai_input = openai_client.reply_inputs[-1]
            entries_path = instances_dir / "Depressionsbot" / "data" / "Working_Memorys.entries.jsonl"
            self.assertIn("Instanz-Arbeitsgedaechtnis", openai_input)
            self.assertIn("Allgemeine Instanzregel", openai_input)
            self.assertNotIn("Persistentes Nutzergedaechtnis", openai_input)
            self.assertEqual(len(read_jsonl(entries_path)), 1)

    def test_handle_update_sends_reply_to_message_chat(self) -> None:
        api = FakeAPI()

        handle_update(api, {"message": {"text": "/ping", "chat": {"id": 123}}})

        self.assertEqual(api.sent_messages, [(123, "Pong")])

    def test_chat_state_clears_previous_response_id_when_provider_returns_none(self) -> None:
        chat_state = ChatState()

        chat_state.set_previous_response_id(123, "resp_old")
        chat_state.set_previous_response_id(123, None)

        self.assertIsNone(chat_state.get_previous_response_id(123))

    def test_chat_state_scopes_previous_response_id_inside_shared_group_chat(self) -> None:
        chat_state = ChatState()

        chat_state.set_previous_response_id(123, "resp_a", "account-a")
        chat_state.set_previous_response_id(123, "resp_b", "account-b")

        self.assertEqual(chat_state.get_previous_response_id(123, "account-a"), "resp_a")
        self.assertEqual(chat_state.get_previous_response_id(123, "account-b"), "resp_b")
        self.assertIsNone(chat_state.get_previous_response_id(123, "account-c"))

    def test_legacy_group_messages_do_not_share_llm_context_between_users(self) -> None:
        api = FakeAPI()
        client = FakeOpenAIClient()
        chat_state = ChatState()
        instructions = BotInstructions(openai_enabled=True)

        def update(sender_id: int, text: str) -> dict[str, object]:
            return {
                "message": {
                    "message_id": sender_id,
                    "text": text,
                    "chat": {"id": -100, "type": "group"},
                    "from": {"id": sender_id},
                }
            }

        handle_update(api, update(1, "Erste Nachricht"), instructions, client, chat_state, llm_client=client)
        handle_update(api, update(2, "Andere Person"), instructions, client, chat_state, llm_client=client)
        handle_update(api, update(1, "Noch einmal"), instructions, client, chat_state, llm_client=client)

        self.assertEqual(client.previous_response_ids, [None, None, "resp_123"])

    def test_chat_state_scopes_auto_voice_counter_inside_shared_group_chat(self) -> None:
        chat_state = ChatState()

        self.assertFalse(chat_state.should_send_auto_voice(123, 2, "account-a"))
        self.assertFalse(chat_state.should_send_auto_voice(123, 2, "account-b"))
        self.assertTrue(chat_state.should_send_auto_voice(123, 2, "account-a"))
        self.assertTrue(chat_state.should_send_auto_voice(123, 2, "account-b"))

    def test_handle_update_with_runtime_context_uses_modern_engine(self) -> None:
        class FixedWakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                value = cls(2026, 6, 15, 12, tzinfo=timezone.utc)
                return value if tz is None else value.astimezone(tz)

        class InstructionBox:
            def get(self):
                return BotInstructions()

        api = FakeAPI()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            account_store = AccountStore(root / "accounts", "Demo", StaticSecretProvider(b"e" * 32))
            state_store = RuntimeStateStore(root / "data", instance_name="Demo", secret_provider=StaticSecretProvider(b"e" * 32))
            message_tracker = MessageTracker(root / "runtime" / "Sent_Message_Refs.json")
            context = build_telegram_runtime_context(
                api=api,
                instance_name="Demo",
                adapter_slot=1,
                instruction_store=InstructionBox(),
                account_store=account_store,
                state_store=state_store,
                message_tracker=message_tracker,
                openai_client=None,
                working_memory_store=None,
                bibliothekar_store=None,
                youtube_job_runner=None,
                bot_identity=BotIdentity(first_name="Mondbot", username="MondBot"),
            )

            with (
                patch("TeeBotus.adapters.telegram_runtime._process_text_message", side_effect=AssertionError("legacy path used")),
                patch("TeeBotus.adapters.telegram.time.sleep"),
                patch("TeeBotus.runtime.notification_loudness.datetime", FixedWakeDatetime),
            ):
                handle_update(
                    api,
                    {"message": {"message_id": 1, "text": "/ping", "chat": {"id": 123, "type": "private"}, "from": {"id": 456}}},
                    chat_state=ChatState(),
                    runtime_context=context,
                )

            account_id = account_store.get_account_for_identity(telegram_identity_key("456"))
            self.assertEqual(message_tracker.list_for_chat("123", instance_name="Demo", channel="telegram")[0].message_ref, "101")

        self.assertEqual(api.sent_messages[:10], [("123", "Pong")] * 10)
        self.assertIn("Nachrichten in diesem Chat auf laut", api.sent_messages[10][1])
        self.assertIsNotNone(account_id)

    def test_modern_group_reply_to_bot_reaches_engine_before_account_resolution(self) -> None:
        from TeeBotus.runtime.actions import SendText
        from TeeBotus.runtime.engine import EngineResult

        class InstructionBox:
            def get(self):
                return BotInstructions()

        api = FakeAPI()
        seen_events = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            account_store = AccountStore(root / "accounts", "Demo", StaticSecretProvider(b"e" * 32))
            state_store = RuntimeStateStore(root / "data", instance_name="Demo", secret_provider=StaticSecretProvider(b"e" * 32))
            message_tracker = MessageTracker(root / "runtime" / "Sent_Message_Refs.json")
            context = build_telegram_runtime_context(
                api=api,
                instance_name="Demo",
                adapter_slot=1,
                instruction_store=InstructionBox(),
                account_store=account_store,
                state_store=state_store,
                message_tracker=message_tracker,
                openai_client=None,
                working_memory_store=None,
                bibliothekar_store=None,
                youtube_job_runner=None,
                bot_identity=BotIdentity(id=99, first_name="Mondbot", username="MondBot"),
            )

            def process_result(event):
                seen_events.append(event)
                return EngineResult(event.account_id, [SendText(event.chat_id, "ok")], handled=True)

            context.engine.process_result = process_result  # type: ignore[method-assign]
            handle_update(
                api,
                {
                    "message": {
                        "message_id": 2,
                        "text": "Ja, bitte.",
                        "chat": {"id": -100, "type": "group", "title": "Debatte"},
                        "from": {"id": 456, "first_name": "Ada"},
                        "reply_to_message": {
                            "message_id": 1,
                            "text": "Botfrage",
                            "from": {"id": "99", "is_bot": True, "username": "MondBot"},
                        },
                    }
                },
                chat_state=ChatState(),
                runtime_context=context,
            )

        self.assertEqual(api.sent_messages, [("-100", "ok")])
        self.assertEqual(len(seen_events), 1)
        self.assertTrue(seen_events[0].reply_to_bot)
        self.assertEqual(seen_events[0].reply_to_text, "Botfrage")

    def test_modern_dispatch_retry_skips_completed_actions_and_reuses_engine_result(self) -> None:
        from TeeBotus.runtime.actions import SendText
        from TeeBotus.runtime.engine import EngineResult

        class InstructionBox:
            def get(self):
                return BotInstructions()

        class PartialFailureAPI(FakeAPI):
            def __init__(self) -> None:
                super().__init__()
                self.failed_once = False

            def send_message(self, chat_id: int, text: str) -> int:
                if text == "second" and not self.failed_once:
                    self.failed_once = True
                    raise TelegramAPIError("temporary second action failure")
                return super().send_message(chat_id, text)

        api = PartialFailureAPI()
        process_calls = 0
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            account_store = AccountStore(root / "accounts", "Demo", StaticSecretProvider(b"e" * 32))
            state_store = RuntimeStateStore(root / "data", instance_name="Demo", secret_provider=StaticSecretProvider(b"e" * 32))
            message_tracker = MessageTracker(root / "runtime" / "Sent_Message_Refs.json")
            context = build_telegram_runtime_context(
                api=api,
                instance_name="Demo",
                adapter_slot=1,
                instruction_store=InstructionBox(),
                account_store=account_store,
                state_store=state_store,
                message_tracker=message_tracker,
                openai_client=None,
                working_memory_store=None,
                bibliothekar_store=None,
                youtube_job_runner=None,
                bot_identity=BotIdentity(first_name="Mondbot", username="MondBot"),
            )

            def process_result(event):
                nonlocal process_calls
                process_calls += 1
                return EngineResult(
                    event.account_id,
                    [SendText(event.chat_id, "first"), SendText(event.chat_id, "second")],
                    handled=True,
                )

            context.engine.process_result = process_result  # type: ignore[method-assign]
            update = {
                "update_id": 41,
                "message": {
                    "message_id": 7,
                    "text": "/ping",
                    "chat": {"id": 123, "type": "private"},
                    "from": {"id": 456},
                },
            }

            with self.assertRaisesRegex(TelegramAPIError, "temporary second action failure"):
                handle_update(api, update, chat_state=ChatState(), runtime_context=context)
            handle_update(api, update, chat_state=ChatState(), runtime_context=context)

        self.assertEqual(api.sent_messages, [("123", "first"), ("123", "second")])
        self.assertEqual(process_calls, 1)

    def test_modern_dispatch_retry_recovers_from_encrypted_journal_after_context_rebuild(self) -> None:
        from TeeBotus.runtime.actions import SendText
        from TeeBotus.runtime.engine import EngineResult

        class InstructionBox:
            def get(self):
                return BotInstructions()

        class PartialFailureAPI(FakeAPI):
            def __init__(self) -> None:
                super().__init__()
                self.failed_once = False

            def send_message(self, chat_id: int, text: str) -> int:
                if text == "second" and not self.failed_once:
                    self.failed_once = True
                    raise TelegramAPIError("temporary second action failure")
                return super().send_message(chat_id, text)

        def build_context(root: Path, api: FakeAPI):
            secret_provider = StaticSecretProvider(b"e" * 32)
            account_store = AccountStore(root / "accounts", "Demo", secret_provider)
            state_store = RuntimeStateStore(root / "data", instance_name="Demo", secret_provider=secret_provider)
            return build_telegram_runtime_context(
                api=api,
                instance_name="Demo",
                adapter_slot=1,
                instruction_store=InstructionBox(),
                account_store=account_store,
                state_store=state_store,
                message_tracker=MessageTracker(root / "runtime" / "Sent_Message_Refs.json"),
                openai_client=None,
                working_memory_store=None,
                bibliothekar_store=None,
                youtube_job_runner=None,
                bot_identity=BotIdentity(first_name="Mondbot", username="MondBot"),
            )

        api = PartialFailureAPI()
        process_calls = 0
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = build_context(root, api)

            def process_result(event):
                nonlocal process_calls
                process_calls += 1
                return EngineResult(
                    event.account_id,
                    [SendText(event.chat_id, "first"), SendText(event.chat_id, "second")],
                    handled=True,
                )

            context.engine.process_result = process_result  # type: ignore[method-assign]
            update = {
                "update_id": 43,
                "message": {
                    "message_id": 9,
                    "text": "/ping",
                    "chat": {"id": 123, "type": "private"},
                    "from": {"id": 456},
                },
            }
            with self.assertRaisesRegex(TelegramAPIError, "temporary second action failure"):
                handle_update(api, update, chat_state=ChatState(), runtime_context=context)

            journal_path = root / "data" / "runtime" / "Telegram_Dispatch_Journal.json"
            self.assertTrue(journal_path.exists())
            self.assertNotIn(b"second", journal_path.read_bytes())

            recovered_context = build_context(root, api)
            recovered_context.engine.process_result = lambda _event: (_ for _ in ()).throw(AssertionError("engine rerun"))  # type: ignore[method-assign]
            handle_update(api, update, chat_state=ChatState(), runtime_context=recovered_context)
            self.assertNotIn(b"second", journal_path.read_bytes())

        self.assertEqual(api.sent_messages, [("123", "first"), ("123", "second")])
        self.assertEqual(process_calls, 1)

    def test_modern_dispatch_retry_does_not_reapply_current_address_gate(self) -> None:
        from TeeBotus.runtime.actions import SendText
        from TeeBotus.runtime.engine import EngineResult

        class InstructionBox:
            def get(self):
                return BotInstructions()

        class PartialFailureAPI(FakeAPI):
            def __init__(self) -> None:
                super().__init__()
                self.failed_once = False

            def send_message(self, chat_id: int, text: str) -> int:
                if text == "second" and not self.failed_once:
                    self.failed_once = True
                    raise TelegramAPIError("temporary second action failure")
                return super().send_message(chat_id, text)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret_provider = StaticSecretProvider(b"e" * 32)
            api = PartialFailureAPI()
            context = build_telegram_runtime_context(
                api=api,
                instance_name="Demo",
                adapter_slot=1,
                instruction_store=InstructionBox(),
                account_store=AccountStore(root / "accounts", "Demo", secret_provider),
                state_store=RuntimeStateStore(root / "data", instance_name="Demo", secret_provider=secret_provider),
                message_tracker=MessageTracker(root / "runtime" / "Sent_Message_Refs.json"),
                openai_client=None,
                working_memory_store=None,
                bibliothekar_store=None,
                youtube_job_runner=None,
                bot_identity=BotIdentity(first_name="Mondbot", username="MondBot"),
            )
            context.engine.process_result = lambda event: EngineResult(  # type: ignore[method-assign]
                event.account_id,
                [SendText(event.chat_id, "first"), SendText(event.chat_id, "second")],
                handled=True,
            )
            update = {
                "update_id": 44,
                "message": {
                    "message_id": 10,
                    "text": "/ping",
                    "chat": {"id": 123, "type": "private"},
                    "from": {"id": 456},
                },
            }
            with self.assertRaisesRegex(TelegramAPIError, "temporary second action failure"):
                handle_update(api, update, chat_state=ChatState(), runtime_context=context)

            context.engine.should_ignore_without_account = Mock(return_value=True)  # type: ignore[method-assign]
            handle_update(api, update, chat_state=ChatState(), runtime_context=context)

        self.assertEqual(api.sent_messages, [("123", "first"), ("123", "second")])
        context.engine.should_ignore_without_account.assert_not_called()

    def test_modern_dispatch_timeout_does_not_send_fallback_while_worker_is_in_flight(self) -> None:
        from TeeBotus.runtime.actions import SendText
        from TeeBotus.runtime.engine import EngineResult

        class InstructionBox:
            def get(self):
                return BotInstructions()

        class BlockingAPI(FakeAPI):
            def __init__(self) -> None:
                super().__init__()
                self.started = threading.Event()
                self.release = threading.Event()
                self.finished = threading.Event()

            def send_message(self, chat_id: int, text: str) -> int:
                self.started.set()
                self.release.wait(timeout=5)
                result = super().send_message(chat_id, text)
                self.finished.set()
                return result

        api = BlockingAPI()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            account_store = AccountStore(root / "accounts", "Demo", StaticSecretProvider(b"e" * 32))
            state_store = RuntimeStateStore(root / "data", instance_name="Demo", secret_provider=StaticSecretProvider(b"e" * 32))
            message_tracker = MessageTracker(root / "runtime" / "Sent_Message_Refs.json")
            context = build_telegram_runtime_context(
                api=api,
                instance_name="Demo",
                adapter_slot=1,
                instruction_store=InstructionBox(),
                account_store=account_store,
                state_store=state_store,
                message_tracker=message_tracker,
                openai_client=None,
                working_memory_store=None,
                bibliothekar_store=None,
                youtube_job_runner=None,
                bot_identity=BotIdentity(first_name="Mondbot", username="MondBot"),
            )
            context.engine.process_result = lambda event: EngineResult(  # type: ignore[method-assign]
                event.account_id,
                [SendText(event.chat_id, "slow")],
                handled=True,
            )
            update = {
                "update_id": 42,
                "message": {
                    "message_id": 8,
                    "text": "/ping",
                    "chat": {"id": 123, "type": "private"},
                    "from": {"id": 456},
                },
            }

            with patch.dict(os.environ, {"TELEGRAM_RUNTIME_DISPATCH_TIMEOUT_SECONDS": "1"}, clear=False):
                with self.assertRaisesRegex(RuntimeError, "dispatch timed out"):
                    handle_update(api, update, chat_state=ChatState(), runtime_context=context)
            self.assertTrue(api.started.wait(timeout=1))
            self.assertEqual(api.sent_messages, [])

            api.release.set()
            self.assertTrue(api.finished.wait(timeout=2))
            self.assertTrue(context.dispatch_lock.acquire(timeout=2))
            context.dispatch_lock.release()
            handle_update(api, update, chat_state=ChatState(), runtime_context=context)

        self.assertEqual(api.sent_messages, [("123", "slow")])

    def test_modern_unaddressed_group_attachment_is_not_downloaded(self) -> None:
        class InstructionBox:
            def get(self):
                return BotInstructions()

        api = FakeAPI()
        api.file_paths["doc-1"] = "documents/doc.bin"
        api.file_data["documents/doc.bin"] = b"private document"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            account_store = AccountStore(root / "accounts", "Demo", StaticSecretProvider(b"e" * 32))
            state_store = RuntimeStateStore(root / "data", instance_name="Demo", secret_provider=StaticSecretProvider(b"e" * 32))
            message_tracker = MessageTracker(root / "runtime" / "Sent_Message_Refs.json")
            context = build_telegram_runtime_context(
                api=api,
                instance_name="Demo",
                adapter_slot=1,
                instruction_store=InstructionBox(),
                account_store=account_store,
                state_store=state_store,
                message_tracker=message_tracker,
                openai_client=None,
                working_memory_store=None,
                bibliothekar_store=None,
                youtube_job_runner=None,
                bot_identity=BotIdentity(id=99, first_name="Mondbot", username="MondBot"),
            )
            context.engine.should_ignore_without_account = lambda _event: True  # type: ignore[method-assign]

            handle_update(
                api,
                {
                    "message": {
                        "message_id": 3,
                        "chat": {"id": -100, "type": "group", "title": "Debatte"},
                        "from": {"id": 456, "first_name": "Ada"},
                        "document": {"file_id": "doc-1", "file_name": "privat.txt"},
                    }
                },
                chat_state=ChatState(),
                runtime_context=context,
            )

        self.assertEqual(api.file_path_requests, [])
        self.assertEqual(api.download_requests, [])

    def test_handle_update_with_runtime_context_answers_callback_query(self) -> None:
        from TeeBotus.runtime.actions import SendText
        from TeeBotus.runtime.engine import EngineResult

        class InstructionBox:
            def get(self):
                return BotInstructions()

        api = FakeAPI()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            account_store = AccountStore(root / "accounts", "Demo", StaticSecretProvider(b"e" * 32))
            state_store = RuntimeStateStore(root / "data", instance_name="Demo", secret_provider=StaticSecretProvider(b"e" * 32))
            message_tracker = MessageTracker(root / "runtime" / "Sent_Message_Refs.json")
            context = build_telegram_runtime_context(
                api=api,
                instance_name="Demo",
                adapter_slot=1,
                instruction_store=InstructionBox(),
                account_store=account_store,
                state_store=state_store,
                message_tracker=message_tracker,
                openai_client=None,
                working_memory_store=None,
                bibliothekar_store=None,
                youtube_job_runner=None,
                bot_identity=BotIdentity(first_name="Mondbot", username="MondBot"),
            )
            context.engine.process_result = lambda event: EngineResult(  # type: ignore[method-assign]
                event.account_id,
                [SendText(event.chat_id, f"got {event.text}")],
                handled=True,
            )

            handle_update(
                api,
                {
                    "callback_query": {
                        "id": "cb-1",
                        "from": {"id": 456, "first_name": "Ada"},
                        "data": "ja",
                        "message": {
                            "message_id": 1,
                            "chat": {"id": 123, "type": "private"},
                            "text": "Bitte waehlen",
                        },
                    }
                },
                chat_state=ChatState(),
                runtime_context=context,
            )

        self.assertEqual(api.callback_answers, [("cb-1", "")])
        self.assertEqual(api.sent_messages, [("123", "got ja")])

    def test_handle_update_with_runtime_context_logs_tracking_errors(self) -> None:
        from TeeBotus.runtime.actions import SendText
        from TeeBotus.runtime.engine import EngineResult

        class InstructionBox:
            def get(self):
                return BotInstructions()

        api = FakeAPI()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            account_store = AccountStore(root / "accounts", "Demo", StaticSecretProvider(b"e" * 32))
            state_store = RuntimeStateStore(root / "data", instance_name="Demo", secret_provider=StaticSecretProvider(b"e" * 32))
            message_tracker = MessageTracker(root / "runtime" / "Sent_Message_Refs.json")
            message_tracker.record = lambda _ref: (_ for _ in ()).throw(OSError("tracker refused"))  # type: ignore[method-assign]
            context = build_telegram_runtime_context(
                api=api,
                instance_name="Demo",
                adapter_slot=1,
                instruction_store=InstructionBox(),
                account_store=account_store,
                state_store=state_store,
                message_tracker=message_tracker,
                openai_client=None,
                working_memory_store=None,
                bibliothekar_store=None,
                youtube_job_runner=None,
                bot_identity=BotIdentity(first_name="Mondbot", username="MondBot"),
            )
            context.engine.process_result = lambda event: EngineResult(event.account_id, [SendText(event.chat_id, "ok")], handled=True)  # type: ignore[method-assign]

            with self.assertLogs("TeeBotus", level="ERROR") as logs:
                handle_update(
                    api,
                    {"message": {"message_id": 1, "text": "/ping", "chat": {"id": 123, "type": "private"}, "from": {"id": 456}}},
                    chat_state=ChatState(),
                    runtime_context=context,
                )

        self.assertEqual(api.sent_messages, [("123", "ok")])
        self.assertIn("Telegram sent message tracking failed", "\n".join(logs.output))

    def test_handle_update_with_runtime_context_marks_codex_history_reply_acknowledged(self) -> None:
        from TeeBotus.runtime.engine import EngineResult

        class InstructionBox:
            def get(self):
                return BotInstructions()

        api = FakeAPI()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            account_store = AccountStore(root / "accounts", "Demo", StaticSecretProvider(b"e" * 32))
            account_id = account_store.resolve_or_create_account(telegram_identity_key("456"), display_label="Ada")
            item_id = account_store.append_codex_history_item(
                INSTANCE_STATE_ACCOUNT_ID,
                {
                    "kind": "codex_run_summary",
                    "status": "accepted",
                    "summary_prefix": "v1.8.2 #0001",
                    "summary_number": 1,
                    "summary": {"title": "Runtime Reply Ack"},
                    "version": {"summary_prefix": "v1.8.2 #0001", "summary_number": 1},
                    "delivery": {"accepted_at": "2026-06-19T12:00:00+00:00"},
                    "status_history": [{"at": "2026-06-19T12:00:00+00:00", "status": "accepted", "reason": "accepted"}],
                },
            )
            account_store.append_codex_history_dispatch_result(
                INSTANCE_STATE_ACCOUNT_ID,
                {
                    "codex_history_item_id": item_id,
                    "account_id": account_id,
                    "instance": "Demo",
                    "status": "accepted",
                    "channel": "telegram",
                    "chat_id": "123",
                    "message_ref": "101",
                    "summary_prefix": "v1.8.2 #0001",
                },
            )
            state_store = RuntimeStateStore(root / "data", instance_name="Demo", secret_provider=StaticSecretProvider(b"e" * 32))
            message_tracker = MessageTracker(root / "runtime" / "Sent_Message_Refs.json")
            context = build_telegram_runtime_context(
                api=api,
                instance_name="Demo",
                adapter_slot=1,
                instruction_store=InstructionBox(),
                account_store=account_store,
                state_store=state_store,
                message_tracker=message_tracker,
                openai_client=None,
                working_memory_store=None,
                bibliothekar_store=None,
                youtube_job_runner=None,
                bot_identity=BotIdentity(first_name="Mondbot", username="MondBot"),
            )
            context.engine.process_result = lambda event: EngineResult(event.account_id, [], handled=True)  # type: ignore[method-assign]

            handle_update(
                api,
                {
                    "message": {
                        "message_id": 202,
                        "text": "ok, gesehen",
                        "chat": {"id": 123, "type": "private"},
                        "from": {"id": 456, "first_name": "Ada"},
                        "reply_to_message": {
                            "message_id": 101,
                            "document": {"file_name": "TeeBotus_release_1.8.2_0001.md"},
                        },
                    }
                },
                chat_state=ChatState(),
                runtime_context=context,
            )

            persisted = account_store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
            dispatch_rows = account_store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)

        self.assertEqual(api.sent_messages, [])
        self.assertEqual(persisted["status"], "acknowledged")
        self.assertEqual(persisted["delivery"]["acknowledged_at"], persisted["delivery"]["delivered_at"])
        self.assertEqual([row["status"] for row in dispatch_rows], ["accepted", "delivered", "acknowledged"])
        self.assertEqual(dispatch_rows[-1]["message_ref"], "101")
        self.assertEqual(dispatch_rows[-1]["reply_message_ref"], "202")
        self.assertEqual(dispatch_rows[-1]["reply_text_preview"], "ok, gesehen")

    def test_legacy_handle_update_marks_codex_history_reply_acknowledged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            api.adapter_slot = 2
            instructions = BotInstructions(user_memory_enabled=True, openai_enabled=False)
            memory_store = account_memory_store(directory, instance_name="Demo")
            account_id = memory_store.resolve_or_create_account(telegram_identity_key("456"), display_label="Ada")
            item_id = memory_store.append_codex_history_item(
                INSTANCE_STATE_ACCOUNT_ID,
                {
                    "kind": "codex_run_summary",
                    "status": "accepted",
                    "summary_prefix": "v1.8.2 #0001",
                    "summary_number": 1,
                    "summary": {"title": "Legacy Reply Ack"},
                    "version": {"summary_prefix": "v1.8.2 #0001", "summary_number": 1},
                    "delivery": {"accepted_at": "2026-06-19T12:00:00+00:00"},
                    "status_history": [{"at": "2026-06-19T12:00:00+00:00", "status": "accepted", "reason": "accepted"}],
                },
            )
            memory_store.append_codex_history_dispatch_result(
                INSTANCE_STATE_ACCOUNT_ID,
                {
                    "codex_history_item_id": item_id,
                    "account_id": account_id,
                    "instance": "Demo",
                    "status": "accepted",
                    "channel": "telegram",
                    "chat_id": "123",
                    "message_ref": "101",
                    "adapter_slot": 2,
                    "summary_prefix": "v1.8.2 #0001",
                },
            )

            handle_update(
                api,
                {
                    "message": {
                        "message_id": 202,
                        "text": "ok, gesehen",
                        "chat": {"id": 123, "type": "private"},
                        "from": {"id": 456, "first_name": "Ada"},
                        "reply_to_message": {"message_id": 101, "document": {"file_name": "Release.md"}},
                    }
                },
                instructions,
                None,
                ChatState(),
                memory_store,
                BotIdentity(first_name="Mondbot", username="MondBot"),
            )

            persisted = memory_store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
            dispatch_rows = memory_store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)

        self.assertEqual(persisted["status"], "acknowledged")
        self.assertEqual([row["status"] for row in dispatch_rows], ["accepted", "delivered", "acknowledged"])
        self.assertEqual(dispatch_rows[-1]["reply_message_ref"], "202")

    def test_legacy_activity_profile_preserves_api_adapter_slot(self) -> None:
        from TeeBotus.adapters.telegram_runtime import _record_telegram_activity

        with tempfile.TemporaryDirectory() as directory:
            store = account_memory_store(directory, instance_name="Depressionsbot")
            account_id = store.resolve_or_create_account(telegram_identity_key("456"), display_label="Ada")
            message = {
                "message_id": 1,
                "text": "Hallo",
                "chat": {"id": 123, "type": "private"},
                "from": {"id": 456, "first_name": "Ada"},
            }

            with patch("TeeBotus.adapters.telegram_runtime.proactive_agent_instance_enabled", return_value=True):
                _record_telegram_activity(store, account_id, telegram_identity_key("456"), message, adapter_slot=2)

            observations = store.read_agent_state(account_id)["activity_profile"]["observations"]

        self.assertEqual(observations[-1]["route_key"], "telegram:2:123")

    def test_handle_update_with_runtime_context_propagates_action_dispatch_errors(self) -> None:
        from TeeBotus.runtime.actions import SendText
        from TeeBotus.runtime.engine import EngineResult

        class InstructionBox:
            def get(self):
                return BotInstructions()

        class FailingSendAPI(FakeAPI):
            def send_message(self, chat_id: int, text: str) -> int:
                raise TelegramAPIError("send refused")

        api = FailingSendAPI()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            account_store = AccountStore(root / "accounts", "Demo", StaticSecretProvider(b"e" * 32))
            state_store = RuntimeStateStore(root / "data", instance_name="Demo", secret_provider=StaticSecretProvider(b"e" * 32))
            message_tracker = MessageTracker(root / "runtime" / "Sent_Message_Refs.json")
            context = build_telegram_runtime_context(
                api=api,
                instance_name="Demo",
                adapter_slot=1,
                instruction_store=InstructionBox(),
                account_store=account_store,
                state_store=state_store,
                message_tracker=message_tracker,
                openai_client=None,
                working_memory_store=None,
                bibliothekar_store=None,
                youtube_job_runner=None,
                bot_identity=BotIdentity(first_name="Mondbot", username="MondBot"),
            )
            context.engine.process_result = lambda event: EngineResult(event.account_id, [SendText(event.chat_id, "ok")], handled=True)  # type: ignore[method-assign]

            with (
                self.assertLogs("TeeBotus", level="ERROR") as logs,
                self.assertRaisesRegex(TelegramAPIError, "send refused"),
            ):
                handle_update(
                    api,
                    {"message": {"message_id": 1, "text": "/ping", "chat": {"id": 123, "type": "private"}, "from": {"id": 456}}},
                    chat_state=ChatState(),
                    runtime_context=context,
                )

        self.assertIn("Telegram action dispatch failed hard", "\n".join(logs.output))

    def test_handle_update_with_runtime_context_handles_account_store_errors(self) -> None:
        class InstructionBox:
            def __init__(self, instructions: BotInstructions) -> None:
                self.instructions = instructions

            def get(self):
                return self.instructions

        api = FakeAPI()
        instructions = BotInstructions(user_memory_error="Memory kaputt.")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            account_store = FailingAccountMemoryStore()
            state_store = RuntimeStateStore(root / "data", instance_name="Demo", secret_provider=StaticSecretProvider(b"e" * 32))
            message_tracker = MessageTracker(root / "runtime" / "Sent_Message_Refs.json")
            context = build_telegram_runtime_context(
                api=api,
                instance_name="Demo",
                adapter_slot=1,
                instruction_store=InstructionBox(instructions),
                account_store=account_store,
                state_store=state_store,
                message_tracker=message_tracker,
                openai_client=None,
                working_memory_store=None,
                bibliothekar_store=None,
                youtube_job_runner=None,
                bot_identity=BotIdentity(first_name="Mondbot", username="MondBot"),
            )

            with self.assertLogs("TeeBotus", level="ERROR"):
                handle_update(
                    api,
                    {"message": {"message_id": 1, "text": "/ping", "chat": {"id": 123, "type": "private"}, "from": {"id": 456}}},
                    chat_state=ChatState(),
                    runtime_context=context,
                )

        self.assertEqual(api.sent_messages, [("123", "Memory kaputt.")])

    def test_handle_update_with_runtime_context_handles_engine_account_store_errors(self) -> None:
        class InstructionBox:
            def __init__(self, instructions: BotInstructions) -> None:
                self.instructions = instructions

            def get(self):
                return self.instructions

        api = FakeAPI()
        instructions = BotInstructions(user_memory_error="Memory kaputt.")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            account_store = AccountStore(root / "accounts", "Demo", StaticSecretProvider(b"e" * 32))
            state_store = RuntimeStateStore(root / "data", instance_name="Demo", secret_provider=StaticSecretProvider(b"e" * 32))
            message_tracker = MessageTracker(root / "runtime" / "Sent_Message_Refs.json")
            context = build_telegram_runtime_context(
                api=api,
                instance_name="Demo",
                adapter_slot=1,
                instruction_store=InstructionBox(instructions),
                account_store=account_store,
                state_store=state_store,
                message_tracker=message_tracker,
                openai_client=None,
                working_memory_store=None,
                bibliothekar_store=None,
                youtube_job_runner=None,
                bot_identity=BotIdentity(first_name="Mondbot", username="MondBot"),
            )
            context.engine.process_result = lambda _event: (_ for _ in ()).throw(AccountStoreError("engine memory broken"))  # type: ignore[method-assign]

            with self.assertLogs("TeeBotus", level="ERROR"):
                handle_update(
                    api,
                    {"message": {"message_id": 1, "text": "/ping", "chat": {"id": 123, "type": "private"}, "from": {"id": 456}}},
                    chat_state=ChatState(),
                    runtime_context=context,
                )

        self.assertEqual(api.sent_messages, [("123", "Memory kaputt.")])

    def test_logs_incoming_and_outgoing_messages_without_content(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()

        with self.assertLogs("TeeBotus", level="INFO") as logs:
            handle_update(
                api,
                {"message": {"message_id": 55, "text": "streng geheim", "chat": {"id": 123}}},
                BotInstructions(),
                None,
                ChatState(),
            )

        log_text = "\n".join(logs.output)
        self.assertIn("Incoming Telegram message chat_id=123 message_id=55 type=text", log_text)
        self.assertIn("Outgoing Telegram message", log_text)
        self.assertIn("chat_id=123 message_id=101 type=text", log_text)
        self.assertNotIn("streng geheim", log_text)
        self.assertNotIn("Echo:", log_text)

    def test_handle_update_ignores_updates_without_chat(self) -> None:
        api = FakeAPI()

        handle_update(api, {"message": {"text": "/ping"}})

        self.assertEqual(api.sent_messages, [])

    def test_handle_update_ignores_non_text_message_with_chat(self) -> None:
        api = FakeAPI()

        handle_update(api, {"message": {"photo": [], "chat": {"id": 123}}})

        self.assertEqual(api.sent_messages, [])

    def test_handle_update_ignores_empty_text_with_bot_identity(self) -> None:
        api = FakeAPI()

        handle_update(
            api,
            {
                "message": {
                    "message_id": 56,
                    "text": "",
                    "chat": {"id": -100123, "type": "group"},
                    "from": {"id": 456, "first_name": "Ada"},
                }
            },
            bot_identity=BotIdentity(id=99, first_name="Mondbot", username="MondBot"),
        )

        self.assertEqual(api.sent_messages, [])

    def test_handle_update_uses_llm_client_for_unmatched_text_when_enabled(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        openai_client = FakeOpenAIClient()
        instructions = BotInstructions(openai_enabled=True)

        handle_update(api, {"message": {"text": "Was ist los?", "chat": {"id": 123}}}, instructions, openai_client, ChatState(), llm_client=openai_client)

        self.assertEqual(api.chat_actions, [(123, "typing")])
        self.assertEqual(api.sent_messages, [(123, "AI: Was ist los?")])

    def test_handle_update_youtube_transcript_command_sends_transcript(self) -> None:
        api = FakeAPI()

        with patch("TeeBotus.bot.transcribe_youtube_video", return_value=("Transcript text.", "YouTube-Untertitel")) as transcribe:
            handle_update(api, {"message": {"text": "/youtube_transcript https://youtu.be/abc123", "chat": {"id": 123}}}, chat_state=ChatState())

        transcribe.assert_called_once_with("https://youtu.be/abc123", local_allowed=False)
        self.assertEqual(api.chat_actions, [(123, "typing")])
        self.assertEqual(api.sent_messages, [(123, "YouTube-Transkript (YouTube-Untertitel):\n\nTranscript text.")])

    def test_handle_update_youtube_transcript_natural_request_uses_llm_pipeline(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        openai_client = FakeOpenAIClient()
        instructions = BotInstructions(openai_enabled=True)

        with patch("TeeBotus.bot.transcribe_youtube_video", return_value=("Transcript text.", "YouTube-Untertitel")) as transcribe:
            handle_update(
                api,
                {"message": {"text": "Bitte transkribiere dieses YouTube Video https://youtu.be/abc123", "chat": {"id": 123}}},
                instructions,
                openai_client,
                ChatState(),
                llm_client=openai_client,
            )

        transcribe.assert_called_once_with("https://youtu.be/abc123", local_allowed=False)
        self.assertIn("YouTube-Transkript:", openai_client.reply_inputs[-1])
        self.assertIn("Transcript text.", openai_client.reply_inputs[-1])
        self.assertEqual(api.sent_messages, [(123, "AI: Bitte transkribiere dieses YouTube Video https://youtu.be/abc123\n\nYouTube-Transkript:\n- Quelle: https://youtu.be/abc123\n- Transkriptquelle: YouTube-Untertitel\nTranscript text.")])

    def test_handle_update_youtube_transcript_asks_for_missing_link_then_uses_next_link(self) -> None:
        api = FakeAPI()
        chat_state = ChatState()

        handle_update(
            api,
            {
                "message": {
                    "text": "Kannst du ein YouTube-Video transkribieren?",
                    "chat": {"id": 123},
                    "from": {"id": 456},
                }
            },
            chat_state=chat_state,
        )

        self.assertEqual(api.sent_messages, [(123, "Schick mir bitte den YouTube-Link, den ich transkribieren soll.")])
        self.assertTrue(chat_state.has_pending_youtube_transcript_link(123, telegram_identity_key(456)))

        with patch("TeeBotus.bot.transcribe_youtube_video", return_value=("Transcript text.", "YouTube-Untertitel")) as transcribe:
            handle_update(
                api,
                {
                    "message": {
                        "text": "https://youtu.be/abc123",
                        "chat": {"id": 123},
                        "from": {"id": 456},
                    }
                },
                chat_state=chat_state,
            )

        transcribe.assert_called_once_with("https://youtu.be/abc123", local_allowed=False)
        self.assertFalse(chat_state.has_pending_youtube_transcript_link(123, telegram_identity_key(456)))
        self.assertEqual(api.sent_messages[-1], (123, "YouTube-Transkript (YouTube-Untertitel):\n\nTranscript text."))

    def test_handle_update_youtube_transcript_pending_link_is_account_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            chat_state = ChatState()
            memory_store = account_memory_store(directory)
            account_id = memory_store.resolve_or_create_account(telegram_identity_key(456), display_label="Ada")
            _, secret = memory_store.register_account(account_id)
            memory_store.link_identity(telegram_identity_key("", username="ada_l"), account_id, secret, display_label="Ada")

            handle_update(
                api,
                {
                    "message": {
                        "text": "Kannst du ein YouTube-Video transkribieren?",
                        "chat": {"id": 123},
                        "from": {"id": 456, "first_name": "Ada"},
                    }
                },
                chat_state=chat_state,
                user_memory_store=memory_store,
            )

            self.assertTrue(chat_state.has_pending_youtube_transcript_link(123, account_id))
            with patch("TeeBotus.bot.transcribe_youtube_video", return_value=("Transcript text.", "YouTube-Untertitel")) as transcribe:
                handle_update(
                    api,
                    {
                        "message": {
                            "text": "https://youtu.be/abc123",
                            "chat": {"id": 123},
                            "from": {"username": "ada_l", "first_name": "Ada"},
                        }
                    },
                    chat_state=chat_state,
                    user_memory_store=memory_store,
                )

            transcribe.assert_called_once_with("https://youtu.be/abc123", local_allowed=False, instance_name="Depressionsbot")
            self.assertFalse(chat_state.has_pending_youtube_transcript_link(123, account_id))
            self.assertEqual(api.sent_messages[-1], (123, "YouTube-Transkript (YouTube-Untertitel):\n\nTranscript text."))

    def test_handle_update_youtube_transcript_detects_freeform_video_text_request(self) -> None:
        api = FakeAPI()
        chat_state = ChatState()

        handle_update(
            api,
            {
                "message": {
                    "text": "alter mach aus dem Video text!",
                    "chat": {"id": 123},
                    "from": {"id": 456},
                }
            },
            chat_state=chat_state,
        )

        self.assertEqual(api.sent_messages, [(123, "Schick mir bitte den YouTube-Link, den ich transkribieren soll.")])
        self.assertTrue(chat_state.has_pending_youtube_transcript_link(123, telegram_identity_key(456)))

    def test_handle_update_youtube_transcript_starts_local_by_default_when_no_subtitles(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()

        with patch(
            "TeeBotus.bot.transcribe_youtube_video",
            side_effect=RuntimeError("wrong error"),
        ):
            with patch(
                "TeeBotus.bot.transcribe_youtube_video",
            ) as transcribe:
                from TeeBotus.bot import YouTubeTranscriptError

                transcribe.side_effect = [
                    YouTubeTranscriptError(
                        "keine YouTube-Untertitel gefunden.",
                        needs_local_transcription=True,
                    ),
                    ("Local transcript.", "lokales Whisper"),
                ]
                handle_update(
                    api,
                    {
                        "message": {
                            "text": "/youtube_transcript https://youtu.be/abc123",
                            "chat": {"id": 123},
                            "from": {"id": 456},
                        }
                    },
                    BotInstructions(openai_model="gpt-test"),
                    chat_state=chat_state,
                )

        self.assertEqual(
            transcribe.call_args_list,
            [
                call("https://youtu.be/abc123", local_allowed=False),
                call("https://youtu.be/abc123", local_allowed=True, live_callback=None),
            ],
        )
        self.assertEqual(chat_state.get_pending_youtube_local_options(123, telegram_identity_key(456)), "")
        self.assertEqual(api.sent_messages[-1], (123, "YouTube-Transkript (lokales Whisper):\n\nLocal transcript."))

    def test_handle_update_youtube_local_options_live_chunks_without_llm(self) -> None:
        api = FakeAPI()
        chat_state = ChatState()
        chat_state.request_youtube_local_options(123, telegram_identity_key(456), "https://youtu.be/abc123")

        def transcribe(url, local_allowed=False, live_callback=None):
            self.assertEqual(url, "https://youtu.be/abc123")
            self.assertTrue(local_allowed)
            self.assertIsNotNone(live_callback)
            live_callback("eins zwei drei vier fuenf sechs sieben acht neun zehn elf zwoelf dreizehn vierzehn fuenfzehn sechzehn siebzehn achtzehn neunzehn zwanzig einundzwanzig zweiundzwanzig dreiundzwanzig vierundzwanzig fuenfundzwanzig sechsundzwanzig")
            live_callback("", force=True)
            return " ".join(["wort"] * 26), "lokales Whisper"

        with patch("TeeBotus.bot.transcribe_youtube_video", side_effect=transcribe):
            handle_update(
                api,
                {
                    "message": {
                        "text": "live ja, llm nein",
                        "chat": {"id": 123},
                        "from": {"id": 456},
                    }
                },
                chat_state=chat_state,
            )

        self.assertEqual(len(api.sent_messages), 2)
        self.assertEqual(len(api.sent_messages[0][1].split()), 26)
        self.assertEqual(api.sent_messages[1][0], 123)
        self.assertEqual(api.sent_messages[1][1], "YouTube-Transkript (lokales Whisper):\n\n" + " ".join(["wort"] * 26))
        self.assertEqual(chat_state.get_pending_youtube_local_options(123, telegram_identity_key(456)), "")

    def test_handle_update_youtube_local_options_can_send_final_transcript_to_llm(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        openai_client = FakeOpenAIClient()
        chat_state.request_youtube_local_options(123, telegram_identity_key(456), "https://youtu.be/abc123")

        with patch("TeeBotus.bot.transcribe_youtube_video", return_value=("Local transcript.", "lokales Whisper")) as transcribe:
            handle_update(
                api,
                {
                    "message": {
                        "text": "live nein, llm ja",
                        "chat": {"id": 123},
                        "from": {"id": 456},
                    }
                },
                BotInstructions(openai_enabled=True),
                openai_client,
                chat_state,
                llm_client=openai_client,
            )

        transcribe.assert_called_once_with("https://youtu.be/abc123", local_allowed=True, live_callback=None)
        self.assertIn("YouTube-Transkript:", openai_client.reply_inputs[-1])
        self.assertIn("Local transcript.", openai_client.reply_inputs[-1])
        self.assertEqual(api.sent_messages, [(123, "AI: live nein, llm ja\n\nYouTube-Transkript:\n- Quelle: https://youtu.be/abc123\n- Transkriptquelle: lokales Whisper\nLocal transcript.")])
        self.assertEqual(chat_state.get_pending_youtube_local_options(123, telegram_identity_key(456)), "")

    def test_youtube_local_options_parse_free_words_without_live_and_with_llm(self) -> None:
        self.assertEqual(
            _parse_youtube_local_options("Bitte ohne live output transkribieren, danach ans LLM schicken."),
            (False, True),
        )
        self.assertEqual(_parse_youtube_local_options("Live aus, LLM true."), (False, True))
        self.assertEqual(_parse_youtube_local_options("liveausgabe aus, ans llm"), (False, True))
        self.assertEqual(_parse_youtube_local_options("live_output = false\nsend_to_llm = true"), (False, True))
        self.assertEqual(_parse_youtube_local_options("transkribieren, nicht live, aber llm"), (False, True))
        self.assertEqual(_parse_youtube_local_options("ohne live, mit llm"), (False, True))
        self.assertEqual(_parse_youtube_local_options("live=false send-to-llm=on"), (False, True))
        self.assertEqual(_parse_youtube_local_options("live output off, send to llm yes"), (False, True))
        self.assertEqual(_parse_youtube_local_options("keine Liveausgabe, anschließend ins LLM"), (False, True))
        self.assertEqual(_parse_youtube_local_options("nicht live; danach bitte zusammenfassen"), (False, True))
        self.assertEqual(_parse_youtube_local_options("live aus und danach analysieren"), (False, True))

    def test_youtube_local_options_parse_more_live_and_llm_variants(self) -> None:
        self.assertEqual(_parse_youtube_local_options("live-output:on llm:on"), (True, True))
        self.assertEqual(_parse_youtube_local_options("Liveausgabe aktivieren, danach zum LLM"), (True, True))
        self.assertEqual(_parse_youtube_local_options("kein liveoutput, send_to_llm true"), (False, True))
        self.assertEqual(_parse_youtube_local_options("live no, llm no"), (False, False))
        self.assertEqual(_parse_youtube_local_options("live output false, send_to_llm false"), (False, False))
        self.assertEqual(_parse_youtube_local_options("ohne live und ohne LLM, danach auswerten"), (False, False))
        self.assertEqual(_parse_youtube_local_options("nur transkribieren, kein llm"), (None, False))
        self.assertEqual(_parse_youtube_local_options("off off"), (False, False))
        self.assertEqual(_parse_youtube_local_options("ja und nein"), (True, False))
        self.assertEqual(_parse_youtube_local_options("ja, das ist richtig, nein keine ahnung"), (None, None))
        self.assertEqual(_parse_youtube_local_options("keine ahnung, ja nein"), (None, None))

    def test_youtube_local_options_parse_broad_context_phrasing(self) -> None:
        cases = {
            "transkribier das, waehrenddessen bitte nichts posten, danach an GPT": (False, True),
            "kein Paste waehrenddessen, anschliessend OpenAI auswerten lassen": (False, True),
            "erst am Ende senden, dann zusammenfassen": (False, True),
            "poste chunks live und lass GPT danach analysieren": (True, True),
            "ohne Zwischenstaende, per KI zusammenfassen": (False, True),
            "zwischendurch nichts schicken, am Ende Fazit": (False, True),
            "keine Haeppchen, danach Summary": (False, True),
            "parallel senden, OpenAI an": (True, True),
            "nicht spammen unterwegs, aber an dich geben": (False, True),
            "schick's an dein Modell": (None, True),
            "Live bitte, keine Auswertung": (True, False),
            "nur Abschrift, nicht analysieren": (None, False),
            "nicht an GPT, live aus": (False, False),
            "OpenAI off, aber live posten": (True, False),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(_parse_youtube_local_options(text), expected)

    def test_youtube_local_options_parse_llm_response_json(self) -> None:
        self.assertEqual(
            _parse_youtube_local_options_from_llm_response('{"live_output": false, "send_to_llm": true, "confidence": 0.91}'),
            (False, True),
        )
        self.assertEqual(
            _parse_youtube_local_options_from_llm_response(
                'Sauber erkannt:\n```json\n{"live_output": "no", "send_to_llm": "yes", "confidence": 0.88}\n```'
            ),
            (False, True),
        )
        self.assertIsNone(
            _parse_youtube_local_options_from_llm_response('{"live_output": false, "send_to_llm": true}')
        )
        self.assertIsNone(
            _parse_youtube_local_options_from_llm_response('{"live_output": null, "send_to_llm": true}')
        )
        self.assertIsNone(
            _parse_youtube_local_options_from_llm_response('{"live_output": false, "send_to_llm": true, "confidence": 0.42}')
        )

    def test_handle_update_youtube_local_options_uses_llm_fallback_and_records_phrase(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        openai_client = SequenceOpenAIClient(['{"live_output": false, "send_to_llm": true, "confidence": 0.91}', "AI: transcript summary"])
        chat_state.request_youtube_local_options(123, telegram_identity_key(456), "https://youtu.be/abc123")

        with tempfile.TemporaryDirectory() as directory:
            instructions = BotInstructions(openai_enabled=True)
            with patch.dict(os.environ, {"TELEGRAM_BOT_INSTANCES_DIR": str(Path(directory) / "instances")}, clear=False):
                with patch("TeeBotus.bot.transcribe_youtube_video", return_value=("Local transcript.", "lokales Whisper")) as transcribe:
                    handle_update(
                        api,
                        {
                            "message": {
                                "text": "Mach das ohne Gelaber unterwegs, LLM ja https://youtu.be/abc123",
                                "chat": {"id": 123},
                                "from": {"id": 456},
                            }
                        },
                        instructions,
                        openai_client,
                        chat_state,
                        instance_name="Demo",
                        llm_client=openai_client,
                    )

            transcribe.assert_called_once_with("https://youtu.be/abc123", local_allowed=True, live_callback=None, instance_name="Demo")
            self.assertEqual(chat_state.get_pending_youtube_local_options(123, telegram_identity_key(456)), "")
            self.assertIn("Local transcript.", openai_client.reply_inputs[-1])

            miss_path = Path(directory) / "instances" / "Demo" / "data" / "YouTube_Parser_Misses.jsonl"
            entries = read_jsonl(miss_path)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["context"], "pending-options")
            self.assertEqual(entries[0]["parser_live_output"], None)
            self.assertEqual(entries[0]["parser_send_to_llm"], True)
            self.assertEqual(entries[0]["llm_live_output"], False)
            self.assertEqual(entries[0]["llm_send_to_llm"], True)
            self.assertIn("<youtube-url>", entries[0]["formulation"])
            self.assertNotIn("https://youtu.be/abc123", entries[0]["formulation"])
            with patch.dict(os.environ, {"TELEGRAM_BOT_INSTANCES_DIR": str(Path(directory) / "instances")}, clear=False):
                self.assertEqual(
                    _parse_youtube_local_options(
                        "Mach das ohne Gelaber unterwegs, LLM ja https://youtu.be/other",
                        instance_name="Demo",
                    ),
                    (False, True),
                )
                self.assertEqual(
                    _parse_youtube_local_options(
                        "Bitte transkribiere https://youtu.be/other und mach das ohne Gelaber unterwegs, LLM ja",
                        instance_name="Demo",
                    ),
                    (False, True),
                )

    def test_youtube_local_options_learned_phrases_need_specific_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            miss_path = Path(directory) / "instances" / "Demo" / "data" / "YouTube_Parser_Misses.jsonl"
            miss_path.parent.mkdir(parents=True)
            miss_path.write_text(
                json.dumps(
                    {
                        "formulation": "LLM ja <youtube-url>",
                        "llm_live_output": False,
                        "llm_send_to_llm": True,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"TELEGRAM_BOT_INSTANCES_DIR": str(Path(directory) / "instances")}, clear=False):
                self.assertEqual(
                    _parse_youtube_local_options("Andere Formulierung, LLM ja https://youtu.be/other", instance_name="Demo"),
                    (None, True),
                )

    def test_youtube_learned_options_do_not_override_explicit_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            miss_path = Path(directory) / "instances" / "Demo" / "data" / "YouTube_Parser_Misses.jsonl"
            miss_path.parent.mkdir(parents=True)
            miss_path.write_text(
                json.dumps(
                    {
                        "formulation": "poste live ja llm nein",
                        "llm_live_output": True,
                        "llm_send_to_llm": False,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"TELEGRAM_BOT_INSTANCES_DIR": str(Path(directory) / "instances")}, clear=False):
                self.assertEqual(
                    _parse_youtube_local_options("poste live nein llm ja", instance_name="Demo"),
                    (False, True),
                )

    def test_handle_update_youtube_transcript_uses_llm_option_fallback_from_initial_request(self) -> None:
        from TeeBotus.bot import YouTubeTranscriptError
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        openai_client = SequenceOpenAIClient(['{"live_output": false, "send_to_llm": true, "confidence": 0.91}', "AI: transcript summary"])

        transcribe_calls = [
            YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True),
            ("Local transcript.", "lokales Whisper"),
        ]

        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"TELEGRAM_BOT_INSTANCES_DIR": str(Path(directory) / "instances")}, clear=False):
                with patch("TeeBotus.bot.transcribe_youtube_video", side_effect=transcribe_calls) as transcribe:
                    handle_update(
                        api,
                        {
                            "message": {
                                "text": "Bitte transkribiere https://youtu.be/abc123 ohne Gelaber unterwegs, LLM ja",
                                "chat": {"id": 123},
                                "from": {"id": 456},
                            }
                        },
                        BotInstructions(openai_enabled=True),
                        openai_client,
                        chat_state,
                        instance_name="Demo",
                        llm_client=openai_client,
                    )

            self.assertEqual(
                transcribe.call_args_list,
                [
                    call("https://youtu.be/abc123", local_allowed=False, instance_name="Demo"),
                    call("https://youtu.be/abc123", local_allowed=True, live_callback=None, instance_name="Demo"),
                ],
            )
            self.assertEqual(chat_state.get_pending_youtube_local_options(123, telegram_identity_key(456)), "")
            self.assertIn("Local transcript.", openai_client.reply_inputs[-1])

            miss_path = Path(directory) / "instances" / "Demo" / "data" / "YouTube_Parser_Misses.jsonl"
            entries = read_jsonl(miss_path)
            self.assertEqual(entries[0]["context"], "initial-request")
            self.assertEqual(entries[0]["parser_live_output"], None)
            self.assertEqual(entries[0]["parser_send_to_llm"], True)
            self.assertEqual(entries[0]["llm_live_output"], False)
            self.assertEqual(entries[0]["llm_send_to_llm"], True)

    def test_handle_update_youtube_transcript_starts_local_job_from_free_words(self) -> None:
        from TeeBotus.bot import YouTubeTranscriptError
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        runner = FakeJobRunner()
        openai_client = FakeOpenAIClient()

        transcribe_calls = [
            YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True),
            ("Local transcript.", "lokales Whisper"),
        ]

        with patch("TeeBotus.bot.transcribe_youtube_video", side_effect=transcribe_calls) as transcribe:
            handle_update(
                api,
                {
                    "message": {
                        "text": "Rate was du machen darfst ^^ Versuch's nochmal. Live aus, LLM true. transkribiere: https://youtu.be/np_ylvc8Zj8?is=Ao0T6ywvPnln3Rms",
                        "chat": {"id": 123},
                        "from": {"id": 456},
                    }
                },
                BotInstructions(openai_enabled=True),
                openai_client,
                chat_state,
                youtube_job_runner=runner,
                llm_client=openai_client,
            )

            self.assertEqual(len(runner.jobs), 1)
            self.assertEqual(api.sent_messages, [(123, "Lokale YouTube-Transkription gestartet. Ich melde mich, sobald sie fertig ist.")])
            self.assertEqual(chat_state.get_pending_youtube_local_options(123, telegram_identity_key(456)), "")

            runner.jobs[0]()

        self.assertEqual(transcribe.call_args_list[0], call("https://youtu.be/np_ylvc8Zj8?is=Ao0T6ywvPnln3Rms", local_allowed=False))
        self.assertEqual(
            transcribe.call_args_list[1],
            call("https://youtu.be/np_ylvc8Zj8?is=Ao0T6ywvPnln3Rms", local_allowed=True, live_callback=None),
        )
        self.assertIn("Local transcript.", openai_client.reply_inputs[-1])
        self.assertEqual(len(api.sent_messages), 2)
        self.assertTrue(api.sent_messages[-1][1].startswith("AI: Rate was du machen darfst"))

    def test_handle_update_youtube_local_options_queues_child_job_when_runner_is_available(self) -> None:
        api = FakeAPI()
        chat_state = ChatState()
        runner = FakeJobRunner()
        chat_state.request_youtube_local_options(123, telegram_identity_key(456), "https://youtu.be/abc123")

        with patch("TeeBotus.bot.transcribe_youtube_video", return_value=("Local transcript.", "lokales Whisper")) as transcribe:
            handle_update(
                api,
                {
                    "message": {
                        "text": "live nein, llm nein",
                        "chat": {"id": 123},
                        "from": {"id": 456},
                    }
                },
                chat_state=chat_state,
                youtube_job_runner=runner,
            )

            transcribe.assert_not_called()
            self.assertEqual(len(runner.jobs), 1)
            self.assertEqual(api.sent_messages, [(123, "Lokale YouTube-Transkription gestartet. Ich melde mich, sobald sie fertig ist.")])

            runner.jobs[0]()

        transcribe.assert_called_once_with("https://youtu.be/abc123", local_allowed=True, live_callback=None)
        self.assertEqual(api.sent_messages[-1], (123, "YouTube-Transkript (lokales Whisper):\n\nLocal transcript."))

    def test_youtube_local_transcription_job_ignores_telegram_network_errors(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState(instance_name="Depressionsbot")
        instructions = BotInstructions()

        def transcribe(url, local_allowed=True, live_callback=None):
            self.assertTrue(local_allowed)
            self.assertIsNotNone(live_callback)
            live_callback("eins zwei drei vier fuenf")
            live_callback("", force=True)
            return "Fertiges Transkript.", "lokales Whisper"

        def fail_send_message(chat_id, text):
            raise TelegramNetworkError("Telegram network error: reset")

        api.send_message = fail_send_message  # type: ignore[assignment]

        with patch("TeeBotus.bot.transcribe_youtube_video", side_effect=transcribe):
            with self.assertLogs("TeeBotus", level="WARNING") as logs:
                _run_youtube_local_transcription_job(
                    api,
                    chat_state,
                    123,
                    {"text": "live ja", "chat": {"id": 123}, "from": {"id": 456}},
                    "live ja",
                    "https://youtu.be/abc123",
                    True,
                    False,
                    None,
                    None,
                    instructions,
                    None,
                    BotIdentity(),
                    False,
                    None,
                )

        log_text = "\n".join(logs.output)
        self.assertIn("Telegram request failed while sending YouTube live output", log_text)
        self.assertIn("Telegram request failed while sending YouTube transcription completion", log_text)

    def test_handle_update_youtube_transcript_timeout_does_not_crash(self) -> None:
        api = FakeAPI()

        with patch("TeeBotus.bot.transcribe_youtube_video", side_effect=TimeoutError("timed out")):
            handle_update(api, {"message": {"text": "/youtube_transcript https://youtu.be/abc123", "chat": {"id": 123}}}, chat_state=ChatState())

        self.assertEqual(
            api.sent_messages,
            [(123, "YouTube-Transkript fehlgeschlagen: Timeout bei der Transkription (timed out).")],
        )

    def test_group_first_contact_must_address_bot_by_telegram_name(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        openai_client = FakeOpenAIClient()
        chat_state = ChatState()
        instructions = BotInstructions(openai_enabled=True)
        bot_identity = BotIdentity(id=99, first_name="Bote_der_Wahrheit Bot", username="BoteDerWahrheitBot")

        handle_update(
            api,
            {
                "message": {
                    "message_id": 70,
                    "text": "Hallo zusammen.",
                    "chat": {"id": -100123, "type": "group", "title": "Debatte"},
                    "from": {"id": 456, "first_name": "Ada"},
                }
            },
            instructions,
            openai_client,
            chat_state,
            None,
            bot_identity,
            llm_client=openai_client,
        )

        self.assertEqual(openai_client.reply_inputs, [])
        self.assertEqual(api.sent_messages, [])

        handle_update(
            api,
            {
                "message": {
                    "message_id": 71,
                    "text": "Hallo @BoteDerWahrheitBot.",
                    "chat": {"id": -100123, "type": "group", "title": "Debatte"},
                    "from": {"id": 456, "first_name": "Ada"},
                }
            },
            instructions,
            openai_client,
            chat_state,
            None,
            bot_identity,
            llm_client=openai_client,
        )

        self.assertEqual(api.sent_messages, [(-100123, "Ich bin Bote der Wahrheit.\n\nAI: Hallo @BoteDerWahrheitBot.")])

    def test_group_first_contact_can_address_bot_by_persistent_alias(self) -> None:
        api = FakeAPI()
        openai_client = FakeOpenAIClient()
        chat_state = ChatState()
        instructions = BotInstructions(openai_enabled=True, user_memory_enabled=True)
        bot_identity = BotIdentity(id=99, first_name="Depressionsbot", username="DepressionsBot")
        with tempfile.TemporaryDirectory() as directory:
            user_memory_store = AccountStore(
                Path(directory) / "accounts",
                "Demo",
                StaticSecretProvider(b"x" * 32),
            )
            identity = telegram_identity_key(456, display_name="Ada")
            account_id = user_memory_store.resolve_or_create_account(identity, display_label="Ada")
            user_memory_store.append_structured_memory_entry(
                account_id,
                {"id": "mem_alias", "user_text": "Ich nenne dich ab jetzt Mondhase.", "bot_text": "Okay."},
            )

            handle_update(
                api,
                {
                    "message": {
                        "message_id": 72,
                        "text": "Mondhase, bitte antworte.",
                        "chat": {"id": -100123, "type": "group", "title": "Debatte"},
                        "from": {"id": 456, "first_name": "Ada"},
                    }
                },
                instructions,
                openai_client,
                chat_state,
                user_memory_store,
                bot_identity,
                llm_client=openai_client,
            )

        self.assertEqual(api.sent_messages, [(-100123, "Ich bin Depressionsbot.\n\nAI: Mondhase, bitte antworte.")])

    def test_group_first_contact_can_address_bot_by_generated_initials(self) -> None:
        api = FakeAPI()
        openai_client = FakeOpenAIClient()
        chat_state = ChatState()
        instructions = BotInstructions(openai_enabled=True)
        bot_identity = BotIdentity(id=99, first_name="Bote_der_Wahrheit Bot", username="BoteDerWahrheitBot")

        handle_update(
            api,
            {
                "message": {
                    "message_id": 73,
                    "text": "BdW, bitte antworte.",
                    "chat": {"id": -100123, "type": "group", "title": "Debatte"},
                    "from": {"id": 456, "first_name": "Ada"},
                }
            },
            instructions,
            openai_client,
            chat_state,
            None,
            bot_identity,
            llm_client=openai_client,
        )

        self.assertEqual(api.sent_messages, [(-100123, "Ich bin Bote der Wahrheit.\n\nAI: BdW, bitte antworte.")])

    def test_group_first_contact_can_address_bot_by_configured_alias(self) -> None:
        instructions = BotInstructions(openai_enabled=True, bot_aliases=("TBL", "tl", "telo"))
        bot_identity = BotIdentity(id=99, first_name="TeeBotus - Logger", username="TeeBotusLoggerBot")

        for index, alias in enumerate(("TBL", "tl", "telo"), start=74):
            with self.subTest(alias=alias):
                api = FakeAPI()
                openai_client = FakeOpenAIClient()
                chat_state = ChatState()

                handle_update(
                    api,
                    {
                        "message": {
                            "message_id": index,
                            "text": f"{alias}, bitte Status.",
                            "chat": {"id": -100123, "type": "group", "title": "Admin"},
                            "from": {"id": 456, "first_name": "Ada"},
                        }
                    },
                    instructions,
                    openai_client,
                    chat_state,
                    None,
                    bot_identity,
                    llm_client=openai_client,
                )

                self.assertEqual(api.sent_messages, [(-100123, f"Ich bin TeeBotus Logger.\n\nAI: {alias}, bitte Status.")])

    def test_first_contact_start_removes_configured_instance_identity(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        instructions = BotInstructions(start="Hallo{name_suffix}. Ich bin Depressionsbot. Sende /help fuer die Befehle.")
        bot_identity = BotIdentity(id=99, first_name="Telegrambotname", username="TelegramBot")

        handle_update(
            api,
            {
                "message": {
                    "text": "/start",
                    "chat": {"id": 123, "type": "private"},
                    "from": {"id": 456, "first_name": "Ada"},
                }
            },
            instructions,
            None,
            chat_state,
            None,
            bot_identity,
        )

        self.assertEqual(
            api.sent_messages,
            [(123, "Ich bin Telegrambotname.\n\nHallo, Ada. Sende /help fuer die Befehle.")],
        )

    def test_start_uses_telegram_identity_for_known_sender(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        chat_state.mark_sender_seen("456")
        instructions = BotInstructions(start="Hallo{name_suffix}. Ich bin Depressionsbot. Sende /help fuer die Befehle.")
        bot_identity = BotIdentity(id=99, first_name="Telegrambotname", username="TelegramBot")

        handle_update(
            api,
            {
                "message": {
                    "text": "/start",
                    "chat": {"id": 123, "type": "private"},
                    "from": {"id": 456, "first_name": "Ada"},
                }
            },
            instructions,
            None,
            chat_state,
            None,
            bot_identity,
        )

        self.assertEqual(
            api.sent_messages,
            [(123, "Ich bin Telegrambotname.\n\nHallo, Ada. Sende /help fuer die Befehle.")],
        )

    def test_known_sender_can_use_any_name_after_first_contact(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        openai_client = FakeOpenAIClient()
        chat_state = ChatState()
        instructions = BotInstructions(openai_enabled=True)
        bot_identity = BotIdentity(id=99, first_name="Depressionsbot", username="DepressionsBot")

        handle_update(
            api,
            {
                "message": {
                    "text": "Depressionsbot, hallo.",
                    "chat": {"id": -100123, "type": "group", "title": "Debatte"},
                    "from": {"id": 456, "first_name": "Ada"},
                }
            },
            instructions,
            openai_client,
            chat_state,
            None,
            bot_identity,
            llm_client=openai_client,
        )
        handle_update(
            api,
            {
                "message": {
                    "text": "Kleiner Mond, bist du da?",
                    "chat": {"id": -100123, "type": "group", "title": "Debatte"},
                    "from": {"id": 456, "first_name": "Ada"},
                }
            },
            instructions,
            openai_client,
            chat_state,
            None,
            bot_identity,
            llm_client=openai_client,
        )

        self.assertEqual(api.sent_messages[0], (-100123, "Ich bin Depressionsbot.\n\nAI: Depressionsbot, hallo."))
        self.assertEqual(api.sent_messages[1], (-100123, "AI: Kleiner Mond, bist du da?"))

    def test_username_fallback_sender_is_not_first_contact_repeatedly(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        openai_client = FakeOpenAIClient()
        chat_state = ChatState()
        instructions = BotInstructions(openai_enabled=True)
        bot_identity = BotIdentity(id=99, first_name="Depressionsbot", username="DepressionsBot")
        message_base = {
            "chat": {"id": 123, "type": "private"},
            "from": {"username": "AdaUser", "first_name": "Ada"},
        }

        handle_update(
            api,
            {"message": {**message_base, "text": "Hallo"}},
            instructions,
            openai_client,
            chat_state,
            None,
            bot_identity,
            llm_client=openai_client,
        )
        handle_update(
            api,
            {"message": {**message_base, "text": "Nochmal"}},
            instructions,
            openai_client,
            chat_state,
            None,
            bot_identity,
            llm_client=openai_client,
        )

        self.assertEqual(api.sent_messages[0], (123, "Ich bin Depressionsbot.\n\nAI: Hallo"))
        self.assertEqual(api.sent_messages[1], (123, "AI: Nochmal"))

    def test_privacy_confirmation_is_persistent_until_memory_reset(self) -> None:
        from TeeBotus.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            instructions = BotInstructions(openai_enabled=True, user_memory_enabled=True)
            bot_identity = BotIdentity(id=99, first_name="Depressionsbot", username="DepressionsBot")
            llm_client = FakeOpenAIClient()
            memory_store = account_memory_store(directory)
            message_base = {
                "chat": {"id": 123, "type": "private"},
                "from": {"id": 456, "first_name": "Ada"},
            }

            handle_update(
                api,
                {"message": {**message_base, "text": "Datenschutz bestätigt"}},
                instructions,
                FakeOpenAIClient(),
                ChatState(),
                memory_store,
                bot_identity,
                llm_client=llm_client,
            )
            account_id = memory_store.get_account_for_identity("telegram:user:456")

            self.assertIsNotNone(account_id)
            assert account_id is not None
            self.assertTrue(memory_store.has_privacy_confirmation(account_id))
            self.assertEqual(
                api.sent_messages[-1],
                (123, "Datenschutz ist bestätigt. Ich frage dich nicht erneut, solange diese Einstellung nicht durch /reset_memorys entfernt wird."),
            )

            handle_update(
                api,
                {"message": {**message_base, "text": "Hallo"}},
                instructions,
                FakeOpenAIClient(),
                ChatState(),
                memory_store,
                bot_identity,
                llm_client=llm_client,
            )

            self.assertEqual(api.sent_messages[-1], (123, "AI: Hallo"))

            memory_store.reset_structured_memory(account_id)
            self.assertFalse(memory_store.has_privacy_confirmation(account_id))

            handle_update(
                api,
                {"message": {**message_base, "text": "Nochmal"}},
                instructions,
                FakeOpenAIClient(),
                ChatState(),
                memory_store,
                bot_identity,
                llm_client=llm_client,
            )

            self.assertEqual(api.sent_messages[-1], (123, "Ich bin Depressionsbot.\n\nAI: Nochmal"))

    def test_command_targeting_other_bot_is_ignored(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        chat_state.mark_sender_seen("456")

        handle_update(
            api,
            {
                "message": {
                    "text": "/ping@OtherBot",
                    "chat": {"id": -100123, "type": "group", "title": "Debatte"},
                    "from": {"id": 456, "first_name": "Ada"},
                }
            },
            BotInstructions(),
            None,
            chat_state,
            None,
            BotIdentity(id=99, first_name="Depressionsbot", username="DepressionsBot"),
        )

        self.assertEqual(api.sent_messages, [])

    def test_openai_input_includes_bot_identity_context(self) -> None:
        openai_input = _build_openai_user_input(
            {
                "text": "Hallo",
                "chat": {"id": 123, "type": "private"},
                "from": {"id": 456, "first_name": "Ada"},
            },
            "Hallo",
            bot_identity=BotIdentity(id=99, first_name="Bote_der_Wahrheit Bot", username="BoteDerWahrheitBot"),
        )

        self.assertIn("- bot_id: 99", openai_input)
        self.assertIn("- bot_name: Bote der Wahrheit", openai_input)
        self.assertIn("- bot_username: @BoteDerWahrheitBot", openai_input)

    def test_openai_input_includes_telegram_reply_context(self) -> None:
        openai_input = _build_openai_user_input(
            {
                "text": "Was meinst du damit?",
                "chat": {"id": 123, "type": "private"},
                "from": {"id": 456, "first_name": "Ada"},
                "reply_to_message": {"message_id": 41, "text": "Die referenzierte Nachricht."},
            },
            "Was meinst du damit?",
        )

        self.assertIn("Telegram-Antwortbezug:", openai_input)
        self.assertIn("Die referenzierte Nachricht.", openai_input)
        self.assertTrue(openai_input.endswith("Nachricht:\nWas meinst du damit?"))

    def test_openai_input_includes_sender_context_for_group_messages(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        openai_client = FakeOpenAIClient()
        instructions = BotInstructions(openai_enabled=True)

        handle_update(
            api,
            {
                "message": {
                    "message_id": 77,
                    "text": "Was ist los?",
                    "chat": {"id": -100123, "type": "group", "title": "Debatte"},
                    "from": {
                        "id": 456,
                        "first_name": "Ada",
                        "last_name": "Lovelace",
                        "username": "ada_l",
                    },
                }
            },
            instructions,
            openai_client,
            ChatState(),
            llm_client=openai_client,
        )

        self.assertEqual(len(openai_client.reply_inputs), 1)
        openai_input = openai_client.reply_inputs[0]
        self.assertIn("- chat_id: -100123", openai_input)
        self.assertIn("- chat_type: group", openai_input)
        self.assertIn("- chat_title: Debatte", openai_input)
        self.assertIn("- sender_id: 456", openai_input)
        self.assertIn("- sender_name: Ada Lovelace", openai_input)
        self.assertIn("- sender_username: @ada_l", openai_input)
        self.assertTrue(openai_input.endswith("Nachricht:\nWas ist los?"))

    def test_openai_input_uses_sender_chat_when_user_sender_is_missing(self) -> None:
        openai_input = _build_openai_user_input(
            {
                "text": "Anonyme Nachricht",
                "chat": {"id": -100123, "type": "supergroup", "title": "Debatte"},
                "sender_chat": {"id": -100999, "title": "Adminteam"},
            },
            "Anonyme Nachricht",
        )

        self.assertIn("- sender_id: -100999", openai_input)
        self.assertIn("- sender_name: Adminteam", openai_input)
        self.assertIn("- sender_username: unbekannt", openai_input)

    def test_openai_input_honors_optional_bibliothekar_citation_requirement(self) -> None:
        openai_input = _build_openai_user_input(
            {
                "text": "Was steht im Buch?",
                "chat": {"id": 123, "type": "private"},
                "from": {"id": 456, "first_name": "Ada"},
            },
            "Was steht im Buch?",
            library_text='{"selected_library_chunks":[{"file":"buch.txt","chunk_id":"chunk-1"}]}',
            require_library_citations=False,
        )

        self.assertIn("Bibliothekar-Quellenkontext", openai_input)
        self.assertIn("fuer reine Hintergrundnutzung reicht Paraphrase", openai_input)
        self.assertNotIn("konkrete Aussagen daraus ableitest", openai_input)

    def test_handle_update_transcribes_voice_and_processes_result_with_openai(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        api.file_paths["file_1"] = "voice/file_1.oga"
        api.file_data["voice/file_1.oga"] = b"voice-audio"
        openai_client = FakeOpenAIClient()
        instructions = BotInstructions(openai_enabled=True)

        handle_update(
            api,
            {
                "message": {
                    "message_id": 60,
                    "voice": {"file_id": "file_1"},
                    "chat": {"id": 123, "type": "group", "title": "Debatte"},
                    "from": {"id": 456, "first_name": "Ada"},
                }
            },
            instructions,
            openai_client,
            ChatState(),
            llm_client=openai_client,
        )

        self.assertEqual(api.file_path_requests, ["file_1"])
        self.assertEqual(api.download_requests, ["voice/file_1.oga"])
        self.assertEqual(openai_client.transcribed_audios, [(b"voice-audio", "file_1.ogg")])
        self.assertEqual(openai_client.transcription_models, ["gpt-4o-mini-transcribe"])
        self.assertIn("- sender_id: 456", openai_client.reply_inputs[0])
        self.assertIn("- sender_name: Ada", openai_client.reply_inputs[0])
        self.assertEqual(api.chat_actions, [(123, "typing"), (123, "typing")])
        self.assertEqual(api.sent_messages, [(123, "AI: Was ist los?")])

    def test_handle_update_transcribes_voice_locally_without_openai_client(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        api.file_paths["file_1"] = "voice/file_1.oga"
        api.file_data["voice/file_1.oga"] = b"voice-audio"
        instructions = BotInstructions(
            openai_enabled=False,
            openai_transcription_backend="local",
            commands={"/ping": "Pong"},
        )

        with patch("TeeBotus.adapters.telegram_runtime.transcribe_local_audio", return_value="/ping") as transcribe:
            handle_update(
                api,
                {
                    "message": {
                        "message_id": 60,
                        "voice": {"file_id": "file_1"},
                        "chat": {"id": 123, "type": "group", "title": "Debatte"},
                        "from": {"id": 456, "first_name": "Ada"},
                    }
                },
                instructions,
                None,
                ChatState(),
            )

        transcribe.assert_called_once()
        self.assertEqual(api.file_path_requests, ["file_1"])
        self.assertEqual(api.download_requests, ["voice/file_1.oga"])
        self.assertEqual(api.sent_messages, [(123, "Pong")])

    def test_handle_update_voice_transcription_timeout_does_not_crash(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        api.file_paths["file_1"] = "voice/file_1.oga"
        api.file_data["voice/file_1.oga"] = b"voice-audio"
        openai_client = FakeOpenAIClient()
        openai_client.transcribe_audio = lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("timed out"))

        handle_update(
            api,
            {
                "message": {
                    "message_id": 60,
                    "voice": {"file_id": "file_1"},
                    "chat": {"id": 123},
                    "from": {"id": 456},
                }
            },
            BotInstructions(),
            openai_client,
            ChatState(),
        )

        self.assertEqual(api.sent_messages, [(123, BotInstructions().openai_transcription_error)])

    def test_transcribed_voice_stores_only_text_in_user_memory(self) -> None:
        from TeeBotus.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            api.file_paths["file_1"] = "voice/file_1.oga"
            api.file_data["voice/file_1.oga"] = b"voice-audio"
            openai_client = FakeOpenAIClient()
            openai_client.transcription_text = "Mein Voice-Geheimnis ist Mondlicht."
            instructions = BotInstructions(
                openai_enabled=True,
                user_memory_enabled=True,
            )

            handle_update(
                api,
                {
                    "message": {
                        "message_id": 60,
                        "voice": {"file_id": "file_1"},
                        "chat": {"id": 123, "type": "group", "title": "Debatte"},
                        "from": {"id": 456, "first_name": "Ada"},
                    }
                },
                instructions,
                openai_client,
                ChatState(),
                account_memory_store(directory),
                llm_client=openai_client,
            )

            memory_store = account_memory_store(directory)
            memory_path = account_memory_dir(memory_store, 456) / "User_Memory_Index.json"
            memory_text = memory_path.read_bytes()
            payload = read_account_memory_index(memory_store, 456)
            entries = read_account_memory_entries(memory_store, 456)
            self.assertIn("Mein Voice-Geheimnis ist Mondlicht.", entries[0]["user_text"])
            self.assertEqual(entries[0]["source"]["message_ref"], "60")
            self.assertIn(entries[0]["id"], payload["index"]["entries"])
            self.assertNotIn(b"voice-audio", memory_text)
            self.assertNotIn("voice-audio", json.dumps(entries, ensure_ascii=False))

    def test_transcribe_voice_audio_retries_fallback_after_empty_primary_transcript(self) -> None:
        from TeeBotus.instructions import BotInstructions

        openai_client = FakeOpenAIClient()
        openai_client.transcription_texts = ["", "Hallo aus Fallback"]
        instructions = BotInstructions(
            openai_transcription_model="gpt-4o-mini-transcribe",
            openai_transcription_fallback_model="whisper-1",
        )

        with self.assertLogs("TeeBotus", level="WARNING") as logs:
            text = _transcribe_voice_audio(openai_client, b"voice-audio", "file_1.ogg", instructions)

        self.assertEqual(text, "Hallo aus Fallback")
        self.assertEqual(openai_client.transcription_models, ["gpt-4o-mini-transcribe", "whisper-1"])
        self.assertIn("Retrying with fallback_model=whisper-1", "\n".join(logs.output))

    def test_local_voice_transcription_does_not_fallback_to_openai(self) -> None:
        from TeeBotus.core.local_transcription import LocalTranscriptionError
        from TeeBotus.instructions import BotInstructions

        openai_client = FakeOpenAIClient()
        instructions = BotInstructions(openai_transcription_backend="local")

        with patch(
            "TeeBotus.adapters.telegram_runtime.transcribe_local_audio",
            side_effect=LocalTranscriptionError("kaputt"),
        ):
            with self.assertRaises(LocalTranscriptionError):
                _transcribe_voice_audio(openai_client, b"voice-audio", "file_1.ogg", instructions)

        self.assertEqual(openai_client.transcribed_audios, [])

    def test_transcribe_voice_audio_does_not_retry_when_fallback_is_disabled(self) -> None:
        from TeeBotus.instructions import BotInstructions

        openai_client = FakeOpenAIClient()
        openai_client.transcription_text = ""
        instructions = BotInstructions(openai_transcription_fallback_model="")

        text = _transcribe_voice_audio(openai_client, b"voice-audio", "file_1.ogg", instructions)

        self.assertEqual(text, "")
        self.assertEqual(openai_client.transcription_models, ["gpt-4o-mini-transcribe"])

    def test_handle_update_transcribed_voice_can_trigger_static_reply(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        api.file_paths["file_1"] = "voice/file_1.oga"
        openai_client = FakeOpenAIClient()
        openai_client.transcription_text = "/ping"

        handle_update(
            api,
            {"message": {"voice": {"file_id": "file_1"}, "chat": {"id": 123}}},
            BotInstructions(),
            openai_client,
            ChatState(),
        )

        self.assertEqual(api.sent_messages, [(123, "Pong")])

    def test_handle_update_voice_requires_openai_client(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()

        handle_update(
            api,
            {"message": {"voice": {"file_id": "file_1"}, "chat": {"id": 123}}},
            BotInstructions(openai_enabled=True),
            None,
            ChatState(),
        )

        self.assertEqual(api.file_path_requests, [])
        self.assertEqual(api.sent_messages, [(123, "OpenAI ist aktiviert, aber OPENAI_API_KEY ist nicht gesetzt.")])

    def test_handle_update_voice_reports_empty_transcription(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        api.file_paths["file_1"] = "voice/file_1.oga"
        openai_client = FakeOpenAIClient()
        openai_client.transcription_text = ""

        handle_update(
            api,
            {"message": {"voice": {"file_id": "file_1"}, "chat": {"id": 123}}},
            BotInstructions(openai_enabled=True, openai_transcription_fallback_model=""),
            openai_client,
            ChatState(),
        )

        self.assertEqual(api.sent_messages, [(123, "Ich konnte in der Sprachnachricht keinen Text erkennen.")])

    def test_logs_incoming_voice_without_transcribed_content(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        api.file_paths["file_1"] = "voice/file_1.oga"
        openai_client = FakeOpenAIClient()
        openai_client.transcription_text = "streng geheim"

        with self.assertLogs("TeeBotus", level="INFO") as logs:
            handle_update(
                api,
                {"message": {"message_id": 60, "voice": {"file_id": "file_1"}, "chat": {"id": 123}}},
                BotInstructions(),
                openai_client,
                ChatState(),
            )

        log_text = "\n".join(logs.output)
        self.assertIn("Incoming Telegram message chat_id=123 message_id=60 type=voice", log_text)
        self.assertIn("Outgoing Telegram message", log_text)
        self.assertIn("chat_id=123 message_id=101 type=text", log_text)
        self.assertNotIn("streng geheim", log_text)
        self.assertNotIn("Echo:", log_text)

    def test_voice_command_sends_generated_voice(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        openai_client = FakeOpenAIClient()

        handle_update(api, {"message": {"text": "/voice Hallo Welt", "chat": {"id": 123}}}, BotInstructions(), openai_client, ChatState())

        self.assertEqual(openai_client.voice_texts, ["Hallo Welt"])
        self.assertEqual(api.chat_actions, [(123, "record_voice"), (123, "upload_voice")])
        self.assertEqual(api.sent_voices, [(123, b"voice-bytes", "voice.ogg", "audio/ogg")])

    def test_voice_command_uses_account_birth_city_dialect(self) -> None:
        api = FakeAPI()
        openai_client = FakeOpenAIClient()
        chat_state = ChatState()
        with tempfile.TemporaryDirectory() as directory:
            memory_store = AccountStore(Path(directory) / "accounts", "Depressionsbot", StaticSecretProvider(b"t" * 32))
            instructions = BotInstructions(openai_voice_instructions="Basisstimme.", user_memory_enabled=True)
            account_id = memory_store.resolve_or_create_account(telegram_identity_key(456))
            memory_store.confirm_privacy(account_id, source="telegram")

            handle_update(
                api,
                {"message": {"text": "Ich bin in Nürnberg geboren.", "chat": {"id": 123}, "from": {"id": 456}}},
                instructions,
                openai_client,
                chat_state,
                user_memory_store=memory_store,
            )
            handle_update(
                api,
                {"message": {"text": "/voice Hallo Welt", "chat": {"id": 123}, "from": {"id": 456}}},
                instructions,
                openai_client,
                chat_state,
                user_memory_store=memory_store,
            )

        self.assertEqual(openai_client.voice_texts, ["Hallo Welt"])
        self.assertIn("Basisstimme.", openai_client.voice_instruction_texts[0])
        self.assertIn("Nürnberg", openai_client.voice_instruction_texts[0])

    def test_weather_context_uses_account_id_not_telegram_sender_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            memory_store = AccountStore(Path(directory) / "accounts", "Depressionsbot", StaticSecretProvider(b"w" * 32))
            account_id = memory_store.resolve_or_create_account(telegram_identity_key("", username="AdaUser"))
            user_memory = UserMemoryRecord(
                sender_id="",
                path=memory_store.account_dir(account_id) / "User_Memory_Index.json",
                prompt_text="",
                selected_ids=(),
                account_id=account_id,
            )

            with patch(
                "TeeBotus.runtime.weather_context.fetch_weather_summary",
                return_value="Berlin: 18 C, leicht bewoelkt",
            ):
                context = _prepare_weather_context(memory_store, user_memory, "Ich wohne in Berlin.")

        self.assertIn("Stadt/Wohnort: Berlin", context)

    def test_voice_model_command_persists_openai_voice_alias(self) -> None:
        api = FakeAPI()
        openai_client = FakeOpenAIClient()
        chat_state = ChatState()
        with tempfile.TemporaryDirectory() as directory:
            memory_store = AccountStore(Path(directory) / "accounts", "Depressionsbot", StaticSecretProvider(b"v" * 32))
            instructions = BotInstructions()

            handle_update(
                api,
                {"message": {"text": "/voicemodel onys", "chat": {"id": 123}, "from": {"id": 456}}},
                instructions,
                openai_client,
                chat_state,
                user_memory_store=memory_store,
            )
            handle_update(
                api,
                {"message": {"text": "/voice Hallo Welt", "chat": {"id": 123}, "from": {"id": 456}}},
                instructions,
                openai_client,
                chat_state,
                user_memory_store=memory_store,
            )

        self.assertIn("OpenAI-Stimme onyx", api.sent_messages[0][1])
        self.assertIn("https://platform.openai.com/docs/guides/text-to-speech#voice-options", api.sent_messages[0][1])
        self.assertEqual(openai_client.voice_names, ["onyx"])

    def test_voice_model_command_lists_openai_voices(self) -> None:
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as directory:
            memory_store = AccountStore(Path(directory) / "accounts", "Depressionsbot", StaticSecretProvider(b"v" * 32))
            handle_update(
                api,
                {"message": {"text": "/voicemodel", "chat": {"id": 123}, "from": {"id": 456}}},
                BotInstructions(),
                FakeOpenAIClient(),
                ChatState(),
                user_memory_store=memory_store,
            )

        self.assertIn("Aktuelle Stimme:", api.sent_messages[0][1])
        self.assertIn("onyx", api.sent_messages[0][1])
        self.assertIn("https://platform.openai.com/docs/guides/text-to-speech#voice-options", api.sent_messages[0][1])

    def test_transcribed_voice_updates_mimic_voice_profile_for_tts(self) -> None:
        api = FakeAPI()
        api.file_paths["file_1"] = "voice/file_1.oga"
        api.file_data["voice/file_1.oga"] = b"voice-audio"
        openai_client = FakeOpenAIClient()
        openai_client.transcription_text = "Aehm also ich weiss nicht, ich bin nervoes und rede sehr schnell."
        chat_state = ChatState()
        with tempfile.TemporaryDirectory() as directory:
            memory_store = AccountStore(Path(directory) / "accounts", "Depressionsbot", StaticSecretProvider(b"m" * 32))
            instructions = BotInstructions(openai_voice_instructions="Basisstimme.", user_memory_enabled=True)
            account_id = memory_store.resolve_or_create_account(telegram_identity_key(456))
            memory_store.confirm_privacy(account_id, source="telegram")

            handle_update(
                api,
                {"message": {"voice": {"file_id": "file_1", "duration": 2}, "chat": {"id": 123, "type": "private"}, "from": {"id": 456}}},
                instructions,
                openai_client,
                chat_state,
                user_memory_store=memory_store,
            )
            handle_update(
                api,
                {"message": {"text": "/mimic_voice on", "chat": {"id": 123, "type": "private"}, "from": {"id": 456}}},
                instructions,
                openai_client,
                chat_state,
                user_memory_store=memory_store,
            )
            handle_update(
                api,
                {"message": {"text": "/voice Hallo Welt", "chat": {"id": 123, "type": "private"}, "from": {"id": 456}}},
                instructions,
                openai_client,
                chat_state,
                user_memory_store=memory_store,
            )

            state = memory_store.read_agent_state(account_id)

        self.assertIn("Sprechweisen-Nachahmung", api.sent_messages[-1][1])
        self.assertIn("beobachtete Sprechweise", openai_client.voice_instruction_texts[0])
        self.assertIn("spricht sehr schnell und hastig", openai_client.voice_instruction_texts[0])
        self.assertNotIn("ich weiss nicht", json.dumps(state, ensure_ascii=False))

    def test_logs_outgoing_voice_without_content(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        openai_client = FakeOpenAIClient()

        with self.assertLogs("TeeBotus", level="INFO") as logs:
            handle_update(
                api,
                {"message": {"message_id": 56, "text": "/voice sehr privat", "chat": {"id": 123}}},
                BotInstructions(),
                openai_client,
                ChatState(),
            )

        log_text = "\n".join(logs.output)
        self.assertIn("Incoming Telegram message chat_id=123 message_id=56 type=text", log_text)
        self.assertIn("Outgoing Telegram message", log_text)
        self.assertIn("chat_id=123 message_id=101 type=voice bytes=11", log_text)
        self.assertNotIn("sehr privat", log_text)

    def test_voice_command_uses_replied_message_text(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        openai_client = FakeOpenAIClient()

        handle_update(
            api,
            {"message": {"text": "/voice", "reply_to_message": {"text": "Aus Reply"}, "chat": {"id": 123}}},
            BotInstructions(),
            openai_client,
            ChatState(),
        )

        self.assertEqual(openai_client.voice_texts, ["Aus Reply"])

    def test_voice_command_uses_replied_poll_question_as_text(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        openai_client = FakeOpenAIClient()

        handle_update(
            api,
            {"message": {"text": "/voice", "reply_to_message": {"poll": {"question": "Welche Quelle?"}}, "chat": {"id": 123}}},
            BotInstructions(),
            openai_client,
            ChatState(),
        )

        self.assertEqual(openai_client.voice_texts, ["[Umfrage] Welche Quelle?"])

    def test_voice_command_requires_text(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()

        handle_update(api, {"message": {"text": "/voice", "chat": {"id": 123}}}, BotInstructions(), FakeOpenAIClient(), ChatState())

        self.assertEqual(api.sent_messages, [(123, "Nutzung: /voice Text fuer die Sprachnachricht")])

    def test_voice_command_rejects_too_long_text(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        instructions = BotInstructions(openai_voice_max_input_chars=5)

        handle_update(api, {"message": {"text": "/voice zu lang", "chat": {"id": 123}}}, instructions, FakeOpenAIClient(), ChatState())

        self.assertEqual(api.sent_messages, [(123, "Der Text ist zu lang fuer eine Sprachnachricht. Maximum: 5 Zeichen.")])

    def test_telegram_getupdates_conflict_is_detected_for_clear_runtime_logging(self) -> None:
        exc = TelegramAPIError(
            'Telegram HTTP error 409: {"ok":false,"error_code":409,'
            '"description":"Conflict: terminated by other getUpdates request; make sure that only one bot instance is running"}'
        )

        self.assertTrue(_is_telegram_getupdates_conflict(exc))
        self.assertFalse(_is_telegram_getupdates_conflict(TelegramAPIError("Telegram HTTP error 401: unauthorized")))

    def test_codex_command_resumes_latest_repo_session_for_runtime_admin(self) -> None:
        from TeeBotus.instructions import BotInstructions
        from TeeBotus.runtime.events import IncomingEvent
        from TeeBotus.runtime.status_auth import authorize_status_recipient

        api = FakeAPI()
        chat_state = ChatState(instance_name="Depressionsbot")
        with tempfile.TemporaryDirectory() as directory:
            memory_store = AccountStore(Path(directory) / "accounts", "Depressionsbot", StaticSecretProvider(b"c" * 32))
            account_id = memory_store.resolve_or_create_account(telegram_identity_key(456), display_label="Ada")
            authorize_status_recipient(
                memory_store,
                account_id,
                IncomingEvent(
                    event_id="telegram:1",
                    instance="Depressionsbot",
                    channel="telegram",
                    adapter_slot=1,
                    account_id=account_id,
                    identity_key=telegram_identity_key(456),
                    chat_id="123",
                    chat_type="private",
                    sender_id="456",
                    sender_name="Ada",
                    text="/codex Bitte pruefe das.",
                    message_ref="1",
                ),
            )
            repo = Path(directory) / "repo"
            repo.mkdir()
            session_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
            session_root = Path(directory) / ".codex" / "sessions"
            session_file = session_root / "2026" / "06" / "19" / f"rollout-2026-06-19T12-00-00-{session_id}.jsonl"
            session_file.parent.mkdir(parents=True, exist_ok=True)
            session_file.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-06-19T12:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": session_id, "cwd": str(repo)},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            memory_store.write_codex_history_outbox(
                INSTANCE_STATE_ACCOUNT_ID,
                [
                    {
                        "id": "hist-1",
                        "created_at": "2026-06-19T12:00:00+00:00",
                        "updated_at": "2026-06-19T12:00:00+00:00",
                        "project": {"repo_name": "repo", "repo_root": str(repo), "remote_url": ""},
                        "codex": {"session_id": session_id},
                        "summary": {"title": "Letzte Nachricht", "markdown": "# Test"},
                    }
                ],
            )
            instructions = BotInstructions(codex_timeout_seconds=30)

            def run(command, cwd, **kwargs):
                self.assertEqual(command, ["codex", "exec", "resume", session_id, "-"])
                self.assertEqual(cwd, str(repo))
                self.assertEqual(kwargs["input"], "Bitte pruefe das.")
                self.assertTrue(kwargs["text"])
                self.assertTrue(kwargs["capture_output"])
                self.assertEqual(kwargs["timeout"], 30)
                self.assertFalse(kwargs["check"])
                self.assertEqual(kwargs["env"]["CODEX_HOME"], str(Path(directory) / ".codex"))
                return subprocess.CompletedProcess(command, 0, "Codex erledigt.\n", "")

            with patch("TeeBotus.runtime.codex_command.shutil.which", return_value="/usr/bin/codex"):
                with patch("TeeBotus.runtime.codex_command.default_codex_session_roots", return_value=(session_root,)):
                    with patch("TeeBotus.runtime.codex_command.subprocess.run", side_effect=run):
                        handle_update(
                            api,
                            {"message": {"text": "/codex Bitte pruefe das.", "chat": {"id": 123}, "from": {"id": 456}}},
                            instructions,
                            None,
                            chat_state,
                            user_memory_store=memory_store,
                        )

        self.assertEqual(api.chat_actions, [(123, "typing")])
        self.assertEqual(api.sent_messages, [(123, f"Codex -> repo\nSession: {session_id}\n\nCodex erledigt.")])

    def test_bare_codex_command_uses_status_executor_for_runtime_admin(self) -> None:
        from TeeBotus.adapters.telegram_runtime import _handle_codex_command
        from TeeBotus.runtime.codex_command import CodexCommandResult
        from TeeBotus.runtime.events import IncomingEvent
        from TeeBotus.runtime.status_auth import authorize_status_recipient

        api = FakeAPI()
        with tempfile.TemporaryDirectory() as directory:
            store = AccountStore(Path(directory) / "accounts", "Depressionsbot", StaticSecretProvider(b"c" * 32))
            account_id = store.resolve_or_create_account(telegram_identity_key(456), display_label="Ada")
            authorize_status_recipient(
                store,
                account_id,
                IncomingEvent(
                    event_id="telegram:bare-codex",
                    instance="Depressionsbot",
                    channel="telegram",
                    adapter_slot=1,
                    account_id=account_id,
                    identity_key=telegram_identity_key(456),
                    chat_id="123",
                    chat_type="private",
                    sender_id="456",
                    sender_name="Ada",
                    text="/codex",
                    message_ref="bare-codex",
                ),
            )
            with patch(
                "TeeBotus.adapters.telegram_runtime.execute_codex_admin_command",
                return_value=CodexCommandResult("ok", text="Codex-Schalter"),
            ) as execute:
                handled = _handle_codex_command(
                    api,
                    ChatState(),
                    123,
                    {"from": {"id": 456}},
                    BotInstructions(),
                    "/codex",
                    False,
                    BotIdentity(first_name="Mondbot"),
                    user_memory_store=store,
                    instance_name="Depressionsbot",
                )

        self.assertTrue(handled)
        execute.assert_called_once()
        self.assertEqual(api.sent_messages, [(123, "Codex-Schalter")])

    def test_codex_command_rejects_non_admin_account(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState(instance_name="Depressionsbot")
        instructions = BotInstructions()

        with tempfile.TemporaryDirectory() as directory:
            memory_store = AccountStore(Path(directory) / "accounts", "Depressionsbot", StaticSecretProvider(b"c" * 32))
            memory_store.resolve_or_create_account(telegram_identity_key(456), display_label="Ada")

            with patch("TeeBotus.runtime.codex_command.subprocess.run") as run:
                handle_update(
                    api,
                    {"message": {"text": "/codex Bitte pruefe das.", "chat": {"id": 123}, "from": {"id": 456}}},
                    instructions,
                    None,
                    chat_state,
                    user_memory_store=memory_store,
                )

        run.assert_not_called()
        self.assertEqual(api.sent_messages, [(123, instructions.codex_unauthorized)])

    def test_codex_command_ignores_legacy_sender_id_whitelist_without_runtime_admin(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState(instance_name="Depressionsbot")
        instructions = BotInstructions(codex_allowed_account_ids=("456",))

        with tempfile.TemporaryDirectory() as directory:
            memory_store = AccountStore(Path(directory) / "accounts", "Depressionsbot", StaticSecretProvider(b"c" * 32))
            memory_store.resolve_or_create_account(telegram_identity_key(456), display_label="Ada")

            with patch("TeeBotus.runtime.codex_command.subprocess.run") as run:
                handle_update(
                    api,
                    {"message": {"text": "/codex Bitte pruefe das.", "chat": {"id": 123}, "from": {"id": 456}}},
                    instructions,
                    None,
                    chat_state,
                    user_memory_store=memory_store,
                )

        run.assert_not_called()
        self.assertEqual(api.sent_messages, [(123, instructions.codex_unauthorized)])

    def test_depression_alert_notifies_teladi_for_suicide_risk(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState(instance_name="Depressionsbot")

        handle_update(
            api,
            {"message": {"text": "Ich will mich umbringen.", "chat": {"id": 123}, "from": {"id": 456, "first_name": "Ada"}}},
            BotInstructions(),
            None,
            chat_state,
        )

        alerts = [text for chat_id, text in api.sent_messages if chat_id == TELADI_EMERGENCY_CHAT_ID]
        self.assertEqual(len(alerts), 1)
        self.assertIn("Depressionsbot Krisenalarm", alerts[0])
        self.assertIn("Grund: Suizid", alerts[0])
        self.assertIn("Quelle: incoming", alerts[0])
        self.assertIn("sender_id: 456", alerts[0])

    def test_depression_alert_deduplicates_messages_not_users(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState(instance_name="Depressionsbot")
        for message_id in (1, 2):
            handle_update(
                api,
                {
                    "message": {
                        "message_id": message_id,
                        "text": "Ich will mich umbringen.",
                        "chat": {"id": 123},
                        "from": {"id": 456, "first_name": "Ada"},
                    }
                },
                BotInstructions(),
                None,
                chat_state,
            )

        alerts = [text for chat_id, text in api.sent_messages if chat_id == TELADI_EMERGENCY_CHAT_ID]
        self.assertEqual(len(alerts), 2)

    def test_depression_alert_retries_after_failed_dispatch(self) -> None:
        from TeeBotus.adapters.telegram_runtime import _maybe_send_depression_alert
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState(instance_name="Depressionsbot")
        message = {
            "message_id": 77,
            "text": "Ich will mich umbringen.",
            "chat": {"id": 123},
            "from": {"id": 456, "first_name": "Ada"},
        }

        with patch(
            "TeeBotus.adapters.telegram_runtime._send_untracked_message",
            side_effect=[TelegramAPIError("temporary failure"), None],
        ) as send:
            _maybe_send_depression_alert(api, chat_state, 123, message, BotInstructions(), message["text"], "Depressionsbot", "incoming")
            _maybe_send_depression_alert(api, chat_state, 123, message, BotInstructions(), message["text"], "Depressionsbot", "incoming")

        self.assertEqual(send.call_count, 2)

    def test_depression_alert_notifies_teladi_for_stress_level_ten(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState(instance_name="Depressionsbot")

        handle_update(
            api,
            {"message": {"text": "Stressstufe 10.", "chat": {"id": 123}, "from": {"id": 456, "first_name": "Ada"}}},
            BotInstructions(),
            None,
            chat_state,
        )

        alerts = [text for chat_id, text in api.sent_messages if chat_id == TELADI_EMERGENCY_CHAT_ID]
        self.assertEqual(len(alerts), 1)
        self.assertIn("Grund: Stressstufe 10", alerts[0])
        self.assertIn("Stressstufe 10", alerts[0])

    def test_handle_update_splits_long_openai_reply(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        llm_client = LongReplyOpenAIClient()
        instructions = BotInstructions(openai_enabled=True)

        handle_update(api, {"message": {"text": "lang bitte", "chat": {"id": 123}}}, instructions, None, ChatState(), llm_client=llm_client)

        self.assertGreater(len(api.sent_messages), 1)
        self.assertTrue(all(len(text) <= TELEGRAM_MESSAGE_CHUNK_SIZE for _, text in api.sent_messages))

    def test_modern_telegram_text_actions_split_before_retry_indexing(self) -> None:
        from TeeBotus.runtime.actions import MessageButton, SendText

        actions = _expand_telegram_text_actions(
            _with_telegram_reply_context(
                [
                    SendText(
                        "123",
                        "wort " * 1200,
                        buttons=(MessageButton("Weiter", "weiter"),),
                    )
                ],
                SimpleNamespace(chat_id="123", message_ref="77"),
            )
        )

        self.assertGreater(len(actions), 1)
        self.assertTrue(all(isinstance(action, SendText) for action in actions))
        self.assertTrue(all(len(action.text) <= TELEGRAM_MESSAGE_CHUNK_SIZE for action in actions))
        self.assertTrue(all(not action.buttons for action in actions[:-1]))
        self.assertEqual(actions[0].reply_to_ref, "77")
        self.assertTrue(all(not action.reply_to_ref for action in actions[1:]))
        self.assertEqual(actions[-1].buttons, (MessageButton("Weiter", "weiter"),))

    def test_every_third_short_openai_reply_without_sources_is_voice(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        openai_client = SequenceOpenAIClient(["Kurz eins.", "Kurz zwei.", "Kurz drei."])
        instructions = BotInstructions(openai_enabled=True, openai_auto_voice_every=3)

        for index in range(3):
            handle_update(
                api,
                {"message": {"text": f"frage {index}", "chat": {"id": 123}}},
                instructions,
                openai_client,
                chat_state,
                llm_client=openai_client,
            )

        self.assertEqual(api.sent_messages, [(123, "Kurz eins."), (123, "Kurz zwei.")])
        self.assertEqual(openai_client.voice_texts, ["Kurz drei."])
        self.assertEqual(api.sent_voices, [(123, b"voice-bytes", "voice.ogg", "audio/ogg")])

    def test_auto_voice_skips_replies_with_sources(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        openai_client = SequenceOpenAIClient(
            [
                "Kurz eins.",
                "Quelle: https://example.com",
                "Kurz zwei.",
                "Kurz drei.",
            ]
        )
        instructions = BotInstructions(openai_enabled=True, openai_auto_voice_every=3)

        for index in range(4):
            handle_update(
                api,
                {"message": {"text": f"frage {index}", "chat": {"id": 123}}},
                instructions,
                openai_client,
                chat_state,
                llm_client=openai_client,
            )

        self.assertEqual(
            api.sent_messages,
            [(123, "Kurz eins."), (123, "Quelle: https://example.com"), (123, "Kurz zwei.")],
        )
        self.assertEqual(openai_client.voice_texts, ["Kurz drei."])

    def test_auto_voice_skips_replies_with_50_or_more_words(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        long_reply = " ".join(["wort"] * 50)
        openai_client = SequenceOpenAIClient(["Kurz eins.", "Kurz zwei.", long_reply, "Kurz drei."])
        instructions = BotInstructions(openai_enabled=True, openai_auto_voice_every=3, openai_auto_voice_max_words=50)

        for index in range(4):
            handle_update(
                api,
                {"message": {"text": f"frage {index}", "chat": {"id": 123}}},
                instructions,
                openai_client,
                chat_state,
                llm_client=openai_client,
            )

        self.assertEqual(api.sent_voices, [(123, b"voice-bytes", "voice.ogg", "audio/ogg")])
        self.assertEqual(openai_client.voice_texts, ["Kurz drei."])

    def test_handle_update_logs_text_llm_error_without_traceback(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        llm_client = FailingOpenAIClient()
        instructions = BotInstructions(openai_enabled=True)

        with self.assertLogs("TeeBotus", level="ERROR") as logs:
            handle_update(api, {"message": {"text": "Was ist los?", "chat": {"id": 123}}}, instructions, None, ChatState(), llm_client=llm_client)

        self.assertIn("Text LLM request failed: short failure", "\n".join(logs.output))
        self.assertEqual(api.sent_messages, [(123, instructions.llm_error)])

    def test_reset_clears_text_llm_chat_state(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        chat_state.set_previous_response_id(123, "resp_old")

        handle_update(api, {"message": {"text": "/reset", "chat": {"id": 123}}}, BotInstructions(), None, chat_state)

        self.assertIsNone(chat_state.get_previous_response_id(123))
        self.assertEqual(api.sent_messages, [(123, BotInstructions().llm_reset)])

    def test_cleanup_removes_requested_number_of_recorded_messages(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        chat_state.record_received_message(123, 10)
        chat_state.record_sent_message(123, 11)
        chat_state.record_received_message(123, 12)
        chat_state.record_sent_message(123, 13)

        handle_update(api, {"message": {"text": "/cleanup 2", "message_id": 14, "chat": {"id": 123}}}, BotInstructions(), None, chat_state)

        self.assertEqual(api.deleted_messages, [(123, 14), (123, 13)])
        self.assertEqual(api.sent_messages, [(123, BotInstructions().cleanup_success.format(count=2))])
        self.assertEqual(chat_state.pop_recent_messages(123, 10), [101, 12, 11, 10])

    def test_cleanup_requires_count(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()

        handle_update(api, {"message": {"text": "/cleanup", "chat": {"id": 123}}}, BotInstructions(), None, ChatState())

        self.assertEqual(api.sent_messages, [(123, BotInstructions().cleanup_usage)])

    def test_cleanup_all_removes_all_recorded_messages(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        chat_state.record_received_message(123, 10)
        chat_state.record_sent_message(123, 11)
        chat_state.record_received_message(123, 12)
        chat_state.record_sent_message(123, 13)

        handle_update(api, {"message": {"text": "/cleanup all", "message_id": 14, "chat": {"id": 123}}}, BotInstructions(), None, chat_state)

        self.assertEqual(api.deleted_messages, [(123, 14), (123, 13), (123, 12), (123, 11), (123, 10)])
        self.assertEqual(api.sent_messages, [(123, BotInstructions().cleanup_success.format(count=5))])
        self.assertEqual(chat_state.pop_recent_messages(123, 10), [101])

    def test_modern_telegram_dispatch_preserves_action_order(self) -> None:
        from TeeBotus.adapters.telegram_runtime import _dispatch_modern_telegram_actions
        from TeeBotus.runtime.actions import DeleteTrackedMessages, SendText
        from TeeBotus.runtime.events import IncomingEvent

        api = FakeAPI()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret_provider = StaticSecretProvider(b"e" * 32)
            account_store = AccountStore(root / "accounts", "Demo", secret_provider)
            tracker = MessageTracker(root / "Sent_Message_Refs.json")
            event = IncomingEvent(
                event_id="telegram:1",
                instance="Demo",
                channel="telegram",
                adapter_slot=1,
                account_id="account-1",
                identity_key="telegram:user:456",
                chat_id="123",
                chat_type="private",
                sender_id="456",
                text="/cleanup 1",
                message_ref="1",
            )

            _dispatch_modern_telegram_actions(
                api,
                tracker,
                event,
                [SendText("123", "before"), DeleteTrackedMessages("123", 1), SendText("123", "after")],
                account_store=account_store,
                instance_name="Demo",
            )

        self.assertEqual(api.sent_messages, [("123", "before"), ("123", "after")])
        self.assertEqual(api.deleted_messages, [(123, 101)])

    def test_modern_telegram_cleanup_logs_and_restores_failed_deletes(self) -> None:
        from TeeBotus.adapters.telegram_runtime import _delete_tracked_telegram_messages
        from TeeBotus.runtime.actions import DeleteTrackedMessages
        from TeeBotus.runtime.events import IncomingEvent
        from TeeBotus.runtime.message_tracking import SentMessageRef

        class FailingDeleteAPI(FakeAPI):
            def delete_message(self, chat_id: int, message_id: int) -> None:
                super().delete_message(chat_id, message_id)
                raise TelegramAPIError("delete refused")

        api = FailingDeleteAPI()
        with tempfile.TemporaryDirectory() as directory:
            tracker = MessageTracker(Path(directory) / "Sent_Message_Refs.json")
            ref = SentMessageRef(
                channel="telegram",
                instance_name="Demo",
                account_id="account-1",
                chat_id="123",
                message_ref="99",
                ref_kind="telegram_message_id",
            )
            tracker.record(ref)
            event = IncomingEvent(
                event_id="telegram:1",
                instance="Demo",
                channel="telegram",
                adapter_slot=1,
                account_id="account-1",
                identity_key="telegram:user:456",
                chat_id="123",
                chat_type="private",
                sender_id="456",
                text="/cleanup 1",
                message_ref="1",
            )

            with self.assertLogs("TeeBotus", level="ERROR") as logs:
                _delete_tracked_telegram_messages(api, tracker, event, [DeleteTrackedMessages("123", 1)])

            self.assertEqual(api.deleted_messages, [(123, 99)])
            self.assertEqual(tracker.list_for_chat("123", instance_name="Demo", channel="telegram"), [ref])
            self.assertIn("Telegram cleanup failed", "\n".join(logs.output))

    def test_modern_telegram_cleanup_logs_tracking_pop_errors(self) -> None:
        from TeeBotus.adapters.telegram_runtime import _delete_tracked_telegram_messages
        from TeeBotus.runtime.actions import DeleteTrackedMessages
        from TeeBotus.runtime.events import IncomingEvent

        api = FakeAPI()
        tracker = MessageTracker()
        tracker.pop_for_cleanup = lambda **_kwargs: (_ for _ in ()).throw(OSError("tracker refused"))  # type: ignore[method-assign]
        event = IncomingEvent(
            event_id="telegram:1",
            instance="Demo",
            channel="telegram",
            adapter_slot=1,
            account_id="account-1",
            identity_key="telegram:user:456",
            chat_id="123",
            chat_type="private",
            sender_id="456",
            text="/cleanup 1",
            message_ref="1",
        )

        with self.assertLogs("TeeBotus", level="ERROR") as logs:
            _delete_tracked_telegram_messages(api, tracker, event, [DeleteTrackedMessages("123", 1)])

        self.assertEqual(api.deleted_messages, [])
        self.assertIn("Telegram cleanup could not load tracked messages", "\n".join(logs.output))

    def test_modern_telegram_linked_identity_logs_send_failures(self) -> None:
        from TeeBotus.adapters.telegram_runtime import _notify_telegram_linked_identities
        from TeeBotus.runtime.actions import NotifyLinkedIdentity

        class FailingSendAPI(FakeAPI):
            def send_message(self, chat_id: int, text: str) -> int:
                raise TelegramAPIError("send refused")

        api = FailingSendAPI()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            account_store = AccountStore(root / "accounts", "Demo", StaticSecretProvider(b"e" * 32))
            tracker = MessageTracker(root / "Sent_Message_Refs.json")
            old_identity = telegram_identity_key("999")
            account_store.resolve_or_create_account(old_identity)
            account_store.update_identity_route(old_identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)
            action = NotifyLinkedIdentity(
                identity_key=old_identity,
                text="Ein neuer Kommunikationsweg wurde verbunden.",
                account_id="account-1",
                new_identity_key=telegram_identity_key("456"),
            )

            with self.assertLogs("TeeBotus", level="ERROR") as logs:
                _notify_telegram_linked_identities(api, tracker, account_store, [action], instance_name="Demo")

            self.assertIn("Telegram linked identity notification failed", "\n".join(logs.output))

    def test_call_a_teladi_prompts_and_forwards_next_message(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        instructions = BotInstructions(openai_enabled=True)

        handle_update(
            api,
            {
                "message": {
                    "text": "/Call_a_Teladi",
                    "message_id": 54,
                    "chat": {"id": 123, "type": "private"},
                    "from": {"id": 456, "first_name": "Ada", "last_name": "Lovelace", "username": "ada_l"},
                }
            },
            instructions,
            FakeOpenAIClient(),
            chat_state,
        )

        self.assertEqual(api.sent_messages, [(123, instructions.teladi_call_prompt)])

        handle_update(
            api,
            {
                "message": {
                    "text": "  Bitte sofort melden.\nKeine Kuerzung.  ",
                    "message_id": 55,
                    "chat": {"id": 123, "type": "private"},
                    "from": {"id": 456, "first_name": "Ada", "last_name": "Lovelace", "username": "ada_l"},
                }
            },
            instructions,
            FakeOpenAIClient(),
            chat_state,
        )

        self.assertEqual(api.sent_messages[-1], (123, instructions.teladi_call_sent))
        user_replies = [text for chat_id, text in api.sent_messages if chat_id == 123]
        self.assertTrue(all(str(TELADI_EMERGENCY_CHAT_ID) not in text for text in user_replies))
        self.assertEqual(api.sent_messages[1][0], TELADI_EMERGENCY_CHAT_ID)
        self.assertIn("Emergency message via /Call_a_Teladi", api.sent_messages[1][1])
        self.assertIn("From: Ada Lovelace @ada_l (sender_id: 456)", api.sent_messages[1][1])
        self.assertIn("Chat: unbekannt (type: private, chat_id: 123)", api.sent_messages[1][1])
        self.assertNotIn("Bitte sofort melden", api.sent_messages[1][1])
        self.assertEqual(api.copied_messages, [(TELADI_EMERGENCY_CHAT_ID, 123, 55)])

    def test_call_a_teladi_cooldown_rejects_until_next_day(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        instructions = BotInstructions()

        with patch("TeeBotus.adapters.telegram_runtime._now_epoch", side_effect=[1000.0, 1000.0, 4600.0, 87401.0]):
            handle_update(
                api,
                {"message": {"text": "/Call_a_Teladi", "message_id": 1, "chat": {"id": 123}, "from": {"id": 456, "first_name": "Ada"}}},
                instructions,
                None,
                chat_state,
            )
            handle_update(
                api,
                {"message": {"text": "Hilfe", "message_id": 2, "chat": {"id": 123}, "from": {"id": 456, "first_name": "Ada"}}},
                instructions,
                None,
                chat_state,
            )
            handle_update(
                api,
                {"message": {"text": "/Call_a_Teladi", "message_id": 3, "chat": {"id": 123}, "from": {"id": 456, "first_name": "Ada"}}},
                instructions,
                None,
                chat_state,
            )
            handle_update(
                api,
                {"message": {"text": "/Call_a_Teladi", "message_id": 4, "chat": {"id": 123}, "from": {"id": 456, "first_name": "Ada"}}},
                instructions,
                None,
                chat_state,
            )

        target_messages = [text for chat_id, text in api.sent_messages if chat_id == TELADI_EMERGENCY_CHAT_ID]
        self.assertEqual(len(target_messages), 1)
        self.assertEqual(api.copied_messages, [(TELADI_EMERGENCY_CHAT_ID, 123, 2)])
        self.assertIn("23h", api.sent_messages[3][1])
        self.assertEqual(api.sent_messages[-1], (123, instructions.teladi_call_prompt))

    def test_call_a_teladi_cooldown_is_account_scoped_across_linked_identities(self) -> None:
        from TeeBotus.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            chat_state = ChatState()
            instructions = BotInstructions()
            memory_store = account_memory_store(directory)
            account_id = memory_store.resolve_or_create_account(telegram_identity_key(456), display_label="Ada")
            _, secret = memory_store.register_account(account_id)
            memory_store.link_identity(telegram_identity_key("", username="ada_l"), account_id, secret, display_label="Ada")

            with patch("TeeBotus.adapters.telegram_runtime._now_epoch", side_effect=[1000.0, 1000.0, 4600.0]):
                handle_update(
                    api,
                    {"message": {"text": "/Call_a_Teladi", "message_id": 1, "chat": {"id": 123}, "from": {"id": 456, "first_name": "Ada"}}},
                    instructions,
                    None,
                    chat_state,
                    memory_store,
                )
                handle_update(
                    api,
                    {"message": {"text": "Hilfe", "message_id": 2, "chat": {"id": 123}, "from": {"id": 456, "first_name": "Ada"}}},
                    instructions,
                    None,
                    chat_state,
                    memory_store,
                )
                handle_update(
                    api,
                    {"message": {"text": "/Call_a_Teladi", "message_id": 3, "chat": {"id": 123}, "from": {"username": "ada_l", "first_name": "Ada"}}},
                    instructions,
                    None,
                    chat_state,
                    memory_store,
                )

            self.assertIn(account_id, chat_state.teladi_call_used_at)
            self.assertNotIn("telegram:user:456", chat_state.teladi_call_used_at)
            target_messages = [text for chat_id, text in api.sent_messages if chat_id == TELADI_EMERGENCY_CHAT_ID]
            self.assertEqual(len(target_messages), 1)
            self.assertIn(f"Account: {account_id}", target_messages[0])
            self.assertIn("Identity: telegram:user:456", target_messages[0])
            self.assertIn("Instanz: Depressionsbot", target_messages[0])
            self.assertIn("Du kannst /Call_a_Teladi erst in", api.sent_messages[-1][1])
            self.assertEqual(api.copied_messages, [(TELADI_EMERGENCY_CHAT_ID, 123, 2)])

    def test_call_a_teladi_cooldown_persists_in_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "teladi_state.json"
            chat_state = ChatState(state_path)
            chat_state.mark_teladi_call_used("456", 1000.0)

            reloaded_state = ChatState(state_path)

            self.assertEqual(reloaded_state.teladi_call_remaining_seconds("456", 4600.0), 82800)
            reloaded_state.clear_teladi_call_used("456")
            self.assertEqual(ChatState(state_path).teladi_call_remaining_seconds("456", 4600.0), 0)

    def test_call_a_teladi_copies_non_text_next_message(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        instructions = BotInstructions()

        handle_update(api, {"message": {"text": "/Call_a_Teladi", "message_id": 10, "chat": {"id": 123}, "from": {"id": 456}}}, instructions, None, chat_state)
        handle_update(api, {"message": {"photo": [{"file_id": "p1"}], "message_id": 11, "chat": {"id": 123}, "from": {"id": 456}}}, instructions, None, chat_state)

        self.assertEqual(api.copied_messages, [(TELADI_EMERGENCY_CHAT_ID, 123, 11)])
        self.assertEqual(api.sent_messages[-1], (123, instructions.teladi_call_sent))

    def test_call_a_teladi_repeated_command_while_pending_does_not_forward_command_text(self) -> None:
        from TeeBotus.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        instructions = BotInstructions()

        handle_update(api, {"message": {"text": "/Call_a_Teladi", "chat": {"id": 123}, "from": {"id": 456}}}, instructions, None, chat_state)
        handle_update(api, {"message": {"text": "/Call_a_Teladi", "chat": {"id": 123}, "from": {"id": 456}}}, instructions, None, chat_state)

        self.assertEqual(api.sent_messages[0], (123, instructions.teladi_call_prompt))
        self.assertEqual(api.sent_messages[1][0], 123)
        self.assertIn("Du kannst /Call_a_Teladi erst in", api.sent_messages[1][1])
        self.assertNotIn(str(TELADI_EMERGENCY_CHAT_ID), api.sent_messages[1][1])
        self.assertFalse(any(chat_id == TELADI_EMERGENCY_CHAT_ID for chat_id, _ in api.sent_messages))

    def test_run_polling_logs_network_errors_without_traceback(self) -> None:
        api = FlakyPollingAPI()

        with tempfile.TemporaryDirectory() as directory:
            with patch("TeeBotus.bot.time.sleep") as sleep, self.assertLogs("TeeBotus", level="WARNING") as logs:
                run_polling(
                    api,
                    FakeInstructionStore(),
                    instance_name="TestPolling",
                    instances_dir=directory,
                    secret_provider=StaticSecretProvider(b"t" * 32),
                    youtube_job_runner=FakeJobRunner(),
                )

        sleep.assert_any_call(5)
        self.assertEqual(api.calls, 2)
        self.assertIn("Retrying in 5 seconds", "\n".join(logs.output))

    def test_run_polling_honors_telegram_retry_after(self) -> None:
        class RateLimitedPollingAPI(FakeAPI):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def get_updates(self, offset, timeout=50):
                self.calls += 1
                if self.calls == 1:
                    raise TelegramAPIError(
                        'Telegram HTTP error 429: {"error_code":429,"parameters":{"retry_after":137}}',
                        status_code=429,
                        retry_after=137,
                    )
                raise KeyboardInterrupt

        api = RateLimitedPollingAPI()
        with tempfile.TemporaryDirectory() as directory:
            with patch("TeeBotus.adapters.telegram_runtime.time.sleep") as sleep:
                run_polling(
                    api,
                    FakeInstructionStore(),
                    instance_name="TestPolling",
                    instances_dir=directory,
                    secret_provider=StaticSecretProvider(b"t" * 32),
                    youtube_job_runner=FakeJobRunner(),
                )

        sleep.assert_called_once_with(137)

    def test_run_polling_passes_modern_runtime_context_to_handle_update(self) -> None:
        api = OneUpdatePollingAPI()
        seen_contexts = []
        factory_calls = []

        def capture_handle_update(*args, **kwargs):
            seen_contexts.append(kwargs.get("runtime_context"))

        def fake_build_runtime_text_llm_client(**kwargs):
            factory_calls.append(kwargs)
            return "profile-client"

        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {
                    "TELEGRAM_BOT_INSTANCES_DIR": str(Path(directory) / "instances"),
                    "TEEBOTUS_LLM_PROFILE_DEMO": "local_ollama",
                },
                clear=False,
            ):
                with (
                    patch("TeeBotus.adapters.telegram_runtime.handle_update", side_effect=capture_handle_update),
                    patch("TeeBotus.runtime.telegram_runner.build_runtime_text_llm_client", side_effect=fake_build_runtime_text_llm_client),
                ):
                    run_polling(
                        api,
                        FakeInstructionStore(),
                        instance_name="Demo",
                        youtube_job_runner=FakeJobRunner(),
                        bot_identity=BotIdentity(first_name="Mondbot", username="MondBot"),
                    )

        self.assertEqual(len(seen_contexts), 1)
        self.assertIsNotNone(seen_contexts[0])
        self.assertEqual(seen_contexts[0].instance_name, "Demo")
        self.assertEqual(factory_calls[0]["profile"], "local_ollama")
        self.assertEqual(seen_contexts[0].engine.llm_client, "profile-client")

    def test_run_polling_retries_failed_update_without_advancing_offset(self) -> None:
        class RetryPollingAPI(FakeAPI):
            def __init__(self) -> None:
                super().__init__()
                self.offsets: list[int | None] = []
                self.calls = 0

            def get_updates(self, offset, timeout=50):
                self.offsets.append(offset)
                self.calls += 1
                if self.calls <= 2:
                    return [{"update_id": 7, "message": {"text": "/ping", "chat": {"id": 123}}}]
                raise KeyboardInterrupt

        api = RetryPollingAPI()
        runtime_context = SimpleNamespace(account_store=object(), bot_identity=BotIdentity())

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.dict("os.environ", {"TELEGRAM_BOT_INSTANCES_DIR": directory}, clear=False),
                patch(
                    "TeeBotus.adapters.telegram_runtime.handle_update",
                    side_effect=[RuntimeError("transient processing failure"), None],
                ) as handle,
                patch("TeeBotus.adapters.telegram_runtime.time.sleep"),
            ):
                run_polling(
                    api,
                    runtime_context=runtime_context,
                    chat_state=ChatState(),
                    youtube_job_runner=FakeJobRunner(),
                )

        self.assertEqual(handle.call_count, 2)
        self.assertEqual(api.offsets, [None, None, 8])

    def test_run_polling_keeps_completed_dispatch_journal_until_offset_is_persisted(self) -> None:
        from TeeBotus.runtime.actions import SendText
        from TeeBotus.runtime.engine import EngineResult

        class InstructionBox:
            def get(self):
                return BotInstructions()

        class OffsetFailurePollingAPI(FakeAPI):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0
                self.offsets: list[int | None] = []

            def get_updates(self, offset, timeout=50):
                self.offsets.append(offset)
                self.calls += 1
                if self.calls <= 2:
                    return [
                        {
                            "update_id": 7,
                            "message": {
                                "message_id": 11,
                                "text": "/ping",
                                "chat": {"id": 123, "type": "private"},
                                "from": {"id": 456},
                            },
                        }
                    ]
                raise KeyboardInterrupt

        api = OffsetFailurePollingAPI()
        process_calls = 0
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret_provider = StaticSecretProvider(b"e" * 32)
            context = build_telegram_runtime_context(
                api=api,
                instance_name="Demo",
                adapter_slot=1,
                instruction_store=InstructionBox(),
                account_store=AccountStore(root / "accounts", "Demo", secret_provider),
                state_store=RuntimeStateStore(root / "data", instance_name="Demo", secret_provider=secret_provider),
                message_tracker=MessageTracker(root / "runtime" / "Sent_Message_Refs.json"),
                openai_client=None,
                working_memory_store=None,
                bibliothekar_store=None,
                youtube_job_runner=None,
                bot_identity=BotIdentity(first_name="Mondbot", username="MondBot"),
            )

            def process_result(event):
                nonlocal process_calls
                process_calls += 1
                return EngineResult(event.account_id, [SendText(event.chat_id, "once")], handled=True)

            context.engine.process_result = process_result  # type: ignore[method-assign]
            with (
                patch("TeeBotus.adapters.telegram_runtime._write_telegram_update_offset", side_effect=[False, True]) as write_offset,
                patch("TeeBotus.adapters.telegram_runtime.time.sleep"),
            ):
                run_polling(
                    api,
                    instruction_store=InstructionBox(),
                    instance_name="Demo",
                    instances_dir=root / "instances",
                    runtime_context=context,
                    chat_state=ChatState(),
                    bot_identity=context.bot_identity,
                    youtube_job_runner=FakeJobRunner(),
                )

            self.assertIsNone(context.dispatch_journal.load("Demo:1:update:7"))

        self.assertEqual(api.sent_messages, [("123", "once")])
        self.assertEqual(process_calls, 1)
        self.assertEqual(api.offsets, [None, None, 8])
        self.assertEqual(write_offset.call_count, 2)

    def test_run_polling_retries_acknowledged_journal_cleanup_without_reprocessing_update(self) -> None:
        class JournalCleanupFailurePollingAPI(FakeAPI):
            def __init__(self) -> None:
                super().__init__()
                self.offsets: list[int | None] = []
                self.calls = 0

            def get_updates(self, offset, timeout=50):
                self.offsets.append(offset)
                self.calls += 1
                if self.calls == 1:
                    return [
                        {
                            "update_id": 7,
                            "message": {
                                "message_id": 11,
                                "text": "/ping",
                                "chat": {"id": 123, "type": "private"},
                                "from": {"id": 456},
                            },
                        }
                    ]
                raise KeyboardInterrupt

        api = JournalCleanupFailurePollingAPI()
        runtime_context = SimpleNamespace(
            account_store=object(),
            bot_identity=BotIdentity(),
            instance_name="Demo",
            adapter_slot=1,
            dispatch_journal=SimpleNamespace(
                complete=Mock(side_effect=[RuntimeError("journal unavailable"), None])
            ),
        )

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.dict("os.environ", {"TELEGRAM_BOT_INSTANCES_DIR": directory}, clear=False),
                patch("TeeBotus.adapters.telegram_runtime.handle_update") as handle,
                patch("TeeBotus.adapters.telegram_runtime.time.sleep"),
            ):
                run_polling(
                    api,
                    runtime_context=runtime_context,
                    chat_state=ChatState(),
                    youtube_job_runner=FakeJobRunner(),
                )

        self.assertEqual(handle.call_count, 1)
        self.assertEqual(api.offsets, [None, 8])
        self.assertEqual(runtime_context.dispatch_journal.complete.call_count, 2)

    def test_run_polling_all_cleans_up_when_bridge_setup_fails(self) -> None:
        from TeeBotus.adapters.telegram_runtime import run_polling_all

        class JobRunner:
            def __init__(self) -> None:
                self.shutdown_calls: list[bool] = []

            def shutdown(self, *, wait: bool = False) -> None:
                self.shutdown_calls.append(wait)

        job_runner = JobRunner()
        config = InstanceRunConfig(
            instance_name="Demo",
            instruction_path="/tmp/Bot_Verhalten.md",
            token_configs=(BotTokenConfig(label="1", token="telegram-token", openai_api_key=""),),
        )

        with (
            patch("TeeBotus.adapters.telegram_runtime.YouTubeTranscriptionJobRunner", return_value=job_runner),
            patch("TeeBotus.adapters.telegram_runtime._notify_recent_users_for_current_version"),
            patch(
                "TeeBotus.runtime.telegram_runner.build_telegram_runtime_bridge",
                side_effect=RuntimeError("bridge setup failed"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "bridge setup failed"):
                run_polling_all([config])

        self.assertEqual(job_runner.shutdown_calls, [False])

    def test_telegram_api_edit_message_text_uses_edit_endpoint(self) -> None:
        api = TelegramAPI("telegram-token")
        with patch.object(
            api,
            "request",
            return_value={"ok": True, "result": {"message_id": 99}},
        ) as request:
            self.assertEqual(
                api.edit_message_text(
                    123,
                    "88",
                    "plain",
                    text_mode="html",
                    formatted_text="<b>formatted</b>",
                ),
                99,
            )

        request.assert_called_once_with(
            "editMessageText",
            {"chat_id": 123, "message_id": "88", "text": "<b>formatted</b>", "parse_mode": "HTML"},
        )

    def test_run_polling_uses_explicit_instances_dir_for_update_offset(self) -> None:
        api = OneUpdatePollingAPI()
        runtime_context = SimpleNamespace(account_store=object(), bot_identity=BotIdentity())

        with tempfile.TemporaryDirectory() as directory:
            explicit_dir = Path(directory) / "configured-instances"
            fallback_dir = Path(directory) / "env-instances"
            with (
                patch.dict("os.environ", {"TELEGRAM_BOT_INSTANCES_DIR": str(fallback_dir)}, clear=False),
                patch("TeeBotus.adapters.telegram_runtime.handle_update"),
            ):
                run_polling(
                    api,
                    runtime_context=runtime_context,
                    chat_state=ChatState(),
                    youtube_job_runner=FakeJobRunner(),
                    instance_name="Demo",
                    instances_dir=explicit_dir,
                )

            expected = explicit_dir / "Demo" / "data" / "Telegram_GetUpdates_Offset_1.json"
            self.assertTrue(expected.exists())
            self.assertFalse((fallback_dir / "Demo" / "data" / expected.name).exists())

    def test_telegram_update_offset_write_is_atomic_and_cleans_temp_file(self) -> None:
        from TeeBotus.adapters.telegram_runtime import _read_telegram_update_offset, _write_telegram_update_offset

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Telegram_GetUpdates_Offset_1.json"
            _write_telegram_update_offset(path, 42)

            self.assertEqual(_read_telegram_update_offset(path), 42)
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_local_json_state_write_is_atomic_and_cleans_temp_file(self) -> None:
        from TeeBotus.adapters.telegram_runtime import _write_json_file

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            _write_json_file(path, {"status": "ok"})

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"status": "ok"})
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_main_impl_loads_runtime_environment_before_configuring_logging(self) -> None:
        from TeeBotus import bot as bot_module

        recorded = {}

        def fake_load_runtime_environment() -> None:
            os.environ["TEEBOTUS_LOG_LEVEL"] = "debug_all"

        def fake_configure_runtime_logging(*, level, tee_stdio) -> None:
            recorded["level"] = level
            recorded["tee_stdio"] = tee_stdio

        with (
            patch.dict(os.environ, {}, clear=False),
            patch("TeeBotus.bot._load_runtime_environment", side_effect=fake_load_runtime_environment),
            patch("TeeBotus.runtime.maintenance.configure_runtime_logging", side_effect=fake_configure_runtime_logging),
            patch("TeeBotus.bot._runtime_config_from_main_args", side_effect=RuntimeError("stop")),
        ):
            with self.assertRaisesRegex(RuntimeError, "stop"):
                bot_module._main_impl([])

        self.assertEqual(recorded["level"], "debug_all")
        self.assertTrue(recorded["tee_stdio"])

    def test_split_telegram_message_prefers_paragraph_boundaries(self) -> None:
        text = ("a" * 20) + "\n\n" + ("b" * 20) + "\n\n" + ("c" * 20)

        chunks = split_telegram_message(text, chunk_size=45)

        self.assertEqual(chunks, [("a" * 20) + "\n\n" + ("b" * 20), "c" * 20])

    def test_split_telegram_message_splits_long_words(self) -> None:
        chunks = split_telegram_message("x" * 25, chunk_size=10)

        self.assertEqual(chunks, ["x" * 10, "x" * 10, "x" * 5])

    def test_source_detection(self) -> None:
        self.assertTrue(contains_sources("Quelle: https://example.com"))
        self.assertTrue(contains_sources("Siehe [Beleg](https://example.com)."))
        self.assertFalse(contains_sources("Nur eine kurze Antwort ohne Link."))

    def test_count_words_uses_whitespace_tokens(self) -> None:
        self.assertEqual(count_words("Eins zwei, drei."), 3)

    def test_downloaded_file_name_maps_telegram_oga_to_openai_ogg(self) -> None:
        self.assertEqual(_downloaded_file_name("voice/file_1.oga"), "file_1.ogg")
        self.assertEqual(_downloaded_file_name("voice/file_1.ogg"), "file_1.ogg")
        self.assertEqual(_downloaded_file_name(""), "voice.ogg")

    def test_encode_multipart_form_data_includes_fields_and_file(self) -> None:
        body, content_type = _encode_multipart_form_data(
            {"chat_id": 123},
            [("voice", "voice.ogg", "audio/ogg", b"abc")],
        )

        self.assertIn("multipart/form-data; boundary=", content_type)
        self.assertIn(b'name="chat_id"', body)
        self.assertIn(b"123", body)
        self.assertIn(b'name="voice"; filename="voice.ogg"', body)
        self.assertIn(b"Content-Type: audio/ogg", body)
        self.assertIn(b"abc", body)


if __name__ == "__main__":
    unittest.main()
