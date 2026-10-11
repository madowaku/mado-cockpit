import json
from pathlib import Path

import pytest

from mado_cockpit.design_discovery import DesignDiscoveryHub
from mado_cockpit.models import Project
from mado_cockpit.motion_foundry import MotionFoundry, MotionFoundryError, validate_brief, main
from mado_cockpit.store import CockpitStore


def brief(**changes):
    payload = {
        "schema": "mado.motion-brief.v1",
        "title": "MADO Launch",
        "format": "landscape",
        "background": "#0b1020",
        "foreground": "#f8fafc",
        "accent": "#5be9c4",
        "scenes": [
            {"heading": "From idea to output", "body": "Make creative work visible.", "duration_frames": 60},
            {"heading": "Ship with evidence", "body": "Review every frame.", "duration_frames": 90},
        ],
    }
    payload.update(changes)
    return payload


def foundry(tmp_path: Path):
    CockpitStore(tmp_path).init(Project(id="motion-test", name="Motion", root=str(tmp_path)))
    hub = DesignDiscoveryHub(tmp_path)
    hub.bootstrap()
    return MotionFoundry(tmp_path), hub


def test_plan_outputs_remotion_project_and_codex_context(tmp_path):
    worker, _ = foundry(tmp_path)
    result = worker.plan(brief())
    folder = Path(result["path"])
    assert result["status"] == "created"
    assert result["duration_frames"] == 150
    assert (result["width"], result["height"]) == (1280, 720)
    assert result["render_state"] == "not_rendered"
    assert worker.verify(folder)["files_checked"] == 8
    assert (folder / "src/index.ts").read_text().count("registerRoot(Root)") == 1
    assert 'id="MadoMotion"' in (folder / "src/Root.tsx").read_text()
    pkg = json.loads((folder / "package.json").read_text())
    assert pkg["dependencies"]["remotion"] == pkg["devDependencies"]["@remotion/cli"]
    assert not (folder / "node_modules").exists()
    assert not (folder / "out").exists()
    context = json.loads((folder / "codex-task.json").read_text())
    assert context["required_evidence"] == ["source_integrity", "render_receipt", "manual_visual_review"]
    assert context["approved_reference_links"] == []
    assert worker.plan(brief())["status"] == "existing"
    assert any(event["type"] == "motion.plan.created" for event in worker.store.list_events())


def test_context_pack_includes_only_reviewed_reference_links(tmp_path):
    worker, hub = foundry(tmp_path)
    accepted = hub.add("remotion", "Official documentation", "https://remotion.dev/docs",
                       note="Official reference, no third-party assets")
    rejected = hub.add("reactbits", "Do not use", "https://reactbits.dev/",
                       note="Rights status pending")
    hub.review(accepted["id"], decision="approve", actor="human:owner",
               note="Approved as an untrusted reference link")
    hub.review(rejected["id"], decision="reject", actor="human:owner",
               note="No evidence for this component asset")
    result = worker.plan(brief())
    context = json.loads((Path(result["path"]) / "codex-task.json").read_text())
    assert len(context["approved_reference_links"]) == 1
    assert context["approved_reference_links"][0]["source_id"] == "remotion"
    assert context["approved_reference_links"][0]["sha256"] == accepted["sha256"]
    assert "note" not in context["approved_reference_links"][0]


def test_different_brief_creates_separate_project(tmp_path):
    worker, _ = foundry(tmp_path)
    first = worker.plan(brief())
    changed = worker.plan(brief(title="New title"))
    assert first["project_id"] != changed["project_id"]


def test_verify_detects_changed_source(tmp_path):
    worker, _ = foundry(tmp_path)
    folder = Path(worker.plan(brief())["path"])
    (folder / "src/Video.tsx").write_text("injected external code", encoding="utf-8")
    with pytest.raises(MotionFoundryError, match="Source integrity"):
        worker.verify(folder)
    with pytest.raises(MotionFoundryError, match="Source integrity"):
        worker.plan(brief())


def test_plan_fails_without_discovery_bootstrap(tmp_path):
    CockpitStore(tmp_path).init(Project(id="motion", name="Motion", root=str(tmp_path)))
    with pytest.raises(MotionFoundryError, match="Bootstrap Design Discovery"):
        MotionFoundry(tmp_path).plan(brief())


@pytest.mark.parametrize("invalid", [
    {"format": "freeform"},
    {"scenes": []},
    {"scenes": [{}]},
    {"scenes": [{"heading": "X", "body": "Y", "duration_frames": True}]},
    {"scenes": [{"heading": "X", "body": "Y", "duration_frames": 10}]},
    {"scenes": [{"heading": "X", "body": "Y", "duration_frames": 300}] * 7},
    {"background": "red"},
    {"extra": "surprise"},
    {"title": ""},
])
def test_invalid_briefs_are_rejected(invalid):
    with pytest.raises(MotionFoundryError):
        validate_brief(brief(**invalid))


@pytest.mark.parametrize("format_name,resolution", [
    ("landscape", (1280, 720)),
    ("portrait", (1080, 1920)),
    ("square", (1080, 1080)),
])
def test_preset_dimensions(tmp_path, format_name, resolution):
    worker, _ = foundry(tmp_path)
    result = worker.plan(brief(format=format_name))
    assert (result["width"], result["height"]) == resolution


def test_render_refuses_implicit_execution_and_unattested_license(tmp_path):
    worker, _ = foundry(tmp_path)
    folder = Path(worker.plan(brief())["path"])
    with pytest.raises(MotionFoundryError, match="--execute"):
        worker.render(folder, allow_execute=False, license_attested=True)
    with pytest.raises(MotionFoundryError, match="--license-attested"):
        worker.render(folder, allow_execute=True, license_attested=False)
    with pytest.raises(MotionFoundryError, match="Local Remotion CLI missing"):
        worker.render(folder, allow_execute=True, license_attested=True)
    assert not (folder / "out").exists()
    assert not (folder / "render-evidence.json").exists()


def test_cannot_verify_outside_motion_workspace(tmp_path):
    worker, _ = foundry(tmp_path)
    with pytest.raises(MotionFoundryError, match="immediate child"):
        worker.verify(tmp_path)


def test_malformed_or_tampered_manifest_rejected(tmp_path):
    worker, _ = foundry(tmp_path)
    folder = Path(worker.plan(brief())["path"])
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["files"]["evil.py"] = "deadbeef"
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(MotionFoundryError, match="Invalid Motion Foundry"):
        worker.verify(folder)


def test_cli_plan_and_verify(tmp_path, capsys):
    worker, _ = foundry(tmp_path)
    input_file = tmp_path / "brief.json"
    input_file.write_text(json.dumps(brief()), encoding="utf-8")
    assert main(["--root", str(tmp_path), "plan", str(input_file)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert main(["--root", str(tmp_path), "verify", result["path"]]) == 0
    assert "source_verified" in capsys.readouterr().out
