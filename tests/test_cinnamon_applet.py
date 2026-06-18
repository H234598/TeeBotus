from __future__ import annotations

import json
import tomllib
from pathlib import Path

import TeeBotus.cinnamon_applet as cinnamon_applet
from TeeBotus.cinnamon_applet import build_status_payload, parse_runtime_status


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
    assert "summary.problem_status_count" in source
    assert "health.total_problem_count" in source
    assert "_problemStatusCount: function(counts)" in source
    assert "payload.health" in source
    assert '"Health "' in source
    assert 'degraded: "eingeschraenkt"' in source
    assert 'schema_mismatch: "Schema passt nicht"' in source


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


def test_cinnamon_applet_qdrant_actions_keep_url_local_only() -> None:
    source = (APPLET_DIR / "applet.js").read_text(encoding="utf-8")
    schema = json.loads((APPLET_DIR / "settings-schema.json").read_text(encoding="utf-8"))

    assert schema["qdrant-url"]["default"] == "http://127.0.0.1:6333"
    assert "Must stay local" in schema["qdrant-url"]["tooltip"]
    assert "return this._safeLocalHttpUrl(this.qdrantUrl, DEFAULT_QDRANT_URL);" in source
    assert "_safeLocalHttpUrl: function(value, fallback)" in source
    assert '["127.0.0.1", "localhost", "::1"].indexOf(normalizedHost)' in source
    assert "match[5] || match[6]" in source
    assert "port > 0 && port <= 65535" in source
    assert 'this._qdrantUrl() + "/collections"' in source
    assert 'this._qdrantUrl() + "/collections/teebotus_user_memory/points/count"' in source


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


def test_cinnamon_applet_runtime_summary_counts_problem_statuses() -> None:
    parsed = parse_runtime_status(
        """
        [Diagnose]
        identity=Demo status=warning
        llm_route=demo status=degraded
        qdrant=local status=invalid
        qdrant_collection=demo status=schema_mismatch
        memory_index=demo status=config_conflict
        api_budget=demo status=missing_key
        service=demo status=unavailable
        account_memory=demo/abc status=broken
        runtime_slot=demo status=not_configured
        structured_decision=demo status=not_applicable
        hf_pool=default status=disabled
        qdrant_collection=ok status=ready
        """
    )

    assert parsed["summary"]["problem_status_count"] == 8
    assert parsed["summary"]["problem_statuses"] == (
        "broken:1,config_conflict:1,degraded:1,invalid:1,missing_key:1,"
        "schema_mismatch:1,unavailable:1,warning:1"
    )
    assert parsed["status_counts"]["not_configured"] == 1
    assert parsed["status_counts"]["not_applicable"] == 1
    assert parsed["status_counts"]["disabled"] == 1
    assert parsed["status_counts"]["ready"] == 1


def test_cinnamon_applet_payload_ok_reflects_runtime_health(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        cinnamon_applet,
        "_runtime_status",
        lambda *_args, **_kwargs: {"returncode": 0, "stdout": "[Diagnose]\nllm_route=demo status=warning\n", "stderr": ""},
    )
    monkeypatch.setattr(cinnamon_applet, "_systemd_unit_status", lambda _unit: {"active_state": "active", "sub_state": "running"})
    monkeypatch.setattr(cinnamon_applet, "_qdrant_status", lambda _url: {"url": "http://127.0.0.1:6333", "collections": {}, "error": ""})
    monkeypatch.setattr(cinnamon_applet, "_repo_status", lambda _root: {"path": str(tmp_path), "short_commit": "abc1234"})

    payload = build_status_payload(
        repo_root=tmp_path,
        channels="telegram,signal",
        unit_name="teebotus.service",
        python_executable="/usr/bin/python3",
        timeout_seconds=1,
    )

    assert payload["command_ok"] is True
    assert payload["ok"] is False
    assert payload["health"] == {
        "status": "warning",
        "command_ok": True,
        "problem_status_count": 1,
        "problem_statuses": "warning:1",
        "qdrant_problem_count": 0,
        "total_problem_count": 1,
        "severe_status_count": 0,
    }


