from __future__ import annotations

import asyncio

from TeeBotus.runtime.accounts import StaticSecretProvider
from TeeBotus.runtime.actions import DeleteTrackedMessages, ExportFile, NotifyLinkedIdentity, SendPoll, SendText
from TeeBotus.runtime.config import AccountRunConfig, InstanceRunConfig, RuntimeConfig
from TeeBotus.runtime.engine import EngineResult
from TeeBotus.runtime.events import IncomingAttachment, IncomingEvent
from TeeBotus.runtime.message_tracking import SentMessageRef
from TeeBotus.runtime.matrix_runner import (
    MatrixHomeserverHealth,
    MatrixRuntimeBridge,
    MatrixRuntimeError,
    _delete_matrix_message,
    _download_matrix_event_attachments,
    check_matrix_homeserver,
    _matrix_message_event_classes,
    run_matrix_accounts,
)


class FakeMatrixRoom:
    room_id = "!room:example"
    joined_count = 2


class FakeMatrixGroupRoom:
    room_id = "!group:example"
    joined_count = 3


class FakeMatrixMessage:
    event_id = "$incoming"
    sender = "@alice:example"
    body = "/account"


class FakeMatrixResponse:
    event_id = "$sent"


class FakeMatrixClient:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.redacted: list[tuple[str, str, str | None]] = []
        self.uploaded: list[tuple[bytes, dict[str, object]]] = []
        self.downloads: list[str] = []
        self.fetched_events: list[tuple[str, str]] = []
        self.fetch_message_calls: list[tuple[str, str]] = []
        self.events: dict[tuple[str, str], object] = {}

    async def room_send(self, **kwargs):
        self.sent.append(kwargs)
        return FakeMatrixResponse()

    async def room_redact(self, room_id: str, event_id: str, reason: str | None = None):
        self.redacted.append((room_id, event_id, reason))
        return FakeMatrixResponse()

    async def upload(self, data_provider, **kwargs):
        self.uploaded.append((data_provider.read(), kwargs))
        response = FakeMatrixResponse()
        response.content_uri = "mxc://example/export"
        return response, None

    async def download(self, *, mxc: str):
        self.downloads.append(mxc)
        return type("DownloadResponse", (), {"body": b"downloaded", "content_type": "image/png", "filename": "download.png"})()

    async def room_get_event(self, room_id: str, event_id: str):
        self.fetched_events.append((room_id, event_id))
        return self.events[(room_id, event_id)]

    async def fetch_message(self, room_id: str, event_id: str):
        self.fetch_message_calls.append((room_id, event_id))
        return self.events[(room_id, event_id)]


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


def test_matrix_bridge_tracks_engine_result_account_id(tmp_path) -> None:
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
    target_account_id = "a" * 128
    bridge.engine = type(
        "FakeEngine",
        (),
        {"process_result": lambda self, event: EngineResult(target_account_id, [SendText(event.chat_id, "verbunden")], handled=True)},
    )()

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), FakeMatrixMessage()))

    refs = bridge.message_tracker.pop_for_cleanup(instance_name="Demo", channel="matrix", chat_id="!room:example", count=1)
    assert len(refs) == 1
    assert refs[0].account_id == target_account_id


def test_matrix_bridge_uses_instance_instructions_for_builtin_replies(tmp_path) -> None:
    instance_dir = tmp_path / "Demo"
    instance_dir.mkdir()
    (instance_dir / "Bot_Verhalten.md").write_text("## Befehle\n- /custom: Matrix custom fuer {first_name}.\n", encoding="utf-8")
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
    message = FakeMatrixMessage()
    message.body = "/custom"

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), message))

    assert client.sent[0]["content"]["body"] == "Matrix custom fuer @alice:example."


def test_matrix_group_free_text_must_address_bot(tmp_path) -> None:
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
    message = FakeMatrixMessage()
    message.body = "Hallo Gruppe"

    asyncio.run(bridge.handle_message(FakeMatrixGroupRoom(), message))

    assert client.sent == []
    assert bridge.account_store.get_account_for_identity("matrix:user:@alice:example") is None


