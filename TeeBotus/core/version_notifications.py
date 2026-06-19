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
    normalized_version = _normalize_version_key(version)
    resolved_now = now or datetime.now(timezone.utc)
    state_path = Path(instances_dir) / instance_name / "data" / NOTIFICATION_STATE_FILENAME
    state = _load_state(account_store, state_path)
    if _sql_state_backend_available(account_store) and _state_has_versions(state):
        _write_state(account_store, state_path, state)
    if not normalized_version:
        if on_skip is not None:
            on_skip("version is empty")
        return 0
    resolved_repo_url = repo_url or github_repo_url(repo_root or Path.cwd())
    if repo_root is not None and not github_has_version(repo_root, normalized_version):
        if on_skip is not None:
            on_skip(f"GitHub tag v{normalized_version} not found on remote")
        return 0
    version_state = _version_state(state, normalized_version)
    sent_identities = set(_string_list(version_state.get("sent_identities")))
    identities = account_store._load_identities()
    failed_identities = _failed_identity_map(version_state.get("failed_identities"))
    version_state["failed_identities"] = failed_identities
    sent_count = 0
    for recipient in recent_telegram_recipients(account_store, instance_name=instance_name, adapter_slot=adapter_slot, now=resolved_now):
        if _sent_delivery_matches_recipient(sent_identities, recipient, identities):
            _clear_resolved_failures(failed_identities, recipient, identities)
            sent_identities.add(recipient.identity_key)
            continue
        if _failed_delivery_matches_recipient(failed_identities, recipient):
            continue
        message = build_version_notification_text(
            version=normalized_version,
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
                    "account_id": recipient.account_id,
                    "adapter_slot": recipient.adapter_slot,
                    "chat_id": recipient.chat_id,
                    "failed_at": resolved_now.isoformat(timespec="seconds"),
                    "reason": _delivery_error_reason(exc),
                }
            continue
        _clear_resolved_failures(failed_identities, recipient, identities)
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
    adapter_slot_filter = _optional_positive_int(adapter_slot) if adapter_slot is not None else None
    if adapter_slot is not None and adapter_slot_filter is None:
        return []
    recipients: list[VersionNotificationRecipient] = []
    try:
        identities = account_store._load_identities()
    except AccountStoreError:
        raise
    for identity_key, payload in identities.items():
        if not isinstance(identity_key, str) or not identity_key.startswith("telegram:"):
            continue
        if not isinstance(payload, dict):
            continue
        account_id = str(payload.get("account_id") or "")
        last_seen = _parse_datetime(str(payload.get("last_seen_at") or ""))
        if not account_id or last_seen is None or last_seen < threshold:
            continue
        route = payload.get("last_route") if isinstance(payload.get("last_route"), dict) else {}
        route_channel = str(route.get("channel") or "telegram").strip().casefold()
        route_chat_type = str(route.get("chat_type") or "").strip().casefold()
        route_slot = _normalize_adapter_slot(route.get("adapter_slot"), default=1)
        if adapter_slot_filter is not None and route_slot != adapter_slot_filter:
            continue
        if route_channel != "telegram":
            continue
        if route_chat_type and route_chat_type != "private":
            continue
        chat_id_text = str(route.get("chat_id") or "").strip()
        if not chat_id_text and identity_key.startswith("telegram:user:"):
            chat_id_text = identity_key.removeprefix("telegram:user:")
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
    return _deduplicate_telegram_recipients(recipients)


def build_version_notification_text(*, version: str, repo_url: str = DEFAULT_REPO_URL, memory_text: str = "") -> str:
    safe_repo_url = _normalize_github_url(repo_url) or DEFAULT_REPO_URL
    return "\n".join(
        [
            f"TeeBotus wurde auf Version {version} aktualisiert.",
            f"Repo: {safe_repo_url}",
            "Kleiner Hinweis aus dem Maschinenraum: Es wurde geschraubt, sortiert und einmal sehr ernst auf ein Logfile geschaut.",
            _memory_shaped_joke(memory_text),
        ]
    )


def _normalize_version_key(version: str) -> str:
    return str(version or "").strip().lstrip("vV")


def github_has_version(repo_root: Path, version: str, *, remote: str = "origin") -> bool:
    normalized_version = _normalize_version_key(version)
    if not normalized_version:
        return False
    tag = f"v{normalized_version}"
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


def _deduplicate_telegram_recipients(recipients: list[VersionNotificationRecipient]) -> list[VersionNotificationRecipient]:
    unique: dict[tuple[str, int, int], VersionNotificationRecipient] = {}
    for recipient in sorted(recipients, key=lambda item: item.identity_key):
        route_key = (recipient.account_id, recipient.chat_id, recipient.adapter_slot)
        unique.setdefault(route_key, recipient)
    return sorted(unique.values(), key=lambda item: item.identity_key)


