from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from TeeBotus.runtime.accounts import AccountStore
from TeeBotus.runtime.events import IncomingEvent
from TeeBotus.runtime.timezone import local_now, to_local

ACTIVITY_PROFILE_SCHEMA_VERSION = 1
ACTIVITY_HISTORY_LIMIT = 1000
ACTIVITY_HISTORY_DAYS = 90
ACTIVITY_MIN_OBSERVATIONS = 6
ACTIVITY_RECENT_ONLINE_WINDOW = timedelta(minutes=15)
ACTIVITY_SMOOTHING_NEIGHBOR_WEIGHT = 0.35
ACTIVITY_WAKE_COMPONENT_GAP_HOURS = 2
ACTIVITY_MAX_RECOMMENDED_HOURS = 6


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
    if not account_id or not event.is_private:
        return
    with account_store.account_memory_lock(account_id):
        state = account_store.read_agent_state(account_id)
        profile = _ensure_activity_profile(state)
        resolved_now = _aware(now or local_now())
        observed_at = resolved_now.isoformat(timespec="seconds")
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
        profile["observations"] = _trim_observations(observations, now=resolved_now)
        previous_updated_at = _parse_datetime(str(profile.get("updated_at") or ""))
        if previous_updated_at is None or resolved_now >= previous_updated_at:
            profile["updated_at"] = observed_at
        profile["derived"] = derive_activity_profile(profile["observations"], now=resolved_now)
        account_store.write_agent_state(account_id, state)


def contact_timing_decision(
    account_store: AccountStore,
    account_id: str,
    *,
    now: datetime | None = None,
    route: Mapping[str, Any] | None = None,
) -> ContactTimingDecision:
    resolved_now = _aware(now or local_now())
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
    hour = to_local(resolved_now).hour
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
    resolved_now = _aware(now or local_now())
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
            "quiet_hours": "hours outside the inferred activity blocks",
            "recommended_contact_hours": "hours with the strongest smoothed recent activity signal",
            "activity_blocks": "separate clusters of observed activity so morning and evening activity do not mark the whole day as reachable",
            "sleep_hours": "longest quiet block inferred from hours outside activity blocks",
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
    trimmed.sort(key=lambda value: _parse_datetime(str(value.get("at") or "")) or datetime.min.replace(tzinfo=timezone.utc))
    return trimmed[-ACTIVITY_HISTORY_LIMIT:]


def _parse_observation(value: Any, now: datetime) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    observed_at = _parse_datetime(str(value.get("at") or ""))
    if observed_at is None or observed_at > now + timedelta(minutes=5) or observed_at < now - timedelta(days=ACTIVITY_HISTORY_DAYS):
        return None
    local = to_local(observed_at)
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
    smoothed = _smooth_hour_counts(counts)
    max_count = max(smoothed)
    active_threshold = max(0.55, max_count * 0.32)
    active_hours = [hour for hour, value in enumerate(smoothed) if value >= active_threshold]
    if not active_hours:
        active_hours = [max(range(24), key=lambda hour: smoothed[hour])]
    activity_blocks = _activity_blocks(active_hours, max_gap=ACTIVITY_WAKE_COMPONENT_GAP_HOURS)
    wake_hours = _wake_hours_from_blocks(activity_blocks)
    recommended_threshold = max(0.8, max_count * 0.55)
    recommended = [hour for hour, value in enumerate(smoothed) if value >= recommended_threshold and hour in wake_hours]
    if not recommended:
        recommended = active_hours[:]
    recommended = sorted(set(recommended), key=lambda hour: smoothed[hour], reverse=True)[:ACTIVITY_MAX_RECOMMENDED_HOURS]
    work_hours = [hour for hour in range(8, 18) if smoothed[hour] >= active_threshold]
    learning_hours = [hour for hour in range(18, 23) if smoothed[hour] >= active_threshold]
    quiet_hours = [hour for hour in range(24) if hour not in wake_hours]
    sleep_hours = _longest_quiet_block(quiet_hours)
    return {
        "observation_count": len(entries),
        "sufficient_data": True,
        "wake_hours": wake_hours,
        "quiet_hours": quiet_hours,
        "sleep_hours": sleep_hours,
        "recommended_contact_hours": sorted(set(recommended)),
        "work_hours": work_hours,
        "learning_hours": learning_hours,
        "activity_blocks": activity_blocks,
        "hour_scores": [round(value, 4) for value in smoothed],
        "peak_hours": sorted(range(24), key=lambda hour: smoothed[hour], reverse=True)[:5],
    }


def _smooth_hour_counts(counts: list[float]) -> list[float]:
    if len(counts) != 24:
        return []
    smoothed: list[float] = []
    for hour, value in enumerate(counts):
        previous_hour = (hour - 1) % 24
        next_hour = (hour + 1) % 24
        smoothed.append(value + counts[previous_hour] * ACTIVITY_SMOOTHING_NEIGHBOR_WEIGHT + counts[next_hour] * ACTIVITY_SMOOTHING_NEIGHBOR_WEIGHT)
    return smoothed


def _activity_blocks(active_hours: list[int], *, max_gap: int) -> list[dict[str, Any]]:
    ordered = sorted(set(int(hour) for hour in active_hours if 0 <= int(hour) <= 23))
    if not ordered:
        return []
    groups: list[list[int]] = [[ordered[0]]]
    for hour in ordered[1:]:
        if hour - groups[-1][-1] <= max_gap:
            groups[-1].append(hour)
        else:
            groups.append([hour])
    if len(groups) > 1 and groups[0][0] + 24 - groups[-1][-1] <= max_gap:
        groups[0] = groups[-1] + groups[0]
        groups.pop()
    blocks: list[dict[str, Any]] = []
    for group in groups:
        normalized = sorted({hour % 24 for hour in group})
        blocks.append({"hours": normalized, "start": normalized[0], "end": normalized[-1], "size": len(normalized)})
    return sorted(blocks, key=lambda block: (block["size"], -block["start"]), reverse=True)


def _wake_hours_from_blocks(blocks: list[dict[str, Any]]) -> list[int]:
    wake_hours: set[int] = set()
    for block in blocks:
        hours = block.get("hours")
        if not isinstance(hours, list):
            continue
        for hour in hours:
            if isinstance(hour, int):
                wake_hours.update({(hour - 1) % 24, hour % 24, (hour + 1) % 24})
    return sorted(wake_hours)


def _longest_quiet_block(quiet_hours: list[int]) -> list[int]:
    blocks = _activity_blocks(quiet_hours, max_gap=1)
    if not blocks:
        return []
    return list(blocks[0].get("hours") or [])


def _day_profile(derived: Mapping[str, Any], now: datetime) -> Mapping[str, Any]:
    profiles = derived.get("profiles")
    if not isinstance(profiles, Mapping):
        return {}
    key = "weekend" if to_local(now).weekday() >= 5 else "weekday"
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
