from __future__ import annotations

import os

import pytest

from TeeBotus.decisions import BibliothekarQueryDecision, build_router_pydantic_ai_model_runner
from TeeBotus.llm.hf_pool.config import DEFAULT_HF_POOL_CONFIG_PATH, load_hf_pool_config
from TeeBotus.llm.hf_pool.errors import HFPoolUnavailable
from TeeBotus.llm.hf_pool.scheduler import select_target


pytestmark = pytest.mark.live


def test_live_structured_decision_runs_through_hf_pool() -> None:
    if os.environ.get("TEEBOTUS_LIVE_HF") != "1":
        pytest.skip("set TEEBOTUS_LIVE_HF=1 to run live Hugging Face structured-decision checks")

    config = load_hf_pool_config(DEFAULT_HF_POOL_CONFIG_PATH)
    if config.error:
        pytest.skip(f"hf_pool config unavailable: {config.error}")
    try:
        scheduled = select_target(config, pool_name="default", purpose="structured_decision", env=os.environ)
    except HFPoolUnavailable as exc:
        pytest.skip(f"structured_decision hf_pool target unavailable: {exc}")

    runner = build_router_pydantic_ai_model_runner(
        "structured_decision",
        system_prompt="Antworte nur als strukturierte Entscheidung im angeforderten Schema.",
        env=os.environ,
    )
    decision = runner(
        "Soll der Bibliothekar fuer die Frage 'Was sagt meine Bibliothek ueber Schlafhygiene?' durchsucht werden?",
        BibliothekarQueryDecision,
    )

    assert isinstance(decision, BibliothekarQueryDecision)
    assert decision.should_search is True
    assert decision.confidence >= 0.5
    assert decision.query.strip()
    assert getattr(runner, "llm_provider") == "hf_pool"
    assert getattr(runner, "hf_pool_target") == scheduled.target.name
    assert getattr(runner, "hf_pool_request_model") == scheduled.target.request_model
