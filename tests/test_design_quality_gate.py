"""MCC-M2.6.2g: real-run trace, build-source binding and decision hard gates.

Fake capture stubs are used only for fast unit contract tests. The separate
browser smoke workflow renders actual HTML with Chrome/Chromium and uploads it.
"""
from __future__ import annotations

import hashlib
import json
import struct
import urllib.request
import zlib
from pathlib import Path

import pytest

from mado_cockpit.design_bakeoff import BakeoffError
from mado_cockpit.design_quality_gate import (
    RealUIDecisionGate, QualityGateError, RUN_SCHEMA, _safe_build_tree,
)
from mado_cockpit.design_intelligence_lab import (
    CANDIDATE_MAP, DesignIntelligenceLab, _sha, _read,
)
from mado_cockpit.design_discovery import DesignDiscoveryHub
from mado_cockpit.models import Project
from mado_cockpit.store import CockpitStore

CANDIDATES = ("design-taste", "better-design", "superdesign")
MODES = {"design-taste": "design_taste_skill",
         "better-design": "better_design_mcp",
         "superdesign": "superdesign_cli"}


def png(width: int, height: int, rgba: tuple[int, int, int, int]) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff))
    scanline = (b"\x00" + bytes(rgba) * width) * height
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(scanline)) + chunk(b"IEND", b""))


def make_world(tmp_path):
    CockpitStore(tmp_path).init(Project(id="real-ui-gate", name="Real UI", root=str(tmp_path)))
    DesignDiscoveryHub(tmp_path).bootstrap()
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps({
        "schema": "mado.ui-compatibility-brief.v1",
        "title": "Operator Review Console",
        "audience": "Human MADO operator",
        "goal": "Choose a readable safe approval UI",
        "framework": "react", "theme": "Preserve existing MADO brand",
        "viewport": [640, 480],
        "acceptance": [
            "Show provenance before a user reviews the proposal",
            "Explain why the approve action is gated",
            "Present keyboard accessible navigation and actions",
        ],
    }), encoding="utf-8")
    lab = DesignIntelligenceLab(tmp_path)
    plan = lab.plan(brief, candidates=CANDIDATES)
    return RealUIDecisionGate(tmp_path), lab, plan


def add_run(tmp_path, gate, lab, plan, candidate, *,
            mode=None, cost=None, variant=None):
    exp = plan["experiment"]
    task = Path(plan["path"]) / "tasks" / (candidate + ".json")
    bundle = tmp_path / "candidate-builds" / candidate
    bundle.mkdir(parents=True, exist_ok=True)
    if variant is None:
        variant = candidate
    (bundle / "index.html").write_text(
        "<!doctype html><html lang='en'><head><title>Real UI</title></head>"
        f"<body><main><h1>{variant}</h1><button type='button'>Review</button></main></body></html>",
        encoding="utf-8",
    )
    (bundle / "style.css").write_text(
        f"body{{background:#{hashlib.sha256(variant.encode()).hexdigest()[:6]};}}", encoding="utf-8")
    trace = tmp_path / (candidate + "-trace.txt")
    trace.write_text("Operator-supplied run trace (not verified by provider). "
                     + candidate * 4, encoding="utf-8")
    declared = {
        "schema": RUN_SCHEMA, "experiment": exp, "candidate": candidate,
        "task_sha256": _sha(task.read_bytes()),
        "upstream_commit": CANDIDATE_MAP[candidate]["commit"],
        "execution_mode": mode or MODES[candidate],
        "run_id": "local-session-" + candidate,
        "operator": "human:operator",
        "command_summary": "Completed one separately authorized UI design run",
        "output_revision": "a" * 40,
        "cost_usd": cost,
        "duration_seconds": 62.3,
        "status": "completed",
    }
    declaration = tmp_path / (candidate + "-declaration.json")
    declaration.write_text(json.dumps(declared), encoding="utf-8")
    result = gate.intake(exp, candidate, declaration_file=declaration,
                         bundle=bundle, trace_file=trace)
    assert result["status"] == "intaken"
    assert gate.intake(exp, candidate, declaration_file=declaration,
                       bundle=bundle, trace_file=trace)["status"] == "existing"
    return {"bundle": bundle, "declaration": declaration, "trace": trace}


