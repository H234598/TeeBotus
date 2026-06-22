from __future__ import annotations

import importlib
import os
from pathlib import Path
from types import SimpleNamespace

from TeeBotus import __version__
from TeeBotus.artifact_outputs import DEFAULT_OBSIDIAN_INCOMING_DIR
from TeeBotus.core.status import account_memory_index_health_lines
from TeeBotus.runtime.accounts import INSTANCE_STATE_ACCOUNT_ID, AccountStore, StaticSecretProvider, telegram_identity_key
from TeeBotus.runtime.qdrant import USER_MEMORY_QDRANT_EMBEDDING_DIMENSIONS, USER_MEMORY_QDRANT_EMBEDDING_MODEL


def _configure_demo_instance(monkeypatch, tmp_path: Path, *, instructions: str = "# Bot\n") -> Path:
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text(instructions, encoding="utf-8")
    monkeypatch.setenv("TEEBOTUS_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    return demo_dir


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
    assert captured.out == f"TeeBotus {__version__}\n"
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


def test_runtime_status_does_not_leak_loaded_default_environment(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.delenv("TEEBOTUS_INSTANCE", raising=False)

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    assert "TEEBOTUS_INSTANCE" not in os.environ


def test_runtime_status_reports_telegram_slot_without_token_secret(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-secret-token")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "telegram_slot=Demo/telegram:1 status=configured token=configured" in captured.out
    assert "telegram-secret-token" not in captured.out


def test_runtime_status_all_uses_runtime_instance_discovery(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    for name in ("DemoA", "DemoB"):
        instance_dir = instances_dir / name
        instance_dir.mkdir(parents=True)
        (instance_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "IgnoredByAll")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMOA", "telegram-token-a")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMOB", "telegram-token-b")

    assert bot.main(["--runtime-status", "--all", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "instances=DemoA,DemoB" in captured.out
    assert "telegram_slot=DemoA/telegram:1 status=configured token=configured" in captured.out
    assert "telegram_slot=DemoB/telegram:1 status=configured token=configured" in captured.out
    assert os.environ["TEEBOTUS_INSTANCE"] == "IgnoredByAll"


def test_runtime_status_groups_output_without_wrapping_status_lines(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_GEMINI_FREE_TIER_CACHE", str(tmp_path / "gemini-limits.json"))

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert captured.out.startswith("TeeBotus runtime configuration resolves.\n\n[Konfiguration]\n")
    for section in (
        "[Accounts und Entscheidungen]",
        "[LLM-Routen und Backends]",
        "[Projekt-History]",
        "[Agenten-Piloten]",
        "[Memory und semantische Suche]",
        "[Messenger]",
        "[Lokale Dienste]",
        "[Tools und Account-Memory]",
    ):
        assert f"\n{section}\n" in captured.out
    lines = captured.out.splitlines()
    assert any(line.startswith("llm=Demo/telegram:1 ") for line in lines)
    assert any(line.startswith("gemini_free_tier_limits status=never ") for line in lines)
    assert any(line.startswith("codex_history=Demo ") for line in lines)
    assert any(line.startswith("telegram_slot=Demo/telegram:1 ") for line in lines)


def test_runtime_status_reports_codex_history_counts(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    demo_dir = _configure_demo_instance(monkeypatch, tmp_path)
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setattr("TeeBotus.core.status.SecretToolInstanceSecretProvider", lambda **_kwargs: StaticSecretProvider(b"c" * 32))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    store = AccountStore(demo_dir / "data" / "accounts", "Demo", StaticSecretProvider(b"c" * 32))
    store.append_codex_history_item(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "status": "queued",
            "summary_prefix": "v1.8.0 #0001",
            "project": {"repo_name": "TeeBotus"},
            "summary": {"title": "Noch offen"},
        },
    )

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "[Projekt-History]" in captured.out
    assert "codex_history=Demo status=warning queued=1 failed=0 total=1 latest_repo=TeeBotus latest_prefix=v1.8.0_#0001" in captured.out


def test_runtime_status_reports_qdrant_default_collections(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    from TeeBotus.runtime.qdrant import QDRANT_BIBLIOTHEKAR_COLLECTION, QDRANT_USER_MEMORY_COLLECTION, QdrantCollectionResult, QdrantHealth

    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text(
        """
        ## Memory Search
        - semantic_enabled: true
        - semantic_backend: qdrant
        - qdrant_url: http://127.0.0.1:6334
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setattr(
        "TeeBotus.runtime.qdrant.check_qdrant_health",
        lambda url=None: QdrantHealth(target=url, status="reachable", ok=True),
    )
    monkeypatch.setattr(
        "TeeBotus.runtime.qdrant.check_default_collections",
        lambda **_kwargs: (
            QdrantCollectionResult(QDRANT_USER_MEMORY_COLLECTION, _kwargs["url"], "ready", True),
            QdrantCollectionResult(QDRANT_BIBLIOTHEKAR_COLLECTION, _kwargs["url"], "missing", False, "HTTP 404"),
        ),
    )

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "qdrant=127.0.0.1:6334 status=reachable" in captured.out
    assert "qdrant_collection=teebotus_user_memory target=127.0.0.1:6334 status=ready" in captured.out
    assert "qdrant_collection=teebotus_bibliothekar_chunks target=127.0.0.1:6334 status=missing" in captured.out
    assert "memory_index=Demo backend=keyword status=ready semantic=ready" in captured.out


def test_runtime_status_memory_index_line_reports_semantic_qdrant_state() -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instructions = SimpleNamespace(
        user_memory_enabled=True,
        memory_search_semantic_enabled=True,
        memory_search_semantic_backend="qdrant",
        memory_search_embedding_provider="hash",
        memory_search_embedding_model=USER_MEMORY_QDRANT_EMBEDDING_MODEL,
        memory_search_embedding_dimensions=USER_MEMORY_QDRANT_EMBEDDING_DIMENSIONS,
    )

    assert bot._runtime_status_memory_index_line("Demo", instructions, qdrant_ok=False) == (
        "memory_index=Demo backend=keyword status=ready semantic=unavailable "
        f"embedding_provider=hash embedding_model={USER_MEMORY_QDRANT_EMBEDDING_MODEL} "
        f"embedding_dimensions={USER_MEMORY_QDRANT_EMBEDDING_DIMENSIONS}"
    )
    assert bot._runtime_status_memory_index_line("Demo", instructions, qdrant_ok=True) == (
        "memory_index=Demo backend=keyword status=ready semantic=ready "
        f"embedding_provider=hash embedding_model={USER_MEMORY_QDRANT_EMBEDDING_MODEL} "
        f"embedding_dimensions={USER_MEMORY_QDRANT_EMBEDDING_DIMENSIONS}"
    )


def test_runtime_status_memory_index_line_reports_invalid_remote_account_memory_embeddings() -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instructions = SimpleNamespace(
        user_memory_enabled=True,
        memory_search_semantic_enabled=True,
        memory_search_semantic_backend="qdrant",
        memory_search_embedding_provider="hf",
        memory_search_embedding_model="intfloat/multilingual-e5-small",
        memory_search_embedding_dimensions=384,
        memory_search_embedding_endpoint="",
    )

    line = bot._runtime_status_memory_index_line("Demo", instructions, qdrant_ok=True)

    assert line.startswith(
        "memory_index=Demo backend=keyword status=ready semantic=invalid "
        "embedding_provider=hf embedding_model=intfloat/multilingual-e5-small embedding_dimensions=384"
    )
    assert "Account-memory embeddings require a local endpoint" in line


def test_runtime_qdrant_collection_specs_follow_active_semantic_memory_config() -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instructions = SimpleNamespace(
        memory_search_semantic_enabled=True,
        memory_search_semantic_backend="qdrant",
        memory_search_embedding_model="intfloat/multilingual-e5-small",
        memory_search_embedding_dimensions=384,
    )

    specs, error = bot._runtime_qdrant_collection_specs({"Demo": instructions})

    assert error == ""
    assert specs[0].name == "teebotus_user_memory"
    assert specs[0].vector_size == 384
    assert specs[0].embedding_model == "intfloat/multilingual-e5-small"


def test_runtime_qdrant_collection_specs_report_invalid_remote_memory_embedding_config() -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instructions = SimpleNamespace(
        memory_search_semantic_enabled=True,
        memory_search_semantic_backend="qdrant",
        memory_search_embedding_provider="hf",
        memory_search_embedding_model="intfloat/multilingual-e5-small",
        memory_search_embedding_dimensions=384,
        memory_search_embedding_endpoint="",
    )

    specs, error = bot._runtime_qdrant_collection_specs({"Demo": instructions})

    assert specs[0].vector_size == USER_MEMORY_QDRANT_EMBEDDING_DIMENSIONS
    assert "invalid user-memory embedding config" in error
    assert "Demo:Account-memory embeddings require a local endpoint" in error


def test_runtime_qdrant_collection_specs_report_conflicting_semantic_memory_configs() -> None:
    bot = importlib.import_module("TeeBotus.bot")
    first = SimpleNamespace(
        memory_search_semantic_enabled=True,
        memory_search_semantic_backend="qdrant",
        memory_search_embedding_model="intfloat/multilingual-e5-small",
        memory_search_embedding_dimensions=384,
    )
    second = SimpleNamespace(
        memory_search_semantic_enabled=True,
        memory_search_semantic_backend="qdrant",
        memory_search_embedding_model="teebotus-account-memory-hash",
        memory_search_embedding_dimensions=64,
    )

    specs, error = bot._runtime_qdrant_collection_specs({"A": first, "B": second})

    assert specs[0].vector_size == USER_MEMORY_QDRANT_EMBEDDING_DIMENSIONS
    assert "conflicting user-memory embedding configs" in error
    assert "A:intfloat/multilingual-e5-small/384" in error
    assert "B:teebotus-account-memory-hash/64" in error


def test_runtime_qdrant_status_url_follows_active_semantic_memory_config() -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instructions = SimpleNamespace(
        memory_search_semantic_enabled=True,
        memory_search_semantic_backend="qdrant",
        memory_search_qdrant_url="http://localhost:6334",
        bibliothekar_enabled=False,
    )

    url, error = bot._runtime_qdrant_status_url({"Demo": instructions})

    assert url == "http://localhost:6334"
    assert error == ""


def test_runtime_qdrant_status_url_reports_conflicting_active_qdrant_urls() -> None:
    bot = importlib.import_module("TeeBotus.bot")
    first = SimpleNamespace(
        memory_search_semantic_enabled=True,
        memory_search_semantic_backend="qdrant",
        memory_search_qdrant_url="http://localhost:6334",
        bibliothekar_enabled=False,
    )
    second = SimpleNamespace(
        memory_search_semantic_enabled=False,
        memory_search_semantic_backend="",
        bibliothekar_enabled=True,
        bibliothekar_backend="haystack",
        bibliothekar_qdrant_url="http://127.0.0.1:6335",
    )

    url, error = bot._runtime_qdrant_status_url({"A": first, "B": second})

    assert url == "http://127.0.0.1:6333"
    assert "conflicting qdrant urls" in error
    assert "A/memory:http://localhost:6334" in error
    assert "B/bibliothekar:http://127.0.0.1:6335" in error


def test_main_starts_default_telegram_runtime_slot(monkeypatch, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    refresh_calls = []

    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    _configure_demo_instance(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setattr(bot, "_start_gemini_free_tier_limit_refresh", lambda config: refresh_calls.append(config))
    monkeypatch.setattr(bot, "_run_telegram_runtime", lambda config: calls.append(config) or 0)

    assert bot.main([]) == 0

    assert refresh_calls
    assert calls
    assert refresh_calls[0] is calls[0]
    assert calls[0].instances[0].instance_name == "Demo"
    assert calls[0].instances[0].accounts[0].label == "telegram:1"


def test_main_refuses_to_start_when_account_storage_preflight_is_broken(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []

    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    _configure_demo_instance(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setattr(
        "TeeBotus.core.status.account_secret_health_lines",
        lambda *, instance_name, project_root: [
            f"account_crypto={instance_name} status=broken mapping=present memory=missing_required keyring=broken"
        ],
    )
    monkeypatch.setattr("TeeBotus.core.status.account_memory_index_health_lines", lambda *, instance_name, project_root: [])
    monkeypatch.setattr(bot, "_run_telegram_runtime", lambda config: calls.append(config) or 0)

    assert bot.main([]) == 2

    captured = capsys.readouterr()
    assert calls == []
    assert "TeeBotus account storage preflight failed; refusing to start bot loops." in captured.err
    assert "account_crypto=Demo status=broken mapping=present memory=missing_required keyring=broken" in captured.err
    assert "Emergency override: TEEBOTUS_ALLOW_BROKEN_ACCOUNT_MEMORY_START=1" in captured.err


def test_main_account_storage_preflight_override_allows_start(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []

    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    _configure_demo_instance(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_ALLOW_BROKEN_ACCOUNT_MEMORY_START", "1")
    monkeypatch.setattr(
        "TeeBotus.core.status.account_secret_health_lines",
        lambda *, instance_name, project_root: [
            f"account_crypto={instance_name} status=broken mapping=present memory=missing_required keyring=broken"
        ],
    )
    monkeypatch.setattr("TeeBotus.core.status.account_memory_index_health_lines", lambda *, instance_name, project_root: [])
    monkeypatch.setattr(bot, "_start_gemini_free_tier_limit_refresh", lambda _config: None)
    monkeypatch.setattr(bot, "_run_telegram_runtime", lambda config: calls.append(config) or 0)

    assert bot.main([]) == 0

    captured = capsys.readouterr()
    assert calls
    assert "TEEBOTUS_ALLOW_BROKEN_ACCOUNT_MEMORY_START=1 allows startup" in captured.err


def test_main_start_does_not_leak_loaded_default_environment(monkeypatch, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []

    monkeypatch.delenv("TELEGRAM_BOT_INSTANCE", raising=False)
    _configure_demo_instance(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setattr(bot, "_run_telegram_runtime", lambda config: calls.append(config) or 0)

    assert bot.main([]) == 0

    assert calls
    assert "TELEGRAM_BOT_INSTANCE" not in os.environ


def test_main_all_start_uses_runtime_instance_discovery(monkeypatch, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    for name in ("DemoA", "DemoB"):
        instance_dir = instances_dir / name
        instance_dir.mkdir(parents=True)
        (instance_dir / "Bot_Verhalten.md").write_text("", encoding="utf-8")
    calls = []

    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "IgnoredByAll")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMOA", "telegram-token-a")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMOB", "telegram-token-b")
    monkeypatch.setattr(bot, "_run_telegram_runtime", lambda config: calls.append(config) or 0)

    assert bot.main(["--all"]) == 0

    assert calls
    assert calls[0].selected_instances == ("DemoA", "DemoB")


def test_main_all_preflight_skips_instances_without_runtime_accounts(monkeypatch, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    for name in ("DemoA", "DemoB"):
        instance_dir = instances_dir / name
        instance_dir.mkdir(parents=True)
        (instance_dir / "Bot_Verhalten.md").write_text("", encoding="utf-8")
    calls = []
    checked_instances = []

    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "all")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMOA", "telegram-token-a")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_DEMOB", raising=False)
    monkeypatch.delenv("SIGNAL_BOT_SERVICE_DEMOA", raising=False)
    monkeypatch.delenv("SIGNAL_BOT_PHONE_NUMBER_DEMOA", raising=False)
    monkeypatch.delenv("SIGNAL_BOT_SERVICE_DEMOB", raising=False)
    monkeypatch.delenv("SIGNAL_BOT_PHONE_NUMBER_DEMOB", raising=False)
    monkeypatch.delenv("MATRIX_BOT_HOMESERVER_DEMOA", raising=False)
    monkeypatch.delenv("MATRIX_BOT_USER_ID_DEMOA", raising=False)
    monkeypatch.delenv("MATRIX_BOT_ACCESS_TOKEN_DEMOA", raising=False)
    monkeypatch.delenv("MATRIX_BOT_HOMESERVER_DEMOB", raising=False)
    monkeypatch.delenv("MATRIX_BOT_USER_ID_DEMOB", raising=False)
    monkeypatch.delenv("MATRIX_BOT_ACCESS_TOKEN_DEMOB", raising=False)

    def secret_health(*, instance_name, project_root):
        checked_instances.append(instance_name)
        if instance_name == "DemoB":
            return [
                "account_crypto=DemoB status=broken mapping=present memory=missing_required keyring=broken"
            ]
        return []

    monkeypatch.setattr("TeeBotus.core.status.account_secret_health_lines", secret_health)
    monkeypatch.setattr("TeeBotus.core.status.account_memory_index_health_lines", lambda *, instance_name, project_root: [])
    monkeypatch.setattr(bot, "_start_gemini_free_tier_limit_refresh", lambda config: None)
    monkeypatch.setattr(bot, "_run_telegram_runtime", lambda config: calls.append(config) or 0)

    assert bot.main(["--all"]) == 0

    assert checked_instances == ["DemoA"]
    assert calls
    assert calls[0].selected_instances == ("DemoA", "DemoB")
    assert tuple(account.label for instance in calls[0].instances for account in instance.accounts) == ("telegram:1",)


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

    def run_telegram(config) -> int:  # noqa: ANN001 - keep the test independent from runtime dataclass imports.
        calls.append(("telegram", labels_for(config, "telegram")))
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
    monkeypatch.setattr(bot, "_run_telegram_runtime", run_telegram)

    assert bot.main(["--all", "--channels", "telegram,signal,matrix"]) == 0

    assert calls == [
        ("matrix", ("matrix:1",)),
        ("signal", ("signal:1",)),
        ("telegram", ("telegram:1",)),
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
    copy_backup_user_dir = (
        tmp_path / "TeeBotus_Backups" / "TeeBotus (Kopie).bak2" / "instances.bak" / "Demo" / "data" / "users" / "395935293"
    )
    copy_backup_user_dir.mkdir(parents=True)
    (copy_backup_user_dir / "User_Memory_Entries.jsonl").write_text(
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
        f'--target-instances-dir {project_root / "instances"} --instance Demo --replace-unreadable '
        f'--replace-unreadable-account-metadata '
        f'--json-output {DEFAULT_OBSIDIAN_INCOMING_DIR / "teebotus-legacy-import-preflight-Demo.json"} '
        f'--markdown-output {DEFAULT_OBSIDIAN_INCOMING_DIR / "teebotus-legacy-import-preflight-Demo.md"}" '
        f'apply_command="python3 scripts/import_legacy_user_memory.py --legacy-instances-dir {tmp_path / "TeeBotus.bak2"} '
        f'--target-instances-dir {project_root / "instances"} --instance Demo --replace-unreadable '
        '--replace-unreadable-account-metadata --apply"'
    ) in lines


def test_account_memory_status_detects_legacy_backup_collection_directory(tmp_path) -> None:
    project_root = tmp_path / "TeeBotus"
    accounts_root = project_root / "instances" / "Demo" / "data" / "accounts"
    bad_store = AccountStore(accounts_root, "Demo", secret_provider=StaticSecretProvider(b"b" * 32))
    account_id = bad_store.resolve_or_create_account(telegram_identity_key("395935293"))
    bad_store.write_memory_entries(account_id, [{"id": "bad", "user_text": "unreadable"}])
    backup_user_dir = tmp_path / "TeeBotus_Backups" / "TeeBotus.bak2" / "instances.bak" / "Demo" / "data" / "users" / "395935293"
    backup_user_dir.mkdir(parents=True)
    (backup_user_dir / "User_Memory_Entries.jsonl").write_text(
        '{"id":"legacy_1","user_text":"A"}\n{"id":"legacy_2","user_text":"B"}\n',
        encoding="utf-8",
    )

    lines = account_memory_index_health_lines(instance_name="Demo", project_root=project_root)

    legacy_line = next(line for line in lines if line.startswith("account_memory_recovery_legacy=Demo "))
    assert "status=available" in legacy_line
    assert "sources=1 entries=2" in legacy_line
    assert f"path={tmp_path / 'TeeBotus_Backups' / 'TeeBotus.bak2' / 'instances.bak'} " in legacy_line
    assert f"--legacy-instances-dir {tmp_path / 'TeeBotus_Backups' / 'TeeBotus.bak2'}" in legacy_line
    assert "Kopie" not in legacy_line


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

    recovery_line = next(line for line in lines if line.startswith("account_memory_recovery=Demo Bot "))
    assert "--instances 'Demo Bot'" in recovery_line
    legacy_line = next(line for line in lines if line.startswith("account_memory_recovery_legacy=Demo Bot "))
    assert "--instance 'Demo Bot'" in legacy_line
    assert "teebotus-legacy-import-preflight-Demo_Bot.json" in legacy_line
    assert "teebotus-legacy-import-preflight-Demo_Bot.md" in legacy_line
    assert "apply_command=" in legacy_line
    assert "--replace-unreadable --replace-unreadable-account-metadata --apply" in legacy_line


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
        "llm=Demo/telegram:1 provider=litellm model=ollama_chat/llama3.2:3b "
        "status=configured profile=local_ollama base_url=http://127.0.0.1:11434/api "
        "api_key=configured timeout_seconds=180 max_output_tokens=700 temperature=0.7"
    ) in captured.out
    assert "ollama=127.0.0.1:11434 status=unreachable error=unsafe Ollama base_url: credentials are not allowed" in captured.out
    assert "fallback_models=2" not in captured.out
    assert "llm-secret" not in captured.out
    assert "user:secret" not in captured.out
    assert "token=nope" not in captured.out


def test_runtime_status_text_redacts_generic_secret_assignments() -> None:
    bot = importlib.import_module("TeeBotus.bot")

    text = bot._sanitize_status_text(
        "provider error api_key=plain-secret password:hunter2 access_token: abc123 "
        "bearer_token=xyz detail=password:nested-secret"
    )

    assert text == (
        "provider error api_key=<redacted> password:<redacted> access_token:<redacted> "
        "bearer_token=<redacted> detail=password:<redacted>"
    )
    assert "plain-secret" not in text
    assert "hunter2" not in text
    assert "abc123" not in text
    assert "xyz" not in text
    assert "nested-secret" not in text


def test_runtime_status_section_redacts_at_print_sink(capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")

    bot._print_runtime_status_section(
        "Secrets",
        (
            "llm=Demo status=broken api_key=plain-secret password:hunter2 "
            "target=https://user:pass@example.test/path",
        ),
    )
    captured = capsys.readouterr()

    assert "plain-secret" not in captured.out
    assert "hunter2" not in captured.out
    assert "user:pass" not in captured.out
    assert "api_key=<redacted>" in captured.out
    assert "password:<redacted>" in captured.out
    assert "target=https://<redacted>@example.test/path" in captured.out


def test_runtime_status_text_redacts_url_query_and_fragment_secrets() -> None:
    bot = importlib.import_module("TeeBotus.bot")

    text = bot._sanitize_status_text(
        "target=https://user:pass@example.test/path?api_key=plain-secret&ok=1&api_key_env=GEMINI_API_KEY"
        "#access_token=fragment-secret;token=configured"
    )

    assert "user:pass" not in text
    assert "plain-secret" not in text
    assert "fragment-secret" not in text
    assert "target=https://<redacted>@example.test/path?api_key=<redacted>&ok=1&api_key_env=GEMINI_API_KEY#access_token=<redacted>;token=configured" in text


def test_runtime_status_text_redacts_schemeless_url_credentials() -> None:
    bot = importlib.import_module("TeeBotus.bot")

    text = bot._sanitize_status_text(
        "target=user:plain-password@signal.example:8080/path?token=plain-token "
        "base_url=:redis-password@example.test/0 "
        "error=user:raw-password@matrix.example/_matrix"
    )

    assert "plain-password" not in text
    assert "plain-token" not in text
    assert "redis-password" not in text
    assert "raw-password" not in text
    assert "target=<redacted>@signal.example:8080/path?token=<redacted>" in text
    assert "base_url=<redacted>@example.test/0" in text
    assert "error=<redacted>@matrix.example/_matrix" in text


def test_runtime_status_text_redacts_username_only_url_userinfo() -> None:
    bot = importlib.import_module("TeeBotus.bot")

    text = bot._sanitize_status_text(
        "target=https://plain-userinfo-token@example.test/path "
        "error=raw-userinfo-token@matrix.example/_matrix"
    )

    assert "plain-userinfo-token" not in text
    assert "raw-userinfo-token" not in text
    assert "target=https://<redacted>@example.test/path" in text
    assert "error=<redacted>@matrix.example/_matrix" in text


def test_runtime_status_text_redacts_embedded_url_credentials() -> None:
    bot = importlib.import_module("TeeBotus.bot")

    text = bot._sanitize_status_text(
        "error=(target=https://user:paren-secret@example.test/path) "
        'json={"target":"https://json-user:json-secret@example.test/path?token=json-token"} '
        "nested=(target=user:schemeless-secret@matrix.example/_matrix)"
    )

    for leaked in ("paren-secret", "json-secret", "json-token", "schemeless-secret"):
        assert leaked not in text
    assert "error=(target=https://<redacted>@example.test/path)" in text
    assert 'json={"target":"https://<redacted>@example.test/path?token=<redacted>"}' in text
    assert "nested=(target=<redacted>@matrix.example/_matrix)" in text


def test_runtime_status_text_redacts_url_credentials_with_invalid_port() -> None:
    bot = importlib.import_module("TeeBotus.bot")

    text = bot._sanitize_status_text(
        "target=https://user:plain-password@example.test:notaport/path "
        "error=user:raw-password@matrix.example:999999/_matrix"
    )

    assert "plain-password" not in text
    assert "raw-password" not in text
    assert "notaport" not in text
    assert "999999" not in text
    assert "target=https://<redacted>@example.test/path" in text
    assert "error=<redacted>@matrix.example/_matrix" in text


def test_runtime_status_text_redacts_malformed_url_credentials() -> None:
    bot = importlib.import_module("TeeBotus.bot")

    text = bot._sanitize_status_text(
        "target=https://user:plain-password@[bad/path?token=plain-token "
        "error=user:raw-password@[bad/path"
    )

    assert "plain-password" not in text
    assert "raw-password" not in text
    assert "plain-token" not in text
    assert "target=https://<redacted>@[bad/path?token=<redacted>" in text
    assert "error=<redacted>@[bad/path" in text


def test_runtime_status_text_redacts_structured_secret_assignments() -> None:
    bot = importlib.import_module("TeeBotus.bot")

    text = bot._sanitize_status_text(
        "api_key=\"plain secret value\" password='another secret phrase' bearer_token=`third secret value` "
        "refresh_tokens=multi word token max_output_tokens=700 tokens=provider_usage_response "
        "message=(client_secret=structured-secret) details=[api_key=\"bracket secret value\"] "
        "meta={password=curly-secret} diagnostic_json={\"api_key\":\"json-secret-value\",\"api_key_env\":\"GEMINI_API_KEY\"} "
        "quoted=\"api_key=quoted-inner-secret\""
    )

    for leaked in (
        "plain secret value",
        "another secret phrase",
        "third secret value",
        "multi word token",
        "structured-secret",
        "bracket secret value",
        "curly-secret",
        "json-secret-value",
        "quoted-inner-secret",
    ):
        assert leaked not in text
    assert "api_key=<redacted>" in text
    assert "password=<redacted>" in text
    assert "bearer_token=<redacted>" in text
    assert "refresh_tokens=<redacted>" in text
    assert "message=(client_secret=<redacted>)" in text
    assert "details=[api_key=<redacted>]" in text
    assert "meta={password=<redacted>}" in text
    assert '"api_key":"<redacted>"' in text
    assert '"api_key_env":"GEMINI_API_KEY"' in text
    assert 'quoted="api_key=<redacted>"' in text
    assert "max_output_tokens=700" in text
    assert "tokens=provider_usage_response" in text


def test_runtime_status_text_redacts_quoted_authorization_values() -> None:
    bot = importlib.import_module("TeeBotus.bot")

    text = bot._sanitize_status_text(
        "authorization=\"Bearer bearer-secret-token\" "
        "Authorization: 'Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==' "
        "proxy-authorization=\"ApiKey proxy-secret-token\" "
        "proxy_authorization=`Token proxy-underscore-secret` "
        "`authorization`:`Bearer backtick-key-secret`"
    )

    assert "bearer-secret-token" not in text
    assert "QWxhZGRpbjpvcGVuIHNlc2FtZQ==" not in text
    assert "proxy-secret-token" not in text
    assert "proxy-underscore-secret" not in text
    assert "backtick-key-secret" not in text
    assert 'authorization="Bearer <redacted-secret>"' in text
    assert "Authorization: 'Basic <redacted-secret>'" in text
    assert 'proxy-authorization="ApiKey <redacted-secret>"' in text
    assert "proxy_authorization=`Token <redacted-secret>`" in text
    assert "`authorization`:`Bearer <redacted-secret>`" in text


def test_runtime_status_text_redacts_proxy_authorization_with_underscore() -> None:
    bot = importlib.import_module("TeeBotus.bot")

    text = bot._sanitize_status_text(
        "proxy_authorization=Bearer proxy-underscore-secret "
        "PROXY_AUTHORIZATION='ApiKey quoted-proxy-underscore-secret'"
    )

    assert "proxy-underscore-secret" not in text
    assert "quoted-proxy-underscore-secret" not in text
    assert "proxy_authorization=Bearer <redacted-secret>" in text
    assert "PROXY_AUTHORIZATION='ApiKey <redacted-secret>'" in text


def test_runtime_status_text_redacts_multiline_private_key_blocks() -> None:
    bot = importlib.import_module("TeeBotus.bot")

    private_key_body = "ABCDEFSECRET"
    text = bot._sanitize_status_text(
        "private_key=-----BEGIN PRIVATE KEY-----\n"
        f"{private_key_body}\n"
        "-----END PRIVATE KEY----- "
        "service_account_private_key=\"-----BEGIN ENCRYPTED PRIVATE KEY-----\n"
        f"{private_key_body}\n"
        "-----END ENCRYPTED PRIVATE KEY-----\" ok=1"
    )

    assert "BEGIN PRIVATE KEY" not in text
    assert "END PRIVATE KEY" not in text
    assert "BEGIN ENCRYPTED PRIVATE KEY" not in text
    assert "END ENCRYPTED PRIVATE KEY" not in text
    assert private_key_body not in text
    assert "private_key=<redacted>" in text
    assert "service_account_private_key=<redacted>" in text
    assert "<redacted>>" not in text
    assert "ok=1" in text


def test_runtime_status_text_redacts_oauth_jwt_and_authorization_tokens() -> None:
    bot = importlib.import_module("TeeBotus.bot")

    google_oauth_token = "ya29.a0AfH6SMabcdefghijklmnopqrstuvwxyz1234567890"
    jwt_like_token = "abcdefghijklmnopqrstuvwx.ABCDEF.abcdefghijklmnopqrstuvwxyz1234567890"
    bearer_token = "abcdefghijklmnopqrstuvwxyz1234567890"
    api_key_header_token = "apikeyheaderabcdefghijklmnopqrstuvwxyz123456"
    text = bot._sanitize_status_text(
        f"google_oauth={google_oauth_token} jwt={jwt_like_token} "
        f"error=Authorization: Bearer {bearer_token}; bare=Bearer {bearer_token}; "
        f"header=Authorization: ApiKey {api_key_header_token}; "
        f"diagnostic_headers={{\"authorization\":\"Bearer {bearer_token}\"}}"
    )

    for leaked in (google_oauth_token, jwt_like_token, bearer_token, api_key_header_token):
        assert leaked not in text
    assert "google_oauth=ya29.<redacted>" in text
    assert "jwt=<redacted-jwt>" in text
    assert "Authorization: Bearer <redacted-secret>" in text
    assert "Bearer <redacted-secret>" in text
    assert "Authorization: ApiKey <redacted-secret>" in text
    assert '"authorization":"Bearer <redacted-secret>"' in text


def test_runtime_status_admin_notify_sanitizes_report_lines() -> None:
    bot = importlib.import_module("TeeBotus.bot")

    sanitized = bot._sanitize_admin_notify_status_line("admin_notify=runtime_status status=failed api_key=plain-secret")

    assert sanitized == "admin_notify=runtime_status status=failed api_key=<redacted>"


def test_runtime_status_text_keeps_secret_named_paths_visible() -> None:
    bot = importlib.import_module("TeeBotus.bot")

    text = bot._sanitize_status_text(
        "account_memory_metadata=Demo status=broken item=account_secrets "
        "path=/repo/instances/Demo/data/accounts/Account_Secrets.json secret=plain-secret"
    )

    assert "path=/repo/instances/Demo/data/accounts/Account_Secrets.json" in text
    assert "secret=<redacted>" in text
    assert "plain-secret" not in text


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


def test_runtime_status_reports_degraded_direct_remote_fallback_without_key(monkeypatch, capsys, tmp_path) -> None:
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
    monkeypatch.setenv("TEEBOTUS_LLM_FALLBACK_MODELS_DEMO", "groq/llama-3.1-8b-instant,ollama_chat/qwen2.5:7b")
    monkeypatch.setenv("TEEBOTUS_LLM_ALLOW_REMOTE_FALLBACK_DEMO", "yes")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert (
        "llm=Demo/telegram:1 provider=ollama model=llama3.1:8b "
        "status=degraded api_key=none fallback_models=2 fallback_api_key=missing remote_fallback=enabled"
    ) in captured.out


def test_runtime_status_reports_configured_direct_remote_fallback_key(monkeypatch, capsys, tmp_path) -> None:
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
    monkeypatch.setenv("TEEBOTUS_LLM_FALLBACK_MODELS_DEMO", "groq/llama-3.1-8b-instant")
    monkeypatch.setenv("TEEBOTUS_LLM_ALLOW_REMOTE_FALLBACK_DEMO", "yes")
    monkeypatch.setenv("TEEBOTUS_LLM_API_KEY_DEMO", "fallback-secret")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert (
        "llm=Demo/telegram:1 provider=ollama model=llama3.1:8b "
        "status=configured api_key=configured fallback_models=1 fallback_api_key=configured remote_fallback=enabled"
    ) in captured.out
    assert "fallback-secret" not in captured.out


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


def test_runtime_status_uses_instruction_llm_disabled_without_runtime_override(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text(
        "## LLM\n- enabled: nein\n- profile: local_ollama\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("OPENAI_API_KEY_DEMO", "openai-secret")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "llm=Demo/telegram:1 provider=none model=<disabled> status=disabled" in captured.out
    assert "openai-secret" not in captured.out


def test_runtime_status_runtime_enabled_overrides_instruction_llm_disabled(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text(
        "## LLM\n- enabled: nein\n- profile: local_ollama\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_ENABLED_DEMO", "true")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert (
        "llm=Demo/telegram:1 provider=litellm model=ollama_chat/llama3.2:3b "
        "status=configured profile=local_ollama base_url=http://127.0.0.1:11434 api_key=none"
    ) in captured.out


def test_runtime_status_uses_instruction_llm_profile_without_runtime_override(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text(
        "## LLM\n- enabled: ja\n- profile: local_ollama\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert (
        "llm=Demo/telegram:1 provider=litellm model=ollama_chat/llama3.2:3b "
        "status=configured profile=local_ollama base_url=http://127.0.0.1:11434 api_key=none"
    ) in captured.out


def test_runtime_status_runtime_profile_overrides_instruction_profile(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text(
        "## LLM\n- enabled: ja\n- profile: local_ollama\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_PROFILE_DEMO", "hf_mistral")
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert (
        "llm=Demo/telegram:1 provider=litellm model=huggingface/mistralai/Mistral-7B-Instruct-v0.3 "
        "status=missing_key profile=hf_mistral api_key=none"
    ) in captured.out
    llm_line = next(line for line in captured.out.splitlines() if line.startswith("llm=Demo/telegram:1 "))
    assert "local_ollama" not in llm_line


def test_runtime_status_uses_instruction_llm_api_key_env_for_direct_remote_provider(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text(
        "## LLM\n"
        "- enabled: ja\n"
        "- provider: litellm\n"
        "- model: groq/llama-3.1-8b-instant\n"
        "- api_key_env: GROQ_API_KEY\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("GROQ_API_KEY", "groq-secret")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert (
        "llm=Demo/telegram:1 provider=litellm model=groq/llama-3.1-8b-instant "
        "status=configured api_key=configured"
    ) in captured.out
    assert "groq-secret" not in captured.out


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


def test_runtime_status_reports_missing_key_for_remote_profile(monkeypatch, capsys, tmp_path) -> None:
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
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert (
        "llm=Demo/telegram:1 provider=litellm model=huggingface/mistralai/Mistral-7B-Instruct-v0.3 "
        "status=missing_key profile=hf_mistral api_key=none"
    ) in captured.out


def test_runtime_status_reports_vertex_profile_credentials_without_leaking_value(monkeypatch, capfd, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_PROFILE_DEMO", "vertex_gemini_flash")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/private/vertex-service-account.json")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capfd.readouterr()
    assert (
        "llm=Demo/telegram:1 provider=litellm model=vertex_ai/gemini-3.5-flash "
        "status=configured profile=vertex_gemini_flash api_key=<redacted>"
    ) in captured.out
    assert "/private/vertex-service-account.json" not in captured.out


def test_runtime_status_accepts_gemini_key_ring_without_single_key(monkeypatch, capfd, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_PROFILE_DEMO", "gemini_flash_stateful")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEYS_ACCOUNT_1", "a1,a2")
    monkeypatch.setenv("GEMINI_API_KEYS_ACCOUNT_2", "b1,b2")
    monkeypatch.setenv("GEMINI_API_KEYS_ACCOUNT_3", "c1,c2")
    monkeypatch.setenv("TEEBOTUS_GEMINI_SERVICE_TIER_DEMO", "flex")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capfd.readouterr()
    assert "llm=Demo/telegram:1 provider=litellm_gemini_stateful model=gemini/" in captured.out
    assert "status=configured profile=gemini_flash_stateful" in captured.out
    assert "google_mode=stateful service_tier=flex" in captured.out
    assert "api_budget=bibliothekar_answer profile=gemini_flash_stateful" in captured.out
    assert "key_ring=6" in captured.out
    assert "a1" not in captured.out


def test_runtime_status_reports_stateless_gemini_profile_mode(monkeypatch, capfd, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_PROFILE_DEMO", "gemini_flash_stateless")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("TEEBOTUS_GEMINI_SERVICE_TIER_DEMO", "flex")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capfd.readouterr()
    assert (
        "llm=Demo/telegram:1 provider=litellm_gemini_stateless model=gemini/gemini-3.5-flash "
        "status=configured profile=gemini_flash_stateless api_key=<redacted> "
        "google_mode=stateless service_tier=flex"
    ) in captured.out


def test_runtime_status_reports_paid_gemini_profile_billing(monkeypatch, capfd, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_PROFILE_DEMO", "gemini_flash_paid_stateful")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("TEEBOTUS_GEMINI_FREE_TIER_RPM", "0")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capfd.readouterr()
    assert (
        "llm=Demo/telegram:1 provider=litellm_gemini_paid_stateful model=gemini/gemini-3.5-flash "
        "status=configured profile=gemini_flash_paid_stateful api_key=<redacted> "
        "google_mode=stateful"
    ) in captured.out
    assert "llm=Demo/telegram:1" in captured.out and "free_tier_guard=off" in captured.out
    assert "llm=Demo/telegram:1" in captured.out and "google_billing=paid" in captured.out


def test_runtime_status_google_helpers_delegate_to_central_gemini_route_logic(monkeypatch) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(
        bot,
        "route_uses_google_gemini",
        lambda *, provider, model: provider == "future_google_alias" and model == "future-model",
    )
    monkeypatch.setattr(
        bot,
        "provider_is_paid_google_gemini",
        lambda provider: provider == "future_paid_google_alias",
    )

    assert bot._status_route_uses_google_gemini(provider="future_google_alias", model="future-model") is True
    assert bot._status_google_billing(provider="future_paid_google_alias") == "paid"
    assert bot._status_route_uses_gemini_api(provider="vertex_ai", model="vertex_ai/gemini-3.5-flash") is False


def test_runtime_status_route_uses_instance_scoped_gemini_key_ring(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("TEEBOTUS_GEMINI_API_KEY_RING", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_RING", raising=False)
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.delenv("TEEBOTUS_GEMINI_API_KEYS_ACCOUNT_1", raising=False)
    monkeypatch.delenv("GEMINI_API_KEYS_ACCOUNT_1", raising=False)
    monkeypatch.setenv("TEEBOTUS_GEMINI_API_KEYS_DEMO_ACCOUNT_1", "demo-a1")
    monkeypatch.setenv("TEEBOTUS_GEMINI_API_KEYS_DEMO_ACCOUNT_2", "demo-b1")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert (
        "llm_route=bibliothekar_answer profile=gemini_flash_stateful provider=litellm_gemini_stateful "
        "model=gemini/gemini-3.5-flash status=configured api_key_env=GEMINI_API_KEY "
        "api_key_ring=2 api_key_instances=1/1"
    ) in captured.out
    assert "demo-a1" not in captured.out
    assert "demo-b1" not in captured.out


def test_runtime_status_route_reports_degraded_instance_scoped_gemini_keys(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    for name in ("Demo", "Other"):
        instance_dir = instances_dir / name
        instance_dir.mkdir(parents=True)
        (instance_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "all")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "demo-token")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_OTHER", "other-token")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("TEEBOTUS_GEMINI_API_KEY_RING", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_RING", raising=False)
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.delenv("TEEBOTUS_GEMINI_API_KEYS_ACCOUNT_1", raising=False)
    monkeypatch.delenv("GEMINI_API_KEYS_ACCOUNT_1", raising=False)
    monkeypatch.setenv("TEEBOTUS_GEMINI_API_KEYS_DEMO_ACCOUNT_1", "demo-a1,demo-a2")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert (
        "llm_route=bibliothekar_answer profile=gemini_flash_stateful provider=litellm_gemini_stateful "
        "model=gemini/gemini-3.5-flash status=degraded api_key_env=GEMINI_API_KEY "
        "api_key_ring=2 api_key_instances=1/2"
    ) in captured.out
    assert "error=missing api key for 1/2 instances" in captured.out
    assert "demo-a1" not in captured.out


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
        "llm=Demo/telegram:1 provider=hf_pool model=pool:default#structured_decision "
        "status=unavailable purpose=structured_decision api_key=none "
        "fallback_models=1 fallback_profile=local_ollama "
        "fallback_model=ollama_chat/llama3.2:3b fallback_base_url=http://127.0.0.1:11434 "
        "remote_fallback=enabled"
    ) in captured.out
    assert (
        "llm_route=structured_decision profile=hf_pool_structured provider=hf_pool "
        "model=pool:default#structured_decision status=unavailable "
        "fallback=local_ollama fallback_profile=local_ollama "
        "fallback_model=ollama_chat/llama3.2:3b fallback_base_url=http://127.0.0.1:11434"
    ) in captured.out
    assert (
        "llm_route=bibliothekar_answer profile=gemini_flash_stateful provider=litellm_gemini_stateful "
        "model=gemini/gemini-3.5-flash "
    ) in captured.out
    assert "llm_route=bibliothekar_answer" in captured.out and " google_mode=stateful" in captured.out
    assert "llm_route=bibliothekar_answer" in captured.out and " free_tier_guard=" in captured.out
    assert (
        "structured_decision=Demo/telegram:1 status=enabled source=runtime_llm_configured "
        "profile=hf_pool_structured provider=hf_pool model=pool:default#structured_decision "
        "route_status=unavailable fallback=local_ollama fallback_model=ollama_chat/llama3.2:3b "
        "fallback_base_url=http://127.0.0.1:11434 remote_fallback=enabled"
    ) in captured.out


def test_runtime_status_reports_structured_decision_disabled_by_instruction(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text(
        """
        # Bot

        ## OpenAI
        - enabled: ja

        ## LLM
        - structured_decision_enabled: nein
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "structured_decision=Demo/telegram:1 status=disabled reason=structured_decision_disabled" in captured.out


def test_runtime_status_reports_configured_remote_fallback_key(monkeypatch, capsys, tmp_path) -> None:
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
    monkeypatch.setenv("GROQ_API_KEY", "groq-secret")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert (
        "llm=Demo/telegram:1 provider=hf_pool model=pool:default#structured_decision "
        "status=unavailable purpose=structured_decision api_key=none "
        "fallback_models=1 fallback_profile=local_ollama "
        "fallback_model=ollama_chat/llama3.2:3b fallback_base_url=http://127.0.0.1:11434 "
        "remote_fallback=enabled"
    ) in captured.out
    assert "groq-secret" not in captured.out


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


def test_runtime_status_reports_missing_key_for_remote_litellm_purpose_route(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_PURPOSE_DEMO", "cheap_fast")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert (
        "llm=Demo/telegram:1 provider=litellm model=groq/llama-3.1-8b-instant "
        "status=missing_key purpose=cheap_fast api_key=none fallback_models=1"
    ) in captured.out


def test_runtime_status_reports_missing_key_for_direct_remote_litellm_model(monkeypatch, capsys, tmp_path) -> None:
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
    monkeypatch.setenv("TEEBOTUS_LLM_MODEL_DEMO", "openai/gpt-4.1-mini")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "llm=Demo/telegram:1 provider=litellm model=openai/gpt-4.1-mini status=missing_key api_key=none" in captured.out


def test_runtime_status_keeps_local_litellm_base_url_configured_without_key(monkeypatch, capsys, tmp_path) -> None:
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
    monkeypatch.setenv("TEEBOTUS_LLM_MODEL_DEMO", "local-custom-model")
    monkeypatch.setenv("TEEBOTUS_LLM_BASE_URL_DEMO", "http://127.0.0.1:9000/v1")

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert (
        "llm=Demo/telegram:1 provider=litellm model=local-custom-model "
        "status=configured base_url=http://127.0.0.1:9000/v1 api_key=none"
    ) in captured.out


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
    assert "llm=Demo/telegram:1 provider=litellm model=ollama_chat/llama3.2:3b status=configured profile=local_ollama" in captured.out
    assert "ollama=127.0.0.1:11434 status=reachable models=llama3.1:8b" in captured.out


def test_runtime_status_checks_ollama_for_instruction_local_profile(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text(
        "## LLM\n- enabled: ja\n- profile: local_ollama\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")

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
    assert "llm=Demo/telegram:1 provider=litellm model=ollama_chat/llama3.2:3b status=configured profile=local_ollama" in captured.out
    assert "ollama=127.0.0.1:11434 status=reachable models=llama3.1:8b" in captured.out


def test_runtime_status_skips_ollama_when_instruction_llm_disabled(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text(
        "## LLM\n- enabled: nein\n- profile: local_ollama\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")

    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("disabled instruction LLM must not probe Ollama")

    monkeypatch.setattr("TeeBotus.runtime.ollama_health.urllib.request.urlopen", fail_urlopen)

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "llm=Demo/telegram:1 provider=none model=<disabled> status=disabled" in captured.out
    assert "ollama=127.0.0.1:11434" not in captured.out


def test_runtime_status_runtime_direct_provider_overrides_instruction_remote_profile(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text(
        "## LLM\n- enabled: ja\n- profile: hf_mistral\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_PROVIDER_DEMO", "litellm")
    monkeypatch.setenv("TEEBOTUS_LLM_MODEL_DEMO", "ollama_chat/llama3.1:8b")
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)

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
    assert (
        "llm=Demo/telegram:1 provider=litellm model=ollama_chat/llama3.1:8b "
        "status=configured api_key=none"
    ) in captured.out
    assert "profile=hf_mistral" not in captured.out
    assert calls == ["http://127.0.0.1:11434/api/tags"]
    assert "ollama=127.0.0.1:11434 status=reachable models=llama3.1:8b" in captured.out


def test_runtime_status_runtime_purpose_overrides_instruction_remote_profile(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text(
        "## LLM\n- enabled: ja\n- profile: hf_mistral\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("TEEBOTUS_LLM_PURPOSE_DEMO", "structured_decision")
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)

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
    assert (
        "llm=Demo/telegram:1 provider=hf_pool model=pool:default#structured_decision "
        "status=unavailable purpose=structured_decision api_key=none fallback_models=1"
    ) in captured.out
    assert "profile=hf_mistral" not in captured.out
    assert calls == ["http://127.0.0.1:11434/api/tags"]
    assert "ollama=127.0.0.1:11434 status=reachable models=llama3.1:8b" in captured.out


def test_runtime_status_profile_uses_runtime_base_url_override_for_llm_and_ollama(monkeypatch, capsys, tmp_path) -> None:
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
    monkeypatch.setenv("TEEBOTUS_LLM_BASE_URL_DEMO", "http://127.0.0.1:11555/api")

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
    assert calls == ["http://127.0.0.1:11555/api/tags"]
    assert (
        "llm=Demo/telegram:1 provider=litellm model=ollama_chat/llama3.2:3b "
        "status=configured profile=local_ollama base_url=http://127.0.0.1:11555/api api_key=none"
    ) in captured.out
    assert "ollama=127.0.0.1:11555 status=reachable models=llama3.1:8b" in captured.out
    assert "ollama=127.0.0.1:11434" not in captured.out


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
    assert "llm=Demo/telegram:1 provider=hf_pool model=pool:default#structured_decision status=unavailable purpose=structured_decision" in captured.out
    assert "ollama=127.0.0.1:11434 status=reachable models=llama3.1:8b" in captured.out


def test_runtime_status_purpose_route_uses_runtime_base_url_override_for_llm_and_ollama(monkeypatch, capsys, tmp_path) -> None:
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
    monkeypatch.setenv("TEEBOTUS_LLM_BASE_URL_DEMO", "http://127.0.0.1:11556/api")

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
    assert calls == ["http://127.0.0.1:11556/api/tags"]
    assert (
        "llm=Demo/telegram:1 provider=hf_pool model=pool:default#structured_decision "
        "status=unavailable purpose=structured_decision base_url=http://127.0.0.1:11556/api api_key=none"
    ) in captured.out
    assert "ollama=127.0.0.1:11556 status=reachable models=llama3.1:8b" in captured.out
    assert "ollama=127.0.0.1:11434" not in captured.out


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
    assert "bibliothekar=Demo backend=local store=json collection=teebotus_bibliothekar_chunks status=ready documents=1 chunks=1" in captured.out


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


def test_runtime_status_reports_llamaindex_bibliothekar_ready(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    library_dir = demo_dir / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text(
        "## Bibliothekar\n- backend: llamaindex\n",
        encoding="utf-8",
    )
    (library_dir / "therapie.txt").write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setattr("TeeBotus.runtime.bibliothekar_service._module_available", lambda name: name == "llama_index.core")
    monkeypatch.setattr("TeeBotus.runtime.bibliothekar_service.LlamaIndexBibliothekarBackend._build_default_query_engine", lambda self, max_chunks=5: object())

    assert bot.main(["--runtime-status", "--channels", "telegram"]) == 0

    captured = capsys.readouterr()
    assert "bibliothekar=Demo backend=llamaindex store=llamaindex collection=teebotus_bibliothekar_chunks target=local_in_memory status=ready documents=1 chunks=1" in captured.out


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


def test_runtime_status_reports_duplicate_signal_phone_as_warning(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_DEMO", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", "+491234")

    def fake_check_signal_services(config):
        account = [account for instance in config.instances for account in instance.accounts if account.channel == "signal"][0]
        return (SimpleNamespace(account=account, ok=True, target="127.0.0.1:8080", error=""),)

    def fake_check_signal_accounts(config):
        account = [account for instance in config.instances for account in instance.accounts if account.channel == "signal"][0]
        return (
            SimpleNamespace(
                account=account,
                ok=True,
                registered=True,
                target="127.0.0.1:8080",
                error="",
                warning="duplicate phone number with Other/signal:1",
            ),
        )

    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_services", fake_check_signal_services)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_accounts", fake_check_signal_accounts)

    assert bot.main(["--runtime-status", "--channels", "signal"]) == 0
    captured = capsys.readouterr()
    assert (
        "signal_account=Demo/signal:1 phone=+491234 target=127.0.0.1:8080 status=registered "
        "warning=duplicate phone number with Other/signal:1"
    ) in captured.out
    assert "status=unavailable warning=duplicate phone number" not in captured.out


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
    assert "matrix_account=Demo/matrix:1 target=matrix.example:443 status=configured user_id=configured" in captured.out


def test_runtime_status_reports_duplicate_matrix_user_id_without_leaking_user_id(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    for name in ("DemoA", "DemoB"):
        instance_dir = instances_dir / name
        instance_dir.mkdir(parents=True)
        (instance_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCES", "DemoA,DemoB")
    monkeypatch.setenv("MATRIX_BOT_HOMESERVER_DEMOA", "https://matrix-a.example")
    monkeypatch.setenv("MATRIX_BOT_USER_ID_DEMOA", "@bot:example")
    monkeypatch.setenv("MATRIX_BOT_ACCESS_TOKEN_DEMOA", "token-a")
    monkeypatch.setenv("MATRIX_BOT_HOMESERVER_DEMOB", "https://matrix-b.example")
    monkeypatch.setenv("MATRIX_BOT_USER_ID_DEMOB", "@bot:example")
    monkeypatch.setenv("MATRIX_BOT_ACCESS_TOKEN_DEMOB", "token-b")

    def fake_check_matrix_homeservers(config):
        return tuple(
            SimpleNamespace(
                account=account,
                ok=True,
                target=f"{account.matrix_homeserver.removeprefix('https://')}:443",
                error="",
            )
            for instance in config.instances
            for account in instance.accounts
            if account.channel == "matrix"
        )

    monkeypatch.setattr("TeeBotus.runtime.matrix_runner.check_matrix_homeservers", fake_check_matrix_homeservers)

    assert bot.main(["--runtime-status", "--channels", "matrix"]) == 0
    captured = capsys.readouterr()
    assert (
        "matrix_account=DemoB/matrix:1 target=matrix-b.example:443 status=broken "
        "error=duplicate user ID with DemoA/matrix:1"
    ) in captured.out
    assert "@bot:example" not in captured.out


def test_runtime_status_reports_numbered_signal_and_matrix_slots(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_DEMO", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", "+491")
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_DEMO_2", "http://127.0.0.1:8081")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_DEMO_2", "+492")
    monkeypatch.setenv("MATRIX_BOT_HOMESERVER_DEMO", "https://matrix-a.example")
    monkeypatch.setenv("MATRIX_BOT_USER_ID_DEMO", "@a:example")
    monkeypatch.setenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", "token-a")
    monkeypatch.setenv("MATRIX_BOT_HOMESERVER_DEMO_2", "https://matrix-b.example")
    monkeypatch.setenv("MATRIX_BOT_USER_ID_DEMO_2", "@b:example")
    monkeypatch.setenv("MATRIX_BOT_ACCESS_TOKEN_DEMO_2", "token-b")
    monkeypatch.setenv("MATRIX_BOT_DEVICE_ID_DEMO_2", "dev-b")

    def fake_check_signal_services(config):
        return tuple(
            SimpleNamespace(
                account=account,
                ok=True,
                target=account.signal_service.removeprefix("http://"),
                error="",
            )
            for instance in config.instances
            for account in instance.accounts
            if account.channel == "signal"
        )

    def fake_check_signal_accounts(config):
        return tuple(
            SimpleNamespace(
                account=account,
                ok=True,
                registered=True,
                target=account.signal_service.removeprefix("http://"),
                error="",
            )
            for instance in config.instances
            for account in instance.accounts
            if account.channel == "signal"
        )

    def fake_check_matrix_homeservers(config):
        return tuple(
            SimpleNamespace(
                account=account,
                ok=True,
                target=f"{account.matrix_homeserver.removeprefix('https://')}:443",
                error="",
            )
            for instance in config.instances
            for account in instance.accounts
            if account.channel == "matrix"
        )

    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_services", fake_check_signal_services)
    monkeypatch.setattr("TeeBotus.runtime.signal_runner.check_signal_accounts", fake_check_signal_accounts)
    monkeypatch.setattr("TeeBotus.runtime.matrix_runner.check_matrix_homeservers", fake_check_matrix_homeservers)

    assert bot.main(["--runtime-status", "--channels", "signal,matrix"]) == 0

    captured = capsys.readouterr()
    assert "signal_service=Demo/signal:2 target=127.0.0.1:8081 status=reachable" in captured.out
    assert "signal_account=Demo/signal:2 phone=+492 target=127.0.0.1:8081 status=registered" in captured.out
    assert "matrix_homeserver=Demo/matrix:2 target=matrix-b.example:443 status=reachable" in captured.out
    assert "matrix_account=Demo/matrix:2 target=matrix-b.example:443 status=configured user_id=configured" in captured.out


def test_runtime_status_reports_requested_matrix_without_config(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    demo_dir = instances_dir / "Demo"
    demo_dir.mkdir(parents=True)
    (demo_dir / "Bot_Verhalten.md").write_text("", encoding="utf-8")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")

    assert bot.main(["--runtime-status", "--channels", "matrix"]) == 0

    captured = capsys.readouterr()
    assert "runtime_slot=Demo/matrix status=not_configured reason=missing_matrix_credentials" in captured.out
    assert "structured_decision=Demo/matrix status=not_applicable reason=no_runtime_slot" in captured.out


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


def test_runtime_status_keeps_safe_key_metadata_visible() -> None:
    bot = importlib.import_module("TeeBotus.bot")

    sanitized = bot._sanitize_status_text(
        "llm_route=bibliothekar_answer api_key_env=GEMINI_API_KEY api_key_ring=3 "
        "api_key_instances=2/3 fallback_api_key=missing api_key=plain-secret"
    )

    assert "api_key_env=GEMINI_API_KEY" in sanitized
    assert "api_key_ring=3" in sanitized
    assert "api_key_instances=2/3" in sanitized
    assert "fallback_api_key=missing" in sanitized
    assert "api_key=<redacted>" in sanitized
    assert "plain-secret" not in sanitized


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


def test_bot_main_rejects_unknown_startup_args_before_runtime_start(monkeypatch) -> None:
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


def test_channels_rejects_option_like_missing_value_before_runtime_start(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setattr(bot, "_run_telegram_runtime", lambda config: (_ for _ in ()).throw(AssertionError("runtime started")))

    assert bot.main(["--channels", "--definitely-not-runtime-status"]) == 2

    captured = capsys.readouterr()
    assert "Missing value for --channels." in captured.err


def test_runtime_status_rejects_missing_channels_value_without_system_exit(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)

    assert bot.main(["--runtime-status", "--channels"]) == 2

    captured = capsys.readouterr()
    assert "missing value for --channels" in captured.err


def test_runtime_status_rejects_unknown_option_with_generic_runtime_wording(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)

    assert bot.main(["--runtime-status", "--unknown"]) == 2

    captured = capsys.readouterr()
    assert "unsupported runtime option(s): --unknown" in captured.err
    assert "runtime-status option" not in captured.err


def test_empty_channels_equals_rejected_before_runtime_start(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setattr(bot, "_run_telegram_runtime", lambda config: calls.append(config) or 0)

    assert bot.main(["--channels="]) == 2

    captured = capsys.readouterr()
    assert "empty --channels value" in captured.err
    assert calls == []


def test_duplicate_channels_option_rejected_before_runtime_start(monkeypatch, capsys) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "Demo")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setattr(bot, "_run_telegram_runtime", lambda config: calls.append(config) or 0)

    assert bot.main(["--channels", "telegram", "--channels=signal"]) == 2

    captured = capsys.readouterr()
    assert "duplicate --channels option" in captured.err
    assert calls == []


def test_explicit_missing_instance_rejected_before_runtime_start(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.setenv("TEEBOTUS_INSTANCES_DIR", str(tmp_path / "instances"))
    monkeypatch.setenv("TEEBOTUS_INSTANCE", "MissingBot")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_MISSINGBOT", "telegram-token")
    monkeypatch.setattr(bot, "_run_telegram_runtime", lambda config: calls.append(config) or 0)

    assert bot.main(["--channels", "telegram"]) == 2

    captured = capsys.readouterr()
    assert "MissingBot ist explizit angefordert" in captured.err
    assert "Bot_Verhalten.md existiert nicht" in captured.err
    assert calls == []


def test_channels_signal_without_config_fails_clearly(monkeypatch, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    _configure_demo_instance(monkeypatch, tmp_path)
    monkeypatch.delenv("SIGNAL_BOT_SERVICE_DEMO", raising=False)
    monkeypatch.delenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", raising=False)
    assert bot.main(["--channels", "signal"]) == 2


def test_channels_signal_delegates_to_signal_runtime(monkeypatch, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    _configure_demo_instance(monkeypatch, tmp_path)
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_DEMO", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", "+491234")
    monkeypatch.setattr(bot, "_run_signal_runtime", lambda config: calls.append(config) or 0)

    assert bot.main(["--channels", "signal"]) == 0
    assert calls
    assert calls[0].instances[0].accounts[0].channel == "signal"


def test_channels_telegram_signal_starts_signal_before_telegram(monkeypatch, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    _configure_demo_instance(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_DEMO", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", "+491234")
    monkeypatch.setattr(bot, "_start_signal_runtime_background", lambda config: calls.append(("signal", config)) or 0)
    monkeypatch.setattr(bot, "_run_telegram_runtime", lambda config: calls.append(("telegram", config)) or 0)

    assert bot.main(["--channels", "telegram,signal"]) == 0
    assert [call[0] for call in calls] == ["signal", "telegram"]


def test_explicit_channels_telegram_signal_without_signal_config_fails_before_telegram(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    _configure_demo_instance(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.delenv("SIGNAL_BOT_SERVICE_DEMO", raising=False)
    monkeypatch.delenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", raising=False)
    monkeypatch.setattr(bot, "_run_telegram_runtime", lambda config: calls.append(("telegram", config)) or 0)

    assert bot.main(["--channels", "telegram,signal"]) == 2

    captured = capsys.readouterr()
    assert "Signal ist angefordert" in captured.err
    assert calls == []


def test_explicit_missing_channel_error_precedes_account_storage_preflight(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    _configure_demo_instance(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.delenv("SIGNAL_BOT_SERVICE_DEMO", raising=False)
    monkeypatch.delenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", raising=False)
    monkeypatch.setattr(
        "TeeBotus.core.status.account_secret_health_lines",
        lambda *, instance_name, project_root: [
            f"account_crypto={instance_name} status=broken mapping=present memory=missing_required keyring=broken"
        ],
    )
    monkeypatch.setattr("TeeBotus.core.status.account_memory_index_health_lines", lambda *, instance_name, project_root: [])
    monkeypatch.setattr(bot, "_run_telegram_runtime", lambda config: calls.append(config) or 0)

    assert bot.main(["--channels", "telegram,signal"]) == 2

    captured = capsys.readouterr()
    assert "Signal ist angefordert" in captured.err
    assert "account storage preflight failed" not in captured.err
    assert calls == []


def test_env_channels_telegram_signal_without_signal_config_fails_before_telegram(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    _configure_demo_instance(monkeypatch, tmp_path)
    monkeypatch.setenv("TEEBOTUS_CHANNELS", "telegram,signal")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.delenv("SIGNAL_BOT_SERVICE_DEMO", raising=False)
    monkeypatch.delenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", raising=False)
    monkeypatch.setattr(bot, "_run_telegram_runtime", lambda config: calls.append(("telegram", config)) or 0)

    assert bot.main([]) == 2

    captured = capsys.readouterr()
    assert "Signal ist angefordert" in captured.err
    assert calls == []


def test_default_auto_channels_keep_telegram_only_start_tolerant(monkeypatch, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.delenv("TEEBOTUS_CHANNELS", raising=False)
    _configure_demo_instance(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.delenv("SIGNAL_BOT_SERVICE_DEMO", raising=False)
    monkeypatch.delenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", raising=False)
    monkeypatch.delenv("MATRIX_BOT_HOMESERVER_DEMO", raising=False)
    monkeypatch.delenv("MATRIX_BOT_USER_ID_DEMO", raising=False)
    monkeypatch.delenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", raising=False)
    monkeypatch.setattr(bot, "_run_telegram_runtime", lambda config: calls.append(("telegram", config)) or 0)

    assert bot.main([]) == 0
    assert [call[0] for call in calls] == ["telegram"]


def test_default_auto_channels_report_missing_telegram_before_preflight(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.delenv("TEEBOTUS_CHANNELS", raising=False)
    _configure_demo_instance(monkeypatch, tmp_path)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_DEMO", raising=False)
    monkeypatch.delenv("SIGNAL_BOT_SERVICE_DEMO", raising=False)
    monkeypatch.delenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", raising=False)
    monkeypatch.delenv("MATRIX_BOT_HOMESERVER_DEMO", raising=False)
    monkeypatch.delenv("MATRIX_BOT_USER_ID_DEMO", raising=False)
    monkeypatch.delenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", raising=False)
    monkeypatch.setattr(
        "TeeBotus.core.status.account_secret_health_lines",
        lambda *, instance_name, project_root: [
            f"account_crypto={instance_name} status=broken mapping=present memory=missing_required keyring=broken"
        ],
    )
    monkeypatch.setattr("TeeBotus.core.status.account_memory_index_health_lines", lambda *, instance_name, project_root: [])
    monkeypatch.setattr(bot, "_run_telegram_runtime", lambda config: calls.append(("telegram", config)) or 0)

    assert bot.main([]) == 2

    captured = capsys.readouterr()
    assert "Telegram ist angefordert" in captured.err
    assert "account storage preflight failed" not in captured.err
    assert calls == []


def test_default_auto_channels_run_signal_blocking_when_telegram_is_unconfigured(monkeypatch, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.delenv("TEEBOTUS_CHANNELS", raising=False)
    _configure_demo_instance(monkeypatch, tmp_path)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_DEMO", raising=False)
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_DEMO", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", "+491234")
    monkeypatch.delenv("MATRIX_BOT_HOMESERVER_DEMO", raising=False)
    monkeypatch.delenv("MATRIX_BOT_USER_ID_DEMO", raising=False)
    monkeypatch.delenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", raising=False)
    monkeypatch.setattr(bot, "_start_signal_runtime_background", lambda config: calls.append(("signal-bg", config)) or 0)
    monkeypatch.setattr(bot, "_run_signal_runtime", lambda config: calls.append(("signal", config)) or 0)
    monkeypatch.setattr(bot, "_run_telegram_runtime", lambda config: calls.append(("telegram", config)) or 0)

    assert bot.main([]) == 0
    assert [call[0] for call in calls] == ["signal"]
    assert calls[0][1].channels == ("signal",)
    assert tuple(account.channel for instance in calls[0][1].instances for account in instance.accounts) == ("signal",)


def test_default_auto_channels_run_signal_preflight_on_narrowed_config(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    refresh_calls = []
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.delenv("TEEBOTUS_CHANNELS", raising=False)
    _configure_demo_instance(monkeypatch, tmp_path)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_DEMO", raising=False)
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_DEMO", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", "+491234")
    monkeypatch.delenv("MATRIX_BOT_HOMESERVER_DEMO", raising=False)
    monkeypatch.delenv("MATRIX_BOT_USER_ID_DEMO", raising=False)
    monkeypatch.delenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", raising=False)
    monkeypatch.setattr(
        "TeeBotus.core.status.account_secret_health_lines",
        lambda *, instance_name, project_root: [
            f"account_crypto={instance_name} status=broken mapping=present memory=missing_required keyring=broken"
        ],
    )
    monkeypatch.setattr("TeeBotus.core.status.account_memory_index_health_lines", lambda *, instance_name, project_root: [])
    monkeypatch.setattr(bot, "_start_gemini_free_tier_limit_refresh", lambda config: refresh_calls.append(config))
    monkeypatch.setattr(bot, "_run_signal_runtime", lambda config: calls.append(("signal", config)) or 0)

    assert bot.main([]) == 2

    captured = capsys.readouterr()
    assert "TeeBotus account storage preflight failed" in captured.err
    assert "Diagnose: python3 -m TeeBotus --runtime-status --channels signal" in captured.err
    assert "--channels telegram,signal,matrix" not in captured.err
    assert calls == []
    assert refresh_calls == []


def test_default_auto_channels_signal_fallback_preflight_skips_empty_instances(monkeypatch, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    instances_dir = tmp_path / "instances"
    for name in ("SignalBot", "TelegramOnly"):
        instance_dir = instances_dir / name
        instance_dir.mkdir(parents=True)
        (instance_dir / "Bot_Verhalten.md").write_text("# Bot\n", encoding="utf-8")
    calls = []
    refresh_calls = []
    checked_instances = []

    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.delenv("TEEBOTUS_CHANNELS", raising=False)
    monkeypatch.setenv("TEEBOTUS_INSTANCES_DIR", str(instances_dir))
    monkeypatch.setenv("TEEBOTUS_INSTANCES", "SignalBot,TelegramOnly")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_SIGNALBOT", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_TELEGRAMONLY", raising=False)
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_SIGNALBOT", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_SIGNALBOT", "+491234")
    monkeypatch.delenv("SIGNAL_BOT_SERVICE_TELEGRAMONLY", raising=False)
    monkeypatch.delenv("SIGNAL_BOT_PHONE_NUMBER_TELEGRAMONLY", raising=False)
    monkeypatch.delenv("MATRIX_BOT_HOMESERVER_SIGNALBOT", raising=False)
    monkeypatch.delenv("MATRIX_BOT_USER_ID_SIGNALBOT", raising=False)
    monkeypatch.delenv("MATRIX_BOT_ACCESS_TOKEN_SIGNALBOT", raising=False)
    monkeypatch.delenv("MATRIX_BOT_HOMESERVER_TELEGRAMONLY", raising=False)
    monkeypatch.delenv("MATRIX_BOT_USER_ID_TELEGRAMONLY", raising=False)
    monkeypatch.delenv("MATRIX_BOT_ACCESS_TOKEN_TELEGRAMONLY", raising=False)

    def secret_health(*, instance_name, project_root):
        checked_instances.append(instance_name)
        if instance_name == "TelegramOnly":
            return [
                "account_crypto=TelegramOnly status=broken mapping=present memory=missing_required keyring=broken"
            ]
        return []

    monkeypatch.setattr("TeeBotus.core.status.account_secret_health_lines", secret_health)
    monkeypatch.setattr("TeeBotus.core.status.account_memory_index_health_lines", lambda *, instance_name, project_root: [])
    monkeypatch.setattr(bot, "_start_gemini_free_tier_limit_refresh", lambda config: refresh_calls.append(config))
    monkeypatch.setattr(bot, "_run_signal_runtime", lambda config: calls.append(config) or 0)

    assert bot.main([]) == 0

    assert checked_instances == ["SignalBot"]
    assert calls
    assert calls[0].selected_instances == ("SignalBot",)
    assert tuple(instance.instance_name for instance in calls[0].instances) == ("SignalBot",)
    assert tuple(account.channel for instance in calls[0].instances for account in instance.accounts) == ("signal",)
    assert refresh_calls and refresh_calls[0] is calls[0]


def test_default_auto_channels_run_matrix_blocking_when_telegram_is_unconfigured(monkeypatch, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.delenv("TEEBOTUS_CHANNELS", raising=False)
    _configure_demo_instance(monkeypatch, tmp_path)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_DEMO", raising=False)
    monkeypatch.delenv("SIGNAL_BOT_SERVICE_DEMO", raising=False)
    monkeypatch.delenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", raising=False)
    monkeypatch.setenv("MATRIX_BOT_HOMESERVER_DEMO", "https://matrix.example")
    monkeypatch.setenv("MATRIX_BOT_USER_ID_DEMO", "@bot:example")
    monkeypatch.setenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", "matrix-token")
    monkeypatch.setattr(bot, "_start_matrix_runtime_background", lambda config: calls.append(("matrix-bg", config)) or 0)
    monkeypatch.setattr(bot, "_run_matrix_runtime", lambda config: calls.append(("matrix", config)) or 0)
    monkeypatch.setattr(bot, "_run_telegram_runtime", lambda config: calls.append(("telegram", config)) or 0)

    assert bot.main([]) == 0
    assert [call[0] for call in calls] == ["matrix"]
    assert calls[0][1].channels == ("matrix",)
    assert tuple(account.channel for instance in calls[0][1].instances for account in instance.accounts) == ("matrix",)


def test_default_auto_channels_reject_signal_matrix_without_telegram_before_background_start(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    monkeypatch.delenv("TEEBOTUS_CHANNELS", raising=False)
    _configure_demo_instance(monkeypatch, tmp_path)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_DEMO", raising=False)
    monkeypatch.setenv("SIGNAL_BOT_SERVICE_DEMO", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIGNAL_BOT_PHONE_NUMBER_DEMO", "+491234")
    monkeypatch.setenv("MATRIX_BOT_HOMESERVER_DEMO", "https://matrix.example")
    monkeypatch.setenv("MATRIX_BOT_USER_ID_DEMO", "@bot:example")
    monkeypatch.setenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", "matrix-token")
    monkeypatch.setattr(bot, "_start_signal_runtime_background", lambda config: calls.append(("signal-bg", config)) or 0)
    monkeypatch.setattr(bot, "_start_matrix_runtime_background", lambda config: calls.append(("matrix-bg", config)) or 0)
    monkeypatch.setattr(bot, "_run_signal_runtime", lambda config: calls.append(("signal", config)) or 0)
    monkeypatch.setattr(bot, "_run_matrix_runtime", lambda config: calls.append(("matrix", config)) or 0)

    assert bot.main([]) == 2

    captured = capsys.readouterr()
    assert "Mehrkanal-Start ohne Telegram" in captured.err
    assert calls == []


def test_channels_matrix_without_config_fails_clearly(monkeypatch, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    _configure_demo_instance(monkeypatch, tmp_path)
    monkeypatch.delenv("MATRIX_BOT_HOMESERVER_DEMO", raising=False)
    monkeypatch.delenv("MATRIX_BOT_USER_ID_DEMO", raising=False)
    monkeypatch.delenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", raising=False)
    assert bot.main(["--channels", "matrix"]) == 2


def test_channels_matrix_delegates_to_matrix_runtime(monkeypatch, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    _configure_demo_instance(monkeypatch, tmp_path)
    monkeypatch.setenv("MATRIX_BOT_HOMESERVER_DEMO", "https://matrix.example")
    monkeypatch.setenv("MATRIX_BOT_USER_ID_DEMO", "@bot:example")
    monkeypatch.setenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", "matrix-token")
    monkeypatch.setattr(bot, "_run_matrix_runtime", lambda config: calls.append(config) or 0)

    assert bot.main(["--channels", "matrix"]) == 0
    assert calls
    assert calls[0].instances[0].accounts[0].channel == "matrix"


def test_channels_telegram_matrix_starts_matrix_before_telegram(monkeypatch, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    _configure_demo_instance(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.setenv("MATRIX_BOT_HOMESERVER_DEMO", "https://matrix.example")
    monkeypatch.setenv("MATRIX_BOT_USER_ID_DEMO", "@bot:example")
    monkeypatch.setenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", "matrix-token")
    monkeypatch.setattr(bot, "_start_matrix_runtime_background", lambda config: calls.append(("matrix", config)) or 0)
    monkeypatch.setattr(bot, "_run_telegram_runtime", lambda config: calls.append(("telegram", config)) or 0)

    assert bot.main(["--channels", "telegram,matrix"]) == 0
    assert [call[0] for call in calls] == ["matrix", "telegram"]


def test_explicit_channels_telegram_matrix_without_matrix_config_fails_before_telegram(monkeypatch, capsys, tmp_path) -> None:
    bot = importlib.import_module("TeeBotus.bot")
    calls = []
    monkeypatch.setattr(bot, "_load_runtime_environment", lambda: None)
    _configure_demo_instance(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEMO", "telegram-token")
    monkeypatch.delenv("MATRIX_BOT_HOMESERVER_DEMO", raising=False)
    monkeypatch.delenv("MATRIX_BOT_USER_ID_DEMO", raising=False)
    monkeypatch.delenv("MATRIX_BOT_ACCESS_TOKEN_DEMO", raising=False)
    monkeypatch.setattr(bot, "_run_telegram_runtime", lambda config: calls.append(("telegram", config)) or 0)

    assert bot.main(["--channels", "telegram,matrix"]) == 2

    captured = capsys.readouterr()
    assert "Matrix ist angefordert" in captured.err
    assert calls == []


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
