from __future__ import annotations

import asyncio

from TeeBotus.runtime.accounts import StaticSecretProvider
from TeeBotus.runtime.config import AccountRunConfig
from TeeBotus.runtime.matrix_runner import MatrixRuntimeBridge


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
