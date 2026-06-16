from __future__ import annotations

import json

from TeeBotus.llm.hf_pool.doctor import main as doctor_main
from TeeBotus.llm.hf_pool.health import check_hf_pool, format_hf_pool_status_lines


def test_hf_pool_doctor_reports_missing_config(tmp_path):
    health = check_hf_pool(config_path=tmp_path / "missing.yaml")
    lines = format_hf_pool_status_lines(health)

    assert health.status == "not_configured"
    assert lines[0].startswith("hf_pool=default status=not_configured")


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
