from __future__ import annotations

import json
import hashlib
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from TeeBotus.runtime.accounts import AccountStore, utc_now

WEATHER_CONTEXT_SCHEMA_VERSION = 1
WEATHER_CHECK_INTERVAL = timedelta(hours=2)
WEATHER_TIMEOUT_SECONDS = 2.5
MAX_CITY_LENGTH = 80

CITY_PATTERNS = (
    re.compile(
        r"\b(?:ich\s+wohne|ich\s+lebe|wohn(?:e)?|lebe)\s+"
        r"(?:(?:jetzt|aktuell|derzeit)\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:meine\s+stadt|mein\s+wohnort|mein\s+ort)\s+(?:ist|heisst|heißt)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})", re.IGNORECASE),
)
CITY_TRAILING_STOP_RE = re.compile(
    r"\s+(?:und|aber|weil|wenn|falls|seit|mit|bei|heute|morgen|gestern|gerade|aktuell|\.|,|;|:|!|\?).*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class WeatherContextResult:
    city: str = ""
    weather_text: str = ""
    checked: bool = False
    skipped_reason: str = ""


WeatherProvider = Callable[[str], str]


def update_city_and_weather_context(
    account_store: AccountStore,
    account_id: str,
    text: str,
    *,
    now: datetime | None = None,
    provider: WeatherProvider | None = None,
) -> WeatherContextResult:
    if not account_id:
        return WeatherContextResult(skipped_reason="missing_account")
    with account_store.account_memory_lock(account_id):
        return _update_city_and_weather_context_unlocked(
            account_store,
            account_id,
            text,
            now=now,
            provider=provider,
        )


def _update_city_and_weather_context_unlocked(
    account_store: AccountStore,
    account_id: str,
    text: str,
    *,
    now: datetime | None = None,
    provider: WeatherProvider | None = None,
) -> WeatherContextResult:
    resolved_now = _aware(now or datetime.now(timezone.utc))
    state = account_store.read_agent_state(account_id)
    weather_state = _ensure_weather_state(state)
    city = extract_residence_city(text)
    city_changed = False
    if city:
        city_changed = city != str(weather_state.get("city") or "").strip()
        weather_state["city"] = city
        weather_state["city_updated_at"] = resolved_now.isoformat(timespec="seconds")
        if city_changed:
            # A cached summary belongs to the previous city and must not be
            # presented as current weather while the global check window is active.
            weather_state["summary"] = ""
            weather_state["last_error"] = ""
            _append_city_memory(account_store, account_id, city, resolved_now)
    current_city = str(weather_state.get("city") or "").strip()
    if not current_city:
        account_store.write_agent_state(account_id, state) if city else None
        return WeatherContextResult(skipped_reason="no_city")
    last_checked = _parse_datetime(str(weather_state.get("last_checked_at") or ""))
    if last_checked is not None and resolved_now - last_checked < WEATHER_CHECK_INTERVAL:
        if city_changed:
            account_store.write_agent_state(account_id, state)
        return WeatherContextResult(
            city=current_city,
            weather_text=str(weather_state.get("summary") or "").strip(),
            skipped_reason="rate_limited",
        )
    weather_provider = provider or fetch_weather_summary
    try:
        summary = weather_provider(current_city).strip()
    except Exception as exc:
        weather_state["summary"] = ""
        weather_state["last_error"] = f"{type(exc).__name__}: {exc}"[:240]
        weather_state["last_checked_at"] = resolved_now.isoformat(timespec="seconds")
        account_store.write_agent_state(account_id, state)
        return WeatherContextResult(city=current_city, checked=True, skipped_reason="weather_error")
    weather_state["summary"] = summary[:500]
    weather_state["last_checked_at"] = resolved_now.isoformat(timespec="seconds")
    weather_state["last_error"] = ""
    weather_state["updated_at"] = utc_now()
    account_store.write_agent_state(account_id, state)
    return WeatherContextResult(city=current_city, weather_text=weather_state["summary"], checked=True)


def _append_city_memory(account_store: AccountStore, account_id: str, city: str, now: datetime) -> None:
    try:
        account_store.append_structured_memory_entry(
            account_id,
            {
                "id": f"mem_residence_city_{_city_id_token(city)}",
                "created_at": now.isoformat(timespec="seconds"),
                "updated_at": now.isoformat(timespec="seconds"),
                "kind": "biographical_fact",
                "memory_type": "semantic",
                "importance": 4,
                "user_text": f"User erwaehnt als Wohnstadt: {city}.",
                "bot_text": "Als Wohnort fuer Wetter- und Kontextchecks gemerkt.",
                "keywords": ["wohnort", "stadt", city.casefold()],
            },
        )
    except Exception:
        return


def weather_context_text(account_store: AccountStore, account_id: str) -> str:
    state = account_store.read_agent_state(account_id)
    weather_state = state.get("weather_context")
    if not isinstance(weather_state, Mapping):
        return ""
    city = str(weather_state.get("city") or "").strip()
    summary = str(weather_state.get("summary") or "").strip()
    checked_at = str(weather_state.get("last_checked_at") or "").strip()
    last_error = str(weather_state.get("last_error") or "").strip()
    if not city or not summary or last_error:
        return ""
    return f"Stadt/Wohnort: {city}\nLetzter Wettercheck: {checked_at or 'unbekannt'}\nKurz-Wetter: {summary}"


def extract_residence_city(text: str) -> str:
    source = str(text or "")
    for pattern in CITY_PATTERNS:
        match = pattern.search(source)
        if not match:
            continue
        city = _clean_city(match.group("city"))
        if city:
            return city
    return ""


def fetch_weather_summary(city: str) -> str:
    query = urllib.parse.quote(str(city or "").strip())
    if not query:
        return ""
    url = f"https://wttr.in/{query}?format=j1"
    request = urllib.request.Request(url, headers={"User-Agent": "TeeBotus/1 weather context"})
    with urllib.request.urlopen(request, timeout=WEATHER_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    current = payload.get("current_condition", [{}])[0]
    area = payload.get("nearest_area", [{}])[0]
    name = _area_name(area) or city
    temp = str(current.get("temp_C") or "").strip()
    feels = str(current.get("FeelsLikeC") or "").strip()
    desc_values = current.get("weatherDesc") if isinstance(current.get("weatherDesc"), list) else []
    desc = str(desc_values[0].get("value") or "").strip() if desc_values and isinstance(desc_values[0], Mapping) else ""
    humidity = str(current.get("humidity") or "").strip()
    wind = str(current.get("windspeedKmph") or "").strip()
    parts = [name]
    if temp:
        parts.append(f"{temp} C")
    if feels and feels != temp:
        parts.append(f"gefuehlt {feels} C")
    if desc:
        parts.append(desc)
    if humidity:
        parts.append(f"Luftfeuchte {humidity}%")
    if wind:
        parts.append(f"Wind {wind} km/h")
    return ", ".join(parts)


def _ensure_weather_state(state: dict[str, Any]) -> dict[str, Any]:
    state.setdefault("schema_version", 1)
    weather_state = state.setdefault("weather_context", {})
    if not isinstance(weather_state, dict):
        weather_state = {}
        state["weather_context"] = weather_state
    weather_state["schema_version"] = WEATHER_CONTEXT_SCHEMA_VERSION
    return weather_state


def _clean_city(value: str) -> str:
    city = CITY_TRAILING_STOP_RE.sub("", str(value or "")).strip(" .,:;!?")
    city = re.sub(r"\s+", " ", city)
    if not city or len(city) > MAX_CITY_LENGTH:
        return ""
    if any(char.isdigit() for char in city):
        return ""
    if re.search(r"(?i)\b(?:nicht(?:\s+mehr)?|kein(?:e|er|em|en)?|mein(?:e|er|em|en)?|ein(?:e|er|em|en)?)\b", city):
        return ""
    return city


def _city_id_token(city: str) -> str:
    normalized = re.sub(r"\s+", "_", city.strip().casefold())
    normalized = re.sub(r"[^a-z0-9_]+", "", normalized)
    return normalized[:48] or hashlib.sha256(city.encode("utf-8")).hexdigest()[:16]


def _area_name(area: Mapping[str, Any]) -> str:
    values = area.get("areaName")
    if isinstance(values, list) and values and isinstance(values[0], Mapping):
        return str(values[0].get("value") or "").strip()
    return ""


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
