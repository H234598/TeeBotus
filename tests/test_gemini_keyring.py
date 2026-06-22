from __future__ import annotations

from datetime import datetime, timezone
import json

from TeeBotus.llm.free_tier import (
    GeminiFreeTierGuard,
    GeminiFreeTierLimits,
    provider_is_paid_google_gemini,
    reset_gemini_free_tier_budget_state,
    resolve_gemini_free_tier_limits,
    route_uses_google_gemini,
)
from TeeBotus.llm.gemini_limits_refresh import (
    DEFAULT_GEMINI_FREE_TIER_LIMIT_SOURCE_URL,
    cached_gemini_free_tier_limit_values,
    gemini_free_tier_limit_status_line,
    parse_gemini_free_tier_limits_payload,
    refresh_gemini_free_tier_limits_if_due,
)
from TeeBotus.llm.keyring import RotatingAPIKeyRing, interleave_key_buckets, resolve_gemini_api_key_ring


def test_interleave_key_buckets_uses_account_column_order() -> None:
    assert interleave_key_buckets(
        (
            ("a1", "a2", "a3"),
            ("b1", "b2", "b3"),
            ("c1", "c2", "c3"),
        )
    ) == ("a1", "b1", "c1", "a2", "b2", "c2", "a3", "b3", "c3")


def test_interleave_key_buckets_skips_shorter_accounts_and_dedupes() -> None:
    assert interleave_key_buckets((("a1", "a2"), ("b1",), ("a1", "c2"))) == ("a1", "b1", "a2", "c2")


def test_resolve_gemini_key_ring_from_three_account_buckets() -> None:
    env = {
        "GEMINI_API_KEYS_ACCOUNT_1": "a1,a2,a3",
        "GEMINI_API_KEYS_ACCOUNT_2": "b1,b2,b3",
        "GEMINI_API_KEYS_ACCOUNT_3": "c1,c2,c3",
    }

    assert resolve_gemini_api_key_ring(env) == ("a1", "b1", "c1", "a2", "b2", "c2", "a3", "b3", "c3")


def test_resolve_gemini_key_ring_accepts_instance_scoped_buckets() -> None:
    env = {
        "TEEBOTUS_GEMINI_API_KEYS_DEMO_ACCOUNT_1": "a1,a2",
        "TEEBOTUS_GEMINI_API_KEYS_DEMO_ACCOUNT_2": "b1,b2",
        "GEMINI_API_KEYS_ACCOUNT_1": "global-a1",
    }

    assert resolve_gemini_api_key_ring(env, instance_name="Demo") == ("a1", "b1", "a2", "b2")


def test_resolve_gemini_key_ring_prefers_role_scope_over_instance_and_global_ring() -> None:
    env = {
        "TEEBOTUS_GEMINI_API_KEY_RING_DEMO_PROACTIVE_PLAN": "plan-a,plan-b",
        "TEEBOTUS_GEMINI_API_KEY_RING_DEMO": "instance-a",
        "GEMINI_API_KEYS": "global-a",
    }

    assert resolve_gemini_api_key_ring(env, instance_name="Demo", scope="proactive_plan") == ("plan-a", "plan-b")


def test_resolve_gemini_key_ring_falls_back_from_role_scope_to_instance_ring() -> None:
    env = {
        "TEEBOTUS_GEMINI_API_KEY_RING_DEMO": "instance-a,instance-b",
        "GEMINI_API_KEYS": "global-a",
    }

    assert resolve_gemini_api_key_ring(env, instance_name="Demo", scope="proactive_worker") == ("instance-a", "instance-b")


def test_resolve_gemini_key_ring_accepts_role_scoped_account_buckets() -> None:
    env = {
        "TEEBOTUS_GEMINI_API_KEYS_DEMO_PROACTIVE_DECISION_ACCOUNT_1": "a1,a2",
        "TEEBOTUS_GEMINI_API_KEYS_DEMO_PROACTIVE_DECISION_ACCOUNT_2": "b1,b2",
        "TEEBOTUS_GEMINI_API_KEYS_DEMO_ACCOUNT_1": "instance-a1",
    }

    assert resolve_gemini_api_key_ring(env, instance_name="Demo", scope="proactive_decision") == ("a1", "b1", "a2", "b2")


def test_resolve_gemini_key_ring_prefers_google_api_key_for_single_key_fallback() -> None:
    env = {"GEMINI_API_KEY": "gemini-single", "GOOGLE_API_KEY": "google-single"}

    assert resolve_gemini_api_key_ring(env) == ("google-single",)