def test_matrix_bridge_ignores_empty_messages_without_account_side_effects(tmp_path) -> None:
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
    message = FakeMatrixMessage()
    message.body = ""

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), message))

    assert client.sent == []
    assert bridge.account_store.get_account_for_identity("matrix:user:@alice:example") is None


def test_matrix_group_free_text_can_address_bot_by_user_id(tmp_path) -> None:
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
    message = FakeMatrixMessage()
    message.body = "@bot:example hallo"

    asyncio.run(bridge.handle_message(FakeMatrixGroupRoom(), message))

    assert client.sent[0]["content"]["body"] == "Echo: @bot:example hallo"
    assert client.sent[0]["content"]["m.relates_to"] == {"m.in_reply_to": {"event_id": "$incoming"}}


def test_matrix_bridge_ignores_own_sender_after_trimming(tmp_path) -> None:
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

    class OwnMessage(FakeMatrixMessage):
        sender = " @bot:example "
        body = "/account"

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), OwnMessage()))

    assert client.sent == []
    assert bridge.account_store.get_account_for_identity("matrix:user:@bot:example") is None


def test_matrix_bridge_preserves_explicit_engine_reply_context(tmp_path) -> None:
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
    bridge.engine = type(
        "FakeEngine",
        (),
        {"process": lambda self, event: [SendText(event.chat_id, "Explizit", reply_to_ref="$explicit")]},
    )()

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), FakeMatrixMessage()))

    assert client.sent[0]["content"]["m.relates_to"] == {"m.in_reply_to": {"event_id": "$explicit"}}


def test_matrix_bridge_replies_to_original_event_for_edit_message(tmp_path) -> None:
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

    class EditMessage(FakeMatrixMessage):
        event_id = "$edit"
        body = "* /custom"
        source = {
            "content": {
                "msgtype": "m.text",
                "body": "* /custom",
                "m.new_content": {"msgtype": "m.text", "body": "/account"},
                "m.relates_to": {"rel_type": "m.replace", "event_id": "$original"},
            }
        }

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), EditMessage()))

    assert "Deine TeeBotus-Account-ID" in client.sent[0]["content"]["body"]
    assert client.sent[0]["content"]["m.relates_to"] == {"m.in_reply_to": {"event_id": "$original"}}


def test_matrix_bridge_fetches_reply_text_without_body_fallback(tmp_path) -> None:
    client = FakeMatrixClient()
    client.events[("!room:example", "$old")] = type(
        "RoomGetEventResponse",
        (),
        {"event": type("MatrixEvent", (), {"source": {"content": {"body": "Originaltext"}}})()},
    )()
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
    seen = []
    bridge.engine = type("FakeEngine", (), {"process": lambda self, event: seen.append(event) or []})()

    class ReplyMessage(FakeMatrixMessage):
        body = "Antwort"
        source = {"content": {"msgtype": "m.text", "body": "Antwort", "m.relates_to": {"m.in_reply_to": {"event_id": "$old"}}}}

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), ReplyMessage()))

    assert client.fetch_message_calls == [("!room:example", "$old")]
    assert client.fetched_events == []
    assert seen[0].text == "Antwort"
    assert seen[0].reply_to_text == "Originaltext"


def test_matrix_bridge_fetches_reply_text_from_niobot_cache_tuple(tmp_path) -> None:
    class CachedReplyClient(FakeMatrixClient):
        async def fetch_message(self, room_id: str, event_id: str):
            self.fetch_message_calls.append((room_id, event_id))
            return FakeMatrixRoom(), type("MatrixEvent", (), {"body": "Cached original"})()

        async def room_get_event(self, _room_id: str, _event_id: str):
            raise AssertionError("room_get_event should not be used when fetch_message returns text")

    client = CachedReplyClient()
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
    seen = []
    bridge.engine = type("FakeEngine", (), {"process": lambda self, event: seen.append(event) or []})()

    class ReplyMessage(FakeMatrixMessage):
        body = "Antwort"
        source = {"content": {"msgtype": "m.text", "body": "Antwort", "m.relates_to": {"m.in_reply_to": {"event_id": "$old"}}}}

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), ReplyMessage()))

    assert client.fetch_message_calls == [("!room:example", "$old")]
    assert seen[0].reply_to_text == "Cached original"


