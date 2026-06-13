import unittest
from pathlib import Path

from TeeBotus.handlers import HELP_TEXT, build_reply
from TeeBotus.instructions import BotInstructions


class HandlerTests(unittest.TestCase):
    def test_start_uses_first_name_when_available(self) -> None:
        reply = build_reply({"text": "/start", "from": {"first_name": "Ada"}})

        self.assertEqual(reply, "Hallo, Ada. Ich bin bereit. Sende /help fuer die Befehle.")

    def test_help_returns_command_list(self) -> None:
        reply = build_reply({"text": "/help"})

        self.assertEqual(reply, HELP_TEXT)
        self.assertIn("/reset - setzt nur den OpenAI-Verlauf", reply)
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

    def test_docs_do_not_claim_habit_markdown_is_encrypted(self) -> None:
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        privacy = (root / "docs" / "privacy-and-encryption.md").read_text(encoding="utf-8")
        defaults = (root / "ALL_BOTS_DEFAULT.md").read_text(encoding="utf-8")

        self.assertIn("User_Habbits_and_behave.md` bleibt absichtlich Klartext-Markdown", readme)
        self.assertIn("Operator-maintained Markdown notes remain plaintext", privacy)
        self.assertIn("Die admingepflegte `User_Habbits_and_behave.md` bleibt Klartext-Markdown", defaults)
        self.assertIn("Structured user memory is encrypted", privacy)


if __name__ == "__main__":
    unittest.main()
