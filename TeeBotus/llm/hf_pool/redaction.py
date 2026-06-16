from __future__ import annotations

import re

HF_TOKEN_RE = re.compile(r"\bhf_[A-Za-z0-9]{8,}\b")
BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)


def redact_hf_secrets(value: object) -> str:
    text = str(value or "")
    text = HF_TOKEN_RE.sub("hf_<REDACTED>", text)
    return BEARER_RE.sub("Bearer <REDACTED>", text)
