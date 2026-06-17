import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from TeeBotus.instructions import InstructionStore, load_instructions, parse_instructions, render_template


class InstructionTests(unittest.TestCase):
    def test_openai_error_settings_remain_text_llm_compatible(self) -> None:
        instructions = parse_instructions(
            """
            ## OpenAI
            - error: OpenAI kaputt.
            - missing_key: OpenAI-Key fehlt.
            - reset: OpenAI-Reset.
            """
        )

        self.assertEqual(instructions.openai_error, "OpenAI kaputt.")
        self.assertEqual(instructions.openai_missing_key, "OpenAI-Key fehlt.")
        self.assertEqual(instructions.openai_reset, "OpenAI-Reset.")
        self.assertEqual(instructions.llm_error, "OpenAI kaputt.")
        self.assertEqual(instructions.llm_missing_key, "OpenAI-Key fehlt.")
        self.assertEqual(instructions.llm_reset, "OpenAI-Reset.")

    def test_llm_reply_settings_win_over_later_openai_legacy_settings(self) -> None:
        instructions = parse_instructions(
            """
            ## LLM
            - error: LLM kaputt.
            - missing_key: LLM-Key fehlt.
            - reset: LLM-Reset.

            ## OpenAI
            - error: OpenAI kaputt.
            - missing_key: OpenAI-Key fehlt.
            - reset: OpenAI-Reset.
            """
        )

        self.assertEqual(instructions.openai_error, "OpenAI kaputt.")
        self.assertEqual(instructions.openai_missing_key, "OpenAI-Key fehlt.")
        self.assertEqual(instructions.openai_reset, "OpenAI-Reset.")
        self.assertEqual(instructions.llm_error, "LLM kaputt.")
        self.assertEqual(instructions.llm_missing_key, "LLM-Key fehlt.")
        self.assertEqual(instructions.llm_reset, "LLM-Reset.")

    def test_structured_decision_enabled_can_be_configured(self) -> None:
        disabled = parse_instructions(
            """
            ## LLM
            - structured_decision_enabled: nein
            """
        )
        enabled = parse_instructions(
            """
            ## Einstellungen
            - structured_decisions_enabled: ja
            """
        )

        self.assertFalse(disabled.structured_decision_enabled)
        self.assertTrue(enabled.structured_decision_enabled)

    def test_parse_markdown_instructions(self) -> None:
        account_a = "a" * 128
        account_b = "b" * 128
        instructions = parse_instructions(
            """
            # Bot_Verhalten.md

            ## Einstellungen
            - echo: nein
            - echo_prefix: Antwort:

            ## OpenAI
            - enabled: ja
            - provider: litellm
            - llm_model: ollama/llama3.1:8b
            - llm_fallback_models: groq/llama-3.3-70b-versatile, gemini/gemini-2.5-flash
            - base_url: http://localhost:11434
            - api_key_env: OLLAMA_API_KEY
            - model: gpt-5.5
            - service_tier: flex
            - rule_file: Analyse.md
            - web_search: ja
            - web_search_context_size: medium
            - web_search_required: nein
            - max_output_tokens: 300
            - timeout_seconds: 900
            - voice_enabled: ja
            - voice_model: gpt-4o-mini-tts
            - voice: sage
            - voice_format: opus
            - voice_speed: 1.2
            - voice_max_input_chars: 4000
            - voice_instructions: Ruhig mittelfraenkisch sprechen.
            - auto_voice_enabled: ja
            - auto_voice_every: 3
            - auto_voice_max_words: 50
            - auto_voice_skip_sources: ja
            - image_enabled: ja
            - image_model: gpt-image-1
            - image_size: 1024x1024
            - image_quality: low
            - image_format: png
            - image_max_prompt_chars: 1500
            - image_max_per_24h: 2
            - image_min_interval_minutes: 45
            - image_error: Bild kaputt.
            - image_rate_limited: Zu viele Bilder.
            - transcription_enabled: ja
            - transcription_backend: local
            - transcription_model: gpt-4o-mini-transcribe
            - transcription_fallback_model: whisper-1
            - local_transcription_model: small
            - transcription_language: de
            - transcription_prompt: Wortgetreu transkribieren.
            - transcription_error: Transkription fehlgeschlagen.
            - transcription_empty: Keine Sprache erkannt.
            - youtube_option_llm_fallback: ja
            - error: OpenAI kaputt.
            - missing_key: OpenAI-Key fehlt.

            ## LLM
            - enabled: ja
            - profile: local_ollama
            - provider: ollama
            - model: llama3.1:8b
            - fallback_models: groq/llama-3.1-8b-instant
            - base_url: http://127.0.0.1:11434
            - api_key_env: LOCAL_LLM_KEY
            - timeout_seconds: 180
            - max_output_tokens: 456
            - temperature: 0.7
            - error: LLM kaputt.
            - missing_key: LLM-Key fehlt.
            - reset: LLM-Reset.

            ## Codex
            - enabled: ja
            - allowed_account_ids: __ACCOUNT_A__, __ACCOUNT_B__
            - timeout_seconds: 180

            ## Proactive
            - model_planner: llm

            ## Antworten
            - start: Moin{name_suffix}
            - user_memory_reset_confirm: Wirklich loeschen?
            - user_memory_reset_success: Memory geloescht.
            - user_memory_reset_cancelled: Memory bleibt.
            - user_memory_reset_unavailable: Kein Memory aktiv.
            - user_memory_reset_error: Memory-Reset fehlgeschlagen.
            - user_memory_error: Memory-Speicher kaputt.
            - user_memory_reset_only_own: Nur eigenes Memory.
            - teladi_call_prompt: Nachricht fuer Teladi?
            - teladi_call_sent: Nachricht gesendet.
            - teladi_call_cooldown: Warte {remaining}.
            - teladi_call_error: Versand fehlgeschlagen.
            - codex_usage: Nutzung: /codex Text.
            - codex_unauthorized: Kein Zugriff.
            - codex_not_found: Codex fehlt.
            - codex_error: Codex kaputt.
            - codex_empty: Keine Ausgabe.

            ## Befehle
            - /status: Alles ok.

            ## Textantworten
            - hallo: Hey.

            ## Enthaelt
            - hilfe: Sende /help.

            ## Systemprompt
            Du bist kurz.
            Antworte auf Deutsch.

            ## Hilfe
            - /status - Status anzeigen
            """
            .replace("__ACCOUNT_A__", account_a)
            .replace("__ACCOUNT_B__", account_b)
        )

        self.assertFalse(instructions.echo_enabled)
        self.assertEqual(instructions.echo_prefix, "Antwort:")
        self.assertTrue(instructions.openai_enabled)
        self.assertTrue(instructions.llm_enabled)
        self.assertTrue(instructions.text_llm_enabled())
        self.assertEqual(instructions.llm_profile, "local_ollama")
        self.assertEqual(instructions.llm_provider, "ollama")
        self.assertEqual(instructions.llm_model, "llama3.1:8b")
        self.assertEqual(instructions.llm_fallback_models, ("groq/llama-3.1-8b-instant",))
        self.assertEqual(instructions.llm_base_url, "http://127.0.0.1:11434")
        self.assertEqual(instructions.llm_api_key_env, "LOCAL_LLM_KEY")
        self.assertEqual(instructions.llm_timeout_seconds, 180)
        self.assertEqual(instructions.llm_max_output_tokens, 456)
        self.assertEqual(instructions.llm_temperature, 0.7)
        self.assertEqual(instructions.llm_error, "LLM kaputt.")
        self.assertEqual(instructions.llm_missing_key, "LLM-Key fehlt.")
        self.assertEqual(instructions.llm_reset, "LLM-Reset.")
        self.assertEqual(instructions.openai_model, "gpt-5.5")
        self.assertEqual(instructions.openai_service_tier, "flex")
        self.assertEqual(instructions.openai_rule_file, "Analyse.md")
        self.assertTrue(instructions.openai_web_search)
        self.assertEqual(instructions.openai_web_search_context_size, "medium")
        self.assertFalse(instructions.openai_web_search_required)
        self.assertEqual(instructions.openai_max_output_tokens, 300)
        self.assertEqual(instructions.openai_timeout_seconds, 900)
        self.assertTrue(instructions.openai_voice_enabled)
        self.assertEqual(instructions.openai_voice_model, "gpt-4o-mini-tts")
        self.assertEqual(instructions.openai_voice, "sage")
        self.assertEqual(instructions.openai_voice_format, "opus")
        self.assertEqual(instructions.openai_voice_speed, 1.2)
        self.assertEqual(instructions.openai_voice_max_input_chars, 4000)
        self.assertEqual(instructions.openai_voice_instructions, "Ruhig mittelfraenkisch sprechen.")
        self.assertTrue(instructions.openai_auto_voice_enabled)
        self.assertEqual(instructions.openai_auto_voice_every, 3)
        self.assertEqual(instructions.openai_auto_voice_max_words, 50)
        self.assertTrue(instructions.openai_auto_voice_skip_sources)
        self.assertTrue(instructions.openai_image_enabled)
        self.assertEqual(instructions.openai_image_model, "gpt-image-1")
        self.assertEqual(instructions.openai_image_size, "1024x1024")
        self.assertEqual(instructions.openai_image_quality, "low")
        self.assertEqual(instructions.openai_image_format, "png")
        self.assertEqual(instructions.openai_image_max_prompt_chars, 1500)
        self.assertEqual(instructions.openai_image_max_per_24h, 2)
        self.assertEqual(instructions.openai_image_min_interval_minutes, 45)
        self.assertEqual(instructions.openai_image_error, "Bild kaputt.")
        self.assertEqual(instructions.openai_image_rate_limited, "Zu viele Bilder.")
        self.assertIn("[[TEE_IMAGE", instructions.openai_instructions_text())
        self.assertTrue(instructions.openai_transcription_enabled)
        self.assertEqual(instructions.openai_transcription_backend, "local")
        self.assertEqual(instructions.openai_transcription_model, "gpt-4o-mini-transcribe")
        self.assertEqual(instructions.openai_transcription_fallback_model, "whisper-1")
        self.assertEqual(instructions.local_transcription_model, "small")
        self.assertEqual(instructions.openai_transcription_language, "de")
        self.assertEqual(instructions.openai_transcription_prompt, "Wortgetreu transkribieren.")
        self.assertEqual(instructions.openai_transcription_error, "Transkription fehlgeschlagen.")
        self.assertEqual(instructions.openai_transcription_empty, "Keine Sprache erkannt.")
        self.assertTrue(instructions.youtube_option_llm_fallback)
        self.assertEqual(instructions.openai_error, "OpenAI kaputt.")
        self.assertEqual(instructions.openai_missing_key, "OpenAI-Key fehlt.")
        self.assertTrue(instructions.codex_enabled)
        self.assertEqual(
            instructions.codex_allowed_account_ids,
            (account_a, account_b),
        )
        self.assertEqual(instructions.proactive_model_planner, "llm")
        self.assertEqual(instructions.codex_timeout_seconds, 180)
        self.assertFalse(instructions.user_memory_enabled)
        self.assertEqual(instructions.openai_system_prompt, "Du bist kurz.\nAntworte auf Deutsch.")
        self.assertEqual(instructions.start, "Moin{name_suffix}")
        self.assertEqual(instructions.user_memory_reset_confirm, "Wirklich loeschen?")
        self.assertEqual(instructions.user_memory_reset_success, "Memory geloescht.")
        self.assertEqual(instructions.user_memory_reset_cancelled, "Memory bleibt.")
        self.assertEqual(instructions.user_memory_reset_unavailable, "Kein Memory aktiv.")
        self.assertEqual(instructions.user_memory_reset_error, "Memory-Reset fehlgeschlagen.")
        self.assertEqual(instructions.user_memory_error, "Memory-Speicher kaputt.")
        self.assertEqual(instructions.user_memory_reset_only_own, "Nur eigenes Memory.")
        self.assertEqual(instructions.teladi_call_prompt, "Nachricht fuer Teladi?")
        self.assertEqual(instructions.teladi_call_sent, "Nachricht gesendet.")
        self.assertEqual(instructions.teladi_call_cooldown, "Warte {remaining}.")
        self.assertEqual(instructions.teladi_call_error, "Versand fehlgeschlagen.")
        self.assertEqual(instructions.codex_usage, "Nutzung: /codex Text.")
        self.assertEqual(instructions.codex_unauthorized, "Kein Zugriff.")
        self.assertEqual(instructions.codex_not_found, "Codex fehlt.")
        self.assertEqual(instructions.codex_error, "Codex kaputt.")
        self.assertEqual(instructions.codex_empty, "Keine Ausgabe.")
        self.assertEqual(instructions.commands["/status"], "Alles ok.")
        self.assertEqual(instructions.text_replies["hallo"], "Hey.")
        self.assertEqual(instructions.contains_replies["hilfe"], "Sende /help.")
        self.assertEqual(instructions.help_text(), "Befehle:\n/status - Status anzeigen")

    def test_codex_whitelist_accepts_only_account_ids(self) -> None:
        account_id = "c" * 128

        instructions = parse_instructions(
            """
            ## Codex
            - allowed_sender_ids: 456
            - allowed_account_ids: 123, __ACCOUNT_ID__
            """.replace("__ACCOUNT_ID__", account_id)
        )

        self.assertEqual(instructions.codex_allowed_account_ids, (account_id,))

    def test_memory_search_section_settings_are_parsed(self) -> None:
        instructions = parse_instructions(
            """
            ## Memory Search
            - semantic_enabled: ja
            - semantic_backend: qdrant
            - local_limit: 3
            - semantic_limit: 5
            - qdrant_url: http://localhost:6334
            """
        )

        self.assertTrue(instructions.memory_search_semantic_enabled)
        self.assertEqual(instructions.memory_search_semantic_backend, "qdrant")
        self.assertEqual(instructions.memory_search_local_limit, 3)
        self.assertEqual(instructions.memory_search_semantic_limit, 5)
        self.assertEqual(instructions.memory_search_qdrant_url, "http://localhost:6334")

    def test_memory_search_settings_accept_prefixed_settings_keys(self) -> None:
        instructions = parse_instructions(
            """
            ## Einstellungen
            - memory_search_semantic_enabled: true
            - memory_search_semantic_backend: qdrant
            """
        )

        self.assertTrue(instructions.memory_search_semantic_enabled)
        self.assertEqual(instructions.memory_search_semantic_backend, "qdrant")

    def test_render_template_uses_safe_placeholders(self) -> None:
        rendered = render_template(
            "Hallo{name_suffix}, Chat {chat_id}, Text {text}, Unbekannt {missing}",
            {"chat": {"id": 7}, "from": {"first_name": "Ada"}},
            "ping",
        )

        self.assertEqual(rendered, "Hallo, Ada, Chat 7, Text ping, Unbekannt ")

    def test_system_prompt_keeps_markdown_subheadings(self) -> None:
        instructions = parse_instructions(
            """
            ## Systemprompt
            Vorher.

            ### Rolle
            Bleibt im Prompt.

            #### Detail
            Bleibt auch.

            ## Befehle
            - /status: ok
            """
        )

        self.assertIn("### Rolle", instructions.openai_system_prompt)
        self.assertIn("#### Detail", instructions.openai_system_prompt)
        self.assertIn("Bleibt im Prompt.", instructions.openai_system_prompt)
        self.assertEqual(instructions.commands["/status"], "ok")

    def test_wrapped_list_values_continue_previous_item(self) -> None:
        instructions = parse_instructions(
            """
            ## OpenAI
            - voice_instructions: Sprich natuerlich und verstaendlich.
            Nutze keine Karikatur.

            ## Hilfe
            - /voice Text - Text als Sprachnachricht senden.
            Ohne Text nutzt /voice die beantwortete Nachricht.
            """
        )

        self.assertEqual(
            instructions.openai_voice_instructions,
            "Sprich natuerlich und verstaendlich. Nutze keine Karikatur.",
        )
        self.assertEqual(
            instructions.help_lines,
            ("/voice Text - Text als Sprachnachricht senden. Ohne Text nutzt /voice die beantwortete Nachricht.",),
        )

    def test_instruction_store_reads_markdown_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Bot_Verhalten.md"
            path.write_text("## Befehle\n- /status: Aus Datei.", encoding="utf-8")

            instructions = InstructionStore(path).get()

        self.assertEqual(instructions.commands["/status"], "Aus Datei.")

    def test_load_instructions_adds_adjacent_rule_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Bot_Verhalten.md"
            rule_path = Path(directory) / "Bot_Rüstzeug.md"
            path.write_text("## Systemprompt\nBasis.\n", encoding="utf-8")
            rule_path.write_text("Regelwerk fuer jedes Gespraech.", encoding="utf-8")

            instructions = load_instructions(path)

        self.assertEqual(instructions.openai_rule_file, "Bot_Rüstzeug.md")
        self.assertEqual(instructions.openai_rule_text, "Regelwerk fuer jedes Gespraech.")
        self.assertIn("Basis.", instructions.openai_instructions_text())
        self.assertIn("Regelwerk fuer jedes Gespraech.", instructions.openai_instructions_text())

    def test_load_instructions_uses_configured_rule_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Bot_Verhalten.md"
            rule_path = Path(directory) / "Analyse.md"
            path.write_text("## OpenAI\n- rule_file: Analyse.md\n", encoding="utf-8")
            rule_path.write_text("Spezielle Analyse.", encoding="utf-8")

            instructions = load_instructions(path)

        self.assertEqual(instructions.openai_rule_file, "Analyse.md")
        self.assertEqual(instructions.openai_rule_text, "Spezielle Analyse.")

    def test_load_instructions_merges_all_bots_default_before_instance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            default_path = root / "ALL_BOTS_DEFAULT.md"
            instance_path = root / "instances" / "Demo" / "Bot_Verhalten.md"
            instance_path.parent.mkdir(parents=True)
            default_path.write_text(
                """
                ## Prompt
                Gemeinsamer Prompt.

                ## OpenAI
                - model: default-model
                - max_output_tokens: 123

                ## Securityantworten
                - short: Kurz.
                - full: Voll.

                ## Systemprompt
                Defaultprompt.

                ## Befehle
                - /default: Aus Default.
                """,
                encoding="utf-8",
            )
            (root / "EASTER_EGGS.json").write_text(
                '{"security": {"easter_egg": "Erfundener Witz aus JSON."}}\n',
                encoding="utf-8",
            )
            instance_path.write_text(
                """
                ## OpenAI
                - model: instance-model

                ## Befehle
                - /status: Aus Instanz.

                ## Systemprompt
                Instanzprompt.
                """,
                encoding="utf-8",
            )

            with patch("TeeBotus.instructions.PROJECT_ROOT", root):
                instructions = load_instructions(instance_path)

        self.assertEqual(instructions.openai_model, "instance-model")
        self.assertEqual(instructions.openai_max_output_tokens, 123)
        self.assertEqual(instructions.openai_system_prompt, "Instanzprompt.\n\nDefaultprompt.")
        self.assertEqual(instructions.commands["/default"], "Aus Default.")
        self.assertEqual(instructions.commands["/status"], "Aus Instanz.")
        self.assertIn("Gemeinsamer Prompt.", instructions.openai_instructions_text())
        self.assertIn("Defaultprompt.", instructions.openai_instructions_text())
        self.assertIn("Instanzprompt.", instructions.openai_instructions_text())
        self.assertIn("Kurz.", instructions.openai_instructions_text())
        self.assertIn("Voll.", instructions.openai_instructions_text())
        self.assertIn("Erfundener Witz aus JSON.", instructions.openai_instructions_text())

    def test_instruction_store_uses_all_bots_default_when_instance_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ALL_BOTS_DEFAULT.md").write_text(
                """
                ## Befehle
                - /default: Aus Default.
                """,
                encoding="utf-8",
            )

            with patch("TeeBotus.instructions.PROJECT_ROOT", root):
                instructions = InstructionStore(root / "instances" / "Demo" / "Bot_Verhalten.md").get()

        self.assertEqual(instructions.commands["/default"], "Aus Default.")


if __name__ == "__main__":
    unittest.main()
