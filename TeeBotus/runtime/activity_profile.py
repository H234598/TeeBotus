from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from TeeBotus.runtime.accounts import AccountStore
from TeeBotus.runtime.events import IncomingEvent

ACTIVITY_PROFILE_SCHEMA_VERSION = 1
ACTIVITY_HISTORY_LIMIT = 1000
ACTIVITY_HISTORY_DAYS = 90
ACTIVITY_MIN_OBSERVATIONS = 6
ACTIVITY_RECENT_ONLINE_WINDOW = timedelta(minutes=15)


@dataclass(frozen=True)
class ContactTimingDecision:
    allowed: bool
    reason: str
    profile: dict[str, Any]


def record_account_activity(
    account_store: AccountStore,
    account_id: str,
    event: IncomingEvent,
    *,
    now: datetime | None = None,
) -> None:
    if not account_id or event.chat_type != "private":
        return
    state = account_store.read_agent_state(account_id)
    profile = _ensure_activity_profile(state)
    observed_at = _aware(now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    observations = profile.setdefault("observations", [])
    if not isinstance(observations, list):
        observations = []
        profile["observations"] = observations
    observations.append(
        {
            "at": observed_at,
            "channel": event.channel,
            "route_key": f"{event.channel}:{event.adapter_slot}:{event.chat_id}",
            "text_length": min(4000, len(str(event.text or ""))),
            "attachment_count": len(event.attachments),
        }
    )
    profile["observations"] = _trim_observations(observations, now=_aware(now or datetime.now(timezone.utc)))
    profile["updated_at"] = observed_at
    profile["derived"] = derive_activity_profile(profile["observations"], now=_aware(now or datetime.now(timezone.utc)))
    account_store.write_agent_state(account_id, state)


def contact_timing_decision(
    account_store: AccountStore,
    account_id: str,
    *,
    now: datetime | None = None,
    route: Mapping[str, Any] | None = None,
) -> ContactTimingDecision:
    resolved_now = _aware(now or datetime.now(timezone.utc))
    state = account_store.read_agent_state(account_id)
    profile = state.get("activity_profile")
    if not isinstance(profile, Mapping):
        return ContactTimingDecision(True, "activity_profile_insufficient", {})
    observations = profile.get("observations")
    if not isinstance(observations, list):
        return ContactTimingDecision(True, "activity_profile_insufficient", {})
    derived = derive_activity_profile(observations, now=resolved_now)
    if not derived.get("sufficient_data"):
        return ContactTimingDecision(True, "activity_profile_insufficient", derived)
    day_profile = _day_profile(derived, resolved_now)
    hour = resolved_now.astimezone().hour
    if hour in day_profile.get("recommended_contact_hours", []):
        return ContactTimingDecision(True, "adaptive_contact_hour", derived)
    if (
        route is not None
        and _route_recently_seen(route, resolved_now)
        and hour in day_profile.get("wake_hours", [])
        and hour not in day_profile.get("quiet_hours", [])
    ):
        return ContactTimingDecision(True, "user_recently_active_in_wake_window", derived)
    return ContactTimingDecision(False, "outside_adaptive_contact_window", derived)


def derive_activity_profile(observations: list[Any], *, now: datetime | None = None) -> dict[str, Any]:
    resolved_now = _aware(now or datetime.now(timezone.utc))
    parsed = [_parse_observation(value, resolved_now) for value in observations]
    parsed = [value for value in parsed if value is not None]
    if len(parsed) < ACTIVITY_MIN_OBSERVATIONS:
        return {
            "schema_version": ACTIVITY_PROFILE_SCHEMA_VERSION,
            "sufficient_data": False,
            "observation_count": len(parsed),
        }
    profiles = {
        "weekday": _build_day_profile([entry for entry in parsed if entry["weekday"] < 5]),
        "weekend": _build_day_profile([entry for entry in parsed if entry["weekday"] >= 5]),
        "all": _build_day_profile(parsed),
    }
    return {
        "schema_version": ACTIVITY_PROFILE_SCHEMA_VERSION,
        "sufficient_data": True,
        "observation_count": len(parsed),
        "profiles": profiles,
        "notes": {
            "weekday_weekend_split": "weekend profile is used when it has enough observations, otherwise all observations are used",
            "quiet_hours": "low-observation hours outside the inferred wake span",
            "recommended_contact_hours": "hours with the strongest recent activity signal",
        },
    }


def _ensure_activity_profile(state: dict[str, Any]) -> dict[str, Any]:
    state.setdefault("schema_version", 1)
    profile = state.setdefault("activity_profile", {})
    if not isinstance(profile, dict):
        profile = {}
        state["activity_profile"] = profile
    profile["schema_version"] = ACTIVITY_PROFILE_SCHEMA_VERSION
    return profile


def _trim_observations(observations: list[Any], *, now: datetime) -> list[Any]:
    cutoff = now - timedelta(days=ACTIVITY_HISTORY_DAYS)
    trimmed: list[Any] = []
    for value in observations:
        if not isinstance(value, Mapping):
            continue
        observed_at = _parse_datetime(str(value.get("at") or ""))
        if observed_at is None or observed_at < cutoff:
            continue
        trimmed.append(dict(value))
    return trimmed[-ACTIVITY_HISTORY_LIMIT:]


def _parse_observation(value: Any, now: datetime) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    observed_at = _parse_datetime(str(value.get("at") or ""))
    if observed_at is None or observed_at > now + timedelta(minutes=5):
        return None
    local = observed_at.astimezone()
    age_days = max(0.0, (now - observed_at).total_seconds() / 86400)
    recency_weight = max(0.25, 1.0 - age_days / ACTIVITY_HISTORY_DAYS)
    text_length = _int_value(value.get("text_length"), default=0)
    weight = recency_weight * (1.0 + min(text_length, 1200) / 2400)
    if _int_value(value.get("attachment_count"), default=0) > 0:
        weight += 0.2
    return {"hour": local.hour, "weekday": local.weekday(), "weight": weight}


def _build_day_profile(entries: list[dict[str, Any]]) -> dict[str, Any]:
    counts = [0.0 for _ in range(24)]
    for entry in entries:
        counts[int(entry["hour"])] += float(entry["weight"])
    total = sum(counts)
    if len(entries) < 4 or total <= 0:
        return {"observation_count": len(entries), "sufficient_data": False}
    max_count = max(counts)
    active_threshold = max(0.55, max_count * 0.24)
    active_hours = [hour for hour, value in enumerate(counts) if value >= active_threshold]
    if not active_hours:
        active_hours = [max(range(24), key=lambda hour: counts[hour])]
    wake_hours = _expanded_hour_span(active_hours, before=1, after=2)
    recommended_threshold = max(0.8, max_count * 0.45)
    recommended = [hour for hour, value in enumerate(counts) if value >= recommended_threshold and hour in wake_hours]
    if not recommended:
        recommended = active_hours[:]
    work_hours = [hour for hour in range(8, 18) if counts[hour] >= active_threshold]
    learning_hours = [hour for hour in range(18, 23) if counts[hour] >= active_threshold]
    quiet_hours = [hour for hour in range(24) if hour not in wake_hours]
    return {
        "observation_count": len(entries),
        "sufficient_data": True,
        "wake_hours": wake_hours,
        "quiet_hours": quiet_hours,
        "recommended_contact_hours": sorted(set(recommended)),
        "work_hours": work_hours,
        "learning_hours": learning_hours,
        "peak_hours": sorted(range(24), key=lambda hour: counts[hour], reverse=True)[:5],
    }


def _expanded_hour_span(active_hours: list[int], *, before: int, after: int) -> list[int]:
    ordered = sorted(set(active_hours))
    if not ordered:
        return []
    start = max(0, ordered[0] - before)
    end = min(23, ordered[-1] + after)
    if end - start > 18:
        return list(range(24))
    return list(range(start, end + 1))


def _day_profile(derived: Mapping[str, Any], now: datetime) -> Mapping[str, Any]:
    profiles = derived.get("profiles")
    if not isinstance(profiles, Mapping):
        return {}
    key = "weekend" if now.astimezone().weekday() >= 5 else "weekday"
    profile = profiles.get(key)
    if isinstance(profile, Mapping) and profile.get("sufficient_data"):
        return profile
    fallback = profiles.get("all")
    return fallback if isinstance(fallback, Mapping) else {}


def _route_recently_seen(route: Mapping[str, Any], now: datetime) -> bool:
    last_seen = _parse_datetime(str(route.get("last_seen_at") or ""))
    if last_seen is None:
        return False
    age = now - last_seen
    return timedelta(0) <= age <= ACTIVITY_RECENT_ONLINE_WINDOW


def _parse_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return _aware(parsed)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _int_value(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
