from __future__ import annotations

from pathlib import Path

from scripts.install_adapter_deps import build_python_install_commands, main, read_pins, signal_cli_release_url


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
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    commands = build_python_install_commands(read_pins(lockfile), python="python3", user=True)

    assert len(commands) == 2
    assert "matrix-nio==0.25.0" in commands[0]
    assert "h11==0.16.0" in commands[0]
    assert "nio-bot==1.0.2.post1" not in commands[0]
    assert commands[1][-2:] == ["--no-deps", "nio-bot==1.0.2.post1"]


def test_signal_cli_release_url_uses_pinned_github_release() -> None:
    assert signal_cli_release_url("0.14.5") == (
        "https://github.com/AsamK/signal-cli/releases/download/v0.14.5/signal-cli-0.14.5.tar.gz"
    )


def test_adapter_dependency_dry_run_includes_native_installs(capsys) -> None:
    result = main(["--dry-run", "--python", "python3"])

    assert result == 0
    output = capsys.readouterr().out
    assert "signalbot==1.2.2" in output
    assert "download https://github.com/AsamK/signal-cli/releases/download/v0.14.5/signal-cli-0.14.5.tar.gz" in output
    assert "cargo install signal-cli-api --version 0.1.1 --locked" in output
