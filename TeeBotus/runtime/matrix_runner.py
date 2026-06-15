from __future__ import annotations

import asyncio
import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from TeeBotus.adapters.matrix import matrix_message_to_event, send_matrix_actions
from TeeBotus.runtime.accounts import AccountStore, InstanceSecretProvider, SecretToolInstanceSecretProvider
from TeeBotus.runtime.actions import DeleteTrackedMessages, ExportFile, NotifyLinkedIdentity, SendAttachment, SendText
from TeeBotus.runtime.config import AccountRunConfig, RuntimeConfig
from TeeBotus.runtime.engine import TeeBotusEngine
from TeeBotus.runtime.message_tracking import MessageTracker, SentMessageRef
from TeeBotus.runtime.state import RuntimeStateStore


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
        data_dir = Path(instances_dir) / run_config.instance_name / "data"
        resolved_secret_provider = secret_provider or SecretToolInstanceSecretProvider()
        self.account_store = AccountStore(data_dir / "accounts", run_config.instance_name, secret_provider=resolved_secret_provider)
        self.state_store = RuntimeStateStore(data_dir, instance_name=run_config.instance_name, secret_provider=resolved_secret_provider)
        self.message_tracker = MessageTracker(data_dir / "runtime" / "Sent_Message_Refs.json")
        self.engine = TeeBotusEngine(self.account_store, state=self.state_store, message_tracker=self.message_tracker)

    async def handle_message(self, room: Any, message: Any) -> None:
        if str(getattr(message, "sender", "") or "") == self.run_config.matrix_user_id:
            return
        event = matrix_message_to_event(
            room,
            message,
            instance=self.run_config.instance_name,
            adapter_slot=self.run_config.slot,
            account_label=self.run_config.label,
        )
        account_id = self.account_store.resolve_or_create_account(event.identity_key, display_label=event.sender_name)
        self.account_store.update_identity_route(
            event.identity_key,
            channel=event.channel,
            chat_id=event.chat_id,
            chat_type=event.chat_type,
            adapter_slot=event.adapter_slot,
        )
        event = event.with_account(account_id)
        actions = self.engine.process(event)
        await self._notify_linked_identities(actions)
        await self._delete_tracked_messages(event, actions)
        sent_refs = await send_matrix_actions(self.client, actions)
        for action, sent_ref in zip(actions, sent_refs):
            if sent_ref is None:
                continue
            if isinstance(action, ExportFile):
                should_track = True
            else:
                should_track = isinstance(action, (SendText, SendAttachment)) and action.track
            if not should_track:
                continue
            self.message_tracker.record(
                SentMessageRef(
                    channel="matrix",
                    instance_name=event.instance,
                    account_id=event.account_id,
                    chat_id=event.chat_id,
                    message_ref=str(sent_ref),
                    ref_kind="matrix_event_id",
                )
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
                await send_matrix_actions(self.client, [SendText(chat_id, action.text, track=action.track)])
            except Exception:
                continue

    async def _delete_tracked_messages(self, event: Any, actions: list[Any]) -> None:
        for action in actions:
            if not isinstance(action, DeleteTrackedMessages):
                continue
            refs = self.message_tracker.pop_for_cleanup(
                instance_name=event.instance,
                channel=event.channel,
                chat_id=event.chat_id,
                count=action.count,
            )
            for ref in refs:
                try:
                    await self.client.room_redact(event.chat_id, ref.message_ref, reason="TeeBotus cleanup")
                except Exception:
                    continue


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


def _matrix_message_event_classes(nio: Any) -> tuple[Any, ...]:
    return tuple(
        getattr(nio, name)
        for name in ("RoomMessageText", "RoomMessageFile", "RoomMessageImage", "RoomMessageAudio", "RoomMessageVideo")
        if hasattr(nio, name)
    )


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
