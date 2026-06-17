from __future__ import annotations

import re

HF_TOKEN_RE = re.compile(r"hf_[A-Za-z0-9]{8,}")
BEARER_RE = re.compile(r"\bBearer\s+[^,\s;\"')\]}]+", re.IGNORECASE)
URL_SECRET_PARAM_RE = re.compile(
    r"(?i)([?&#](?:api[_-]?key|access[_-]?token|token|secret|password|key)=)([^&#\s]+)"
)
ASSIGNMENT_SECRET_RE = re.compile(
    r"\b(api[_-]?key|access[_-]?token|token|secret|password)=([^,&#\s;\"')\]}]+)",
    re.IGNORECASE,
)
URL_USERINFO_RE = re.compile(r"\b(https?://)([^/@\s]+)@")
ENV_NAME_RE = re.compile(r"[A-Z][A-Z0-9_]{2,}")


def redact_hf_secrets(value: object) -> str:
    text = str(value or "")
    text = BEARER_RE.sub("Bearer <REDACTED>", text)
    text = HF_TOKEN_RE.sub("hf_<REDACTED>", text)
    text = URL_SECRET_PARAM_RE.sub(r"\1<REDACTED>", text)
    text = ASSIGNMENT_SECRET_RE.sub(_redact_assignment_secret, text)
    return URL_USERINFO_RE.sub(r"\1<REDACTED>@", text)


def _redact_assignment_secret(match: re.Match[str]) -> str:
    key = match.group(1)
    value = match.group(2)
    if ENV_NAME_RE.fullmatch(value):
        return match.group(0)
    return f"{key}=<REDACTED>"
