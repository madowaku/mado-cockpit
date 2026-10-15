import json
import struct
import zlib
from pathlib import Path

import pytest

from mado_cockpit.design_intelligence_lab import (
    BRIEF_SCHEMA, CANDIDATE_MAP, DEFAULT_DESIGN_TRACK,
    DesignIntelligenceLab, DesignLabError,
)
from mado_cockpit.design_discovery import (
    CATALOG, DesignDiscoveryHub, DiscoveryError, _digest,
)
from mado_cockpit.models import Project
from mado_cockpit.store import CockpitStore

COMMIT_COUNT = 10


def make_lab(root):
    CockpitStore(root).init(Project(id="design-lab", name="Design Lab", root=str(root)))
    hub = DesignDiscoveryHub(root)
    hub.bootstrap()
    return DesignIntelligenceLab(root), hub


def brief(tmp_path):
    path = tmp_path / "brief.json"
    path.write_text(json.dumps({
        "schema": BRIEF_SCHEMA, "title": "MADO Approval Console",
        "audience": "Operators overseeing AI changes",
        "goal": "Approval console showing sources and human approval flow",
        "framework": "react", "theme": "Keep existing brand tokens",
        "viewport": [1280, 800],
        "acceptance": [
            "Display incoming change request and origin provenance",
            "Keep approval gated by actual user permissions",
            "Provide a readable change summary with evidence",
            "Ensure accessible focus and responsive behavior",
        ],
    }), encoding="utf-8")
    return path


def tiny_png(width=1280, height=800):
    def chunk(kind, data):
        return (len(data).to_bytes(4, "big") + kind + data
                + (zlib.crc32(kind + data) & 0xffffffff).to_bytes(4, "big"))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    scanline = b"\x00" + b"\x30\x40\x50\xff" * width
    pixels = scanline * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def test_all_ten_pinned_and_labeled_no_auto_execute(tmp_path):
    lab, hub = make_lab(tmp_path)
    catalog = lab.catalog()
    assert len(catalog) == COMMIT_COUNT
    assert len({x["repository"] for x in catalog}) == 10
    assert len({x["commit"] for x in catalog}) == 10
    assert all(len(x["commit"]) == 40 for x in catalog)
    assert len(CATALOG) == 53
    assert len(hub.sources("design")) >= 1
    assert CANDIDATE_MAP["canvas-ui"]["license"] == "MIT+Commons-Clause"
    assert CANDIDATE_MAP["hyperiux"]["license"] == "Hyperiux-Effects-License"
    assert CANDIDATE_MAP["cursify"]["license"] == "unverified"
    assert CANDIDATE_MAP["paper-shaders"]["license"] == "Apache-2.0"
    assert CANDIDATE_MAP["hyperiux"]["discovery_source_id"] == "hyperiux-vault"
    assert len(lab.catalog(role="design_skill")) == 3
    assert len(lab.catalog(role="component")) == 7
    assert lab.catalog(query="motion-primitives")[0]["id"] == "motion-primitives"
    assert not (tmp_path / "node_modules").exists()


@pytest.mark.parametrize("size", [10, 18, 28, 36, 42, 43, 44])
def test_known_source_upgrades_preserve_review_evidence(tmp_path, size):
    lab, hub = make_lab(tmp_path)
    approved = hub.add("evilbuttons", "Approved old UI reference", "https://evilbuttons.com/",
                       note="Existing reference kept for backwards compatibility")
    hub.review(approved["id"], decision="approve", actor="human:owner",
               note="Reference approved for research only, not source reuse")
    before = hub.references()
    audit = hub.audit.read_bytes()
    stored = json.loads(hub.path.read_text())
    stored["source_catalog_sha256"] = _digest({"sources": CATALOG[:size]})
    hub.path.write_text(json.dumps(stored))
    assert hub.bootstrap()["status"] == "upgraded"
    assert hub.bootstrap()["status"] == "existing"
    assert hub.references() == before
    assert hub.audit.read_bytes() == audit
    assert lab.catalog()


def test_migration_fails_on_future_reference(tmp_path):
    _, hub = make_lab(tmp_path)
    hub.add("trickle-ui-kit", "Future candidate", "https://github.com/akaieuan/trickle-UI-kit",
            note="Cannot claim this source existed in the 44-source catalog")
    old = json.loads(hub.path.read_text())
    old["source_catalog_sha256"] = _digest({"sources": CATALOG[:44]})
    hub.path.write_text(json.dumps(old))
    with pytest.raises(DiscoveryError, match="predates"):
        hub.bootstrap()


