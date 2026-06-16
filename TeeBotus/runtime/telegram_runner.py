from __future__ import annotations

import logging
from pathlib import Path

from TeeBotus.adapters import telegram_runtime
from TeeBotus.runtime.config import RuntimeConfig

LOGGER = logging.getLogger("TeeBotus.telegram")


class TelegramRuntimeError(RuntimeError):
    """Raised when the Telegram runtime cannot be started."""


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


__all__ = ["TelegramRuntimeError", "build_telegram_instance_configs", "run_telegram_accounts"]
