import unittest
from pathlib import Path

from TeeBotus.handlers import HELP_TEXT, build_reply, is_program_history_request
from TeeBotus.instructions import BotInstructions


class HandlerTests(unittest.TestCase):
    def test_start_uses_first_name_when_available(self) -> None:
        reply = build_reply({"text": "/start", "from": {"first_name": "Ada"}})

        self.assertEqual(reply, "Hallo, Ada. Ich bin bereit. Sende /help fuer die Befehle.")

    def test_help_returns_command_list(self) -> None:
        reply = build_reply({"text": "/help"})

        self.assertEqual(reply, HELP_TEXT)
        self.assertIn("/history - Release Log https://github.com/H234598/TeeBotus/releases und Commits anzeigen", reply)
        self.assertIn("/reset - setzt nur den Text-LLM-Kontext", reply)
        self.assertIn("/reset_memorys - fragt nach und loescht danach nur deine eigenen User-Memory-Eintraege", reply)
        self.assertIn("/Call_a_Teladi - Send Teladi a emergency message", reply)
        self.assertIn("/codex Prompt - fuehrt Codex CLI lokal aus", reply)
        self.assertIn("/cleanup N - loescht die letzten N seit Bot-Start gemerkten Nachrichten in diesem Chat", reply)
        self.assertIn("/cleanup all - loescht alle seit Bot-Start gemerkten Nachrichten in diesem Chat", reply)

    def test_ping(self) -> None:
        self.assertEqual(build_reply({"text": "/ping"}), "pong")

    def test_chat_id(self) -> None:
        self.assertEqual(build_reply({"text": "/chatid", "chat": {"id": 42}}), "Chat-ID: 42")

    def test_echoes_plain_text(self) -> None:
        self.assertEqual(build_reply({"text": "Hallo Bot"}), "Echo: Hallo Bot")

    def test_ignores_non_text_messages(self) -> None:
        self.assertIsNone(build_reply({"photo": []}))

    def test_understands_commands_addressed_to_bot(self) -> None:
        self.assertEqual(build_reply({"text": "/ping@my_test_bot"}), "pong")

    def test_uses_configured_command_reply(self) -> None:
        instructions = BotInstructions(commands={"/status": "Laeuft fuer {first_name}."})

        reply = build_reply({"text": "/status", "from": {"first_name": "Ada"}}, instructions)

        self.assertEqual(reply, "Laeuft fuer Ada.")

    def test_program_history_command_uses_builtin_reply_before_configured_commands(self) -> None:
        instructions = BotInstructions(commands={"/history": "Configured history."})

        reply = build_reply({"text": "/history"}, instructions, project_root=Path("/does/not/exist"))

        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertIn("GitHub", reply)
        self.assertIn("- Repo: https://github.com/H234598/TeeBotus", reply)
        self.assertNotEqual(reply, "Configured history.")

    def test_program_history_natural_language_request_is_hardwired(self) -> None:
        instructions = BotInstructions(openai_enabled=True)

        reply = build_reply({"text": "Was ist neu?"}, instructions, include_fallback=False, project_root=Path("/does/not/exist"))

        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertIn("- Commits: https://github.com/H234598/TeeBotus/commits/main", reply)

    def test_program_history_detection_avoids_generic_commit_request(self) -> None:
        self.assertTrue(is_program_history_request("Zeig mir bitte die Commit Historie"))
        self.assertTrue(is_program_history_request("Welche Programmänderungen gab es?"))
        self.assertTrue(is_program_history_request("Zeig mir die Programhistorie"))
        self.assertTrue(is_program_history_request("Was ist mit neuen Features?"))
        self.assertTrue(is_program_history_request("Welche Github Comitts gab es?"))
        self.assertFalse(is_program_history_request("commit bitte"))

    def test_uses_exact_text_reply_before_echo(self) -> None:
        instructions = BotInstructions(text_replies={"hallo": "Hallo zurueck."})

        self.assertEqual(build_reply({"text": "Hallo"}, instructions), "Hallo zurueck.")

    def test_can_disable_echo(self) -> None:
        instructions = BotInstructions(echo_enabled=False)

        self.assertIsNone(build_reply({"text": "irgendwas"}, instructions))

    def test_openai_enabled_suppresses_echo_when_requested(self) -> None:
        instructions = BotInstructions(openai_enabled=True)

        self.assertIsNone(build_reply({"text": "freie Frage"}, instructions, include_fallback=False))

    def test_readme_documents_youtube_transcription_runtime_guards(self) -> None:
        readme = Path(__file__).resolve().parents[1] / "README.md"
        text = readme.read_text(encoding="utf-8")

        for needle in [
            "faster-whisper",
            "tiny",
            "nice -n 19",
            "ionice -c 3",
            "7200",
            "5, 15, 60 und 90 Minuten",
            "Watchdog",
            "resource_tracker",
        ]:
            self.assertIn(needle, text)

    def test_user_facing_docs_do_not_expose_internal_habit_filename(self) -> None:
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        privacy = (root / "docs" / "privacy-and-encryption.md").read_text(encoding="utf-8")
        defaults = (root / "ALL_BOTS_DEFAULT.md").read_text(encoding="utf-8")

        self.assertNotIn("User_Habbits_and_behave", readme)
        self.assertNotIn("User_Habbits_and_behave", privacy)
        self.assertNotIn("User_Habbits_and_behave", defaults)
        self.assertIn("Interne operatorgepflegte Hinweise", readme)
        self.assertIn("Operator-maintained internal notes", privacy)
        self.assertIn("interne operatorgepflegte Hinweise", defaults)
        self.assertIn("Structured user memory is encrypted", privacy)


if __name__ == "__main__":
    unittest.main()
