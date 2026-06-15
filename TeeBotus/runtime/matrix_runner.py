from __future__ import annotations

import asyncio
import logging
import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from TeeBotus.adapters.matrix import _matrix_response_error_message, matrix_message_to_event, send_matrix_actions
from TeeBotus.instructions import InstructionStore
from TeeBotus.llm_client import build_text_llm_client
from TeeBotus.openai_client import OpenAIClient
from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, InstanceSecretProvider, SecretToolInstanceSecretProvider
from TeeBotus.runtime.actions import DeleteTrackedMessages, ExportFile, NotifyLinkedIdentity, SendAttachment, SendEdit, SendPoll, SendText
from TeeBotus.runtime.async_bridge import run_background_coroutine
from TeeBotus.runtime.config import AccountRunConfig, RuntimeConfig
from TeeBotus.runtime.engine import EngineResult, TeeBotusEngine, should_ignore_event_without_account
from TeeBotus.runtime.events import IncomingAttachment, IncomingEvent
from TeeBotus.runtime.jobs import YouTubeTranscriptionJobRunner
from TeeBotus.runtime.message_tracking import MessageTracker, SentMessageRef
from TeeBotus.runtime.proactive_backends import matrix_proactive_sender
from TeeBotus.runtime.state import RuntimeStateStore
from TeeBotus.runtime.working_memory import WorkingMemoryStore
from TeeBotus.runtime.bibliothekar import BibliothekarStore


LOGGER = logging.getLogger("TeeBotus.matrix")


class MatrixRuntimeError(RuntimeError):
    """Raised when the Matrix runtime cannot be started."""


@dataclass(frozen=True)
class MatrixHomeserverHealth:
    account: AccountRunConfig
    ok: bool
    target: str
    error: str = ""


