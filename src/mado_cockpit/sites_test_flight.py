"""MCC-M2.9: fail-closed, review-only human test mission manifest.

Mission text is a curated draft, not LLM-generated or proof of a live test build.
Feedback remains client-side until the tester explicitly exports or opens a draft.
"""
from __future__ import annotations

from typing import Any

from .sites_portal import SLUG, SiteCatalogError, _reject_sensitive_keys, _text

SCHEMA = "mado.human-test-flight.v1"
TARGETS = {"web", "web_or_windows"}
EXPECTED_FIELDS = {
    "id", "project_id", "title", "goal", "target",
    "estimated_minutes", "review_state", "steps",
}


def validate_test_flights(data: Any, catalog: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != {"schema", "release_state", "missions"}:
        raise SiteCatalogError("Unexpected human test flight manifest fields")
    if data["schema"] != SCHEMA or data["release_state"] != "review_only":
        raise SiteCatalogError("Human test flights must remain review_only")
    _reject_sensitive_keys(data)
    missions = data["missions"]
    if not isinstance(missions, list) or not 1 <= len(missions) <= 20:
        raise SiteCatalogError("Expected 1..20 human test missions")
    published_ids = {p["id"] for p in catalog["projects"]}
    seen_ids: set[str] = set()
    seen_projects: set[str] = set()
    for mission in missions:
        if not isinstance(mission, dict) or set(mission) != EXPECTED_FIELDS:
            raise SiteCatalogError("Unexpected human test mission fields")
        identifier = _text(mission["id"], "mission.id", 70)
        project = _text(mission["project_id"], "mission.project_id", 70)
        if not SLUG.fullmatch(identifier) or identifier in seen_ids:
            raise SiteCatalogError("Duplicate or invalid mission ID")
        if project not in published_ids or project in seen_projects:
            raise SiteCatalogError("Unreviewed or duplicate mission project")
        seen_ids.add(identifier)
        seen_projects.add(project)
        _text(mission["title"], "mission.title", 100)
        _text(mission["goal"], "mission.goal", 240)
        if mission["target"] not in TARGETS:
            raise SiteCatalogError("Unreviewed test target")
        if type(mission["estimated_minutes"]) is not int or mission["estimated_minutes"] != 3:
            raise SiteCatalogError("Human test flight must be a 3-minute mission")
        if mission["review_state"] != "draft":
            raise SiteCatalogError("Curated missions must remain draft until separately reviewed")
        steps = mission["steps"]
        if not isinstance(steps, list) or len(steps) != 3:
            raise SiteCatalogError("Exactly 3 human test steps required")
        for step in steps:
            _text(step, "mission.step", 160)
    return data
