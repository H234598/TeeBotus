from __future__ import annotations

import importlib.util
from dataclasses import dataclass


@dataclass(frozen=True)
class CrewPilot:
    name: str
    roles: tuple[str, ...]
    workflow: tuple[str, ...]
    enabled_by_default: bool = False


CREW_PILOTS: tuple[CrewPilot, ...] = (
    CrewPilot(
        name="bibliothekar_expedition",
        roles=("researcher", "retriever", "psychology_explainer", "skeptic", "safety_reviewer", "formatter"),
        workflow=("classify", "retrieve", "explain", "criticize", "safety_review", "format"),
    ),
    CrewPilot(
        name="source_quality_expedition",
        roles=("harvester", "metadata_inspector", "claim_extractor", "nli_verifier", "summary_writer"),
        workflow=("discover", "metadata", "claims", "verify", "summarize"),
    ),
    CrewPilot(
        name="anki_expedition",
        roles=("source_reader", "card_writer", "cloze_checker", "scientific_hygiene_reviewer"),
        workflow=("read", "draft_cards", "check_cloze", "hygiene_review"),
    ),
)


def crewai_available() -> bool:
    return importlib.util.find_spec("crewai") is not None


def crew_pilot_status_lines(*, dependency_available: bool | None = None) -> tuple[str, ...]:
    available = crewai_available() if dependency_available is None else bool(dependency_available)
    dependency = "installed" if available else "missing"
    lines = []
    for pilot in CREW_PILOTS:
        status = "available" if available and pilot.enabled_by_default else "planned"
        lines.append(
            "crew_pilot={name} status={status} dependency={dependency} enabled_by_default={enabled} roles={roles} workflow={workflow}".format(
                name=pilot.name,
                status=status,
                dependency=dependency,
                enabled=str(pilot.enabled_by_default).lower(),
                roles=",".join(pilot.roles),
                workflow=",".join(pilot.workflow),
            )
        )
    return tuple(lines)


__all__ = ["CREW_PILOTS", "CrewPilot", "crew_pilot_status_lines", "crewai_available"]
