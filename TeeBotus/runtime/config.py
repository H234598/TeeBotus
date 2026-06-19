from __future__ import annotations

import os
import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

DEFAULT_INSTANCE_NAME = "Bote_der_Wahrheit"
DEFAULT_INSTANCES_DIR = "instances"
DEFAULT_CHANNELS = ("telegram", "signal", "matrix")
SUPPORTED_CHANNELS = frozenset(DEFAULT_CHANNELS)
BACKGROUND_OPENAI_CHANNELS = frozenset({"PROACTIVE", "BACKGROUND"})


class RuntimeConfigError(RuntimeError):
    """Raised when TeeBotus runtime configuration is invalid."""


@dataclass(frozen=True)
class AccountRunConfig:
    instance_name: str
    channel: str
    slot: int
    label: str
    openai_api_key: str
    llm_enabled: str = ""
    llm_provider: str = ""
    llm_model: str = ""
    llm_fallback_models: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_profile: str = ""
    llm_purpose: str = ""
    llm_allow_remote_fallback: str = ""
    llm_timeout_seconds: str = ""
    llm_max_output_tokens: str = ""
    llm_temperature: str = ""
    llm_service_tier: str = ""
    telegram_token: str = ""
    signal_service: str = ""
    signal_phone_number: str = ""
    matrix_homeserver: str = ""
    matrix_user_id: str = ""
    matrix_access_token: str = ""
    matrix_device_id: str = ""


@dataclass(frozen=True)
class InstanceRunConfig:
    instance_name: str
    instruction_path: Path
    accounts: tuple[AccountRunConfig, ...]


@dataclass(frozen=True)
class RuntimeConfig:
    instances_dir: Path
    selected_instances: tuple[str, ...]
    channels: tuple[str, ...]
    instances: tuple[InstanceRunConfig, ...]


def normalize_instance_env_token(instance_name: str) -> str:
    token = "".join(char if char.isalnum() else "_" for char in str(instance_name).strip().upper())
    token = "_".join(part for part in token.split("_") if part)
    if not token:
        raise RuntimeConfigError("instance name must not be empty")
    return token


