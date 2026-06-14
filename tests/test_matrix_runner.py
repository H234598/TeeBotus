from __future__ import annotations

import asyncio

from TeeBotus.runtime.accounts import StaticSecretProvider
from TeeBotus.runtime.config import AccountRunConfig, InstanceRunConfig, RuntimeConfig
from TeeBotus.runtime.matrix_runner import MatrixRuntimeBridge, run_matrix_accounts


class FakeMatrixRoom:
    room_id = "!room:example"
    joined_count = 2


class FakeMatrixMessage:
    event_id = "$incoming"
    sender = "@alice:example"
    body = "/account"


class FakeMatrixResponse:
    event_id = "$sent"


class FakeMatrixClient:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def room_send(self, **kwargs):
        self.sent.append(kwargs)
        return FakeMatrixResponse()


def test_matrix_bridge_routes_private_account_commands(tmp_path) -> None:
    client = FakeMatrixClient()
    bridge = MatrixRuntimeBridge(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="matrix",
            slot=1,
            label="matrix:1",
            openai_api_key="",
            matrix_homeserver="https://matrix.example",
            matrix_user_id="@bot:example",
            matrix_access_token="matrix-token",
        ),
        client=client,
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), FakeMatrixMessage()))

    assert client.sent
    assert "Deine TeeBotus-Account-ID" in client.sent[0]["content"]["body"]


def test_matrix_only_multi_slot_start_backgrounds_additional_slots(monkeypatch, tmp_path) -> None:
    calls: list[tuple[str, int]] = []

    class FakeThread:
        def __init__(self, slot: int) -> None:
            self.slot = slot

        def start(self) -> None:
            calls.append(("background", self.slot))

    accounts = (
        AccountRunConfig(
            instance_name="Demo",
            channel="matrix",
            slot=1,
            label="matrix:1",
            openai_api_key="",
            matrix_homeserver="https://matrix-a.example",
            matrix_user_id="@bot-a:example",
            matrix_access_token="token-a",
        ),
        AccountRunConfig(
            instance_name="Demo",
            channel="matrix",
            slot=2,
            label="matrix:2",
            openai_api_key="",
            matrix_homeserver="https://matrix-b.example",
            matrix_user_id="@bot-b:example",
            matrix_access_token="token-b",
        ),
    )
    config = RuntimeConfig(
        instances_dir=tmp_path,
        selected_instances=("Demo",),
        channels=("matrix",),
        instances=(InstanceRunConfig("Demo", tmp_path / "Bot_Verhalten.md", accounts),),
    )
    monkeypatch.setattr("TeeBotus.runtime.matrix_runner._import_nio", lambda: object())
    monkeypatch.setattr("TeeBotus.runtime.matrix_runner._matrix_account_thread", lambda *, account, instances_dir: FakeThread(account.slot))
    monkeypatch.setattr(
        "TeeBotus.runtime.matrix_runner.run_matrix_account",
        lambda *, account, instances_dir: calls.append(("blocking", account.slot)),
    )

    assert run_matrix_accounts(config) == 0
    assert calls == [("background", 2), ("blocking", 1)]
