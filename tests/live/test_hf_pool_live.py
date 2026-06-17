from __future__ import annotations

import os

import pytest

from TeeBotus.llm.hf_pool.config import DEFAULT_HF_POOL_CONFIG_PATH, load_hf_pool_config
from TeeBotus.llm.hf_pool.health import check_hf_pool, format_hf_pool_status_lines
from TeeBotus.llm.hf_pool.state import SQLiteHFPoolRuntimeStateStore


pytestmark = pytest.mark.live


def test_live_hf_pool_target_records_usage_and_latency(tmp_path):
    if os.environ.get("TEEBOTUS_LIVE_HF") != "1":
        pytest.skip("set TEEBOTUS_LIVE_HF=1 to run live Hugging Face checks")

    config = load_hf_pool_config(DEFAULT_HF_POOL_CONFIG_PATH)
    if config.error:
        pytest.skip(f"hf_pool config unavailable: {config.error}")
    pool = config.pool("default")
    if pool is None or not pool.enabled:
        pytest.skip("hf_pool default pool is not enabled")
    enabled_targets = [target for target in pool.targets if target.enabled]
    if not enabled_targets:
        pytest.skip("hf_pool default pool has no enabled targets")
    missing_tokens = sorted(
        {
            target.api_key_env
            for target in enabled_targets
            if target.api_key_env and not os.environ.get(target.api_key_env, "").strip()
        }
    )
    if missing_tokens:
        pytest.skip(f"missing HF token environment: {', '.join(missing_tokens)}")

    state_store = SQLiteHFPoolRuntimeStateStore(tmp_path / "hf_pool_live_state.sqlite3")
    health = check_hf_pool(live=True, state_store=state_store)
    lines = "\n".join(format_hf_pool_status_lines(health))
    healthy = [target for target in health.targets if target.status == "healthy"]
    usage_events = state_store.read_usage(limit=20)

    assert healthy, lines
    assert any(target.latency_ms is not None and target.latency_ms >= 0 for target in healthy)
    assert any(event.status == "ok" and event.latency_ms is not None and event.latency_ms >= 0 for event in usage_events)
    assert "hf_" not in lines
