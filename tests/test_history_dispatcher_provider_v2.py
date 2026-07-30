from __future__ import annotations

import asyncio
import json
import socketserver
import struct
import threading
from pathlib import Path
from typing import Any

import pytest

from TeeBotus.history_dispatcher_bridge import (
    PROVIDER_API_SCHEMA_VERSION,
    PROVIDER_V2_OPERATIONS,
    TEEBOTUS_CAPABILITY_V2,
    CallbackSpool,
    HistoryDispatcherBridge,
    HistoryDispatcherClient,
    HistoryDispatcherProtocolError,
    ProviderCallbackSpool,
)
from TeeBotus.runtime.accounts import StaticSecretProvider


FIXTURE = Path(__file__).parent / "fixtures" / "provider-v2" / "contract.json"


def _provider_spool(tmp_path: Path) -> ProviderCallbackSpool:
    return ProviderCallbackSpool(
        tmp_path / "provider-spool",
        secret_provider=StaticSecretProvider(b"k" * 32),
        instance_name="TeeBotus_Logger",
    )


class _RequestCaptureHandler(socketserver.StreamRequestHandler):
    requests: list[dict[str, Any]] = []

    def handle(self) -> None:
        raw_size = self.rfile.read(4)
        if len(raw_size) != 4:
            return
        size = struct.unpack("!I", raw_size)[0]
        request = json.loads(self.rfile.read(size).decode("utf-8"))
        self.__class__.requests.append(request)
        if request["operation"] == "provider.v2.claim":
            data: dict[str, Any] = {
                "ok": True,
                "schema_version": 2,
                "claims": [],
            }
        else:
            data = {"ok": True}
        response = json.dumps(
            {"ok": True, "data": data},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.wfile.write(struct.pack("!I", len(response)) + response)


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def _server(tmp_path: Path) -> tuple[_Server, threading.Thread, Path]:
    socket_path = tmp_path / "runtime" / "control.sock"
    socket_path.parent.mkdir(parents=True)
    _RequestCaptureHandler.requests = []
    server = _Server(str(socket_path), _RequestCaptureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, socket_path


def test_provider_v2_fixture_matches_dispatcher_contract_and_is_secret_free() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert fixture["schema_version"] == PROVIDER_API_SCHEMA_VERSION == 2
    assert tuple(fixture["operations"]) == PROVIDER_V2_OPERATIONS
    assert fixture["capability"] == TEEBOTUS_CAPABILITY_V2
    rendered = json.dumps(fixture, ensure_ascii=False, sort_keys=True)
    for forbidden in ("bot_token", "chat_id", "123456789:", "-1001234567890"):
        assert forbidden not in rendered


def test_client_preserves_explicit_provider_request_id(tmp_path: Path) -> None:
    server, thread, socket_path = _server(tmp_path)
    try:
        client = HistoryDispatcherClient(socket_path)
        response = client.request(
            "provider.v2.claim",
            {
                "target_id": "telegram",
                "provider_id": "teebotus",
                "worker_id": "teebotus-worker",
                "capability_version": TEEBOTUS_CAPABILITY_V2,
            },
            request_id="stable-claim-request",
        )

        assert response["ok"] is True
        assert _RequestCaptureHandler.requests == [
            {
                "protocol_version": 1,
                "request_id": "stable-claim-request",
                "operation": "provider.v2.claim",
                "body": {
                    "target_id": "telegram",
                    "provider_id": "teebotus",
                    "worker_id": "teebotus-worker",
                    "capability_version": TEEBOTUS_CAPABILITY_V2,
                },
            }
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class _RecordingClient:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any], str | None]] = []

    async def request_async(
        self,
        operation: str,
        body: dict[str, Any] | None = None,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append((operation, dict(body or {}), request_id))
        if not self.responses:
            raise AssertionError("unexpected provider request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, dict)
        return response


def _claim_response() -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "ok": True,
            "schema_version": 2,
            "claims": [
                {
                    "target_delivery_id": "target_0001",
                    "route_plan_id": "route_0001",
                    "event_id": "evt_0001",
                    "target_id": "telegram",
                    "provider_id": "teebotus",
                    "provider_schema_version": 1,
                    "binding": {
                        "schema_version": 1,
                        "provider": "teebotus",
                        "bridge_capability": TEEBOTUS_CAPABILITY_V2,
                    },
                    "attempt_no": 1,
                    "worker_id": "teebotus-worker",
                    "capability_version": TEEBOTUS_CAPABILITY_V2,
                    "claim_token": "token_" + "a" * 40,
                    "claim_expires_at": "2026-07-30T21:00:00Z",
                    "payload": {"text": "Visible result"},
                    "successful_recipient_refs": [],
                    "open_recipient_refs": [],
                }
            ],
        },
    }


