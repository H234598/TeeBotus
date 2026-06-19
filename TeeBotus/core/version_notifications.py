from __future__ import annotations

import json
import re
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
SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


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
    sent_identities = set(_telegram_identity_list(version_state.get("sent_identities")))
    identities = account_store._load_identities()
    failed_identities = _failed_identity_map(version_state.get("failed_identities"))
    historical_failed_identities = _historical_failed_identity_map(state, normalized_version, identities)
    version_state["failed_identities"] = failed_identities
    sent_count = 0
    for recipient in recent_telegram_recipients(account_store, instance_name=instance_name, adapter_slot=adapter_slot, now=resolved_now):
        if _sent_delivery_matches_recipient(sent_identities, recipient, identities):
            missing_sent_alias = recipient.identity_key not in sent_identities
            previous_failures = dict(failed_identities)
            _clear_resolved_failures(failed_identities, recipient, identities)
            sent_identities.add(recipient.identity_key)
            if missing_sent_alias or failed_identities != previous_failures:
                _sync_version_delivery_state(version_state, sent_identities, failed_identities, resolved_now)
                _write_state_incrementally(account_store, state_path, state)
            continue
        matched_failure = _matched_failed_delivery(failed_identities, recipient, identities)
        historical_failure = False
        if matched_failure is None:
            matched_failure = _matched_failed_delivery(historical_failed_identities, recipient, identities)
            historical_failure = matched_failure is not None
        if matched_failure is not None:
            if _record_skipped_failed_delivery(failed_identities, recipient, matched_failure, force_record=historical_failure):
                _sync_version_delivery_state(version_state, sent_identities, failed_identities, resolved_now)
                _write_state_incrementally(account_store, state_path, state)
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
                _sync_version_delivery_state(version_state, sent_identities, failed_identities, resolved_now)
                _write_state_incrementally(account_store, state_path, state)
            continue
        _clear_resolved_failures(failed_identities, recipient, identities)
        sent_identities.add(recipient.identity_key)
        _sync_version_delivery_state(version_state, sent_identities, failed_identities, resolved_now)
        _write_state_incrementally(account_store, state_path, state)
        sent_count += 1
    _sync_version_delivery_state(version_state, sent_identities, failed_identities, resolved_now)
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


def _version_order_key(version: str) -> tuple[tuple[int, int | str], ...]:
    text = _normalize_version_key(version)
    semver_key = _semver_order_key(text)
    if semver_key:
        return semver_key
    chunks: list[tuple[int, int | str]] = []
    current = ""
    current_is_digit: bool | None = None
    for char in text:
        is_digit = char.isdigit()
        if current and current_is_digit != is_digit:
            chunks.append((0, int(current)) if current_is_digit else (1, current.casefold()))
            current = ""
        current += char
        current_is_digit = is_digit
    if current:
        chunks.append((0, int(current)) if current_is_digit else (1, current.casefold()))
    return tuple(chunks)


def _semver_order_key(version: str) -> tuple[tuple[int, int | str], ...]:
    match = SEMVER_RE.fullmatch(version)
    if match is None:
        return ()
    chunks: list[tuple[int, int | str]] = [
        (0, int(match.group("major"))),
        (0, int(match.group("minor"))),
        (0, int(match.group("patch"))),
    ]
    prerelease = match.group("prerelease")
    if prerelease is None:
        chunks.append((2, ""))
        return tuple(chunks)
    chunks.append((1, ""))
    for identifier in prerelease.split("."):
        chunks.append((0, int(identifier)) if identifier.isdigit() else (1, identifier))
    return tuple(chunks)


def _version_is_before(version: str, reference: str) -> bool:
    version_key = _version_order_key(version)
    reference_key = _version_order_key(reference)
    return bool(version_key and reference_key and version_key < reference_key)


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
        payload = identities.get(identity_key)
        if isinstance(payload, dict):
            if _identity_route_matches_recipient(identity_key, payload, recipient):
                return True
            if _identity_account_slot_matches_recipient(payload, recipient):
                return True
            continue
        if _encoded_telegram_user_route_matches_recipient(identity_key, recipient):
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


def _identity_account_slot_matches_recipient(payload: dict[str, Any], recipient: VersionNotificationRecipient) -> bool:
    if _normalized_account_id(payload.get("account_id")) != recipient.account_id:
        return False
    route = payload.get("last_route") if isinstance(payload.get("last_route"), dict) else {}
    if _route_channel(route) != "telegram":
        return False
    route_chat_type = _route_chat_type(route)
    if route_chat_type is None or (route_chat_type and route_chat_type != "private"):
        return False
    route_slot = _route_adapter_slot(route)
    return route_slot == recipient.adapter_slot


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


