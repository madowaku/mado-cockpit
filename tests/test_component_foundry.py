import json
import struct
import zlib
from pathlib import Path

import pytest

from mado_cockpit.component_foundry import (
    ComponentFoundry, ComponentGateError, PNG_MAGIC, _decode_png,
)
from mado_cockpit.design_discovery import DesignDiscoveryHub
from mado_cockpit.models import Project
from mado_cockpit.store import CockpitStore
from mado_cockpit.component_foundry import main


def png(width, height, pixels, filters=None):
    """Create genuine RGBA PNG screenshots using only the standard library."""
    assert len(pixels) == width * height * 4
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    scanlines = bytearray()
    prev = bytes(width * 4)
    for y in range(height):
        row = pixels[y * width * 4:(y + 1) * width * 4]
        filter_type = (filters or [0] * height)[y]
        scanlines.append(filter_type)
        encoded = bytearray()
        for i, val in enumerate(row):
            left = row[i - 4] if i >= 4 else 0
            above = prev[i]
            upper = prev[i - 4] if i >= 4 else 0
            if filter_type == 0:
                prediction = 0
            elif filter_type == 1:
                prediction = left
            elif filter_type == 2:
                prediction = above
            elif filter_type == 3:
                prediction = (left + above) // 2
            elif filter_type == 4:
                p = left + above - upper
                a, b, c = abs(p - left), abs(p - above), abs(p - upper)
                prediction = left if a <= b and a <= c else above if b <= c else upper
            encoded.append((val - prediction) & 255)
        scanlines.extend(encoded)
        prev = row
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return PNG_MAGIC + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(scanlines))) + chunk(b"IEND", b"")


def make_foundry(tmp_path):
    CockpitStore(tmp_path).init(Project(id="component", name="Components", root=str(tmp_path)))
    hub = DesignDiscoveryHub(tmp_path)
    hub.bootstrap()
    foundry = ComponentFoundry(tmp_path)
    return foundry, hub


def approve_reference(hub, source_id="beautifului"):
    reference = hub.add(source_id, "Agent approval button", f"https://{next(s['host'] for s in hub.sources() if s['id'] == source_id)}/",
                        note="Design reference for human-controlled agent approval flow")
    hub.review(reference["id"], decision="approve", actor="human:owner",
               note="Read reference, approval is for inspiration only")
    return reference


def setup_selection(tmp_path, *, usage="prototype", rights=True):
    foundry, hub = make_foundry(tmp_path)
    ref = approve_reference(hub)
    nomination = foundry.nominate(ref["id"], "ApproveButton",
                                 "Accessible approve action and subtle focus animation", usage)
    folder = Path(nomination["path"])
    (folder / "evidence" / "license.txt").write_text(
        "Source page license or permission evidence saved for local human review.\n",
        encoding="utf-8")
    if rights:
        foundry.license(nomination["selection_id"], evidence_file="license.txt", license_id="MIT",
                        reviewer="human:owner", note="I reviewed local evidence and permitted this scope",
                        commercial_use=True, modification=True, redistribution=True)
    return foundry, hub, nomination, folder


def test_approved_shortlist_only_and_deterministic_ranking(tmp_path):
    foundry, hub = make_foundry(tmp_path)
    assert foundry.shortlist("button") == []
    pending = hub.add("beautifului", "Button idea", "https://beautifului.dev/",
                      note="Review not yet complete")
    assert foundry.shortlist("button") == []
    ref = approve_reference(hub, "arc-ui")
    found = foundry.shortlist("button")
    assert [entry["reference_id"] for entry in found] == [ref["id"]]
    assert found[0]["rights"] == "not_cleared"
    assert foundry.shortlist("button") == found
    with pytest.raises(ComponentGateError, match="human approval"):
        foundry.nominate(pending["id"], "Button", "Test approval rule", "prototype")


def test_cannot_select_non_component_source(tmp_path):
    foundry, hub = make_foundry(tmp_path)
    ref = hub.add("shotreel", "Showcase tool", "https://shotreel.app/",
                  note="Video showcase is not an installable UI component")
    hub.review(ref["id"], decision="approve", actor="human:owner",
               note="Reference reviewed for general video inspiration")
    with pytest.raises(ComponentGateError, match="not a selectable"):
        foundry.nominate(ref["id"], "Video", "Design video", "prototype")


