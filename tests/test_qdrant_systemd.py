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
    for image in (
        "qdrant/qdrant",
        "qdrant/qdrant:latest",
        "-bad:v1",
        "docker.io/qdrant/qdrant:v1.18.2 extra",
        "docker.io/qdrant/qdrant%x:v1.18.2",
    ):
        try:
            render_qdrant_systemd_unit(image=image)
        except ValueError as exc:
            assert "Qdrant image" in str(exc)
        else:
            raise AssertionError(f"expected image={image} to fail")


def test_render_qdrant_systemd_unit_rejects_non_local_bind() -> None:
    try:
        render_qdrant_systemd_unit(bind_host="0.0.0.0")
    except ValueError as exc:
        assert "127.0.0.1" in str(exc)
    else:
        raise AssertionError("expected public Qdrant bind to fail")


def test_render_qdrant_systemd_unit_rejects_unsafe_names() -> None:
    cases = [
        {"container_name": "."},
        {"container_name": ".."},
        {"container_name": "---"},
        {"container_name": "@bad"},
        {"container_name": "bad@name"},
        {"volume_name": "."},
        {"volume_name": "---"},
    ]
    for kwargs in cases:
        try:
            render_qdrant_systemd_unit(**kwargs)
        except ValueError as exc:
            assert "Qdrant" in str(exc)
        else:
            raise AssertionError(f"expected unsafe name rejection for {kwargs}")


def test_render_qdrant_systemd_unit_allows_dotted_safe_names() -> None:
    unit = render_qdrant_systemd_unit(container_name="qdrant.store", volume_name="qdrant-store_1")

    assert unit.service_name == "qdrant.store.service"
    assert "--name qdrant.store" in unit.service_text
    assert "-v qdrant-store_1:/qdrant/storage" in unit.service_text


def test_render_qdrant_systemd_unit_rejects_control_characters() -> None:
    cases = [
        {"image": "docker.io/qdrant/qdrant:v1.18.2\nExecStart=/bin/false"},
        {"podman": "podman\nExecStart=/bin/false"},
    ]
    for kwargs in cases:
        try:
            render_qdrant_systemd_unit(**kwargs)
        except ValueError as exc:
            assert "invalid control characters" in str(exc)
        else:
            raise AssertionError(f"expected control character rejection for {kwargs}")


def test_render_qdrant_systemd_unit_rejects_podman_execstart_prefixes() -> None:
    for podman in ("-podman", "@podman", ":podman", "+podman", "!podman", "|podman"):
        try:
            render_qdrant_systemd_unit(podman=podman)
        except ValueError as exc:
            assert "special ExecStart prefix" in str(exc)
        else:
            raise AssertionError(f"expected podman executable rejection for {podman!r}")


def test_render_qdrant_systemd_unit_rejects_relative_podman_path() -> None:
    try:
        render_qdrant_systemd_unit(podman="bin/podman")
    except ValueError as exc:
        assert "PATH executable name or absolute path" in str(exc)
    else:
        raise AssertionError("expected relative podman path rejection")


def test_render_qdrant_systemd_unit_allows_absolute_podman_path() -> None:
    unit = render_qdrant_systemd_unit(podman="/usr/bin/podman")

    assert "ExecStart=/usr/bin/podman run --rm" in unit.service_text


def test_render_qdrant_systemd_unit_escapes_systemd_percent_specifiers() -> None:
    unit = render_qdrant_systemd_unit(
        podman="/usr/bin/podman%h",
    )

    assert "ExecStartPre=-/usr/bin/podman%%h rm -f teebotus-qdrant" in unit.service_text
    assert "/usr/bin/podman%%h volume exists teebotus-qdrant" in unit.service_text
    assert "docker.io/qdrant/qdrant:v1.18.2" in unit.service_text
    assert "%%%%h" not in unit.service_text


def test_qdrant_systemd_print_mode_outputs_unit(capsys) -> None:
    result = main(["--print"])

    captured = capsys.readouterr()
    assert result == 0
    assert "# teebotus-qdrant.service" in captured.out
    assert DEFAULT_QDRANT_IMAGE in captured.out
    assert "127.0.0.1:6333:6333" in captured.out


def test_qdrant_systemd_cli_reports_invalid_render_options_without_traceback(capsys) -> None:
    try:
        main(["--image=-bad:v1", "--print"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected invalid image to exit with argparse error")

    captured = capsys.readouterr()
    assert "Qdrant image must not start with '-'" in captured.err
    assert "Traceback" not in captured.err


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
