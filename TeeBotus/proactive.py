from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from inspect import isawaitable
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, TOKEN_HEX_RE
from TeeBotus.adapters.telegram_runtime import TelegramAPI
from TeeBotus.instructions import load_instructions
from TeeBotus.openai_client import OpenAIClient
from TeeBotus.runtime.config import AccountRunConfig, build_runtime_config, resolve_llm_setting, resolve_openai_key
from TeeBotus.runtime.dotenv import load_dotenv_defaults, load_project_dotenv_for_instances, project_root_for_instances_dir
from TeeBotus.runtime.llm_factory import build_runtime_text_llm_client
from TeeBotus.runtime.message_tracking import MessageTracker
from TeeBotus.runtime.notification_loudness import queue_due_notification_loudness_prompts
from TeeBotus.runtime.maintenance import configure_runtime_logging
from TeeBotus.adapters.telegram_runtime import _load_runtime_config_defaults
from TeeBotus.runtime.proactive_backends import matrix_proactive_sender, signal_proactive_sender, telegram_proactive_sender
from TeeBotus.runtime.proactive_agent import (
    ProactiveSender,
    dispatch_due_proactive_outbox_items,
    due_proactive_outbox_items,
    expire_stale_proactive_outbox_items,
    proactive_agent_instance_enabled,
    proactive_policy_decision,
    run_proactive_llm_planner,
    run_proactive_reflection_planner,
    run_proactive_tool_agent,
    recover_stale_proactive_dispatching_items,
    should_run_proactive_model_planner,
)

