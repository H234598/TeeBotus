from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from inspect import isawaitable
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

from TeeBotus.admin.codex_history import record_codex_history_delivery_receipt, record_codex_history_reply
from TeeBotus.adapters.signal import _signal_message_recipient, _signal_raw_data_message, _signal_required_timestamp, send_signal_actions, signal_context_to_event
from TeeBotus.instructions import InstructionStore
from TeeBotus.openai_client import OpenAIClient
from TeeBotus.runtime.llm_factory import build_runtime_structured_decision_runner, build_runtime_text_llm_client
from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, InstanceSecretProvider, runtime_secret_provider
from TeeBotus.runtime.actions import DeleteTrackedMessages, ExportFile, NotifyLinkedIdentity, SendAttachment, SendEdit, SendPoll, SendText
from TeeBotus.runtime.async_bridge import run_background_coroutine
from TeeBotus.runtime.config import AccountRunConfig, RuntimeConfig
from TeeBotus.runtime.engine import (
    EngineResult,
    TeeBotusEngine,
    _command_name,
    _command_targets_other_bot,
    _text_addresses_bot,
    should_ignore_event_without_account,
)
from TeeBotus.runtime.jobs import YouTubeTranscriptionJobRunner
from TeeBotus.runtime.maintenance import runtime_dir
from TeeBotus.runtime.message_tracking import MessageTracker, SentMessageRef
from TeeBotus.runtime.proactive_backends import signal_proactive_sender
from TeeBotus.runtime.state import RuntimeStateStore
from TeeBotus.runtime.working_memory import WorkingMemoryStore
from TeeBotus.runtime.bibliothekar_service import BibliothekarService

LOGGER = logging.getLogger("TeeBotus.signal")

try:
    from signalbot import Command as _SignalBotCommand  # type: ignore[import-not-found]
except ModuleNotFoundError as exc:
    if exc.name != "signalbot":
        raise
    _SignalBotCommand = object  # type: ignore[assignment]


class SignalRuntimeError(RuntimeError):
    """Raised when the Signal runtime cannot be started."""


@dataclass(frozen=True)
class SignalServiceHealth:
    account: AccountRunConfig
    ok: bool
    target: str
    error: str = ""


@dataclass(frozen=True)
class SignalAccountHealth:
    account: AccountRunConfig
    ok: bool
    target: str
    registered: bool = False
    error: str = ""
    warning: str = ""
    router: str = ""


@dataclass(frozen=True)
class _SignalRouteCandidate:
    command: "TeeBotusSignalCommand"
    event: Any
    account_id: str = ""
    addressed: bool = False
    targets_other_bot: bool = False


LOCAL_SIGNAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
SIGNAL_JSON_RPC_HOST = "127.0.0.1"
SIGNAL_JSON_RPC_PORT = 6001
SIGNAL_JSON_RPC_START_TIMEOUT_SECONDS = 45.0
SIGNAL_REST_API_START_TIMEOUT_SECONDS = 45.0


