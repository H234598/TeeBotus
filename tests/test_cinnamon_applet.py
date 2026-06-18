from __future__ import annotations

import json
import tomllib
from pathlib import Path

from TeeBotus.cinnamon_applet import parse_runtime_status


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPLET_DIR = PROJECT_ROOT / "files" / "teebotus@H234598"


def test_cinnamon_applet_files_are_present_and_wired() -> None:
    metadata = json.loads((APPLET_DIR / "metadata.json").read_text(encoding="utf-8"))
    schema = json.loads((APPLET_DIR / "settings-schema.json").read_text(encoding="utf-8"))
    source = (APPLET_DIR / "applet.js").read_text(encoding="utf-8")

    assert metadata["uuid"] == "teebotus@H234598"
    assert metadata["name"] == "TB"
    assert metadata["icon"] == "teebotus"
    assert (APPLET_DIR / "icon.svg").is_file()
    assert (APPLET_DIR / "SettingsLogo.py").is_file()
    assert (APPLET_DIR / "assets" / "teebotus.svg").is_file()
    assert (APPLET_DIR / "assets" / "settings-header-logo.svg").is_file()
    assert (APPLET_DIR / "assets" / "settings-about-logo.svg").is_file()
    assert (APPLET_DIR / "stylesheet.css").is_file()
    assert "new Settings.AppletSettings(this, UUID, instanceId)" in source
    assert "main-page" in schema["layout"]["pages"]
    assert "actions-page" in schema["layout"]["pages"]
    assert "settings-logo-header-section" in schema["layout"]["main-page"]["sections"]
    assert schema["settings-logo-header"]["type"] == "custom"
    assert schema["settings-logo-header"]["file"] == "SettingsLogo.py"
    assert schema["settings-logo-header"]["widget"] == "HeaderLogo"
    assert schema["about-logo"]["type"] == "custom"
    assert schema["about-logo"]["widget"] == "AboutLogo"
    assert schema["repo-path"]["default"] == "/home/teladi/TeeBotus"
    assert schema["channels"]["default"] == "telegram,signal"
    assert schema["runtime-unit"]["default"] == "teebotus.service"
    assert schema["qdrant-unit"]["default"] == "teebotus-qdrant.service"
    assert schema["qdrant-url"]["default"] == "http://127.0.0.1:6333"
    assert schema["status-timeout-seconds"]["default"] == 30
    assert "new PopupMenu.PopupMenuManager(this)" in source
    assert "new Applet.AppletPopupMenu(this, orientation)" in source
    assert "this.menuManager.addMenu(this.menu)" in source
    assert "Gio.SubprocessLauncher.new" in source
    assert "}, this._repoPath());" in source
    assert "launcher.set_cwd(String(cwd))" in source
    assert (PROJECT_ROOT / "scripts" / "install_cinnamon_applet.py").is_file()


def test_cinnamon_applet_main_menu_exposes_teebotus_features() -> None:
    source = (APPLET_DIR / "applet.js").read_text(encoding="utf-8")
    schema = json.loads((APPLET_DIR / "settings-schema.json").read_text(encoding="utf-8"))

    assert "teebotus-cinnamon-applet" not in source
    assert "TeeBotus.cinnamon_applet" in source
    assert 'this.statusMenu = new PopupMenu.PopupSubMenuMenuItem(_("Status & Diagnose"))' in source
    assert 'this.messengerMenu = new PopupMenu.PopupSubMenuMenuItem(_("Messenger"))' in source
    assert 'this.llmMenu = new PopupMenu.PopupSubMenuMenuItem(_("LLM & Dienste"))' in source
    assert 'this.apiMenu = new PopupMenu.PopupSubMenuMenuItem(_("API Keys & Usage"))' in source
    assert 'this.memoryMenu = new PopupMenu.PopupSubMenuMenuItem(_("Memory & Speicher"))' in source
    assert 'this.bibliothekarMenu = new PopupMenu.PopupSubMenuMenuItem(_("Bibliothekar"))' in source
    assert 'this.proactiveMenu = new PopupMenu.PopupSubMenuMenuItem(_("Proaktiv"))' in source
    assert 'this.actionsMenu = new PopupMenu.PopupSubMenuMenuItem(_("Bot-Steuerung"))' in source
    assert 'this.quickCommandsMenu = new PopupMenu.PopupSubMenuMenuItem(_("Schnellbefehle"))' in source
    assert "systemctl" in source
    assert "journalctl" in source
    assert "TeeBotus.bibliothekar" in source
    assert "TeeBotus.proactive" in schema["proactive-command"]["default"]
    assert "_formatMessengerLine" in source
    assert "_formatLlmLine" in source
    assert "_formatApiBudgetLine" in source
    assert "_formatMemoryLine" in source
    assert "Ersatz bei Modell-/Key-/Limitfehlern" in source
    assert "codex-usage latest" in source
    assert "Qdrant-Status" in source
    assert "Usermemory-Vektoranzahl" in source
    assert "TeeBotus.embedding" in source
    assert "/status" in source
    assert "/voicemodel" in source
    assert 'this.set_applet_label("TB")' in source


def test_cinnamon_applet_settings_cover_visible_sections_and_safety() -> None:
    schema = json.loads((APPLET_DIR / "settings-schema.json").read_text(encoding="utf-8"))

    assert schema["layout"]["sections-section"]["keys"] == [
        "show-messenger-section",
        "show-llm-section",
        "show-api-section",
        "show-memory-section",
        "show-bibliothekar-section",
        "show-proactive-section",
        "show-actions-section",
        "show-quick-commands-section",
        "show-project-section",
    ]
    assert schema["confirm-service-actions"]["default"] is True
    assert "zenity" in schema["confirm-service-actions"]["tooltip"]
    assert schema["enable-service-actions"]["default"] is True
    assert schema["terminal-command"]["default"] == ""
    assert "gnome-terminal" in schema["terminal-command"]["tooltip"]
    assert schema["codex-usage-path"]["default"] == "/home/teladi/codex-usage"
    assert schema["codex-usage-command"]["default"] == "codex-usage"


