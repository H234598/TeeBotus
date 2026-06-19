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
    last_seen_at: datetime = datetime(1970, 1, 1, tzinfo=timezone.utc)


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
    if _sql_state_backend_available(account_store) or state_path.exists():
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
        account_id = _normalized_account_id(payload.get("account_id"))
        last_seen = _parse_datetime(str(payload.get("last_seen_at") or ""))
        if not account_id or last_seen is None or last_seen < threshold:
            continue
        route = payload.get("last_route") if isinstance(payload.get("last_route"), dict) else {}
        route_channel = _route_channel(route)
        route_chat_type = _route_chat_type(route)
        route_slot = _route_adapter_slot(route)
        if route_slot is None:
            continue
        if adapter_slot_filter is not None and route_slot != adapter_slot_filter:
            continue
        if route_channel != "telegram":
            continue
        if route_chat_type is None or (route_chat_type and route_chat_type != "private"):
            continue
        chat_id = _route_chat_id(route, identity_key)
        if chat_id is None:
            continue
        recipients.append(
            VersionNotificationRecipient(
                instance_name=instance_name,
                account_id=account_id,
                identity_key=identity_key,
                chat_id=chat_id,
                adapter_slot=route_slot,
                last_seen_at=last_seen,
            )
        )
    return _deduplicate_telegram_recipients(recipients)


def build_version_notification_text(*, version: str, repo_url: str = DEFAULT_REPO_URL, memory_text: str = "") -> str:
    display_version = _normalize_version_key(version) or _inline_text(version) or "unbekannt"
    safe_repo_url = _normalize_github_url(repo_url) or DEFAULT_REPO_URL
    return "\n".join(
        [
            f"TeeBotus wurde auf Version {display_version} aktualisiert.",
            f"Repo: {safe_repo_url}",
            "Kleiner Hinweis aus dem Maschinenraum: Es wurde geschraubt, sortiert und einmal sehr ernst auf ein Logfile geschaut.",
            _memory_shaped_joke(memory_text),
        ]
    )


def _normalize_version_key(version: str) -> str:
    text = _inline_text(version)
    if text in {"v", "V"}:
        return ""
    if len(text) >= 2 and text[0] in {"v", "V"} and text[1].isdigit():
        return text[1:]
    return text


def _inline_text(value: object) -> str:
    text = "".join(char if ord(char) >= 32 and ord(char) != 127 else " " for char in str(value or ""))
    return " ".join(text.split())


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
    if result.returncode != 0:
        return False
    expected_refs = {f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"}
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        if parts and parts[-1] in expected_refs:
            return True
    return False


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
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return ""
    if parsed.scheme in {"http", "https", "ssh"} and parsed.hostname:
        if parsed.hostname != "github.com":
            return ""
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) < 2:
            return ""
        owner = path_parts[0]
        repo = path_parts[1]
        if repo.endswith(".git"):
            repo = repo[:-4]
        if not _valid_github_path_part(owner) or not _valid_github_path_part(repo):
            return ""
        netloc = parsed.hostname
        try:
            port = parsed.port
        except ValueError:
            return ""
        if port is not None and parsed.scheme in {"http", "https"}:
            netloc = f"{netloc}:{port}"
        raw = urlunsplit(("https", netloc, f"/{owner}/{repo}", "", ""))
    else:
        return ""
    return raw


def _valid_github_path_part(value: str) -> bool:
    if not value or value in {".", ".."}:
        return False
    return all(char.isascii() and (char.isalnum() or char in "._-") for char in value)


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


def _route_adapter_slot(route: dict[str, Any]) -> int | None:
    value = route.get("adapter_slot")
    if value is None or str(value).strip() == "":
        return 1
    return _optional_positive_int(value)


def _route_channel(route: dict[str, Any]) -> str | None:
    if "channel" not in route:
        return "telegram"
    text = str(route.get("channel") or "").strip().casefold()
    return text or None


def _route_chat_type(route: dict[str, Any]) -> str | None:
    if "chat_type" not in route:
        return ""
    text = str(route.get("chat_type") or "").strip().casefold()
    return text or None


def _route_chat_id(route: dict[str, Any], identity_key: str) -> int | None:
    if "chat_id" not in route:
        return _telegram_user_identity_chat_id(identity_key)
    value = route.get("chat_id")
    if isinstance(value, bool):
        return None
    chat_id_text = str(value or "").strip()
    if not chat_id_text or not chat_id_text.isdigit() or int(chat_id_text) <= 0:
        return None
    return int(chat_id_text)


