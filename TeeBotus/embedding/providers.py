from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote
from urllib.request import Request, urlopen

from TeeBotus.embedding.base import EmbeddingProvider
from TeeBotus.llm.hf_pool.redaction import redact_hf_secrets


EmbeddingOpener = Callable[..., Any]


@dataclass(frozen=True)
class FakeEmbeddingProvider:
    model_name: str = "teebotus-fake-hash-embedding-v1"
    dimensions: int = 64

    def embed_text(self, text: str) -> list[float]:
        size = _validate_dimensions(self.dimensions)
        vector = [0.0] * size
        tokens = _embedding_tokens(text)
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:2], "big") % size
            sign = 1.0 if digest[2] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm <= 0:
            return vector
        return [round(value / norm, 6) for value in vector]

    def embed_texts(self, texts: list[str], *, purpose: str = "") -> list[list[float]]:
        return [self.embed_text(text) for text in texts]


@dataclass(frozen=True)
class HFEmbeddingProvider:
    model_name: str = "intfloat/multilingual-e5-small"
    dimensions: int = 384
    endpoint: str = ""
    api_key: str = ""
    timeout_seconds: int = 60
    opener: EmbeddingOpener | None = None

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str], *, purpose: str = "") -> list[list[float]]:
        cleaned = [str(text or "") for text in texts]
        if not cleaned:
            return []
        request = self._request(cleaned)
        try:
            response = (self.opener or urlopen)(request, timeout=max(1, int(self.timeout_seconds)))
            status_code = int(getattr(response, "status", getattr(response, "code", 200)) or 200)
            raw = response.read() if hasattr(response, "read") else b"{}"
            close = getattr(response, "close", None)
            if callable(close):
                close()
        except Exception as exc:  # noqa: BLE001 - optional provider boundary redacts secrets.
            raise RuntimeError(redact_hf_secrets(f"HF embedding request failed: {exc}")) from exc
        if not 200 <= status_code < 300:
            raise RuntimeError(f"HF embedding request failed: HTTP {status_code}")
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else []
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("HF embedding endpoint returned invalid JSON") from exc
        vectors = _normalize_embedding_payload(payload, expected_count=len(cleaned))
        for vector in vectors:
            _validate_embedding_vector(vector, self.dimensions)
        return vectors

    def _request(self, texts: list[str]) -> Request:
        endpoint = _embedding_endpoint(self.endpoint, self.model_name)
        body = {"inputs": texts, "options": {"wait_for_model": True}}
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return Request(endpoint, data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), method="POST", headers=headers)


def _embedding_tokens(text: str) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    for match in re.finditer(r"\b\w{2,}\b", str(text or "").casefold(), re.UNICODE):
        token = match.group(0).strip("_")
        if not token or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
        if len(tokens) >= 128:
            break
    return tokens


def _validate_dimensions(value: int) -> int:
    dimensions = int(value)
    if dimensions < 1:
        raise ValueError("Embedding dimensions must be positive.")
    return dimensions


def _embedding_endpoint(endpoint: str, model_name: str) -> str:
    configured = str(endpoint or "").strip().rstrip("/")
    if configured:
        return configured
    model_path = quote(str(model_name or "").strip(), safe="/")
    return f"https://api-inference.huggingface.co/pipeline/feature-extraction/{model_path}"


def _normalize_embedding_payload(payload: Any, *, expected_count: int) -> list[list[float]]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        vectors = []
        for item in payload["data"]:
            if isinstance(item, dict):
                vectors.append(_coerce_vector(item.get("embedding")))
        return vectors
    if isinstance(payload, list):
        if expected_count == 1 and payload and all(isinstance(value, (int, float)) for value in payload):
            return [_coerce_vector(payload)]
        vectors = [_coerce_vector(item) for item in payload if isinstance(item, list) and all(isinstance(value, (int, float)) for value in item)]
        if len(vectors) == expected_count:
            return vectors
        pooled = [_pool_token_vectors(item) for item in payload if isinstance(item, list)]
        pooled = [vector for vector in pooled if vector]
        if len(pooled) == expected_count:
            return pooled
    raise RuntimeError("HF embedding endpoint returned unsupported payload shape")


def _pool_token_vectors(value: Any) -> list[float]:
    if not isinstance(value, list) or not value:
        return []
    if all(isinstance(item, (int, float)) for item in value):
        return _coerce_vector(value)
    token_vectors = [_coerce_vector(item) for item in value if isinstance(item, list)]
    if not token_vectors:
        return []
    width = len(token_vectors[0])
    if width < 1:
        return []
    totals = [0.0] * width
    for vector in token_vectors:
        if len(vector) != width:
            continue
        for index, item in enumerate(vector):
            totals[index] += item
    return [round(item / len(token_vectors), 6) for item in totals]


def _coerce_vector(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    return [float(item) for item in value if isinstance(item, (int, float))]


def _validate_embedding_vector(vector: list[float], dimensions: int) -> None:
    expected = _validate_dimensions(dimensions)
    if len(vector) != expected:
        raise RuntimeError(f"HF embedding vector dimensions mismatch: expected {expected}, got {len(vector)}")
