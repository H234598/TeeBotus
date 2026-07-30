from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from TeeBotus.history_dispatcher_bridge import (
    PROVIDER_API_SCHEMA_VERSION,
    TEEBOTUS_CAPABILITY_V2,
    CallbackSpool,
    HistoryDispatcherBridge,
    HistoryDispatcherProtocolError,
    ProviderCallbackSpool,
)
from TeeBotus.runtime.accounts import StaticSecretProvider


def _provider_spool(tmp_path: Path) -> ProviderCallbackSpool:
    return ProviderCallbackSpool(
        tmp_path / "provider-spool",
        secret_provider=StaticSecretProvider(b"k" * 32),
        instance_name="TeeBotus_Logger",
    )


class RecordingClient:
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


def _reclaim_response(*, attempt_no: int = 2, token_char: str = "n") -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "ok": True,
            "schema_version": PROVIDER_API_SCHEMA_VERSION,
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
                    "attempt_no": attempt_no,
                    "worker_id": "teebotus-worker",
                    "capability_version": TEEBOTUS_CAPABILITY_V2,
                    "claim_token": "token_" + token_char * 40,
                    "claim_expires_at": "2026-07-31T00:05:00Z",
                    "payload": {"text": "reconciliation payload"},
                    "successful_recipient_refs": [],
                    "open_recipient_refs": ["status_admin_primary"],
                    "reconciliation_only": True,
                }
            ],
        },
    }


def _success() -> dict[str, Any]:
    return {"ok": True, "data": {"ok": True, "recipients": []}}


def test_expired_spooled_callback_is_reclaimed_rewritten_and_replayed(
    tmp_path: Path,
) -> None:
    client = RecordingClient(
        [
            HistoryDispatcherProtocolError("socket unavailable"),
            HistoryDispatcherProtocolError("claim has expired"),
            _reclaim_response(),
            HistoryDispatcherProtocolError("socket unavailable after rebind"),
            _success(),
        ]
    )
    provider_spool = _provider_spool(tmp_path)
    bridge = HistoryDispatcherBridge(
        client,  # type: ignore[arg-type]
        CallbackSpool(tmp_path / "legacy-spool"),
        provider_spool=provider_spool,
    )
    old_token = "token_" + "a" * 40

    spooled = asyncio.run(
        bridge.record_provider_v2_recipients(
            target_delivery_id="target_0001",
            worker_id="teebotus-worker",
            claim_token=old_token,
            outcomes=(
                {
                    "recipient_ref": "status_admin_primary",
                    "status": "accepted",
                },
            ),
            previous_attempt_no=1,
            request_id="record-attempt-1",
        )
    )
    assert spooled["spooled"] is True
    path, original = provider_spool.events()[0]
    assert original["reclaim"] == {
        "target_delivery_id": "target_0001",
        "provider_id": "teebotus",
        "worker_id": "teebotus-worker",
        "capability_version": TEEBOTUS_CAPABILITY_V2,
        "previous_attempt_no": 1,
    }
    assert old_token.encode("utf-8") not in path.read_bytes()

    first_flush = asyncio.run(bridge.flush_provider_v2_spool())

    assert first_flush == {"delivered": 0, "failed": 1}
    path, rebound = provider_spool.events()[0]
    new_token = "token_" + "n" * 40
    assert rebound["body"]["claim_token"] == new_token
    assert rebound["request_id"] != "record-attempt-1"
    assert rebound["reclaim"]["previous_attempt_no"] == 2
    assert new_token.encode("utf-8") not in path.read_bytes()
    assert [operation for operation, _body, _request_id in client.calls[:4]] == [
        "provider.v2.record_recipients",
        "provider.v2.record_recipients",
        "provider.v2.reclaim",
        "provider.v2.record_recipients",
    ]
    reclaim_body = client.calls[2][1]
    assert reclaim_body == {
        "target_delivery_id": "target_0001",
        "provider_id": "teebotus",
        "worker_id": "teebotus-worker",
        "capability_version": TEEBOTUS_CAPABILITY_V2,
        "previous_attempt_no": 1,
        "lease_seconds": 120,
    }

    second_flush = asyncio.run(bridge.flush_provider_v2_spool())

    assert second_flush == {"delivered": 1, "failed": 0}
    assert provider_spool.events() == []
    assert client.calls[-1][0] == "provider.v2.record_recipients"
    assert client.calls[-1][1]["claim_token"] == new_token


def test_non_expiry_callback_failure_does_not_attempt_reclaim(tmp_path: Path) -> None:
    client = RecordingClient(
        [
            HistoryDispatcherProtocolError("socket unavailable"),
            HistoryDispatcherProtocolError("permission denied"),
        ]
    )
    provider_spool = _provider_spool(tmp_path)
    bridge = HistoryDispatcherBridge(
        client,  # type: ignore[arg-type]
        CallbackSpool(tmp_path / "legacy-spool"),
        provider_spool=provider_spool,
    )
    asyncio.run(
        bridge.complete_provider_v2_claim(
            target_delivery_id="target_0001",
            worker_id="teebotus-worker",
            claim_token="token_" + "a" * 40,
            previous_attempt_no=1,
            request_id="complete-attempt-1",
        )
    )

    result = asyncio.run(bridge.flush_provider_v2_spool())

    assert result == {"delivered": 0, "failed": 1}
    assert [call[0] for call in client.calls] == [
        "provider.v2.complete",
        "provider.v2.complete",
    ]
    assert len(provider_spool.events()) == 1


def test_empty_or_invalid_reclaim_keeps_original_callback_blocked(tmp_path: Path) -> None:
    empty_reclaim = {
        "ok": True,
        "data": {"ok": True, "schema_version": 2, "claims": []},
    }
    client = RecordingClient(
        [
            HistoryDispatcherProtocolError("socket unavailable"),
            HistoryDispatcherProtocolError("target delivery is not actively claimed"),
            empty_reclaim,
        ]
    )
    provider_spool = _provider_spool(tmp_path)
    bridge = HistoryDispatcherBridge(
        client,  # type: ignore[arg-type]
        CallbackSpool(tmp_path / "legacy-spool"),
        provider_spool=provider_spool,
    )
    asyncio.run(
        bridge.complete_provider_v2_claim(
            target_delivery_id="target_0001",
            worker_id="teebotus-worker",
            claim_token="token_" + "a" * 40,
            previous_attempt_no=1,
            request_id="complete-attempt-1",
        )
    )

    result = asyncio.run(bridge.flush_provider_v2_spool())

    assert result == {"delivered": 0, "failed": 1}
    assert len(provider_spool.events()) == 1
    assert client.calls[-1][0] == "provider.v2.reclaim"