def _failed_delivery_matches_recipient(
    failed_identities: dict[str, object],
    recipient: VersionNotificationRecipient,
    identities: dict[str, Any],
) -> bool:
    return _matched_failed_delivery(failed_identities, recipient, identities) is not None


def _matched_failed_delivery(
    failed_identities: dict[str, object],
    recipient: VersionNotificationRecipient,
    identities: dict[str, Any],
) -> tuple[str, dict[str, object]] | None:
    direct_failure = failed_identities.get(recipient.identity_key)
    if _failed_delivery_route_matches(direct_failure, recipient):
        return recipient.identity_key, direct_failure if isinstance(direct_failure, dict) else {}
    for identity_key, failure in failed_identities.items():
        if identity_key == recipient.identity_key:
            continue
        if _failed_identity_matches_recipient(identity_key, failure, recipient, identities):
            return identity_key, failure if isinstance(failure, dict) else {}
    return None


def _record_skipped_failed_delivery(
    failed_identities: dict[str, object],
    recipient: VersionNotificationRecipient,
    matched_failure: tuple[str, dict[str, object]],
    *,
    force_record: bool = False,
) -> bool:
    previous_failures = dict(failed_identities)
    matched_identity, source_failure = matched_failure
    if matched_identity == recipient.identity_key and not force_record:
        return False
    canonical_failure: dict[str, object] = {
        "account_id": recipient.account_id,
        "adapter_slot": recipient.adapter_slot,
        "chat_id": recipient.chat_id,
    }
    failed_at = _valid_timestamp_string(source_failure.get("failed_at"))
    if failed_at:
        canonical_failure["failed_at"] = failed_at
    reason = _inline_text(source_failure.get("reason")) if isinstance(source_failure.get("reason"), str) else ""
    if reason:
        canonical_failure["reason"] = reason[:240]
    existing_failure = failed_identities.get(recipient.identity_key)
    if isinstance(existing_failure, dict):
        canonical_failure = _merge_failure_payload(existing_failure, canonical_failure)
    normalized_failure = _normalized_failure_payload(canonical_failure)
    if normalized_failure:
        failed_identities[recipient.identity_key] = normalized_failure
    return failed_identities != previous_failures


def _historical_failed_identity_map(
    state: dict[str, Any],
    current_version: str,
    identities: dict[str, Any],
) -> dict[str, object]:
    versions = state.get("versions")
    if not isinstance(versions, dict):
        return {}
    failed_identities: dict[str, object] = {}
    ordered_versions = sorted(
        versions.items(),
        key=lambda item: _version_order_key(str(item[0] or "")),
    )
    for version_key, version_state in ordered_versions:
        if not isinstance(version_key, str) or not _version_is_before(version_key, current_version):
            continue
        if isinstance(version_state, dict):
            normalized_version_state = _merge_version_notification_state({}, version_state)
            for identity_key, failure in _failed_identity_map(normalized_version_state.get("failed_identities")).items():
                existing_failure = failed_identities.get(identity_key)
                if existing_failure is not None and _failure_payload_quality(existing_failure) > _failure_payload_quality(failure):
                    continue
                if existing_failure is not None:
                    failure = _merge_failure_payload(existing_failure, failure)
                failed_identities[identity_key] = failure
            _clear_historical_failures_resolved_by_sent_identities(
                failed_identities,
                _telegram_identity_list(normalized_version_state.get("sent_identities")),
                identities,
            )
    return dict(sorted(failed_identities.items()))