def test_readonly_probe_and_deterministic_three_skill_tasks(tmp_path):
    lab, _ = make_lab(tmp_path)
    spec = brief(tmp_path)
    assert lab.probe()["status"] == "manifest_not_provided"
    pkg = tmp_path / "package.json"
    pkg.write_text(json.dumps({"dependencies": {"react": "18.3.1", "motion": "11.0.0"},
                               "devDependencies": {"tailwindcss": "4.0.0"}}), encoding="utf-8")
    probe = lab.probe(pkg)
    assert probe["status"] == "static_manifest_inspected_not_executed"
    assert probe["detected_dependencies"] == ["motion", "react", "tailwindcss"]
    initial = lab.plan(spec, package_file=pkg)
    assert initial["candidate_count"] == 3
    assert initial["status"] == "created"
    assert lab.plan(spec, package_file=pkg)["status"] == "existing"
    folder = Path(initial["path"])
    assert {p.stem for p in (folder / "tasks").glob("*.json")} == set(DEFAULT_DESIGN_TRACK)
    task = json.loads((folder / "tasks" / "design-taste.json").read_text())
    assert task["status"] == "advisory_handoff_only"
    assert task["candidate"]["commit"] == CANDIDATE_MAP["design-taste"]["commit"]
    assert task["brief"]["acceptance"][0].startswith("Display")
    assert lab.compare(initial["experiment"])["complete"] is False
    assert not lab.compare(initial["experiment"])["release_approved"]
    with pytest.raises(DesignLabError, match="same|track"):
        lab.plan(spec, candidates=("design-taste", "motion-primitives"))


def test_component_track_and_no_runtime_claims(tmp_path):
    lab, _ = make_lab(tmp_path)
    plan = lab.plan(brief(tmp_path), candidates=("motion-primitives", "trickle"))
    assert plan["candidate_count"] == 2
    result = lab.compare(plan["experiment"])
    assert result["track"] == "component"
    assert [x["status"] for x in result["comparison"]] == ["not_evaluated"] * 2


def test_unsafe_benchmark_and_tampered_task_fail_closed(tmp_path):
    lab, _ = make_lab(tmp_path)
    path = brief(tmp_path)
    raw = json.loads(path.read_text())
    raw["viewport"] = [99999, 800]
    path.write_text(json.dumps(raw))
    with pytest.raises(DesignLabError, match="Viewport"):
        lab.plan(path)
    spec = brief(tmp_path)
    run = lab.plan(spec)
    folder = Path(run["path"])
    task_path = folder / "tasks" / "design-taste.json"
    task = json.loads(task_path.read_text())
    task["candidate"]["commit"] = "0" * 40
    task_path.write_text(json.dumps(task))
    with pytest.raises(DesignLabError, match="Tampered"):
        lab.compare(run["experiment"])


def test_real_png_review_and_comparison_evidence_integrity(tmp_path):
    lab, _ = make_lab(tmp_path)
    p = lab.plan(brief(tmp_path), candidates=("design-taste", "better-design"))
    folder = Path(p["path"])
    evidence = folder / "evidence"
    evidence.mkdir()
    img = tiny_png()
    dimensions = ("hierarchy", "typography", "layout", "interaction",
                  "accessibility", "responsive", "performance", "brand_fidelity")
    for candidate in ("design-taste", "better-design"):
        (evidence / (candidate + ".png")).write_bytes(img)
        scores = {name: (3 if candidate == "design-taste" else 2) for name in dimensions}
        (evidence / (candidate + ".json")).write_text(json.dumps({
            "schema": "mado.ui-compatibility-review.v1", "actor": "human:reviewer",
            "note": "Reviewed actual browser output against the fixed acceptance rubric",
            "scores": scores,
            "checks": {"keyboard": True, "touch": True, "reduced_motion": True,
                       "theme": True, "responsive": True},
            "observed_output": "Approval hierarchy and visual evidence reviewed on the actual viewport.",
            "cost_usd": 0.0,
        }))
        result = lab.record(p["experiment"], candidate, screenshot=candidate + ".png",
                            evaluation_file=candidate + ".json")
        assert result["status"] == "recorded"
        assert lab.record(p["experiment"], candidate, screenshot=candidate + ".png",
                          evaluation_file=candidate + ".json")["status"] == "existing"
    compare = lab.compare(p["experiment"])
    assert compare["complete"]
    assert not compare["release_approved"]
    assert [x["candidate"] for x in compare["comparison"]] == ["design-taste", "better-design"]
    assert compare["comparison"][0]["score_percent"] == 75.0
    (evidence / "design-taste.png").write_bytes(img + b"altered")
    with pytest.raises(DesignLabError, match="Screenshot evidence changed"):
        lab.compare(p["experiment"])


def test_review_requirements_reject_untrusted_claims(tmp_path):
    lab, _ = make_lab(tmp_path)
    p = lab.plan(brief(tmp_path), candidates=("design-taste", "better-design"))
    evidence = Path(p["path"]) / "evidence"
    evidence.mkdir()
    (evidence / "design-taste.png").write_bytes(tiny_png(800, 600))
    (evidence / "design-taste.json").write_text("{}")
    with pytest.raises(DesignLabError, match="dimensions"):
        lab.record(p["experiment"], "design-taste", screenshot="design-taste.png",
                   evaluation_file="design-taste.json")
    (evidence / "design-taste.png").write_bytes(tiny_png())
    with pytest.raises(DesignLabError, match="versioned review"):
        lab.record(p["experiment"], "design-taste", screenshot="design-taste.png",
                   evaluation_file="design-taste.json")
    with pytest.raises(DesignLabError, match="filenames"):
        lab.record(p["experiment"], "design-taste", screenshot="../other.png",
                   evaluation_file="design-taste.json")
