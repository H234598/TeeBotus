from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from TeeBotus.adapters import telegram_runtime
from TeeBotus.instructions import InstructionStore
from TeeBotus.openai_client import OpenAIClient
from TeeBotus.runtime.accounts import AccountStore, InstanceSecretProvider, SecretToolInstanceSecretProvider
from TeeBotus.runtime.bibliothekar_service import BibliothekarService
from TeeBotus.runtime.config import AccountRunConfig, RuntimeConfig
from TeeBotus.runtime.llm_factory import build_runtime_text_llm_client
from TeeBotus.runtime.message_tracking import MessageTracker
from TeeBotus.runtime.state import RuntimeStateStore
from TeeBotus.runtime.working_memory import WorkingMemoryStore

LOGGER = logging.getLogger("TeeBotus.telegram")


class TelegramRuntimeError(RuntimeError):
    """Raised when the Telegram runtime cannot be started."""


@dataclass(frozen=True)
class TelegramAccountHealth:
    account: AccountRunConfig
    ok: bool
    error: str = ""


class TelegramRuntimeBridge:
    def __init__(
        self,
        *,
        run_config: AccountRunConfig,
        api: Any,
        instances_dir: str | Path,
        secret_provider: InstanceSecretProvider | None = None,
        youtube_job_runner: Any | None = None,
        bot_identity: Any | None = None,
    ) -> None:
        if run_config.channel != "telegram":
            raise TelegramRuntimeError(f"unsupported Telegram account channel: {run_config.channel}")
        self.run_config = run_config
        self.api = api
        self.instances_dir = Path(instances_dir)
        instance_dir = self.instances_dir / run_config.instance_name
        data_dir = instance_dir / "data"
        resolved_secret_provider = secret_provider or SecretToolInstanceSecretProvider()
        self.instruction_store = InstructionStore(instance_dir / "Bot_Verhalten.md")
        self.account_store = AccountStore(data_dir / "accounts", run_config.instance_name, secret_provider=resolved_secret_provider)
        self.state_store = RuntimeStateStore(data_dir, instance_name=run_config.instance_name, secret_provider=resolved_secret_provider)
        self.message_tracker = MessageTracker(data_dir / "runtime" / "Sent_Message_Refs.json")
        self.openai_client = OpenAIClient(run_config.openai_api_key) if run_config.openai_api_key else None
        self.working_memory_store = WorkingMemoryStore(run_config.instance_name, instances_dir=self.instances_dir)
        self.working_memory_store.ensure()
        instructions = self.instruction_store.get()
        self.llm_client = build_runtime_text_llm_client(
            instructions=instructions,
            openai_client=self.openai_client,
            default_api_key=run_config.openai_api_key,
            enabled=run_config.llm_enabled,
            profile=run_config.llm_profile,
            purpose=run_config.llm_purpose,
            allow_remote_fallback=run_config.llm_allow_remote_fallback,
            provider=run_config.llm_provider,
            model=run_config.llm_model,
            fallback_models=run_config.llm_fallback_models,
            api_key=run_config.llm_api_key,
            api_base=run_config.llm_base_url,
            timeout=run_config.llm_timeout_seconds,
            max_tokens=run_config.llm_max_output_tokens,
            temperature=run_config.llm_temperature,
        )
        self.bibliothekar_store = BibliothekarService.from_instructions(run_config.instance_name, self.instances_dir, instructions)
        self.bot_identity = bot_identity or telegram_runtime._resolve_bot_identity(api)
        self.chat_state = telegram_runtime.ChatState(
            telegram_runtime._teladi_call_state_path(run_config.instance_name),
            run_config.instance_name,
        )
        self.context = telegram_runtime.build_telegram_runtime_context(
            api=api,
            instance_name=run_config.instance_name,
            adapter_slot=run_config.slot,
            instruction_store=self.instruction_store,
            account_store=self.account_store,
            state_store=self.state_store,
            message_tracker=self.message_tracker,
            openai_client=self.openai_client,
            working_memory_store=self.working_memory_store,
            bibliothekar_store=self.bibliothekar_store,
            youtube_job_runner=youtube_job_runner,
            bot_identity=self.bot_identity,
            llm_client=self.llm_client,
            llm_enabled_override=run_config.llm_enabled,
        )

    def run_polling(self, *, stop_event: threading.Event | None = None, poll_timeout: int | None = None, youtube_job_runner: Any | None = None) -> None:
        telegram_runtime.run_polling(
            self.api,
            self.instruction_store,
            self.run_config.instance_name,
            stop_event=stop_event,
            poll_timeout=poll_timeout or telegram_runtime.MULTI_BOT_POLL_TIMEOUT_SECONDS,
            token_label=str(self.run_config.slot),
            openai_api_key=self.run_config.openai_api_key,
            bot_identity=self.bot_identity,
            youtube_job_runner=youtube_job_runner,
            runtime_context=self.context,
            chat_state=self.chat_state,
        )


