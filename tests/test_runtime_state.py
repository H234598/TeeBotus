from __future__ import annotations

from TeeBotus.runtime.accounts import AccountStoreError, SecretToolInstanceSecretProvider, StaticSecretProvider
from TeeBotus.runtime.telegram_bridge import TelegramRuntimeBridge
from TeeBotus.runtime.state import RuntimeStateStore


class BrokenProvider:
    def get_secret(self, instance_name: str, purpose: str) -> bytes:
        raise AccountStoreError("secret backend unavailable")


def test_runtime_state_store_falls_back_to_memory_on_corrupt_persisted_link_notifications(tmp_path):
    runtime_dir = tmp_path / "Bot" / "data" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "Link_Notifications.json").write_text("{not-json", encoding="utf-8")

    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))

    assert state.link_notifications == {}
    assert state.link_notifications_persistence_error


def test_runtime_state_store_keeps_link_notifications_in_memory_when_secret_backend_fails(tmp_path):
    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=BrokenProvider())

    state.record_link_notification(
        instance_name="Bot",
        account_id="a" * 128,
        new_identity_key="signal:uuid:new",
        old_identity_key="telegram:user:1",
    )

    assert state.list_link_notifications(instance_name="Bot", account_id="a" * 128)
    assert "secret backend unavailable" in state.link_notifications_persistence_error


def test_telegram_bridge_defaults_to_secret_tool_provider(tmp_path):
    bridge = TelegramRuntimeBridge(instance_name="Bot", data_dir=tmp_path / "Bot" / "data")

    assert isinstance(bridge.account_store.secret_provider, SecretToolInstanceSecretProvider)
    assert bridge.state_store.secret_provider is bridge.account_store.secret_provider
