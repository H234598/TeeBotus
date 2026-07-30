from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from TeeBotus.history_dispatcher_provider_v2_worker import dispatch_provider_v2_batch


def _claim() -> dict[str, Any]:
    return {
        "target_delivery_id": "target_0001",
        "route_plan_id": "route_0001",
        "event_id": "evt_0001",
        "target_id": "telegram",
        "provider_id": "teebotus",
        "provider_schema_version": 1,
        "binding": {
            "schema_version": 1,
            "provider": "teebotus",
            "bridge_capability": "history-dispatcher-telegram-v2",
        },
        "attempt_no": 2,
        "worker_id": "teebotus-worker",
        "capability_version": "history-dispatcher-telegram-v2",
        "claim_token": "token_" + "a" * 40,
        "claim_expires_at": "2026-07-30T22:00:00Z",
        "payload": {"text": "Provider-v2 payload"},
        "successful_recipient_refs": ["already_delivered"],
        "open_recipient_refs": ["open_admin"],
    }


class FakeBridge:
    def __init__(self) -> None:
        self.flush_result = {"delivered": 0, "failed": 0}
        self.claims = [_claim()]
        self.register_result = {
            "ok": True,
            "recipients": [
                {"recipient_ref": "already_delivered", "state": "delivered"},
                {"recipient_ref": "open_admin", "state": "pending"},
            ],
        }
        self.record_result: dict[str, Any] = {
            "ok": True,
            "recipients": [
                {"recipient_ref": "open_admin", "state": "accepted"}
            ],
        }
        self.complete_result: dict[str, Any] = {
            "ok": True,
            "state": "delivered",
        }
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def flush_provider_v2_spool(self) -> dict[str, int]:
        self.calls.append(("flush", {}))
        return dict(self.flush_result)

    async def heartbeat_provider_v2(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("heartbeat", dict(kwargs)))
        return {"ok": True}

    async def claim_provider_v2(self, worker_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("claim", {"worker_id": worker_id, **kwargs}))
        return [dict(claim) for claim in self.claims]

    async def register_provider_v2_recipients(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("register", dict(kwargs)))
        return dict(self.register_result)

    async def renew_provider_v2_claim(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("renew", dict(kwargs)))
        return {"ok": True, "claim_expires_at": "2026-07-30T22:05:00Z"}

    async def record_provider_v2_recipients(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("record", dict(kwargs)))
        return dict(self.record_result)

    async def complete_provider_v2_claim(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("complete", dict(kwargs)))
        return dict(self.complete_result)


def _request_id(phase: str, target_delivery_id: str, attempt_no: int) -> str:
    return f"pv2-{phase}-{target_delivery_id}-{attempt_no}"


def test_provider_v2_worker_skips_claim_when_no_routable_recipient() -> None:
    bridge = FakeBridge()

    result = asyncio.run(
        dispatch_provider_v2_batch(
            bridge,  # type: ignore[arg-type]
            worker_id="teebotus-worker",
            recipient_refs=(),
            send=lambda _claim, _recipient: None,
            request_id_factory=_request_id,
        )
    )

    assert result == {
        "ok": True,
        "blocked": False,
        "reason": "no_routable_recipients",
        "claims": 0,
        "sent": 0,
        "spooled": 0,
        "items": [],
        "status_counts": {},
    }
    assert [name for name, _body in bridge.calls] == ["flush", "heartbeat"]


def test_provider_v2_worker_sends_only_open_recipient_and_completes() -> None:
    bridge = FakeBridge()
    sends: list[tuple[str, str]] = []

    async def send(claim: Mapping[str, Any], recipient_ref: str) -> dict[str, Any]:
        sends.append((str(claim["target_delivery_id"]), recipient_ref))
        return {
            "recipient_ref": recipient_ref,
            "status": "accepted",
            "message_ref_key": "message_open_admin",
        }

    result = asyncio.run(
        dispatch_provider_v2_batch(
            bridge,  # type: ignore[arg-type]
            worker_id="teebotus-worker",
            recipient_refs=("already_delivered", "open_admin"),
            send=send,
            lease_seconds=180,
            request_id_factory=_request_id,
        )
    )

    assert result["ok"] is True
    assert result["blocked"] is False
    assert result["claims"] == 1
    assert result["sent"] == 1
    assert result["status_counts"] == {"accepted": 1}
    assert sends == [("target_0001", "open_admin")]
    assert [name for name, _body in bridge.calls] == [
        "flush",
        "heartbeat",
        "claim",
        "register",
        "renew",
        "record",
        "complete",
        "heartbeat",
    ]
    record = next(body for name, body in bridge.calls if name == "record")
    assert record["outcomes"] == (
        {
            "recipient_ref": "open_admin",
            "status": "accepted",
            "message_ref_key": "message_open_admin",
        },
    )
    complete = next(body for name, body in bridge.calls if name == "complete")
    assert complete["claim_token"].startswith("token_")


def test_provider_v2_worker_blocks_all_new_sends_when_callback_spool_is_not_clean() -> None:
    bridge = FakeBridge()
    bridge.flush_result = {"delivered": 0, "failed": 1}
    sends: list[str] = []

    result = asyncio.run(
        dispatch_provider_v2_batch(
            bridge,  # type: ignore[arg-type]
            worker_id="teebotus-worker",
            recipient_refs=("open_admin",),
            send=lambda _claim, recipient: sends.append(recipient),
            request_id_factory=_request_id,
        )
    )

    assert result["ok"] is False
    assert result["blocked"] is True
    assert result["reason"] == "provider_callback_spool_blocked"
    assert sends == []
    assert [name for name, _body in bridge.calls] == ["flush", "heartbeat"]


def test_provider_v2_worker_does_not_complete_when_recipient_callback_was_spooled() -> None:
    bridge = FakeBridge()
    bridge.register_result = {
        "ok": True,
        "recipients": [{"recipient_ref": "open_admin", "state": "pending"}],
    }
    bridge.record_result = {
        "ok": False,
        "spooled": True,
        "event_id": "record-spooled",
    }

    async def send(_claim: Mapping[str, Any], recipient_ref: str) -> dict[str, Any]:
        return {"recipient_ref": recipient_ref, "status": "accepted"}

    result = asyncio.run(
        dispatch_provider_v2_batch(
            bridge,  # type: ignore[arg-type]
            worker_id="teebotus-worker",
            recipient_refs=("open_admin",),
            send=send,
            request_id_factory=_request_id,
        )
    )

    assert result["ok"] is False
    assert result["blocked"] is True
    assert result["reason"] == "recipient_callback_spooled"
    assert result["spooled"] == 1
    assert "complete" not in [name for name, _body in bridge.calls]


def test_provider_v2_worker_records_transport_failure_instead_of_raising() -> None:
    bridge = FakeBridge()
    bridge.register_result = {
        "ok": True,
        "recipients": [{"recipient_ref": "open_admin", "state": "pending"}],
    }

    async def send(_claim: Mapping[str, Any], _recipient_ref: str) -> dict[str, Any]:
        raise TimeoutError("transport timed out")

    result = asyncio.run(
        dispatch_provider_v2_batch(
            bridge,  # type: ignore[arg-type]
            worker_id="teebotus-worker",
            recipient_refs=("open_admin",),
            send=send,
            request_id_factory=_request_id,
        )
    )

    assert result["status_counts"] == {"failed": 1}
    record = next(body for name, body in bridge.calls if name == "record")
    assert record["outcomes"] == (
        {
            "recipient_ref": "open_admin",
            "status": "failed",
            "reason_code": "send_error_timeouterror",
        },
    )
