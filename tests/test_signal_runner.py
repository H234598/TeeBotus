from __future__ import annotations

import asyncio

from TeeBotus.runtime.accounts import StaticSecretProvider
from TeeBotus.runtime.config import AccountRunConfig
from TeeBotus.runtime.signal_runner import TeeBotusSignalCommand


class FakeSignalMessage:
    source_uuid = "signal-uuid"
    source_number = "+491234"
    source = "+491234"
    text = "/account"
    timestamp = 123456
    group = ""
    attachments_local_filenames = []
    base64_attachments = []

    def recipient(self) -> str:
        return self.source


class FakeSignalContext:
    def __init__(self) -> None:
        self.message = FakeSignalMessage()
        self.sent: list[str] = []

    async def send(self, text: str, **_kwargs) -> int:
        self.sent.append(text)
        return 987654

    async def start_typing(self) -> None:
        return None


def test_signal_command_routes_private_account_commands(tmp_path) -> None:
    command = TeeBotusSignalCommand(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="signal",
            slot=1,
            label="signal:1",
            openai_api_key="",
            signal_service="http://127.0.0.1:8080",
            signal_phone_number="+491234",
        ),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )
    context = FakeSignalContext()

    asyncio.run(command.handle(context))

    assert context.sent
    assert "Deine TeeBotus-Account-ID" in context.sent[0]
