from __future__ import annotations

import json

from TeeBotus.bibliothekar.source_harvester import SourceHarvester
from TeeBotus.runtime.graphs import run_source_harvester_workflow
from TeeBotus.runtime.source_quality import FakeNLIVerifier, SourceQualityPipeline


def test_source_harvester_workflow_marks_accepted_sources_ready_for_ingest(tmp_path) -> None:
    source = tmp_path / "quelle.pdf"
    source.write_text("Therapie und Schlafhygiene.", encoding="utf-8")
    harvester = SourceHarvester(
        tmp_path / "library",
        quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.9)),
    )

    state = run_source_harvester_workflow(
        harvester,
        source,
        metadata={"title": "Quelle", "license": "private"},
        claims=("Schlafhygiene ist relevant.",),
        evidence=("Therapie und Schlafhygiene.",),
        prefer_langgraph=False,
    )

    assert state["status"] == "ready_for_ingest"
    assert state["route"] == "accepted"
    assert state["accepted_for_ingest"] is True
    assert state["decision_status"] == "trusted"
    assert state["stored_path"].endswith(".pdf")
    json.dumps(state)


def test_source_harvester_workflow_returns_serializable_failure_state(tmp_path) -> None:
    harvester = SourceHarvester(tmp_path / "library")

    state = run_source_harvester_workflow(harvester, tmp_path / "missing.pdf", prefer_langgraph=False)

    assert state["status"] == "failed"
    assert state["fallback_reason"] == "source_not_found"
    json.dumps(state)
