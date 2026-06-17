from __future__ import annotations

import json

from TeeBotus.llm.hf_pool.doctor import main as doctor_main
from TeeBotus.llm.hf_pool.health import check_hf_pool, format_hf_pool_status_lines
from TeeBotus.llm.hf_pool.state import HFPoolRuntimeState, SQLiteHFPoolRuntimeStateStore


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


def test_hf_pool_doctor_reports_persistent_cooldown_without_live_check(tmp_path):
    path = _enabled_config(tmp_path)
    state_store = SQLiteHFPoolRuntimeStateStore(tmp_path / "hf_pool_state.sqlite3")
    state_store.save(
        HFPoolRuntimeState(
            cooldowns={"live_target": "2999-01-01T00:00:00+00:00"},
            failures={"live_target": 2},
            successes={"live_target": 3},
            avg_latency_ms={"live_target": 44.6},
        )
    )

    health = check_hf_pool(
        config_path=path,
        env={"HF_TOKEN_MAIN": "hf_TESTSECRET123"},
        state_store=state_store,
    )
    lines = "\n".join(format_hf_pool_status_lines(health))

    assert health.status == "unavailable"
    assert health.targets[0].status == "cooldown"
    assert health.targets[0].failures == 2
    assert health.targets[0].successes == 3
    assert health.targets[0].avg_latency_ms == 45
    assert "error=all_configured_targets_in_cooldown" in lines
    assert "targets=1 healthy=0 unavailable=0 cooldown=1 missing_key=0 disabled=0" in lines
    assert "target=live_target status=cooldown" in lines
    assert "until=2999-01-01T00:00:00+00:00" in lines
    assert "successes=3" in lines
    assert "failures=2" in lines
    assert "avg_latency_ms=45" in lines
    assert "hf_TESTSECRET123" not in lines


def test_hf_pool_doctor_cli_uses_state_db_without_live_network(monkeypatch, capsys, tmp_path):
    path = _enabled_config(tmp_path)
    state_db = tmp_path / "hf_pool_state.sqlite3"
    SQLiteHFPoolRuntimeStateStore(state_db).save(HFPoolRuntimeState(cooldowns={"live_target": "2999-01-01T00:00:00+00:00"}))
    monkeypatch.setenv("HF_TOKEN_MAIN", "hf_TESTSECRET123")

    exit_code = doctor_main(["--config", str(path), "--state-db", str(state_db)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "target=live_target status=cooldown" in captured.out
    assert "until=2999-01-01T00:00:00+00:00" in captured.out


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
