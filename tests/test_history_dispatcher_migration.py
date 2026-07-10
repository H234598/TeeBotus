from __future__ import annotations

from pathlib import Path

from TeeBotus.history_dispatcher_migration import migrate_codex_history_to_dispatcher
from TeeBotus.runtime.accounts import INSTANCE_STATE_ACCOUNT_ID, StaticSecretProvider, AccountStore


class FakeClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []

    def request(self, operation: str, body: dict[str, object]) -> dict[str, object]:
        self.requests.append((operation, body))
        return {"ok": True, "data": {"deduplicated": False}}


def test_migration_streams_account_store_rows_without_staging(tmp_path: Path) -> None:
    store = AccountStore(tmp_path / "accounts", "Logger", StaticSecretProvider(b"a" * 32))
    store.write_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID, [{"id": "legacy-1", "kind": "codex_run_summary", "summary": {"text": "hello"}}])
    client = FakeClient()
    result = migrate_codex_history_to_dispatcher(store, client)
    assert result["ok"] is True
    assert result["imported"] == 1
    assert client.requests[0][0] == "history.append"
    assert client.requests[0][1]["id"] == "legacy-1"