def fake_real_browser(**kwargs):
    # Real local HTTP is used to prove source bytes match what the static server served.
    with urllib.request.urlopen(kwargs["url"]) as response:
        html = response.read()
    rgba = tuple(hashlib.sha256(html).digest()[:3]) + (255,)
    viewport = kwargs["viewport"]
    audits = []
    for state, (w, h) in [
        ("light", viewport), ("dark", viewport), ("mobile", (390, 844))
    ]:
        (kwargs["staging"] / (state + ".png")).write_bytes(png(w, h, rgba))
        audits.append({
            "state": state, "lang_present": True, "main_count": 1,
            "heading_count": 1, "focusable_count": 1, "unnamed_controls": 0,
            "horizontal_overflow_px": 0, "reduced_motion_active": True,
        })
    return {
        "browser_engine": "chromium", "browser_version": "mock-not-real-browser",
        "browser_channel": "test", "http_status": 200, "locale": "en-US",
        "timezone": "UTC", "dpr": 1, "reduced_motion": "reduce",
        "animations": "disabled", "external_requests_blocked": 0,
        "javascript_errors": 0, "console_errors": 0, "dom_audits": audits,
        "served_html_sha256": _sha(html),
        "capture_states": [
            {"state": "light", "width": viewport[0], "height": viewport[1]},
            {"state": "dark", "width": viewport[0], "height": viewport[1]},
            {"state": "mobile", "width": 390, "height": 844},
        ],
    }


def reviewed(gate, lab, plan, candidate, *, score=3, cost=0.0, brand=3, keyboard=True):
    folder = Path(plan["path"]) / "evidence"
    review = {
        "schema": "mado.ui-compatibility-review.v1", "actor": "human:reviewer",
        "note": "Inspected all rendered viewports and recorded the observed output",
        "scores": {
            "hierarchy": score, "typography": score, "layout": score,
            "interaction": score, "accessibility": score,
            "responsive": score, "performance": score, "brand_fidelity": brand,
        },
        "checks": {"keyboard": keyboard, "touch": True, "reduced_motion": True,
                   "theme": True, "responsive": True},
        "observed_output": "Verified label quality, layout stability and scroll behavior.",
        "cost_usd": cost,
    }
    folder.mkdir(exist_ok=True)
    (folder / (candidate + ".json")).write_text(json.dumps(review), encoding="utf-8")
    return gate.bridge.review(plan["experiment"], candidate, evaluation_file=candidate + ".json")


def test_no_external_service_and_incomplete_evidence_holds(tmp_path):
    gate, lab, plan = make_world(tmp_path)
    result = gate.evaluate(plan["experiment"])
    assert result["status"] == "hold_missing_evidence"
    assert result["recommendation"] is None
    assert not result["model_authorship_verified"]
    assert not result["license_and_release_approved"]
    assert all("missing_real_run" in row["reasons"] for row in result["candidates"])
    sealed = gate.seal(plan["experiment"])
    assert sealed["decision_status"] == "hold_missing_evidence"
    assert gate.seal(plan["experiment"])["status"] == "existing"
    with pytest.raises(QualityGateError, match="No complete"):
        gate.select(plan["experiment"], candidate="design-taste", actor="human:owner",
                    note="This selection has no actual evidence and must be rejected.")


def test_enroll_trace_tampering_and_source_change_detection(tmp_path):
    gate, lab, plan = make_world(tmp_path)
    info = add_run(tmp_path, gate, lab, plan, "design-taste", cost=0.0)
    _, run_sha = gate.verify_run(plan["experiment"], "design-taste")
    assert len(run_sha) == 64
    source = info["bundle"] / "index.html"
    old = source.read_text()
    source.write_text(old + "<p>Tampered</p>", encoding="utf-8")
    with pytest.raises(QualityGateError, match="Local build changed"):
        gate.verify_run(plan["experiment"], "design-taste")
    source.write_text(old, encoding="utf-8")
    info["trace"].write_text(info["trace"].read_text() + "more", encoding="utf-8")
    with pytest.raises(QualityGateError, match="Execution trace changed"):
        gate.verify_run(plan["experiment"], "design-taste")


def test_declaration_changes_and_symlinked_files_fail(tmp_path):
    gate, lab, plan = make_world(tmp_path)
    info = add_run(tmp_path, gate, lab, plan, "design-taste", cost=0.0)
    info["declaration"].write_text(info["declaration"].read_text() + " ", encoding="utf-8")
    with pytest.raises(QualityGateError, match="declaration file changed"):
        gate.verify_run(plan["experiment"], "design-taste")
    other = tmp_path / "outside.txt"
    other.write_text("Secret-ish data", encoding="utf-8")
    (info["bundle"] / "linked.txt").symlink_to(other)
    with pytest.raises(QualityGateError, match="symlink"):
        _safe_build_tree(info["bundle"])


def test_provider_mode_spoof_and_missing_trace_blocked(tmp_path):
    gate, lab, plan = make_world(tmp_path)
    with pytest.raises(QualityGateError, match="Execution mode"):
        add_run(tmp_path, gate, lab, plan, "better-design",
                mode="superdesign_cli", cost=1.0)
    # No recorded run when declaration is invalid.
    assert gate.evaluate(plan["experiment"])["status"] == "hold_missing_evidence"


