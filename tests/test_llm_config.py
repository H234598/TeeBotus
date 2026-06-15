from __future__ import annotations

from TeeBotus.instructions import parse_instructions
from TeeBotus.runtime.config import build_runtime_config, resolve_llm_setting


def test_plan2_llm_config_acceptance_covers_instructions_and_runtime_env(tmp_path) -> None:
    instructions = parse_instructions(
        """
        ## LLM
        - enabled: ja
        - provider: ollama
        - model: llama3.1:8b
        - profile: local_ollama
        - base_url: http://127.0.0.1:11434
        - fallback_models: groq/llama-3.3-70b-versatile
        - timeout_seconds: 180
        - max_tokens: 700
        - temperature: 0.4
        """
    )

    assert instructions.llm_provider == "ollama"
    assert instructions.llm_enabled is True
    assert instructions.llm_model == "llama3.1:8b"
    assert instructions.llm_profile == "local_ollama"
    assert instructions.llm_base_url == "http://127.0.0.1:11434"
    assert instructions.llm_fallback_models == ("groq/llama-3.3-70b-versatile",)
    assert instructions.llm_timeout_seconds == 180
    assert instructions.llm_max_output_tokens == 700
    assert instructions.llm_temperature == 0.4

    instances_dir = tmp_path / "instances"
    (instances_dir / "Demo").mkdir(parents=True)
    (instances_dir / "Demo" / "Bot_Verhalten.md").write_text("# Demo\n", encoding="utf-8")
    env = {
        "TELEGRAM_BOT_INSTANCES_DIR": str(instances_dir),
        "TEEBOTUS_INSTANCE": "Demo",
        "TEEBOTUS_CHANNELS": "telegram",
        "TELEGRAM_BOT_TOKEN_DEMO": "telegram-token",
        "TEEBOTUS_LLM_ENABLED_DEMO": "false",
        "TEEBOTUS_LLM_PROVIDER_DEMO": "ollama",
        "TEEBOTUS_LLM_MODEL_DEMO": "llama3.1:8b",
        "TEEBOTUS_LLM_PROFILE_DEMO": "local_ollama",
        "TEEBOTUS_LLM_API_KEY_DEMO": "runtime-key",
        "TEEBOTUS_LLM_BASE_URL_DEMO": "http://127.0.0.1:11434",
    }

    assert resolve_llm_setting("Demo", "telegram", 1, "PROFILE", env) == "local_ollama"
    config = build_runtime_config(env)
    account = config.instances[0].accounts[0]

    assert account.llm_provider == "ollama"
    assert account.llm_enabled == "false"
    assert account.llm_model == "llama3.1:8b"
    assert account.llm_profile == "local_ollama"
    assert account.llm_api_key == "runtime-key"
    assert account.llm_base_url == "http://127.0.0.1:11434"
