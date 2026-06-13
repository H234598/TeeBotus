import base64
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from telegram_bot.bot import (
    BotIdentity,
    BotTokenConfig,
    ChatState,
    InstanceRunConfig,
    TELADI_EMERGENCY_CHAT_ID,
    TELEGRAM_MESSAGE_CHUNK_SIZE,
    TelegramAPI,
    TelegramNetworkError,
    UserMemoryStore,
    WorkingMemoryStore,
    _build_openai_user_input,
    _bot_token_config_error,
    _discover_instance_names,
    _duplicate_telegram_token_error,
    _downloaded_file_name,
    _encode_multipart_form_data,
    _instance_env_key,
    _lowest_priority_command,
    _resolve_bot_token_configs,
    _resolve_instruction_path,
    _resolve_openai_api_key,
    _resolve_openai_api_keys,
    _resolve_telegram_token,
    _resolve_telegram_tokens,
    _srt_to_plain_text,
    _run_youtube_local_transcription_job,
    _transcribe_voice_audio,
    contains_sources,
    count_words,
    handle_update,
    run_polling,
    split_telegram_message,
    transcribe_youtube_video,
)
from telegram_bot.openai_client import OpenAIAPIError, OpenAIResponse, OpenAIVoice


class FakeAPI:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[int, str]] = []
        self.chat_actions: list[tuple[int, str]] = []
        self.deleted_messages: list[tuple[int, int]] = []
        self.copied_messages: list[tuple[int, int, int]] = []
        self.sent_voices: list[tuple[int, bytes, str, str]] = []
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
        return OpenAIVoice(audio=b"voice-bytes", filename="voice.ogg", content_type="audio/ogg")

    def transcribe_audio(self, audio, filename, instructions, model=None):
        self.transcribed_audios.append((audio, filename))
        self.transcription_models.append(model)
        if self.transcription_texts:
            return self.transcription_texts.pop(0)
        return self.transcription_text


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
        from telegram_bot.instructions import BotInstructions

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


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class BotTests(unittest.TestCase):
    AVATAR_PNG = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR4nGP8z8BQDwAFgwJ/lwQ+0gAAAABJRU5ErkJggg=="
    )

    def test_default_instruction_path_uses_bote_der_wahrheit_instance(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(_resolve_instruction_path(), "instances/Bote_der_Wahrheit/Bot_Verhalten.md")

    def test_telegram_request_timeout_is_network_error(self) -> None:
        api = TelegramAPI("123:test-token")

        with patch("telegram_bot.bot.urllib.request.urlopen", side_effect=TimeoutError("read timed out")):
            with self.assertRaises(TelegramNetworkError):
                api.request("getUpdates", {})

    def test_telegram_multipart_timeout_is_network_error(self) -> None:
        api = TelegramAPI("123:test-token")

        with patch("telegram_bot.bot.urllib.request.urlopen", side_effect=TimeoutError("read timed out")):
            with self.assertRaises(TelegramNetworkError):
                api.request_multipart("sendVoice", {"chat_id": 123}, [("voice", "voice.ogg", "audio/ogg", b"data")])

    def test_telegram_file_download_timeout_is_network_error(self) -> None:
        api = TelegramAPI("123:test-token")

        with patch("telegram_bot.bot.urllib.request.urlopen", side_effect=TimeoutError("read timed out")):
            with self.assertRaises(TelegramNetworkError):
                api.download_file("voice/file.oga")

    def test_srt_to_plain_text_removes_indices_timestamps_and_tags(self) -> None:
        srt = "1\n00:00:00,000 --> 00:00:01,000\n<i>Hello</i>\n\n2\n00:00:01,000 --> 00:00:02,000\nWorld\n"

        self.assertEqual(_srt_to_plain_text(srt), "Hello\nWorld")

    def test_youtube_transcript_uses_subtitles_before_whisper(self) -> None:
        calls: list[list[str]] = []

        def run(command, cwd, **kwargs):
            calls.append(command)
            Path(cwd, "video.en.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nSubtitle text.\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch("telegram_bot.bot.shutil.which", return_value="/usr/bin/tool"):
            with patch("telegram_bot.bot.subprocess.run", side_effect=run):
                transcript, source = transcribe_youtube_video("https://www.youtube.com/watch?v=abc123")

        self.assertEqual(transcript, "Subtitle text.")
        self.assertEqual(source, "YouTube-Untertitel")
        self.assertEqual(len(calls), 1)
        self.assertIn("--write-auto-subs", calls[0])

    def test_youtube_transcript_uses_faster_whisper_when_no_subtitles_exist(self) -> None:
        calls: list[list[str]] = []

        def run(command, cwd, **kwargs):
            calls.append(command)
            if command[:2] == ["yt-dlp", "-x"]:
                Path(cwd, "youtube-audio.mp3").write_bytes(b"mp3")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch("telegram_bot.bot.shutil.which", return_value="/usr/bin/tool"):
            with patch("telegram_bot.bot._has_python_module", return_value=True):
                with patch("telegram_bot.bot.subprocess.run", side_effect=run):
                    with patch(
                        "telegram_bot.bot._run_local_command_streaming",
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

    def test_youtube_transcript_command_runs_with_lowest_priority_wrappers(self) -> None:
        with patch("telegram_bot.bot.shutil.which", side_effect=lambda name: f"/usr/bin/{name}" if name in {"nice", "ionice"} else None):
            command = _lowest_priority_command(["python3", "-c", "print('x')"])

        self.assertEqual(command[:6], ["nice", "-n", "19", "ionice", "-c", "3"])
        self.assertEqual(command[6:], ["python3", "-c", "print('x')"])

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

    def test_user_memory_file_is_sender_id_and_follows_openai_across_chats(self) -> None:
        from telegram_bot.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            openai_client = FakeOpenAIClient()
            instructions = BotInstructions(
                openai_enabled=True,
                user_memory_enabled=True,
                user_memory_dir=str(Path(directory) / "instances" / "{instance}" / "data" / "users"),
            )
            memory_store = UserMemoryStore("Depressionsbot")

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
            )

            memory_path = Path(directory) / "instances" / "Depressionsbot" / "data" / "users" / "456" / "User_Memory_Index.json"
            self.assertTrue(memory_path.exists())
            payload = json.loads(memory_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["sender_id"], "456")
            self.assertIn("mond", payload["index"]["keywords"])
            entries = read_jsonl(Path(directory) / "instances" / "Depressionsbot" / "data" / "users" / "456" / "User_Memory_Entries.jsonl")
            self.assertIn("Mein Lieblingswort ist Mond.", entries[0]["user_text"])
            self.assertTrue((Path(directory) / "instances" / "Depressionsbot" / "data" / "users" / "456" / "User_Habbits_and_behave.md").exists())

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
            )

            self.assertIn("Persistentes Nutzergedaechtnis", openai_client.reply_inputs[-1])
            self.assertIn("selected_memory_ids", openai_client.reply_inputs[-1])
            self.assertIn("Mein Lieblingswort ist Mond.", openai_client.reply_inputs[-1])

    def test_user_memory_downloads_avatar_icon_and_sets_folder_icon(self) -> None:
        from telegram_bot.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            api.profile_photo_file_ids[456] = "avatar_file_id"
            api.file_paths["avatar_file_id"] = "photos/avatar.jpg"
            api.file_data["photos/avatar.jpg"] = self.AVATAR_PNG
            instructions = BotInstructions(
                user_memory_enabled=True,
                user_memory_dir=str(Path(directory) / "instances" / "{instance}" / "data" / "users"),
                commands={"/status": "ok"},
            )
            memory_store = UserMemoryStore("Depressionsbot")

            with patch("telegram_bot.bot.subprocess.run") as run:
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
                    BotIdentity(id=99, first_name="Mondbot", username="MondBot"),
                )

            user_dir = Path(directory) / "instances" / "Depressionsbot" / "data" / "users" / "456"
            avatar_path = user_dir / "User_Avatar.jpg"
            icon_path = user_dir / "User_Avatar.icon"
            marker_path = user_dir / ".User_Avatar_Icon_Set"
            self.assertEqual(api.profile_photo_requests, [456])
            self.assertEqual(api.file_path_requests, ["avatar_file_id"])
            self.assertEqual(api.download_requests, ["photos/avatar.jpg"])
            self.assertTrue(avatar_path.exists())
            self.assertTrue(icon_path.exists())
            self.assertTrue(marker_path.exists())
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0][0:5], ["gio", "set", "-t", "string", str(user_dir)])
            self.assertEqual(run.call_args.args[0][5], "metadata::custom-icon")
            self.assertEqual(run.call_args.args[0][6], icon_path.resolve().as_uri())

    def test_user_memory_rechecks_missing_avatar_only_once_per_day(self) -> None:
        from telegram_bot.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            instructions = BotInstructions(
                user_memory_enabled=True,
                user_memory_dir=str(Path(directory) / "instances" / "{instance}" / "data" / "users"),
                commands={"/status": "ok"},
            )
            memory_store = UserMemoryStore("Depressionsbot")
            message = {
                "message": {
                    "message_id": 1,
                    "text": "/status",
                    "chat": {"id": 123, "type": "private"},
                    "from": {"id": 456, "first_name": "Ada"},
                }
            }

            handle_update(api, message, instructions, None, ChatState(), memory_store)
            handle_update(api, message, instructions, None, ChatState(), memory_store)

            user_dir = Path(directory) / "instances" / "Depressionsbot" / "data" / "users" / "456"
            self.assertEqual(api.profile_photo_requests, [456])
            self.assertTrue((user_dir / ".User_Avatar_Checked").exists())
            self.assertFalse((user_dir / "User_Avatar.jpg").exists())
            self.assertFalse((user_dir / "User_Avatar.icon").exists())

    def test_user_memory_does_not_leak_between_sender_ids(self) -> None:
        from telegram_bot.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            openai_client = FakeOpenAIClient()
            instructions = BotInstructions(
                openai_enabled=True,
                user_memory_enabled=True,
                user_memory_dir=str(Path(directory) / "instances" / "{instance}" / "data" / "users"),
            )
            memory_store = UserMemoryStore("Depressionsbot")

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
            )

            self.assertTrue((Path(directory) / "instances" / "Depressionsbot" / "data" / "users" / "456" / "User_Memory_Index.json").exists())
            self.assertTrue((Path(directory) / "instances" / "Depressionsbot" / "data" / "users" / "789" / "User_Memory_Index.json").exists())
            self.assertNotIn("Geheimnis fuer Ada", openai_client.reply_inputs[-1])

    def test_user_habits_file_is_included_for_same_sender_id(self) -> None:
        from telegram_bot.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            openai_client = FakeOpenAIClient()
            instructions = BotInstructions(
                openai_enabled=True,
                user_memory_enabled=True,
                user_memory_dir=str(Path(directory) / "instances" / "{instance}" / "data" / "users"),
            )
            memory_store = UserMemoryStore("Depressionsbot")

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
            )
            habits_path = Path(directory) / "instances" / "Depressionsbot" / "data" / "users" / "456" / "User_Habbits_and_behave.md"
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
            )

            self.assertIn("Interne, admingepflegte Zusatzhinweise", openai_client.reply_inputs[-1])
            self.assertIn("Nutze diese Hinweise nur als stillen Kontext", openai_client.reply_inputs[-1])
            self.assertNotIn("User_Habbits_and_behave.md", openai_client.reply_inputs[-1])
            self.assertIn("Ada mag knappe Antworten.", openai_client.reply_inputs[-1])

    def test_user_memory_reset_requires_confirmation_and_resets_only_current_sender(self) -> None:
        from telegram_bot.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            openai_client = FakeOpenAIClient()
            chat_state = ChatState()
            instructions = BotInstructions(
                openai_enabled=True,
                user_memory_enabled=True,
                user_memory_dir=str(Path(directory) / "instances" / "{instance}" / "data" / "users"),
            )
            memory_store = UserMemoryStore("Depressionsbot")

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
            )

            memory_dir = Path(directory) / "instances" / "Depressionsbot" / "data" / "users" / "456"
            entries_path = memory_dir / "User_Memory_Entries.jsonl"
            habits_path = memory_dir / "User_Habbits_and_behave.md"
            habits_path.write_text("Ada mag knappe Antworten.", encoding="utf-8")
            self.assertEqual(api.sent_messages[-1], (123, instructions.user_memory_reset_confirm))
            self.assertNotIn("User_Habbits", api.sent_messages[-1][1])
            self.assertEqual(len(read_jsonl(entries_path)), 1)
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
            )

            payload = json.loads((memory_dir / "User_Memory_Index.json").read_text(encoding="utf-8"))
            self.assertEqual(api.sent_messages[-1], (123, instructions.user_memory_reset_success))
            self.assertNotIn("User_Habbits", api.sent_messages[-1][1])
            self.assertEqual(payload["sender_id"], "456")
            self.assertEqual(payload["profile"], {"names": [], "usernames": [], "chat_ids": [], "chat_titles": []})
            self.assertEqual(payload["index"], {"entries": {}, "keywords": {}, "recent_ids": []})
            self.assertEqual(read_jsonl(entries_path), [])
            self.assertEqual(habits_path.read_text(encoding="utf-8"), "Ada mag knappe Antworten.")
            self.assertEqual(len(openai_client.reply_inputs), 1)

    def test_user_memory_reset_can_be_cancelled(self) -> None:
        from telegram_bot.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            openai_client = FakeOpenAIClient()
            chat_state = ChatState()
            instructions = BotInstructions(
                openai_enabled=True,
                user_memory_enabled=True,
                user_memory_dir=str(Path(directory) / "instances" / "{instance}" / "data" / "users"),
            )
            memory_store = UserMemoryStore("Depressionsbot")

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

            entries_path = Path(directory) / "instances" / "Depressionsbot" / "data" / "users" / "456" / "User_Memory_Entries.jsonl"
            self.assertEqual(api.sent_messages[-1], (123, instructions.user_memory_reset_cancelled))
            self.assertEqual(len(read_jsonl(entries_path)), 1)

    def test_user_memory_reset_rejects_foreign_and_instance_memory_targets(self) -> None:
        from telegram_bot.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            openai_client = FakeOpenAIClient()
            chat_state = ChatState()
            instructions = BotInstructions(
                openai_enabled=True,
                user_memory_enabled=True,
                user_memory_dir=str(Path(directory) / "instances" / "{instance}" / "data" / "users"),
            )
            memory_store = UserMemoryStore("Depressionsbot")
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
            )

            self.assertIn("nur deine eigenen Erinnerungen", api.sent_messages[-1][1])
            self.assertIn("keine userbezogenen Daten", api.sent_messages[-1][1])
            bob_entries = read_jsonl(Path(directory) / "instances" / "Depressionsbot" / "data" / "users" / "789" / "User_Memory_Entries.jsonl")
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
            )

            self.assertIn("Instanz-/Arbeitsgedaechtnis enthaelt keine userbezogenen Daten", api.sent_messages[-1][1])
            working_entries = read_jsonl(Path(directory) / "instances" / "Depressionsbot" / "data" / "Working_Memorys.entries.jsonl")
            self.assertEqual(len(working_entries), 1)

    def test_user_memory_reset_ignores_negated_delete_requests(self) -> None:
        from telegram_bot.instructions import BotInstructions

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

    def test_working_memory_is_included_in_openai_input_without_auto_writes(self) -> None:
        from telegram_bot.instructions import BotInstructions

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

        self.assertEqual(api.sent_messages, [(123, "pong")])

    def test_logs_incoming_and_outgoing_messages_without_content(self) -> None:
        from telegram_bot.instructions import BotInstructions

        api = FakeAPI()

        with self.assertLogs("telegram_bot", level="INFO") as logs:
            handle_update(
                api,
                {"message": {"message_id": 55, "text": "streng geheim", "chat": {"id": 123}}},
                BotInstructions(),
                None,
                ChatState(),
            )

        log_text = "\n".join(logs.output)
        self.assertIn("Incoming Telegram message chat_id=123 message_id=55 type=text", log_text)
        self.assertIn("Outgoing Telegram message chat_id=123 message_id=101 type=text", log_text)
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

    def test_handle_update_uses_openai_for_unmatched_text_when_enabled(self) -> None:
        from telegram_bot.instructions import BotInstructions

        api = FakeAPI()
        openai_client = FakeOpenAIClient()
        instructions = BotInstructions(openai_enabled=True)

        handle_update(api, {"message": {"text": "Was ist los?", "chat": {"id": 123}}}, instructions, openai_client, ChatState())

        self.assertEqual(api.chat_actions, [(123, "typing")])
        self.assertEqual(api.sent_messages, [(123, "AI: Was ist los?")])

    def test_handle_update_youtube_transcript_command_sends_transcript(self) -> None:
        api = FakeAPI()

        with patch("telegram_bot.bot.transcribe_youtube_video", return_value=("Transcript text.", "YouTube-Untertitel")) as transcribe:
            handle_update(api, {"message": {"text": "/youtube_transcript https://youtu.be/abc123", "chat": {"id": 123}}}, chat_state=ChatState())

        transcribe.assert_called_once_with("https://youtu.be/abc123", local_allowed=False)
        self.assertEqual(api.chat_actions, [(123, "typing")])
        self.assertEqual(api.sent_messages, [(123, "YouTube-Transkript (YouTube-Untertitel):\n\nTranscript text.")])

    def test_handle_update_youtube_transcript_natural_request_uses_openai_pipeline(self) -> None:
        from telegram_bot.instructions import BotInstructions

        api = FakeAPI()
        openai_client = FakeOpenAIClient()
        instructions = BotInstructions(openai_enabled=True)

        with patch("telegram_bot.bot.transcribe_youtube_video", return_value=("Transcript text.", "YouTube-Untertitel")) as transcribe:
            handle_update(
                api,
                {"message": {"text": "Bitte transkribiere dieses YouTube Video https://youtu.be/abc123", "chat": {"id": 123}}},
                instructions,
                openai_client,
                ChatState(),
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
        self.assertTrue(chat_state.has_pending_youtube_transcript_link(123, "456"))

        with patch("telegram_bot.bot.transcribe_youtube_video", return_value=("Transcript text.", "YouTube-Untertitel")) as transcribe:
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
        self.assertFalse(chat_state.has_pending_youtube_transcript_link(123, "456"))
        self.assertEqual(api.sent_messages[-1], (123, "YouTube-Transkript (YouTube-Untertitel):\n\nTranscript text."))

    def test_handle_update_youtube_transcript_asks_local_options_when_no_subtitles(self) -> None:
        from telegram_bot.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()

        with patch(
            "telegram_bot.bot.transcribe_youtube_video",
            side_effect=RuntimeError("wrong error"),
        ):
            with patch(
                "telegram_bot.bot.transcribe_youtube_video",
            ) as transcribe:
                from telegram_bot.bot import YouTubeTranscriptError

                transcribe.side_effect = YouTubeTranscriptError(
                    "keine YouTube-Untertitel gefunden.",
                    needs_local_transcription=True,
                )
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

        transcribe.assert_called_once_with("https://youtu.be/abc123", local_allowed=False)
        self.assertEqual(chat_state.get_pending_youtube_local_options(123, "456"), "https://youtu.be/abc123")
        self.assertIn("Moechtest Du den Text live ausgegeben haben?", api.sent_messages[-1][1])
        self.assertIn("Moechtest Du, dass das Ganze an dein LLM gpt-test geht?", api.sent_messages[-1][1])

    def test_handle_update_youtube_local_options_live_chunks_without_llm(self) -> None:
        api = FakeAPI()
        chat_state = ChatState()
        chat_state.request_youtube_local_options(123, "456", "https://youtu.be/abc123")

        def transcribe(url, local_allowed=False, live_callback=None):
            self.assertEqual(url, "https://youtu.be/abc123")
            self.assertTrue(local_allowed)
            self.assertIsNotNone(live_callback)
            live_callback("eins zwei drei vier fuenf sechs sieben acht neun zehn elf zwoelf dreizehn vierzehn fuenfzehn sechzehn siebzehn achtzehn neunzehn zwanzig einundzwanzig zweiundzwanzig dreiundzwanzig vierundzwanzig fuenfundzwanzig sechsundzwanzig")
            live_callback("", force=True)
            return " ".join(["wort"] * 26), "lokales Whisper"

        with patch("telegram_bot.bot.transcribe_youtube_video", side_effect=transcribe):
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

        self.assertEqual(len(api.sent_messages), 3)
        self.assertEqual(len(api.sent_messages[0][1].split()), 25)
        self.assertEqual(api.sent_messages[1][1], "sechsundzwanzig")
        self.assertEqual(api.sent_messages[2], (123, "Lokale YouTube-Transkription abgeschlossen."))
        self.assertEqual(chat_state.get_pending_youtube_local_options(123, "456"), "")

    def test_handle_update_youtube_local_options_can_send_final_transcript_to_llm(self) -> None:
        from telegram_bot.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        openai_client = FakeOpenAIClient()
        chat_state.request_youtube_local_options(123, "456", "https://youtu.be/abc123")

        with patch("telegram_bot.bot.transcribe_youtube_video", return_value=("Local transcript.", "lokales Whisper")) as transcribe:
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
            )

        transcribe.assert_called_once_with("https://youtu.be/abc123", local_allowed=True, live_callback=None)
        self.assertIn("YouTube-Transkript:", openai_client.reply_inputs[-1])
        self.assertIn("Local transcript.", openai_client.reply_inputs[-1])
        self.assertEqual(api.sent_messages, [(123, "AI: live nein, llm ja\n\nYouTube-Transkript:\n- Quelle: https://youtu.be/abc123\n- Transkriptquelle: lokales Whisper\nLocal transcript.")])
        self.assertEqual(chat_state.get_pending_youtube_local_options(123, "456"), "")

    def test_handle_update_youtube_local_options_queues_child_job_when_runner_is_available(self) -> None:
        api = FakeAPI()
        chat_state = ChatState()
        runner = FakeJobRunner()
        chat_state.request_youtube_local_options(123, "456", "https://youtu.be/abc123")

        with patch("telegram_bot.bot.transcribe_youtube_video", return_value=("Local transcript.", "lokales Whisper")) as transcribe:
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
        from telegram_bot.instructions import BotInstructions

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

        with patch("telegram_bot.bot.transcribe_youtube_video", side_effect=transcribe):
            with self.assertLogs("telegram_bot", level="WARNING") as logs:
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

        with patch("telegram_bot.bot.transcribe_youtube_video", side_effect=TimeoutError("timed out")):
            handle_update(api, {"message": {"text": "/youtube_transcript https://youtu.be/abc123", "chat": {"id": 123}}}, chat_state=ChatState())

        self.assertEqual(
            api.sent_messages,
            [(123, "YouTube-Transkript fehlgeschlagen: Timeout bei der Transkription (timed out).")],
        )

    def test_group_first_contact_must_address_bot_by_telegram_name(self) -> None:
        from telegram_bot.instructions import BotInstructions

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
        )

        self.assertEqual(api.sent_messages, [(-100123, "Ich bin Bote der Wahrheit.\n\nAI: Hallo @BoteDerWahrheitBot.")])

    def test_first_contact_start_removes_configured_instance_identity(self) -> None:
        from telegram_bot.instructions import BotInstructions

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
        from telegram_bot.instructions import BotInstructions

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
        from telegram_bot.instructions import BotInstructions

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
        )

        self.assertEqual(api.sent_messages[0], (-100123, "Ich bin Depressionsbot.\n\nAI: Depressionsbot, hallo."))
        self.assertEqual(api.sent_messages[1], (-100123, "AI: Kleiner Mond, bist du da?"))

    def test_command_targeting_other_bot_is_ignored(self) -> None:
        from telegram_bot.instructions import BotInstructions

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

    def test_openai_input_includes_sender_context_for_group_messages(self) -> None:
        from telegram_bot.instructions import BotInstructions

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

    def test_handle_update_transcribes_voice_and_processes_result_with_openai(self) -> None:
        from telegram_bot.instructions import BotInstructions

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
        )

        self.assertEqual(api.file_path_requests, ["file_1"])
        self.assertEqual(api.download_requests, ["voice/file_1.oga"])
        self.assertEqual(openai_client.transcribed_audios, [(b"voice-audio", "file_1.ogg")])
        self.assertEqual(openai_client.transcription_models, ["gpt-4o-mini-transcribe"])
        self.assertIn("- sender_id: 456", openai_client.reply_inputs[0])
        self.assertIn("- sender_name: Ada", openai_client.reply_inputs[0])
        self.assertEqual(api.chat_actions, [(123, "typing"), (123, "typing")])
        self.assertEqual(api.sent_messages, [(123, "AI: Was ist los?")])

    def test_handle_update_voice_transcription_timeout_does_not_crash(self) -> None:
        from telegram_bot.instructions import BotInstructions

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
        from telegram_bot.instructions import BotInstructions

        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI()
            api.file_paths["file_1"] = "voice/file_1.oga"
            api.file_data["voice/file_1.oga"] = b"voice-audio"
            openai_client = FakeOpenAIClient()
            openai_client.transcription_text = "Mein Voice-Geheimnis ist Mondlicht."
            instructions = BotInstructions(
                openai_enabled=True,
                user_memory_enabled=True,
                user_memory_dir=str(Path(directory) / "instances" / "{instance}" / "data" / "users"),
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
                UserMemoryStore("Depressionsbot"),
            )

            memory_text = (Path(directory) / "instances" / "Depressionsbot" / "data" / "users" / "456" / "User_Memory_Index.json").read_text(encoding="utf-8")
            payload = json.loads(memory_text)
            entries = read_jsonl(Path(directory) / "instances" / "Depressionsbot" / "data" / "users" / "456" / "User_Memory_Entries.jsonl")
            self.assertIn("Mein Voice-Geheimnis ist Mondlicht.", entries[0]["user_text"])
            self.assertEqual(entries[0]["source"]["message_type"], "voice")
            self.assertIn(entries[0]["id"], payload["index"]["entries"])
            self.assertNotIn("voice-audio", memory_text)
            self.assertNotIn("voice-audio", json.dumps(entries, ensure_ascii=False))

    def test_transcribe_voice_audio_retries_fallback_after_empty_primary_transcript(self) -> None:
        from telegram_bot.instructions import BotInstructions

        openai_client = FakeOpenAIClient()
        openai_client.transcription_texts = ["", "Hallo aus Fallback"]
        instructions = BotInstructions(
            openai_transcription_model="gpt-4o-mini-transcribe",
            openai_transcription_fallback_model="whisper-1",
        )

        with self.assertLogs("telegram_bot", level="WARNING") as logs:
            text = _transcribe_voice_audio(openai_client, b"voice-audio", "file_1.ogg", instructions)

        self.assertEqual(text, "Hallo aus Fallback")
        self.assertEqual(openai_client.transcription_models, ["gpt-4o-mini-transcribe", "whisper-1"])
        self.assertIn("Retrying with fallback_model=whisper-1", "\n".join(logs.output))

    def test_transcribe_voice_audio_does_not_retry_when_fallback_is_disabled(self) -> None:
        from telegram_bot.instructions import BotInstructions

        openai_client = FakeOpenAIClient()
        openai_client.transcription_text = ""
        instructions = BotInstructions(openai_transcription_fallback_model="")

        text = _transcribe_voice_audio(openai_client, b"voice-audio", "file_1.ogg", instructions)

        self.assertEqual(text, "")
        self.assertEqual(openai_client.transcription_models, ["gpt-4o-mini-transcribe"])

    def test_handle_update_transcribed_voice_can_trigger_static_reply(self) -> None:
        from telegram_bot.instructions import BotInstructions

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

        self.assertEqual(api.sent_messages, [(123, "pong")])

    def test_handle_update_voice_requires_openai_client(self) -> None:
        from telegram_bot.instructions import BotInstructions

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
        from telegram_bot.instructions import BotInstructions

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
        from telegram_bot.instructions import BotInstructions

        api = FakeAPI()
        api.file_paths["file_1"] = "voice/file_1.oga"
        openai_client = FakeOpenAIClient()
        openai_client.transcription_text = "streng geheim"

        with self.assertLogs("telegram_bot", level="INFO") as logs:
            handle_update(
                api,
                {"message": {"message_id": 60, "voice": {"file_id": "file_1"}, "chat": {"id": 123}}},
                BotInstructions(),
                openai_client,
                ChatState(),
            )

        log_text = "\n".join(logs.output)
        self.assertIn("Incoming Telegram message chat_id=123 message_id=60 type=voice", log_text)
        self.assertIn("Outgoing Telegram message chat_id=123 message_id=101 type=text", log_text)
        self.assertNotIn("streng geheim", log_text)
        self.assertNotIn("Echo:", log_text)

    def test_voice_command_sends_generated_voice(self) -> None:
        from telegram_bot.instructions import BotInstructions

        api = FakeAPI()
        openai_client = FakeOpenAIClient()

        handle_update(api, {"message": {"text": "/voice Hallo Welt", "chat": {"id": 123}}}, BotInstructions(), openai_client, ChatState())

        self.assertEqual(openai_client.voice_texts, ["Hallo Welt"])
        self.assertEqual(api.chat_actions, [(123, "record_voice"), (123, "upload_voice")])
        self.assertEqual(api.sent_voices, [(123, b"voice-bytes", "voice.ogg", "audio/ogg")])

    def test_logs_outgoing_voice_without_content(self) -> None:
        from telegram_bot.instructions import BotInstructions

        api = FakeAPI()
        openai_client = FakeOpenAIClient()

        with self.assertLogs("telegram_bot", level="INFO") as logs:
            handle_update(
                api,
                {"message": {"message_id": 56, "text": "/voice sehr privat", "chat": {"id": 123}}},
                BotInstructions(),
                openai_client,
                ChatState(),
            )

        log_text = "\n".join(logs.output)
        self.assertIn("Incoming Telegram message chat_id=123 message_id=56 type=text", log_text)
        self.assertIn("Outgoing Telegram message chat_id=123 message_id=101 type=voice bytes=11", log_text)
        self.assertNotIn("sehr privat", log_text)

    def test_voice_command_uses_replied_message_text(self) -> None:
        from telegram_bot.instructions import BotInstructions

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

    def test_voice_command_requires_text(self) -> None:
        from telegram_bot.instructions import BotInstructions

        api = FakeAPI()

        handle_update(api, {"message": {"text": "/voice", "chat": {"id": 123}}}, BotInstructions(), FakeOpenAIClient(), ChatState())

        self.assertEqual(api.sent_messages, [(123, "Nutzung: /voice Text fuer die Sprachnachricht")])

    def test_voice_command_rejects_too_long_text(self) -> None:
        from telegram_bot.instructions import BotInstructions

        api = FakeAPI()
        instructions = BotInstructions(openai_voice_max_input_chars=5)

        handle_update(api, {"message": {"text": "/voice zu lang", "chat": {"id": 123}}}, instructions, FakeOpenAIClient(), ChatState())

        self.assertEqual(api.sent_messages, [(123, "Der Text ist zu lang fuer eine Sprachnachricht. Maximum: 5 Zeichen.")])

    def test_codex_command_runs_locally_for_allowed_sender(self) -> None:
        from telegram_bot.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState(instance_name="Depressionsbot")
        instructions = BotInstructions(codex_allowed_sender_ids=("456",), codex_timeout_seconds=30)

        def run(command, cwd, **kwargs):
            self.assertEqual(command, ["codex", "exec", "Bitte pruefe das."])
            self.assertEqual(cwd, Path("/home/teladi/TeeBotus"))
            self.assertTrue(kwargs["text"])
            self.assertTrue(kwargs["capture_output"])
            self.assertEqual(kwargs["timeout"], 30)
            self.assertFalse(kwargs["check"])
            return subprocess.CompletedProcess(command, 0, "Codex erledigt.\n", "")

        with patch("telegram_bot.bot.shutil.which", return_value="/usr/bin/codex"):
            with patch("telegram_bot.bot.subprocess.run", side_effect=run):
                handle_update(
                    api,
                    {"message": {"text": "/codex Bitte pruefe das.", "chat": {"id": 123}, "from": {"id": 456}}},
                    instructions,
                    None,
                    chat_state,
                )

        self.assertEqual(api.chat_actions, [(123, "typing")])
        self.assertEqual(api.sent_messages, [(123, "Codex erledigt.")])

    def test_codex_command_rejects_unauthorized_sender(self) -> None:
        from telegram_bot.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState(instance_name="Depressionsbot")
        instructions = BotInstructions(codex_allowed_sender_ids=("456",))

        with patch("telegram_bot.bot.subprocess.run") as run:
            handle_update(
                api,
                {"message": {"text": "/codex Bitte pruefe das.", "chat": {"id": 123}, "from": {"id": 999}}},
                instructions,
                None,
                chat_state,
            )

        run.assert_not_called()
        self.assertEqual(api.sent_messages, [(123, instructions.codex_unauthorized)])

    def test_depression_alert_notifies_teladi_for_suicide_risk(self) -> None:
        from telegram_bot.instructions import BotInstructions

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

    def test_depression_alert_notifies_teladi_for_stress_level_ten(self) -> None:
        from telegram_bot.instructions import BotInstructions

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
        from telegram_bot.instructions import BotInstructions

        api = FakeAPI()
        instructions = BotInstructions(openai_enabled=True)

        handle_update(api, {"message": {"text": "lang bitte", "chat": {"id": 123}}}, instructions, LongReplyOpenAIClient(), ChatState())

        self.assertGreater(len(api.sent_messages), 1)
        self.assertTrue(all(len(text) <= TELEGRAM_MESSAGE_CHUNK_SIZE for _, text in api.sent_messages))

    def test_every_third_short_openai_reply_without_sources_is_voice(self) -> None:
        from telegram_bot.instructions import BotInstructions

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
            )

        self.assertEqual(api.sent_messages, [(123, "Kurz eins."), (123, "Kurz zwei.")])
        self.assertEqual(openai_client.voice_texts, ["Kurz drei."])
        self.assertEqual(api.sent_voices, [(123, b"voice-bytes", "voice.ogg", "audio/ogg")])

    def test_auto_voice_skips_replies_with_sources(self) -> None:
        from telegram_bot.instructions import BotInstructions

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
            )

        self.assertEqual(
            api.sent_messages,
            [(123, "Kurz eins."), (123, "Quelle: https://example.com"), (123, "Kurz zwei.")],
        )
        self.assertEqual(openai_client.voice_texts, ["Kurz drei."])

    def test_auto_voice_skips_replies_with_50_or_more_words(self) -> None:
        from telegram_bot.instructions import BotInstructions

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
            )

        self.assertEqual(api.sent_voices, [(123, b"voice-bytes", "voice.ogg", "audio/ogg")])
        self.assertEqual(openai_client.voice_texts, ["Kurz drei."])

    def test_handle_update_logs_openai_error_without_traceback(self) -> None:
        from telegram_bot.instructions import BotInstructions

        api = FakeAPI()
        instructions = BotInstructions(openai_enabled=True)

        with self.assertLogs("telegram_bot", level="ERROR") as logs:
            handle_update(api, {"message": {"text": "Was ist los?", "chat": {"id": 123}}}, instructions, FailingOpenAIClient(), ChatState())

        self.assertIn("OpenAI request failed: short failure", "\n".join(logs.output))
        self.assertEqual(api.sent_messages, [(123, instructions.openai_error)])

    def test_reset_clears_openai_chat_state(self) -> None:
        from telegram_bot.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        chat_state.set_previous_response_id(123, "resp_old")

        handle_update(api, {"message": {"text": "/reset", "chat": {"id": 123}}}, BotInstructions(), None, chat_state)

        self.assertIsNone(chat_state.get_previous_response_id(123))
        self.assertEqual(api.sent_messages, [(123, BotInstructions().openai_reset)])

    def test_delete_last_removes_last_recorded_bot_message(self) -> None:
        from telegram_bot.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        chat_state.record_sent_message(123, 88)

        handle_update(api, {"message": {"text": "/delete_last", "chat": {"id": 123}}}, BotInstructions(), None, chat_state)

        self.assertEqual(api.deleted_messages, [(123, 88)])
        self.assertEqual(api.sent_messages, [(123, BotInstructions().delete_last_success)])

    def test_cleanup_removes_requested_number_of_recorded_messages(self) -> None:
        from telegram_bot.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        chat_state.record_received_message(123, 10)
        chat_state.record_sent_message(123, 11)
        chat_state.record_received_message(123, 12)
        chat_state.record_sent_message(123, 13)

        handle_update(api, {"message": {"text": "/cleanup 2", "message_id": 14, "chat": {"id": 123}}}, BotInstructions(), None, chat_state)

        self.assertEqual(api.deleted_messages, [(123, 13), (123, 12)])
        self.assertEqual(api.sent_messages, [(123, BotInstructions().cleanup_success.format(count=2))])
        self.assertEqual(chat_state.pop_recent_messages(123, 10), [101, 11, 10])
        self.assertNotIn((123, 14), api.deleted_messages)

    def test_cleanup_requires_count(self) -> None:
        from telegram_bot.instructions import BotInstructions

        api = FakeAPI()

        handle_update(api, {"message": {"text": "/cleanup", "chat": {"id": 123}}}, BotInstructions(), None, ChatState())

        self.assertEqual(api.sent_messages, [(123, BotInstructions().cleanup_usage)])

    def test_call_a_teladi_prompts_and_forwards_next_message(self) -> None:
        from telegram_bot.instructions import BotInstructions

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
        from telegram_bot.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        instructions = BotInstructions()

        with patch("telegram_bot.bot.time.time", side_effect=[1000.0, 1000.0, 4600.0, 87401.0]):
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
        from telegram_bot.instructions import BotInstructions

        api = FakeAPI()
        chat_state = ChatState()
        instructions = BotInstructions()

        handle_update(api, {"message": {"text": "/Call_a_Teladi", "message_id": 10, "chat": {"id": 123}, "from": {"id": 456}}}, instructions, None, chat_state)
        handle_update(api, {"message": {"photo": [{"file_id": "p1"}], "message_id": 11, "chat": {"id": 123}, "from": {"id": 456}}}, instructions, None, chat_state)

        self.assertEqual(api.copied_messages, [(TELADI_EMERGENCY_CHAT_ID, 123, 11)])
        self.assertEqual(api.sent_messages[-1], (123, instructions.teladi_call_sent))

    def test_call_a_teladi_repeated_command_while_pending_does_not_forward_command_text(self) -> None:
        from telegram_bot.instructions import BotInstructions

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

        with patch("telegram_bot.bot.time.sleep") as sleep, self.assertLogs("telegram_bot", level="WARNING") as logs:
            run_polling(api, FakeInstructionStore())

        sleep.assert_called_once_with(5)
        self.assertEqual(api.calls, 2)
        self.assertIn("Retrying in 5 seconds", "\n".join(logs.output))

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