def _clear_historical_failures_resolved_by_sent_identities(
    failed_identities: dict[str, object],
    sent_identities: list[str],
    identities: dict[str, Any],
) -> None:
    for sent_identity in sent_identities:
        failed_identities.pop(sent_identity, None)
        payload = identities.get(sent_identity)
        if not isinstance(payload, dict):
            continue
        account_id = _normalized_account_id(payload.get("account_id"))
        route = payload.get("last_route") if isinstance(payload.get("last_route"), dict) else {}
        if not account_id or _route_channel(route) != "telegram":
            continue
        route_chat_type = _route_chat_type(route)
        if route_chat_type is None or (route_chat_type and route_chat_type != "private"):
            continue
        route_slot = _route_adapter_slot(route)
        chat_id = _route_chat_id(route, sent_identity)
        if route_slot is None or chat_id is None:
            continue
        recipient = VersionNotificationRecipient(
            instance_name="",
            account_id=account_id,
            identity_key=sent_identity,
            chat_id=chat_id,
            adapter_slot=route_slot,
        )
        for identity_key, failure in list(failed_identities.items()):
            if _failed_identity_matches_recipient(identity_key, failure, recipient, identities):
                failed_identities.pop(identity_key, None)


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
        failed_account_id = _normalized_account_id(failure.get("account_id")) if isinstance(failure, dict) else ""
        if (
            isinstance(payload, dict)
            and _normalized_account_id(payload.get("account_id")) == recipient.account_id
        ):
            payload_matches_slot = _identity_account_slot_matches_recipient(payload, recipient)
            if payload_matches_slot and (not failed_account_id or failed_account_id == recipient.account_id):
                failed_identities.pop(identity_key, None)
                continue
        failure_slot = _optional_positive_int(failure.get("adapter_slot")) if isinstance(failure, dict) else None
        failure_chat_id = _optional_positive_int(failure.get("chat_id")) if isinstance(failure, dict) else None
        if (
            failed_account_id == recipient.account_id
            and not _failure_payload_has_complete_route(failure)
            and (
                (failure_slot is not None and failure_slot == recipient.adapter_slot)
                or (
                    failure_slot is None
                    and (
                        (
                            not isinstance(payload, dict)
                            and (failure_chat_id is None or failure_chat_id == recipient.chat_id)
                        )
                        or (
                            isinstance(payload, dict)
                            and _identity_account_slot_matches_recipient(payload, recipient)
                        )
                    )
                )
            )
        ):
            failed_identities.pop(identity_key, None)
            continue
        if _failed_identity_matches_recipient(identity_key, failure, recipient, identities):
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


def _failure_payload_has_complete_route(failure: object) -> bool:
    if not isinstance(failure, dict):
        return False
    return _optional_positive_int(failure.get("chat_id")) is not None and _optional_positive_int(failure.get("adapter_slot")) is not None


def _failed_identity_matches_recipient(
    identity_key: str,
    failure: object,
    recipient: VersionNotificationRecipient,
    identities: dict[str, Any],
) -> bool:
    payload = identities.get(identity_key)
    if isinstance(payload, dict) and not (
        _identity_route_matches_recipient(identity_key, payload, recipient)
        or _identity_account_slot_matches_recipient(payload, recipient)
    ):
        return False
    return _failed_delivery_route_matches(failure, recipient) or _failed_identity_key_route_matches(
        identity_key,
        failure,
        recipient,
        identities,
    )


def _failed_identity_key_route_matches(
    identity_key: str,
    failure: object,
    recipient: VersionNotificationRecipient,
    identities: dict[str, Any],
) -> bool:
    if not isinstance(failure, dict):
        return False
    failure_chat_id = _optional_positive_int(failure.get("chat_id"))
    failure_slot = _optional_positive_int(failure.get("adapter_slot"))
    failed_account_id = _normalized_account_id(failure.get("account_id"))
    if failure_chat_id is not None and failure_slot is None:
        return False
    if failure_chat_id is None and failure_slot is not None and failure_slot != recipient.adapter_slot:
        return False
    if failure_chat_id is not None and failure_slot is not None and not _failed_delivery_route_matches(failure, recipient):
        return False
    payload = identities.get(identity_key)
    if isinstance(payload, dict):
        if not (_identity_route_matches_recipient(identity_key, payload, recipient) or _identity_account_slot_matches_recipient(payload, recipient)):
            return False
        return not failed_account_id or failed_account_id == recipient.account_id
    if failed_account_id and not _failure_payload_has_complete_route(failure):
        return False
    if not _encoded_telegram_user_route_matches_recipient(identity_key, recipient):
        return False
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
    return _inline_text(exc)[:240]


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
    merged: dict[str, Any] = {}
    updated_at = _newest_timestamp_string(base.get("updated_at"), incoming.get("updated_at"))
    if updated_at:
        merged["updated_at"] = updated_at
    else:
        merged.pop("updated_at", None)
    sent_identities = set(_telegram_identity_list(base.get("sent_identities")))
    sent_identities.update(_telegram_identity_list(incoming.get("sent_identities")))
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
    for sent_identity in sent_identities:
        failed_identities.pop(sent_identity, None)
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


def _telegram_identity_list(value: Any) -> list[str]:
    return [identity_key for identity_key in _string_list(value) if _is_telegram_identity_key(identity_key)]


def _failed_identity_map(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, object] = {}
    for key, payload in value.items():
        identity_key = str(key or "").strip() if isinstance(key, str) else ""
        if not _is_telegram_identity_key(identity_key) or not isinstance(payload, dict):
            continue
        normalized_payload = _normalized_failure_payload(payload)
        if not normalized_payload:
            continue
        normalized[identity_key] = normalized_payload
    return normalized


def _is_telegram_identity_key(identity_key: str) -> bool:
    if any(ord(char) < 32 or ord(char) == 127 for char in identity_key):
        return False
    return identity_key.startswith("telegram:") and bool(identity_key.removeprefix("telegram:").strip())