def check_telegram_accounts(config: RuntimeConfig) -> tuple[TelegramAccountHealth, ...]:
    seen_tokens: dict[str, str] = {}
    health: list[TelegramAccountHealth] = []
    for account in _telegram_accounts(config):
        if not account.telegram_token:
            health.append(TelegramAccountHealth(account=account, ok=False, error="missing Telegram bot token"))
            continue
        label = f"{account.instance_name}/{account.label}"
        previous_label = seen_tokens.get(account.telegram_token)
        if previous_label is not None:
            health.append(TelegramAccountHealth(account=account, ok=False, error=f"duplicate token with {previous_label}"))
            continue
        seen_tokens[account.telegram_token] = label
        health.append(TelegramAccountHealth(account=account, ok=True))
    return tuple(health)


def build_telegram_instance_configs(config: RuntimeConfig) -> tuple[telegram_runtime.InstanceRunConfig, ...]:
    instance_configs: list[telegram_runtime.InstanceRunConfig] = []
    for instance in config.instances:
        token_configs = tuple(
            telegram_runtime.BotTokenConfig(
                label=account.label,
                token=account.telegram_token,
                openai_api_key=account.openai_api_key,
            )
            for account in instance.accounts
            if account.channel == "telegram" and account.telegram_token
        )
        if not token_configs:
            continue
        instance_configs.append(
            telegram_runtime.InstanceRunConfig(
                instance_name=instance.instance_name,
                instruction_path=str(Path(instance.instruction_path)),
                token_configs=token_configs,
            )
        )
    return tuple(instance_configs)


def start_telegram_accounts(config: RuntimeConfig) -> int:
    return run_telegram_accounts(config)


def start_telegram_accounts_in_background(config: RuntimeConfig) -> list[threading.Thread]:
    thread = threading.Thread(
        target=run_telegram_accounts,
        args=(config,),
        name="teebotus-telegram-runtime",
        daemon=True,
    )
    thread.start()
    return [thread]


def run_telegram_accounts(config: RuntimeConfig) -> int:
    instance_configs = build_telegram_instance_configs(config)
    if not instance_configs:
        raise TelegramRuntimeError("Telegram ist angefordert, aber kein TELEGRAM_BOT_TOKEN_<INSTANCE> ist konfiguriert.")
    duplicate_error = _duplicate_telegram_token_error(instance_configs)
    if duplicate_error:
        raise TelegramRuntimeError(duplicate_error)
    LOGGER.info(
        "Starting Telegram runtime slot for %s configured instance(s).",
        len(instance_configs),
    )
    _run_telegram_polling_bridges(config, instance_configs)
    return 0


def _run_telegram_polling_bridges(
    config: RuntimeConfig,
    instance_configs: tuple[telegram_runtime.InstanceRunConfig, ...],
) -> None:
    stop_event = threading.Event()
    threads: list[threading.Thread] = []
    youtube_job_runner = telegram_runtime.YouTubeTranscriptionJobRunner()
    telegram_runtime._notify_recent_users_for_current_version(list(instance_configs))
    try:
        for account in _telegram_accounts(config):
            bridge = TelegramRuntimeBridge(
                run_config=account,
                api=telegram_runtime.TelegramAPI(account.telegram_token),
                instances_dir=config.instances_dir,
                youtube_job_runner=youtube_job_runner,
            )
            thread = threading.Thread(
                target=bridge.run_polling,
                kwargs={
                    "stop_event": stop_event,
                    "poll_timeout": telegram_runtime.MULTI_BOT_POLL_TIMEOUT_SECONDS,
                    "youtube_job_runner": youtube_job_runner,
                },
                name=f"telegram-bot-{account.instance_name}-{account.label}",
                daemon=True,
            )
            threads.append(thread)
            thread.start()
        while any(thread.is_alive() for thread in threads):
            for thread in threads:
                thread.join(timeout=0.5)
    except KeyboardInterrupt:
        LOGGER.info("Stopping %s Telegram bot token slots.", len(threads))
        stop_event.set()
        for thread in threads:
            thread.join(timeout=telegram_runtime.MULTI_BOT_POLL_TIMEOUT_SECONDS + 1)
    finally:
        youtube_job_runner.shutdown(wait=False)


def _telegram_accounts(config: RuntimeConfig) -> tuple[AccountRunConfig, ...]:
    return tuple(account for instance in config.instances for account in instance.accounts if account.channel == "telegram")


def _duplicate_telegram_token_error(instance_configs: tuple[telegram_runtime.InstanceRunConfig, ...]) -> str:
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for instance_config in instance_configs:
        for token_config in instance_config.token_configs:
            label = f"{instance_config.instance_name}:{token_config.label}"
            previous_label = seen.get(token_config.token)
            if previous_label is None:
                seen[token_config.token] = label
            else:
                duplicates.append(f"{previous_label} / {label}")
    if not duplicates:
        return ""
    return (
        "Duplicate Telegram bot token configured across bot slots. "
        "Each Telegram name needs its own BotFather token. Duplicate slot pairs: "
        + ", ".join(duplicates)
    )


__all__ = [
    "TelegramAccountHealth",
    "TelegramRuntimeBridge",
    "TelegramRuntimeError",
    "build_telegram_instance_configs",
    "check_telegram_accounts",
    "run_telegram_accounts",
    "start_telegram_accounts",
    "start_telegram_accounts_in_background",
]