def test_nominations_are_deterministic_and_capture_provenance(tmp_path):
    foundry, hub = make_foundry(tmp_path)
    ref = approve_reference(hub)
    initial = foundry.nominate(ref["id"], "ApproveButton", "Agent approval action", "prototype")
    assert initial["status"] == "nominated"
    assert foundry.nominate(ref["id"], "ApproveButton", "Agent approval action", "prototype")["status"] == "existing"
    changed = foundry.nominate(ref["id"], "ApproveButton", "Agent approval action V2", "prototype")
    assert changed["selection_id"] != initial["selection_id"]
    data = json.loads((Path(initial["path"]) / "selection.json").read_text())
    assert data["data"]["reference_sha256"] == ref["sha256"]
    assert data["data"]["source_id"] == "beautifului"
    assert any(e["type"] == "component.selection.nominated" for e in foundry.store.list_events())


def test_license_is_required_for_task_and_visual_qa(tmp_path):
    foundry, _, result, folder = setup_selection(tmp_path, rights=False)
    with pytest.raises(ComponentGateError, match="evidence file"):
        foundry.task(result["selection_id"])
    with pytest.raises(ComponentGateError, match="evidence file"):
        foundry.qa(result["selection_id"], "a.png", "b.png")
    assert not (folder / "codex-task.json").exists()


def test_scope_requires_explicit_rights_for_production(tmp_path):
    foundry, _, selected, folder = setup_selection(tmp_path, usage="production", rights=False)
    with pytest.raises(ComponentGateError, match="Production"):
        foundry.license(selected["selection_id"], evidence_file="license.txt", license_id="MIT",
                        reviewer="human:owner", note="Commercial scope not confirmed",
                        commercial_use=False, modification=True, redistribution=True)
    assert not (folder / "license.json").exists()
    result = foundry.license(selected["selection_id"], evidence_file="license.txt", license_id="MIT",
                             reviewer="human:owner", note="Human reviewed rights evidence for production",
                             commercial_use=True, modification=True, redistribution=True)
    assert result["status"] == "human_attested_not_automatically_verified"
    with pytest.raises(ComponentGateError, match="immutable"):
        foundry.license(selected["selection_id"], evidence_file="license.txt", license_id="MIT",
                        reviewer="human:owner", note="Attempt to overwrite existing rights grant",
                        commercial_use=True, modification=True, redistribution=True)


def test_license_rejects_invalid_actor_and_unapproved_license(tmp_path):
    foundry, _, selected, folder = setup_selection(tmp_path, rights=False)
    for license_id, reviewer in (("UNKNOWN", "human:owner"), ("MIT", "agent:codex")):
        with pytest.raises(ComponentGateError):
            foundry.license(selected["selection_id"], evidence_file="license.txt",
                            license_id=license_id, reviewer=reviewer,
                            note="Cannot create an invalid license review",
                            commercial_use=True, modification=True, redistribution=True)
    assert not (folder / "license.json").exists()


def test_license_evidence_tamper_blocks_handoff_and_qa(tmp_path):
    foundry, _, selected, folder = setup_selection(tmp_path)
    (folder / "evidence" / "license.txt").write_text("Changed evidence text", encoding="utf-8")
    with pytest.raises(ComponentGateError, match="modified"):
        foundry.task(selected["selection_id"])


def test_codex_task_advisory_only_and_idempotent(tmp_path):
    foundry, _, selected, folder = setup_selection(tmp_path)
    result = foundry.task(selected["selection_id"])
    assert result["status"] == "ready_for_manual_codex_handoff"
    task = json.loads((folder / "codex-task.json").read_text())
    assert task["schema"] == "mado.codex-component-task.v1"
    assert task["component"] == "ApproveButton"
    assert task["reference"]["source_id"] == "beautifului"
    assert all("shell" not in item for item in task["expected_outputs"])
    assert foundry.task(selected["selection_id"])["status"] == "existing"
    assert foundry.status(selected["selection_id"])["license"] == "human_attested"