def test_rotating_key_ring_advances_only_when_limited() -> None:
    ring = RotatingAPIKeyRing(("k1", "k2", "k3"), name="test-advances")

    assert ring.ordered_keys()[0] == "k1"
    ring.mark_success("k1")
    assert ring.ordered_keys()[0] == "k1"
    ring.mark_limited("k1")
    assert ring.ordered_keys()[0] == "k2"
    ring.mark_limited("k2")
    assert ring.ordered_keys()[0] == "k3"


def test_resolve_gemini_free_tier_limits_uses_instance_override() -> None:
    env = {
        "TEEBOTUS_GEMINI_FREE_TIER_DEMO_RPM": "7",
        "TEEBOTUS_GEMINI_FREE_TIER_TPM": "250000",
        "TEEBOTUS_GEMINI_FREE_TIER_DEMO_RPD": "33",
        "TEEBOTUS_GEMINI_FREE_TIER_DEMO_RESERVE_TOKENS": "4096",
    }

    limits = resolve_gemini_free_tier_limits(
        env,
        instance_name="Demo",
        provider="litellm",
        model="gemini/gemini-2.5-flash",
    )

    assert limits.requests_per_minute == 7
    assert limits.input_tokens_per_minute == 250_000
    assert limits.requests_per_day == 33
    assert limits.reserve_input_tokens == 4096
    assert limits.status_summary() == "on(rpm=7,tpm=250000,rpd=33,reserve=4096)"


def test_resolve_gemini_free_tier_limits_disables_paid_provider_even_with_env_limits() -> None:
    env = {
        "TEEBOTUS_GEMINI_FREE_TIER_RPM": "1",
        "TEEBOTUS_GEMINI_FREE_TIER_TPM": "2",
        "TEEBOTUS_GEMINI_FREE_TIER_RPD": "3",
    }

    limits = resolve_gemini_free_tier_limits(
        env,
        provider="litellm-gemini-paid-statefull",
        model="gemini/gemini-3.5-flash",
    )

    assert limits.status_summary() == "off"


def test_gemini_paid_aliases_disable_free_tier_guard() -> None:
    env = {
        "TEEBOTUS_GEMINI_FREE_TIER_RPM": "1",
        "TEEBOTUS_GEMINI_FREE_TIER_TPM": "2",
        "TEEBOTUS_GEMINI_FREE_TIER_RPD": "3",
    }

    limits = resolve_gemini_free_tier_limits(
        env,
        provider="gemini_paid_interactions",
        model="gemini/gemini-3.5-flash",
    )

    assert provider_is_paid_google_gemini("gemini_paid_interactions")
    assert route_uses_google_gemini(provider="gemini_paid_interactions", model="custom")
    assert limits.status_summary() == "off"


def test_parse_gemini_free_tier_limits_from_json_payload() -> None:
    payload = json.dumps(
        {
            "limits": [
                {
                    "model": "gemini/gemini-2.5-flash",
                    "tier": "free",
                    "rpm": 10,
                    "input_tokens_per_minute": "250,000",
                    "requests_per_day": 250,
                },
                {"model": "gemini/gemini-2.5-pro", "tier": "tier_1", "rpm": 1000, "tpm": 1_000_000, "rpd": 10_000},
            ]
        }
    )

    parsed = parse_gemini_free_tier_limits_payload(payload)

    assert parsed == {"gemini/gemini-2.5-flash": {"rpm": 10, "tpm": 250_000, "rpd": 250}}


def test_parse_gemini_free_tier_limits_from_html_table() -> None:
    payload = """
    <table>
      <tr><th>Tier</th><th>Model</th><th>RPM</th><th>TPM</th><th>RPD</th></tr>
      <tr><td>Free</td><td>Gemini 2.5 Flash</td><td>10</td><td>250,000</td><td>250</td></tr>
    </table>
    """

    parsed = parse_gemini_free_tier_limits_payload(payload)

    assert parsed == {"Gemini 2.5 Flash": {"rpm": 10, "tpm": 250_000, "rpd": 250}}


