from __future__ import annotations

import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from TeeBotus.adapters.signal import send_signal_actions, signal_context_to_event
from TeeBotus.runtime.accounts import AccountStore, InstanceSecretProvider, SecretToolInstanceSecretProvider
from TeeBotus.runtime.actions import DeleteTrackedMessages, SendAttachment, SendText
from TeeBotus.runtime.config import AccountRunConfig, RuntimeConfig
from TeeBotus.runtime.engine import TeeBotusEngine
from TeeBotus.runtime.message_tracking import MessageTracker, SentMessageRef
from TeeBotus.runtime.state import RuntimeStateStore


class SignalRuntimeError(RuntimeError):
    """Raised when the Signal runtime cannot be started."""


@dataclass(frozen=True)
class SignalServiceHealth:
    account: AccountRunConfig
    ok: bool
    target: str
    error: str = ""


class TeeBotusSignalCommand:
    """signalbot command that forwards every Signal message into TeeBotus' runtime engine."""

    def __init__(
        self,
        *,
        run_config: AccountRunConfig,
        instances_dir: str | Path,
        secret_provider: InstanceSecretProvider | None = None,
    ) -> None:
        self.run_config = run_config
        self.instances_dir = Path(instances_dir)
        data_dir = self.instances_dir / run_config.instance_name / "data"
        resolved_secret_provider = secret_provider or SecretToolInstanceSecretProvider()
        self.account_store = AccountStore(data_dir / "accounts", run_config.instance_name, secret_provider=resolved_secret_provider)
        self.state_store = RuntimeStateStore(data_dir, instance_name=run_config.instance_name, secret_provider=resolved_secret_provider)
        self.message_tracker = MessageTracker(data_dir / "runtime" / "Sent_Message_Refs.json")
        self.engine = TeeBotusEngine(self.account_store, state=self.state_store, message_tracker=self.message_tracker)
        self.bot: Any | None = None

    def setup(self) -> None:
        return None

    async def handle(self, context: Any) -> None:
        event = signal_context_to_event(
            context=context,
            instance_name=self.run_config.instance_name,
            adapter_slot=self.run_config.slot,
            account_label=self.run_config.label,
        )
        account_id = self.account_store.resolve_or_create_account(event.identity_key, display_label=event.sender_name)
        event = event.with_account(account_id)
        actions = self.engine.process(event)
        await self._delete_tracked_messages(context, event, actions)
        sent_refs = await send_signal_actions(context, actions)
        for action, sent_ref in zip(actions, sent_refs):
            if sent_ref is None or not isinstance(action, (SendText, SendAttachment)) or not action.track:
                continue
            self.message_tracker.record(
                SentMessageRef(
                    channel="signal",
                    instance_name=event.instance,
                    account_id=event.account_id,
                    chat_id=event.chat_id,
                    message_ref=str(sent_ref),
                    ref_kind="signal_timestamp",
                )
            )

    async def _delete_tracked_messages(self, context: Any, event: Any, actions: list[Any]) -> None:
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
                    await context.remote_delete(int(ref.message_ref))
                except Exception:
                    continue


def start_signal_accounts_in_background(config: RuntimeConfig) -> list[threading.Thread]:
    _import_signalbot()
    _require_signal_services_reachable(config)
    threads: list[threading.Thread] = []
    for account in _signal_accounts(config):
        thread = _signal_account_thread(account=account, instances_dir=config.instances_dir)
        thread.start()
        threads.append(thread)
    return threads


def run_signal_accounts(config: RuntimeConfig) -> int:
    accounts = _signal_accounts(config)
    if not accounts:
        raise SignalRuntimeError(
            "Signal ist angefordert, aber kein SIGNAL_BOT_SERVICE_<INSTANCE> plus SIGNAL_BOT_PHONE_NUMBER_<INSTANCE> ist konfiguriert."
        )
    _import_signalbot()
    _require_signal_services_reachable(config)
    for account in accounts[1:]:
        thread = _signal_account_thread(account=account, instances_dir=config.instances_dir)
        thread.start()
    run_signal_account(account=accounts[0], instances_dir=config.instances_dir)
    return 0


def run_signal_account(*, account: AccountRunConfig, instances_dir: str | Path) -> None:
    if account.channel != "signal":
        raise SignalRuntimeError(f"unsupported Signal account channel: {account.channel}")
    signalbot = _import_signalbot()
    config_class = getattr(signalbot, "Config")
    bot_class = getattr(signalbot, "SignalBot")
    bot = bot_class(config_class(**_signalbot_config_kwargs(signalbot, account)))
    bot.register(TeeBotusSignalCommand(run_config=account, instances_dir=instances_dir))
    bot.start()


def _signal_accounts(config: RuntimeConfig) -> tuple[AccountRunConfig, ...]:
    return tuple(account for instance in config.instances for account in instance.accounts if account.channel == "signal")


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


def _require_signal_services_reachable(config: RuntimeConfig) -> None:
    failures = [health for health in check_signal_services(config) if not health.ok]
    if failures:
        details = "; ".join(
            f"{health.account.instance_name}/{health.account.label} {health.target}: {health.error}" for health in failures
        )
        raise SignalRuntimeError(f"signal-cli-rest-api nicht erreichbar: {details}")


def _signal_account_thread(*, account: AccountRunConfig, instances_dir: str | Path) -> threading.Thread:
    return threading.Thread(
        target=run_signal_account,
        kwargs={"account": account, "instances_dir": instances_dir},
        name=f"teebotus-signal-{account.instance_name}-{account.slot}",
        daemon=True,
    )


def _signalbot_config_kwargs(signalbot: Any, account: AccountRunConfig) -> dict[str, Any]:
    signal_service, scheme = _normalize_signal_service(account.signal_service)
    kwargs: dict[str, Any] = {
        "signal_service": signal_service,
        "phone_number": account.signal_phone_number,
    }
    connection_mode = _signalbot_connection_mode(signalbot, scheme)
    if connection_mode is not None:
        kwargs["connection_mode"] = connection_mode
    return kwargs


def _normalize_signal_service(signal_service: str) -> tuple[str, str]:
    service = signal_service.strip().rstrip("/")
    lowered = service.casefold()
    if lowered.startswith(("http://", "https://")):
        parsed = urlsplit(service)
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise SignalRuntimeError("SIGNAL_BOT_SERVICE_<INSTANCE> darf keinen Pfad, Query-String oder Fragment enthalten.")
        if not parsed.netloc:
            raise SignalRuntimeError("SIGNAL_BOT_SERVICE_<INSTANCE> muss Host und optional Port enthalten.")
        return parsed.netloc, parsed.scheme.casefold()
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
        port = 80 if scheme == "http" else 443
    target = f"{parsed.hostname}:{port}"
    return parsed.hostname, port, target


def _signalbot_connection_mode(signalbot: Any, scheme: str) -> Any | None:
    if not scheme:
        return None
    api = getattr(signalbot, "api", None)
    connection_mode = getattr(api, "ConnectionMode", None)
    if connection_mode is None:
        return None
    if scheme == "http":
        return getattr(connection_mode, "HTTP_ONLY", None)
    if scheme == "https":
        return getattr(connection_mode, "HTTPS_ONLY", None)
    return None


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