def test_matrix_bridge_keeps_reply_missing_when_lookup_fails(tmp_path) -> None:
    class FailingGetEventClient(FakeMatrixClient):
        async def room_get_event(self, room_id: str, event_id: str):
            self.fetched_events.append((room_id, event_id))
            raise OSError("lookup refused")

    client = FailingGetEventClient()
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
    seen = []
    bridge.engine = type("FakeEngine", (), {"process": lambda self, event: seen.append(event) or []})()

    class ReplyMessage(FakeMatrixMessage):
        body = "Antwort"
        source = {"content": {"msgtype": "m.text", "body": "Antwort", "m.relates_to": {"m.in_reply_to": {"event_id": "$old"}}}}

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), ReplyMessage()))

    assert client.fetch_message_calls == [("!room:example", "$old")]
    assert client.fetched_events == [("!room:example", "$old")]
    assert seen[0].reply_to_text is None


def test_matrix_bridge_constructs_openai_client_from_run_config(monkeypatch, tmp_path) -> None:
    captured: list[str] = []

    class FakeOpenAIClient:
        def __init__(self, api_key: str) -> None:
            captured.append(api_key)

    monkeypatch.setattr("TeeBotus.runtime.matrix_runner.OpenAIClient", FakeOpenAIClient)
    bridge = MatrixRuntimeBridge(
        run_config=AccountRunConfig(
            instance_name="Demo",
            channel="matrix",
            slot=1,
            label="matrix:1",
            openai_api_key="sk-matrix",
            matrix_homeserver="https://matrix.example",
            matrix_user_id="@bot:example",
            matrix_access_token="matrix-token",
        ),
        client=FakeMatrixClient(),
        instances_dir=tmp_path,
        secret_provider=StaticSecretProvider(b"x" * 32),
    )

    assert captured == ["sk-matrix"]
    assert bridge.engine.openai_client is bridge.openai_client


def test_matrix_cleanup_redacts_tracked_current_room_messages(tmp_path) -> None:
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
    account_id = bridge.account_store.resolve_or_create_account("matrix:user:@alice:example")
    bridge.message_tracker.record(
        SentMessageRef(
            channel="matrix",
            instance_name="Demo",
            account_id=account_id,
            chat_id="!room:example",
            message_ref="$old",
            ref_kind="matrix_event_id",
        )
    )
    message = FakeMatrixMessage()
    message.body = "/cleanup 1"

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), message))

    assert client.redacted == [("!room:example", "$old", "TeeBotus cleanup")]
    assert any("aktuellen Chat" in call["content"]["body"] for call in client.sent)


def test_matrix_cleanup_prefers_niobot_delete_message(tmp_path) -> None:
    class DeleteMessageClient(FakeMatrixClient):
        def __init__(self) -> None:
            super().__init__()
            self.deleted: list[tuple[str, str, str | None]] = []

        async def delete_message(self, room_id: str, event_id: str, reason: str | None = None):
            self.deleted.append((room_id, event_id, reason))
            return FakeMatrixResponse()

        async def room_redact(self, *_args, **_kwargs):
            raise AssertionError("room_redact should not be used when delete_message is available")

    client = DeleteMessageClient()
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
    account_id = bridge.account_store.resolve_or_create_account("matrix:user:@alice:example")
    bridge.message_tracker.record(
        SentMessageRef(
            channel="matrix",
            instance_name="Demo",
            account_id=account_id,
            chat_id="!room:example",
            message_ref="$old",
            ref_kind="matrix_event_id",
        )
    )
    message = FakeMatrixMessage()
    message.body = "/cleanup 1"

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), message))

    assert client.deleted == [("!room:example", "$old", "TeeBotus cleanup")]