class TeeBotusSignalCommand(_SignalBotCommand):
    """signalbot command that forwards every Signal message into TeeBotus' runtime engine."""

    def __init__(
        self,
        *,
        run_config: AccountRunConfig,
        instances_dir: str | Path,
        secret_provider: InstanceSecretProvider | None = None,
    ) -> None:
        super().__init__()
        self.run_config = run_config
        self.instances_dir = Path(instances_dir)
        data_dir = self.instances_dir / run_config.instance_name / "data"
        instruction_path = self.instances_dir / run_config.instance_name / "Bot_Verhalten.md"
        self.instruction_store = InstructionStore(instruction_path)
        resolved_secret_provider = secret_provider or runtime_secret_provider()
        self.account_store = AccountStore(data_dir / "accounts", run_config.instance_name, secret_provider=resolved_secret_provider)
        self.state_store = RuntimeStateStore(data_dir, instance_name=run_config.instance_name, secret_provider=resolved_secret_provider)
        self.message_tracker = MessageTracker(data_dir / "runtime" / "Sent_Message_Refs.json")
        self.openai_client = OpenAIClient(run_config.openai_api_key) if run_config.openai_api_key else None
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
            service_tier=run_config.llm_service_tier,
            instance_name=run_config.instance_name,
        )
        self.structured_decision_runner = build_runtime_structured_decision_runner(
            instructions=instructions,
            enabled=run_config.structured_decision_enabled or run_config.llm_enabled,
            runtime_llm_configured=_run_config_has_llm_route(run_config),
            allow_remote_fallback=run_config.llm_allow_remote_fallback,
        )
        self.working_memory_store = WorkingMemoryStore(run_config.instance_name, self.instances_dir)
        self.bibliothekar_store = BibliothekarService.from_instructions(
            run_config.instance_name,
            self.instances_dir,
            instructions,
        )
        self.youtube_job_runner = YouTubeTranscriptionJobRunner()
        self.engine = TeeBotusEngine(
            self.account_store,
            state=self.state_store,
            message_tracker=self.message_tracker,
            instructions=self.instruction_store.get,
            openai_client=self.openai_client,
            openai_api_key=run_config.openai_api_key,
            llm_client=self.llm_client,
            llm_enabled_override=run_config.llm_enabled,
            bot_address_names=(run_config.signal_phone_number, run_config.label, run_config.instance_name),
            working_memory_store=self.working_memory_store,
            bibliothekar_store=self.bibliothekar_store,
            youtube_job_runner=self.youtube_job_runner,
            background_action_dispatcher=self._dispatch_background_actions,
            structured_decision_runner=self.structured_decision_runner,
        )
        self.bot: Any | None = None
        self._dispatch_loop: asyncio.AbstractEventLoop | None = None
        self._dispatch_loop_thread_id: int | None = None

    def setup(self) -> None:
        return None

    def proactive_sender(self):
        if self.bot is None:
            raise SignalRuntimeError("SignalBot instance is not attached to TeeBotusSignalCommand")
        return signal_proactive_sender({self.run_config.slot: self.bot})

    async def handle(self, context: Any) -> None:
        self._dispatch_loop = asyncio.get_running_loop()
        self._dispatch_loop_thread_id = threading.get_ident()
        try:
            if self._record_codex_history_native_receipts(getattr(context, "message", None)):
                return
            event = signal_context_to_event(
                context=context,
                instance_name=self.run_config.instance_name,
                adapter_slot=self.run_config.slot,
                account_label=self.run_config.label,
            )
            if event is None:
                return
            should_ignore = getattr(self.engine, "should_ignore_without_account", None)
            try:
                if callable(should_ignore):
                    ignored = bool(should_ignore(event))
                else:
                    ignored = should_ignore_event_without_account(event, (self.run_config.signal_phone_number, self.run_config.label))
            except (AccountStoreError, OSError, ValueError, AttributeError):
                LOGGER.exception(
                    "Signal account lookup failed before routing instance=%s recipient=%s message_ref=%s.",
                    self.run_config.instance_name,
                    event.chat_id,
                    event.message_ref,
                )
                await self._send_memory_error(context, event)
                return
            if ignored:
                return
            try:
                account_id = self.account_store.resolve_or_create_account(event.identity_key, display_label=event.sender_name)
                self.account_store.update_identity_route(
                    event.identity_key,
                    channel=event.channel,
                    chat_id=event.chat_id,
                    chat_type=event.chat_type,
                    adapter_slot=event.adapter_slot,
                )
            except (AccountStoreError, OSError, ValueError, AttributeError):
                LOGGER.exception(
                    "Signal account resolution failed instance=%s recipient=%s message_ref=%s.",
                    self.run_config.instance_name,
                    event.chat_id,
                    event.message_ref,
                )
                await self._send_memory_error(context, event)
                return
            event = event.with_account(account_id)
            self._record_codex_history_reply(event)
            try:
                engine_result = _process_engine_result(self.engine, event)
            except (AccountStoreError, OSError, ValueError, AttributeError):
                LOGGER.exception(
                    "Signal engine processing failed instance=%s recipient=%s message_ref=%s.",
                    self.run_config.instance_name,
                    event.chat_id,
                    event.message_ref,
                )
                await self._send_memory_error(context, event)
                return
            event = event.with_account(engine_result.account_id)
            actions = engine_result.actions
            await self._notify_linked_identities(actions)
            await self._delete_tracked_messages(context, event, actions)
            actions = _with_signal_reply_context(actions, event)
            try:
                sent_refs = await send_signal_actions(context, actions)
            except Exception:
                LOGGER.exception(
                    "Signal action dispatch failed instance=%s recipient=%s message_ref=%s.",
                    event.instance,
                    event.chat_id,
                    event.message_ref,
                )
                return
            for action, sent_ref in zip(actions, sent_refs):
                if sent_ref is None:
                    continue
                if isinstance(action, ExportFile):
                    should_track = True
                else:
                    should_track = isinstance(action, (SendText, SendAttachment, SendEdit, SendPoll)) and action.track
                if not should_track:
                    continue
                self._record_sent_ref(
                    SentMessageRef(
                        channel="signal",
                        instance_name=event.instance,
                        account_id=event.account_id,
                        chat_id=event.chat_id,
                        message_ref=str(sent_ref),
                        ref_kind="signal_timestamp",
                    ),
                    context="action",
                )
        finally:
            await self._delete_local_attachments(context)

    async def _send_memory_error(self, context: Any, event: Any) -> None:
        try:
            await send_signal_actions(context, [SendText(event.chat_id, self.instruction_store.get().user_memory_error, track=False)])
        except Exception:
            LOGGER.exception(
                "Signal memory error notification failed instance=%s recipient=%s message_ref=%s.",
                self.run_config.instance_name,
                event.chat_id,
                event.message_ref,
            )

    async def _notify_linked_identities(self, actions: list[Any]) -> None:
        for action in actions:
            if not isinstance(action, NotifyLinkedIdentity):
                continue
            route = self.account_store.get_identity_route(action.identity_key)
            if not route or route.get("channel") != "signal":
                continue
            receiver = str(route.get("chat_id") or "").strip()
            if not receiver or self.bot is None:
                continue
            try:
                sent_ref = await _maybe_await(self.bot.send(receiver, action.text))
            except Exception:
                LOGGER.exception(
                    "Signal linked identity notification failed instance=%s recipient=%s identity_key=%s.",
                    self.run_config.instance_name,
                    receiver,
                    action.identity_key,
                )
                continue
            if not action.track:
                continue
            try:
                message_ref = str(_signal_required_timestamp(sent_ref, "Signal linked identity notification"))
            except RuntimeError:
                continue
            self._record_sent_ref(
                SentMessageRef(
                    channel="signal",
                    instance_name=self.run_config.instance_name,
                    account_id=action.account_id,
                    chat_id=receiver,
                    message_ref=message_ref,
                    ref_kind="signal_timestamp",
                ),
                context="linked_identity",
            )

    def _dispatch_background_actions(self, event: Any, actions: list[Any]) -> None:
        if self.bot is None:
            return
        sender = signal_proactive_sender({self.run_config.slot: self.bot})
        for action in actions:
            try:
                sent_ref = run_background_coroutine(
                    lambda action=action: sender({"adapter_slot": self.run_config.slot, "chat_id": event.chat_id}, action, {}),
                    loop=self._dispatch_loop,
                    loop_thread_id=self._dispatch_loop_thread_id,
                    on_scheduled_result=lambda sent_ref, action=action: self._track_background_action(event, action, sent_ref),
                )
            except Exception:
                LOGGER.exception(
                    "Signal background action dispatch failed instance=%s recipient=%s message_ref=%s action=%s.",
                    self.run_config.instance_name,
                    event.chat_id,
                    event.message_ref,
                    action.__class__.__name__,
                )
                continue
            self._track_background_action(event, action, sent_ref)

    def _track_background_action(self, event: Any, action: Any, sent_ref: Any) -> None:
        if sent_ref is None:
            return
        should_track = isinstance(action, (SendText, SendAttachment, SendEdit, SendPoll, ExportFile)) and getattr(action, "track", True)
        if not should_track:
            return
        try:
            message_ref = str(_signal_required_timestamp(sent_ref, "Signal background dispatch"))
        except RuntimeError:
            return
        self._record_sent_ref(
            SentMessageRef(
                channel="signal",
                instance_name=event.instance,
                account_id=event.account_id,
                chat_id=event.chat_id,
                message_ref=message_ref,
                ref_kind="signal_timestamp",
            ),
            context="background",
        )

    def _record_sent_ref(self, ref: SentMessageRef, *, context: str) -> None:
        try:
            self.message_tracker.record(ref)
        except Exception:
            LOGGER.exception(
                "Signal sent message tracking failed instance=%s recipient=%s message_ref=%s context=%s.",
                ref.instance_name,
                ref.chat_id,
                ref.message_ref,
                context,
            )

    async def _delete_tracked_messages(self, context: Any, event: Any, actions: list[Any]) -> None:
        for action in actions:
            if not isinstance(action, DeleteTrackedMessages):
                continue
            try:
                refs = self.message_tracker.pop_for_cleanup(
                    instance_name=event.instance,
                    channel=event.channel,
                    chat_id=event.chat_id,
                    count=action.count,
                )
            except Exception:
                LOGGER.exception(
                    "Signal cleanup could not load tracked messages instance=%s recipient=%s count=%s.",
                    event.instance,
                    event.chat_id,
                    action.count,
                )
                continue
            failed_refs: list[SentMessageRef] = []
            for ref in refs:
                try:
                    await _remote_delete_signal_message(context, event.chat_id, ref.message_ref)
                except Exception:
                    LOGGER.exception(
                        "Signal cleanup failed instance=%s recipient=%s message_ref=%s.",
                        event.instance,
                        event.chat_id,
                        ref.message_ref,
                    )
                    failed_refs.append(ref)
                    continue
            try:
                self.message_tracker.restore_for_cleanup(failed_refs)
            except Exception:
                LOGGER.exception(
                    "Signal cleanup could not restore failed refs instance=%s recipient=%s count=%s.",
                    event.instance,
                    event.chat_id,
                    len(failed_refs),
                )

    def _record_codex_history_reply(self, event: Any) -> None:
        reply_to_ref = _signal_reply_message_ref(getattr(event, "raw", None))
        if not reply_to_ref:
            return
        try:
            record_codex_history_reply(
                self.account_store,
                instance_name=self.run_config.instance_name,
                channel="signal",
                chat_id=event.chat_id,
                account_id=event.account_id,
                reply_to_message_ref=reply_to_ref,
                reply_message_ref=event.message_ref,
                reply_text=event.text,
            )
        except (AccountStoreError, OSError, ValueError, AttributeError):
            LOGGER.exception(
                "Signal Codex-History reply tracking failed instance=%s recipient=%s message_ref=%s reply_to=%s.",
                self.run_config.instance_name,
                event.chat_id,
                event.message_ref,
                reply_to_ref,
            )

    def _record_codex_history_native_receipts(self, message: Any) -> bool:
        receipt = _signal_native_receipt(message)
        if not receipt:
            return False
        chat_id = receipt.get("chat_id", "")
        receipt_type = receipt.get("receipt_type", "delivered")
        message_refs = receipt.get("message_refs", ())
        if not chat_id or not message_refs:
            return True
        for message_ref in message_refs:
            try:
                record_codex_history_delivery_receipt(
                    self.account_store,
                    instance_name=self.run_config.instance_name,
                    channel="signal",
                    chat_id=chat_id,
                    message_ref=message_ref,
                    receipt_type=receipt_type,
                )
            except (AccountStoreError, OSError, ValueError, AttributeError):
                LOGGER.exception(
                    "Signal Codex-History receipt tracking failed instance=%s recipient=%s message_ref=%s receipt_type=%s.",
                    self.run_config.instance_name,
                    chat_id,
                    message_ref,
                    receipt_type,
                )
        return True

    async def _delete_local_attachments(self, context: Any) -> None:
        message = getattr(context, "message", None)
        filenames = _signal_local_attachment_filenames(message)
        if not filenames:
            return
        bot = getattr(context, "bot", None) or self.bot
        delete_attachment = getattr(bot, "delete_attachment", None)
        if not callable(delete_attachment):
            return
        for filename in filenames:
            try:
                await _maybe_await(delete_attachment(filename))
            except Exception:
                continue