class MatrixRuntimeBridge:
    def __init__(
        self,
        *,
        run_config: AccountRunConfig,
        client: Any,
        instances_dir: str | Path,
        secret_provider: InstanceSecretProvider | None = None,
    ) -> None:
        self.run_config = run_config
        self.client = client
        instance_dir = Path(instances_dir) / run_config.instance_name
        data_dir = instance_dir / "data"
        self.instruction_store = InstructionStore(instance_dir / "Bot_Verhalten.md")
        resolved_secret_provider = secret_provider or SecretToolInstanceSecretProvider()
        self.account_store = AccountStore(data_dir / "accounts", run_config.instance_name, secret_provider=resolved_secret_provider)
        self.state_store = RuntimeStateStore(data_dir, instance_name=run_config.instance_name, secret_provider=resolved_secret_provider)
        self.message_tracker = MessageTracker(data_dir / "runtime" / "Sent_Message_Refs.json")
        self.openai_client = OpenAIClient(run_config.openai_api_key) if run_config.openai_api_key else None
        self.llm_client = build_text_llm_client(
            instructions=self.instruction_store.get(),
            openai_client=self.openai_client,
            default_api_key=run_config.openai_api_key,
            provider=run_config.llm_provider,
            model=run_config.llm_model,
            fallback_models=run_config.llm_fallback_models,
            api_key=run_config.llm_api_key,
            api_base=run_config.llm_base_url,
            timeout=run_config.llm_timeout_seconds,
            max_tokens=run_config.llm_max_output_tokens,
            temperature=run_config.llm_temperature,
        )
        self.working_memory_store = WorkingMemoryStore(run_config.instance_name, Path(instances_dir))
        self.bibliothekar_store = BibliothekarStore(run_config.instance_name, Path(instances_dir))
        self.youtube_job_runner = YouTubeTranscriptionJobRunner()
        self.engine = TeeBotusEngine(
            self.account_store,
            state=self.state_store,
            message_tracker=self.message_tracker,
            instructions=self.instruction_store.get,
            openai_client=self.openai_client,
            llm_client=self.llm_client,
            bot_address_names=_matrix_bot_address_names(run_config),
            working_memory_store=self.working_memory_store,
            bibliothekar_store=self.bibliothekar_store,
            youtube_job_runner=self.youtube_job_runner,
            background_action_dispatcher=self._dispatch_background_actions,
        )
        self._dispatch_loop: asyncio.AbstractEventLoop | None = None
        self._dispatch_loop_thread_id: int | None = None

    def proactive_sender(self):
        return matrix_proactive_sender({self.run_config.slot: self.client})

    async def handle_message(self, room: Any, message: Any) -> None:
        self._dispatch_loop = asyncio.get_running_loop()
        self._dispatch_loop_thread_id = threading.get_ident()
        if _matrix_sender_is_self(message, self.run_config.matrix_user_id):
            return
        event = matrix_message_to_event(
            room,
            message,
            instance=self.run_config.instance_name,
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
                ignored = should_ignore_event_without_account(event, _matrix_bot_address_names(self.run_config))
        except (AccountStoreError, OSError, ValueError, AttributeError):
            LOGGER.exception(
                "Matrix account lookup failed before routing instance=%s room_id=%s event_id=%s.",
                self.run_config.instance_name,
                event.chat_id,
                event.message_ref,
            )
            await self._send_memory_error(event)
            return
        if ignored:
            return
        event = await _fetch_matrix_reply_text(self.client, event)
        event = await _download_matrix_event_attachments(self.client, event)
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
                "Matrix account resolution failed instance=%s room_id=%s event_id=%s.",
                self.run_config.instance_name,
                event.chat_id,
                event.message_ref,
            )
            await self._send_memory_error(event)
            return
        event = event.with_account(account_id)
        try:
            engine_result = _process_engine_result(self.engine, event)
        except (AccountStoreError, OSError, ValueError, AttributeError):
            LOGGER.exception(
                "Matrix engine processing failed instance=%s room_id=%s event_id=%s.",
                self.run_config.instance_name,
                event.chat_id,
                event.message_ref,
            )
            await self._send_memory_error(event)
            return
        event = event.with_account(engine_result.account_id)
        actions = engine_result.actions
        await self._notify_linked_identities(actions)
        await self._delete_tracked_messages(event, actions)
        actions = _with_matrix_reply_context(actions, event)
        try:
            sent_refs = await send_matrix_actions(self.client, actions)
        except Exception:
            LOGGER.exception(
                "Matrix action dispatch failed instance=%s room_id=%s event_id=%s.",
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
                    channel="matrix",
                    instance_name=event.instance,
                    account_id=event.account_id,
                    chat_id=event.chat_id,
                    message_ref=str(sent_ref),
                    ref_kind="matrix_event_id",
                ),
                context="action",
            )

    async def _send_memory_error(self, event: IncomingEvent) -> None:
        try:
            await send_matrix_actions(self.client, [SendText(event.chat_id, self.instruction_store.get().user_memory_error, track=False)])
        except Exception:
            LOGGER.exception(
                "Matrix memory error notification failed instance=%s room_id=%s event_id=%s.",
                self.run_config.instance_name,
                event.chat_id,
                event.message_ref,
            )

    async def _notify_linked_identities(self, actions: list[Any]) -> None:
        for action in actions:
            if not isinstance(action, NotifyLinkedIdentity):
                continue
            route = self.account_store.get_identity_route(action.identity_key)
            if not route or route.get("channel") != "matrix":
                continue
            chat_id = str(route.get("chat_id") or "").strip()
            if not chat_id:
                continue
            try:
                sent_refs = await send_matrix_actions(self.client, [SendText(chat_id, action.text, track=action.track)])
            except Exception:
                LOGGER.exception(
                    "Matrix linked identity notification failed instance=%s room_id=%s identity_key=%s.",
                    self.run_config.instance_name,
                    chat_id,
                    action.identity_key,
                )
                continue
            sent_ref = sent_refs[0] if sent_refs else None
            if not action.track or sent_ref is None:
                continue
            self._record_sent_ref(
                SentMessageRef(
                    channel="matrix",
                    instance_name=self.run_config.instance_name,
                    account_id=action.account_id,
                    chat_id=chat_id,
                    message_ref=str(sent_ref),
                    ref_kind="matrix_event_id",
                ),
                context="linked_identity",
            )

    def _dispatch_background_actions(self, event: IncomingEvent, actions: list[Any]) -> None:
        sender = matrix_proactive_sender({self.run_config.slot: self.client})
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
                    "Matrix background action dispatch failed instance=%s room_id=%s event_id=%s action=%s.",
                    self.run_config.instance_name,
                    event.chat_id,
                    event.message_ref,
                    action.__class__.__name__,
                )
                continue
            self._track_background_action(event, action, sent_ref)

    def _track_background_action(self, event: IncomingEvent, action: Any, sent_ref: Any) -> None:
        if sent_ref is None:
            return
        should_track = isinstance(action, (SendText, SendAttachment, SendEdit, SendPoll, ExportFile)) and getattr(action, "track", True)
        if not should_track:
            return
        self._record_sent_ref(
            SentMessageRef(
                channel="matrix",
                instance_name=event.instance,
                account_id=event.account_id,
                chat_id=event.chat_id,
                message_ref=str(sent_ref),
                ref_kind="matrix_event_id",
            ),
            context="background",
        )

    def _record_sent_ref(self, ref: SentMessageRef, *, context: str) -> None:
        try:
            self.message_tracker.record(ref)
        except Exception:
            LOGGER.exception(
                "Matrix sent message tracking failed instance=%s room_id=%s event_id=%s context=%s.",
                ref.instance_name,
                ref.chat_id,
                ref.message_ref,
                context,
            )

    async def _delete_tracked_messages(self, event: Any, actions: list[Any]) -> None:
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
                    "Matrix cleanup could not load tracked messages instance=%s room_id=%s count=%s.",
                    event.instance,
                    event.chat_id,
                    action.count,
                )
                continue
            failed_refs: list[SentMessageRef] = []
            for ref in refs:
                try:
                    await _delete_matrix_message(self.client, event.chat_id, ref.message_ref)
                except Exception:
                    LOGGER.exception(
                        "Matrix cleanup failed instance=%s room_id=%s event_id=%s.",
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
                    "Matrix cleanup could not restore failed refs instance=%s room_id=%s count=%s.",
                    event.instance,
                    event.chat_id,
                    len(failed_refs),
                )