@pytest.mark.parametrize("filter_type", [0, 1, 2, 3, 4])
def test_png_decoder_handles_all_standard_scanline_filters(filter_type):
    data = bytes([255, 10, 25, 255, 0, 240, 80, 125] * 2)
    image = png(2, 2, data, filters=[filter_type, filter_type])
    assert _decode_png(image) == (2, 2, data)


@pytest.mark.parametrize("corruption", [
    b"not PNG", png(1, 1, bytes((1, 2, 3, 4)))[:-9],
    png(1, 1, bytes((1, 2, 3, 4)))[:-1] + b"\x01",
])
def test_png_decoder_rejects_bad_images(corruption):
    with pytest.raises(ComponentGateError):
        _decode_png(corruption)


def test_visual_qa_pixel_delta_and_approval(tmp_path):
    foundry, _, selected, folder = setup_selection(tmp_path, usage="production")
    foundry.task(selected["selection_id"])
    first = bytes((10, 30, 50, 255) * 4)
    second = bytearray(first)
    (folder / "screenshots" / "baseline.png").write_bytes(png(2, 2, first))
    (folder / "screenshots" / "actual.png").write_bytes(png(2, 2, bytes(second)))
    qa = foundry.qa(selected["selection_id"], "baseline.png", "actual.png")
    assert qa["status"] == "passed_pending_human"
    assert qa["changed_fraction"] == 0
    assert qa["mae"] == 0
    assert _decode_png(Path(qa["delta_png"]).read_bytes())[0:2] == (2, 2)
    with pytest.raises(ComponentGateError, match="human"):
        foundry.review(selected["selection_id"], qa["qa_id"], actor="agent:codex",
                       note="Not a real human review", decision="approve")
    approved = foundry.review(selected["selection_id"], qa["qa_id"], actor="human:owner",
                             note="Inspected screenshot, keyboard focus, reduced motion and responsive layout",
                             decision="approve")
    assert approved["status"] == "approved"
    assert foundry.status(selected["selection_id"])["visual_qa"][0]["review"] == "approve"
    with pytest.raises(ComponentGateError, match="immutable"):
        foundry.review(selected["selection_id"], qa["qa_id"], actor="human:owner",
                       note="Attempted second review", decision="reject")


def test_failed_visual_qa_not_approvable_and_tolerances_work(tmp_path):
    foundry, _, selected, folder = setup_selection(tmp_path)
    orig = bytes((0, 0, 0, 255) * 4)
    changed = bytearray(orig)
    changed[0] = 255
    (folder / "screenshots" / "a.png").write_bytes(png(2, 2, orig))
    (folder / "screenshots" / "b.png").write_bytes(png(2, 2, changed))
    failure = foundry.qa(selected["selection_id"], "a.png", "b.png")
    assert failure["status"] == "failed"
    assert failure["changed_fraction"] == 0.25
    assert failure["mae"] > 0
    with pytest.raises(ComponentGateError, match="cannot be approved"):
        foundry.review(selected["selection_id"], failure["qa_id"],
                       actor="human:owner", note="Visual difference rejected", decision="approve")
    assert foundry.review(selected["selection_id"], failure["qa_id"],
                          actor="human:owner", note="The red pixel change is unacceptable",
                          decision="reject")["status"] == "rejected"
    allowed = foundry.qa(selected["selection_id"], "a.png", "b.png",
                         max_changed_fraction=0.3, max_mae=20)
    assert allowed["status"] == "passed_pending_human"
    assert allowed["qa_id"] != failure["qa_id"]


def test_dimensions_mismatch_causes_failure_without_delta(tmp_path):
    foundry, _, selected, folder = setup_selection(tmp_path)
    (folder / "screenshots" / "small.png").write_bytes(png(1, 1, bytes((10, 20, 30, 255))))
    (folder / "screenshots" / "big.png").write_bytes(png(2, 1, bytes((10, 20, 30, 255)) * 2))
    qa = foundry.qa(selected["selection_id"], "small.png", "big.png")
    assert qa["status"] == "failed"
    assert qa["delta_png"] is None
    assert foundry.status(selected["selection_id"])["visual_qa"][0]["machine"] == "failed"


