from __future__ import annotations

import json

from TeeBotus.llm.hf_pool.doctor import main as doctor_main
from TeeBotus.llm.hf_pool.health import check_hf_pool, format_hf_pool_status_lines
from TeeBotus.llm.hf_pool.state import SQLiteHFPoolRuntimeStateStore


class _Response:
    status = 200

    def read(self) -> bytes:
        return json.dumps(
            {
                "id": "health-ok",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            }
        ).encode("utf-8")

    def close(self) -> None:
        return None


def test_hf_pool_doctor_reports_missing_config(tmp_path):
    health = check_hf_pool(config_path=tmp_path / "missing.yaml")
    lines = format_hf_pool_status_lines(health)

    assert health.status == "not_configured"
    assert lines[0].startswith("hf_pool=default status=not_configured")


def test_hf_pool_doctor_reports_malformed_config_as_broken(tmp_path):
    path = tmp_path / "hf_pool.yaml"
    path.write_text("[]", encoding="utf-8")

    health = check_hf_pool(config_path=path)
    lines = format_hf_pool_status_lines(health)

    assert health.status == "broken"
    assert lines[0].startswith("hf_pool=default status=broken")
    assert "root must be a mapping" in lines[0]


def test_hf_pool_doctor_reports_missing_key_without_secret_leak(tmp_path):
    path = tmp_path / "hf_pool.yaml"
    path.write_text(
        json.dumps(
            {
                "pools": {
                    "default": {
                        "enabled": True,
                        "targets": [
                            {
                                "name": "needs_key",
                                "api_key_env": "HF_TOKEN_MAIN",
                                "model": "Qwen/Qwen3-4B-Instruct-2507",
                            }
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    health = check_hf_pool(config_path=path, env={"HF_TOKEN_MAIN": ""})
    lines = format_hf_pool_status_lines(health)

    assert health.status == "unavailable"
    assert any("target=needs_key status=missing_key" in line for line in lines)
    assert "hf-secret" not in "\n".join(lines)


def test_hf_pool_doctor_cli_never_requires_live_hf(capsys, tmp_path):
    exit_code = doctor_main(["--config", str(tmp_path / "missing.yaml")])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "hf_pool=default status=not_configured" in captured.out


def test_hf_pool_live_check_marks_configured_target_healthy_without_secret_leak(tmp_path):
    path = _enabled_config(tmp_path)
    calls: list[dict[str, object]] = []

    def opener(request, *, timeout):
        calls.append(
            {
                "url": request.full_url,
                "timeout": timeout,
                "authorization": request.get_header("Authorization"),
                "body": json.loads(request.data.decode("utf-8")),
            }
        )
        return _Response()

    health = check_hf_pool(
        config_path=path,
        env={"HF_TOKEN_MAIN": "hf_TESTSECRET123"},
        live=True,
        opener=opener,
    )
    lines = "\n".join(format_hf_pool_status_lines(health))

    assert health.status == "configured"
    assert health.targets[0].status == "healthy"
    assert health.targets[0].latency_ms is not None
    assert "target=live_target status=healthy" in lines
    assert "latency_ms=" in lines
    assert "hf_TESTSECRET123" not in lines
    assert calls[0]["authorization"] == "Bearer hf_TESTSECRET123"
    assert calls[0]["body"]["model"] == "Qwen/Qwen3-4B-Instruct-2507"


def test_hf_pool_live_check_reports_errors_redacted_and_nonfatal(tmp_path):
    path = _enabled_config(tmp_path)

    def opener(_request, *, timeout):
        raise OSError("transport failed for hf_TESTSECRET123")

    health = check_hf_pool(
        config_path=path,
        env={"HF_TOKEN_MAIN": "hf_TESTSECRET123"},
        live=True,
        opener=opener,
    )
    lines = "\n".join(format_hf_pool_status_lines(health))

    assert health.status == "unavailable"
    assert health.targets[0].status == "unavailable"
    assert "hf_TESTSECRET123" not in lines
    assert "hf_<REDACTED>" in lines


def test_hf_pool_doctor_live_cli_records_usage_in_state_db(monkeypatch, capsys, tmp_path):
    path = _enabled_config(tmp_path)
    state_db = tmp_path / "hf_pool_state.sqlite3"

    def opener(_request, *, timeout):
        return _Response()

    monkeypatch.setenv("HF_TOKEN_MAIN", "hf_TESTSECRET123")
    exit_code = doctor_main(["--config", str(path), "--live", "--state-db", str(state_db)], opener=opener)

    captured = capsys.readouterr()
    usage = SQLiteHFPoolRuntimeStateStore(state_db).read_usage()

    assert exit_code == 0
    assert "target=live_target status=healthy" in captured.out
    assert usage
    assert usage[0].target == "live_target"
    assert usage[0].status == "ok"


def _enabled_config(tmp_path):
    path = tmp_path / "hf_pool.yaml"
    path.write_text(
        json.dumps(
            {
                "pools": {
                    "default": {
                        "enabled": True,
                        "timeout_seconds": 7,
                        "targets": [
                            {
                                "name": "live_target",
                                "api_key_env": "HF_TOKEN_MAIN",
                                "model": "Qwen/Qwen3-4B-Instruct-2507",
                                "purposes": ["normal_chat"],
                                "enabled": True,
                            }
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return path