def test_capture_local_binds_response_to_entrypoint(monkeypatch, tmp_path):
    monkeypatch.setattr("mado_cockpit.design_bakeoff._browser_capture", fake_real_browser)
    gate, lab, plan = make_world(tmp_path)
    add_run(tmp_path, gate, lab, plan, "design-taste", cost=0.0)
    output = gate.capture_local(plan["experiment"], "design-taste")
    assert output["status"] == "captured_unreviewed"
    assert len(output["served_entrypoint_sha256"]) == 64
    report = gate.evaluate(plan["experiment"])
    assert report["status"] == "hold_missing_evidence"
    assert "missing_human_review" in next(x for x in report["candidates"]
                                           if x["candidate"] == "design-taste")["reasons"]


def test_real_candidate_comparison_selects_quality_over_lower_cost_only_when_dominant(monkeypatch, tmp_path):
    monkeypatch.setattr("mado_cockpit.design_bakeoff._browser_capture", fake_real_browser)
    gate, lab, plan = make_world(tmp_path)
    exp = plan["experiment"]
    # These are simulated operator declarations. Neither provider invocation nor
    # independently authenticated provenance is claimed by this unit test.
    for candidate, cost in (("design-taste", 0.0),
                            ("better-design", 1.0),
                            ("superdesign", 2.0)):
        add_run(tmp_path, gate, lab, plan, candidate, cost=cost)
        gate.capture_local(exp, candidate)
        score = 4 if candidate == "design-taste" else 3
        reviewed(gate, lab, plan, candidate, score=score, brand=score, cost=cost)
    result = gate.evaluate(exp)
    assert result["status"] == "ready_for_human_selection"
    assert result["complete"]
    assert result["recommendation"] == "design-taste"
    assert not result["model_authorship_verified"]
    assert not result["license_and_release_approved"]
    assert all(x["status"] == "eligible_for_human_selection" for x in result["candidates"])
    gate.seal(exp)
    selected = gate.select(exp, candidate="design-taste", actor="human:owner",
                           note="I reviewed the comparable screenshot, human scores and costs.")
    assert selected["status"] == "recorded"
    assert not selected["release_approved"]
    assert gate.select(exp, candidate="design-taste", actor="human:owner",
                       note="I reviewed the comparable screenshot, human scores and costs.")["status"] == "existing"


def test_quality_hard_floor_and_unknown_cost_prevent_autoselection(monkeypatch, tmp_path):
    monkeypatch.setattr("mado_cockpit.design_bakeoff._browser_capture", fake_real_browser)
    gate, lab, plan = make_world(tmp_path)
    exp = plan["experiment"]
    for candidate in CANDIDATES:
        add_run(tmp_path, gate, lab, plan, candidate, cost=None)
        gate.capture_local(exp, candidate)
        reviewed(gate, lab, plan, candidate, score=2, brand=2, cost=None, keyboard=False)
    report = gate.evaluate(exp)
    assert report["complete"]
    assert report["status"] == "hold_no_eligible_candidate"
    assert report["recommendation"] is None
    assert all("cost_unreported" in r["reasons"] for r in report["candidates"])
    assert all("human_qa_checks_failed" in r["reasons"] for r in report["candidates"])
    with pytest.raises(QualityGateError, match="No complete"):
        gate.select(exp, candidate="design-taste", actor="human:reviewer",
                    note="I cannot select an unqualified design candidate here.")


def test_identical_screenshots_are_hold_not_fake_provider_winner(monkeypatch, tmp_path):
    monkeypatch.setattr("mado_cockpit.design_bakeoff._browser_capture", fake_real_browser)
    gate, lab, plan = make_world(tmp_path)
    exp = plan["experiment"]
    for candidate in CANDIDATES:
        # Matching UI markup simulates mislabeled output across provider names.
        add_run(tmp_path, gate, lab, plan, candidate, cost=0.0,
                variant="identical-candidate")
        gate.capture_local(exp, candidate)
        reviewed(gate, lab, plan, candidate, score=4, brand=4, cost=0.0)
    result = gate.evaluate(exp)
    assert result["status"] == "hold_duplicate_visual_evidence"
    assert result["recommendation"] is None
    assert all("identical_screenshot_across_candidates" in r["reasons"]
               for r in result["candidates"])


def test_fixture_manual_baseline_cannot_pass_as_real_provider(monkeypatch, tmp_path):
    monkeypatch.setattr("mado_cockpit.design_bakeoff._browser_capture", fake_real_browser)
    gate, lab, plan = make_world(tmp_path)
    exp = plan["experiment"]
    for candidate in CANDIDATES:
        add_run(tmp_path, gate, lab, plan, candidate, mode="manual_baseline", cost=0.0)
        output = gate.capture_local(exp, candidate)
        assert output["status"] == "captured_unreviewed"
        with pytest.raises(BakeoffError, match="Fixture-smoke"):
            gate.bridge.review(exp, candidate, evaluation_file=candidate + ".json")
    report = gate.evaluate(exp)
    assert report["status"] == "hold_missing_evidence"
    assert all("manually_authored_baseline_not_provider_run" in r["reasons"]
               for r in report["candidates"])
