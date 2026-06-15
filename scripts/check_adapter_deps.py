#!/usr/bin/env python3
from __future__ import annotations

import importlib.metadata
import importlib
import inspect
import os
import shutil
import subprocess
import sys
from io import BytesIO
from pathlib import Path


LOCKFILE = Path(__file__).resolve().parents[1] / "adapter-dependencies.lock"
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    pins = _read_pins(LOCKFILE)
    checks = [
        _check_python_package("signalbot", pins["signalbot"]),
        _check_python_package("nio-bot", pins["nio-bot"]),
        _check_python_package("matrix-nio", pins["matrix-nio"]),
        _check_python_package("blurhash-python", pins["blurhash-python"]),
        _check_python_package("h11", pins["h11"]),
        _check_niobot_matrix_contract(),
        _check_matrix_file_contract(),
        _check_signalbot_context_contract(),
        _check_executable_version("signal-cli", pins["signal-cli"], ["--version"]),
        _check_cargo_binary("signal-cli-api", pins["signal-cli-api"]),
    ]
    for ok, message in checks:
        print(("OK " if ok else "FAIL ") + message)
    return 0 if all(ok for ok, _message in checks) else 1


def _read_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, sep, version = stripped.partition("==")
        if not sep:
            raise SystemExit(f"Invalid lock line: {line}")
        pins[name.strip()] = version.strip()
    return pins


def _check_python_package(name: str, expected: str) -> tuple[bool, str]:
    try:
        installed = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return False, f"{name} missing, expected {expected}"
    import_name = {"nio-bot": "niobot", "matrix-nio": "nio", "blurhash-python": "blurhash"}.get(
        name, name.replace("-", "_")
    )
    try:
        module = importlib.import_module(import_name)
    except Exception as exc:
        module = None
        import_detail = f" import_error={type(exc).__name__}: {exc}"
    else:
        import_detail = f" import={getattr(module, '__file__', '<unknown>')}"
    ok = installed == expected and module is not None
    return ok, f"{name} installed={installed} expected={expected}{import_detail}"


def _check_niobot_matrix_contract() -> tuple[bool, str]:
    try:
        import nio  # type: ignore[import-not-found]
        import niobot  # type: ignore[import-not-found]
    except Exception as exc:
        return False, f"nio-bot/matrix-nio contract import_error={type(exc).__name__}: {exc}"
    required_nio = (
        "AsyncClient",
        "RoomMessageText",
        "RoomMessageNotice",
        "RoomMessageEmote",
        "RoomMessageFile",
        "RoomMessageImage",
        "RoomMessageAudio",
        "RoomMessageVideo",
        "RoomMessageUnknown",
        "RoomSendResponse",
        "RoomSendError",
        "RoomGetEventResponse",
        "RoomGetEventError",
        "RoomPutStateResponse",
        "RoomPutStateError",
        "SyncResponse",
        "UploadResponse",
        "UploadError",
        "MemoryDownloadResponse",
        "DiskDownloadResponse",
        "DownloadError",
    )
    missing_nio = [name for name in required_nio if not hasattr(nio, name)]
    if missing_nio:
        return False, f"matrix-nio missing required API: {', '.join(missing_nio)}"
    if not hasattr(niobot, "NioBot"):
        return False, "nio-bot missing NioBot"
    start_params = inspect.signature(niobot.NioBot.start).parameters
    send_params = inspect.signature(niobot.NioBot.send_message).parameters
    client_params = inspect.signature(niobot.NioBot).parameters
    upload_params = inspect.signature(nio.AsyncClient.upload).parameters
    download_params = inspect.signature(nio.AsyncClient.download).parameters
    room_get_event_params = inspect.signature(nio.AsyncClient.room_get_event).parameters
    room_send_params = inspect.signature(nio.AsyncClient.room_send).parameters
    room_put_state_params = inspect.signature(nio.AsyncClient.room_put_state).parameters
    room_typing_params = inspect.signature(nio.AsyncClient.room_typing).parameters
    room_redact_params = inspect.signature(nio.AsyncClient.room_redact).parameters
    update_receipt_params = inspect.signature(nio.AsyncClient.update_receipt_marker).parameters
    expectations = {
        "NioBot.command_prefix": "command_prefix" in client_params,
        "NioBot.start.access_token": "access_token" in start_params,
        "NioBot.send_message.file": "file" in send_params,
        "NioBot.send_message.message_type": "message_type" in send_params,
        "NioBot.send_message.reply_to": "reply_to" in send_params,
        "AsyncClient.upload.filesize": "filesize" in upload_params,
        "AsyncClient.download.mxc": "mxc" in download_params,
        "AsyncClient.room_get_event.event_id": "event_id" in room_get_event_params,
        "AsyncClient.room_send.content": "content" in room_send_params,
        "AsyncClient.room_put_state.content": "content" in room_put_state_params,
        "AsyncClient.room_put_state.state_key": "state_key" in room_put_state_params,
        "AsyncClient.room_typing.timeout": "timeout" in room_typing_params,
        "AsyncClient.room_redact.reason": "reason" in room_redact_params,
        "AsyncClient.update_receipt_marker.receipt_type": "receipt_type" in update_receipt_params,
        "nio.ReceiptType.read": hasattr(getattr(nio, "ReceiptType", object), "read"),
    }
    failures = [name for name, ok in expectations.items() if not ok]
    if failures:
        return False, f"nio-bot/matrix-nio contract missing: {', '.join(failures)}"
    try:
        requirements = importlib.metadata.metadata("nio-bot").get_all("Requires-Dist") or []
    except importlib.metadata.PackageNotFoundError:
        requirements = []
    declared = next((value for value in requirements if value.startswith("matrix-nio ")), "matrix-nio <unknown>")
    installed = importlib.metadata.version("matrix-nio")
    return True, f"nio-bot/matrix-nio runtime_contract=ok matrix-nio={installed} nio-bot_declares='{declared}'"