PROACTIVE_LLM_INSTANCE_LIST_ENV = "TEEBOTUS_PROACTIVE_LLM_PLANNER_INSTANCES"
PROACTIVE_LLM_INSTANCE_FLAG_PREFIX = "TEEBOTUS_PROACTIVE_LLM_PLANNER_"
PROACTIVE_ROLE_LLM_CHANNELS = {
    "plan": "proactive_plan",
    "decision": "proactive_decision",
    "worker": "proactive_worker",
}
PROACTIVE_ROLE_OPENAI_CHANNELS = PROACTIVE_ROLE_LLM_CHANNELS
PROACTIVE_ROLE_LLM_SETTING_NAMES = (
    "ENABLED",
    "PROFILE",
    "PURPOSE",
    "PROVIDER",
    "MODEL",
    "FALLBACK_MODELS",
    "API_KEY",
    "BASE_URL",
    "ALLOW_REMOTE_FALLBACK",
    "TIMEOUT_SECONDS",
    "MAX_OUTPUT_TOKENS",
    "TEMPERATURE",
    "SERVICE_TIER",
)
MATRIX_LAZY_READY_TIMEOUT_SECONDS = 35.0
LOGGER = logging.getLogger("TeeBotus.proactive")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run TeeBotus Proactive Agent scheduler checks.")
    parser.add_argument("--instances-dir", default=str(PROJECT_ROOT / "instances"), help="TeeBotus instances directory.")
    parser.add_argument("--instance", action="append", default=[], help="Instance name to check. Can be repeated.")
    parser.add_argument("--dry-run", action="store_true", help="Do not send due items. Plain dry-run only inspects; --plan can still write planner output.")
    parser.add_argument("--dispatch", action="store_true", help="Dispatch due items using explicitly configured in-process senders.")
    parser.add_argument("--plan", action="store_true", help="Run the local reflection planner before due selection. This can write memory/outbox entries.")
    parser.add_argument("--llm-plan", action="store_true", help="Run the LLM planner before due selection. Requires --plan, the LLM instance gate, and an OpenAI key.")
    parser.add_argument("--tool-plan", action="store_true", help="Run the native tool-call planner before due selection. Requires --plan, the LLM instance gate, and an OpenAI key.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args(argv)
    if args.dry_run == args.dispatch:
        print("Use exactly one of --dry-run or --dispatch.", file=sys.stderr)
        return 2
    if args.llm_plan and not args.plan:
        print("--llm-plan requires --plan so LLM decisions cannot run as an accidental plain status check.", file=sys.stderr)
        return 2
    if args.tool_plan and not args.plan:
        print("--tool-plan requires --plan so tool-agent decisions cannot run as an accidental plain status check.", file=sys.stderr)
        return 2
    if args.llm_plan and args.tool_plan:
        print("Use only one model planner: --llm-plan or --tool-plan.", file=sys.stderr)
        return 2
    instances_dir = Path(args.instances_dir)
    project_root = project_root_for_instances_dir(instances_dir)
    load_project_dotenv_for_instances(instances_dir, environ=os.environ)
    _load_runtime_config_defaults(project_root / "ALL_BOTS_DEFAULT.md")
    configure_runtime_logging(level=os.getenv("TEEBOTUS_LOG_LEVEL") or os.getenv("LOG_LEVEL", "INFO"), tee_stdio=True)
    report = asyncio.run(
        run_proactive_agent_cycle(
            instances_dir=instances_dir,
            selected_instances=tuple(args.instance),
            dispatch=bool(args.dispatch),
            plan=bool(args.plan),
            llm_plan=bool(args.llm_plan),
            tool_plan=bool(args.tool_plan),
            sender_factory=runtime_sender_factory(instances_dir) if args.dispatch else None,
            llm_planner_factory=runtime_llm_planner_factory(instances_dir) if args.plan else None,
            planner_resolver=runtime_planner_resolver(),
        )
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_dry_run_report(report)
    return 0 if report["ok"] else 1


StoreFactory = Callable[[Path, str], AccountStore]
SenderFactory = Callable[[str, AccountStore], Mapping[str, ProactiveSender]]
MessageTrackerFactory = Callable[[Path, str], MessageTracker | None]
LLMPlannerFactory = Callable[[str, AccountStore, str], tuple[Any, Any] | None]
PlannerResolver = Callable[[Path], str]


def run_proactive_agent_dry_run(
    *,
    instances_dir: Path,
    selected_instances: Iterable[str] = (),
    env: Mapping[str, str] | None = None,
    store_factory: StoreFactory | None = None,
    now: datetime | None = None,
    plan: bool = False,
    llm_plan: bool = False,
    tool_plan: bool = False,
    llm_planner_factory: LLMPlannerFactory | None = None,
) -> dict[str, Any]:
    return asyncio.run(
        run_proactive_agent_cycle(
            instances_dir=instances_dir,
            selected_instances=selected_instances,
            env=env,
            store_factory=store_factory,
            now=now,
            dispatch=False,
            plan=plan,
            llm_plan=llm_plan,
            tool_plan=tool_plan,
            llm_planner_factory=llm_planner_factory,
        )
    )


def runtime_llm_planner_factory(instances_dir: Path, env: Mapping[str, str] | None = None) -> LLMPlannerFactory:
    return runtime_proactive_role_llm_factory(instances_dir, role="plan", env=env)


def runtime_proactive_role_llm_factory(instances_dir: Path, *, role: str, env: Mapping[str, str] | None = None) -> LLMPlannerFactory:
    source = os.environ if env is None else env
    normalized_role = _normalize_proactive_role(role)

    def factory(instance_name: str, _store: AccountStore, _account_id: str) -> tuple[Any, Any] | None:
        context = build_proactive_role_llm_context(instances_dir, instance_name, normalized_role, env=source)
        if context is None:
            return None
        return context

    return factory


def build_proactive_role_llm_context(
    instances_dir: Path,
    instance_name: str,
    role: str,
    *,
    env: Mapping[str, str] | None = None,
) -> tuple[Any, Any] | None:
    source = os.environ if env is None else env
    normalized_role = _normalize_proactive_role(role)
    instructions = load_instructions(instances_dir / instance_name / "Bot_Verhalten.md")
    role_openai_key = resolve_proactive_role_openai_key(instance_name, normalized_role, source)
    settings = resolve_proactive_role_llm_settings(instance_name, normalized_role, source)
    if not _proactive_role_llm_settings_configured(settings):
        if not role_openai_key:
            return None
        return OpenAIClient(role_openai_key), instructions
    channel = PROACTIVE_ROLE_LLM_CHANNELS[normalized_role]
    client = build_runtime_text_llm_client(
        instructions=instructions,
        openai_client=None,
        default_api_key=role_openai_key,
        enabled=settings["enabled"],
        profile=settings["profile"],
        purpose=settings["purpose"] or channel,
        allow_remote_fallback=settings["allow_remote_fallback"],
        provider=settings["provider"],
        model=settings["model"],
        fallback_models=settings["fallback_models"],
        api_key=settings["api_key"],
        api_base=settings["base_url"],
        timeout=settings["timeout_seconds"],
        temperature=settings["temperature"],
        max_tokens=settings["max_output_tokens"],
        service_tier=settings["service_tier"],
        gemini_key_scope=channel,
        env=source,
        instance_name=instance_name,
    )
    if client is None:
        return None
    return ProactiveRoleLLMClient(client, role=normalized_role, channel=channel), instructions


def resolve_proactive_role_llm_settings(instance_name: str, role: str, env: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if env is None else env
    normalized_role = _normalize_proactive_role(role)
    channel = PROACTIVE_ROLE_LLM_CHANNELS[normalized_role]
    return {
        name.casefold(): resolve_llm_setting(instance_name, channel, 1, name, source)
        for name in PROACTIVE_ROLE_LLM_SETTING_NAMES
    }


def resolve_proactive_role_openai_key(instance_name: str, role: str, env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    normalized_role = _normalize_proactive_role(role)
    channel = PROACTIVE_ROLE_OPENAI_CHANNELS.get(normalized_role)
    return resolve_openai_key(instance_name, channel, 1, source)


def _normalize_proactive_role(role: str) -> str:
    normalized_role = str(role or "").strip().casefold()
    if normalized_role not in PROACTIVE_ROLE_LLM_CHANNELS:
        raise ValueError(f"unsupported proactive LLM role: {role}")
    return normalized_role


def _proactive_role_llm_settings_configured(settings: Mapping[str, str]) -> bool:
    return any(str(settings.get(name.casefold()) or "").strip() for name in PROACTIVE_ROLE_LLM_SETTING_NAMES)


class ProactiveRoleLLMClient:
    def __init__(self, client: Any, *, role: str, channel: str) -> None:
        self.client = client
        self.proactive_role = role
        self.proactive_channel = channel
        self.provider = str(getattr(client, "provider", "") or "")
        self.model = str(getattr(client, "model", "") or "")
        self.capabilities = getattr(client, "capabilities", None)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.client, name)

    def create_reply(self, user_text: str, instructions: Any, previous_response_id: str | None = None) -> Any:
        create_reply = getattr(self.client, "create_reply")
        return create_reply(user_text, instructions, previous_response_id)

    def create_tool_calls(
        self,
        user_text: str,
        instructions: Any,
        tools: list[dict[str, Any]],
        previous_response_id: str | None = None,
    ) -> dict[str, Any]:
        create_tool_calls = getattr(self.client, "create_tool_calls", None)
        if callable(create_tool_calls):
            return create_tool_calls(user_text, instructions, tools, previous_response_id)
        prompt = "\n".join(
            [
                user_text,
                "",
                "Dieser LLM-Provider hat keinen nativen Tool-Call-Transport in dieser Route.",
                "Gib stattdessen exakt das JSON-Planungsschema aus dem Prompt zurueck; kein Markdown, kein Erklaertext.",
                "Tool-Definitionen nur als Referenz:",
                json.dumps(tools, ensure_ascii=False, sort_keys=True),
            ]
        )
        response = self.create_reply(prompt, instructions, previous_response_id)
        text = str(getattr(response, "text", response) or "").strip()
        return {"text": text, "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}


def runtime_planner_resolver() -> PlannerResolver:
    def resolver(instance_dir: Path) -> str:
        instructions = load_instructions(instance_dir / "Bot_Verhalten.md")
        planner = str(getattr(instructions, "proactive_model_planner", "") or "").strip().casefold()
        if planner in {"llm", "tool", "none"}:
            return planner
        return "tool"

    return resolver


def runtime_sender_factory(instances_dir: Path, env: Mapping[str, str] | None = None, *, channels: Iterable[str] | None = None) -> SenderFactory:
    source = os.environ if env is None else env
    requested_channels = _normalized_sender_channels(channels)
    config = build_runtime_config(env={**source, "TEEBOTUS_INSTANCES_DIR": str(instances_dir)})
    accounts_by_instance: dict[str, list[AccountRunConfig]] = {}
    for instance in config.instances:
        accounts_by_instance.setdefault(instance.instance_name, []).extend(instance.accounts)

    def factory(instance_name: str, _store: AccountStore) -> Mapping[str, ProactiveSender]:
        accounts = accounts_by_instance.get(instance_name, [])
        senders: dict[str, ProactiveSender] = {}
        if _sender_channel_requested("telegram", requested_channels):
            telegram_apis = {
                account.slot: TelegramAPI(account.telegram_token)
                for account in accounts
                if account.channel == "telegram" and account.telegram_token
            }
            if telegram_apis:
                senders["telegram"] = telegram_proactive_sender(telegram_apis)
        if _sender_channel_requested("signal", requested_channels):
            signal_bots = _signal_bots_for_accounts(accounts)
            if signal_bots:
                senders["signal"] = signal_proactive_sender(signal_bots)
        if _sender_channel_requested("matrix", requested_channels):
            matrix_clients = _matrix_clients_for_accounts(accounts)
            if matrix_clients:
                senders["matrix"] = matrix_proactive_sender(matrix_clients)
        return senders

    return factory


def _normalized_sender_channels(channels: Iterable[str] | None) -> frozenset[str] | None:
    if channels is None:
        return None
    return frozenset(str(channel or "").strip().casefold() for channel in channels if str(channel or "").strip())


def _sender_channel_requested(channel: str, requested_channels: frozenset[str] | None) -> bool:
    return requested_channels is None or channel in requested_channels


def _signal_bots_for_accounts(accounts: Iterable[AccountRunConfig]) -> dict[int, Any]:
    signal_accounts = [account for account in accounts if account.channel == "signal" and account.signal_service and account.signal_phone_number]
    if not signal_accounts:
        return {}
    from TeeBotus.runtime.signal_runner import _import_signalbot, _signalbot_config_kwargs

    signalbot = _import_signalbot()
    bots: dict[int, Any] = {}
    for account in signal_accounts:
        config = signalbot.Config(**_signalbot_config_kwargs(signalbot, account))
        bots[account.slot] = signalbot.SignalBot(config)
    return bots


def _matrix_clients_for_accounts(accounts: Iterable[AccountRunConfig]) -> dict[int, Any]:
    matrix_accounts = [
        account
        for account in accounts
        if account.channel == "matrix" and account.matrix_homeserver and account.matrix_user_id and account.matrix_access_token
    ]
    if not matrix_accounts:
        return {}
    from TeeBotus.runtime.matrix_runner import _import_niobot

    niobot = _import_niobot()
    return {account.slot: _LazyMatrixProactiveClient(niobot, account) for account in matrix_accounts}


class _LazyMatrixProactiveClient:
    def __init__(self, niobot: Any, account: AccountRunConfig) -> None:
        self._niobot = niobot
        self._account = account
        self._client: Any | None = None
        self._started = False
        self._lock: asyncio.Lock | None = None
        self._start_task: asyncio.Task[Any] | None = None
        self._ready_event: asyncio.Event | None = None

    @property
    def rooms(self) -> Any:
        return getattr(self._client, "rooms", {}) if self._client is not None else {}

    def room(self, room_id: str) -> Any | None:
        if self._client is None:
            return None
        room = getattr(self._client, "room", None)
        if not callable(room):
            return None
        return room(room_id)

    def __getattr__(self, name: str) -> Any:
        async def delegated(*args: Any, **kwargs: Any) -> Any:
            client = await self._ensure_started()
            target = getattr(client, name)
            result = target(*args, **kwargs)
            if isawaitable(result):
                return await result
            return result

        return delegated

    async def _ensure_started(self) -> Any:
        return await self.ensure_started()

    async def ensure_started(self) -> Any:
        if self._started and self._client is not None and not _matrix_start_task_failed(self._start_task):
            return self._client
        if _matrix_start_task_failed(self._start_task):
            self._reset_failed_start()
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._started and self._client is not None and not _matrix_start_task_failed(self._start_task):
                return self._client
            if _matrix_start_task_failed(self._start_task):
                self._reset_failed_start()
            client = self._niobot.NioBot(
                self._account.matrix_homeserver,
                self._account.matrix_user_id,
                device_id=self._account.matrix_device_id or "teebotus",
                command_prefix="/",
                global_message_type="m.text",
            )
            self._ready_event = asyncio.Event()
            _register_matrix_ready_event(client, self._ready_event)
            result = client.start(access_token=self._account.matrix_access_token)
            if isawaitable(result):
                self._start_task = asyncio.create_task(result, name=f"teebotus-proactive-matrix-{self._account.label}")
                self._start_task.add_done_callback(_log_matrix_start_task_failure)
            self._client = client
            self._started = True
            if self._start_task is not None:
                try:
                    await _wait_for_matrix_lazy_ready(client, self._ready_event, self._start_task, self._account.label)
                except Exception:
                    self._reset_failed_start()
                    raise
            return client

    def _reset_failed_start(self) -> None:
        self._client = None
        self._started = False
        self._start_task = None
        self._ready_event = None


def _register_matrix_ready_event(client: Any, ready_event: asyncio.Event) -> None:
    async def mark_ready(*_args: Any, **_kwargs: Any) -> None:
        ready_event.set()

    add_event_listener = getattr(client, "add_event_listener", None)
    if callable(add_event_listener):
        try:
            add_event_listener("ready", mark_ready)
            return
        except Exception:
            LOGGER.debug("Could not register nio-bot ready listener.", exc_info=True)


async def _wait_for_matrix_lazy_ready(client: Any, ready_event: asyncio.Event, start_task: asyncio.Task[Any], label: str) -> None:
    if start_task.done():
        start_task.result()
        return
    if _matrix_client_has_room_state(client):
        return
    ready_task = asyncio.create_task(ready_event.wait(), name=f"teebotus-proactive-matrix-ready-{label}")
    try:
        await asyncio.wait(
            {ready_task, start_task},
            timeout=MATRIX_LAZY_READY_TIMEOUT_SECONDS,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if ready_event.is_set() or _matrix_client_has_room_state(client):
            return
        if start_task.done():
            start_task.result()
            return
        LOGGER.warning(
            "Matrix proactive lazy client did not report ready within %.1fs for slot=%s; continuing with current room state.",
            MATRIX_LAZY_READY_TIMEOUT_SECONDS,
            label,
        )
    finally:
        if not ready_task.done():
            ready_task.cancel()


def _matrix_client_has_room_state(client: Any) -> bool:
    rooms = getattr(client, "rooms", None)
    return isinstance(rooms, dict) and bool(rooms)


def _matrix_start_task_failed(task: asyncio.Task[Any] | None) -> bool:
    if task is None or not task.done():
        return False
    if task.cancelled():
        return True
    try:
        task.result()
    except Exception:
        return True
    return False


def _log_matrix_start_task_failure(task: asyncio.Task[Any]) -> None:
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        LOGGER.exception("Matrix proactive lazy client stopped with an error.")


def _load_dotenv(path: Path) -> None:
    load_dotenv_defaults(path)


async def run_proactive_agent_cycle(
    *,
    instances_dir: Path,
    selected_instances: Iterable[str] = (),
    env: Mapping[str, str] | None = None,
    store_factory: StoreFactory | None = None,
    now: datetime | None = None,
    dispatch: bool = False,
    plan: bool = False,
    llm_plan: bool = False,
    tool_plan: bool = False,
    sender_factory: SenderFactory | None = None,
    message_tracker_factory: MessageTrackerFactory | None = None,
    llm_planner_factory: LLMPlannerFactory | None = None,
    planner_resolver: PlannerResolver | None = None,
) -> dict[str, Any]:
    if dispatch and sender_factory is None:
        raise ValueError("sender_factory is required when dispatch=True")
    if llm_plan and llm_planner_factory is None:
        raise ValueError("llm_planner_factory is required when llm_plan=True")
    if tool_plan and llm_planner_factory is None:
        raise ValueError("llm_planner_factory is required when tool_plan=True")
    if llm_plan and tool_plan:
        raise ValueError("llm_plan and tool_plan are mutually exclusive")
    resolved_now = now or datetime.now(timezone.utc)
    resolved_store_factory = store_factory or AccountStore
    instances: list[dict[str, Any]] = []
    for instance_dir in _instance_dirs(instances_dir, tuple(selected_instances)):
        instance_report: dict[str, Any] = {
            "instance": instance_dir.name,
            "enabled": proactive_agent_instance_enabled(instance_dir.name, env=env),
            "accounts": [],
        }
        if not instance_report["enabled"]:
            instance_report["skipped_reason"] = "instance_not_enabled"
            instances.append(instance_report)
            continue
        store = resolved_store_factory(instance_dir / "data" / "accounts", instance_dir.name)
        for account_dir in _account_dirs(store.accounts_dir):
            account_id = account_dir.name
            account_report: dict[str, Any] = {"account_id": account_id, "due_items": []}
            try:
                effective_llm_plan, effective_tool_plan = _effective_model_planners(
                    instance_dir,
                    plan=plan,
                    llm_plan=llm_plan,
                    tool_plan=tool_plan,
                    planner_resolver=planner_resolver,
                )
                if dispatch:
                    notification_prompt_ids = queue_due_notification_loudness_prompts(store, account_id, now=resolved_now)
                    if notification_prompt_ids:
                        account_report["notification_loudness_prompt_ids"] = list(notification_prompt_ids)
                if plan:
                    planning = run_proactive_reflection_planner(store, account_id, now=resolved_now)
                    account_report["planning"] = {
                        "account_id": planning.account_id,
                        "created_memory_ids": list(planning.created_memory_ids),
                        "queued_item_ids": list(planning.queued_item_ids),
                        "skipped_reason": planning.skipped_reason,
                    }
                model_planner_allowed = True
                model_planner_skip_reason = ""
                if effective_llm_plan or effective_tool_plan:
                    model_planner_allowed, model_planner_skip_reason = should_run_proactive_model_planner(store, account_id)
                if effective_llm_plan:
                    if not proactive_llm_planner_instance_enabled(instance_dir.name, env=env):
                        account_report["llm_planning"] = {"skipped_reason": "llm_planner_instance_not_enabled"}
                    elif not model_planner_allowed:
                        account_report["llm_planning"] = {"skipped_reason": f"model_planner_idle:{model_planner_skip_reason}"}
                    else:
                        planner_context = (llm_planner_factory or _missing_llm_planner_factory)(instance_dir.name, store, account_id)
                        if planner_context is None:
                            account_report["llm_planning"] = {**_proactive_llm_role_report(None, role="plan"), "skipped_reason": "llm_planner_unavailable"}
                        else:
                            openai_client, instructions = planner_context
                            llm_planning = run_proactive_llm_planner(
                                store,
                                account_id,
                                openai_client=openai_client,
                                instructions=instructions,
                                now=resolved_now,
                            )
                            account_report["llm_planning"] = {
                                "account_id": llm_planning.account_id,
                                **_proactive_llm_role_report(openai_client, role="plan"),
                                "created_memory_ids": list(llm_planning.created_memory_ids),
                                "queued_item_ids": list(llm_planning.queued_item_ids),
                                "errors": list(llm_planning.errors),
                                "audit_event_ids": list(llm_planning.audit_event_ids),
                            }
                if effective_tool_plan:
                    if not proactive_llm_planner_instance_enabled(instance_dir.name, env=env):
                        account_report["tool_planning"] = {"skipped_reason": "tool_planner_instance_not_enabled"}
                    elif not model_planner_allowed:
                        account_report["tool_planning"] = {"skipped_reason": f"model_planner_idle:{model_planner_skip_reason}"}
                    else:
                        planner_context = (llm_planner_factory or _missing_llm_planner_factory)(instance_dir.name, store, account_id)
                        if planner_context is None:
                            account_report["tool_planning"] = {**_proactive_llm_role_report(None, role="plan"), "skipped_reason": "tool_planner_unavailable"}
                        else:
                            openai_client, instructions = planner_context
                            tool_planning = run_proactive_tool_agent(
                                store,
                                account_id,
                                openai_client=openai_client,
                                instructions=instructions,
                                now=resolved_now,
                            )
                            account_report["tool_planning"] = {
                                "account_id": tool_planning.account_id,
                                **_proactive_llm_role_report(openai_client, role="plan"),
                                "created_memory_ids": list(tool_planning.created_memory_ids),
                                "queued_item_ids": list(tool_planning.queued_item_ids),
                                "errors": list(tool_planning.errors),
                                "audit_event_ids": list(tool_planning.audit_event_ids),
                            }
                if dispatch:
                    recovered_item_ids = recover_stale_proactive_dispatching_items(store, account_id, now=resolved_now)
                    if recovered_item_ids:
                        account_report["recovered_dispatching_item_ids"] = list(recovered_item_ids)
                    expired_item_ids = expire_stale_proactive_outbox_items(store, account_id, now=resolved_now)
                    if expired_item_ids:
                        account_report["expired_item_ids"] = list(expired_item_ids)
                items: list[dict[str, Any]] = []
                for item in due_proactive_outbox_items(store, account_id, now=resolved_now):
                    category = str(item.get("category") or "")
                    item_id = str(item.get("id") or "")
                    decision = proactive_policy_decision(store, account_id, category=category, now=resolved_now, exclude_item_id=item_id, item=item)
                    items.append(
                        {
                            "id": item_id,
                            "category": category,
                            "intent": str(item.get("intent") or ""),
                            "due_at": str(item.get("due_at") or ""),
                            "policy_allowed": decision.allowed,
                            "policy_reason": decision.reason,
                            "route": decision.route or item.get("route") or {},
                        }
                    )
                account_report["due_items"] = items
                if dispatch:
                    senders = dict((sender_factory or _missing_sender_factory)(instance_dir.name, store))
                    tracker = _message_tracker_for_instance(instance_dir, instance_dir.name, message_tracker_factory)
                    results = await dispatch_due_proactive_outbox_items(
                        store,
                        account_id,
                        senders=senders,
                        now=resolved_now,
                        message_tracker=tracker,
                        instance_name=instance_dir.name,
                    )
                    dispatch_rows = [
                        {
                            "account_id": result.account_id,
                            "item_id": result.item_id,
                            "status": result.status,
                            "reason": result.reason,
                            "channel": result.channel,
                            "message_ref": result.message_ref,
                        }
                        for result in results
                    ]
                    account_report["dispatch_results"] = dispatch_rows
                    append_dispatch_results = getattr(store, "append_proactive_dispatch_results", None)
                    if dispatch_rows and callable(append_dispatch_results):
                        persisted_rows = [
                            {
                                **row,
                                "instance": instance_dir.name,
                                "generated_at": resolved_now.isoformat(timespec="seconds"),
                            }
                            for row in dispatch_rows
                        ]
                        try:
                            account_report["dispatch_result_ids"] = list(append_dispatch_results(account_id, persisted_rows))
                        except (AccountStoreError, OSError, ValueError) as exc:
                            account_report["dispatch_persistence_error"] = f"{type(exc).__name__}: {exc}"
            except (AccountStoreError, OSError, ValueError) as exc:
                account_report["error"] = f"{type(exc).__name__}: {exc}"
            instance_report["accounts"].append(account_report)
        instances.append(instance_report)
    return {
        "ok": _cycle_ok(instances),
        "dry_run": not dispatch,
        "dispatch": dispatch,
        "generated_at": resolved_now.isoformat(timespec="seconds"),
        "instances": instances,
    }


def _effective_model_planners(
    instance_dir: Path,
    *,
    plan: bool,
    llm_plan: bool,
    tool_plan: bool,
    planner_resolver: PlannerResolver | None,
) -> tuple[bool, bool]:
    if llm_plan or tool_plan or not plan or planner_resolver is None:
        return llm_plan, tool_plan
    planner = str(planner_resolver(instance_dir) or "").strip().casefold()
    if planner == "llm":
        return True, False
    if planner == "tool":
        return False, True
    return False, False


def _instance_dirs(instances_dir: Path, selected: tuple[str, ...]) -> list[Path]:
    if selected:
        return [instances_dir / name for name in selected]
    if not instances_dir.exists():
        return []
    return sorted(path for path in instances_dir.iterdir() if path.is_dir() and (path / "data" / "accounts").exists())


def _account_dirs(accounts_dir: Path) -> list[Path]:
    if not accounts_dir.exists():
        return []
    return sorted(path for path in accounts_dir.iterdir() if path.is_dir() and TOKEN_HEX_RE.fullmatch(path.name))


def proactive_llm_planner_instance_enabled(instance_name: str, env: Mapping[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    instance = str(instance_name or "").strip()
    if not instance:
        return False
    listed = _parse_csv(source.get(PROACTIVE_LLM_INSTANCE_LIST_ENV, ""))
    token = _instance_env_token(instance)
    if "all" in listed or instance.casefold() in listed or token.casefold() in listed:
        return True
    flag = source.get(f"{PROACTIVE_LLM_INSTANCE_FLAG_PREFIX}{token}")
    return str(flag or "").strip().casefold() in {"1", "true", "yes", "on", "enabled", "ja", "an"}


def _parse_csv(value: str) -> set[str]:
    return {part.strip().casefold() for part in str(value or "").split(",") if part.strip()}


def _instance_env_token(instance_name: str) -> str:
    token = "".join(char if char.isalnum() else "_" for char in str(instance_name or "").strip().upper())
    return "_".join(part for part in token.split("_") if part)


def _missing_sender_factory(_instance_name: str, _store: AccountStore) -> Mapping[str, ProactiveSender]:
    return {}


def _missing_llm_planner_factory(_instance_name: str, _store: AccountStore, _account_id: str) -> tuple[Any, Any] | None:
    return None


def _message_tracker_for_instance(instance_dir: Path, instance_name: str, factory: MessageTrackerFactory | None) -> MessageTracker | None:
    if factory is not None:
        return factory(instance_dir, instance_name)
    return MessageTracker(instance_dir / "data" / "runtime" / "Sent_Message_Refs.json")


def _cycle_ok(instances: list[dict[str, Any]]) -> bool:
    for instance in instances:
        if instance.get("error"):
            return False
        for account in instance.get("accounts", []):
            if account.get("error"):
                return False
            if account.get("dispatch_persistence_error"):
                return False
            for result in account.get("dispatch_results", []):
                if result.get("status") == "failed":
                    return False
    return True


def _proactive_llm_role_report(client: Any | None, *, role: str) -> dict[str, str]:
    resolved_role = str(getattr(client, "proactive_role", "") or role or "").strip()
    report = {"llm_role": resolved_role}
    if resolved_role:
        report["openai_role"] = resolved_role
    provider = str(getattr(client, "provider", "") or "").strip()
    model = str(getattr(client, "model", "") or "").strip()
    if provider:
        report["llm_provider"] = provider
    if model:
        report["llm_model"] = model
    return report


def _print_dry_run_report(report: dict[str, Any]) -> None:
    mode = "dispatch" if report.get("dispatch") else "dry_run"
    print(f"proactive_{mode} generated_at={report['generated_at']}")
    for instance in report["instances"]:
        enabled = "yes" if instance.get("enabled") else "no"
        print(f"instance={instance['instance']} enabled={enabled}")
        if instance.get("skipped_reason"):
            print(f"  skipped={instance['skipped_reason']}")
            continue
        for account in instance.get("accounts", []):
            due_items = account.get("due_items", [])
            print(f"  account={account['account_id']} due_items={len(due_items)}")
            if account.get("error"):
                print(f"    error={account['error']}")
            if account.get("expired_item_ids"):
                print(f"    expired_items={len(account['expired_item_ids'])}")
            if "llm_planning" in account:
                llm = account["llm_planning"]
                role = _openai_role_suffix(llm)
                if llm.get("skipped_reason"):
                    print(f"    llm_planning{role} skipped={llm['skipped_reason']}")
                else:
                    print(
                        f"    llm_planning{role} "
                        f"created={len(llm.get('created_memory_ids', []))} "
                        f"queued={len(llm.get('queued_item_ids', []))} "
                        f"errors={len(llm.get('errors', []))}"
                    )
            if "tool_planning" in account:
                tool = account["tool_planning"]
                role = _openai_role_suffix(tool)
                if tool.get("skipped_reason"):
                    print(f"    tool_planning{role} skipped={tool['skipped_reason']}")
                else:
                    print(
                        f"    tool_planning{role} "
                        f"created={len(tool.get('created_memory_ids', []))} "
                        f"queued={len(tool.get('queued_item_ids', []))} "
                        f"errors={len(tool.get('errors', []))}"
                    )
            for item in due_items:
                policy = "allowed" if item["policy_allowed"] else f"blocked:{item['policy_reason']}"
                print(f"    item={item['id']} category={item['category']} intent={item['intent']} policy={policy}")
            for result in account.get("dispatch_results", []):
                print(
                    f"    dispatch item={result['item_id']} status={result['status']} "
                    f"reason={result['reason']} channel={result['channel']}"
                )


def _openai_role_suffix(report: Mapping[str, Any]) -> str:
    role = str(report.get("llm_role") or report.get("openai_role") or "").strip()
    return f" role={role}" if role else ""


if __name__ == "__main__":
    raise SystemExit(main())