def test_refresh_gemini_free_tier_limits_caches_parseable_source(tmp_path) -> None:
    cache_path = tmp_path / "gemini-limits.json"
    env = {"TEEBOTUS_GEMINI_FREE_TIER_CACHE": str(cache_path), "TEEBOTUS_GEMINI_FREE_TIER_LIMITS_URL": "https://limits.example/free.json"}

    result = refresh_gemini_free_tier_limits_if_due(
        env,
        force=True,
        now=lambda: datetime(2026, 6, 17, tzinfo=timezone.utc),
        fetcher=lambda _url, _timeout: '{"models":{"gemini-2.5-flash":{"rpm":9,"tpm":240000,"rpd":120}}}',
    )

    assert result.status == "ok"
    assert result.models == 1
    assert cached_gemini_free_tier_limit_values(env, model="gemini/gemini-2.5-flash") == {
        "rpm": 9,
        "tpm": 240_000,
        "rpd": 120,
    }


def test_refresh_gemini_free_tier_limits_preserves_cache_when_source_has_no_table(tmp_path) -> None:
    cache_path = tmp_path / "gemini-limits.json"
    cache_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "fetched_at": "2026-06-16T00:00:00Z",
                "last_refresh_attempt_at": "2026-06-16T00:00:00Z",
                "last_refresh_status": "ok",
                "models": {"gemini-2.5-flash": {"rpm": 9, "tpm": 240000, "rpd": 120}},
            }
        ),
        encoding="utf-8",
    )
    env = {"TEEBOTUS_GEMINI_FREE_TIER_CACHE": str(cache_path), "TEEBOTUS_GEMINI_FREE_TIER_LIMITS_URL": "https://limits.example/docs"}

    result = refresh_gemini_free_tier_limits_if_due(
        env,
        force=True,
        now=lambda: datetime(2026, 6, 17, tzinfo=timezone.utc),
        fetcher=lambda _url, _timeout: "<html><td>Gemini 2.5 Flash</td><td>3,000,000</td></html>",
    )

    assert result.status == "no_limits_found"
    assert cached_gemini_free_tier_limit_values(env, model="gemini/gemini-2.5-flash") == {
        "rpm": 9,
        "tpm": 240_000,
        "rpd": 120,
    }
    status = gemini_free_tier_limit_status_line(env, now=lambda: datetime(2026, 6, 17, tzinfo=timezone.utc))
    assert "gemini_free_tier_limits status=no_limits_found" in status
    assert "models=1" in status


def test_refresh_gemini_free_tier_limits_uses_conservative_defaults_when_official_page_has_no_public_table(tmp_path) -> None:
    cache_path = tmp_path / "gemini-limits.json"
    env = {"TEEBOTUS_GEMINI_FREE_TIER_CACHE": str(cache_path)}
    payload = """
    <p>Rate limits are usually measured across three dimensions: RPM, TPM, and RPD.</p>
    <a>View your active rate limits in AI Studio</a>
    <p>Rate limits depend on a variety of factors and can be viewed in Google AI Studio.</p>
    <p>Specified rate limits are not guaranteed and actual capacity may vary.</p>
    """

    result = refresh_gemini_free_tier_limits_if_due(
        env,
        force=True,
        now=lambda: datetime(2026, 6, 17, tzinfo=timezone.utc),
        fetcher=lambda _url, _timeout: payload,
    )

    assert result.status == "fallback_defaults"
    assert result.models == 2
    assert cached_gemini_free_tier_limit_values(env, model="gemini/gemini-2.5-flash") == {
        "rpm": 5,
        "tpm": 250_000,
        "rpd": 20,
    }
    assert cached_gemini_free_tier_limit_values(env, model="gemini/gemini-3.5-flash") == {
        "rpm": 5,
        "tpm": 250_000,
        "rpd": 20,
    }
    status = gemini_free_tier_limit_status_line(env, now=lambda: datetime(2026, 6, 17, tzinfo=timezone.utc))
    assert "gemini_free_tier_limits status=fallback_defaults" in status
    assert "models=2" in status


