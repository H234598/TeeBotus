from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path


DEFAULT_QDRANT_IMAGE = "docker.io/qdrant/qdrant:v1.18.2"
DEFAULT_CONTAINER_NAME = "teebotus-qdrant"
DEFAULT_VOLUME_NAME = "teebotus-qdrant"
DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_PORT = 6333


@dataclass(frozen=True)
class QdrantSystemdUnit:
    service_name: str
    service_text: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install or print TeeBotus Qdrant user systemd unit.")
    parser.add_argument("--image", default=DEFAULT_QDRANT_IMAGE, help="Pinned qdrant/qdrant image tag.")
    parser.add_argument("--container-name", default=DEFAULT_CONTAINER_NAME, help="Podman container name.")
    parser.add_argument("--volume-name", default=DEFAULT_VOLUME_NAME, help="Podman volume name for /qdrant/storage.")
    parser.add_argument("--bind-host", default=DEFAULT_BIND_HOST, help="Host address for Qdrant HTTP port.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Qdrant HTTP host/container port.")
    parser.add_argument("--podman", default="podman", help="Podman executable.")
    parser.add_argument("--print", action="store_true", dest="print_only", help="Print unit file instead of writing it.")
    parser.add_argument("--enable", action="store_true", help="Run systemctl --user daemon-reload and enable --now the service after writing.")
    args = parser.parse_args(argv)

    unit = render_qdrant_systemd_unit(
        image=args.image,
        container_name=args.container_name,
        volume_name=args.volume_name,
        bind_host=args.bind_host,
        port=args.port,
        podman=args.podman,
    )
    if args.print_only:
        print(f"# {unit.service_name}")
        print(unit.service_text, end="")
        return 0
    user_dir = Path.home() / ".config" / "systemd" / "user"
    user_dir.mkdir(parents=True, exist_ok=True)
    target = user_dir / unit.service_name
    target.write_text(unit.service_text, encoding="utf-8")
    print(f"wrote {target}")
    if args.enable:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", unit.service_name], check=True)
        print(f"enabled {unit.service_name}")
    return 0


def render_qdrant_systemd_unit(
    *,
    image: str = DEFAULT_QDRANT_IMAGE,
    container_name: str = DEFAULT_CONTAINER_NAME,
    volume_name: str = DEFAULT_VOLUME_NAME,
    bind_host: str = DEFAULT_BIND_HOST,
    port: int = DEFAULT_PORT,
    podman: str = "podman",
) -> QdrantSystemdUnit:
    image = _validate_image(image)
    container_name = _systemd_token(container_name, label="container name")
    volume_name = _systemd_token(volume_name, label="volume name")
    bind_host = _validate_bind_host(bind_host)
    port = _validate_port(port)
    podman = str(podman or "podman").strip() or "podman"
    podman = _validate_systemd_unit_value(podman, label="podman executable")
    service_name = f"{container_name}.service"
    publish = f"{bind_host}:{port}:{port}"
    podman_q = _shell_quote(podman)
    container_q = _shell_quote(container_name)
    volume_q = _shell_quote(volume_name)
    image_q = _shell_quote(image)
    ensure_volume_command = (
        f"{podman_q} volume exists {volume_q} >/dev/null 2>&1 || {podman_q} volume create {volume_q}"
    )
    service_text = "\n".join(
        [
            "[Unit]",
            "Description=TeeBotus local Qdrant vector store",
            "Documentation=https://qdrant.tech/documentation/quickstart/",
            "Wants=network-online.target",
            "After=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            "Restart=on-failure",
            "RestartSec=5s",
            f"ExecStartPre={_systemd_unit_value(f'-{podman_q} rm -f {container_q}', label='command line')}",
            f"ExecStartPre={_systemd_unit_value(f'/bin/sh -c {_shell_quote(ensure_volume_command)}', label='command line')}",
            "ExecStart="
            + _systemd_unit_value(
                (
                    f"{podman_q} run --rm --name {container_q} "
                    f"-p {_shell_quote(publish)} -v {volume_q}:/qdrant/storage {image_q}"
                ),
                label="command line",
            ),
            f"ExecStop={_systemd_unit_value(f'{podman_q} stop -t 10 {container_q}', label='command line')}",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )
    return QdrantSystemdUnit(service_name=service_name, service_text=service_text)


def _validate_image(value: str) -> str:
    image = str(value or "").strip()
    if not image:
        raise ValueError("Qdrant image must not be empty")
    _validate_systemd_unit_value(image, label="image")
    if image in {"qdrant/qdrant", "qdrant/qdrant:latest"} or image.endswith(":latest"):
        raise ValueError("Qdrant image must use a pinned tag, not latest")
    if ":" not in image.rsplit("/", 1)[-1]:
        raise ValueError("Qdrant image must include an explicit tag")
    return image


def _validate_bind_host(value: str) -> str:
    host = str(value or "").strip()
    if host != DEFAULT_BIND_HOST:
        raise ValueError("Qdrant bind host must stay 127.0.0.1 for the local Plan2 service")
    return host


def _validate_port(value: int) -> int:
    port = int(value)
    if port < 1 or port > 65535:
        raise ValueError("Qdrant port must be between 1 and 65535")
    return port


def _systemd_token(value: str, *, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Qdrant {label} must not be empty")
    if not text[0].isalnum():
        raise ValueError(f"Qdrant {label} must start with an alphanumeric character")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
    if any(char not in allowed for char in text):
        raise ValueError(f"Qdrant {label} contains unsupported characters")
    return text


def _systemd_unit_value(value: str, *, label: str) -> str:
    return _validate_systemd_unit_value(value, label=label).replace("%", "%%")


def _validate_systemd_unit_value(value: str, *, label: str) -> str:
    text = str(value)
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError(f"Qdrant {label} contains invalid control characters")
    return text


def _shell_quote(value: str) -> str:
    _validate_systemd_unit_value(value, label="command argument")
    if not value:
        return "''"
    if all(char.isalnum() or char in "@%_+=:,./-" for char in value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


if __name__ == "__main__":
    raise SystemExit(main())