def test_cinnamon_applet_payload_health_reports_command_and_qdrant_failures(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cinnamon_applet, "_runtime_status", lambda *_args, **_kwargs: {"returncode": 124, "stdout": "", "stderr": "timeout"})
    monkeypatch.setattr(cinnamon_applet, "_systemd_unit_status", lambda _unit: {"active_state": "missing", "sub_state": "dead"})
    monkeypatch.setattr(
        cinnamon_applet,
        "_qdrant_status",
        lambda _url: {
            "url": "http://127.0.0.1:6333",
            "collections": {"teebotus_user_memory": {"status": "unreachable", "count": 0, "error": "connection refused"}},
            "error": "teebotus_user_memory: connection refused",
        },
    )
    monkeypatch.setattr(cinnamon_applet, "_repo_status", lambda _root: {"path": str(tmp_path), "short_commit": "abc1234"})

    payload = build_status_payload(
        repo_root=tmp_path,
        channels="telegram,signal",
        unit_name="teebotus.service",
        python_executable="/usr/bin/python3",
        timeout_seconds=1,
    )

    assert payload["command_ok"] is False
    assert payload["ok"] is False
    assert payload["health"]["status"] == "broken"
    assert payload["health"]["qdrant_problem_count"] == 2
    assert payload["health"]["total_problem_count"] == 2


def test_cinnamon_applet_payload_total_problems_includes_qdrant_health(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cinnamon_applet, "_runtime_status", lambda *_args, **_kwargs: {"returncode": 0, "stdout": "[Diagnose]\nservice=demo status=ready\n", "stderr": ""})
    monkeypatch.setattr(cinnamon_applet, "_systemd_unit_status", lambda _unit: {"active_state": "active", "sub_state": "running"})
    monkeypatch.setattr(
        cinnamon_applet,
        "_qdrant_status",
        lambda _url: {
            "url": "http://127.0.0.1:6333",
            "collections": {"teebotus_user_memory": {"status": "unreachable", "count": 0, "error": "connection refused"}},
            "error": "",
        },
    )
    monkeypatch.setattr(cinnamon_applet, "_repo_status", lambda _root: {"path": str(tmp_path), "short_commit": "abc1234"})

    payload = build_status_payload(
        repo_root=tmp_path,
        channels="telegram,signal",
        unit_name="teebotus.service",
        python_executable="/usr/bin/python3",
        timeout_seconds=1,
    )

    assert payload["command_ok"] is True
    assert payload["ok"] is False
    assert payload["health"]["status"] == "warning"
    assert payload["health"]["problem_status_count"] == 0
    assert payload["health"]["qdrant_problem_count"] == 1
    assert payload["health"]["total_problem_count"] == 1


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


def test_cinnamon_applet_runtime_parser_redacts_url_and_bearer_edge_cases() -> None:
    bearer_token = "abcdefghijklmnopqrstuvwxyz123456"

    parsed = parse_runtime_status(
        f"""
        [LLM-Routen und Backends]
        llm_route=normal_chat status=broken target=redis://:redis-password@example.test/0 authorization=Bearer {bearer_token}

        [API Keys, Limits und Kosten]
        api_budget=normal_chat status=broken target=https://example.test/path?api_key=plain-secret&ok=1
        """
    )
    rendered = json.dumps(parsed, sort_keys=True)

    assert "redis-password" not in rendered
    assert bearer_token not in rendered
    assert "plain-secret" not in rendered
    assert "target=redis://<redacted>@example.test/0" in rendered
    assert "authorization=Bearer <redacted-secret>" in rendered
    assert "target=https://example.test/path?api_key=<redacted>&ok=1" in rendered
    assert parsed["status_counts"]["broken"] == 2
    assert parsed["summary"]["llm_routes"] == 1
    assert parsed["summary"]["api_budgets"] == 1


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
