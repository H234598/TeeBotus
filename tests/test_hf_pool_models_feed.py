from __future__ import annotations

import json

from TeeBotus.llm.hf_pool.models_feed import fetch_hf_pool_models, model_info_by_id, parse_hf_pool_models_payload


class _Response:
    status = 200

    def __init__(self, payload: object) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def close(self) -> None:
        return None


def test_parse_hf_pool_models_payload_extracts_openai_compatible_metadata() -> None:
    models = parse_hf_pool_models_payload(
        {
            "data": [
                {
                    "id": "Qwen/Qwen3-4B-Instruct",
                    "metadata": {"context_length": 32768},
                    "capabilities": {
                        "tool_calling": True,
                        "structured_output": "supported",
                    },
                    "pricing": {"prompt": 0.0, "completion": 0.0},
                    "latency_ms": 123,
                    "throughput_tokens_per_second": "42.5",
                }
            ]
        }
    )

    assert len(models) == 1
    assert models[0].model == "Qwen/Qwen3-4B-Instruct"
    assert models[0].context_length == 32768
    assert models[0].supports_tools is True
    assert models[0].supports_structured_output is True
    assert models[0].pricing == {"prompt": 0.0, "completion": 0.0}
    assert models[0].latency_ms == 123
    assert models[0].throughput_tokens_per_second == 42.5


def test_parse_hf_pool_models_payload_accepts_list_and_builds_lookup() -> None:
    models = parse_hf_pool_models_payload(
        [
            {
                "model_id": "google/gemma",
                "limits": {"max_input_tokens": "8192"},
                "features": ["json_schema"],
            },
            {"name": ""},
        ]
    )

    lookup = model_info_by_id(models)

    assert tuple(lookup) == ("google/gemma",)
    assert lookup["google/gemma"].context_length == 8192
    assert lookup["google/gemma"].supports_structured_output is True


def test_fetch_hf_pool_models_uses_models_endpoint_and_redacts_fetch_errors() -> None:
    calls: list[dict[str, object]] = []

    def opener(request, *, timeout):
        calls.append({"url": request.full_url, "authorization": request.get_header("Authorization"), "timeout": timeout})
        return _Response({"data": [{"id": "model-a", "context_length": 4096}]})

    feed = fetch_hf_pool_models("https://router.huggingface.co/v1", api_key="hf_TESTSECRET123", timeout_seconds=5, opener=opener)

    assert feed.status == "ok"
    assert feed.source == "https://router.huggingface.co/v1/models"
    assert feed.models[0].model == "model-a"
    assert calls == [
        {
            "url": "https://router.huggingface.co/v1/models",
            "authorization": "Bearer hf_TESTSECRET123",
            "timeout": 5,
        }
    ]

    def failing(_request, *, timeout):
        raise OSError("failed Bearer hf_TESTSECRET123")

    failed = fetch_hf_pool_models("https://router.huggingface.co/v1/models", api_key="hf_TESTSECRET123", opener=failing)

    assert failed.status == "unavailable"
    assert failed.source == "https://router.huggingface.co/v1/models"
    assert "hf_TESTSECRET123" not in failed.error
    assert "hf_<REDACTED>" in failed.error