def _normalized_failure_payload(payload: dict[str, Any]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    account_id = _normalized_account_id(payload.get("account_id"))
    if account_id:
        normalized["account_id"] = account_id
    failed_at = _valid_timestamp_string(payload.get("failed_at"))
    if failed_at:
        normalized["failed_at"] = failed_at
    chat_id = _optional_positive_int(payload.get("chat_id"))
    if chat_id is not None:
        normalized["chat_id"] = chat_id
    adapter_slot = _optional_positive_int(payload.get("adapter_slot"))
    if adapter_slot is not None:
        normalized["adapter_slot"] = adapter_slot
    reason = _inline_text(payload.get("reason")) if isinstance(payload.get("reason"), str) else ""
    if reason:
        normalized["reason"] = reason[:240]
    return normalized


def _failure_payload_quality(value: object) -> int:
    if not isinstance(value, dict):
        return 0
    return 2 if _failure_payload_has_complete_route(value) else 1


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
    base_text = _valid_timestamp_string(base)
    incoming_text = _valid_timestamp_string(incoming)
    base_timestamp = _parse_datetime(base_text)
    incoming_timestamp = _parse_datetime(incoming_text)
    if base_timestamp is not None and incoming_timestamp is not None:
        return base_text if base_timestamp >= incoming_timestamp else incoming_text
    if incoming_timestamp is not None:
        return incoming_text
    if base_timestamp is not None:
        return base_text
    return ""


def _valid_timestamp_string(value: object) -> str:
    text = str(value or "").strip() if isinstance(value, str) else ""
    return text if _parse_datetime(text) is not None else ""


def _load_state(account_store: AccountStore, path: Path) -> dict[str, Any]:
    if _sql_state_backend_available(account_store):
        state = _normalize_state(
            account_store.read_instance_json_state(
                NOTIFICATION_STATE_FILENAME,
                NOTIFICATION_STATE_COLLECTION,
                {"versions": {}},
                fallback_to_legacy_on_read_error=False,
            )
        )
        if path.exists():
            state = _merge_notification_states(_read_legacy_state(account_store, path), state)
        return state
    return _read_legacy_state(account_store, path)


def _write_state(account_store: AccountStore, path: Path, state: dict[str, Any]) -> None:
    normalized_state = _normalize_state(state)
    if _sql_state_backend_available(account_store):
        account_store.write_instance_json_state(
            NOTIFICATION_STATE_FILENAME,
            NOTIFICATION_STATE_COLLECTION,
            normalized_state,
        )
        _unlink_legacy_state_path(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(normalized_state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _write_state_incrementally(account_store: AccountStore, path: Path, state: dict[str, Any]) -> None:
    _write_state(account_store, path, state)


def _sync_version_delivery_state(
    version_state: dict[str, Any],
    sent_identities: set[str],
    failed_identities: dict[str, object],
    updated_at: datetime,
) -> None:
    version_state["sent_identities"] = sorted(sent_identities)
    version_state["failed_identities"] = dict(sorted(failed_identities.items()))
    version_state["updated_at"] = updated_at.isoformat(timespec="seconds")


def _sql_state_backend_available(account_store: AccountStore) -> bool:
    checker = getattr(account_store, "instance_json_state_backend_available", None)
    return callable(checker) and bool(checker())


def _read_legacy_state(account_store: AccountStore, path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"versions": {}}
    reader = getattr(account_store, "_read_legacy_instance_json_state", None)
    if callable(reader):
        try:
            return _normalize_state(reader(path, {"versions": {}}))
        except (UnicodeDecodeError, json.JSONDecodeError, OSError):
            return {"versions": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError, OSError):
        return {"versions": {}}
    return _normalize_state(data)


def _unlink_legacy_state_path(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _merge_notification_states(*states: dict[str, Any]) -> dict[str, Any]:
    versions: dict[str, Any] = {}
    for state in states:
        for version_key, version_state in _normalize_state(state).get("versions", {}).items():
            if not isinstance(version_key, str) or not isinstance(version_state, dict):
                continue
            existing = versions.get(version_key)
            if isinstance(existing, dict):
                versions[version_key] = _merge_version_notification_state(existing, version_state)
            else:
                versions[version_key] = _merge_version_notification_state({}, version_state)
    return {"versions": dict(sorted(versions.items()))}


def _normalize_state(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"versions": {}}
    versions = data.get("versions")
    if not isinstance(versions, dict):
        return {"versions": {}}
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
    return {"versions": dict(sorted(normalized_versions.items()))}


def _version_state_normalization_order(item: tuple[Any, Any]) -> bool:
    key = item[0]
    return isinstance(key, str) and bool(_normalize_version_key(key)) and _normalize_version_key(key) == key