def _deduplicate_telegram_recipients(recipients: list[VersionNotificationRecipient]) -> list[VersionNotificationRecipient]:
    unique_by_account_slot: dict[tuple[str, int], VersionNotificationRecipient] = {}
    for recipient in sorted(recipients, key=lambda item: item.identity_key):
        route_key = (recipient.account_id, recipient.adapter_slot)
        existing = unique_by_account_slot.get(route_key)
        if existing is None or _recipient_route_preferred(recipient, existing):
            unique_by_account_slot[route_key] = recipient
    unique_by_route: dict[tuple[int, int], VersionNotificationRecipient] = {}
    for recipient in sorted(unique_by_account_slot.values(), key=lambda item: item.identity_key):
        route_key = (recipient.adapter_slot, recipient.chat_id)
        existing = unique_by_route.get(route_key)
        if existing is None or _recipient_route_preferred(recipient, existing):
            unique_by_route[route_key] = recipient
    return sorted(unique_by_route.values(), key=lambda item: item.identity_key)


def _recipient_route_preferred(candidate: VersionNotificationRecipient, current: VersionNotificationRecipient) -> bool:
    if candidate.chat_id == current.chat_id:
        return _recipient_identity_rank(candidate.identity_key) > _recipient_identity_rank(current.identity_key)
    return _recipient_freshness_key(candidate) > _recipient_freshness_key(current)


def _recipient_freshness_key(recipient: VersionNotificationRecipient) -> tuple[datetime, int, str]:
    return (recipient.last_seen_at, _recipient_identity_rank(recipient.identity_key), recipient.identity_key)


def _recipient_identity_rank(identity_key: str) -> int:
    return 1 if identity_key.startswith("telegram:user:") else 0


def _sent_delivery_matches_recipient(
    sent_identities: set[str],
    recipient: VersionNotificationRecipient,
    identities: dict[str, Any],
) -> bool:
    if recipient.identity_key in sent_identities:
        return True
    for identity_key in sent_identities:
        if _encoded_telegram_user_route_matches_recipient(identity_key, recipient):
            return True
        payload = identities.get(identity_key)
        if not isinstance(payload, dict):
            continue
        if _normalized_account_id(payload.get("account_id")) == recipient.account_id:
            return True
        if _identity_route_matches_recipient(identity_key, payload, recipient):
            return True
    return False


def _identity_route_matches_recipient(identity_key: str, payload: dict[str, Any], recipient: VersionNotificationRecipient) -> bool:
    route = payload.get("last_route") if isinstance(payload.get("last_route"), dict) else {}
    route_channel = _route_channel(route)
    if route_channel != "telegram":
        return False
    route_chat_type = _route_chat_type(route)
    if route_chat_type is None or (route_chat_type and route_chat_type != "private"):
        return False
    route_slot = _route_adapter_slot(route)
    if route_slot is None:
        return False
    chat_id = _route_chat_id(route, identity_key)
    return chat_id == recipient.chat_id and route_slot == recipient.adapter_slot


def _encoded_telegram_user_route_matches_recipient(identity_key: str, recipient: VersionNotificationRecipient) -> bool:
    chat_id = _telegram_user_identity_chat_id(identity_key)
    return chat_id == recipient.chat_id and recipient.adapter_slot == 1


def _telegram_user_identity_chat_id(identity_key: str) -> int | None:
    if not identity_key.startswith("telegram:user:"):
        return None
    chat_id_text = identity_key.removeprefix("telegram:user:").strip()
    if not chat_id_text.isdigit():
        return None
    chat_id = int(chat_id_text)
    return chat_id if chat_id > 0 else None


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
            "can't initiate conversation",
            "cannot initiate conversation",
        )
    )


def _failed_delivery_matches_recipient(failed_identities: dict[str, object], recipient: VersionNotificationRecipient) -> bool:
    failures = [failed_identities.get(recipient.identity_key)]
    failures.extend(
        failure
        for identity_key, failure in failed_identities.items()
        if identity_key != recipient.identity_key
    )
    if any(_failed_delivery_route_matches(failure, recipient) for failure in failures):
        return True
    return any(
        identity_key != recipient.identity_key and _failed_identity_key_route_matches(identity_key, failure, recipient)
        for identity_key, failure in failed_identities.items()
    )


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
        if isinstance(payload, dict) and _normalized_account_id(payload.get("account_id")) == recipient.account_id:
            failed_identities.pop(identity_key, None)
            continue
        if _failed_delivery_route_matches(failure, recipient) or _failed_identity_key_route_matches(identity_key, failure, recipient):
            failed_identities.pop(identity_key, None)


