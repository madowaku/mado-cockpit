from __future__ import annotations

import copy
import hashlib
import json

import pytest

from mado_cockpit.sites_portal import SITE_ROOT, SiteCatalogError, build_site
from mado_cockpit.sites_test_flight import validate_test_flights


@pytest.fixture
def data():
    flights = json.loads((SITE_ROOT / "test-flights.json").read_text(encoding="utf-8"))
    catalog = json.loads((SITE_ROOT / "catalog.json").read_text(encoding="utf-8"))
    return flights, catalog


def test_review_only_missions_accepted(data):
    flights, catalog = data
    assert validate_test_flights(flights, catalog) is flights
    assert {m["project_id"] for m in flights["missions"]} == {
        "mado-game-service-factory", "gear-relay", "mado-cockpit"
    }
    assert all(m["review_state"] == "draft" and len(m["steps"]) == 3 for m in flights["missions"])


@pytest.mark.parametrize("field,value", [
    ("id", "wrong/slug"),
    ("project_id", "private-repo"),
    ("estimated_minutes", True),
    ("target", "auto_install"),
    ("review_state", "published_verified"),
    ("steps", ["one", "two"]),
    ("preview_url", "https://example.com/unreviewed"),
    ("access_token", "secret-placeholder"),
])
def test_mission_contract_fails_closed(data, field, value):
    flights, catalog = copy.deepcopy(data)
    flights["missions"][0][field] = value
    with pytest.raises(SiteCatalogError):
        validate_test_flights(flights, catalog)


def test_duplicate_project_and_mission_rejected(data):
    flights, catalog = copy.deepcopy(data)
    flights["missions"][1]["id"] = flights["missions"][0]["id"]
    with pytest.raises(SiteCatalogError, match="Duplicate"):
        validate_test_flights(flights, catalog)
    flights, catalog = copy.deepcopy(data)
    flights["missions"][1]["project_id"] = flights["missions"][0]["project_id"]
    with pytest.raises(SiteCatalogError, match="duplicate mission project"):
        validate_test_flights(flights, catalog)


def test_missing_manifest_fails_before_writing(tmp_path, monkeypatch):
    from mado_cockpit import sites_portal
    monkeypatch.setattr(sites_portal, "FLIGHTS_PATH", tmp_path / "missing.json")
    with pytest.raises(FileNotFoundError):
        build_site(output=tmp_path / "dist")
    assert not (tmp_path / "dist").exists()


def test_receipt_includes_flight_assets_and_non_deployment_proof(tmp_path):
    out = tmp_path / "candidate"
    receipt = build_site(output=out)
    assert receipt["human_test_flight"] == {
        "mission_count": 3,
        "review_state": "draft",
        "feedback_upload_enabled": False,
        "live_play_verified": False,
    }
    assert receipt["deployment_verified"] is False
    for name in ("test-flight.html", "test-flight.css", "test-flight.js", "test-flights.json"):
        data = (out / name).read_bytes()
        assert receipt["sha256"][name] == hashlib.sha256(data).hexdigest()
