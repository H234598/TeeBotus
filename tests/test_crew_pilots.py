from __future__ import annotations

from TeeBotus.runtime.crew_pilots import CREW_PILOTS, crew_pilot_status_lines


def test_crew_pilot_registry_defines_plan3_specialized_expeditions() -> None:
    pilots = {pilot.name: pilot for pilot in CREW_PILOTS}

    assert {"bibliothekar_expedition", "source_quality_expedition", "anki_expedition"}.issubset(pilots)
    assert "safety_reviewer" in pilots["bibliothekar_expedition"].roles
    assert "nli_verifier" in pilots["source_quality_expedition"].roles
    assert all(pilot.enabled_by_default is False for pilot in CREW_PILOTS)


def test_crew_pilot_status_lines_are_planned_and_dependency_visible() -> None:
    lines = crew_pilot_status_lines(dependency_available=False)

    assert len(lines) == len(CREW_PILOTS)
    assert all("status=planned" in line for line in lines)
    assert all("dependency=missing" in line for line in lines)
    assert any(line.startswith("crew_pilot=bibliothekar_expedition") for line in lines)