def _check_matrix_file_contract() -> tuple[bool, str]:
    try:
        from niobot.attachment import AudioAttachment, FileAttachment, ImageAttachment, VideoAttachment  # type: ignore[import-not-found]
    except Exception as exc:
        return False, f"nio-bot attachment import_error={type(exc).__name__}: {exc}"
    try:
        attachment = FileAttachment(
            BytesIO(b"ok"),
            file_name="check.txt",
            mime_type="text/plain",
            size_bytes=2,
        )
    except Exception as exc:
        return False, f"nio-bot FileAttachment construction_error={type(exc).__name__}: {exc}"
    if attachment.file_name != "check.txt" or attachment.mime_type != "text/plain" or attachment.size != 2:
        return False, "nio-bot FileAttachment did not preserve filename/mime/size"
    body = attachment.as_body("Check")
    expected_msgtypes = {
        "file": body,
        "image": ImageAttachment(BytesIO(b"ok"), file_name="check.jpg", mime_type="image/jpeg", size_bytes=2).as_body("Check"),
        "audio": AudioAttachment(BytesIO(b"ok"), file_name="check.ogg", mime_type="audio/ogg", size_bytes=2).as_body("Check"),
        "video": VideoAttachment(BytesIO(b"ok"), file_name="check.mp4", mime_type="video/mp4", size_bytes=2).as_body("Check"),
    }
    failures = [
        f"{name}={payload.get('msgtype')}"
        for name, payload in expected_msgtypes.items()
        if payload.get("msgtype") != f"m.{name}"
    ]
    ok = not failures and body.get("body") == "Check" and body.get("filename") == "check.txt"
    details = "ok" if ok else f"invalid {' '.join(failures)}"
    return ok, f"nio-bot attachment contract={details} body_keys={','.join(sorted(body.keys()))}"