def test_bridge_provider_v2_claim_uses_fixed_provider_capability_and_request_id(
    tmp_path: Path,
) -> None:
    client = _RecordingClient([_claim_response()])
    bridge = HistoryDispatcherBridge(
        client,  # type: ignore[arg-type]
        CallbackSpool(tmp_path / "legacy-spool"),
        provider_spool=_provider_spool(tmp_path),
    )

    claims = asyncio.run(
        bridge.claim_provider_v2(
            "teebotus-worker",
            limit=20,
            lease_seconds=120,
            request_id="claim-request-1",
        )
    )

    assert len(claims) == 1
    assert claims[0]["claim_token"].startswith("token_")
    assert client.calls == [
        (
            "provider.v2.claim",
            {
                "target_id": "telegram",
                "provider_id": "teebotus",
                "worker_id": "teebotus-worker",
                "capability_version": TEEBOTUS_CAPABILITY_V2,
                "limit": 20,
                "lease_seconds": 120,
            },
            "claim-request-1",
        )
    ]


def test_bridge_provider_v2_rejects_wrong_schema_and_provider(tmp_path: Path) -> None:
    wrong_schema = _claim_response()
    wrong_schema["data"]["schema_version"] = 3
    wrong_provider = _claim_response()
    wrong_provider["data"]["claims"][0]["provider_id"] = "history_dispatcher"
    client = _RecordingClient([wrong_schema, wrong_provider])
    bridge = HistoryDispatcherBridge(
        client,  # type: ignore[arg-type]
        CallbackSpool(tmp_path / "legacy-spool"),
        provider_spool=_provider_spool(tmp_path),
    )

    with pytest.raises(HistoryDispatcherProtocolError, match="schema"):
        asyncio.run(bridge.claim_provider_v2("worker", request_id="wrong-schema"))
    with pytest.raises(HistoryDispatcherProtocolError, match="provider"):
        asyncio.run(bridge.claim_provider_v2("worker", request_id="wrong-provider"))


def test_bridge_provider_v2_register_record_complete_and_heartbeat(tmp_path: Path) -> None:
    client = _RecordingClient(
        [
            {"ok": True, "data": {"ok": True, "recipients": []}},
            {"ok": True, "data": {"ok": True, "recipients": []}},
            {"ok": True, "data": {"ok": True, "state": "delivered"}},
            {"ok": True, "data": {"ok": True}},
        ]
    )
    bridge = HistoryDispatcherBridge(
        client,  # type: ignore[arg-type]
        CallbackSpool(tmp_path / "legacy-spool"),
        provider_spool=_provider_spool(tmp_path),
    )
    token = "token_" + "b" * 40

    asyncio.run(
        bridge.register_provider_v2_recipients(
            target_delivery_id="target_0001",
            worker_id="worker",
            claim_token=token,
            recipient_refs=("status_admin_primary",),
            request_id="register-1",
        )
    )
    asyncio.run(
        bridge.record_provider_v2_recipients(
            target_delivery_id="target_0001",
            worker_id="worker",
            claim_token=token,
            outcomes=(
                {
                    "recipient_ref": "status_admin_primary",
                    "status": "accepted",
                },
            ),
            request_id="record-1",
        )
    )
    completed = asyncio.run(
        bridge.complete_provider_v2_claim(
            target_delivery_id="target_0001",
            worker_id="worker",
            claim_token=token,
            request_id="complete-1",
        )
    )
    asyncio.run(
        bridge.heartbeat_provider_v2(
            worker_id="worker",
            state="idle",
            details={"queue_depth": 0},
            request_id="heartbeat-1",
        )
    )

    assert completed["state"] == "delivered"
    assert [call[0] for call in client.calls] == [
        "provider.v2.register_recipients",
        "provider.v2.record_recipients",
        "provider.v2.complete",
        "provider.v2.heartbeat",
    ]
    assert client.calls[-1][1]["provider_id"] == "teebotus"
    assert client.calls[-1][1]["capability_version"] == TEEBOTUS_CAPABILITY_V2


def test_provider_callback_spool_is_encrypted_and_replays_exact_request(
    tmp_path: Path,
) -> None:
    unavailable = HistoryDispatcherProtocolError("temporarily unavailable")
    client = _RecordingClient(
        [
            unavailable,
            {"ok": True, "data": {"ok": True, "recipients": []}},
        ]
    )
    provider_spool = _provider_spool(tmp_path)
    bridge = HistoryDispatcherBridge(
        client,  # type: ignore[arg-type]
        CallbackSpool(tmp_path / "legacy-spool"),
        provider_spool=provider_spool,
    )
    token = "token_" + "c" * 40

    result = asyncio.run(
        bridge.record_provider_v2_recipients(
            target_delivery_id="target_0001",
            worker_id="worker",
            claim_token=token,
            outcomes=(
                {
                    "recipient_ref": "status_admin_primary",
                    "status": "accepted",
                },
            ),
            request_id="record-stable-1",
        )
    )
    assert result["spooled"] is True
    events = provider_spool.events()
    assert len(events) == 1
    path, envelope = events[0]
    assert token.encode("utf-8") not in path.read_bytes()
    assert envelope["operation"] == "provider.v2.record_recipients"
    assert envelope["request_id"] == "record-stable-1"
    assert envelope["body"]["claim_token"] == token

    flushed = asyncio.run(bridge.flush_provider_v2_spool())

    assert flushed == {"delivered": 1, "failed": 0}
    assert provider_spool.events() == []
    assert client.calls[0] == client.calls[1]
