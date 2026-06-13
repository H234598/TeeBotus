import unittest
from unittest.mock import patch

from telegram_bot.instructions import BotInstructions
from telegram_bot.openai_client import (
    OpenAIAPIError,
    OpenAIClient,
    build_response_payload,
    build_speech_payload,
    build_transcription_fields,
    extract_output_text,
    extract_transcription_text,
    summarize_empty_response,
)


class OpenAIClientTests(unittest.TestCase):
    def test_build_response_payload_includes_flex_service_tier(self) -> None:
        instructions = BotInstructions(openai_service_tier="flex", openai_timeout_seconds=900)

        payload = build_response_payload("Hallo", instructions, "resp_old")

        self.assertEqual(payload["service_tier"], "flex")
        self.assertEqual(payload["previous_response_id"], "resp_old")

    def test_build_response_payload_uses_combined_instruction_text(self) -> None:
        instructions = BotInstructions(openai_system_prompt="Basis.", openai_rule_text="Regelwerk.")

        payload = build_response_payload("Hallo", instructions)

        self.assertIn("Basis.", payload["instructions"])
        self.assertIn("Bot_Rüstzeug.md", payload["instructions"])
        self.assertIn("Regelwerk.", payload["instructions"])

    def test_build_response_payload_includes_optional_web_search(self) -> None:
        instructions = BotInstructions(openai_web_search=True, openai_web_search_context_size="medium")

        payload = build_response_payload("Was ist heute passiert?", instructions)

        self.assertEqual(payload["tools"], [{"type": "web_search", "search_context_size": "medium"}])
        self.assertEqual(payload["tool_choice"], "auto")

    def test_build_response_payload_can_require_web_search(self) -> None:
        instructions = BotInstructions(openai_web_search=True, openai_web_search_required=True)

        payload = build_response_payload("Suche zwingend.", instructions)

        self.assertEqual(payload["tool_choice"], "required")

    def test_build_speech_payload_uses_voice_settings(self) -> None:
        instructions = BotInstructions(
            openai_voice_model="gpt-4o-mini-tts",
            openai_voice="sage",
            openai_voice_format="opus",
            openai_voice_speed=1.2,
            openai_voice_instructions="Ruhig sprechen.",
        )

        payload = build_speech_payload("Hallo", instructions)

        self.assertEqual(
            payload,
            {
                "model": "gpt-4o-mini-tts",
                "input": "Hallo",
                "voice": "sage",
                "response_format": "opus",
                "speed": 1.2,
                "instructions": "Ruhig sprechen.",
            },
        )

    def test_build_speech_payload_omits_instructions_for_legacy_tts(self) -> None:
        instructions = BotInstructions(openai_voice_model="tts-1", openai_voice_instructions="Ignored.")

        payload = build_speech_payload("Hallo", instructions)

        self.assertNotIn("instructions", payload)

    def test_build_transcription_fields_uses_transcription_settings(self) -> None:
        instructions = BotInstructions(
            openai_transcription_model="gpt-4o-mini-transcribe",
            openai_transcription_language="de",
            openai_transcription_prompt="Wortgetreu transkribieren.",
        )

        fields = build_transcription_fields(instructions)

        self.assertEqual(
            fields,
            {
                "model": "gpt-4o-mini-transcribe",
                "response_format": "json",
                "language": "de",
                "prompt": "Wortgetreu transkribieren.",
            },
        )

    def test_build_transcription_fields_omits_empty_optional_values(self) -> None:
        instructions = BotInstructions(openai_transcription_language="", openai_transcription_prompt="")

        fields = build_transcription_fields(instructions)

        self.assertEqual(fields, {"model": "gpt-4o-mini-transcribe", "response_format": "json"})

    def test_build_transcription_fields_can_override_model(self) -> None:
        instructions = BotInstructions(openai_transcription_model="gpt-4o-mini-transcribe")

        fields = build_transcription_fields(instructions, model="whisper-1")

        self.assertEqual(fields["model"], "whisper-1")

    def test_transcribe_audio_timeout_is_api_error(self) -> None:
        client = OpenAIClient("test-key", timeout=1)

        with patch("telegram_bot.openai_client.urllib.request.urlopen", side_effect=TimeoutError("read timed out")):
            with self.assertRaises(OpenAIAPIError):
                client.transcribe_audio(b"audio", "voice.ogg", BotInstructions(openai_timeout_seconds=1))

    def test_extract_output_text_from_direct_field(self) -> None:
        self.assertEqual(extract_output_text({"output_text": " Hallo "}), "Hallo")

    def test_extract_output_text_from_output_items(self) -> None:
        payload = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "Hallo"},
                        {"type": "output_text", "text": "Welt"},
                    ],
                }
            ]
        }

        self.assertEqual(extract_output_text(payload), "Hallo\nWelt")

    def test_extract_refusal_as_text(self) -> None:
        payload = {"output": [{"content": [{"type": "refusal", "refusal": "Nein."}]}]}

        self.assertEqual(extract_output_text(payload), "Nein.")

    def test_extract_transcription_text(self) -> None:
        self.assertEqual(extract_transcription_text({"text": " Hallo "}), "Hallo")
        self.assertEqual(extract_transcription_text({"text": ""}), "")

    def test_summarize_empty_response_does_not_dump_full_payload(self) -> None:
        summary = summarize_empty_response(
            {
                "id": "resp_123",
                "status": "incomplete",
                "service_tier": "flex",
                "incomplete_details": {"reason": "max_output_tokens"},
                "usage": {
                    "output_tokens": 700,
                    "output_tokens_details": {"reasoning_tokens": 700},
                    "input_tokens": 29000,
                },
                "output": [{"large": "payload"}],
            },
            700,
        )

        self.assertIn("id='resp_123'", summary)
        self.assertIn("reasoning_tokens=700", summary)
        self.assertIn("reasoning consumed the full output budget", summary)
        self.assertNotIn("large", summary)


if __name__ == "__main__":
    unittest.main()
