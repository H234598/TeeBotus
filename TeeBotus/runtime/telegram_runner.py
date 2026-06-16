from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from TeeBotus.adapters import telegram_runtime
from TeeBotus.runtime.config import AccountRunConfig, RuntimeConfig

LOGGER = logging.getLogger("TeeBotus.telegram")


class TelegramRuntimeError(RuntimeError):
    """Raised when the Telegram runtime cannot be started."""


@dataclass(frozen=True)
class TelegramAccountHealth:
    account: AccountRunConfig
    ok: bool
    error: str = ""


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
    telegram_runtime.run_polling_all(list(instance_configs))
    return 0


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
    "TelegramRuntimeError",
    "build_telegram_instance_configs",
    "check_telegram_accounts",
    "run_telegram_accounts",
    "start_telegram_accounts",
    "start_telegram_accounts_in_background",
]