def _failed_delivery_route_matches(failure: object, recipient: VersionNotificationRecipient) -> bool:
    if not isinstance(failure, dict):
        return False
    failed_account_id = _normalized_account_id(failure.get("account_id"))
    if failed_account_id and failed_account_id != recipient.account_id:
        return False
    failed_chat_id = _optional_positive_int(failure.get("chat_id"))
    failed_slot = _optional_positive_int(failure.get("adapter_slot"))
    if failed_chat_id is None or failed_slot is None:
        return False
    return failed_chat_id == recipient.chat_id and failed_slot == recipient.adapter_slot


def _failed_identity_key_route_matches(identity_key: str, failure: object, recipient: VersionNotificationRecipient) -> bool:
    if not _encoded_telegram_user_route_matches_recipient(identity_key, recipient):
        return False
    if not isinstance(failure, dict):
        return False
    failed_account_id = _normalized_account_id(failure.get("account_id"))
    return not failed_account_id or failed_account_id == recipient.account_id


def _normalized_account_id(value: object) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 128:
        return ""
    return text if all(char in "0123456789abcdef" for char in text) else ""


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
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
    updated_at = _newest_timestamp_string(base.get("updated_at"), incoming.get("updated_at"))
    if updated_at:
        merged["updated_at"] = updated_at
    sent_identities = set(_string_list(base.get("sent_identities")))
    sent_identities.update(_string_list(incoming.get("sent_identities")))
    if sent_identities or "sent_identities" in base or "sent_identities" in incoming:
        merged["sent_identities"] = sorted(sent_identities)
    failed_identities = _failed_identity_map(base.get("failed_identities"))
    for identity_key, failure in _failed_identity_map(incoming.get("failed_identities")).items():
        existing_failure = failed_identities.get(identity_key)
        if existing_failure is not None and _failure_payload_quality(existing_failure) > _failure_payload_quality(failure):
            continue
        if existing_failure is not None:
            failure = _merge_failure_payload(existing_failure, failure)
        failed_identities[identity_key] = failure
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
        if not _is_telegram_identity_key(identity_key) or not isinstance(payload, dict):
            continue
        normalized[identity_key] = _normalized_failure_payload(payload)
    return normalized


def _is_telegram_identity_key(identity_key: str) -> bool:
    return identity_key.startswith("telegram:")


def _normalized_failure_payload(payload: dict[str, Any]) -> dict[str, object]:
    normalized = dict(payload)
    account_id = _normalized_account_id(normalized.get("account_id"))
    if account_id:
        normalized["account_id"] = account_id
    else:
        normalized.pop("account_id", None)
    return normalized


def _failure_payload_quality(value: object) -> int:
    if not isinstance(value, dict):
        return 0
    has_route = _optional_positive_int(value.get("chat_id")) is not None and _optional_positive_int(value.get("adapter_slot")) is not None
    return 2 if has_route else 1


def _merge_failure_payload(base: object, incoming: object) -> dict[str, object]:
    merged: dict[str, object] = {}
    base_timestamp = _parse_datetime(str(base.get("failed_at") or "")) if isinstance(base, dict) else None
    incoming_timestamp = _parse_datetime(str(incoming.get("failed_at") or "")) if isinstance(incoming, dict) else None
    if isinstance(base, dict) and isinstance(incoming, dict) and base_timestamp is not None and incoming_timestamp is not None:
        older, newer = (incoming, base) if base_timestamp > incoming_timestamp else (base, incoming)
        merged.update(older)
        merged.update(newer)
        return merged
    if isinstance(base, dict):
        merged.update(base)
    if isinstance(incoming, dict):
        merged.update(incoming)
    failed_at = _newest_timestamp_string(
        base.get("failed_at") if isinstance(base, dict) else None,
        incoming.get("failed_at") if isinstance(incoming, dict) else None,
    )
    if failed_at:
        merged["failed_at"] = failed_at
    return merged


def _newest_timestamp_string(base: object, incoming: object) -> str:
    base_text = str(base or "").strip() if isinstance(base, str) else ""
    incoming_text = str(incoming or "").strip() if isinstance(incoming, str) else ""
    base_timestamp = _parse_datetime(base_text)
    incoming_timestamp = _parse_datetime(incoming_text)
    if base_timestamp is not None and incoming_timestamp is not None:
        return base_text if base_timestamp >= incoming_timestamp else incoming_text
    if incoming_timestamp is not None:
        return incoming_text
    if base_timestamp is not None:
        return base_text
    return incoming_text or base_text


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
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError, OSError):
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