def parse_csv(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def parse_config_list(value: str | None, *, label: str) -> tuple[str, ...]:
    if value is None or not value.strip():
        return ()
    values = tuple(part.strip() for part in value.split(","))
    empty_items = [str(index) for index, part in enumerate(values, start=1) if not part]
    if empty_items:
        raise RuntimeConfigError(f"empty value in {label}; empty item(s): {', '.join(empty_items)}")
    return values


def parse_slot_csv(value: str | None, *, label: str) -> tuple[str, ...]:
    if value is None or not value.strip():
        return ()
    try:
        return parse_config_list(value, label=f"positional slot list {label}")
    except RuntimeConfigError as exc:
        raise RuntimeConfigError(
            str(exc).replace("empty item(s)", "empty slot(s)")
        ) from exc


def resolve_channels(env: Mapping[str, str] | None = None, cli_channels: str | None = None) -> tuple[str, ...]:
    source = cli_channels if cli_channels is not None else (os.environ if env is None else env).get("TEEBOTUS_CHANNELS", "auto")
    value = str(source or "auto").strip().casefold()
    if value in {"", "auto", "all"}:
        return DEFAULT_CHANNELS
    channels = parse_config_list(value, label="TEEBOTUS_CHANNELS")
    invalid = [channel for channel in channels if channel not in SUPPORTED_CHANNELS]
    if invalid:
        raise RuntimeConfigError(f"unsupported channel(s): {', '.join(invalid)}")
    return _validate_unique_values(channels, label="TEEBOTUS_CHANNELS")


def resolve_instances_dir(env: Mapping[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    for key in ("TEEBOTUS_INSTANCES_DIR", "TELEGRAM_BOT_INSTANCES_DIR"):
        value = str(source.get(key, "") or "").strip()
        if value:
            return Path(value)
    return Path(DEFAULT_INSTANCES_DIR)


def resolve_selected_instances(instances_dir: Path, env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    source = os.environ if env is None else env
    explicit = source.get("TEEBOTUS_INSTANCES") or source.get("TELEGRAM_BOT_INSTANCES")
    if explicit:
        selected = parse_csv(explicit)
        if _selected_instances_requests_discovery(selected):
            return _discover_selected_instances(instances_dir)
        if _selected_instances_contains_discovery_token(selected):
            raise RuntimeConfigError("TEEBOTUS_INSTANCES/TELEGRAM_BOT_INSTANCES cannot combine all/auto with explicit instance names")
        if selected:
            return selected
    single = source.get("TEEBOTUS_INSTANCE") or source.get("TELEGRAM_BOT_INSTANCE")
    if single and single.strip().casefold() not in {"", "all", "auto"}:
        return (single.strip(),)
    return _discover_selected_instances(instances_dir)


def _selected_instances_requests_discovery(selected: Sequence[str]) -> bool:
    return len(selected) == 1 and selected[0].strip().casefold() in {"all", "auto"}


def _selected_instances_contains_discovery_token(selected: Sequence[str]) -> bool:
    return any(value.strip().casefold() in {"all", "auto"} for value in selected)


def _discover_selected_instances(instances_dir: Path) -> tuple[str, ...]:
    if not instances_dir.exists():
        return ()
    return tuple(
        sorted(
            path.name
            for path in instances_dir.iterdir()
            if path.is_dir() and (path / "Bot_Verhalten.md").exists()
        )
    )


def resolve_openai_key(
    instance_name: str,
    channel: str,
    slot: int,
    env: Mapping[str, str] | None = None,
) -> str:
    source = os.environ if env is None else env
    instance_token = normalize_instance_env_token(instance_name)
    channel_token = str(channel).strip().upper()
    candidates = [
        f"OPENAI_API_KEY_{instance_token}_{channel_token}_{slot}",
        f"OPENAI_API_KEY_{instance_token}_{channel_token}",
        f"OPENAI_API_KEY_{instance_token}_{slot}",
        f"OPENAI_API_KEY_{instance_token}",
        "OPENAI_API_KEY",
    ]
    list_candidates = [
        f"OPENAI_API_KEYS_{instance_token}_{channel_token}",
        f"OPENAI_API_KEYS_{instance_token}",
    ]
    if channel_token != "BACKGROUND":
        if source.get(candidates[0]):
            return source[candidates[0]]
        resolved = _resolve_indexed_secret(source.get(list_candidates[0]), slot, label=list_candidates[0])
        if resolved:
            return resolved
        if source.get(candidates[1]):
            return source[candidates[1]]
    background_key = _resolve_background_openai_key(source, instance_name, instance_token, channel_token, slot)
    if background_key:
        return background_key
    if source.get(candidates[2]):
        return source[candidates[2]]
    resolved = _resolve_indexed_secret(source.get(list_candidates[1]), slot, label=list_candidates[1])
    if resolved:
        return resolved
    for key in candidates[3:]:
        if source.get(key):
            return source[key]
    return ""


def _resolve_background_openai_key(source: Mapping[str, str], instance_name: str, instance_token: str, channel_token: str, slot: int) -> str:
    if channel_token not in BACKGROUND_OPENAI_CHANNELS:
        return ""
    raw_instance = str(instance_name or "").strip()
    slot_candidates = [
        f"{raw_instance}_BACKGROUND_SERVICES_{slot}",
        f"{instance_token}_BACKGROUND_SERVICES_{slot}",
        f"OPENAI_API_KEY_{instance_token}_BACKGROUND_SERVICES_{slot}",
    ]
    candidates = [
        f"{raw_instance}_BACKGROUND_SERVICES",
        f"{instance_token}_BACKGROUND_SERVICES",
        f"OPENAI_API_KEY_{instance_token}_BACKGROUND_SERVICES",
    ]
    list_candidates = [
        f"OPENAI_API_KEYS_{instance_token}_BACKGROUND_SERVICES",
    ]
    for key in slot_candidates:
        if source.get(key):
            return source[key]
    resolved = _resolve_indexed_secret(source.get(list_candidates[0]), slot, label=list_candidates[0])
    if resolved:
        return resolved
    for key in candidates:
        if source.get(key):
            return source[key]
    return ""


def resolve_llm_setting(
    instance_name: str,
    channel: str,
    slot: int,
    name: str,
    env: Mapping[str, str] | None = None,
) -> str:
    source = os.environ if env is None else env
    setting = "_".join(part for part in str(name or "").strip().upper().split("_") if part)
    if not setting:
        raise RuntimeConfigError("LLM setting name must not be empty")
    instance_token = normalize_instance_env_token(instance_name)
    channel_token = str(channel).strip().upper()
    candidates = [
        f"TEEBOTUS_LLM_{setting}_{instance_token}_{channel_token}_{slot}",
        f"TEEBOTUS_LLM_{setting}_{instance_token}_{channel_token}",
        f"TEEBOTUS_LLM_{setting}_{instance_token}_{slot}",
        f"TEEBOTUS_LLM_{setting}_{instance_token}",
        f"TEEBOTUS_LLM_{setting}",
    ]
    for key in candidates:
        value = source.get(key, "").strip()
        if value:
            return value
    return ""


def _resolve_indexed_secret(value: str | None, slot: int, *, label: str) -> str:
    values = parse_slot_csv(value, label=label)
    index = slot - 1
    if index < 0 or index >= len(values):
        return ""
    return values[index]


def resolve_telegram_tokens(instance_name: str, env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    source = os.environ if env is None else env
    token = normalize_instance_env_token(instance_name)
    bulk_values = _nonempty(
        parse_slot_csv(source.get(f"TELEGRAM_BOT_TOKENS_{token}"), label=f"TELEGRAM_BOT_TOKENS_{token}")
    )
    single = source.get(f"TELEGRAM_BOT_TOKEN_{token}", "").strip()
    instance_values = _merge_numbered_values(
        source,
        (*bulk_values, single),
        f"TELEGRAM_BOT_TOKEN_{token}",
        label=f"TELEGRAM_BOT_TOKEN_{token}",
    )
    if instance_values:
        return _validate_unique_values(instance_values, label=f"TELEGRAM_BOT_TOKEN_{token}")
    global_values = _nonempty(
        (
            *parse_slot_csv(source.get("TELEGRAM_BOT_TOKENS"), label="TELEGRAM_BOT_TOKENS"),
            source.get("TELEGRAM_BOT_TOKEN", ""),
        )
    )
    return _validate_unique_values(global_values, label="TELEGRAM_BOT_TOKEN")


def resolve_signal_accounts(instance_name: str, env: Mapping[str, str] | None = None) -> tuple[tuple[str, str], ...]:
    source = os.environ if env is None else env
    token = normalize_instance_env_token(instance_name)
    services = parse_slot_csv(source.get(f"SIGNAL_BOT_SERVICES_{token}"), label=f"SIGNAL_BOT_SERVICES_{token}")
    phones = parse_slot_csv(source.get(f"SIGNAL_BOT_PHONE_NUMBERS_{token}"), label=f"SIGNAL_BOT_PHONE_NUMBERS_{token}")
    single_service = source.get(f"SIGNAL_BOT_SERVICE_{token}", "").strip()
    single_phone = source.get(f"SIGNAL_BOT_PHONE_NUMBER_{token}", "").strip()
    if bool(single_service) != bool(single_phone):
        raise RuntimeConfigError(f"Signal single service/phone must be configured together for instance {instance_name}")
    if single_service and single_phone:
        services = (*services, single_service)
        phones = (*phones, single_phone)
    if len(services) != len(phones):
        raise RuntimeConfigError(f"Signal service/phone slot mismatch for instance {instance_name}")
    pairs = tuple((service, phone) for service, phone in zip(services, phones) if service and phone)
    _validate_unique_values([service for service, _ in pairs], label=f"SIGNAL_BOT_SERVICES_{token}")
    _validate_unique_values([phone for _, phone in pairs], label=f"SIGNAL_BOT_PHONE_NUMBERS_{token}")
    return pairs


def resolve_matrix_accounts(instance_name: str, env: Mapping[str, str] | None = None) -> tuple[tuple[str, str, str, str], ...]:
    source = os.environ if env is None else env
    token = normalize_instance_env_token(instance_name)
    homeservers = parse_slot_csv(
        source.get(f"MATRIX_BOT_HOMESERVERS_{token}"), label=f"MATRIX_BOT_HOMESERVERS_{token}"
    )
    user_ids = parse_slot_csv(source.get(f"MATRIX_BOT_USER_IDS_{token}"), label=f"MATRIX_BOT_USER_IDS_{token}")
    access_tokens = parse_slot_csv(
        source.get(f"MATRIX_BOT_ACCESS_TOKENS_{token}"), label=f"MATRIX_BOT_ACCESS_TOKENS_{token}"
    )
    device_ids = parse_slot_csv(source.get(f"MATRIX_BOT_DEVICE_IDS_{token}"), label=f"MATRIX_BOT_DEVICE_IDS_{token}")
    single_homeserver = source.get(f"MATRIX_BOT_HOMESERVER_{token}", "").strip()
    single_user_id = source.get(f"MATRIX_BOT_USER_ID_{token}", "").strip()
    single_access_token = source.get(f"MATRIX_BOT_ACCESS_TOKEN_{token}", "").strip()
    single_device_id = source.get(f"MATRIX_BOT_DEVICE_ID_{token}", "").strip()
    required_singles = (single_homeserver, single_user_id, single_access_token)
    if any(required_singles) and not all(required_singles):
        raise RuntimeConfigError(f"Matrix single homeserver/user/access_token must be configured together for instance {instance_name}")
    if single_device_id and not all(required_singles):
        raise RuntimeConfigError(f"Matrix single device_id requires homeserver/user/access_token for instance {instance_name}")
    if single_homeserver and single_user_id and single_access_token:
        homeservers = (*homeservers, single_homeserver)
        user_ids = (*user_ids, single_user_id)
        access_tokens = (*access_tokens, single_access_token)
        device_ids = (*device_ids, single_device_id)
    if not (len(homeservers) == len(user_ids) == len(access_tokens)):
        raise RuntimeConfigError(f"Matrix homeserver/user/access_token slot mismatch for instance {instance_name}")
    if device_ids and len(device_ids) != len(homeservers):
        raise RuntimeConfigError(f"Matrix device_id slot mismatch for instance {instance_name}")
    if not device_ids:
        device_ids = tuple("" for _ in homeservers)
    pairs = tuple(
        (homeserver, user_id, access_token, device_id)
        for homeserver, user_id, access_token, device_id in zip(homeservers, user_ids, access_tokens, device_ids)
        if homeserver and user_id and access_token
    )
    _validate_unique_values([user_id for _, user_id, _, _ in pairs], label=f"MATRIX_BOT_USER_IDS_{token}")
    return pairs


def build_account_run_configs(
    instance_name: str,
    channels: Sequence[str],
    env: Mapping[str, str] | None = None,
) -> tuple[AccountRunConfig, ...]:
    accounts: list[AccountRunConfig] = []
    telegram_accounts: list[AccountRunConfig] = []
    if "telegram" in channels:
        for slot, token in enumerate(resolve_telegram_tokens(instance_name, env), start=1):
            openai_key = resolve_openai_key(instance_name, "telegram", slot, env)
            llm_kwargs = _resolve_llm_runtime_kwargs(instance_name, "telegram", slot, env)
            account = AccountRunConfig(
                instance_name=instance_name,
                channel="telegram",
                slot=slot,
                label=f"telegram:{slot}",
                telegram_token=token,
                openai_api_key=openai_key,
                **llm_kwargs,
            )
            accounts.append(account)
            telegram_accounts.append(account)
        _validate_telegram_openai_key_slots(instance_name, telegram_accounts)
    if "signal" in channels:
        for slot, (service, phone) in enumerate(resolve_signal_accounts(instance_name, env), start=1):
            openai_key = resolve_openai_key(instance_name, "signal", slot, env)
            llm_kwargs = _resolve_llm_runtime_kwargs(instance_name, "signal", slot, env)
            accounts.append(
                AccountRunConfig(
                    instance_name=instance_name,
                    channel="signal",
                    slot=slot,
                    label=f"signal:{slot}",
                    signal_service=service,
                    signal_phone_number=phone,
                    openai_api_key=openai_key,
                    **llm_kwargs,
                )
            )
    if "matrix" in channels:
        for slot, (homeserver, user_id, access_token, device_id) in enumerate(resolve_matrix_accounts(instance_name, env), start=1):
            openai_key = resolve_openai_key(instance_name, "matrix", slot, env)
            llm_kwargs = _resolve_llm_runtime_kwargs(instance_name, "matrix", slot, env)
            accounts.append(
                AccountRunConfig(
                    instance_name=instance_name,
                    channel="matrix",
                    slot=slot,
                    label=f"matrix:{slot}",
                    matrix_homeserver=homeserver,
                    matrix_user_id=user_id,
                    matrix_access_token=access_token,
                    matrix_device_id=device_id,
                    openai_api_key=openai_key,
                    **llm_kwargs,
                )
            )
    return tuple(accounts)


def _validate_telegram_openai_key_slots(instance_name: str, accounts: Sequence[AccountRunConfig]) -> None:
    if len(accounts) <= 1:
        return
    missing = [str(account.slot) for account in accounts if not str(account.openai_api_key or "").strip()]
    if missing:
        token = normalize_instance_env_token(instance_name)
        raise RuntimeConfigError(
            "Missing OpenAI API key for Telegram bot token slot(s): "
            f"{', '.join(missing)}. Set matching OPENAI_API_KEY_{token}[_N] or OPENAI_API_KEYS_{token}."
        )
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for account in accounts:
        previous_slot = seen.get(account.openai_api_key)
        if previous_slot is not None:
            duplicates.append(f"{previous_slot}/{account.slot}")
        else:
            seen[account.openai_api_key] = str(account.slot)
    if duplicates:
        raise RuntimeConfigError(
            "Multiple Telegram bot token slots for one instance must not share the same OpenAI API key. "
            f"Duplicate slot pairs: {', '.join(duplicates)}."
        )


def _resolve_llm_runtime_kwargs(
    instance_name: str,
    channel: str,
    slot: int,
    env: Mapping[str, str] | None,
) -> dict[str, str]:
    return {
        "llm_enabled": resolve_llm_setting(instance_name, channel, slot, "ENABLED", env),
        "llm_provider": resolve_llm_setting(instance_name, channel, slot, "PROVIDER", env),
        "llm_model": resolve_llm_setting(instance_name, channel, slot, "MODEL", env),
        "llm_fallback_models": resolve_llm_setting(instance_name, channel, slot, "FALLBACK_MODELS", env),
        "llm_api_key": resolve_llm_setting(instance_name, channel, slot, "API_KEY", env),
        "llm_base_url": resolve_llm_setting(instance_name, channel, slot, "BASE_URL", env),
        "llm_profile": resolve_llm_setting(instance_name, channel, slot, "PROFILE", env),
        "llm_purpose": resolve_llm_setting(instance_name, channel, slot, "PURPOSE", env),
        "llm_allow_remote_fallback": resolve_llm_setting(instance_name, channel, slot, "ALLOW_REMOTE_FALLBACK", env),
        "llm_timeout_seconds": resolve_llm_setting(instance_name, channel, slot, "TIMEOUT_SECONDS", env),
        "llm_max_output_tokens": resolve_llm_setting(instance_name, channel, slot, "MAX_OUTPUT_TOKENS", env),
        "llm_temperature": resolve_llm_setting(instance_name, channel, slot, "TEMPERATURE", env),
        "llm_service_tier": resolve_llm_setting(instance_name, channel, slot, "SERVICE_TIER", env),
    }


def build_runtime_config(
    env: Mapping[str, str] | None = None,
    cli_channels: str | None = None,
) -> RuntimeConfig:
    source = os.environ if env is None else env
    instances_dir = resolve_instances_dir(source)
    channels = resolve_channels(source, cli_channels)
    selected_instances = resolve_selected_instances(instances_dir, source)
    instances = []
    for instance_name in selected_instances:
        accounts = build_account_run_configs(instance_name, channels, source)
        instances.append(
            InstanceRunConfig(
                instance_name=instance_name,
                instruction_path=instances_dir / instance_name / "Bot_Verhalten.md",
                accounts=accounts,
            )
        )
    return RuntimeConfig(instances_dir, selected_instances, channels, tuple(instances))


def resolve_runtime_config(
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> RuntimeConfig:
    parser = argparse.ArgumentParser(prog="python3 -m TeeBotus --runtime-status", add_help=False)
    parser.add_argument("--channels", default=None)
    args, unknown = parser.parse_known_args(list(argv or ()))
    if unknown:
        raise RuntimeConfigError(f"unsupported runtime-status option(s): {', '.join(unknown)}")
    return build_runtime_config(env=env, cli_channels=args.channels)


def _merge_numbered_values(
    source: Mapping[str, str],
    base_values: Sequence[str],
    prefix: str,
    *,
    label: str,
) -> tuple[str, ...]:
    values = list(_nonempty(base_values))
    for index, value in _numbered_items(source, prefix):
        if index < 1:
            continue
        if index <= len(values):
            existing = values[index - 1]
            if existing == value:
                continue
            raise RuntimeConfigError(
                f"{label}_{index} conflicts with already configured slot {index}; "
                "use either the positional list value or the numbered value for that slot"
            )
        next_slot = len(values) + 1
        if index > next_slot:
            missing = ", ".join(str(slot) for slot in range(next_slot, index))
            raise RuntimeConfigError(f"{label}_{index} leaves missing numbered slot(s): {missing}")
        values.append(value)
    return tuple(values)


def _numbered_items(source: Mapping[str, str], prefix: str) -> tuple[tuple[int, str], ...]:
    key_prefix = f"{prefix}_"
    items: list[tuple[int, str]] = []
    for key, raw_value in source.items():
        if not key.startswith(key_prefix):
            continue
        suffix = key[len(key_prefix) :]
        value = str(raw_value or "").strip()
        if suffix.isdigit() and value:
            items.append((int(suffix), value))
    return tuple(sorted(items))


def _nonempty(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(str(value or "").strip() for value in values if str(value or "").strip())


def _validate_unique_values(values: Sequence[str], *, label: str) -> tuple[str, ...]:
    result = tuple(values)
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in result:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    if duplicates:
        raise RuntimeConfigError(f"duplicate values in {label}; duplicate adapter tokens would corrupt slot-to-key mapping")
    return result