async def _delete_matrix_message(client: Any, room_id: str, event_id: str) -> None:
    delete_message = getattr(client, "delete_message", None)
    if callable(delete_message):
        response = await delete_message(room_id, event_id, reason="TeeBotus cleanup")
        _raise_matrix_runtime_response_error(response)
        return
    room_redact = getattr(client, "room_redact", None)
    if not callable(room_redact):
        raise MatrixRuntimeError("Matrix cleanup requires nio-bot delete_message or matrix-nio room_redact")
    response = await room_redact(room_id, event_id, reason="TeeBotus cleanup")
    _raise_matrix_runtime_response_error(response)


def _raise_matrix_runtime_response_error(response: Any) -> None:
    message = _matrix_response_error_message(response)
    if not message:
        return
    raise MatrixRuntimeError(message)


def start_matrix_accounts_in_background(config: RuntimeConfig) -> list[threading.Thread]:
    _import_niobot()
    _require_matrix_homeservers_reachable(config)
    threads: list[threading.Thread] = []
    for account in _matrix_accounts(config):
        thread = _matrix_account_thread(account=account, instances_dir=config.instances_dir)
        thread.start()
        threads.append(thread)
    return threads


def run_matrix_accounts(config: RuntimeConfig) -> int:
    accounts = _matrix_accounts(config)
    if not accounts:
        raise MatrixRuntimeError(
            "Matrix ist angefordert, aber kein MATRIX_BOT_HOMESERVER_<INSTANCE> plus MATRIX_BOT_USER_ID_<INSTANCE> plus MATRIX_BOT_ACCESS_TOKEN_<INSTANCE> ist konfiguriert."
        )
    _import_niobot()
    _require_matrix_homeservers_reachable(config)
    for account in accounts[1:]:
        thread = _matrix_account_thread(account=account, instances_dir=config.instances_dir)
        thread.start()
    run_matrix_account(account=accounts[0], instances_dir=config.instances_dir)
    return 0


