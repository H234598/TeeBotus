from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from TeeBotus import __version__
from TeeBotus.adapters import telegram_runtime
from TeeBotus.core.version_notifications import notify_recent_telegram_users_for_version
from TeeBotus.instructions import InstructionStore
from TeeBotus.openai_client import OpenAIClient
from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, InstanceSecretProvider, SecretToolInstanceSecretProvider
from TeeBotus.runtime.bibliothekar_service import BibliothekarService
from TeeBotus.runtime.config import AccountRunConfig, RuntimeConfig, resolve_llm_setting
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
        instruction_store: Any | None = None,
    ) -> None:
        if run_config.channel != "telegram":
            raise TelegramRuntimeError(f"unsupported Telegram account channel: {run_config.channel}")
        self.run_config = run_config
        self.api = api
        self.instances_dir = Path(instances_dir)
        instance_dir = self.instances_dir / run_config.instance_name
        data_dir = instance_dir / "data"
        resolved_secret_provider = secret_provider or SecretToolInstanceSecretProvider()
        self.instruction_store = instruction_store or InstructionStore(instance_dir / "Bot_Verhalten.md")
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
            data_dir / telegram_runtime.TELADI_CALL_STATE_FILENAME,
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


def build_telegram_runtime_bridge(
    *,
    api: Any,
    instance_name: str,
    adapter_slot: int,
    instances_dir: str | Path,
    instruction_store: Any | None = None,
    openai_api_key: str = "",
    bot_identity: Any | None = None,
    youtube_job_runner: Any | None = None,
    secret_provider: InstanceSecretProvider | None = None,
) -> TelegramRuntimeBridge:
    run_config = AccountRunConfig(
        instance_name=instance_name,
        channel="telegram",
        slot=adapter_slot,
        label=f"telegram:{adapter_slot}",
        telegram_token=getattr(api, "token", ""),
        openai_api_key=openai_api_key,
        llm_enabled=resolve_llm_setting(instance_name, "telegram", adapter_slot, "ENABLED"),
        llm_provider=resolve_llm_setting(instance_name, "telegram", adapter_slot, "PROVIDER"),
        llm_model=resolve_llm_setting(instance_name, "telegram", adapter_slot, "MODEL"),
        llm_fallback_models=resolve_llm_setting(instance_name, "telegram", adapter_slot, "FALLBACK_MODELS"),
        llm_api_key=resolve_llm_setting(instance_name, "telegram", adapter_slot, "API_KEY"),
        llm_base_url=resolve_llm_setting(instance_name, "telegram", adapter_slot, "BASE_URL"),
        llm_profile=resolve_llm_setting(instance_name, "telegram", adapter_slot, "PROFILE"),
        llm_purpose=resolve_llm_setting(instance_name, "telegram", adapter_slot, "PURPOSE"),
        llm_allow_remote_fallback=resolve_llm_setting(instance_name, "telegram", adapter_slot, "ALLOW_REMOTE_FALLBACK"),
        llm_timeout_seconds=resolve_llm_setting(instance_name, "telegram", adapter_slot, "TIMEOUT_SECONDS"),
        llm_max_output_tokens=resolve_llm_setting(instance_name, "telegram", adapter_slot, "MAX_OUTPUT_TOKENS"),
        llm_temperature=resolve_llm_setting(instance_name, "telegram", adapter_slot, "TEMPERATURE"),
    )
    return TelegramRuntimeBridge(
        run_config=run_config,
        api=api,
        instances_dir=instances_dir,
        secret_provider=secret_provider,
        youtube_job_runner=youtube_job_runner,
        bot_identity=bot_identity,
        instruction_store=instruction_store,
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
    _notify_recent_users_for_current_version(config, instance_configs)
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


def _notify_recent_users_for_current_version(
    config: RuntimeConfig,
    instance_configs: tuple[telegram_runtime.InstanceRunConfig, ...],
) -> None:
    instances_dir = Path(config.instances_dir)
    for instance_config in instance_configs:
        if not instance_config.token_configs:
            continue
        api = telegram_runtime.TelegramAPI(instance_config.token_configs[0].token)
        store = AccountStore(
            instances_dir / instance_config.instance_name / "data" / "accounts",
            instance_config.instance_name,
            secret_provider=SecretToolInstanceSecretProvider(),
            create_dirs=False,
        )
        try:
            count = notify_recent_telegram_users_for_version(
                version=__version__,
                instances_dir=instances_dir,
                instance_name=instance_config.instance_name,
                account_store=store,
                send_message=api.send_message,
                repo_root=telegram_runtime.PROJECT_ROOT,
                on_error=lambda recipient, exc: LOGGER.warning(
                    "Version notification failed version=%s instance=%s identity=%s: %s",
                    __version__,
                    instance_config.instance_name,
                    recipient.identity_key,
                    exc,
                ),
                on_skip=lambda reason: LOGGER.info(
                    "Version notification skipped version=%s instance=%s reason=%s.",
                    __version__,
                    instance_config.instance_name,
                    reason,
                ),
            )
        except (AccountStoreError, telegram_runtime.TelegramAPIError, telegram_runtime.TelegramNetworkError, OSError) as exc:
            LOGGER.warning("Version notification skipped for instance=%s: %s", instance_config.instance_name, exc)
            continue
        if count:
            LOGGER.info("Sent version notification version=%s instance=%s recipients=%s.", __version__, instance_config.instance_name, count)


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
    "build_telegram_runtime_bridge",
    "build_telegram_instance_configs",
    "check_telegram_accounts",
    "run_telegram_accounts",
    "start_telegram_accounts",
    "start_telegram_accounts_in_background",
]
