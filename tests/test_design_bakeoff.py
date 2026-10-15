"""Unit tests for the optional local browser evidence bridge.

Synthetic PNGs below test contract checks only. The separate GitHub workflow
runs real Chromium/Playwright and uploads genuine fixture screenshots.
"""
import json
import struct
import zlib
from pathlib import Path

import pytest

from mado_cockpit.design_bakeoff import (
    ScreenshotEvidenceBridge, BakeoffError, _loopback_url, CAPTURE_SCHEMA,
)
from mado_cockpit.design_discovery import DesignDiscoveryHub
from mado_cockpit.design_intelligence_lab import DesignIntelligenceLab, _canonical, _sha
from mado_cockpit.models import Project
from mado_cockpit.store import CockpitStore


def png(w, h, pixel=(56, 68, 86, 255)):
    def chunk(kind, payload):
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff))
    scan = (b"\x00" + bytes(pixel) * w) * h
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(scan)) + chunk(b"IEND", b""))


def sample(tmp_path):
    CockpitStore(tmp_path).init(Project(id="bakeoff", name="Bakeoff", root=str(tmp_path)))
    DesignDiscoveryHub(tmp_path).bootstrap()
    lab = DesignIntelligenceLab(tmp_path)
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps({
        "schema": "mado.ui-compatibility-brief.v1",
        "title": "Approval Console",
        "audience": "Human quality reviewers",
        "goal": "Compare a safe approval console UI",
        "framework": "react", "theme": "Existing product branding",
        "viewport": [640, 480],
        "acceptance": [
            "Show clear evidence before enabling a human review",
            "Expose understandable visual hierarchy and typography",
            "Support keyboard, mobile and reduced motion behavior",
        ],
    }), encoding="utf-8")
    plan = lab.plan(brief, candidates=("design-taste", "better-design", "superdesign"))
    source = tmp_path / "index.html"
    source.write_text("<!doctype html><title>Fixture</title><p>Hello UI</p>", encoding="utf-8")
    return ScreenshotEvidenceBridge(tmp_path), plan, source


def fake_capture(**args):
    viewport = args["viewport"]
    for state, dims in (("light", viewport), ("dark", viewport), ("mobile", (390, 844))):
        (args["staging"] / (state + ".png")).write_bytes(png(*dims))
    return {
        "browser_engine": "chromium", "browser_version": "test-no-browser",
        "browser_channel": "test", "http_status": 200, "locale": "en-US",
        "timezone": "UTC", "dpr": 1, "reduced_motion": "reduce",
        "animations": "disabled", "external_requests_blocked": 0,
        "javascript_errors": 0, "console_errors": 0, "capture_states": [
            {"state": "light", "width": viewport[0], "height": viewport[1]},
            {"state": "dark", "width": viewport[0], "height": viewport[1]},
            {"state": "mobile", "width": 390, "height": 844},
        ],
        "captured_at": "test-fixture",
    }


@pytest.mark.parametrize("bad", [
    "https://127.0.0.1:8080", "http://evil.example:8080",
    "http://127.0.0.1:8080@evil.example", "http://127.0.0.1/",
    "http://127.0.0.1:8080/?token=a", "http://127.0.0.1:8080/#frag",
    "http://127.0.0.1:22/", "http://localhost:8080\\evil",
])
def test_no_external_or_credentialed_urls(bad):
    with pytest.raises(BakeoffError):
        _loopback_url(bad)


def test_capture_three_states_and_receipt_verification(monkeypatch, tmp_path):
    monkeypatch.setattr("mado_cockpit.design_bakeoff._browser_capture", fake_capture)
    bridge, plan, source = sample(tmp_path)
    ident = plan["experiment"]
    outcome = bridge.capture(ident, "design-taste", url="http://127.0.0.1:8765/",
                             source_file=source, provenance="fixture_smoke")
    assert outcome["status"] == "captured_unreviewed"
    verified = bridge.verify(ident, "design-taste")
    assert verified["schema"] == CAPTURE_SCHEMA
    assert [v["state"] for v in verified["images"]] == ["light", "dark", "mobile"]
    assert bridge.capture(ident, "design-taste", url="http://127.0.0.1:8765/",
                          source_file=source, provenance="fixture_smoke")["status"] == "existing"
    comparison = bridge.compare(ident)
    assert comparison["capture_complete"] is False
    assert comparison["comparison"][0]["screenshot_capture"] in ("verified_local_browser", "not_captured")
    assert comparison["release_approved"] is False
    with pytest.raises(BakeoffError, match="Fixture-smoke"):
        bridge.review(ident, "design-taste", evaluation_file="design-taste.json")