def test_screenshot_tamper_blocks_human_review(tmp_path):
    foundry, _, selected, folder = setup_selection(tmp_path)
    src = png(1, 1, bytes((1, 2, 3, 255)))
    (folder / "screenshots" / "a.png").write_bytes(src)
    (folder / "screenshots" / "b.png").write_bytes(src)
    result = foundry.qa(selected["selection_id"], "a.png", "b.png")
    (folder / "screenshots" / "b.png").write_bytes(png(1, 1, bytes((3, 2, 1, 255))))
    with pytest.raises(ComponentGateError, match="Screenshot modified"):
        foundry.review(selected["selection_id"], result["qa_id"], actor="human:owner",
                       note="Would otherwise approve this QA", decision="approve")


def test_unsafe_path_rejected_without_reading_outside_files(tmp_path):
    foundry, _, selected, folder = setup_selection(tmp_path, rights=False)
    with pytest.raises(ComponentGateError, match="filename"):
        foundry.license(selected["selection_id"], evidence_file="../../secrets.txt",
                        license_id="MIT", reviewer="human:owner", note="Should not read secrets",
                        commercial_use=True, modification=True, redistribution=True)
    foundry.license(selected["selection_id"], evidence_file="license.txt",
                    license_id="MIT", reviewer="human:owner",
                    note="Reviewed for prototype-only UI work",
                    commercial_use=False, modification=False, redistribution=False)
    with pytest.raises(ComponentGateError, match="filename"):
        foundry.qa(selected["selection_id"], "../a.png", "b.png")


def test_selection_record_tamper_detected(tmp_path):
    foundry, _, selected, folder = setup_selection(tmp_path)
    record = json.loads((folder / "selection.json").read_text())
    record["data"]["goal"] = "Malicious goal from a third party"
    (folder / "selection.json").write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ComponentGateError, match="digest mismatch"):
        foundry.task(selected["selection_id"])


def test_cli_shortlist_and_nominate(tmp_path, capsys):
    foundry, hub = make_foundry(tmp_path)
    ref = approve_reference(hub)
    assert main(["--root", str(tmp_path), "shortlist", "--query", "approval"]) == 0
    candidates = json.loads(capsys.readouterr().out)["candidates"]
    assert [x["reference_id"] for x in candidates] == [ref["id"]]
    assert main(["--root", str(tmp_path), "nominate", ref["id"],
                 "--component", "ApproveButton", "--goal", "Approve an agent task",
                 "--usage", "prototype"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert main(["--root", str(tmp_path), "status", result["selection_id"]]) == 0
    assert json.loads(capsys.readouterr().out)["license"] == "missing"



def test_cannot_compare_one_screenshot_with_itself(tmp_path):
    foundry, _, selected, folder = setup_selection(tmp_path)
    (folder / "screenshots" / "same.png").write_bytes(png(1, 1, bytes((1, 2, 3, 255))))
    with pytest.raises(ComponentGateError, match="distinct screenshot"):
        foundry.qa(selected["selection_id"], "same.png", "same.png")


def test_review_record_provenance_mismatch_is_rejected(tmp_path):
    foundry, _, selected, folder = setup_selection(tmp_path)
    blob = png(1, 1, bytes((12, 23, 34, 255)))
    (folder / "screenshots" / "before.png").write_bytes(blob)
    (folder / "screenshots" / "after.png").write_bytes(blob)
    qa = foundry.qa(selected["selection_id"], "before.png", "after.png")
    foundry.review(selected["selection_id"], qa["qa_id"], actor="human:owner",
                   note="Reviewed actual matched screenshots", decision="approve")
    path = folder / "qa" / f"{qa['qa_id']}-review.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["data"]["selection_id"] = "component_" + "0" * 16
    from mado_cockpit.component_foundry import _sha, _canonical
    record["sha256"] = _sha(_canonical(record["data"]))
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ComponentGateError, match="Human review no longer matches"):
        foundry.status(selected["selection_id"])
