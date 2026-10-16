from __future__ import annotations

import pytest

from mado_cockpit.sites_live_qa import (
    VIEWPORTS, LiveSitesError, decision_gate, evaluate_checks, validate_site_url,
)


@pytest.mark.parametrize("url", [
    "http://mado-project-atlas.example.chatgpt.site/",
    "https://chatgpt.site/",
    "https://evilchatgpt.site/",
    "https://example.org/",
    "https://example.chatgpt.site:8443/",
    "https://example.chatgpt.site/?token=secret",
    "https://example.chatgpt.site/#secret",
    "https://user:pass@example.chatgpt.site/",
    "https://example.chatgpt.site/untrusted",
    "javascript:alert(1)",
])
def test_reject_unapproved_targets(url):
    with pytest.raises(LiveSitesError):
        validate_site_url(url)


def test_valid_url_normalizes():
    assert validate_site_url("https://example.chatgpt.site") == "https://example.chatgpt.site/"


def test_absent_evidence_is_not_success():
    report = {"visual_checks": evaluate_checks({})}
    assert all(v["status"] == "not_observed" for v in report["visual_checks"].values())
    assert decision_gate(report)["release_approved"] is False
    assert decision_gate(report)["ui_candidate"] == "hold"


def test_observed_failures_hold_gate():
    sample = {name: {field: True for field in (
        "title", "h1", "main", "search", "filters", "project_cards",
        "no_horizontal_overflow", "no_js_errors")} for name in VIEWPORTS}
    sample["mobile"]["no_horizontal_overflow"] = False
    report = {"visual_checks": evaluate_checks(sample)}
    assert report["visual_checks"]["mobile"]["status"] == "failed"
    assert decision_gate(report)["ui_candidate"] == "hold"


def test_full_ui_evidence_is_not_production_approval():
    fields = ("title", "h1", "main", "search", "filters", "project_cards",
              "no_horizontal_overflow", "no_js_errors")
    report = {"visual_checks": evaluate_checks({name: {key: True for key in fields} for name in VIEWPORTS})}
    gate = decision_gate(report)
    assert gate["ui_candidate"] == "passed"
    assert gate["public_access"] == "unverified"
    assert gate["audience"] == "unverified"
    assert gate["source_revision"] == "unverified"
    assert gate["release_approved"] is False
