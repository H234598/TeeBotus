from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from TeeBotus.adapters.signal import send_signal_actions, signal_context_to_event
from TeeBotus.runtime.accounts import AccountStore, InstanceSecretProvider, SecretToolInstanceSecretProvider
from TeeBotus.runtime.actions import SendAttachment, SendText
from TeeBotus.runtime.config import AccountRunConfig, RuntimeConfig
from TeeBotus.runtime.engine import TeeBotusEngine
from TeeBotus.runtime.message_tracking import MessageTracker, SentMessageRef
from TeeBotus.runtime.state import RuntimeStateStore


class SignalRuntimeError(RuntimeError):
    """Raised when the Signal runtime cannot be started."""


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


def start_signal_accounts_in_background(config: RuntimeConfig) -> list[threading.Thread]:
    _import_signalbot()
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
    bot = bot_class(config_class(signal_service=account.signal_service, phone_number=account.signal_phone_number))
    bot.register(TeeBotusSignalCommand(run_config=account, instances_dir=instances_dir))
    bot.start()


def _signal_accounts(config: RuntimeConfig) -> tuple[AccountRunConfig, ...]:
    return tuple(account for instance in config.instances for account in instance.accounts if account.channel == "signal")


def _signal_account_thread(*, account: AccountRunConfig, instances_dir: str | Path) -> threading.Thread:
    return threading.Thread(
        target=run_signal_account,
        kwargs={"account": account, "instances_dir": instances_dir},
        name=f"teebotus-signal-{account.instance_name}-{account.slot}",
        daemon=True,
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