def run_matrix_account(*, account: AccountRunConfig, instances_dir: str | Path) -> None:
    asyncio.run(_run_matrix_account_async(account=account, instances_dir=instances_dir))


async def _run_matrix_account_async(*, account: AccountRunConfig, instances_dir: str | Path) -> None:
    if account.channel != "matrix":
        raise MatrixRuntimeError(f"unsupported Matrix account channel: {account.channel}")
    niobot = _import_niobot()
    nio = _import_nio_from_niobot_backend()
    client = niobot.NioBot(
        account.matrix_homeserver,
        account.matrix_user_id,
        device_id=account.matrix_device_id or "teebotus",
        command_prefix="/",
        global_message_type="m.text",
    )
    bridge = MatrixRuntimeBridge(run_config=account, client=client, instances_dir=instances_dir)
    for event_class in _matrix_message_event_classes(nio):
        client.add_event_callback(bridge.handle_message, event_class)
    await client.start(access_token=account.matrix_access_token)


def _matrix_accounts(config: RuntimeConfig) -> tuple[AccountRunConfig, ...]:
    return tuple(account for instance in config.instances for account in instance.accounts if account.channel == "matrix")


def _matrix_bot_address_names(account: AccountRunConfig) -> tuple[str, ...]:
    user_id = str(account.matrix_user_id or "").strip()
    localpart = user_id[1:].split(":", maxsplit=1)[0] if user_id.startswith("@") else ""
    return tuple(value for value in (user_id, localpart, account.label) if value)


def _matrix_sender_is_self(message: Any, matrix_user_id: str) -> bool:
    sender = str(getattr(message, "sender", "") or "").strip()
    own_user_id = str(matrix_user_id or "").strip()
    return bool(sender and own_user_id and sender == own_user_id)


def _matrix_message_event_classes(nio: Any) -> tuple[Any, ...]:
    return tuple(
        getattr(nio, name)
        for name in (
            "RoomMessageText",
            "RoomMessageNotice",
            "RoomMessageEmote",
            "RoomMessageFile",
            "RoomMessageImage",
            "RoomMessageAudio",
            "RoomMessageVideo",
            "RoomEncryptedFile",
            "RoomEncryptedImage",
            "RoomEncryptedAudio",
            "RoomEncryptedVideo",
            "RoomMessageUnknown",
        )
        if hasattr(nio, name)
    )


def _with_matrix_reply_context(actions: list[Any], event: IncomingEvent) -> list[Any]:
    reply_to_ref = str(event.message_ref or "").strip()
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


def _process_engine_result(engine: Any, event: IncomingEvent) -> EngineResult:
    process_result = getattr(engine, "process_result", None)
    if callable(process_result):
        result = process_result(event)
        if isinstance(result, EngineResult):
            return result
    actions = engine.process(event)
    return EngineResult(event.account_id, list(actions or []), handled=bool(actions))


async def _fetch_matrix_reply_text(client: Any, event: IncomingEvent) -> IncomingEvent:
    if event.reply_to_text:
        return event
    reply_event_id = _matrix_reply_event_id(event.raw)
    if not reply_event_id:
        return event
    fetch_message = getattr(client, "fetch_message", None)
    if callable(fetch_message):
        try:
            response = await fetch_message(event.chat_id, reply_event_id)
        except Exception:
            response = None
        reply_text = _matrix_reply_text_from_response(response)
        if reply_text:
            return event.with_reply_to_text(reply_text)
    room_get_event = getattr(client, "room_get_event", None)
    if not callable(room_get_event):
        return event
    try:
        response = await room_get_event(event.chat_id, reply_event_id)
    except Exception:
        return event
    reply_text = _matrix_reply_text_from_response(response)
    if not reply_text:
        return event
    return event.with_reply_to_text(reply_text)