class SharedSignalRouterCommand(_SignalBotCommand):
    """Route one shared Signal account to the right TeeBotus instance."""

    def __init__(
        self,
        *,
        run_configs: Sequence[AccountRunConfig],
        instances_dir: str | Path,
        secret_provider: InstanceSecretProvider | None = None,
    ) -> None:
        super().__init__()
        accounts = tuple(run_configs)
        if not accounts:
            raise SignalRuntimeError("Shared Signal router needs at least one Signal account config")
        _validate_shared_signal_route(accounts)
        self.run_configs = accounts
        self.instances_dir = Path(instances_dir)
        self.commands = tuple(
            TeeBotusSignalCommand(run_config=account, instances_dir=instances_dir, secret_provider=secret_provider)
            for account in accounts
        )
        self.bot: Any | None = None

    def setup(self) -> None:
        return None

    async def handle(self, context: Any) -> None:
        for command in self.commands:
            command.bot = self.bot or getattr(context, "bot", None)
        candidates = self._route_candidates(context)
        selected = self._select_route(candidates)
        if selected is None:
            await self.commands[0]._delete_local_attachments(context)
            return
        LOGGER.info(
            "Shared Signal router selected instance=%s recipient=%s message_ref=%s candidates=%s.",
            selected.command.run_config.instance_name,
            selected.event.chat_id,
            selected.event.message_ref,
            len(candidates),
        )
        await selected.command.handle(context)

    def _route_candidates(self, context: Any) -> list[_SignalRouteCandidate]:
        candidates: list[_SignalRouteCandidate] = []
        for command in self.commands:
            event = signal_context_to_event(
                context=context,
                instance_name=command.run_config.instance_name,
                adapter_slot=command.run_config.slot,
                account_label=command.run_config.label,
            )
            if event is None:
                continue
            account_id = ""
            try:
                account_id = command.account_store.get_account_for_identity(event.identity_key) or ""
            except (AccountStoreError, OSError, ValueError, AttributeError):
                account_id = ""
            if account_id:
                event = event.with_account(account_id)
            targets_other = _signal_event_targets_other_bot(command, event)
            candidates.append(
                _SignalRouteCandidate(
                    command=command,
                    event=event,
                    account_id=account_id,
                    addressed=False if targets_other else _signal_event_addresses_command(command, event),
                    targets_other_bot=targets_other,
                )
            )
        return candidates

    def _select_route(self, candidates: Sequence[_SignalRouteCandidate]) -> _SignalRouteCandidate | None:
        usable = [candidate for candidate in candidates if not candidate.targets_other_bot]
        if not usable:
            return None
        addressed = [candidate for candidate in usable if candidate.addressed]
        if addressed:
            linked_addressed = [candidate for candidate in addressed if candidate.account_id]
            return (linked_addressed or addressed)[0]
        linked = [candidate for candidate in usable if candidate.account_id]
        if linked:
            return linked[0]
        private = [candidate for candidate in usable if candidate.event.is_private]
        if private:
            return private[0]
        command_candidates = [candidate for candidate in usable if _command_name(candidate.event.text)]
        if command_candidates:
            return command_candidates[0]
        return None


def start_signal_accounts_in_background(config: RuntimeConfig) -> list[threading.Thread]:
    accounts = _require_signal_accounts(config)
    groups = _signal_router_groups(accounts)
    _import_signalbot()
    ensure_signal_services_available(config)
    threads: list[threading.Thread] = []
    for group in groups:
        thread = _signal_router_thread(accounts=group, instances_dir=config.instances_dir)
        thread.start()
        threads.append(thread)
    return threads


def run_signal_accounts(config: RuntimeConfig) -> int:
    accounts = _require_signal_accounts(config)
    groups = _signal_router_groups(accounts)
    _import_signalbot()
    ensure_signal_services_available(config)
    for group in groups[1:]:
        thread = _signal_router_thread(accounts=group, instances_dir=config.instances_dir)
        thread.start()
    if len(groups[0]) == 1:
        run_signal_account(account=groups[0][0], instances_dir=config.instances_dir)
    else:
        run_signal_router_group(accounts=groups[0], instances_dir=config.instances_dir)
    return 0


def run_signal_account(*, account: AccountRunConfig, instances_dir: str | Path) -> None:
    run_signal_router_group(accounts=(account,), instances_dir=instances_dir)


