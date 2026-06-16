from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

from TeeBotus.core.status import account_memory_index_health_lines
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, telegram_identity_key


def test_package_entrypoint_exists_and_delegates_to_bot_main() -> None:
    module = importlib.import_module("TeeBotus.__main__")
    bot = importlib.import_module("TeeBotus.bot")
    assert hasattr(module, "main")
    assert module.main is bot.main


def test_bot_main_is_callable() -> None:
    bot = importlib.import_module("TeeBotus.bot")
    assert callable(bot.main)


def test_version_flag_prints_package_version_without_runtime_start(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_runtime_config_from_main_args", lambda _args: (_ for _ in ()).throw(AssertionError("runtime loaded")))
    monkeypatch.setattr(bot, "_load_telegram_main", lambda: (_ for _ in ()).throw(AssertionError("telegram loaded")))

    assert bot.main(["--version"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "TeeBotus 1.5.0\n"
    assert captured.err == ""


def test_help_flag_prints_usage_without_runtime_start(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_runtime_config_from_main_args", lambda _args: (_ for _ in ()).throw(AssertionError("runtime loaded")))
    monkeypatch.setattr(bot, "_load_telegram_main", lambda: (_ for _ in ()).throw(AssertionError("telegram loaded")))

    assert bot.main(["--help"]) == 0

    captured = capsys.readouterr()
    assert "Usage: python3 -m TeeBotus" in captured.out
    assert "--runtime-status" in captured.out
    assert captured.err == ""


def test_runtime_status_does_not_require_telegram_bot_start() -> None:
    bot = importlib.import_module("TeeBotus.bot")
    result = bot.main(["--runtime-status", "--channels", "telegram"])
    assert result == 0


def test_main_delegates_default_start_to_telegram_entrypoint(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls: list[list[str]] = []

    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setattr(bot, "_load_telegram_main", lambda: lambda args: calls.append(list(args)) or 0)

    assert bot.main([]) == 0

    assert calls == [[]]


def test_main_delegates_all_start_to_telegram_entrypoint(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls: list[list[str]] = []

    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setattr(bot, "_load_telegram_main", lambda: lambda args: calls.append(list(args)) or 0)

    assert bot.main(["--all"]) == 0

    assert calls == [["--all"]]


def test_main_all_start_initializes_signal_and_matrix_before_telegram(monkeypatch, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("", encoding="utf-8")
    calls: list[tuple[str, tuple[str, ...]]] = []

    def labels_for(config, channel: str) -> tuple[str, ...]:  # noqa: ANN001 - runtime config is imported lazily in entrypoint tests.
        return tuple(account.label for instance in config.instances for account in instance.accounts if account.channel == channel)

    def start_matrix(config) -> int:  # noqa: ANN001 - keep the test independent from runtime dataclass imports.
        calls.append(("matrix", labels_for(config, "matrix")))
        return 0

    def start_signal(config) -> int:  # noqa: ANN001 - keep the test independent from runtime dataclass imports.
        calls.append(("signal", labels_for(config, "signal")))
        return 0

    def telegram_main(args) -> int:  # noqa: ANN001 - mirrors the legacy Telegram main callable.
        calls.append(("telegram", tuple(args or ())))
        return 0

    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_DEMO", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", "+491")
    monkeypatch.setenv("MATRIX_BOT_HOMESERVER_DEMO", "https://matrix.example")
    monkeypatch.setenv("MATRIX_BOT_USER_ID_DEMO", "@demo:example")
    monkeypatch.setenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", "matrix-token")
    monkeypatch.setattr(bot, "_start_matrix_runtime_background", start_matrix)
    monkeypatch.setattr(bot, "_start_signal_runtime_background", start_signal)
    monkeypatch.setattr(bot, "_load_telegram_main", lambda: telegram_main)

    assert bot.main(["--all", "--channels", "telegram,signal,matrix"]) == 0

    assert calls == [
        ("matrix", ("matrix:1",)),
        ("signal", ("signal:1",)),
        ("telegram", ("--all",)),
    ]


def test_runtime_status_prints_account_memory_index_health(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setattr(
        "TeeBotus.core.status.account_memory_index_health_lines",
        lambda *, instance_name, project_root: [f"account_memory={instance_name}/abc status=broken error=recent_ids missing entries: mem_missing"],
    )

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "account_memory=Demo/abc status=broken error=recent_ids missing entries: mem_missing" in captured.out


def test_account_memory_status_suggests_detected_plaintext_legacy_backup(tmp_path) -> None:
    project_root = tmp_path / "TeeBotus"
    accounts_root = project_root / "instances" / "Demo" / "data" / "accounts"
    bad_store = AccountStore(accounts_root, "Demo", secret_provider=StaticSecretProvider(b"b" * 32))
    account_id = bad_store.resolve_or_create_account(telegram_identity_key("395935293"))
    bad_store.write_memory_entries(account_id, [{"id": "bad", "user_text": "unreadable"}])
    backup_user_dir = tmp_path / "TeeBotus.bak2" / "instances.bak" / "Demo" / "data" / "users" / "395935293"
    backup_user_dir.mkdir(parents=True)
    (backup_user_dir / "User_Memory_Entries.jsonl").write_text(
        '{"id":"legacy_1","user_text":"A"}\n{"id":"legacy_2","user_text":"B"}\n',
        encoding="utf-8",
    )
    older_backup_user_dir = tmp_path / "TeeBotus.bak" / "instances.bak" / "Demo" / "data" / "users" / "395935293"
    older_backup_user_dir.mkdir(parents=True)
    (older_backup_user_dir / "User_Memory_Entries.jsonl").write_text(
        '{"id":"legacy_1","user_text":"A"}\n{"id":"legacy_2","user_text":"B"}\n',
        encoding="utf-8",
    )

    lines = account_memory_index_health_lines(instance_name="Demo", project_root=project_root)

    assert any("account_memory=Demo/" in line and "status=broken" in line for line in lines)
    assert (
        "account_memory_recovery_legacy=Demo status=available "
        "sources=1 entries=2 "
        f"path={tmp_path / 'TeeBotus.bak2' / 'instances.bak'} "
        f'command="python3 scripts/import_legacy_user_memory.py --legacy-instances-dir {tmp_path / "TeeBotus.bak2"} '
        f'--target-instances-dir {project_root / "instances"} --instance Demo --replace-unreadable-account-metadata '
        f'--json-output {Path.home() / "Downloads" / "teebotus-legacy-import-preflight-Demo.json"} '
        f'--markdown-output {Path.home() / "Downloads" / "teebotus-legacy-import-preflight-Demo.md"}"'
    ) in lines


def test_account_memory_status_quotes_legacy_preflight_command_for_spaced_instance(tmp_path) -> None:
    project_root = tmp_path / "TeeBotus"
    accounts_root = project_root / "instances" / "Demo Bot" / "data" / "accounts"
    bad_store = AccountStore(accounts_root, "Demo Bot", secret_provider=StaticSecretProvider(b"b" * 32))
    account_id = bad_store.resolve_or_create_account(telegram_identity_key("395935293"))
    bad_store.write_memory_entries(account_id, [{"id": "bad", "user_text": "unreadable"}])
    backup_user_dir = tmp_path / "TeeBotus.bak2" / "instances.bak" / "Demo Bot" / "data" / "users" / "395935293"
    backup_user_dir.mkdir(parents=True)
    (backup_user_dir / "User_Memory_Entries.jsonl").write_text('{"id":"legacy_1","user_text":"A"}\n', encoding="utf-8")

    lines = account_memory_index_health_lines(instance_name="Demo Bot", project_root=project_root)

    legacy_line = next(line for line in lines if line.startswith("account_memory_recovery_legacy=Demo Bot "))
    assert "--instance 'Demo Bot'" in legacy_line
    assert "teebotus-legacy-import-preflight-Demo_Bot.json" in legacy_line
    assert "teebotus-legacy-import-preflight-Demo_Bot.md" in legacy_line


def test_account_memory_status_ignores_encrypted_legacy_backup(tmp_path) -> None:
    project_root = tmp_path / "TeeBotus"
    accounts_root = project_root / "instances" / "Demo" / "data" / "accounts"
    bad_store = AccountStore(accounts_root, "Demo", secret_provider=StaticSecretProvider(b"b" * 32))
    account_id = bad_store.resolve_or_create_account(telegram_identity_key("395935293"))
    bad_store.write_memory_entries(account_id, [{"id": "bad", "user_text": "unreadable"}])
    backup_user_dir = tmp_path / "TeeBotus.bak2" / "instances.bak" / "Demo" / "data" / "users" / "395935293"
    backup_user_dir.mkdir(parents=True)
    (backup_user_dir / "User_Memory_Entries.jsonl").write_text('{"version":1,"nonce":"n","ciphertext":"c"}\n', encoding="utf-8")

    lines = account_memory_index_health_lines(instance_name="Demo", project_root=project_root)

    assert any(line.startswith("account_memory_recovery=Demo status=needed") for line in lines)
    assert not any(line.startswith("account_memory_recovery_legacy=Demo ") for line in lines)


def test_runtime_status_reports_local_transcription_health(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text(
        "## OpenAI\n- transcription_backend: local\n- local_transcription_model: tiny\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setattr("TeeBotus.core.local_transcription._has_python_module", lambda module: module == "faster_whisper")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "local_transcription=Demo backend=local model=tiny status=ready engine=faster-whisper" in captured.out


def test_runtime_status_reports_llm_provider_without_secrets(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_PROVIDER_DEMO", "litellm")
    monkeypatch.setenv("TEEBOTUS_LLM_MODEL_DEMO", "ollama_chat/llama3.1:8b")
    monkeypatch.setenv("TEEBOTUS_LLM_BASE_URL_DEMO", "http://user:secret@127.0.0.1:11434/api?token=nope")
    monkeypatch.setenv("TEEBOTUS_LLM_API_KEY_DEMO", "llm-secret")
    monkeypatch.setenv("TEEBOTUS_LLM_FALLBACK_MODELS_DEMO", "groq/llama-3.3-70b-versatile,openai/gpt-4.1-mini")
    monkeypatch.setenv("TEEBOTUS_LLM_PROFILE_DEMO", "local_ollama")
    monkeypatch.setenv("TEEBOTUS_LLM_TIMEOUT_SECONDS_DEMO", "180")
    monkeypatch.setenv("TEEBOTUS_LLM_MAX_OUTPUT_TOKENS_DEMO", "700")
    monkeypatch.setenv("TEEBOTUS_LLM_TEMPERATURE_DEMO", "0.7")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert (
        "llm=Demo/telegram:1 provider=litellm model=ollama_chat/llama3.1:8b "
        "status=configured profile=local_ollama base_url=http://127.0.0.1:11434 "
        "api_key=configured timeout_seconds=180 max_output_tokens=700 temperature=0.7"
    ) in captured.out
    assert "fallback_models=2" not in captured.out
    assert "llm-secret" not in captured.out
    assert "user:secret" not in captured.out
    assert "token=nope" not in captured.out


def test_runtime_status_text_redacts_generic_secret_assignments() -> None:
    bot = importlib.import_module("TeeBotus.bot")

    text = bot._sanitize_status_text(
        "provider error api_key=plain-secret password=hunter2 access_token=abc123 bearer_token=xyz"
    )

    assert text == "provider error api_key=<redacted> password=<redacted> access_token=<redacted> bearer_token=<redacted>"
    assert "plain-secret" not in text
    assert "hunter2" not in text
    assert "abc123" not in text
    assert "xyz" not in text


def test_runtime_status_counts_only_effective_local_fallbacks_without_remote_allow(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_PROVIDER_DEMO", "ollama")
    monkeypatch.setenv("TEEBOTUS_LLM_MODEL_DEMO", "llama3.1:8b")
    monkeypatch.setenv(
        "TEEBOTUS_LLM_FALLBACK_MODELS_DEMO",
        "groq/llama-3.3-70b-versatile,ollama_chat/qwen2.5:7b,openai/gpt-4.1-mini",
    )

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert (
        "llm=Demo/telegram:1 provider=ollama model=llama3.1:8b "
        "status=configured api_key=none fallback_models=1"
    ) in captured.out
    assert "fallback_models=3" not in captured.out


def test_runtime_status_reports_runtime_llm_disabled(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("## LLM\n- enabled: ja\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_ENABLED_DEMO", "false")
    monkeypatch.setenv("OPENAI_API_KEY_DEMO", "openai-secret")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "llm=Demo/telegram:1 provider=none model=<disabled> status=disabled" in captured.out
    assert "openai-secret" not in captured.out


def test_runtime_status_resolves_profile_without_direct_provider(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_PROFILE_DEMO", "hf_mistral")
    monkeypatch.setenv("HUGGINGFACE_API_KEY", "hf-secret")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert (
        "llm=Demo/telegram:1 provider=litellm model=huggingface/mistralai/Mistral-7B-Instruct-v0.3 "
        "status=configured profile=hf_mistral api_key=configured"
    ) in captured.out
    assert "hf-secret" not in captured.out


def test_runtime_status_resolves_purpose_router_and_remote_fallback_flag(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_PURPOSE_DEMO", "structured_decision")
    monkeypatch.setenv("TEEBOTUS_LLM_ALLOW_REMOTE_FALLBACK_DEMO", "yes")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert (
        "llm=Demo/telegram:1 provider=litellm model=ollama_chat/llama3.1:8b "
        "status=configured purpose=structured_decision base_url=http://127.0.0.1:11434 "
        "api_key=none fallback_models=1 remote_fallback=enabled"
    ) in captured.out


def test_runtime_status_resolves_purpose_route_api_key_env(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_PURPOSE_DEMO", "hard_reasoning")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-profile-secret")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "llm=Demo/telegram:1 provider=openai model=gpt-5.5 status=configured purpose=hard_reasoning" in captured.out
    assert "openai-profile-secret" not in captured.out


def test_runtime_status_reports_reachable_ollama(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_PROVIDER_DEMO", "litellm")
    monkeypatch.setenv("TEEBOTUS_LLM_MODEL_DEMO", "ollama_chat/llama3.1:8b")
    monkeypatch.setenv("TEEBOTUS_LLM_BASE_URL_DEMO", "http://127.0.0.1:11434/api")

    calls: list[str] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read() -> bytes:
            return b'{"models":[{"name":"llama3.1:8b"},{"model":"qwen2.5:7b"}]}'

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        assert timeout == 1.0
        return Response()

    monkeypatch.setattr("TeeBotus.runtime.ollama_health.urllib.request.urlopen", fake_urlopen)

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert calls == ["http://127.0.0.1:11434/api/tags"]
    assert "ollama=127.0.0.1:11434 status=reachable models=llama3.1:8b,qwen2.5:7b" in captured.out


def test_runtime_status_refuses_unsafe_ollama_base_url_without_probe(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_PROVIDER_DEMO", "litellm")
    monkeypatch.setenv("TEEBOTUS_LLM_MODEL_DEMO", "ollama_chat/llama3.1:8b")
    monkeypatch.setenv("TEEBOTUS_LLM_BASE_URL_DEMO", "http://user:secret@ollama.example:11434/api?token=plain-token#frag")

    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("unsafe Ollama base_url must not be probed")

    monkeypatch.setattr("TeeBotus.runtime.ollama_health.urllib.request.urlopen", fail_urlopen)

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "ollama=ollama.example:11434 status=unreachable error=unsafe Ollama base_url: credentials are not allowed" in captured.out
    assert "user:secret" not in captured.out
    assert "plain-token" not in captured.out


def test_runtime_status_refuses_remote_ollama_host_without_probe(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_PROVIDER_DEMO", "ollama")
    monkeypatch.setenv("TEEBOTUS_LLM_MODEL_DEMO", "llama3.1:8b")
    monkeypatch.setenv("TEEBOTUS_LLM_BASE_URL_DEMO", "http://ollama.example:11434")

    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("remote Ollama base_url must not be probed")

    monkeypatch.setattr("TeeBotus.runtime.ollama_health.urllib.request.urlopen", fail_urlopen)

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "ollama=ollama.example:11434 status=unreachable error=unsafe Ollama base_url: host must be loopback" in captured.out


def test_runtime_status_checks_ollama_for_local_profile(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_PROFILE_DEMO", "local_ollama")

    calls: list[str] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read() -> bytes:
            return b'{"models":[{"name":"llama3.1:8b"}]}'

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        assert timeout == 1.0
        return Response()

    monkeypatch.setattr("TeeBotus.runtime.ollama_health.urllib.request.urlopen", fake_urlopen)

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert calls == ["http://127.0.0.1:11434/api/tags"]
    assert "llm=Demo/telegram:1 provider=litellm model=ollama_chat/llama3.1:8b status=configured profile=local_ollama" in captured.out
    assert "ollama=127.0.0.1:11434 status=reachable models=llama3.1:8b" in captured.out


def test_runtime_status_checks_ollama_for_local_purpose_route(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_PURPOSE_DEMO", "structured_decision")

    calls: list[str] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read() -> bytes:
            return b'{"models":[{"model":"llama3.1:8b"}]}'

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        assert timeout == 1.0
        return Response()

    monkeypatch.setattr("TeeBotus.runtime.ollama_health.urllib.request.urlopen", fake_urlopen)

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert calls == ["http://127.0.0.1:11434/api/tags"]
    assert "llm=Demo/telegram:1 provider=litellm model=ollama_chat/llama3.1:8b status=configured purpose=structured_decision" in captured.out
    assert "ollama=127.0.0.1:11434 status=reachable models=llama3.1:8b" in captured.out


def test_runtime_status_reports_unreachable_default_ollama(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_PROVIDER_DEMO", "ollama")
    monkeypatch.setenv("TEEBOTUS_LLM_MODEL_DEMO", "llama3.1:8b")

    def fake_urlopen(_request, timeout):
        assert timeout == 1.0
        raise OSError("connection refused")

    monkeypatch.setattr("TeeBotus.runtime.ollama_health.urllib.request.urlopen", fake_urlopen)

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "ollama=127.0.0.1:11434 status=unreachable error=connection refused" in captured.out


def test_runtime_status_reports_missing_local_transcription_backend(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text(
        "## OpenAI\n- transcription_backend: local\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setattr("TeeBotus.core.local_transcription._has_python_module", lambda _module: False)
    monkeypatch.setattr("TeeBotus.core.local_transcription.shutil.which", lambda _binary: None)

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "local_transcription=Demo backend=local model=tiny status=unavailable error=weder faster-whisper noch whisper ist lokal installiert" in captured.out


def test_runtime_status_reports_local_bibliothekar_health(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    library_dir = demo_dir / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("## Bibliothekar\n- backend: local\n", encoding="utf-8")
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "bibliothekar=Demo backend=local store=json collection=teebotus_books status=ready documents=1 chunks=1" in captured.out


def test_runtime_status_reports_haystack_bibliothekar_dependency_gap(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text(
        "## Bibliothekar\n- backend: haystack\n- collection: therapy_books\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setattr("TeeBotus.runtime.bibliothekar_service._module_available", lambda _name: False)

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert (
        "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books target=http://127.0.0.1:6333 status=unavailable "
        "error=missing optional dependency: haystack, haystack_integrations.document_stores.qdrant"
    ) in captured.out


def test_runtime_status_reports_reachable_haystack_bibliothekar(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    library_dir = demo_dir / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text(
        "## Bibliothekar\n- backend: haystack\n- collection: therapy_books\n",
        encoding="utf-8",
    )
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung.", encoding="utf-8")

    class FakeDocumentStore:
        def filter_documents(self, **_kwargs):
            return []

    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setattr("TeeBotus.runtime.bibliothekar_service._module_available", lambda _name: True)
    monkeypatch.setattr(
        "TeeBotus.runtime.bibliothekar_service.HaystackBibliothekarBackend._document_store",
        lambda _self: FakeDocumentStore(),
    )

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books target=http://127.0.0.1:6333 status=reachable documents=1 chunks=1" in captured.out


def test_runtime_status_reports_mcp_tool_policy(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text(
        """
        ## MCP Tools
        - bibliothekar.search.enabled: true
        - bibliothekar.search.read_only: true
        - memory.search.enabled: false
        - codex.exec.enabled: true
        - shell.exec.enabled: true
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "mcp_tools=Demo Read-only allowlist: bibliothekar.search Deaktiviert: codex.exec (nicht read-only), export.account, memory.search, youtube.transcribe Ignoriert: shell.exec" in captured.out


def test_runtime_status_cannot_relax_private_memory_tool_policy(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text(
        """
        ## MCP Tools
        - memory.search.enabled: true
        - memory.search.read_only: true
        - memory.search.private_chat_only: false
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "memory.search (private)" in captured.out


def test_runtime_status_loads_env_before_resolving_config(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls: list[tuple[str, Path]] = []

    class TelegramModule:
        PROJECT_ROOT = Path("/tmp/teebotus-test-root")
        ALL_BOTS_DEFAULT_FILENAME = "ALL_BOTS_DEFAULT.md"

        @staticmethod
        def _load_dotenv(path: Path) -> None:
            calls.append(("dotenv", path))
            monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
            monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "token")

        @staticmethod
        def _load_runtime_config_defaults(path: Path) -> None:
            calls.append(("defaults", path))
            monkeypatch.setenv("OPENAI_API_KEY_DEMO", "sk-demo")

    monkeypatch.setattr(bot, "_load_telegram_module", lambda: TelegramModule)
    monkeypatch.delenv("TEEBOTUS_INSTANCE", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_DEMO", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY_DEMO", raising=False)

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0
    assert calls == [
        ("dotenv", Path("/tmp/teebotus-test-root/.env")),
        ("defaults", Path("/tmp/teebotus-test-root/ALL_BOTS_DEFAULT.md")),
    ]


def test_runtime_status_reports_signal_service_health(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_DEMO", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", "+491234")

    def fake_check_signal_services(config):
        account = [account for instance in config.instances for account in instance.accounts if account.channel == "signal"][0]
        return (SimpleNamespace(account=account, ok=False, target="127.0.0.1:8080", error="connection refused"),)

    def fake_check_signal_accounts(config):
        account = [account for instance in config.instances for account in instance.accounts if account.channel == "signal"][0]
        return (
            SimpleNamespace(
                account=account,
                ok=False,
                registered=False,
                target="127.0.0.1:8080",
                error="account missing in signal-cli-rest-api /v1/accounts",
            ),
        )

    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_services", fake_check_signal_services)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_accounts", fake_check_signal_accounts)

    assert bot.main(["--runtime-status", "--channels", "signal"]) == 0
    captured = capsys.readouterr()
    assert "signal_service=Demo/signal:1 target=127.0.0.1:8080 status=unreachable error=connection refused" in captured.out
    assert (
        "signal_account=Demo/signal:1 phone=+491234 target=127.0.0.1:8080 status=missing "
        "error=account missing in signal-cli-rest-api /v1/accounts"
    ) in captured.out


def test_runtime_status_reports_matrix_homeserver_health(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("MATRIX_BOT_HOMESERVER_DEMO", "https://matrix.example")
    monkeypatch.setenv("MATRIX_BOT_USER_ID_DEMO", "@bot:example")
    monkeypatch.setenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", "matrix-token")

    def fake_check_matrix_homeservers(config):
        account = [account for instance in config.instances for account in instance.accounts if account.channel == "matrix"][0]
        return (SimpleNamespace(account=account, ok=False, target="matrix.example:443", error="connection refused"),)

    monkeypatch.setattr("TeeBotus.runtime.matrix_runner.check_matrix_homeservers", fake_check_matrix_homeservers)

    assert bot.main(["--runtime-status", "--channels", "matrix"]) == 0
    captured = capsys.readouterr()
    assert "matrix_homeserver=Demo/matrix:1 target=matrix.example:443 status=unreachable error=connection refused" in captured.out


def test_runtime_status_redacts_secret_like_health_errors(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_DEMO", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", "+491234")
    monkeypatch.setenv("MATRIX_BOT_HOMESERVER_DEMO", "https://matrix.example")
    monkeypatch.setenv("MATRIX_BOT_USER_ID_DEMO", "@bot:example")
    monkeypatch.setenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", "matrix-token")
    openai_key = "sk-" + "runtimeStatusLeak123456"
    matrix_token = "syt_" + "runtimeStatusLeak123456"

    def fake_check_signal_services(config):
        account = [account for instance in config.instances for account in instance.accounts if account.channel == "signal"][0]
        return (SimpleNamespace(account=account, ok=False, target=f"https://user:{openai_key}@signal.example:8080", error=f"bearer {openai_key} rejected"),)

    def fake_check_signal_accounts(config):
        account = [account for instance in config.instances for account in instance.accounts if account.channel == "signal"][0]
        return (
            SimpleNamespace(
                account=account,
                ok=False,
                registered=False,
                target="127.0.0.1:8080",
                error=f"account missing with token {matrix_token}",
            ),
        )

    def fake_check_matrix_homeservers(config):
        account = [account for instance in config.instances for account in instance.accounts if account.channel == "matrix"][0]
        return (SimpleNamespace(account=account, ok=False, target="matrix.example:443", error=f"matrix token {matrix_token} rejected"),)

    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_services", fake_check_signal_services)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_accounts", fake_check_signal_accounts)
    monkeypatch.setattr("TeeBotus.runtime.matrix_runner.check_matrix_homeservers", fake_check_matrix_homeservers)

    assert bot.main(["--runtime-status", "--channels", "signal,matrix"]) == 0
    captured = capsys.readouterr()

    assert openai_key not in captured.out
    assert matrix_token not in captured.out
    assert "target=https://signal.example:8080" in captured.out
    assert "sk-<redacted>" in captured.out
    assert "syt_<redacted>" in captured.out


def test_runtime_status_redacts_schemeless_target_credentials(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_DEMO", "127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", "+491234")

    def fake_check_signal_services(config):
        account = [account for instance in config.instances for account in instance.accounts if account.channel == "signal"][0]
        return (
            SimpleNamespace(
                account=account,
                ok=False,
                target="user:plain-password@signal.example:8080/path?token=plain-token",
                error="connection refused",
            ),
        )

    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_services", fake_check_signal_services)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_accounts", lambda _config: ())

    assert bot.main(["--runtime-status", "--channels", "signal"]) == 0
    captured = capsys.readouterr()

    assert "plain-password" not in captured.out
    assert "plain-token" not in captured.out
    assert "target=signal.example:8080" in captured.out


def test_runtime_status_redacts_helper_status_lines(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    openai_key = "sk-" + "helperStatusLeak123456"
    hf_key = "hf_" + "helperStatusLeak123456"

    monkeypatch.setattr(
        "TeeBotus.core.status.mcp_tool_runtime_status_line",
        lambda _instance_name, _mcp_tools: f"mcp_tools=Demo status=broken error=tool leaked {openai_key}",
    )
    monkeypatch.setattr(
        "TeeBotus.core.status.account_memory_index_health_lines",
        lambda *, instance_name, project_root: [f"account_memory={instance_name}/abc status=broken error=index leaked {hf_key}"],
    )

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0
    captured = capsys.readouterr()

    assert openai_key not in captured.out
    assert hf_key not in captured.out
    assert "mcp_tools=Demo status=broken error=tool leaked sk-<redacted>" in captured.out
    assert "account_memory=Demo/abc status=broken error=index leaked hf_<redacted>" in captured.out


def test_runtime_status_marks_signal_account_unavailable_when_backend_is_down(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_DEMO", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", "+491234")

    def fake_check_signal_services(config):
        account = [account for instance in config.instances for account in instance.accounts if account.channel == "signal"][0]
        return (SimpleNamespace(account=account, ok=False, target="127.0.0.1:8080", error="connection refused"),)

    def fake_check_signal_accounts(config):
        account = [account for instance in config.instances for account in instance.accounts if account.channel == "signal"][0]
        return (
            SimpleNamespace(
                account=account,
                ok=False,
                registered=False,
                target="127.0.0.1:8080",
                error="service does not expose signal-cli-rest-api account list",
            ),
        )

    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_services", fake_check_signal_services)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_accounts", fake_check_signal_accounts)

    assert bot.main(["--runtime-status", "--channels", "signal"]) == 0
    captured = capsys.readouterr()
    assert (
        "signal_account=Demo/signal:1 phone=+491234 target=127.0.0.1:8080 status=unavailable "
        "error=service does not expose signal-cli-rest-api account list"
    ) in captured.out


def test_bot_main_delegates_unknown_normal_args_to_telegram_bot(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    assert bot.main(["--definitely-not-runtime-status"]) == 2


def test_channels_telegram_is_stripped_before_telegram_delegation(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    assert bot.main(["--channels", "telegram", "--definitely-not-runtime-status"]) == 2


def test_channels_signal_without_config_fails_clearly(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.delenv("SIGNAL_BOT_SERVICE_DEMO", raising=False)
    monkeypatch.delenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", raising=False)
    assert bot.main(["--channels", "signal"]) == 2


def test_channels_signal_delegates_to_signal_runtime(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_DEMO", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", "+491234")
    monkeypatch.setattr(bot, "_run_signal_runtime", lambda config: calls.append(config) or 0)

    assert bot.main(["--channels", "signal"]) == 0
    assert calls
    assert calls[0].instances[0].accounts[0].channel == "signal"


def test_channels_telegram_signal_starts_signal_before_telegram(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_DEMO", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", "+491234")
    monkeypatch.setattr(bot, "_start_signal_runtime_background", lambda config: calls.append(("signal", config)) or 0)
    monkeypatch.setattr(bot, "_load_telegram_main", lambda: lambda args: calls.append(("telegram", args)) or 0)

    assert bot.main(["--channels", "telegram,signal"]) == 0
    assert [call[0] for call in calls] == ["signal", "telegram"]


def test_channels_matrix_without_config_fails_clearly(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.delenv("MATRIX_BOT_HOMESERVER_DEMO", raising=False)
    monkeypatch.delenv("MATRIX_BOT_USER_ID_DEMO", raising=False)
    monkeypatch.delenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", raising=False)
    assert bot.main(["--channels", "matrix"]) == 2


def test_channels_matrix_delegates_to_matrix_runtime(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("MATRIX_BOT_HOMESERVER_DEMO", "https://matrix.example")
    monkeypatch.setenv("MATRIX_BOT_USER_ID_DEMO", "@bot:example")
    monkeypatch.setenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", "matrix-token")
    monkeypatch.setattr(bot, "_run_matrix_runtime", lambda config: calls.append(config) or 0)

    assert bot.main(["--channels", "matrix"]) == 0
    assert calls
    assert calls[0].instances[0].accounts[0].channel == "matrix"


def test_channels_telegram_matrix_starts_matrix_before_telegram(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("MATRIX_BOT_HOMESERVER_DEMO", "https://matrix.example")
    monkeypatch.setenv("MATRIX_BOT_USER_ID_DEMO", "@bot:example")
    monkeypatch.setenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", "matrix-token")
    monkeypatch.setattr(bot, "_start_matrix_runtime_background", lambda config: calls.append(("matrix", config)) or 0)
    monkeypatch.setattr(bot, "_load_telegram_main", lambda: lambda args: calls.append(("telegram", args)) or 0)

    assert bot.main(["--channels", "telegram,matrix"]) == 0
    assert [call[0] for call in calls] == ["matrix", "telegram"]


def test_channels_signal_matrix_rejects_before_starting_any_runner(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_DEMO", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", "+491234")
    monkeypatch.setenv("MATRIX_BOT_HOMESERVER_DEMO", "https://matrix.example")
    monkeypatch.setenv("MATRIX_BOT_USER_ID_DEMO", "@bot:example")
    monkeypatch.setenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", "matrix-token")
    monkeypatch.setattr(bot, "_start_signal_runtime_background", lambda config: calls.append(("signal", config)) or 0)
    monkeypatch.setattr(bot, "_start_matrix_runtime_background", lambda config: calls.append(("matrix", config)) or 0)
    monkeypatch.setattr(bot, "_run_signal_runtime", lambda config: calls.append(("run-signal", config)) or 0)
    monkeypatch.setattr(bot, "_run_matrix_runtime", lambda config: calls.append(("run-matrix", config)) or 0)

    assert bot.main(["--channels", "signal,matrix"]) == 2
    assert calls == []
