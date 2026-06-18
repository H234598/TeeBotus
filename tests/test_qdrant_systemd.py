from __future__ import annotations

import subprocess

from TeeBotus.qdrant_systemd import DEFAULT_QDRANT_IMAGE, main, render_qdrant_systemd_unit


def test_render_qdrant_systemd_unit_pins_image_and_localhost() -> None:
    unit = render_qdrant_systemd_unit()

    assert unit.service_name == "teebotus-qdrant.service"
    assert DEFAULT_QDRANT_IMAGE in unit.service_text
    assert "latest" not in DEFAULT_QDRANT_IMAGE
    assert "-p 127.0.0.1:6333:6333" in unit.service_text
    assert "-v teebotus-qdrant:/qdrant/storage" in unit.service_text
    assert "ExecStartPre=-podman rm -f teebotus-qdrant" in unit.service_text
    assert "ExecStartPre=/bin/sh -c 'podman volume exists teebotus-qdrant >/dev/null 2>&1 || podman volume create teebotus-qdrant'" in unit.service_text
    assert "Restart=on-failure" in unit.service_text
    assert "WantedBy=default.target" in unit.service_text


def test_render_qdrant_systemd_unit_rejects_latest_or_unpinned_image() -> None:
    for image in ("qdrant/qdrant", "qdrant/qdrant:latest"):
        try:
            render_qdrant_systemd_unit(image=image)
        except ValueError as exc:
            assert "pinned tag" in str(exc) or "explicit tag" in str(exc)
        else:
            raise AssertionError(f"expected image={image} to fail")


def test_render_qdrant_systemd_unit_rejects_non_local_bind() -> None:
    try:
        render_qdrant_systemd_unit(bind_host="0.0.0.0")
    except ValueError as exc:
        assert "127.0.0.1" in str(exc)
    else:
        raise AssertionError("expected public Qdrant bind to fail")


def test_qdrant_systemd_print_mode_outputs_unit(capsys) -> None:
    result = main(["--print"])

    captured = capsys.readouterr()
    assert result == 0
    assert "# teebotus-qdrant.service" in captured.out
    assert DEFAULT_QDRANT_IMAGE in captured.out
    assert "127.0.0.1:6333:6333" in captured.out


def test_qdrant_systemd_enable_runs_user_systemctl(monkeypatch, tmp_path) -> None:
    calls: list[list[str]] = []

    def fake_run(command, check=False, **_kwargs):
        calls.append(list(command))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("TeeBotus.qdrant_systemd.Path.home", lambda: tmp_path)
    monkeypatch.setattr("TeeBotus.qdrant_systemd.subprocess.run", fake_run)

    result = main(["--enable"])

    assert result == 0
    assert (tmp_path / ".config" / "systemd" / "user" / "teebotus-qdrant.service").exists()
    assert calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "teebotus-qdrant.service"],
    ]
