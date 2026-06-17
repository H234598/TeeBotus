from __future__ import annotations

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
