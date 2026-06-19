from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from TeeBotus.runtime.accounts import AccountStore, AccountStoreError

NOTIFICATION_STATE_FILENAME = "Version_Notifications.json"
NOTIFICATION_STATE_COLLECTION = "version_notifications"
ACTIVE_WINDOW_DAYS = 7
DEFAULT_REPO_URL = "https://github.com/H234598/TeeBotus"


@dataclass(frozen=True)
class VersionNotificationRecipient:
    instance_name: str
    account_id: str
    identity_key: str
    chat_id: int
    adapter_slot: int = 1


def notify_recent_telegram_users_for_version(
    *,
    version: str,
    instances_dir: Path,
    instance_name: str,
    account_store: AccountStore,
    send_message: Callable[[int, str], object],
    repo_root: Path | None = None,
    repo_url: str | None = None,
    adapter_slot: int | None = None,
    on_error: Callable[[VersionNotificationRecipient, Exception], object] | None = None,
    on_skip: Callable[[str], object] | None = None,
    now: datetime | None = None,
) -> int:
    resolved_repo_url = repo_url or github_repo_url(repo_root or Path.cwd())
    if repo_root is not None and not github_has_version(repo_root, version):
        if on_skip is not None:
            on_skip(f"GitHub tag v{str(version).strip().lstrip('v')} not found on remote")
        return 0
    resolved_now = now or datetime.now(timezone.utc)
    state_path = Path(instances_dir) / instance_name / "data" / NOTIFICATION_STATE_FILENAME
    state = _load_state(account_store, state_path)
    version_state = _version_state(state, version)
    sent_identities = set(_string_list(version_state.get("sent_identities")))
    failed_identities = _failed_identity_map(version_state.get("failed_identities"))
    version_state["failed_identities"] = failed_identities
    sent_count = 0
    for recipient in recent_telegram_recipients(account_store, instance_name=instance_name, adapter_slot=adapter_slot, now=resolved_now):
        if recipient.identity_key in sent_identities or _failed_delivery_matches_recipient(failed_identities, recipient):
            continue
        message = build_version_notification_text(
            version=version,
            repo_url=resolved_repo_url,
            memory_text=_memory_signal_text(account_store, recipient.account_id),
        )
        try:
            send_message(recipient.chat_id, message)
        except Exception as exc:  # noqa: BLE001
            if on_error is not None:
                try:
                    on_error(recipient, exc)
                except Exception:
                    pass
            if _is_permanent_delivery_error(exc):
                failed_identities[recipient.identity_key] = {
                    "adapter_slot": recipient.adapter_slot,
                    "chat_id": recipient.chat_id,
                    "failed_at": resolved_now.isoformat(timespec="seconds"),
                    "reason": _delivery_error_reason(exc),
                }
            continue
        failed_identities.pop(recipient.identity_key, None)
        sent_identities.add(recipient.identity_key)
        sent_count += 1
    version_state["sent_identities"] = sorted(sent_identities)
    version_state["failed_identities"] = dict(sorted(failed_identities.items()))
    version_state["updated_at"] = resolved_now.isoformat(timespec="seconds")
    _write_state(account_store, state_path, state)
    return sent_count


def recent_telegram_recipients(
    account_store: AccountStore,
    *,
    instance_name: str,
    adapter_slot: int | None = None,
    now: datetime | None = None,
) -> list[VersionNotificationRecipient]:
    resolved_now = now or datetime.now(timezone.utc)
    threshold = resolved_now - timedelta(days=ACTIVE_WINDOW_DAYS)
    recipients: list[VersionNotificationRecipient] = []
    try:
        identities = account_store._load_identities()
    except AccountStoreError:
        raise
    for identity_key, payload in identities.items():
        if not isinstance(identity_key, str) or not identity_key.startswith("telegram:user:"):
            continue
        if not isinstance(payload, dict):
            continue
        account_id = str(payload.get("account_id") or "")
        last_seen = _parse_datetime(str(payload.get("last_seen_at") or ""))
        if not account_id or last_seen is None or last_seen < threshold:
            continue
        route = payload.get("last_route") if isinstance(payload.get("last_route"), dict) else {}
        route_channel = str(route.get("channel") or "telegram").strip().casefold()
        route_slot = _normalize_adapter_slot(route.get("adapter_slot"), default=1)
        if adapter_slot is not None and route_slot != int(adapter_slot):
            continue
        if route_channel != "telegram":
            continue
        chat_id_text = str(route.get("chat_id") or "").strip() or identity_key.removeprefix("telegram:user:")
        if not chat_id_text.isdigit():
            continue
        recipients.append(
            VersionNotificationRecipient(
                instance_name=instance_name,
                account_id=account_id,
                identity_key=identity_key,
                chat_id=int(chat_id_text),
                adapter_slot=route_slot,
            )
        )
    return sorted(recipients, key=lambda item: item.identity_key)


def build_version_notification_text(*, version: str, repo_url: str = DEFAULT_REPO_URL, memory_text: str = "") -> str:
    return "\n".join(
        [
            f"TeeBotus wurde auf Version {version} aktualisiert.",
            f"Repo: {repo_url}",
            "Kleiner Hinweis aus dem Maschinenraum: Es wurde geschraubt, sortiert und einmal sehr ernst auf ein Logfile geschaut.",
            _memory_shaped_joke(memory_text),
        ]
    )


