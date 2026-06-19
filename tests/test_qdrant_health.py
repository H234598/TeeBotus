from __future__ import annotations

import json
from urllib.error import URLError

from TeeBotus.runtime.qdrant import MAX_QDRANT_RESPONSE_BYTES, check_qdrant_health, format_qdrant_status_line, resolve_qdrant_url


class _Response:
    def __init__(self, status: int = 200, payload: object | None = None) -> None:
        self.status = status
        self.payload = payload
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        if self.payload is None:
            return b""
        raw = json.dumps(self.payload).encode("utf-8")
        return raw if size is None or size < 0 else raw[:size]

    def close(self) -> None:
        self.closed = True


def test_resolve_qdrant_url_allows_only_local_base_urls() -> None:
    assert resolve_qdrant_url("http://127.0.0.1:6333") == "http://127.0.0.1:6333"
    assert resolve_qdrant_url("http://localhost:6333/") == "http://localhost:6333"
    assert resolve_qdrant_url(None, env={"TEEBOTUS_QDRANT_URL": "http://[::1]:6333"}) == "http://[::1]:6333"


def test_resolve_qdrant_url_rejects_public_or_secret_targets() -> None:
    bad_urls = (
        "https://qdrant.example.test:6333",
        "http://user:pass@127.0.0.1:6333",
        "http://127.0.0.1:6333/collections",
        "http://127.0.0.1:6333?api-key=secret",
        "http://127.0.0.1",
        "http://127.0.0.1:0",
    )

    for url in bad_urls:
        try:
            resolve_qdrant_url(url)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected Qdrant URL to be rejected: {url}")


def test_check_qdrant_health_reports_reachable() -> None:
    seen: list[str] = []

    def opener(request, *, timeout):
        seen.append(request.full_url)
        assert timeout > 0
        return _Response(200)

    health = check_qdrant_health("http://127.0.0.1:6333", opener=opener)

    assert health.ok is True
    assert health.status == "reachable"
    assert health.error == ""
    assert seen == ["http://127.0.0.1:6333/collections"]
    assert format_qdrant_status_line(health) == "qdrant=127.0.0.1:6333 status=reachable"


def test_check_qdrant_health_reports_unreachable_as_nonfatal_fallback() -> None:
    def opener(_request, *, timeout):
        assert timeout > 0
        raise URLError("connection refused")

    health = check_qdrant_health("http://127.0.0.1:6333", opener=opener)
    line = format_qdrant_status_line(health)

    assert health.ok is False
    assert health.status == "unreachable"
    assert "connection refused" in health.error
    assert line.startswith("qdrant=127.0.0.1:6333 status=unreachable fallback=keyword_memory_search")


def test_check_qdrant_health_rejects_unexpected_success_payload_status() -> None:
    response = _Response(200, {"status": "error", "result": {"collections": []}})

    def opener(_request, *, timeout):
        assert timeout > 0
        return response

    health = check_qdrant_health("http://127.0.0.1:6333", opener=opener)

    assert health.ok is False
    assert health.status == "unreachable"
    assert health.error == "unexpected Qdrant status: error"
    assert response.closed is True


def test_check_qdrant_health_rejects_oversized_response() -> None:
    class OversizedResponse:
        status = 200
        closed = False

        def read(self, size: int = -1) -> bytes:
            assert size == MAX_QDRANT_RESPONSE_BYTES + 1
            return b"{" + (b"x" * MAX_QDRANT_RESPONSE_BYTES)

        def close(self) -> None:
            self.closed = True

    response = OversizedResponse()

    def opener(_request, *, timeout):
        assert timeout > 0
        return response

    health = check_qdrant_health("http://127.0.0.1:6333", opener=opener)

    assert health.ok is False
    assert health.status == "unreachable"
    assert health.error == "Qdrant response too large"
    assert response.closed is True


def test_check_qdrant_health_reports_invalid_as_nonfatal_fallback() -> None:
    health = check_qdrant_health("https://qdrant.example.test:6333")

    assert health.ok is False
    assert health.status == "invalid"
    assert "local" in health.error
    assert "fallback=keyword_memory_search" in format_qdrant_status_line(health)
