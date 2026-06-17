from __future__ import annotations

from TeeBotus.llm.hf_pool.redaction import redact_hf_secrets


def test_redact_hf_secrets_removes_hf_tokens_and_bearer_values() -> None:
    text = redact_hf_secrets("bad hf_TESTSECRET123 and Authorization: Bearer hf_TESTSECRET456")

    assert "hf_TESTSECRET" not in text
    assert "Bearer hf_" not in text
    assert "hf_<REDACTED>" in text
    assert "Bearer <REDACTED>" in text


def test_redact_hf_secrets_removes_url_and_assignment_secret_values() -> None:
    text = redact_hf_secrets(
        "url=https://router.example/v1/models?api_key=plain-secret&token=hf_TESTSECRET123 "
        "callback=https://plain-user:plain-pass@example.test/path "
        "access_token=matrix-secret secret=local-secret password=topsecret token=HF_TOKEN_MAIN"
    )

    assert "plain-secret" not in text
    assert "hf_TESTSECRET123" not in text
    assert "plain-user:plain-pass" not in text
    assert "matrix-secret" not in text
    assert "local-secret" not in text
    assert "topsecret" not in text
    assert "?api_key=<REDACTED>" in text
    assert "&token=<REDACTED>" in text
    assert "https://<REDACTED>@example.test/path" in text
    assert "access_token=<REDACTED>" in text
    assert "secret=<REDACTED>" in text
    assert "password=<REDACTED>" in text
    assert "token=HF_TOKEN_MAIN" in text
