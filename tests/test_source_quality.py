from __future__ import annotations

from pydantic import ValidationError
import pytest

from TeeBotus.decisions.source_quality import SourceQualityDecision
from TeeBotus.runtime.source_quality import FakeNLIVerifier, SourceQualityInput, SourceQualityPipeline


def test_source_quality_decision_schema_validates_status_and_confidence() -> None:
    decision = SourceQualityDecision(status="trusted", reason="ok", requires_human_review=False, confidence=0.91)

    assert decision.status == "trusted"

    with pytest.raises(ValidationError):
        SourceQualityDecision(status="maybe", reason="bad", requires_human_review=True, confidence=0.5)


def test_source_quality_pipeline_accepts_supported_source_with_entailing_nli() -> None:
    pipeline = SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.92))
    source = SourceQualityInput(
        identifier="therapie.pdf",
        size_bytes=2048,
        suffix=".pdf",
        metadata={"title": "Therapiehandbuch", "license": "private"},
        claims=("Schlafhygiene kann bei Depression relevant sein.",),
        evidence=("Das Kapitel beschreibt Schlafhygiene als Baustein bei Depression.",),
    )

    report = pipeline.evaluate(source)

    assert report.route == "accepted"
    assert report.decision.status == "trusted"
    assert report.decision.requires_human_review is False
    assert report.citation_quality == "trusted"
    assert report.nli_results[0].model_name == "fake-nli-verifier"


def test_source_quality_pipeline_quarantines_nli_contradictions_before_ingest() -> None:
    pipeline = SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="contradiction", confidence=0.89))
    source = SourceQualityInput(
        identifier="quelle.epub",
        size_bytes=4096,
        suffix=".epub",
        metadata={"title": "Quelle", "license": "private"},
        claims=("Das Buch sagt, Schlaf sei unwichtig.",),
        evidence=("Die Quelle empfiehlt Schlafhygiene als wichtiges Element.",),
    )

    report = pipeline.evaluate(source)

    assert report.route == "quarantine"
    assert report.decision.status == "weak"
    assert report.decision.requires_human_review is True
    assert report.citation_quality == "weak"


def test_source_quality_pipeline_rejects_executable_or_too_large_sources() -> None:
    pipeline = SourceQualityPipeline(max_source_bytes=100)

    executable = pipeline.evaluate(
        SourceQualityInput(
            identifier="payload.sh",
            size_bytes=10,
            suffix=".sh",
            metadata={"title": "bad", "license": "private"},
        )
    )
    spaced_executable = pipeline.evaluate(
        SourceQualityInput(
            identifier="payload-spaced.sh ",
            size_bytes=10,
            suffix=".sh ",
            metadata={"title": "bad spaced", "license": "private"},
        )
    )
    huge = pipeline.evaluate(
        SourceQualityInput(
            identifier="huge.pdf",
            size_bytes=101,
            suffix=".pdf",
            metadata={"title": "big", "license": "private"},
        )
    )

    assert executable.route == "rejected"
    assert executable.decision.status == "reject"
    assert spaced_executable.route == "rejected"
    assert spaced_executable.decision.status == "reject"
    assert huge.route == "rejected"
    assert "too large" in huge.decision.reason


def test_source_quality_pipeline_quarantines_missing_license_without_llm_judge() -> None:
    pipeline = SourceQualityPipeline()

    report = pipeline.evaluate(SourceQualityInput(identifier="notes.txt", size_bytes=20, suffix=".txt", metadata={"title": "Notes"}))

    assert report.route == "quarantine"
    assert report.decision.status == "needs_review"
    assert report.nli_results == ()
    assert "missing license" in report.decision.reason


def test_source_quality_pipeline_quarantines_sources_without_convertible_suffix() -> None:
    pipeline = SourceQualityPipeline()

    report = pipeline.evaluate(SourceQualityInput(identifier="quelle", size_bytes=20, suffix="", metadata={"title": "Quelle", "license": "private"}))

    assert report.route == "quarantine"
    assert report.decision.status == "needs_review"
    assert "missing file suffix" in report.decision.reason