def test_refresh_gemini_free_tier_limits_rechecks_old_empty_default_no_limits_cache_before_interval(tmp_path) -> None:
    cache_path = tmp_path / "gemini-limits.json"
    cache_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "last_refresh_attempt_at": "2026-06-17T00:00:00Z",
                "last_refresh_status": "no_limits_found",
                "last_refresh_error": "source contained no parseable free-tier RPM/TPM/RPD table",
                "source_url": DEFAULT_GEMINI_FREE_TIER_LIMIT_SOURCE_URL,
            }
        ),
        encoding="utf-8",
    )
    env = {
        "TEEBOTUS_GEMINI_FREE_TIER_CACHE": str(cache_path),
        "TEEBOTUS_GEMINI_FREE_TIER_REFRESH_INTERVAL_SECONDS": "86400",
    }
    calls: list[str] = []

    result = refresh_gemini_free_tier_limits_if_due(
        env,
        now=lambda: datetime(2026, 6, 17, 1, tzinfo=timezone.utc),
        fetcher=lambda url, _timeout: calls.append(url)
        or "<a>View your active rate limits in AI Studio</a><p>Specified rate limits are not guaranteed.</p>",
    )

    assert result.status == "fallback_defaults"
    assert calls == [DEFAULT_GEMINI_FREE_TIER_LIMIT_SOURCE_URL]
    assert cached_gemini_free_tier_limit_values(env, model="gemini/gemini-2.5-flash")["rpm"] == 5


def test_refresh_gemini_free_tier_limits_keeps_default_fallback_status_on_next_official_refresh(tmp_path) -> None:
    cache_path = tmp_path / "gemini-limits.json"
    cache_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "fetched_at": "2026-06-16T00:00:00Z",
                "last_refresh_attempt_at": "2026-06-16T00:00:00Z",
                "last_refresh_status": "fallback_defaults",
                "limits_source": "conservative_defaults",
                "source_url": DEFAULT_GEMINI_FREE_TIER_LIMIT_SOURCE_URL,
                "models": {"gemini-2.5-flash": {"rpm": 5, "tpm": 250000, "rpd": 20}},
            }
        ),
        encoding="utf-8",
    )
    env = {"TEEBOTUS_GEMINI_FREE_TIER_CACHE": str(cache_path)}
    payload = """
    <p>Rate limits are usually measured across RPM, TPM, and RPD.</p>
    <a>View your active rate limits in AI Studio</a>
    <p>Rate limits depend on project capacity.</p>
    """

    result = refresh_gemini_free_tier_limits_if_due(
        env,
        force=True,
        now=lambda: datetime(2026, 6, 17, tzinfo=timezone.utc),
        fetcher=lambda _url, _timeout: payload,
    )

    assert result.status == "fallback_defaults"
    assert cached_gemini_free_tier_limit_values(env, model="gemini/gemini-2.5-flash") == {
        "rpm": 5,
        "tpm": 250_000,
        "rpd": 20,
    }
    status = gemini_free_tier_limit_status_line(env, now=lambda: datetime(2026, 6, 17, 0, 1, tzinfo=timezone.utc))
    assert "gemini_free_tier_limits status=fallback_defaults" in status
    assert "models=2" in status


def test_resolve_gemini_free_tier_limits_uses_cached_defaults_and_keeps_env_override(tmp_path) -> None:
    cache_path = tmp_path / "gemini-limits.json"
    cache_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "fetched_at": "2026-06-17T00:00:00Z",
                "last_refresh_attempt_at": "2026-06-17T00:00:00Z",
                "last_refresh_status": "ok",
                "models": {"gemini-2.5-flash": {"rpm": 10, "tpm": 250000, "rpd": 250}},
            }
        ),
        encoding="utf-8",
    )
    env = {"TEEBOTUS_GEMINI_FREE_TIER_CACHE": str(cache_path), "TEEBOTUS_GEMINI_FREE_TIER_RPD": "200"}

    limits = resolve_gemini_free_tier_limits(env, provider="litellm", model="gemini/gemini-2.5-flash")

    assert limits.requests_per_minute == 10
    assert limits.input_tokens_per_minute == 250_000
    assert limits.requests_per_day == 200


def test_gemini_free_tier_guard_blocks_before_limit() -> None:
    reset_gemini_free_tier_budget_state()
    guard = GeminiFreeTierGuard(
        GeminiFreeTierLimits(
            requests_per_minute=10,
            input_tokens_per_minute=100,
            requests_per_day=10,
            reserve_input_tokens=10,
        )
    )

    first = guard.reserve(quota_owner="project-a", model="gemini/gemini-2.5-flash", estimated_input_tokens=85)
    second = guard.reserve(quota_owner="project-a", model="gemini/gemini-2.5-flash", estimated_input_tokens=6)
    other_project = guard.reserve(quota_owner="project-b", model="gemini/gemini-2.5-flash", estimated_input_tokens=6)

    assert first.allowed is True
    assert second.allowed is False
    assert "TPM free-tier budget would be exceeded" in second.reason
    assert other_project.allowed is True