def github_has_version(repo_root: Path, version: str, *, remote: str = "origin") -> bool:
    tag = f"v{str(version).strip().lstrip('v')}"
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--exit-code", "--tags", remote, tag],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def github_repo_url(repo_root: Path, *, remote: str = "origin") -> str:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", remote],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return DEFAULT_REPO_URL
    if result.returncode != 0:
        return DEFAULT_REPO_URL
    return _normalize_github_url(result.stdout.strip()) or DEFAULT_REPO_URL


def _normalize_github_url(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    if raw.startswith("git@github.com:"):
        raw = "https://github.com/" + raw.removeprefix("git@github.com:")
    elif raw.startswith("ssh://git@github.com/"):
        raw = "https://github.com/" + raw.removeprefix("ssh://git@github.com/")
    else:
        try:
            parsed = urlsplit(raw)
        except ValueError:
            return ""
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            netloc = parsed.hostname
            if parsed.port is not None:
                netloc = f"{netloc}:{parsed.port}"
            raw = urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    if raw.endswith(".git"):
        raw = raw[:-4]
    return raw


def _memory_signal_text(account_store: AccountStore, account_id: str) -> str:
    chunks: list[str] = []
    try:
        index = account_store.read_memory_index(account_id)
        chunks.append(json.dumps(index, ensure_ascii=False)[:4000])
    except Exception:
        pass
    try:
        entries = account_store.read_memory_entries(account_id)
        chunks.append(json.dumps(entries[-10:], ensure_ascii=False)[:4000])
    except Exception:
        pass
    try:
        habits = account_store.read_account_text(account_id, "User_Habbits_and_behave.md")
        chunks.append(habits[:2000])
    except Exception:
        pass
    return "\n".join(chunks)


def _memory_shaped_joke(memory_text: str) -> str:
    text = memory_text.casefold()
    if any(word in text for word in ("youtube", "transkript", "whisper", "ffmpeg")):
        return "Mini-Witz: ffmpeg wollte auch gratulieren, hat aber erst noch 47 Flags sortiert."
    if any(word in text for word in ("crypto", "secret", "key", "verschluessel")):
        return "Mini-Witz: Der Secret Store hat gelacht, aber natuerlich nur verschluesselt."
    if any(word in text for word in ("telegram", "signal", "sms", "telefon")):
        return "Mini-Witz: Ein Messenger kam zu spaet zum Update. Er hatte noch eine Nachricht offen."
    if any(word in text for word in ("depression", "krise", "teladi", "notfall")):
        return "Mini-Witz: Der Bot hat beim Neustart tief durchgeatmet. Sogar die Exception war kurz achtsam."
    if any(word in text for word in ("test", "pytest", "fehler", "bug")):
        return "Mini-Witz: Ein Test ging in eine Bar. Der Barkeeper sagte: Erst gruen werden, dann reden."
    return "Mini-Witz: Der Bot hat sich beim Update einen Kaffee gemacht. Leider nur als JSON."


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_adapter_slot(value: object, *, default: int = 1) -> int:
    try:
        slot = int(value)
    except (TypeError, ValueError):
        return default
    return slot if slot > 0 else default


def _is_permanent_delivery_error(exc: Exception) -> bool:
    text = str(exc).casefold()
    return any(
        marker in text
        for marker in (
            "chat not found",
            "bot was blocked",
            "user is deactivated",
            "have no rights to send",
            "forbidden: bot",
        )
    )


def _failed_delivery_matches_recipient(failed_identities: dict[str, object], recipient: VersionNotificationRecipient) -> bool:
    failure = failed_identities.get(recipient.identity_key)
    if failure is None:
        return False
    if not isinstance(failure, dict):
        return False
    failed_chat_id = _optional_int(failure.get("chat_id"))
    failed_slot = _optional_int(failure.get("adapter_slot"))
    if failed_chat_id is None or failed_slot is None:
        return False
    return failed_chat_id == recipient.chat_id and failed_slot == recipient.adapter_slot


def _optional_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _delivery_error_reason(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    return text[:240]


def _version_state(state: dict[str, Any], version: str) -> dict[str, Any]:
    versions = state.setdefault("versions", {})
    if not isinstance(versions, dict):
        versions = {}
        state["versions"] = versions
    raw_version_state = versions.get(version)
    if not isinstance(raw_version_state, dict):
        raw_version_state = {}
        versions[version] = raw_version_state
    return raw_version_state


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    values: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text:
            values.append(text)
    return values


def _failed_identity_map(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, object] = {}
    for key, payload in value.items():
        identity_key = str(key or "").strip() if isinstance(key, str) else ""
        if not identity_key:
            continue
        normalized[identity_key] = payload
    return normalized


def _load_state(account_store: AccountStore, path: Path) -> dict[str, Any]:
    if _sql_state_backend_available(account_store):
        return _normalize_state(
            account_store.read_instance_json_state(
                NOTIFICATION_STATE_FILENAME,
                NOTIFICATION_STATE_COLLECTION,
                {"versions": {}},
            )
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"versions": {}}
    return _normalize_state(data)


def _write_state(account_store: AccountStore, path: Path, state: dict[str, Any]) -> None:
    if _sql_state_backend_available(account_store):
        account_store.write_instance_json_state(
            NOTIFICATION_STATE_FILENAME,
            NOTIFICATION_STATE_COLLECTION,
            _normalize_state(state),
        )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _sql_state_backend_available(account_store: AccountStore) -> bool:
    checker = getattr(account_store, "instance_json_state_backend_available", None)
    return callable(checker) and bool(checker())


def _normalize_state(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"versions": {}}
    normalized = dict(data)
    versions = normalized.get("versions")
    if not isinstance(versions, dict):
        normalized["versions"] = {}
    return normalized
