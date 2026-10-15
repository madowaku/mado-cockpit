import json
from pathlib import Path

import pytest

from mado_cockpit.component_foundry import ComponentFoundry
from mado_cockpit.design_discovery import DesignDiscoveryHub, CATALOG, _digest
from mado_cockpit.lucian_bridge import LucianBridge, LucianError
from mado_cockpit.models import Project
from mado_cockpit.store import CockpitStore

COMMIT = "42396145b375a17712fd738ca0e1d977556c0b73"


def setup(tmp_path):
    CockpitStore(tmp_path).init(Project(id="lucian", name="Lucian", root=str(tmp_path)))
    hub = DesignDiscoveryHub(tmp_path)
    hub.bootstrap()
    return LucianBridge(tmp_path), hub


def upstream(tmp_path):
    idx = {"api": 1, "name": "Lucian UX/UI Prompt", "count": 200,
           "languages": ["en", "ko"], "license": "MIT (c) 2026 Seokwoooo",
           "version": "test", "categories": [{"slug": "buttons"}]}
    index = tmp_path / "index.json"
    catalog = tmp_path / "catalog.tsv"
    index.write_text(json.dumps(idx), encoding="utf-8")
    lines = ["# lucian-uxui catalog · api v1",
             "id\tcat\tcategory\ttitle\ttags\tshape\thash\tsummary"]
    lines.extend(f"{n:03}\tbuttons\tButtons\tButton {n}\tbutton click\t square\t123456789a\tAccessible action {n}" for n in range(1, 201))
    catalog.write_text("\n".join(lines), encoding="utf-8")
    return index, catalog


def test_intake_search_and_immutability(tmp_path):
    bridge, _ = setup(tmp_path)
    index, catalog = upstream(tmp_path)
    assert bridge.intake(index, catalog, commit=COMMIT)["count"] == 200
    assert bridge.intake(index, catalog, commit=COMMIT)["status"] == "existing"
    found = bridge.search("button 180")
    assert [r["id"] for r in found] == ["180"]
    assert found[0]["demo"].endswith("#180")
    assert len(bridge.search(category="buttons")) == 200
    catalog.write_text(catalog.read_text().replace("Button 180", "Modified 180"), encoding="utf-8")
    with pytest.raises(LucianError, match="never silently replace"):
        bridge.intake(index, catalog, commit=COMMIT)
    wrapper = json.loads(bridge.snapshot.read_text())
    wrapper["data"]["elements"][0]["title"] = "tampered"
    bridge.snapshot.write_text(json.dumps(wrapper), encoding="utf-8")
    with pytest.raises(LucianError, match="digest mismatch"):
        bridge.search()


def test_bad_input_fails_closed(tmp_path):
    bridge, _ = setup(tmp_path)
    index, catalog = upstream(tmp_path)
    with pytest.raises(LucianError, match="40-character"):
        bridge.intake(index, catalog, commit="main")
    catalog.write_text(catalog.read_text().replace("Button 180", "Button 179"), encoding="utf-8")
    # Duplicate titles are acceptable, duplicate IDs are not.
    assert bridge.intake(index, catalog, commit=COMMIT)["count"] == 200


def test_catalog_migration_43_to_44_preserves_reviews(tmp_path):
    bridge, hub = setup(tmp_path)
    ref = hub.add("reactbits", "Earlier approved", "https://reactbits.dev/",
                  note="Reviewed reference before Lucian addition")
    hub.review(ref["id"], decision="approve", actor="human:owner",
               note="Reference-only human approval remains intact")
    before = hub.references()
    old = json.loads(hub.path.read_text())
    old["source_catalog_sha256"] = _digest({"sources": CATALOG[:43]})
    hub.path.write_text(json.dumps(old), encoding="utf-8")
    assert hub.bootstrap()["status"] == "upgraded"
    assert hub.references() == before
    assert len(hub.sources()) == len(CATALOG)
    assert hub.sources("lucian")[0]["id"] == "lucian-uxui"


def test_handoff_requires_reference_selection_and_license(tmp_path):
    bridge, hub = setup(tmp_path)
    index, catalog = upstream(tmp_path)
    bridge.intake(index, catalog, commit=COMMIT)
    ref = hub.add("lucian-uxui", "Approval signoff", "https://lucianlabs.dev/uxui-prompt/#180",
                  note="Review this single upstream component for Cockpit")
    element = tmp_path / "180.txt"
    tokens = tmp_path / "tokens.css"
    element.write_text("<!-- Lucian UX/UI Prompt #180 · MIT License (c) 2026 Seokwoooo -->\n"
                       "<!-- ID: 180 · Category: Workflow -->\n<style>.u180{color:var(--ux-ink)}</style>\n"
                       "<div class='u180'>Test</div><script>void 0</script>", encoding="utf-8")
    tokens.write_text(":root {--ux-ink:#111;}", encoding="utf-8")
    with pytest.raises(LucianError, match="human approval"):
        bridge.handoff("180", reference_id=ref["id"], selection_id="component_0000000000000000",
                       target="src/Approval.tsx", element_file=element, tokens_file=tokens)
    hub.review(ref["id"], decision="approve", actor="human:owner",
               note="Reviewed official demo URL as reference only")
    foundry = ComponentFoundry(tmp_path)
    selection = foundry.nominate(ref["id"], "ApprovalSignoff", "Approval UI", "prototype")
    sid = selection["selection_id"]
    with pytest.raises(Exception, match="evidence file"):
        bridge.handoff("180", reference_id=ref["id"], selection_id=sid,
                       target="src/Approval.tsx", element_file=element, tokens_file=tokens)
    folder = Path(selection["path"])
    (folder / "evidence" / "license.txt").write_text(
        "MIT License (c) 2026 Seokwoooo. Permission to use, copy, modify and distribute.", encoding="utf-8")
    foundry.license(sid, evidence_file="license.txt", license_id="MIT", reviewer="human:owner",
                    note="Reviewed rights for this example component", commercial_use=True,
                    modification=True, redistribution=True)
    result = bridge.handoff("180", reference_id=ref["id"], selection_id=sid,
                            target="src/Approval.tsx", element_file=element, tokens_file=tokens)
    assert result["status"] == "created"
    assert bridge.handoff("180", reference_id=ref["id"], selection_id=sid,
                          target="src/Approval.tsx", element_file=element, tokens_file=tokens)["status"] == "existing"
    task = json.loads(Path(result["path"]).read_text())
    assert task["source_id"] == "lucian-uxui"
    assert task["license_sha256"]
    assert task["status"] == "ready_for_manual_codex_handoff"
    with pytest.raises(LucianError, match="relative project path"):
        bridge.handoff("180", reference_id=ref["id"], selection_id=sid,
                       target="../evil.tsx", element_file=element, tokens_file=tokens)