def _matrix_reply_event_id(message: Any) -> str:
    content = getattr(message, "source", {}).get("content", {}) if isinstance(getattr(message, "source", {}), dict) else {}
    relates_to = content.get("m.relates_to", {})
    if not isinstance(relates_to, dict):
        return ""
    in_reply_to = relates_to.get("m.in_reply_to", {})
    if not isinstance(in_reply_to, dict):
        return ""
    return str(in_reply_to.get("event_id") or "").strip()


def _matrix_reply_text_from_response(response: Any) -> str:
    if isinstance(response, tuple):
        for item in response:
            text = _matrix_event_body(item)
            if text:
                return text
    for candidate in (
        getattr(response, "event", None),
        response,
    ):
        text = _matrix_event_body(candidate)
        if text:
            return text
    return ""


def _matrix_event_body(event: Any) -> str:
    body = str(getattr(event, "body", "") or "").strip()
    if body:
        return body
    source = getattr(event, "source", {})
    if not isinstance(source, dict):
        return ""
    content = source.get("content", {})
    if not isinstance(content, dict):
        return ""
    return str(content.get("body") or "").strip()


async def _download_matrix_event_attachments(client: Any, event: IncomingEvent) -> IncomingEvent:
    if not event.attachments:
        return event
    downloaded: list[IncomingAttachment] = []
    changed = False
    for attachment in event.attachments:
        if attachment.data or not attachment.base64_data.startswith("mxc://"):
            downloaded.append(attachment)
            continue
        try:
            response = await client.download(mxc=attachment.base64_data)
        except Exception:
            downloaded.append(attachment)
            continue
        body = _matrix_download_body_bytes(getattr(response, "body", None))
        if body is None:
            downloaded.append(attachment)
            continue
        body = _matrix_decrypt_attachment_body(body, event.raw, attachment)
        if body is None:
            downloaded.append(attachment)
            continue
        filename = str(getattr(response, "filename", "") or attachment.filename or "").strip() or "matrix-attachment.bin"
        content_type = _matrix_resolved_download_content_type(response, attachment)
        downloaded.append(
            IncomingAttachment(
                data=body,
                filename=filename,
                content_type=content_type,
                base64_data=attachment.base64_data,
                view_once=attachment.view_once,
            )
        )
        changed = True
    if not changed:
        return event
    return event.with_attachments(tuple(downloaded))


def _matrix_download_body_bytes(body: Any) -> bytes | None:
    if isinstance(body, bytes):
        return body
    try:
        return Path(body).read_bytes()
    except (OSError, TypeError, ValueError):
        return None


def _matrix_resolved_download_content_type(response: Any, attachment: IncomingAttachment) -> str:
    downloaded_type = str(getattr(response, "content_type", "") or "").strip()
    attachment_type = str(attachment.content_type or "").strip()
    if downloaded_type and downloaded_type != "application/octet-stream":
        return downloaded_type
    return attachment_type or downloaded_type or "application/octet-stream"


def _matrix_decrypt_attachment_body(body: bytes, raw_event: Any, attachment: IncomingAttachment) -> bytes | None:
    metadata = _matrix_attachment_crypto_metadata(raw_event, attachment.base64_data)
    if not metadata:
        return body
    key = metadata.get("key")
    hashes = metadata.get("hashes")
    iv = str(metadata.get("iv") or "").strip()
    key_value = key.get("k") if isinstance(key, dict) else str(key or "").strip()
    hash_value = hashes.get("sha256") if isinstance(hashes, dict) else ""
    if not key_value or not hash_value or not iv:
        return None
    try:
        from nio.crypto.attachments import decrypt_attachment  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        return decrypt_attachment(body, str(key_value), str(hash_value), iv)
    except Exception:
        return None


def _matrix_attachment_crypto_metadata(raw_event: Any, mxc_url: str) -> dict[str, Any]:
    content = _matrix_raw_content(raw_event)
    file_info = content.get("file") if isinstance(content.get("file"), dict) else {}
    target = str(mxc_url or "").strip()
    if file_info:
        file_url = str(file_info.get("url") or "").strip()
        if not target or not file_url or target == file_url:
            return file_info
    raw_url = str(getattr(raw_event, "url", "") or "").strip()
    if target and raw_url and target != raw_url:
        return {}
    key = getattr(raw_event, "key", None)
    hashes = getattr(raw_event, "hashes", None)
    iv = getattr(raw_event, "iv", None)
    if key or hashes or iv:
        return {"key": key, "hashes": hashes, "iv": iv}
    return {}


