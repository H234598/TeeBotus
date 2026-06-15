from __future__ import annotations

from pathlib import Path

import pytest

import scripts.check_adapter_deps as check_adapter_deps
from scripts.install_adapter_deps import build_python_install_commands, main, read_pins, signal_cli_release_url, signal_cli_rest_api_repo_url


def test_adapter_dependency_installer_keeps_matrix_override_outside_niobot_deps(tmp_path: Path) -> None:
    lockfile = tmp_path / "adapter-dependencies.lock"
    lockfile.write_text(
        "\n".join(
            [
                "signalbot==1.2.2",
                "nio-bot==1.0.2.post1",
                "matrix-nio==0.25.0",
                "blurhash-python==1.2.2",
                "h11==0.16.0",
                "faster-whisper==1.2.1",
                "litellm==1.83.7",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    commands = build_python_install_commands(read_pins(lockfile), python="python3", user=True)

    assert len(commands) == 2
    assert "matrix-nio==0.25.0" in commands[0]
    assert "h11==0.16.0" in commands[0]
    assert "faster-whisper==1.2.1" in commands[0]
    assert "litellm==1.83.7" in commands[0]
    assert "nio-bot==1.0.2.post1" not in commands[0]
    assert commands[1][-2:] == ["--no-deps", "nio-bot==1.0.2.post1"]


def test_signal_cli_release_url_uses_pinned_github_release() -> None:
    assert signal_cli_release_url("0.14.5") == (
        "https://github.com/AsamK/signal-cli/releases/download/v0.14.5/signal-cli-0.14.5.tar.gz"
    )


def test_signal_cli_rest_api_repo_url_uses_bbernhard_upstream() -> None:
    assert signal_cli_rest_api_repo_url() == "https://github.com/bbernhard/signal-cli-rest-api.git"


def test_adapter_dependency_dry_run_includes_native_installs(capsys) -> None:
    result = main(["--dry-run", "--python", "python3"])

    assert result == 0
    output = capsys.readouterr().out
    assert "signalbot==1.2.2" in output
    assert "litellm==1.83.7" in output
    assert "download https://github.com/AsamK/signal-cli/releases/download/v0.14.5/signal-cli-0.14.5.tar.gz" in output
    assert "git clone --depth 1 --branch 0.100 https://github.com/bbernhard/signal-cli-rest-api.git" in output
    assert "go build -o signal-cli-rest-api main.go" in output


def test_litellm_supply_chain_guard_blocks_bad_pin() -> None:
    ok, message = check_adapter_deps._check_litellm_supply_chain_guard("1.82.8")

    assert not ok
    assert "blocked" in message


def test_litellm_supply_chain_guard_blocks_suspicious_pth(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "litellm_init.pth").write_text("bad", encoding="utf-8")
    monkeypatch.setattr(check_adapter_deps.importlib.metadata, "version", lambda _name: "1.83.7")
    monkeypatch.setattr(check_adapter_deps.sys, "path", [str(tmp_path)])

    ok, message = check_adapter_deps._check_litellm_supply_chain_guard("1.83.7")

    assert not ok
    assert "suspicious_pth_files" in message