def _check_signalbot_context_contract() -> tuple[bool, str]:
    try:
        from signalbot.context import Context  # type: ignore[import-not-found]
        from signalbot import SignalBot  # type: ignore[import-not-found]
    except Exception as exc:
        return False, f"signalbot Context import_error={type(exc).__name__}: {exc}"
    missing = [
        name
        for name in ("send", "reply", "edit", "start_typing", "stop_typing", "remote_delete", "react", "receipt")
        if not hasattr(Context, name)
    ]
    if missing:
        return False, f"signalbot Context missing required API: {', '.join(missing)}"
    send_params = inspect.signature(Context.send).parameters
    reply_params = inspect.signature(Context.reply).parameters
    edit_params = inspect.signature(Context.edit).parameters
    bot_send_params = inspect.signature(SignalBot.send).parameters
    bot_register_params = inspect.signature(SignalBot.register).parameters
    bot_start_params = inspect.signature(SignalBot.start).parameters
    bot_start_typing_params = inspect.signature(SignalBot.start_typing).parameters
    bot_stop_typing_params = inspect.signature(SignalBot.stop_typing).parameters
    bot_react_params = inspect.signature(SignalBot.react).parameters
    bot_receipt_params = inspect.signature(SignalBot.receipt).parameters
    bot_poll_params = inspect.signature(SignalBot.poll).parameters
    bot_update_contact_params = inspect.signature(SignalBot.update_contact).parameters
    bot_update_group_params = inspect.signature(SignalBot.update_group).parameters
    bot_delete_attachment_params = inspect.signature(SignalBot.delete_attachment).parameters
    delete_params = inspect.signature(Context.remote_delete).parameters
    react_params = inspect.signature(Context.react).parameters
    receipt_params = inspect.signature(Context.receipt).parameters
    expectations = {
        "Context.send.base64_attachments": "base64_attachments" in send_params,
        "Context.send.mentions": "mentions" in send_params,
        "Context.send.text_mode": "text_mode" in send_params,
        "Context.send.view_once": "view_once" in send_params,
        "Context.send.link_preview": "link_preview" in send_params,
        "Context.reply.base64_attachments": "base64_attachments" in reply_params,
        "Context.reply.mentions": "mentions" in reply_params,
        "Context.reply.text_mode": "text_mode" in reply_params,
        "Context.reply.view_once": "view_once" in reply_params,
        "Context.reply.link_preview": "link_preview" in reply_params,
        "Context.edit.edit_timestamp": "edit_timestamp" in edit_params,
        "Context.edit.mentions": "mentions" in edit_params,
        "Context.edit.text_mode": "text_mode" in edit_params,
        "Context.edit.view_once": "view_once" in edit_params,
        "Context.edit.link_preview": "link_preview" in edit_params,
        "Context.react.emoji": "emoji" in react_params,
        "Context.receipt.receipt_type": "receipt_type" in receipt_params,
        "SignalBot.send.receiver": "receiver" in bot_send_params,
        "SignalBot.send.base64_attachments": "base64_attachments" in bot_send_params,
        "SignalBot.send.edit_timestamp": "edit_timestamp" in bot_send_params,
        "SignalBot.send.mentions": "mentions" in bot_send_params,
        "SignalBot.send.text_mode": "text_mode" in bot_send_params,
        "SignalBot.send.view_once": "view_once" in bot_send_params,
        "SignalBot.send.link_preview": "link_preview" in bot_send_params,
        "SignalBot.send.quote_author": "quote_author" in bot_send_params,
        "SignalBot.send.quote_mentions": "quote_mentions" in bot_send_params,
        "SignalBot.send.quote_message": "quote_message" in bot_send_params,
        "SignalBot.send.quote_timestamp": "quote_timestamp" in bot_send_params,
        "SignalBot.register.command": "command" in bot_register_params,
        "SignalBot.start.run_forever": "run_forever" in bot_start_params,
        "SignalBot.signal_cli_rest_api_mode": hasattr(SignalBot, "signal_cli_rest_api_mode"),
        "SignalBot.signal_cli_rest_api_version": hasattr(SignalBot, "signal_cli_rest_api_version"),
        "SignalBot.react.message": "message" in bot_react_params,
        "SignalBot.react.emoji": "emoji" in bot_react_params,
        "SignalBot.receipt.message": "message" in bot_receipt_params,
        "SignalBot.receipt.receipt_type": "receipt_type" in bot_receipt_params,
        "SignalBot.poll.receiver": "receiver" in bot_poll_params,
        "SignalBot.poll.answers": "answers" in bot_poll_params,
        "SignalBot.poll.allow_multiple_selections": "allow_multiple_selections" in bot_poll_params,
        "SignalBot.update_contact.receiver": "receiver" in bot_update_contact_params,
        "SignalBot.update_contact.expiration_in_seconds": "expiration_in_seconds" in bot_update_contact_params,
        "SignalBot.update_contact.name": "name" in bot_update_contact_params,
        "SignalBot.update_group.group_id": "group_id" in bot_update_group_params,
        "SignalBot.update_group.base64_avatar": "base64_avatar" in bot_update_group_params,
        "SignalBot.update_group.description": "description" in bot_update_group_params,
        "SignalBot.update_group.expiration_in_seconds": "expiration_in_seconds" in bot_update_group_params,
        "SignalBot.update_group.name": "name" in bot_update_group_params,
        "SignalBot.delete_attachment.attachment_filename": "attachment_filename" in bot_delete_attachment_params,
        "SignalBot.start_typing.receiver": "receiver" in bot_start_typing_params,
        "SignalBot.stop_typing.receiver": "receiver" in bot_stop_typing_params,
        "Context.remote_delete.timestamp": "timestamp" in delete_params,
    }
    failures = [name for name, ok in expectations.items() if not ok]
    if failures:
        return False, f"signalbot Context contract missing: {', '.join(failures)}"
    return True, "signalbot Context contract=ok methods=register,start,send,reply,edit,react,receipt,poll,update_contact,update_group,start_typing,stop_typing,remote_delete,delete_attachment,about"


def _check_executable_version(binary: str, expected: str, args: list[str]) -> tuple[bool, str]:
    path = _which(binary)
    if path is None:
        return False, f"{binary} missing from PATH, expected {expected}"
    try:
        result = subprocess.run(
            [path, *args],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{binary} could not be executed: {exc}"
    output = " ".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    ok = result.returncode == 0 and expected in output
    return ok, f"{binary} path={path} version_output={output or '<empty>'} expected={expected}"


def _check_cargo_binary(binary: str, expected: str) -> tuple[bool, str]:
    path = _which(binary)
    if path is None:
        return False, f"{binary} missing from PATH, expected {expected}"
    cargo = _which("cargo")
    if cargo is None:
        return False, f"{binary} path={path}, but cargo is missing; cannot verify expected {expected}"
    try:
        result = subprocess.run(
            [cargo, "install", "--list"],
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{binary} could not be verified through cargo: {exc}"
    expected_line = f"{binary} v{expected}:"
    ok = result.returncode == 0 and expected_line in result.stdout
    return ok, f"{binary} path={path} cargo_pin={'found' if ok else 'missing'} expected={expected}"


def _which(binary: str) -> str | None:
    path = shutil.which(binary)
    if path is not None:
        return path
    for directory in (Path.home() / ".local" / "bin", Path.home() / ".cargo" / "bin"):
        candidate = directory / binary
        if os.access(candidate, os.X_OK):
            return str(candidate)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