def test_cinnamon_applet_helper_parses_runtime_status_sections() -> None:
    parsed = parse_runtime_status(
        """
        TeeBotus runtime configuration resolves.

        [Konfiguration]
        instances=Bote_der_Wahrheit,Depressionsbot
        channels=telegram,signal

        [LLM-Routen und Backends]
        hf_pool=default status=disabled
        gemini_free_tier_limits status=no_limits_found source=ai.google.dev/gemini-api/docs/rate-limits
        llm_route=bibliothekar_answer status=configured

        [Memory und semantische Suche]
        qdrant=127.0.0.1:6333 status=reachable
        qdrant_collection=teebotus_user_memory target=127.0.0.1:6333 status=ready vector_size=64 embedding_model=teebotus-account-memory-hash
        qdrant_collection=teebotus_bibliothekar_chunks target=127.0.0.1:6333 status=ready vector_size=1024 embedding_model=BAAI/bge-m3
        memory_index=Depressionsbot backend=keyword status=ready semantic=ready

        [API Keys, Limits und Kosten]
        api_budget=bibliothekar_answer status=configured key=configured
        codex_usage=local status=ready snapshots=2
        codex_usage_account=BW_Work status=ok five_hour=1/100 weekly=5/100

        [Messenger]
        telegram_slot=Depressionsbot/telegram:1 status=configured token=configured
        signal_account=Depressionsbot/signal:1 status=registered

        [Tools und Account-Memory]
        account_memory=Depressionsbot/example status=ok
        """
    )

    assert parsed["summary"]["instances"] == "Bote_der_Wahrheit,Depressionsbot"
    assert parsed["summary"]["channels"] == "telegram,signal"
    assert parsed["summary"]["telegram_slots"] == 1
    assert parsed["summary"]["signal_accounts"] == 1
    assert parsed["summary"]["memory_accounts"] == 1
    assert parsed["summary"]["llm_routes"] == 1
    assert parsed["summary"]["api_budgets"] == 1
    assert parsed["summary"]["codex_usage"].startswith("codex_usage=local")
    assert parsed["summary"]["codex_usage_accounts"] == 1
    assert parsed["summary"]["gemini_free_tier"].startswith("gemini_free_tier_limits")
    assert parsed["summary"]["qdrant"].startswith("qdrant=127.0.0.1:6333")
    assert parsed["summary"]["qdrant_collections"] == 2
    assert parsed["summary"]["qdrant_ready_collections"] == 2
    assert parsed["summary"]["memory_semantic_ready"] == 1
    assert parsed["status_counts"]["configured"] == 3
    assert parsed["status_counts"]["ready"] == 4
    assert "Messenger" in parsed["sections"]


def test_cinnamon_applet_runtime_parser_redacts_secrets_without_losing_safe_metadata() -> None:
    github_token = "ghp_" + "1234567890ABCDEFGHIJK"

    parsed = parse_runtime_status(
        f"""
        [LLM-Routen und Backends]
        llm_route=normal_chat status=broken api_key={github_token} api_key_env=GEMINI_API_KEY api_key_ring=3 error=password:nested-secret

        [API Keys, Limits und Kosten]
        api_budget=normal_chat status=configured tokens=provider_usage_response+local_guard max_output_tokens=700

        [Messenger]
        telegram_slot=Demo/telegram:1 status=configured token=configured target=https://user:plainpass@example.test/path
        """
    )
    rendered = json.dumps(parsed, sort_keys=True)

    assert github_token not in rendered
    assert "nested-secret" not in rendered
    assert "user:plainpass" not in rendered
    assert "api_key=<redacted-secret>" in rendered
    assert "api_key_env=GEMINI_API_KEY" in rendered
    assert "api_key_ring=3" in rendered
    assert "password:<redacted>" in rendered
    assert "tokens=provider_usage_response+local_guard" in rendered
    assert "max_output_tokens=700" in rendered
    assert "token=configured" in rendered
    assert "target=https://<redacted>@example.test/path" in rendered
    assert parsed["status_counts"]["broken"] == 1
    assert parsed["status_counts"]["configured"] == 2
    assert parsed["summary"]["llm_routes"] == 1
    assert parsed["summary"]["api_budgets"] == 1
    assert parsed["summary"]["telegram_slots"] == 1


def test_pyproject_declares_cinnamon_applet_helper_script() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["scripts"]["teebotus-cinnamon-applet"] == "TeeBotus.cinnamon_applet:main"


def test_cinnamon_applet_install_script_targets_user_applet_dir() -> None:
    source = (PROJECT_ROOT / "scripts" / "install_cinnamon_applet.py").read_text(encoding="utf-8")

    assert 'APPLET_UUID = "teebotus@H234598"' in source
    assert 'SETTINGS_ICON_NAME = "teebotus.svg"' in source
    assert '".local" / "share" / "cinnamon" / "applets"' in source
    assert '".local" / "share" / "icons" / "hicolor" / "scalable" / "apps"' in source
    assert "shutil.copytree(source, target)" in source
    assert "shutil.rmtree(target)" in source
    assert "shutil.copy2(icon_source, icon_target)" in source
    assert "gtk-update-icon-cache" in source
