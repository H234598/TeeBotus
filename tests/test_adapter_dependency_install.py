from __future__ import annotations

from pathlib import Path

from scripts.install_adapter_deps import build_python_install_commands, read_pins


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
