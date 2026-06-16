from __future__ import annotations

from pathlib import Path


README = Path(__file__).resolve().parents[1] / "README.md"


def test_readme_documents_plan2_llm_rag_graph_and_benchmark_topics() -> None:
    text = README.read_text(encoding="utf-8")

    assert "## LLM-Router und Providerprofile" in text
    assert "Ollama Quickstart" in text
    assert "Hugging Face" in text
    assert "Groq" in text
    assert "Gemini" in text
    assert "LiteLLM-Security" in text
    assert "Rollback" in text
    assert "schnellen OpenAI-Rollback" in text
    assert "Git-Rollback" in text
    assert "Daten-Rollback" in text
    assert "Bibliothekar-/Haystack-/Qdrant-Indizes sind rebuildbar" in text
    assert "memory-recovery --instances-dir instances --instances <Instanz>" in text
    assert "memory-recovery --instances-dir instances --legacy-instances-dir" in text
    assert "scripts/import_legacy_user_memory.py" in text
    assert "check_plan2_acceptance.py --skip-runtime-status --legacy-instances-dir /home/teladi/TeeBotus.bak2" in text
    assert "Backup-Root oder direkt auf einen konkreten `instances*`-Unterordner" in text
    assert "/home/teladi/TeeBotus.bak2/instances.bak" in text
    assert "--json-output /home/teladi/Downloads/teebotus-legacy-import-preflight.json" in text
    assert "--markdown-output /home/teladi/Downloads/teebotus-legacy-import-preflight.md" in text
    assert "apply_safety" in text
    assert "apply_allowed_now=true" in text
    assert "running_bot_process_count=0" in text
    assert "--replace-unreadable-account-metadata --apply" in text
    assert "Account_Memory.sqlite3" in text
    assert "## Bibliothekar, Haystack und LangGraph" in text
    assert "Account-Memory wird nicht in Haystack/Qdrant indexiert" in text
    assert "teebotus-qdrant-systemd" in text
    assert "gepinnten `qdrant/qdrant`-Image-Tag statt `latest`" in text
    assert "keine Zugangsdaten, Query-Parameter oder Fragmente" in text
    assert "Normale Chatantworten" in text
    assert "--category" in text
    assert "dieselben Filter laufen ueber den lokalen Store und das Haystack/Qdrant-Backend" in text
    assert "scripts/run_benchmarks.py --quick" in text
    assert "--baseline-json /home/teladi/Downloads/teebotus-benchmarks-latest.json" in text
    assert "scripts/check_plan2_acceptance.py" in text
    assert "startet keine Bot-Loops" in text
    assert "teebotus-systemd" in text
    assert "NoNewPrivileges=true" in text
    assert "PrivateTmp=true" in text
    assert "--include-qdrant-live" in text
    assert "--include-audit" in text
    assert "tests/test_llm_client.py" in text
    assert "tests/test_llm_package.py" in text
    assert "tests/test_openai_client.py" in text
    assert "tests/test_llm_base.py" not in text
    assert "tests/test_openai_provider.py" not in text
    assert "Der Acceptance-Runner nimmt die aktuellen" in text
    assert "ReminderDecision" in text
    assert "wiederkehrendes Reminder-Item" in text
    assert "MemoryCandidate" in text
    assert "sensitivity=high" in text
    assert "tests/test_llm_config.py" in text
    assert "tests/test_litellm_provider.py" in text
    assert "tests/test_bibliothekar_*.py" in text
    assert "tests/test_secret_hygiene.py" in text
    assert "## MCP/FastMCP Pilot" in text
    assert "bibliothekar.search" in text
    assert "memory.search" in text


def test_readme_documents_local_vs_remote_provider_boundary() -> None:
    text = README.read_text(encoding="utf-8")

    assert "Remote-Fallbacks sind standardmaessig aus" in text
    assert "Ollama ist der bevorzugte lokale Textprovider" in text
    assert "Keine Provider-Keys gehoeren ins Repo" in text


def test_readme_documents_telegram_as_runtime_slot_not_entrypoint_special_case() -> None:
    text = README.read_text(encoding="utf-8")

    assert "additiven Runtime-Slots fuer Telegram, Signal und Matrix" in text
    assert "Telegram, Signal und Matrix werden ueber dieselbe Runtime-Konfiguration" in text
    assert "Telegram-Long-Poller bleibt nur der konkrete Telegram-Transport" in text
    assert "Telegram laeuft weiter ueber `TeeBotus/adapters/telegram_runtime.py`" not in text
    assert "Plan3 Account-Runtime" not in text


def test_readme_has_privacy_docs_in_de_and_en() -> None:
    text = README.read_text(encoding="utf-8")

    assert "docs/privacy-and-encryption.de.md" in text
    assert "docs/privacy-and-encryption.en.md" in text


def test_readme_uses_placeholder_secrets_only() -> None:
    text = README.read_text(encoding="utf-8")

    assert "sk-" not in text
    assert "xoxb-" not in text
    assert "postgresql://USER:PASSWORD@HOST:5432/DBNAME" in text
    assert "syt_..." in text