def run_signal_router_group(*, accounts: Sequence[AccountRunConfig], instances_dir: str | Path) -> None:
    accounts = tuple(accounts)
    if not accounts:
        raise SignalRuntimeError("Signal router group is empty")
    _validate_shared_signal_route(accounts)
    account = accounts[0]
    if account.channel != "signal":
        raise SignalRuntimeError(f"unsupported Signal account channel: {account.channel}")
    signalbot = _import_signalbot()
    _patch_signalbot_signal_cli_api_about(signalbot)
    config_class = getattr(signalbot, "Config")
    bot_class = getattr(signalbot, "SignalBot")
    bot = bot_class(config_class(**_signalbot_config_kwargs(signalbot, account)))
    if len(accounts) == 1:
        command = TeeBotusSignalCommand(run_config=account, instances_dir=instances_dir)
    else:
        command = SharedSignalRouterCommand(run_configs=accounts, instances_dir=instances_dir)
    command.bot = bot
    bot.register(command)
    bot.start()


def _signal_accounts(config: RuntimeConfig) -> tuple[AccountRunConfig, ...]:
    return tuple(account for instance in config.instances for account in instance.accounts if account.channel == "signal")


def _require_signal_accounts(config: RuntimeConfig) -> tuple[AccountRunConfig, ...]:
    accounts = _signal_accounts(config)
    if not accounts:
        raise SignalRuntimeError(
            "Signal ist angefordert, aber kein SIGNAL_BOT_SERVICE_<INSTANCE> plus SIGNAL_BOT_PHONE_NUMBER_<INSTANCE> ist konfiguriert."
        )
    return accounts


def _signal_router_groups(accounts: Sequence[AccountRunConfig]) -> tuple[tuple[AccountRunConfig, ...], ...]:
    groups: list[list[AccountRunConfig]] = []
    group_indexes: dict[tuple[str, str], int] = {}
    phone_services: dict[str, tuple[str, str]] = {}
    for account in accounts:
        if account.channel != "signal":
            raise SignalRuntimeError(f"unsupported Signal account channel: {account.channel}")
        phone = str(account.signal_phone_number or "").strip()
        service_key = _signal_service_cache_key(account.signal_service)
        label = f"{account.instance_name}/{account.label}"
        if phone:
            previous = phone_services.get(phone)
            if previous is not None and previous[0] != service_key:
                raise SignalRuntimeError(
                    "Duplicate Signal phone number configured across different signal-cli-rest-api services. "
                    "Use one shared service for one Signal account or register separate phone numbers. "
                    f"Duplicate slot pairs: {previous[1]} / {label}"
                )
            phone_services[phone] = (service_key, label)
        key = (service_key, phone)
        index = group_indexes.get(key)
        if index is None:
            group_indexes[key] = len(groups)
            groups.append([account])
        else:
            groups[index].append(account)
    return tuple(tuple(group) for group in groups)


def _validate_shared_signal_route(accounts: Sequence[AccountRunConfig]) -> None:
    if not accounts:
        raise SignalRuntimeError("Shared Signal router needs at least one Signal account config")
    _signal_router_groups(accounts)


def _signal_event_targets_other_bot(command: TeeBotusSignalCommand, event: Any) -> bool:
    return _command_targets_other_bot(str(getattr(event, "text", "") or ""), _signal_command_address_names(command, event))


def _signal_event_addresses_command(command: TeeBotusSignalCommand, event: Any) -> bool:
    names = _signal_command_address_names(command, event)
    if _command_name(str(getattr(event, "text", "") or "")):
        return not _command_targets_other_bot(str(getattr(event, "text", "") or ""), names)
    if _normalize_event_chat_type(event) == "group":
        try:
            if not command.engine.should_ignore_without_account(event):
                return True
        except (AccountStoreError, OSError, ValueError, AttributeError):
            pass
    return _text_addresses_bot(str(getattr(event, "text", "") or ""), names)


def _normalize_event_chat_type(event: Any) -> str:
    return str(getattr(event, "chat_type", "") or "").strip().casefold()


def _signal_command_address_names(command: TeeBotusSignalCommand, event: Any) -> frozenset[str]:
    try:
        names = set(command.engine._bot_address_names_for_event(event))  # noqa: SLF001 - router uses engine routing contract.
    except (AccountStoreError, OSError, ValueError, AttributeError):
        names = set(command.engine.bot_address_names)
    names.update(
        str(value or "").strip()
        for value in (
            command.run_config.signal_phone_number,
            command.run_config.label,
            command.run_config.instance_name,
        )
        if str(value or "").strip()
    )
    return frozenset(names)


