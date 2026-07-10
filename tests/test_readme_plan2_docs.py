from __future__ import annotations

import re
from pathlib import Path
README = Path(__file__).resolve().parents[1] / "README.md"
PLAN2 = Path(__file__).resolve().parents[1] / "docs" / "Plan2.md"


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
    assert "check_plan2_acceptance.py --skip-runtime-status --legacy-instances-dir /home/teladi/TeeBotus_Backups/TeeBotus.bak2" in text
    assert "Backup-Root oder direkt auf einen konkreten `instances*`-Unterordner" in text
    assert "/home/teladi/TeeBotus_Backups/TeeBotus.bak2/instances.bak" in text
    assert re.search(r"--json-output\s+\S+/teebotus-legacy-import-preflight\.json", text)
    assert re.search(r"--markdown-output\s+\S+/teebotus-legacy-import-preflight\.md", text)
    assert "apply_safety" in text
    assert "apply_allowed_now=true" in text
    assert "running_bot_process_count=0" in text
    assert "--replace-unreadable-account-metadata --apply" in text
    assert "Account_Memory.sqlite3" in text
    assert "## Bibliothekar, Haystack und LangGraph" in text
    assert "Account-Memory wird nicht in Haystack und nicht als Klartext in Qdrant" in text
    assert "Qdrant darf fuer\nUsermemory nur als optionaler, rebuildbarer ID-/Vektor-Cache dienen" in text
    assert "/reset_memorys` loescht bei aktiver semantischer Qdrant-Suche" in text
    assert "teebotus-embedding --instances-dir instances --instance Depressionsbot memory-rebuild" in text
    assert "teebotus-embedding --instances-dir instances --instance Depressionsbot bibliothekar-rebuild" in text
    assert "ohne\nEmbedding-Override nutzt der Operatorpfad einen lokalen Fake-Embeddingvertrag" in text
    assert "teebotus-qdrant-systemd" in text
    assert "gepinnten `qdrant/qdrant`-Image-Tag statt `latest`" in text
    assert "mit gueltigem Port" in text
    assert "keine Zugangsdaten, Pfade, Query-Parameter oder Fragmente" in text
    assert "Normale Chatantworten" in text
    assert "--category" in text
    assert "--keyword" in text
    assert "--relative-path" in text
    assert "--extension" in text
    assert "dieselben Filter laufen ueber den lokalen Store und das Haystack/Qdrant-Backend" in text
    assert "scripts/run_benchmarks.py --quick" in text
    assert re.search(r"--baseline-json\s+\S+/teebotus-benchmarks-latest\.json", text)
    assert "scripts/check_plan2_acceptance.py" in text
    assert "startet keine Bot-Loops" in text
    assert "--adapter-deps-python-only" in text
    assert "native `signal-cli` Checks" in text
    assert "bleiben." in text
    assert "nicht mit `--skip-adapter-deps`" in text
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
    assert "Plan2-relevanten `tests/test_*.py`-Module" in text
    assert "Standardpfad bleiben Legacy-Import-Unit-Tests bewusst ausgeklammert" in text
    assert "`--include-legacy-import-tests` muss der Runner die komplette Repo-Testflaeche" in text
    assert "ReminderDecision" in text
    assert "wiederkehrendes Reminder-Item" in text
    assert "MemoryCandidate" in text
    assert "sensitivity=high" in text
    assert "tests/test_llm_config.py" in text
    assert "tests/test_litellm_provider.py" in text
    assert "`missing_key`, `error` und `reset` im `## LLM`-Block steuern nur Text-LLM-Antworten" in text
    assert "OpenAI-spezifische Spezialfunktionen wie Voice, Bilder und OpenAI-Transkription" in text
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


def test_plan2_doc_tracks_current_pyproject_and_llm_contract() -> None:
    text = PLAN2.read_text(encoding="utf-8")

    assert 'dynamic = ["version"]' in text
    assert 'requires-python = ">=3.11"' in text
    assert 'version = "1.4.28"' not in text
    assert 'requires-python = ">=3.10"' not in text
    assert "requires-python >=3.10" not in text
    assert "ein neutraler llm_client existiert im aktuellen Stand noch nicht" not in text
    assert "nicht llm_provider/llm_model" not in text
    assert "llm_provider" in text
    assert "llm_model" in text
    assert "`missing_key`, `error` und `reset` im `## LLM`-Block sind die neutralen" in text
    assert "OpenAI-spezifische Spezialfunktionen wie Voice, Bilder und OpenAI-Transkription" in text