def test_matrix_cleanup_restores_ref_when_remote_delete_fails(tmp_path) -> None:
    class FailingDeleteClient(FakeMatrixClient):
        async def room_redact(self, room_id: str, event_id: str, reason: str | None = None):
            self.redacted.append((room_id, event_id, reason))
            raise RuntimeError("redact refused")

    client = FailingDeleteClient()
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
    bridge.engine = type("FakeEngine", (), {"process": lambda self, event: [DeleteTrackedMessages(event.chat_id, 1)]})()
    ref = SentMessageRef(
        channel="matrix",
        instance_name="Demo",
        account_id="account-1",
        chat_id="!room:example",
        message_ref="$old",
        ref_kind="matrix_event_id",
    )
    bridge.message_tracker.record(ref)

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), FakeMatrixMessage()))

    assert client.redacted == [("!room:example", "$old", "TeeBotus cleanup")]
    assert bridge.message_tracker.list_for_chat("!room:example", instance_name="Demo", channel="matrix") == [ref]


def test_delete_matrix_message_rejects_niobot_error_response() -> None:
    class ErrorResponse:
        message = "redact refused"
        status_code = "M_FORBIDDEN"

    class Client:
        async def delete_message(self, room_id: str, event_id: str, reason: str | None = None):
            return ErrorResponse()

        async def room_redact(self, *_args, **_kwargs):
            raise AssertionError("room_redact should not be used when delete_message is available")

    try:
        asyncio.run(_delete_matrix_message(Client(), "!room:example", "$old"))
    except MatrixRuntimeError as exc:
        assert str(exc) == "M_FORBIDDEN: redact refused"
    else:
        raise AssertionError("MatrixRuntimeError was not raised")


def test_delete_matrix_message_rejects_room_redact_error_response() -> None:
    class ErrorResponse:
        message = "redact refused"
        status_code = ""

    class Client:
        async def room_redact(self, room_id: str, event_id: str, reason: str | None = None):
            return ErrorResponse()

    try:
        asyncio.run(_delete_matrix_message(Client(), "!room:example", "$old"))
    except MatrixRuntimeError as exc:
        assert str(exc) == "redact refused"
    else:
        raise AssertionError("MatrixRuntimeError was not raised")


def test_delete_matrix_message_rejects_dict_error_response() -> None:
    class Client:
        async def room_redact(self, room_id: str, event_id: str, reason: str | None = None):
            return {"errcode": "M_FORBIDDEN", "error": "redact refused"}

    try:
        asyncio.run(_delete_matrix_message(Client(), "!room:example", "$old"))
    except MatrixRuntimeError as exc:
        assert str(exc) == "M_FORBIDDEN: redact refused"
    else:
        raise AssertionError("MatrixRuntimeError was not raised")


def test_matrix_bridge_tracks_export_files_for_cleanup(tmp_path) -> None:
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
    bridge.engine = type(
        "FakeEngine",
        (),
        {"process": lambda self, event: [ExportFile(event.chat_id, "report.txt", "text/plain", b"hello")]},
    )()

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), FakeMatrixMessage()))

    refs = bridge.message_tracker.pop_for_cleanup(instance_name="Demo", channel="matrix", chat_id="!room:example", count=1)
    assert len(refs) == 1
    assert refs[0].message_ref == "$sent"


def test_matrix_bridge_tracks_polls_for_cleanup(tmp_path) -> None:
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
    bridge.engine = type(
        "FakeEngine",
        (),
        {"process": lambda self, event: [SendPoll(event.chat_id, "Tee?", ("Ja", "Nein"))]},
    )()

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), FakeMatrixMessage()))

    refs = bridge.message_tracker.pop_for_cleanup(instance_name="Demo", channel="matrix", chat_id="!room:example", count=1)
    assert len(refs) == 1
    assert refs[0].message_ref == "$sent"
    assert client.sent[0]["content"]["msgtype"] == "org.matrix.msc3381.poll.start"


def test_matrix_bridge_downloads_inbound_media_before_engine(tmp_path) -> None:
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
    seen = []
    bridge.engine = type("FakeEngine", (), {"process": lambda self, event: seen.append(event) or []})()

    class MediaMessage(FakeMatrixMessage):
        body = "photo.jpg"
        url = "mxc://example/photo"
        source = {"content": {"msgtype": "m.image", "url": "mxc://example/photo", "info": {"mimetype": "image/jpeg"}}}

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), MediaMessage()))

    assert client.downloads == ["mxc://example/photo"]
    assert seen[0].attachments[0].data == b"downloaded"
    assert seen[0].attachments[0].filename == "download.png"
    assert seen[0].attachments[0].content_type == "image/png"


