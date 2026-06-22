from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Protocol

from TeeBotus.decisions.source_quality import SourceQualityDecision


SourceRoute = Literal["accepted", "quarantine", "rejected"]
NLIStance = Literal["entailment", "neutral", "contradiction"]

DEFAULT_MAX_SOURCE_BYTES = 100 * 1024 * 1024
ALLOWED_SOURCE_SUFFIXES = frozenset({".pdf", ".epub", ".docx", ".txt", ".md", ".markdown"})
EXECUTABLE_SUFFIXES = frozenset({".exe", ".dll", ".so", ".sh", ".bat", ".cmd", ".js", ".jar", ".py"})


class NLIVerifier(Protocol):
    model_name: str

    def verify(self, *, claim: str, evidence: str) -> "NLIResult":
        ...


@dataclass(frozen=True)
class NLIResult:
    stance: NLIStance
    confidence: float
    model_name: str = ""
    reason: str = ""


@dataclass(frozen=True)
class FakeNLIVerifier:
    stance: NLIStance = "entailment"
    confidence: float = 0.9
    model_name: str = "fake-nli-verifier"

    def verify(self, *, claim: str, evidence: str) -> NLIResult:
        if not str(claim or "").strip() or not str(evidence or "").strip():
            return NLIResult("neutral", 0.0, self.model_name, "missing claim or evidence")
        return NLIResult(self.stance, max(0.0, min(1.0, float(self.confidence))), self.model_name, "fake verifier")


@dataclass(frozen=True)
class SourceQualityInput:
    identifier: str
    size_bytes: int = 0
    suffix: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    claims: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        *,
        metadata: Mapping[str, Any] | None = None,
        claims: Iterable[str] = (),
        evidence: Iterable[str] = (),
    ) -> "SourceQualityInput":
        source_path = Path(path)
        try:
            size = source_path.stat().st_size
        except OSError:
            size = 0
        return cls(
            identifier=str(source_path),
            size_bytes=size,
            suffix=source_path.suffix.strip(),
            metadata=dict(metadata or {}),
            claims=tuple(str(item) for item in claims),
            evidence=tuple(str(item) for item in evidence),
        )


@dataclass(frozen=True)
class SourceQualityReport:
    source: SourceQualityInput
    decision: SourceQualityDecision
    route: SourceRoute
    issues: tuple[str, ...] = ()
    nli_results: tuple[NLIResult, ...] = ()

    @property
    def citation_quality(self) -> str:
        if self.decision.status in {"trusted", "usable"}:
            return self.decision.status
        return "unreviewed" if self.decision.status == "needs_review" else self.decision.status


@dataclass(frozen=True)
class SourceQualityPipeline:
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES
    allowed_suffixes: frozenset[str] = ALLOWED_SOURCE_SUFFIXES
    nli_verifier: NLIVerifier | None = None

    def evaluate(self, source: SourceQualityInput) -> SourceQualityReport:
        issues = list(_deterministic_source_issues(source, max_source_bytes=self.max_source_bytes, allowed_suffixes=self.allowed_suffixes))
        if any(issue.startswith("reject:") for issue in issues):
            decision = SourceQualityDecision(status="reject", reason="; ".join(issues), requires_human_review=True, confidence=0.95)
            return SourceQualityReport(source=source, decision=decision, route="rejected", issues=tuple(issues))

        nli_results = tuple(self._run_nli(source))
        contradictions = [result for result in nli_results if result.stance == "contradiction" and result.confidence >= 0.75]
        entailments = [result for result in nli_results if result.stance == "entailment" and result.confidence >= 0.75]
        if contradictions:
            decision = SourceQualityDecision(
                status="weak",
                reason="NLI contradiction against supplied evidence",
                requires_human_review=True,
                confidence=max(result.confidence for result in contradictions),
            )
            return SourceQualityReport(source=source, decision=decision, route="quarantine", issues=tuple(issues), nli_results=nli_results)
        if issues:
            decision = SourceQualityDecision(status="needs_review", reason="; ".join(issues), requires_human_review=True, confidence=0.65)
            return SourceQualityReport(source=source, decision=decision, route="quarantine", issues=tuple(issues), nli_results=nli_results)
        if nli_results and entailments:
            decision = SourceQualityDecision(
                status="trusted",
                reason="metadata checks passed and NLI evidence supports extracted claims",
                requires_human_review=False,
                confidence=max(result.confidence for result in entailments),
            )
            return SourceQualityReport(source=source, decision=decision, route="accepted", nli_results=nli_results)
        decision = SourceQualityDecision(
            status="usable",
            reason="deterministic source checks passed; no NLI claim conflict was found",
            requires_human_review=False,
            confidence=0.72,
        )
        return SourceQualityReport(source=source, decision=decision, route="accepted", nli_results=nli_results)

    def _run_nli(self, source: SourceQualityInput) -> list[NLIResult]:
        if self.nli_verifier is None:
            return []
        pairs = zip(source.claims, source.evidence, strict=False)
        return [self.nli_verifier.verify(claim=claim, evidence=evidence) for claim, evidence in pairs]


def _deterministic_source_issues(
    source: SourceQualityInput,
    *,
    max_source_bytes: int,
    allowed_suffixes: frozenset[str],
) -> tuple[str, ...]:
    issues: list[str] = []
    suffix = str(source.suffix or Path(source.identifier).suffix or "").strip().casefold()
    if suffix in EXECUTABLE_SUFFIXES:
        issues.append(f"reject: executable suffix {suffix}")
    elif not suffix:
        issues.append("needs_review: missing file suffix")
    elif suffix and suffix not in allowed_suffixes:
        issues.append(f"needs_review: unsupported suffix {suffix}")
    if source.size_bytes > max_source_bytes:
        issues.append(f"reject: source too large ({source.size_bytes} bytes)")
    metadata = dict(source.metadata or {})
    if not str(metadata.get("title") or metadata.get("source_id") or source.identifier or "").strip():
        issues.append("needs_review: missing source identifier")
    license_value = str(metadata.get("license") or "").strip().casefold()
    if license_value in {"forbidden", "rejected", "unknown-bad"}:
        issues.append(f"reject: license {license_value}")
    elif not license_value:
        issues.append("needs_review: missing license")
    return tuple(issues)