def _sent_delivery_matches_recipient(
    sent_identities: set[str],
    recipient: VersionNotificationRecipient,
    identities: dict[str, Any],
) -> bool:
    if recipient.identity_key in sent_identities:
        return True
    for identity_key in sent_identities:
        payload = identities.get(identity_key)
        if not isinstance(payload, dict):
            continue
        account_id = str(payload.get("account_id") or "")
        if account_id != recipient.account_id:
            continue
        if _identity_route_matches_recipient(identity_key, payload, recipient):
            return True
    return False


def _identity_route_matches_recipient(identity_key: str, payload: dict[str, Any], recipient: VersionNotificationRecipient) -> bool:
    route = payload.get("last_route") if isinstance(payload.get("last_route"), dict) else {}
    route_channel = str(route.get("channel") or "telegram").strip().casefold()
    if route_channel != "telegram":
        return False
    route_chat_type = str(route.get("chat_type") or "").strip().casefold()
    if route_chat_type and route_chat_type != "private":
        return False
    route_slot = _normalize_adapter_slot(route.get("adapter_slot"), default=1)
    chat_id_text = str(route.get("chat_id") or "").strip()
    if not chat_id_text and identity_key.startswith("telegram:user:"):
        chat_id_text = identity_key.removeprefix("telegram:user:")
    chat_id = _optional_int(chat_id_text)
    return chat_id == recipient.chat_id and route_slot == recipient.adapter_slot


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
    failures = [failed_identities.get(recipient.identity_key)]
    failures.extend(
        failure
        for identity_key, failure in failed_identities.items()
        if identity_key != recipient.identity_key
    )
    return any(_failed_delivery_route_matches(failure, recipient) for failure in failures)


def _clear_resolved_failures(
    failed_identities: dict[str, object],
    recipient: VersionNotificationRecipient,
    identities: dict[str, Any],
) -> None:
    for identity_key, failure in list(failed_identities.items()):
        if identity_key == recipient.identity_key:
            failed_identities.pop(identity_key, None)
            continue
        payload = identities.get(identity_key)
        if isinstance(payload, dict) and str(payload.get("account_id") or "") == recipient.account_id:
            failed_identities.pop(identity_key, None)
            continue
        if _failed_delivery_route_matches(failure, recipient):
            failed_identities.pop(identity_key, None)


def _failed_delivery_route_matches(failure: object, recipient: VersionNotificationRecipient) -> bool:
    if not isinstance(failure, dict):
        return False
    failed_account_id = str(failure.get("account_id") or "").strip()
    if failed_account_id and failed_account_id != recipient.account_id:
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


def _optional_positive_int(value: object) -> int | None:
    resolved = _optional_int(value)
    if resolved is None or resolved <= 0:
        return None
    return resolved


def _delivery_error_reason(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    return text[:240]


def _version_state(state: dict[str, Any], version: str) -> dict[str, Any]:
    normalized_version = _normalize_version_key(version)
    versions = state.setdefault("versions", {})
    if not isinstance(versions, dict):
        versions = {}
        state["versions"] = versions
    matching_keys = [
        key
        for key in list(versions)
        if isinstance(key, str) and _normalize_version_key(key) == normalized_version
    ]
    if not matching_keys:
        versions[normalized_version] = {}
        return versions[normalized_version]

    matching_keys.sort(key=lambda key: key == normalized_version)
    merged: dict[str, Any] = {}
    for key in matching_keys:
        raw_version_state = versions.pop(key, None)
        if isinstance(raw_version_state, dict):
            merged = _merge_version_notification_state(merged, raw_version_state)
    versions[normalized_version] = merged
    return merged


def _merge_version_notification_state(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = {**base, **incoming}
    sent_identities = set(_string_list(base.get("sent_identities")))
    sent_identities.update(_string_list(incoming.get("sent_identities")))
    if sent_identities or "sent_identities" in base or "sent_identities" in incoming:
        merged["sent_identities"] = sorted(sent_identities)
    failed_identities = _failed_identity_map(base.get("failed_identities"))
    failed_identities.update(_failed_identity_map(incoming.get("failed_identities")))
    if failed_identities or "failed_identities" in base or "failed_identities" in incoming:
        merged["failed_identities"] = dict(sorted(failed_identities.items()))
    return merged


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
        if not identity_key or not isinstance(payload, dict):
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
    normalized_versions: dict[str, Any] = {}
    for key, value in sorted(versions.items(), key=_version_state_normalization_order):
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        version_key = _normalize_version_key(key)
        if not version_key:
            continue
        normalized_value = _merge_version_notification_state({}, value)
        existing = normalized_versions.get(version_key)
        if isinstance(existing, dict):
            normalized_versions[version_key] = _merge_version_notification_state(existing, normalized_value)
        else:
            normalized_versions[version_key] = normalized_value
    normalized["versions"] = dict(sorted(normalized_versions.items()))
    return normalized


def _version_state_normalization_order(item: tuple[Any, Any]) -> bool:
    key = item[0]
    return isinstance(key, str) and bool(_normalize_version_key(key)) and _normalize_version_key(key) == key


def _state_has_versions(state: dict[str, Any]) -> bool:
    versions = state.get("versions")
    return isinstance(versions, dict) and bool(versions)