def test_matrix_bridge_downloads_inbound_media_from_disk_response(tmp_path) -> None:
    download_path = tmp_path / "download.bin"
    download_path.write_bytes(b"from disk")

    class DiskDownloadClient(FakeMatrixClient):
        async def download(self, *, mxc: str):
            self.downloads.append(mxc)
            return type("DownloadResponse", (), {"body": download_path, "content_type": "application/pdf", "filename": "disk.pdf"})()

    client = DiskDownloadClient()
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
    seen = []
    bridge.engine = type("FakeEngine", (), {"process": lambda self, event: seen.append(event) or []})()

    class MediaMessage(FakeMatrixMessage):
        body = "photo.jpg"
        url = "mxc://example/photo"
        source = {"content": {"msgtype": "m.file", "url": "mxc://example/photo", "filename": "fallback.pdf"}}

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), MediaMessage()))

    assert client.downloads == ["mxc://example/photo"]
    assert seen[0].attachments[0].data == b"from disk"
    assert seen[0].attachments[0].filename == "disk.pdf"
    assert seen[0].attachments[0].content_type == "application/pdf"


def test_matrix_download_preserves_attachment_metadata_flags() -> None:
    class DownloadClient:
        async def download(self, *, mxc: str):
            return type("DownloadResponse", (), {"body": b"downloaded", "content_type": "application/octet-stream", "filename": ""})()

    event = IncomingEvent(
        event_id="matrix:$media",
        instance="Demo",
        channel="matrix",
        adapter_slot=1,
        identity_key="matrix:user:@alice:example",
        chat_id="!room:example",
        chat_type="private",
        sender_id="@alice:example",
        text="",
        message_ref="$media",
        attachments=(
            IncomingAttachment(
                filename="voice.ogg",
                content_type="audio/ogg",
                base64_data="mxc://example/voice",
                view_once=True,
            ),
        ),
    )

    downloaded = asyncio.run(_download_matrix_event_attachments(DownloadClient(), event))

    assert downloaded.attachments[0].data == b"downloaded"
    assert downloaded.attachments[0].filename == "voice.ogg"
    assert downloaded.attachments[0].content_type == "audio/ogg"
    assert downloaded.attachments[0].view_once is True


def test_matrix_bridge_decrypts_inbound_encrypted_media(tmp_path) -> None:
    from nio.crypto.attachments import encrypted_attachment_generator

    encrypted_parts = list(encrypted_attachment_generator(b"plain image bytes"))
    decrypt_info = encrypted_parts[-1]
    ciphertext = b"".join(part for part in encrypted_parts[:-1] if isinstance(part, bytes))

    class EncryptedDownloadClient(FakeMatrixClient):
        async def download(self, *, mxc: str):
            self.downloads.append(mxc)
            return type("DownloadResponse", (), {"body": ciphertext, "content_type": "application/octet-stream", "filename": "encrypted.jpg"})()

    client = EncryptedDownloadClient()
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
    seen = []
    bridge.engine = type("FakeEngine", (), {"process": lambda self, event: seen.append(event) or []})()

    class MediaMessage(FakeMatrixMessage):
        body = "encrypted.jpg"
        source = {
            "content": {
                "msgtype": "m.image",
                "body": "encrypted.jpg",
                "file": {
                    "url": "mxc://example/encrypted",
                    "mimetype": "image/jpeg",
                    "key": decrypt_info["key"],
                    "hashes": decrypt_info["hashes"],
                    "iv": decrypt_info["iv"],
                },
                "info": {"mimetype": "image/jpeg"},
            }
        }

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), MediaMessage()))

    assert client.downloads == ["mxc://example/encrypted"]
    assert seen[0].attachments[0].data == b"plain image bytes"
    assert seen[0].attachments[0].filename == "encrypted.jpg"
    assert seen[0].attachments[0].content_type == "image/jpeg"
    assert seen[0].attachments[0].base64_data == "mxc://example/encrypted"


