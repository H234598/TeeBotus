from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from TeeBotus.llm.hf_pool.metrics import HFPoolUsageEvent
from TeeBotus.llm.hf_pool.redaction import redact_hf_secrets


def default_hf_pool_state_path() -> Path:
    root = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return root / "teebotus" / "hf_pool_state.sqlite3"


def hf_pool_state_key(pool_name: object, target_name: object) -> str:
    pool = str(pool_name or "default").strip() or "default"
    target = str(target_name or "").strip()
    return f"{pool}/{target}" if target else pool


def hf_pool_state_lookup(mapping: dict[str, Any], pool_name: object, target_name: object, default: Any = None) -> Any:
    scoped_key = hf_pool_state_key(pool_name, target_name)
    if scoped_key in mapping:
        return mapping[scoped_key]
    return mapping.get(str(target_name or "").strip(), default)


def hf_pool_state_pop(mapping: dict[str, Any], pool_name: object, target_name: object) -> None:
    mapping.pop(hf_pool_state_key(pool_name, target_name), None)
    mapping.pop(str(target_name or "").strip(), None)


@dataclass
class HFPoolRuntimeState:
    cooldowns: dict[str, str] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)
    successes: dict[str, int] = field(default_factory=dict)
    avg_latency_ms: dict[str, float] = field(default_factory=dict)


class HFPoolRuntimeStateStore(Protocol):
    def load(self) -> HFPoolRuntimeState:
        ...

    def save(self, state: HFPoolRuntimeState) -> None:
        ...

    def append_usage(self, event: HFPoolUsageEvent) -> None:
        ...


@dataclass(frozen=True)
class SQLiteHFPoolRuntimeStateStore:
    path: str | Path

    def load(self) -> HFPoolRuntimeState:
        self._ensure_schema()
        state = HFPoolRuntimeState()
        with self._connect() as con:
            rows = con.execute("select kind, target, value from hf_pool_state").fetchall()
        for kind, target, value in rows:
            target_name = str(target or "")
            if not target_name:
                continue
            if kind == "cooldown":
                state.cooldowns[target_name] = str(value or "")
            elif kind == "failure":
                state.failures[target_name] = _int_value(value)
            elif kind == "success":
                state.successes[target_name] = _int_value(value)
            elif kind == "avg_latency_ms":
                state.avg_latency_ms[target_name] = _float_value(value)
        return state

    def save(self, state: HFPoolRuntimeState) -> None:
        self._ensure_schema()
        rows: list[tuple[str, str, str]] = []
        rows.extend(("cooldown", target, value) for target, value in sorted(state.cooldowns.items()) if target and value)
        rows.extend(("failure", target, str(count)) for target, count in sorted(state.failures.items()) if target and count)
        rows.extend(("success", target, str(count)) for target, count in sorted(state.successes.items()) if target and count)
        rows.extend(("avg_latency_ms", target, str(value)) for target, value in sorted(state.avg_latency_ms.items()) if target and value)
        with self._connect() as con:
            con.execute("delete from hf_pool_state")
            con.executemany(
                "insert into hf_pool_state(kind, target, value) values (?, ?, ?)",
                rows,
            )

    def append_usage(self, event: HFPoolUsageEvent) -> None:
        self._ensure_schema()
        with self._connect() as con:
            con.execute(
                """
                insert into hf_pool_usage(created_at, pool, target, model, status, latency_ms, usage_json)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    event.pool,
                    event.target,
                    event.model,
                    event.status,
                    event.latency_ms,
                    json.dumps(_json_safe(event.usage), ensure_ascii=False, sort_keys=True),
                ),
            )

    def read_usage(self, *, limit: int = 100) -> tuple[HFPoolUsageEvent, ...]:
        self._ensure_schema()
        max_rows = max(1, min(10000, int(limit)))
        with self._connect() as con:
            rows = con.execute(
                """
                select pool, target, model, status, latency_ms, usage_json
                from hf_pool_usage
                order by id desc
                limit ?
                """,
                (max_rows,),
            ).fetchall()
        events: list[HFPoolUsageEvent] = []
        for pool, target, model, status, latency_ms, usage_json in rows:
            try:
                usage = json.loads(str(usage_json or "{}"))
            except json.JSONDecodeError:
                usage = {}
            events.append(
                HFPoolUsageEvent(
                    pool=str(pool or ""),
                    target=str(target or ""),
                    model=str(model or ""),
                    status=str(status or ""),
                    latency_ms=None if latency_ms is None else _int_value(latency_ms),
                    usage=usage if isinstance(usage, dict) else {},
                )
            )
        return tuple(events)

    def _connect(self) -> sqlite3.Connection:
        db_path = Path(self.path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                create table if not exists hf_pool_state (
                    kind text not null,
                    target text not null,
                    value text not null,
                    primary key (kind, target)
                )
                """
            )
            con.execute(
                """
                create table if not exists hf_pool_usage (
                    id integer primary key autoincrement,
                    created_at text not null,
                    pool text not null,
                    target text not null,
                    model text not null,
                    status text not null,
                    latency_ms integer,
                    usage_json text not null
                )
                """
            )


def _int_value(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float_value(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _json_safe(value: Any) -> Any:
    value = _redact_json_secrets(value)
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return {}
    return value


def _redact_json_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact_json_secrets(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_json_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_json_secrets(item) for item in value]
    if isinstance(value, str):
        return redact_hf_secrets(value)
    return value