def _matrix_raw_content(raw_event: Any) -> dict[str, Any]:
    source = getattr(raw_event, "source", None)
    content = source.get("content", {}) if isinstance(source, dict) else {}
    return content if isinstance(content, dict) else {}


def check_matrix_homeservers(config: RuntimeConfig, *, timeout_seconds: float = 1.0) -> tuple[MatrixHomeserverHealth, ...]:
    return tuple(check_matrix_homeserver(account, timeout_seconds=timeout_seconds) for account in _matrix_accounts(config))


def check_matrix_homeserver(account: AccountRunConfig, *, timeout_seconds: float = 1.0) -> MatrixHomeserverHealth:
    try:
        host, port, target = _matrix_homeserver_host_port(account.matrix_homeserver)
    except MatrixRuntimeError as exc:
        return MatrixHomeserverHealth(account=account, ok=False, target=account.matrix_homeserver, error=str(exc))
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return MatrixHomeserverHealth(account=account, ok=True, target=target)
    except OSError as exc:
        return MatrixHomeserverHealth(account=account, ok=False, target=target, error=str(exc))


def _require_matrix_homeservers_reachable(config: RuntimeConfig) -> None:
    failures = [health for health in check_matrix_homeservers(config) if not health.ok]
    if failures:
        details = "; ".join(
            f"{health.account.instance_name}/{health.account.label} {health.target}: {health.error}" for health in failures
        )
        raise MatrixRuntimeError(f"Matrix-Homeserver nicht erreichbar: {details}")


def _matrix_account_thread(*, account: AccountRunConfig, instances_dir: str | Path) -> threading.Thread:
    return threading.Thread(
        target=run_matrix_account,
        kwargs={"account": account, "instances_dir": instances_dir},
        name=f"teebotus-matrix-{account.instance_name}-{account.slot}",
        daemon=True,
    )


def _matrix_homeserver_host_port(homeserver: str) -> tuple[str, int, str]:
    parsed = urlsplit(homeserver.strip().rstrip("/"))
    if parsed.scheme not in {"http", "https"}:
        raise MatrixRuntimeError("MATRIX_BOT_HOMESERVER_<INSTANCE> muss mit http:// oder https:// beginnen.")
    if not parsed.hostname:
        raise MatrixRuntimeError("MATRIX_BOT_HOMESERVER_<INSTANCE> muss Host und optional Port enthalten.")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise MatrixRuntimeError("MATRIX_BOT_HOMESERVER_<INSTANCE> darf keinen Pfad, Query-String oder Fragment enthalten.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise MatrixRuntimeError("MATRIX_BOT_HOMESERVER_<INSTANCE> enthaelt keinen gueltigen Port.") from exc
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    target = f"{parsed.hostname}:{port}"
    return parsed.hostname, port, target


def _import_niobot() -> Any:
    try:
        import niobot  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        if exc.name in {"niobot", "blurhash", "marko", "magic"}:
            raise MatrixRuntimeError(
                "Matrix braucht das Python-Paket 'nio-bot' mit seinen Abhaengigkeiten. "
                "Installiere die gepinnte Version aus requirements.txt."
            ) from exc
        raise
    if not hasattr(niobot, "NioBot"):
        raise MatrixRuntimeError("Das installierte Paket 'nio-bot' stellt NioBot nicht bereit.")
    return niobot


def _import_nio_from_niobot_backend() -> Any:
    try:
        import nio  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        if exc.name == "nio":
            raise MatrixRuntimeError("Matrix ist vorbereitet, aber das Backend von 'nio-bot' stellt 'matrix-nio' nicht bereit.") from exc
        raise
    for required in ("AsyncClient", "RoomMessageText"):
        if not hasattr(nio, required):
            raise MatrixRuntimeError(f"Das Matrix-Backend stellt {required} nicht bereit.")
    return nio