def test_matrix_bridge_keeps_media_metadata_when_download_fails(tmp_path) -> None:
    class FailingDownloadClient(FakeMatrixClient):
        async def download(self, *, mxc: str):
            self.downloads.append(mxc)
            raise OSError("download refused")

    client = FailingDownloadClient()
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
    seen = []
    bridge.engine = type("FakeEngine", (), {"process": lambda self, event: seen.append(event) or []})()

    class MediaMessage(FakeMatrixMessage):
        body = "photo.jpg"
        url = "mxc://example/photo"
        source = {"content": {"msgtype": "m.image", "url": "mxc://example/photo", "info": {"mimetype": "image/jpeg"}}}

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), MediaMessage()))

    assert client.downloads == ["mxc://example/photo"]
    assert seen[0].attachments[0].data == b""
    assert seen[0].attachments[0].filename == "photo.jpg"
    assert seen[0].attachments[0].base64_data == "mxc://example/photo"


def test_matrix_bridge_keeps_media_metadata_when_download_has_no_body(tmp_path) -> None:
    class NoBodyDownloadClient(FakeMatrixClient):
        async def download(self, *, mxc: str):
            self.downloads.append(mxc)
            return type("DownloadResponse", (), {"filename": "wrong-name.bin", "content_type": "application/octet-stream"})()

    client = NoBodyDownloadClient()
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
    seen = []
    bridge.engine = type("FakeEngine", (), {"process": lambda self, event: seen.append(event) or []})()

    class MediaMessage(FakeMatrixMessage):
        body = "photo.jpg"
        url = "mxc://example/photo"
        source = {"content": {"msgtype": "m.image", "url": "mxc://example/photo", "info": {"mimetype": "image/jpeg"}}}

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), MediaMessage()))

    assert client.downloads == ["mxc://example/photo"]
    assert seen[0].attachments[0].data == b""
    assert seen[0].attachments[0].filename == "photo.jpg"
    assert seen[0].attachments[0].content_type == "image/jpeg"


def test_matrix_bridge_notifies_old_matrix_identity_route(tmp_path) -> None:
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
    old_identity = "matrix:user:@old:example"
    bridge.account_store.resolve_or_create_account(old_identity)
    bridge.account_store.update_identity_route(old_identity, channel="matrix", chat_id="!old:example", chat_type="private", adapter_slot=1)
    bridge.engine = type(
        "FakeEngine",
        (),
        {
            "process": lambda self, event: [
                NotifyLinkedIdentity(
                    identity_key=old_identity,
                    text="Ein neuer Kommunikationsweg wurde verbunden.",
                    account_id=event.account_id,
                    new_identity_key=event.identity_key,
                )
            ]
        },
    )()

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), FakeMatrixMessage()))

    assert client.sent[0]["room_id"] == "!old:example"
    assert client.sent[0]["content"] == {"msgtype": "m.text", "body": "Ein neuer Kommunikationsweg wurde verbunden."}


def test_matrix_bridge_tracks_linked_identity_notification_when_requested(tmp_path) -> None:
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
    old_identity = "matrix:user:@old:example"
    bridge.account_store.resolve_or_create_account(old_identity)
    bridge.account_store.update_identity_route(old_identity, channel="matrix", chat_id="!old:example", chat_type="private", adapter_slot=1)
    bridge.engine = type(
        "FakeEngine",
        (),
        {
            "process": lambda self, event: [
                NotifyLinkedIdentity(
                    identity_key=old_identity,
                    text="Ein neuer Kommunikationsweg wurde verbunden.",
                    account_id=event.account_id,
                    new_identity_key=event.identity_key,
                    track=True,
                )
            ]
        },
    )()

    asyncio.run(bridge.handle_message(FakeMatrixRoom(), FakeMatrixMessage()))

    refs = bridge.message_tracker.pop_for_cleanup(instance_name="Demo", channel="matrix", chat_id="!old:example", count=1)
    assert len(refs) == 1
    assert refs[0].message_ref == "$sent"


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
    monkeypatch.setattr("TeeBotus.runtime.matrix_runner._import_niobot", lambda: object())
    monkeypatch.setattr("TeeBotus.runtime.matrix_runner.check_matrix_homeservers", lambda _config: ())
    monkeypatch.setattr("TeeBotus.runtime.matrix_runner._matrix_account_thread", lambda *, account, instances_dir: FakeThread(account.slot))
    monkeypatch.setattr(
        "TeeBotus.runtime.matrix_runner.run_matrix_account",
        lambda *, account, instances_dir: calls.append(("blocking", account.slot)),
    )

    assert run_matrix_accounts(config) == 0
    assert calls == [("background", 2), ("blocking", 1)]


