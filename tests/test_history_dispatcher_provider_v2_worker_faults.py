from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from TeeBotus.history_dispatcher_provider_v2_worker import dispatch_provider_v2_batch


class FaultBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.complete_result: dict[str, Any] = {
            "ok": True,
            "state": "partial",
        }
        self.register_state = "possible_duplicate"

    async def flush_provider_v2_spool(self) -> dict[str, int]:
        self.calls.append(("flush", {}))
        return {"delivered": 0, "failed": 0}

    async def heartbeat_provider_v2(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("heartbeat", dict(kwargs)))
        return {"ok": True}

    async def claim_provider_v2(self, worker_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("claim", {"worker_id": worker_id, **kwargs}))
        return [
            {
                "target_delivery_id": "target_fault",
                "route_plan_id": "route_fault",
                "event_id": "evt_fault",
                "target_id": "telegram",
                "provider_id": "teebotus",
                "provider_schema_version": 1,
                "binding": {
                    "schema_version": 1,
                    "provider": "teebotus",
                    "bridge_capability": "history-dispatcher-telegram-v2",
                },
                "attempt_no": 3,
                "worker_id": worker_id,
                "capability_version": "history-dispatcher-telegram-v2",
                "claim_token": "token_" + "f" * 40,
                "claim_expires_at": "2026-07-30T22:00:00Z",
                "payload": {"text": "fault payload"},
                "successful_recipient_refs": [],
                "open_recipient_refs": ["uncertain_admin"],
            }
        ]

    async def register_provider_v2_recipients(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("register", dict(kwargs)))
        return {
            "ok": True,
            "recipients": [
                {
                    "recipient_ref": "uncertain_admin",
                    "state": self.register_state,
                }
            ],
        }

    async def renew_provider_v2_claim(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("renew", dict(kwargs)))
        return {"ok": True}

    async def record_provider_v2_recipients(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("record", dict(kwargs)))
        return {"ok": True, "recipients": []}

    async def complete_provider_v2_claim(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("complete", dict(kwargs)))
        return dict(self.complete_result)


def _request_id(phase: str, target_delivery_id: str, attempt_no: int) -> str:
    return f"pv2-{phase}-{target_delivery_id}-{attempt_no}"


def test_possible_duplicate_recipient_is_never_sent_again() -> None:
    bridge = FaultBridge()
    sends: list[str] = []

    result = asyncio.run(
        dispatch_provider_v2_batch(
            bridge,  # type: ignore[arg-type]
            worker_id="teebotus-worker",
            recipient_refs=("uncertain_admin",),
            send=lambda _claim, recipient: sends.append(recipient),
            request_id_factory=_request_id,
        )
    )

    assert sends == []
    assert result["sent"] == 0
    assert "renew" not in [name for name, _body in bridge.calls]
    assert "record" not in [name for name, _body in bridge.calls]
    assert "complete" in [name for name, _body in bridge.calls]


def test_spooled_completion_blocks_batch_after_recipient_result_was_recorded() -> None:
    bridge = FaultBridge()
    bridge.register_state = "pending"
    bridge.complete_result = {
        "ok": False,
        "spooled": True,
        "event_id": "completion-spooled",
    }

    async def send(_claim: Mapping[str, Any], recipient_ref: str) -> dict[str, Any]:
        return {
            "recipient_ref": recipient_ref,
            "status": "accepted",
        }

    result = asyncio.run(
        dispatch_provider_v2_batch(
            bridge,  # type: ignore[arg-type]
            worker_id="teebotus-worker",
            recipient_refs=("uncertain_admin",),
            send=send,
            request_id_factory=_request_id,
        )
    )

    assert result["ok"] is False
    assert result["blocked"] is True
    assert result["reason"] == "completion_callback_spooled"
    assert result["spooled"] == 1
    assert [name for name, _body in bridge.calls].index("record") < [
        name for name, _body in bridge.calls
    ].index("complete")
