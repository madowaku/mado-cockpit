import json
import struct
import zlib
from pathlib import Path

import pytest

from mado_cockpit.design_discovery import DesignDiscoveryHub
from mado_cockpit.models import Project
from mado_cockpit.motion_foundry import MotionFoundry
from mado_cockpit.motion_recipe import MotionRecipeRegistry, MotionRecipeError, main
from mado_cockpit.store import CockpitStore


def _png(width=1280, height=720, color=(10, 20, 30)):
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))
    raw = (b"\x00" + bytes(color) * width) * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _setup(root):
    CockpitStore(root).init(Project(id="test-motion-recipe", name="Video QA", root=str(root)))
    DesignDiscoveryHub(root).bootstrap()
    brief = {"schema": "mado.motion-brief.v1", "title": "GYRO LAB Title",
             "format": "landscape", "background": "#101020", "foreground": "#ffffff",
             "accent": "#50ddff", "scenes": [
                 {"heading": "GYRO LAB", "body": "Motion prototype", "duration_frames": 60}]}
    project = Path(MotionFoundry(root).plan(brief)["path"])
    registry = MotionRecipeRegistry(root)
    selected = registry.select(project, "remotion-title-reveal")
    return registry, project, selected


def _captured(root, frames=(0, 30, 59), actual=None, dims=(1280, 720)):
    b, a = root / "baseline", root / "actual"
    b.mkdir(exist_ok=True)
    a.mkdir(exist_ok=True)
    for frame in frames:
        name = f"frame_{frame:06d}.png"
        (b / name).write_bytes(_png(*dims))
        (a / name).write_bytes(_png(*dims, color=(10, 20, 30) if actual is None else actual))
    return b, a


def test_registry_and_selection_are_stable(tmp_path):
    registry, project, selected = _setup(tmp_path)
    assert len(registry.list_recipes()) >= 4
    assert registry.list_recipes("remotion")[0]["adapter"] == "m2.6.3-native"
    assert registry.list_recipes("hyperframes")[0]["adapter"] == "reference-only"
    assert all(x["license_status"] == "operator_review_required" for x in registry.list_recipes())
    assert registry.select(project, "remotion-title-reveal") == selected
    assert selected["source_handling"] == "reference_link_only_no_code_import"
    with pytest.raises(MotionRecipeError, match="Unknown recipe"):
        registry.select(project, "missing")
    assert not (project / "recipe.json").exists()


def test_exact_sampling_and_human_review(tmp_path):
    registry, _, selected = _setup(tmp_path)
    b, a = _captured(tmp_path)
    receipt = registry.qa(selected["selection_id"], b, a, [0, 30, 59])
    assert receipt["status"] == "passed_pending_human"
    assert len(receipt["samples"]) == 3
    assert receipt["samples"][-1]["time_seconds"] == 59 / 30
    assert "audio_sync" in receipt["not_verified"]
    assert registry.qa(selected["selection_id"], b, a, [0, 30, 59]) == receipt
    review = registry.review(receipt["receipt_id"], actor="human:owner",
                             note="Checked all sampled frames")
    assert review["decision"] == "visual_approved_not_release_cleared"
    (a / "frame_000030.png").write_bytes(_png(color=(99, 20, 30)))
    with pytest.raises(MotionRecipeError, match="Screenshots changed"):
        registry.review(receipt["receipt_id"], actor="human:owner", note="Repeat")


def test_mismatch_blocks_approval_but_supports_explicit_tolerance(tmp_path):
    registry, _, selected = _setup(tmp_path)
    b, a = _captured(tmp_path, frames=[0], actual=(11, 20, 30))
    receipt = registry.qa(selected["selection_id"], b, a, [0])
    assert receipt["status"] == "failed"
    assert receipt["samples"][0]["changed_fraction"] == 1
    with pytest.raises(MotionRecipeError, match="Failed QA"):
        registry.review(receipt["receipt_id"], actor="human:owner", note="Incorrect approval")
    relaxed = registry.qa(selected["selection_id"], b, a, [0],
                          max_changed_fraction=1.0, max_mae=2)
    assert relaxed["status"] == "passed_pending_human"
    assert relaxed["receipt_id"] != receipt["receipt_id"]


def test_dimension_and_range_rejection(tmp_path):
    registry, _, selected = _setup(tmp_path)
    b, a = _captured(tmp_path, frames=[0], dims=(20, 20))
    assert registry.qa(selected["selection_id"], b, a, [0])["status"] == "failed"
    with pytest.raises(MotionRecipeError, match="in-range"):
        registry.qa(selected["selection_id"], b, a, [60])
    with pytest.raises(MotionRecipeError, match="finite"):
        registry.qa(selected["selection_id"], b, a, [0], max_mae=float("nan"))
    with pytest.raises(MotionRecipeError, match="Missing or unsafe frame"):
        registry.qa(selected["selection_id"], b, a, [1])


def test_project_and_receipt_tampering_blocked(tmp_path):
    registry, project, selected = _setup(tmp_path)
    b, a = _captured(tmp_path, frames=[0])
    receipt = registry.qa(selected["selection_id"], b, a, [0])
    receipt_file = registry.base / "qa" / f"{receipt['receipt_id']}.json"
    corrupted = json.loads(receipt_file.read_text())
    corrupted["status"] = "failed"
    receipt_file.write_text(json.dumps(corrupted))
    with pytest.raises(MotionRecipeError, match="digest mismatch"):
        registry.review(receipt["receipt_id"], actor="human:owner", note="Not valid")
    (project / "src" / "Video.tsx").write_text("modified")
    with pytest.raises(ValueError, match="Source integrity"):
        registry.select(project, "remotion-title-reveal")


def test_cli_catalog_and_selection(tmp_path, capsys):
    registry, project, _ = _setup(tmp_path)
    assert main(["--root", str(tmp_path), "list", "--engine", "remotion"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["engine"] == "remotion"
    assert main(["--root", str(tmp_path), "select", str(project), "remotion-title-reveal"]) == 0
    assert json.loads(capsys.readouterr().out)["selection_id"].startswith("recipe_")