def _signal_reply_message_ref(message: Any) -> str:
    quote = getattr(message, "quote", None)
    if quote is not None:
        for attr in ("id", "timestamp", "quote_timestamp", "sent_timestamp", "target_sent_timestamp"):
            value = str(getattr(quote, attr, "") or "").strip()
            if value:
                return value
    raw_message = getattr(message, "raw_message", None)
    if not isinstance(raw_message, str) or not raw_message.strip():
        return ""
    try:
        payload = json.loads(raw_message)
    except (TypeError, ValueError):
        return ""
    envelope = payload.get("envelope") if isinstance(payload, Mapping) else {}
    if not isinstance(envelope, dict):
        return ""
    data_message = _signal_raw_data_message(envelope)
    quote_payload = data_message.get("quote") if isinstance(data_message, Mapping) else {}
    if not isinstance(quote_payload, Mapping):
        return ""
    for key in ("id", "timestamp", "sentTimestamp", "targetSentTimestamp"):
        value = str(quote_payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _signal_native_receipt(message: Any) -> dict[str, Any]:
    message_refs = _signal_receipt_message_refs(message)
    if not message_refs:
        return {}
    chat_id = _signal_message_recipient_for_receipt(message)
    if not chat_id:
        return {}
    return {
        "chat_id": chat_id,
        "receipt_type": _signal_receipt_type(message),
        "message_refs": tuple(dict.fromkeys(message_refs)),
    }


def _signal_receipt_message_refs(message: Any) -> list[str]:
    refs: list[str] = []
    for attr in ("timestamps", "target_sent_timestamps", "target_timestamps", "sent_timestamps"):
        value = getattr(message, attr, None)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            refs.extend(str(item or "").strip() for item in value if str(item or "").strip())
    raw_message = getattr(message, "raw_message", None)
    if isinstance(raw_message, str) and raw_message.strip():
        try:
            payload = json.loads(raw_message)
        except (TypeError, ValueError):
            payload = {}
        envelope = payload.get("envelope") if isinstance(payload, Mapping) else {}
        receipt_message = envelope.get("receiptMessage") if isinstance(envelope, Mapping) else {}
        if isinstance(receipt_message, Mapping):
            timestamps = receipt_message.get("timestamps") or receipt_message.get("targetSentTimestamps") or []
            if isinstance(timestamps, Sequence) and not isinstance(timestamps, (str, bytes, bytearray)):
                refs.extend(str(item or "").strip() for item in timestamps if str(item or "").strip())
            for key in ("timestamp", "targetSentTimestamp"):
                value = str(receipt_message.get(key) or "").strip()
                if value:
                    refs.append(value)
    return [ref for ref in refs if ref]


def _signal_message_recipient_for_receipt(message: Any) -> str:
    group = str(getattr(message, "group", "") or "").strip()
    if group:
        return group
    recipient = _signal_message_recipient(message)
    if recipient:
        return recipient
    for attr in ("source", "source_number", "source_uuid"):
        value = str(getattr(message, attr, "") or "").strip()
        if value:
            return value
    return ""


def _signal_receipt_type(message: Any) -> str:
    raw_type = ""
    raw_message = getattr(message, "raw_message", None)
    if isinstance(raw_message, str) and raw_message.strip():
        try:
            payload = json.loads(raw_message)
        except (TypeError, ValueError):
            payload = {}
        envelope = payload.get("envelope") if isinstance(payload, Mapping) else {}
        receipt_message = envelope.get("receiptMessage") if isinstance(envelope, Mapping) else {}
        if isinstance(receipt_message, Mapping):
            raw_type = str(receipt_message.get("type") or "").strip()
    if not raw_type:
        message_type = getattr(message, "type", None)
        raw_type = str(getattr(message_type, "name", "") or "").strip()
    normalized = raw_type.casefold()
    if "view" in normalized:
        return "viewed"
    if "read" in normalized:
        return "read"
    return "delivered"


def _with_signal_reply_context(actions: list[Any], event: Any) -> list[Any]:
    reply_to_ref = str(getattr(event, "message_ref", "") or "").strip()
    if not reply_to_ref:
        return actions
    enriched: list[Any] = []
    for action in actions:
        if isinstance(action, SendText) and action.chat_id == event.chat_id and not action.reply_to_ref:
            enriched.append(
                SendText(
                    action.chat_id,
                    action.text,
                    track=action.track,
                    reply_to_ref=reply_to_ref,
                    mentions=action.mentions,
                    text_mode=action.text_mode,
                    formatted_text=action.formatted_text,
                    view_once=action.view_once,
                    link_preview=action.link_preview,
                )
            )
        elif isinstance(action, SendAttachment) and action.chat_id == event.chat_id and not action.reply_to_ref:
            enriched.append(
                SendAttachment(
                    action.chat_id,
                    action.data,
                    action.filename,
                    action.content_type,
                    caption=action.caption,
                    track=action.track,
                    reply_to_ref=reply_to_ref,
                    mentions=action.mentions,
                    text_mode=action.text_mode,
                    view_once=action.view_once,
                    link_preview=action.link_preview,
                )
            )
        elif isinstance(action, ExportFile) and action.chat_id == event.chat_id and not action.reply_to_ref:
            enriched.append(
                ExportFile(
                    action.chat_id,
                    action.filename,
                    action.content_type,
                    action.data,
                    caption=action.caption,
                    reply_to_ref=reply_to_ref,
                )
            )
        else:
            enriched.append(action)
    return enriched


def _process_engine_result(engine: Any, event: Any) -> EngineResult:
    process_result = getattr(engine, "process_result", None)
    if callable(process_result):
        result = process_result(event)
        if isinstance(result, EngineResult):
            return result
    actions = engine.process(event)
    return EngineResult(event.account_id, list(actions or []), handled=bool(actions))


async def _remote_delete_signal_message(context: Any, receiver: str, message_ref: str) -> int | None:
    timestamp = int(str(message_ref or "").strip())
    remote_delete = getattr(context, "remote_delete", None)
    if callable(remote_delete):
        return await _maybe_await(remote_delete(timestamp))
    bot = getattr(context, "bot", None)
    bot_remote_delete = getattr(bot, "remote_delete", None)
    target = str(receiver or "").strip() or _signal_context_recipient(context)
    if callable(bot_remote_delete) and target:
        return await _maybe_await(bot_remote_delete(target, timestamp))
    raise SignalRuntimeError("SignalBot.remote_delete is required to delete tracked messages")


async def _maybe_await(value: Any) -> Any:
    if isawaitable(value):
        return await value
    return value


def _signal_context_recipient(context: Any) -> str:
    message = getattr(context, "message", None)
    recipient = getattr(message, "recipient", None)
    if not callable(recipient):
        return ""
    try:
        return str(recipient() or "").strip()
    except Exception:
        return ""


def _signal_local_attachment_filenames(message: Any) -> tuple[str, ...]:
    values = getattr(message, "attachments_local_filenames", None) or []
    filenames: list[str] = []
    for value in values:
        filename = str(value or "").strip()
        if filename and filename not in filenames:
            filenames.append(filename)
    return tuple(filenames)


def check_signal_services(config: RuntimeConfig, *, timeout_seconds: float = 1.0) -> tuple[SignalServiceHealth, ...]:
    return tuple(check_signal_service(account, timeout_seconds=timeout_seconds) for account in _signal_accounts(config))


def check_signal_service(account: AccountRunConfig, *, timeout_seconds: float = 1.0) -> SignalServiceHealth:
    try:
        host, port, target = _signal_service_host_port(account.signal_service)
    except SignalRuntimeError as exc:
        return SignalServiceHealth(account=account, ok=False, target=account.signal_service, error=str(exc))
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return SignalServiceHealth(account=account, ok=True, target=target)
    except OSError as exc:
        return SignalServiceHealth(account=account, ok=False, target=target, error=str(exc))


def check_signal_accounts(config: RuntimeConfig) -> tuple[SignalAccountHealth, ...]:
    healths: list[SignalAccountHealth] = []
    seen_phones: dict[str, tuple[str, str]] = {}
    service_accounts_cache: dict[str, tuple[bool, list[Any], str]] = {}
    for account in _signal_accounts(config):
        phone = str(account.signal_phone_number or "").strip()
        label = f"{account.instance_name}/{account.label}"
        try:
            _host, _port, target = _signal_service_host_port(account.signal_service)
        except SignalRuntimeError as exc:
            previous = seen_phones.get(phone)
            duplicate_warning = f"duplicate phone number with {previous[1]}" if phone and previous is not None else ""
            healths.append(SignalAccountHealth(account=account, ok=False, target=account.signal_service, error=str(exc), warning=duplicate_warning))
            if phone and previous is None:
                seen_phones[phone] = ("", label)
            continue
        service_key = _signal_service_cache_key(account.signal_service)
        duplicate_warning = ""
        router = ""
        previous = seen_phones.get(phone)
        if phone and previous is not None:
            previous_service_key, previous_label = previous
            if previous_service_key == service_key:
                router = f"shared_with:{previous_label}"
            elif previous_service_key:
                duplicate_warning = f"duplicate phone number with {previous_label} on different service"
            else:
                duplicate_warning = f"duplicate phone number with {previous_label}"
        if phone:
            seen_phones[phone] = (service_key, label)
        if service_key not in service_accounts_cache:
            try:
                if _signal_service_looks_like_signal_cli_api(account):
                    service_accounts_cache[service_key] = (True, _signal_cli_api_accounts(account), "")
                else:
                    service_accounts_cache[service_key] = (False, [], "service does not expose signal-cli-rest-api account list")
            except SignalRuntimeError as exc:
                service_accounts_cache[service_key] = (False, [], str(exc))
        ok, accounts, error = service_accounts_cache[service_key]
        if not ok:
            healths.append(SignalAccountHealth(account=account, ok=False, target=target, error=error, warning=duplicate_warning, router=router))
            continue
        registered = account.signal_phone_number in {_signal_cli_api_account_identifier(value) for value in accounts}
        healths.append(
            SignalAccountHealth(
                account=account,
                ok=registered,
                target=target,
                registered=registered,
                error="" if registered else "account missing in signal-cli-rest-api /v1/accounts",
                warning=duplicate_warning,
                router=router,
            )
        )
    return tuple(healths)


def _require_signal_services_reachable(config: RuntimeConfig) -> None:
    failures = [health for health in check_signal_services(config) if not health.ok]
    if failures:
        details = "; ".join(
            f"{health.account.instance_name}/{health.account.label} {health.target}: {health.error}" for health in failures
        )
        raise SignalRuntimeError(f"signal-cli-rest-api nicht erreichbar: {details}")


def ensure_signal_services_available(config: RuntimeConfig) -> None:
    failures = [health for health in check_signal_services(config) if not health.ok]
    attempted_targets: set[str] = set()
    for health in failures:
        if health.target in attempted_targets:
            continue
        attempted_targets.add(health.target)
        _start_local_signal_backend_if_possible(health.account)
    _require_signal_services_reachable(config)
    _require_signal_cli_api_accounts_registered(config)


def _start_local_signal_backend_if_possible(account: AccountRunConfig) -> None:
    try:
        host, port, _target = _signal_service_host_port(account.signal_service)
        _normalized, scheme = _normalize_signal_service(account.signal_service)
    except SignalRuntimeError:
        return
    if scheme == "https":
        return
    if host.casefold() not in LOCAL_SIGNAL_HOSTS:
        return
    if check_signal_service(account, timeout_seconds=0.25).ok:
        return
    command = _signal_cli_rest_api_command(host, port)
    log_path = runtime_dir() / f"signal-cli-rest-api-{account.instance_name}-{account.slot}.log"
    pid_path = runtime_dir() / f"signal-cli-rest-api-{account.instance_name}-{account.slot}.pid"
    if _pid_file_process_is_running(pid_path, markers=("signal-cli-rest-api",)):
        _wait_for_signal_cli_rest_api(account=account, process=None, log_path=log_path)
        return
    _require_signal_backend_binary("signal-cli")
    _ensure_signal_json_rpc_daemon()
    runtime_dir().mkdir(parents=True, exist_ok=True)
    try:
        log_file = log_path.open("ab")
    except OSError as exc:
        raise SignalRuntimeError(f"signal-cli-rest-api log konnte nicht geoeffnet werden: {log_path}: {exc}") from exc
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=_signal_backend_env(port),
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        log_file.close()
        raise SignalRuntimeError(
            "signal-cli-rest-api ist nicht im PATH. Installiere die gepinnte native Abhaengigkeit aus adapter-dependencies.lock."
        ) from exc
    except OSError as exc:
        log_file.close()
        raise SignalRuntimeError(f"signal-cli-rest-api konnte nicht gestartet werden: {exc}") from exc
    finally:
        try:
            log_file.close()
        except OSError:
            pass
    pid_path.write_text(f"{process.pid}\n", encoding="utf-8")
    _wait_for_signal_cli_rest_api(account=account, process=process, log_path=log_path)


def _wait_for_signal_cli_rest_api(
    *,
    account: AccountRunConfig,
    process: subprocess.Popen[Any] | None,
    log_path: Path,
) -> None:
    deadline = time.monotonic() + SIGNAL_REST_API_START_TIMEOUT_SECONDS
    last_error = ""
    _host, _port, target = _signal_service_host_port(account.signal_service)
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise SignalRuntimeError(
                f"signal-cli-rest-api fuer {target} wurde gestartet, ist aber sofort beendet. Siehe {log_path}."
            )
        health = check_signal_service(account, timeout_seconds=0.25)
        if health.ok:
            return
        last_error = health.error
        time.sleep(0.25)
    raise SignalRuntimeError(f"signal-cli-rest-api fuer {target} startete nicht rechtzeitig: {last_error}. Siehe {log_path}.")


def _signal_cli_rest_api_command(host: str, port: int) -> list[str]:
    listen_host = "127.0.0.1" if host in {"localhost", "::1"} else host
    binary = shutil.which("signal-cli-rest-api")
    if binary is None:
        local_binary = Path.home() / ".local" / "bin" / "signal-cli-rest-api"
        binary = str(local_binary) if local_binary.exists() else "signal-cli-rest-api"
    return [binary, "-signal-cli-config", str(_signal_cli_config_dir()), "-attachment-tmp-dir", str(runtime_dir()), "-avatar-tmp-dir", str(runtime_dir())]


def _ensure_signal_json_rpc_daemon() -> None:
    config_dir = _signal_cli_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    jsonrpc_config = config_dir / "jsonrpc2.yml"
    if not jsonrpc_config.exists():
        jsonrpc_config.write_text(f"config:\n  <multi-account>:\n    tcp_port: {SIGNAL_JSON_RPC_PORT}\n", encoding="utf-8")
    if _tcp_port_is_open(SIGNAL_JSON_RPC_HOST, SIGNAL_JSON_RPC_PORT, timeout_seconds=0.2):
        return
    log_path = runtime_dir() / "signal-cli-json-rpc-daemon.log"
    pid_path = runtime_dir() / "signal-cli-json-rpc-daemon.pid"
    if _pid_file_process_is_running(pid_path, markers=("org.asamk.signal.Main",)):
        _wait_for_signal_json_rpc_daemon(process=None, log_path=log_path)
        return
    signal_cli = _require_signal_backend_binary("signal-cli")
    runtime_dir().mkdir(parents=True, exist_ok=True)
    try:
        log_file = log_path.open("ab")
    except OSError as exc:
        raise SignalRuntimeError(f"signal-cli JSON-RPC log konnte nicht geoeffnet werden: {log_path}: {exc}") from exc
    try:
        process = subprocess.Popen(
            [
                signal_cli,
                "--output=json",
                "--config",
                str(config_dir),
                "daemon",
                "--tcp",
                f"{SIGNAL_JSON_RPC_HOST}:{SIGNAL_JSON_RPC_PORT}",
            ],
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=_signal_backend_env(),
            start_new_session=True,
        )
    except OSError as exc:
        log_file.close()
        raise SignalRuntimeError(f"signal-cli JSON-RPC daemon konnte nicht gestartet werden: {exc}") from exc
    finally:
        try:
            log_file.close()
        except OSError:
            pass
    pid_path.write_text(f"{process.pid}\n", encoding="utf-8")
    _wait_for_signal_json_rpc_daemon(process=process, log_path=log_path)


def _wait_for_signal_json_rpc_daemon(*, process: subprocess.Popen[Any] | None, log_path: Path) -> None:
    deadline = time.monotonic() + SIGNAL_JSON_RPC_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise SignalRuntimeError(f"signal-cli JSON-RPC daemon wurde gestartet, ist aber sofort beendet. Siehe {log_path}.")
        if _tcp_port_is_open(SIGNAL_JSON_RPC_HOST, SIGNAL_JSON_RPC_PORT, timeout_seconds=0.2):
            return
        time.sleep(0.25)
    raise SignalRuntimeError(f"signal-cli JSON-RPC daemon startete nicht rechtzeitig. Siehe {log_path}.")


def _tcp_port_is_open(host: str, port: int, *, timeout_seconds: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def _require_signal_backend_binary(binary: str) -> str:
    path = _signal_backend_binary(binary)
    if path is None:
        raise SignalRuntimeError(
            f"{binary} ist nicht im PATH. Installiere die gepinnte native Abhaengigkeit aus adapter-dependencies.lock."
        )
    return path


def _signal_backend_binary(binary: str) -> str | None:
    path = shutil.which(binary, path=_signal_backend_path())
    if path is not None:
        return path
    return shutil.which(binary)


def _signal_backend_env(port: int | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = _signal_backend_path()
    env["MODE"] = "json-rpc"
    env["BUILD_VERSION"] = _signal_cli_rest_api_locked_version()
    env["SIGNAL_CLI_CONFIG_DIR"] = str(_signal_cli_config_dir())
    if port is not None:
        env["PORT"] = str(port)
    return env


def _signal_backend_path() -> str:
    extra = [str(Path.home() / ".local" / "bin"), str(Path.home() / ".cargo" / "bin")]
    current = os.environ.get("PATH", "")
    parts = [part for part in current.split(os.pathsep) if part]
    merged: list[str] = []
    for part in [*extra, *parts]:
        if part not in merged:
            merged.append(part)
    return os.pathsep.join(merged)


def _signal_cli_config_dir() -> Path:
    return Path(os.environ.get("SIGNAL_CLI_CONFIG_DIR", str(Path.home() / ".local" / "share" / "signal-cli"))).expanduser()


def _signal_cli_rest_api_locked_version() -> str:
    lockfile = Path(__file__).resolve().parents[2] / "adapter-dependencies.lock"
    try:
        for line in lockfile.read_text(encoding="utf-8").splitlines():
            name, sep, version = line.partition("==")
            if sep and name.strip() == "signal-cli-rest-api":
                return version.strip()
    except OSError:
        return "unset"
    return "unset"


def _require_signal_cli_api_accounts_registered(config: RuntimeConfig) -> None:
    missing: list[str] = []
    incompatible_services: list[str] = []
    checked_services: set[str] = set()
    signal_accounts = _signal_accounts(config)
    for account in signal_accounts:
        service_key = _signal_service_cache_key(account.signal_service)
        if service_key in checked_services:
            continue
        checked_services.add(service_key)
        if not _signal_service_looks_like_signal_cli_api(account):
            try:
                _host, _port, target = _signal_service_host_port(account.signal_service)
            except SignalRuntimeError:
                target = account.signal_service
            incompatible_services.append(target)
            continue
        accounts = _signal_cli_api_accounts(account)
        configured_numbers = {
            signal_account.signal_phone_number
            for signal_account in signal_accounts
            if _signal_service_cache_key(signal_account.signal_service) == service_key
        }
        available = {_signal_cli_api_account_identifier(value) for value in accounts}
        missing.extend(sorted(number for number in configured_numbers if number not in available))
    if incompatible_services:
        details = ", ".join(incompatible_services)
        raise SignalRuntimeError(
            f"signal-cli-rest-api ist erreichbar, stellt aber keine kompatible /v1/about-Antwort bereit: {details}. "
            "Pruefe SIGNAL_BOT_SERVICE_<INSTANCE> oder starte die gepinnte signal-cli-rest-api."
        )
    if missing:
        details = ", ".join(missing)
        raise SignalRuntimeError(
            f"signal-cli-rest-api kennt den konfigurierten Signal-Account nicht: {details}. "
            "Registriere oder verlinke den Account zuerst mit signal-cli."
        )


def _signal_service_looks_like_signal_cli_api(account: AccountRunConfig) -> bool:
    try:
        about = _signal_service_json(account, "/v1/about")
    except SignalRuntimeError:
        return False
    if isinstance(about.get("version"), str) and isinstance(about.get("mode"), str):
        return True
    versions = about.get("versions")
    return isinstance(versions, dict) and isinstance(versions.get("signal-cli-rest-api"), str)


def _signal_cli_api_accounts(account: AccountRunConfig) -> list[Any]:
    payload = _signal_service_json(account, "/v1/accounts")
    if not isinstance(payload, list):
        raise SignalRuntimeError("signal-cli-rest-api /v1/accounts lieferte keine Liste.")
    return payload


def _signal_cli_api_account_identifier(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("number", "phone_number", "account", "username"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate
    return str(value)


def _signal_service_json(account: AccountRunConfig, path: str) -> Any:
    signal_service, scheme = _normalize_signal_service(account.signal_service)
    base_scheme = scheme or "http"
    url = f"{base_scheme}://{signal_service}{path}"
    try:
        with urlopen(url, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
        raise SignalRuntimeError(f"signal-cli-rest-api Statusabfrage fehlgeschlagen: {url}: {exc}") from exc


def _pid_file_process_is_running(path: Path, *, markers: Sequence[str] = ()) -> bool:
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    if pid <= 0:
        return False
    if markers and not _pid_matches_markers(pid, markers):
        return False
    try:
        result = subprocess.run(["kill", "-0", str(pid)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    return result.returncode == 0


def _pid_matches_markers(pid: int, markers: Sequence[str]) -> bool:
    normalized_markers = tuple(str(marker or "").strip() for marker in markers if str(marker or "").strip())
    if not normalized_markers:
        return True
    cmdline_path = Path("/proc") / str(pid) / "cmdline"
    try:
        raw = cmdline_path.read_bytes()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    cmdline = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace")
    return any(marker in cmdline for marker in normalized_markers)


def _signal_account_thread(*, account: AccountRunConfig, instances_dir: str | Path) -> threading.Thread:
    return threading.Thread(
        target=run_signal_account,
        kwargs={"account": account, "instances_dir": instances_dir},
        name=f"teebotus-signal-{account.instance_name}-{account.slot}",
        daemon=True,
    )


def _signal_router_thread(*, accounts: Sequence[AccountRunConfig], instances_dir: str | Path) -> threading.Thread:
    accounts = tuple(accounts)
    if len(accounts) == 1:
        return _signal_account_thread(account=accounts[0], instances_dir=instances_dir)
    label = "_".join(f"{account.instance_name}-{account.slot}" for account in accounts)
    return threading.Thread(
        target=run_signal_router_group,
        kwargs={"accounts": accounts, "instances_dir": instances_dir},
        name=f"teebotus-signal-shared-{label}",
        daemon=True,
    )


def _signalbot_config_kwargs(signalbot: Any, account: AccountRunConfig) -> dict[str, Any]:
    signal_service, scheme = _normalize_signal_service(account.signal_service)
    kwargs: dict[str, Any] = {
        "signal_service": signal_service,
        "phone_number": account.signal_phone_number,
    }
    connection_mode = _signalbot_connection_mode(signalbot, scheme, signal_service)
    if connection_mode is not None:
        kwargs["connection_mode"] = connection_mode
    in_memory_config = getattr(signalbot, "InMemoryConfig", None)
    if in_memory_config is not None:
        kwargs["storage"] = in_memory_config()
    return kwargs


def _normalize_signal_service(signal_service: str) -> tuple[str, str]:
    service = signal_service.strip()
    lowered = service.casefold()
    if lowered.startswith(("http://", "https://")):
        parsed = urlsplit(service)
        if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise SignalRuntimeError("SIGNAL_BOT_SERVICE_<INSTANCE> darf keinen Pfad, Query-String, Fragment oder Zugangsdaten enthalten.")
        if not parsed.netloc:
            raise SignalRuntimeError("SIGNAL_BOT_SERVICE_<INSTANCE> muss Host und optional Port enthalten.")
        return parsed.netloc, parsed.scheme.casefold()
    parsed = urlsplit(f"//{service}")
    if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise SignalRuntimeError("SIGNAL_BOT_SERVICE_<INSTANCE> darf keinen Pfad, Query-String, Fragment oder Zugangsdaten enthalten.")
    if parsed.path == "/":
        return service[:-1], ""
    return service, ""


def _signal_service_host_port(signal_service: str) -> tuple[str, int, str]:
    normalized, scheme = _normalize_signal_service(signal_service)
    parsed = urlsplit(f"//{normalized}")
    if not parsed.hostname:
        raise SignalRuntimeError("SIGNAL_BOT_SERVICE_<INSTANCE> muss Host und optional Port enthalten.")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise SignalRuntimeError("SIGNAL_BOT_SERVICE_<INSTANCE> darf keinen Pfad, Query-String oder Fragment enthalten.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise SignalRuntimeError("SIGNAL_BOT_SERVICE_<INSTANCE> enthaelt keinen gueltigen Port.") from exc
    if port is None:
        port = 443 if scheme == "https" else 80
    target = _signal_service_target(parsed.hostname, port)
    return parsed.hostname, port, target


def _signal_service_target(host: str, port: int) -> str:
    if ":" in host and not host.startswith("["):
        return f"[{host}]:{port}"
    return f"{host}:{port}"


def _signal_service_cache_key(signal_service: str) -> str:
    host, port, _target = _signal_service_host_port(signal_service)
    _normalized, scheme = _normalize_signal_service(signal_service)
    target = _signal_service_target(_signal_service_cache_host(host), port)
    return f"{scheme or 'http'}://{target}"


def _signal_service_cache_host(host: str) -> str:
    normalized = host.casefold()
    if normalized == "localhost":
        return "127.0.0.1"
    return normalized


def _signalbot_connection_mode(signalbot: Any, scheme: str, signal_service: str = "") -> Any | None:
    api = getattr(signalbot, "api", None)
    connection_mode = getattr(api, "ConnectionMode", None)
    if connection_mode is None:
        return None
    if not scheme:
        try:
            host, _port, _target = _signal_service_host_port(signal_service)
        except SignalRuntimeError:
            return None
        if host.casefold() in LOCAL_SIGNAL_HOSTS:
            return getattr(connection_mode, "HTTP_ONLY", None)
        return None
    if scheme == "http":
        return getattr(connection_mode, "HTTP_ONLY", None)
    if scheme == "https":
        return getattr(connection_mode, "HTTPS_ONLY", None)
    return None


def _patch_signalbot_signal_cli_api_about(signalbot: Any) -> None:
    api_module = getattr(signalbot, "api", None)
    signal_api_class = getattr(api_module, "SignalAPI", None)
    if signal_api_class is None or getattr(signal_api_class, "_teebotus_signal_cli_api_about_patch", False):
        return
    original_version = getattr(signal_api_class, "get_signal_cli_rest_api_version", None)
    original_mode = getattr(signal_api_class, "get_signal_cli_rest_api_mode", None)
    if original_version is None or original_mode is None:
        return

    def get_about_api_version(about: Mapping[str, Any]) -> str | None:
        versions = about.get("versions")
        if not isinstance(versions, dict):
            return None
        api_version = versions.get("signal-cli-rest-api")
        if isinstance(api_version, str) and api_version.strip():
            return api_version
        return None

    def has_signal_cli_api_shape(about: Mapping[str, Any]) -> bool:
        versions = about.get("versions")
        if not isinstance(versions, dict):
            return False
        return "signal-cli-rest-api" in versions

    async def get_signal_cli_rest_api_version(self: Any) -> str:
        about = await self.get_signal_cli_about()
        version = about.get("version")
        if isinstance(version, str):
            return version
        api_version = get_about_api_version(about)
        if api_version is not None:
            return api_version
        if has_signal_cli_api_shape(about):
            return "unset"
        return await original_version(self)

    async def get_signal_cli_rest_api_mode(self: Any) -> str:
        about = await self.get_signal_cli_about()
        mode = about.get("mode")
        if isinstance(mode, str):
            return mode
        if has_signal_cli_api_shape(about):
            return "json-rpc"
        return await original_mode(self)

    signal_api_class.get_signal_cli_rest_api_version = get_signal_cli_rest_api_version
    signal_api_class.get_signal_cli_rest_api_mode = get_signal_cli_rest_api_mode
    signal_api_class._teebotus_signal_cli_api_about_patch = True


def _run_config_has_llm_route(run_config: AccountRunConfig) -> bool:
    return any(
        str(getattr(run_config, attr, "") or "").strip()
        for attr in ("llm_profile", "llm_purpose", "llm_provider", "llm_model")
    )


def _import_signalbot() -> Any:
    try:
        import signalbot  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        if exc.name == "signalbot":
            raise SignalRuntimeError("Signal ist freigeschaltet, aber das Python-Paket 'signalbot' ist nicht installiert.") from exc
        raise
    for required in ("Config", "SignalBot"):
        if not hasattr(signalbot, required):
            raise SignalRuntimeError(f"Das installierte Paket 'signalbot' stellt {required} nicht bereit.")
    return signalbot
