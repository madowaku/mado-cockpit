"""Contract and trust-boundary tests for Motion Prompt pinned vocabulary intake."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from mado_cockpit.design_discovery import DesignDiscoveryHub
from mado_cockpit.models import Project
from mado_cockpit.motion_foundry import MotionFoundry
from mado_cockpit.motion_prompt_bridge import (
    MotionPromptBridge, MotionPromptError, UPSTREAM_REPO, UPSTREAM_SITE,
    main, validate_catalog,
)
from mado_cockpit.store import CockpitStore


def catalog():
    packs = [{
        "pack": "motion", "order": 1, "title": {"en": "Motion", "ja": "動き"},
        "categories": [{"slug": "entrances-text", "en": "Entrances", "ja": "登場"}],
        "count": 2, "first": "001", "last": "002",
        "width": 539, "height": 208, "cycle": 4.7, "langs": ["en", "ja"],
    }]
    elements = []
    for i, (slug, name, meaning, tags) in enumerate([
        ("pop-in", "Pop-in", "Pops into view", ["spring", "pop", "2.5d"]),
        ("stagger", "Stagger", "Items enter sequentially", ["stagger", "camera move"]),
    ], 1):
        elements.append({
            "id": f"{i:03d}", "no": f"{i:02d}", "pack": "motion",
            "slug": slug, "category": "entrances-text", "width": 539,
            "height": 208, "cycle": 4.7,
            "name": {"en": name, "ja": f"日本語{i}"},
            "meaning": {"en": meaning, "ja": f"説明{i}"},
            "ask": {"en": f"Please {slug} for 0.4 seconds.", "ja": f"0.4秒で動かす{i}"},
            "summary": {"en": meaning, "ja": f"見本{i}"},
            "spec": {"en": ["Start 0.4 s; ease out"], "ja": ["0.4秒で開始"]},
            "use": {"en": "Small UI elements", "ja": "UIに使う"},
            "tags": tags,
            "code": "<script>evil upstream field is never retained</script>",
        })
    return {"version": "1.fixture", "site": UPSTREAM_SITE, "repo": UPSTREAM_REPO,
            "packs": packs, "count": 2, "elements": elements}


def init(root: Path):
    CockpitStore(root).init(Project(id="motion-prompt-test", name="Motion Prompt", root=str(root)))
    DesignDiscoveryHub(root).bootstrap()
    return MotionPromptBridge(root)


def write_catalog(root: Path, payload):
    file = root / "upstream-catalog.json"
    data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    file.write_bytes(data)
    return file, hashlib.sha256(data).hexdigest()


def intake(bridge, root):
    file, digest = write_catalog(root, catalog())
    return bridge.intake(file, expected_sha256=digest)


def test_pinned_snapshot_get_search_and_idempotency(tmp_path):
    bridge = init(tmp_path)
    file, sha = write_catalog(tmp_path, catalog())
    first = bridge.intake(file, expected_sha256=sha)
    assert first["status"] == "intaken"
    assert bridge.intake(file, expected_sha256=sha)["status"] == "existing"
    assert bridge.verify()["count"] == 2
    assert bridge.verify()["upstream_sha256"] == sha
    item = bridge.get("#001")
    assert item["id"] == "001"
    assert item["demo_url"] == UPSTREAM_SITE + "#001"
    assert item["spec"]["ja"] == ["0.4秒で開始"]
    assert "code" not in item
    assert len(bridge.search("spring")) == 1
    assert [e["id"] for e in bridge.search("日本語")] == ["001", "002"]
    assert len(bridge.search(pack="motion")) == 2
    assert len([e for e in bridge.store.list_events()
                if e["type"] == "motion_prompt.catalog.intaken"]) == 1


@pytest.mark.parametrize("mutation", [
    lambda c: c.update(site="https://evil.example/"),
    lambda c: c.update(count=3),
    lambda c: c["elements"][1].update(id="001"),
    lambda c: c["elements"][0].update(category="missing"),
    lambda c: c["elements"][0].update(cycle=6.4),
    lambda c: c["packs"][0].update(last="199"),
    lambda c: c["elements"][0].update(spec={"en": []}),
    lambda c: c["elements"][0].update(tags=["\x00bad"]),
])
def test_catalog_rejects_wrong_identity_or_shape(mutation):
    payload = catalog()
    mutation(payload)
    with pytest.raises(MotionPromptError):
        validate_catalog(payload)


def test_catalog_sha_required_and_snapshot_immutable(tmp_path):
    bridge = init(tmp_path)
    file, sha = write_catalog(tmp_path, catalog())
    with pytest.raises(MotionPromptError, match="SHA-256 does not match"):
        bridge.intake(file, expected_sha256="a" * 64)
    assert not bridge.snapshot.exists()
    intake(bridge, tmp_path)
    modified = catalog()
    modified["elements"][0]["name"]["en"] = "Other"
    file, second = write_catalog(tmp_path, modified)
    with pytest.raises(MotionPromptError, match="refuse silent replacement"):
        bridge.intake(file, expected_sha256=second)
    assert bridge.verify()["upstream_sha256"] == sha


def test_snapshot_tampering_fails_closed(tmp_path):
    bridge = init(tmp_path)
    intake(bridge, tmp_path)
    data = json.loads(bridge.snapshot.read_text())
    data["data"]["elements"][0]["spec"]["en"] = ["pretend this is reviewed"]
    bridge.snapshot.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(MotionPromptError, match="integrity"):
        bridge.search("pop")


def test_symlink_source_rejected(tmp_path):
    bridge = init(tmp_path)
    source, digest = write_catalog(tmp_path, catalog())
    alias = tmp_path / "catalog-link.json"
    alias.symlink_to(source)
    with pytest.raises(MotionPromptError, match="symlinked"):
        bridge.intake(alias, expected_sha256=digest)


def test_handoff_links_existing_verified_motion_foundry_without_modifying_it(tmp_path):
    bridge = init(tmp_path)
    intake(bridge, tmp_path)
    brief = {
        "schema": "mado.motion-brief.v1", "title": "Launch",
        "format": "landscape", "background": "#001122",
        "foreground": "#ffffff", "accent": "#11ccaa",
        "scenes": [{"heading": "Start", "body": "Hello", "duration_frames": 90}],
    }
    result = MotionFoundry(tmp_path).plan(brief)
    folder = Path(result["path"])
    before = (folder / "codex-task.json").read_bytes()
    task = bridge.handoff(folder, scene_index=0, element_ids=["#001", "002"])
    assert task["status"] == "created"
    assert task["selected_ids"] == ["001", "002"]
    generated = json.loads(Path(task["path"]).read_text())
    assert generated["schema"] == "mado.motion-prompt-handoff.v1"
    assert generated["scene_duration_frames"] == 90
    assert generated["license_notice"].startswith("Motion Prompt")
    assert generated["render_authorized"] is False
    assert generated["visual_review"] == "pending"
    assert generated["selected_motions"][0]["demo_url"].endswith("#001")
    assert "source code" not in generated
    assert (folder / "codex-task.json").read_bytes() == before
    assert bridge.handoff(folder, scene_index=0, element_ids=["#001", "002"])["status"] == "existing"
    assert MotionFoundry(tmp_path).verify(folder)["status"] == "source_verified"


def test_handoff_rejects_bad_target_duplicate_and_tamper(tmp_path):
    bridge = init(tmp_path)
    intake(bridge, tmp_path)
    with pytest.raises(MotionPromptError, match="Duplicate"):
        bridge.handoff(tmp_path, scene_index=0, element_ids=["001", "#001"])
    with pytest.raises(MotionPromptError, match="not verified"):
        bridge.handoff(tmp_path, scene_index=0, element_ids=["001"])
    with pytest.raises(MotionPromptError, match="Unknown"):
        bridge.handoff(tmp_path, scene_index=0, element_ids=["999"])


def test_cli_intake_search_get_verify(tmp_path, capsys):
    init(tmp_path)
    file, sha = write_catalog(tmp_path, catalog())
    assert main(["--root", str(tmp_path), "intake", "--catalog", str(file),
                 "--expected-sha256", sha]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "intaken"
    assert main(["--root", str(tmp_path), "search", "--query", "stagger"]) == 0
    assert len(json.loads(capsys.readouterr().out)["elements"]) == 1
    assert main(["--root", str(tmp_path), "get", "#002"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "002"
    assert main(["--root", str(tmp_path), "verify"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "snapshot_verified"