def test_matrix_start_fails_before_threads_when_homeserver_unreachable(monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    account = AccountRunConfig(
        instance_name="Demo",
        channel="matrix",
        slot=1,
        label="matrix:1",
        openai_api_key="",
        matrix_homeserver="https://matrix.example",
        matrix_user_id="@bot:example",
        matrix_access_token="token",
    )
    config = RuntimeConfig(
        instances_dir=tmp_path,
        selected_instances=("Demo",),
        channels=("matrix",),
        instances=(InstanceRunConfig("Demo", tmp_path / "Bot_Verhalten.md", (account,)),),
    )
    monkeypatch.setattr("TeeBotus.runtime.matrix_runner._import_niobot", lambda: object())
    monkeypatch.setattr(
        "TeeBotus.runtime.matrix_runner.check_matrix_homeservers",
        lambda _config: (MatrixHomeserverHealth(account=account, ok=False, target="matrix.example:443", error="connection refused"),),
    )
    monkeypatch.setattr("TeeBotus.runtime.matrix_runner.run_matrix_account", lambda **_kwargs: calls.append("started"))

    try:
        run_matrix_accounts(config)
    except MatrixRuntimeError as exc:
        assert "Matrix-Homeserver nicht erreichbar" in str(exc)
    else:
        raise AssertionError("MatrixRuntimeError was not raised")
    assert calls == []


def test_matrix_homeserver_health_uses_normalized_host_port(monkeypatch) -> None:
    calls: list[tuple[tuple[str, int], float]] = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    def fake_create_connection(address, timeout):
        calls.append((address, timeout))
        return FakeSocket()

    monkeypatch.setattr("TeeBotus.runtime.matrix_runner.socket.create_connection", fake_create_connection)

    health = check_matrix_homeserver(
        AccountRunConfig(
            instance_name="Demo",
            channel="matrix",
            slot=1,
            label="matrix:1",
            openai_api_key="",
            matrix_homeserver="https://matrix.example",
            matrix_user_id="@bot:example",
            matrix_access_token="token",
        ),
        timeout_seconds=0.25,
    )

    assert health.ok
    assert health.target == "matrix.example:443"
    assert calls == [(("matrix.example", 443), 0.25)]


def test_matrix_runtime_registers_text_and_media_event_classes() -> None:
    class Nio:
        RoomMessageText = object()
        RoomMessageNotice = object()
        RoomMessageEmote = object()
        RoomMessageFile = object()
        RoomMessageImage = object()
        RoomMessageAudio = object()
        RoomMessageVideo = object()
        RoomEncryptedFile = object()
        RoomEncryptedImage = object()
        RoomEncryptedAudio = object()
        RoomEncryptedVideo = object()
        RoomMessageUnknown = object()

    assert _matrix_message_event_classes(Nio) == (
        Nio.RoomMessageText,
        Nio.RoomMessageNotice,
        Nio.RoomMessageEmote,
        Nio.RoomMessageFile,
        Nio.RoomMessageImage,
        Nio.RoomMessageAudio,
        Nio.RoomMessageVideo,
        Nio.RoomEncryptedFile,
        Nio.RoomEncryptedImage,
        Nio.RoomEncryptedAudio,
        Nio.RoomEncryptedVideo,
        Nio.RoomMessageUnknown,
    )


def test_matrix_homeserver_health_rejects_homeserver_with_path() -> None:
    health = check_matrix_homeserver(
        AccountRunConfig(
            instance_name="Demo",
            channel="matrix",
            slot=1,
            label="matrix:1",
            openai_api_key="",
            matrix_homeserver="https://matrix.example/client",
            matrix_user_id="@bot:example",
            matrix_access_token="token",
        )
    )

    assert not health.ok
    assert "darf keinen Pfad" in health.error