def test_screenshot_hash_and_receipt_tampering_detected(monkeypatch, tmp_path):
    monkeypatch.setattr("mado_cockpit.design_bakeoff._browser_capture", fake_capture)
    bridge, plan, source = sample(tmp_path)
    exp = plan["experiment"]
    bridge.capture(exp, "design-taste", url="http://localhost:8765/",
                   source_file=source)
    folder = Path(plan["path"]) / "evidence"
    light = folder / "design-taste.png"
    original = light.read_bytes()
    light.write_bytes(original + b"junk")
    with pytest.raises(BakeoffError, match="hash or structural"):
        bridge.verify(exp, "design-taste")
    light.write_bytes(original)
    receipt = folder / "design-taste.capture.json"
    obj = json.loads(receipt.read_text())
    obj["data"]["runtime"]["dpr"] = 2
    receipt.write_text(json.dumps(obj))
    with pytest.raises(BakeoffError, match="integrity mismatch"):
        bridge.verify(exp, "design-taste")


def test_capture_fails_without_partial_artifacts(monkeypatch, tmp_path):
    def failing_runner(**kwargs):
        stage = kwargs["staging"]
        (stage / "light.png").write_bytes(png(640, 480))
        raise BakeoffError("External network request blocked")
    monkeypatch.setattr("mado_cockpit.design_bakeoff._browser_capture", failing_runner)
    bridge, plan, source = sample(tmp_path)
    with pytest.raises(BakeoffError, match="External network"):
        bridge.capture(plan["experiment"], "design-taste",
                       url="http://127.0.0.1:8765/", source_file=source)
    assert not (Path(plan["path"]) / "evidence" / "design-taste.png").exists()


def test_contact_sheet_and_origin_integrity(monkeypatch, tmp_path):
    monkeypatch.setattr("mado_cockpit.design_bakeoff._browser_capture", fake_capture)
    bridge, plan, source = sample(tmp_path)
    ident = plan["experiment"]
    for cid in ("design-taste", "better-design", "superdesign"):
        bridge.capture(ident, cid, url="http://127.0.0.1:8765/",
                       source_file=source, provenance="fixture_smoke")
    assert bridge.compare(ident)["capture_complete"] is False
    result = bridge.sheet(ident, state="light")
    assert result["status"] == "visual_contact_sheet_not_quality_assessment"
    raw = Path(result["path"]).read_bytes()
    assert raw.startswith(b"\x89PNG\r\n\x1a\n")
    assert bridge.sheet(ident)["sha256"] == result["sha256"]
    assert bridge.sheet(ident, state="dark")["status"] == result["status"]
    assert bridge.sheet(ident, state="mobile")["status"] == result["status"]
    (Path(plan["path"]) / "evidence" / "better-design.png").write_bytes(png(640, 480, (1, 2, 3, 255)))
    with pytest.raises(BakeoffError, match="hash or structural"):
        bridge.sheet(ident)


def test_browser_capture_review_flows_through_existing_lab(monkeypatch, tmp_path):
    monkeypatch.setattr("mado_cockpit.design_bakeoff._browser_capture", fake_capture)
    bridge, plan, source = sample(tmp_path)
    exp = plan["experiment"]
    bridge.capture(exp, "design-taste", url="http://127.0.0.1:8765/",
                   source_file=source, provenance="operator_supplied_build")
    evidence = Path(plan["path"]) / "evidence"
    review = {
        "schema": "mado.ui-compatibility-review.v1",
        "actor": "human:reviewer",
        "note": "Inspected the rendered browser screenshots and keyboard focus",
        "scores": {k: 3 for k in (
            "hierarchy", "typography", "layout", "interaction",
            "accessibility", "responsive", "performance", "brand_fidelity")},
        "checks": {k: True for k in ("keyboard", "touch", "reduced_motion", "theme", "responsive")},
        "observed_output": "Actual page layout and human approval controls were inspected.",
        "cost_usd": None,
    }
    (evidence / "design-taste.json").write_text(json.dumps(review))
    recorded = bridge.review(exp, "design-taste", evaluation_file="design-taste.json")
    assert recorded["score_percent"] == 75
    result = bridge.compare(exp)
    assert not result["complete"]
    assert not result["release_approved"]
    assert not result["capture_complete"]
    assert any(e["status"] == "human_asserted_evaluation" for e in result["comparison"])
