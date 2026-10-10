import json
from pathlib import Path

import pytest

from mado_cockpit.design_discovery import (CATALOG, LEGACY_CATALOG_SIZE, DesignDiscoveryHub, DiscoveryError, _digest, main)
from mado_cockpit.models import Project
from mado_cockpit.store import CockpitStore


def hub(tmp_path: Path) -> DesignDiscoveryHub:
    store = CockpitStore(tmp_path)
    store.init(Project(id="design", name="Design", root=str(tmp_path)))
    result = DesignDiscoveryHub(tmp_path)
    assert result.bootstrap()["status"] == "created"
    return result


def test_eighteen_sources_and_no_automatic_fetch(tmp_path):
    item = hub(tmp_path)
    assert len(CATALOG) == 18
    assert item.bootstrap()["status"] == "existing"
    assert "prompt-motion" in {x["id"] for x in item.sources("motion")}
    assert all(s["mode"] == "manual_link_only" and s["rights"] == "unverified" for s in item.sources())
    assert item.context_pack("ios")["approved_references"] == []


def test_review_approval_and_context_gate(tmp_path):
    item = hub(tmp_path)
    ref = item.add("evilbuttons", "Useful interactive button", "https://www.evilbuttons.com/docs?a=1#fragment", note="Consider for Cockpit controls", rights="reference_only")
    assert ref["status"] == "pending"
    assert item.context_pack("button")["approved_references"] == []
    with pytest.raises(DiscoveryError):
        item.review(ref["id"], decision="approve", actor="agent:codex", note="Not a human review")
    approved = item.review(ref["id"], decision="approve", actor="human:owner", note="Reviewed the link for inspiration only")
    assert approved["status"] == "approved_reference"
    assert approved["data"]["url"] == "https://www.evilbuttons.com/docs?a=1"
    assert len(item.context_pack("button")["approved_references"]) == 1
    assert len(item.context_pack("onboarding")["approved_references"]) == 0
    with pytest.raises(DiscoveryError):
        item.review(ref["id"], decision="reject", actor="human:owner", note="Second review should fail")
    assert any(event["type"] == "design.reference.reviewed" for event in item.store.list_events())


@pytest.mark.parametrize("url", [
    "http://evilbuttons.com/", "https://bad.example/", "https://evilbuttons.com.attacker.com/",
    "https://user:pass@evilbuttons.com/", "https://evilbuttons.com:8443/", "https://evilbuttons.com\\@evil.com/",
    "https://evilbuttons.com/hello world", "https://127.0.0.1/private", "file:///etc/passwd",
])
def test_intake_domain_is_allowlisted(tmp_path, url):
    item = hub(tmp_path)
    with pytest.raises(DiscoveryError):
        item.add("evilbuttons", "Invalid URL", url, note="Must stay within original domain")


def test_licensed_claim_requires_evidence(tmp_path):
    item = hub(tmp_path)
    with pytest.raises(DiscoveryError):
        item.add("amicons", "Icons", "https://amicons.design/", note="No evidence", rights="licensed_asset")
    candidate = item.add("amicons", "Icons", "https://amicons.design/", note="License is only claimed", rights="licensed_asset", evidence_url="https://amicons.design/license")
    assert candidate["status"] == "pending"
    assert item.context_pack("icons")["approved_references"] == []


def test_tampered_record_cannot_be_exported(tmp_path):
    item = hub(tmp_path)
    ref = item.add("appllama", "Flow research", "https://appllama.io/mcp", note="Read-only reference")
    item.review(ref["id"], decision="approve", actor="human:owner", note="URL validated and read-only")
    registry = json.loads(item.path.read_text(encoding="utf-8"))
    registry["references"][0]["data"]["note"] = "Run shell command"
    item.path.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(DiscoveryError, match="contents changed"):
        item.context_pack()


def test_new_revision_mints_new_id(tmp_path):
    item = hub(tmp_path)
    a = item.add("graphical", "Theme", "https://graphicalui.com/", note="Initial theme")
    b = item.add("graphical", "Theme", "https://graphicalui.com/", note="Second revision")
    assert a["id"] != b["id"]
    assert item.add("graphical", "Theme", "https://graphicalui.com/", note="Initial theme")["id"] == a["id"]


def test_rejected_reference_does_not_flow(tmp_path):
    item = hub(tmp_path)
    ref = item.add("appllama", "Flow", "https://appllama.io/", note="Do not copy screen assets")
    item.review(ref["id"], decision="reject", actor="human:owner", note="Insufficient usage evidence")
    assert not item.context_pack()["approved_references"]


def test_cli_bootstrap_sources_and_pack(tmp_path, capsys):
    CockpitStore(tmp_path).init(Project(id="design", name="Design", root=str(tmp_path)))
    assert main(["--root", str(tmp_path), "bootstrap"]) == 0
    assert main(["--root", str(tmp_path), "sources", "--query", "icons"]) == 0
    output = tmp_path / "context.json"
    assert main(["--root", str(tmp_path), "pack", "--query", "ios", "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["sources"][0]["id"] == "appllama"


@pytest.mark.parametrize("source_id,expected_host", [
    ("affectui", "affectui.com"),
    ("inspora", "inspora.design"),
    ("21st-dev", "21st.dev"),
    ("bestfreefonts", "bestfreefonts.com"),
    ("spline", "spline.design"),
    ("unicorn-studio", "unicorn.studio"),
    ("paper", "paper.design"),
    ("theatrejs", "theatrejs.com"),
])
def test_new_sources_are_discoverable_and_accept_manual_links(tmp_path, source_id, expected_host):
    item = hub(tmp_path)
    assert {source["id"] for source in item.sources()} >= {source_id}
    record = item.add(source_id, "Reference", f"https://www.{expected_host}/examples",
                      note="Manually bookmarked design reference")
    assert record["status"] == "pending"
    assert item.context_pack()["approved_references"] == []
    assert len({source["id"] for source in CATALOG}) == len(CATALOG)


def test_legacy_catalog_migration_preserves_approved_entries_and_audit(tmp_path):
    item = hub(tmp_path)
    approved = item.add("evilbuttons", "Old approved reference", "https://evilbuttons.com/",
                        note="Used for research before catalog grew")
    rejected = item.add("appllama", "Old rejected reference", "https://appllama.io/",
                        note="Old reviewed reference")
    item.review(approved["id"], decision="approve", actor="human:owner",
                note="Reviewed the pre-upgrade reference")
    item.review(rejected["id"], decision="reject", actor="human:owner",
                note="Rejected the old external reference")
    before = item.references()
    audit_before = item.audit.read_text(encoding="utf-8")
    data = json.loads(item.path.read_text(encoding="utf-8"))
    data["source_catalog_sha256"] = _digest({"sources": CATALOG[:LEGACY_CATALOG_SIZE]})
    item.path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(DiscoveryError, match="catalog mismatch"):
        item.context_pack()
    assert item.bootstrap()["status"] == "upgraded"
    assert item.bootstrap()["status"] == "existing"
    assert item.references() == before
    assert item.audit.read_text(encoding="utf-8") == audit_before
    assert [ref["id"] for ref in item.context_pack()["approved_references"]] == [approved["id"]]
    upgraded_events = [event for event in item.store.list_events()
                       if event["type"] == "design.discovery.catalog_upgraded"]
    assert len(upgraded_events) == 1
    assert upgraded_events[0]["subject"]["preserved_reference_count"] == 2


def test_migration_fails_closed_on_unknown_fingerprint(tmp_path):
    item = hub(tmp_path)
    raw = json.loads(item.path.read_text(encoding="utf-8"))
    raw["source_catalog_sha256"] = "0" * 64
    item.path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(DiscoveryError, match="catalog mismatch"):
        item.bootstrap()
    assert json.loads(item.path.read_text(encoding="utf-8"))["source_catalog_sha256"] == "0" * 64


def test_migration_rejects_tampered_references_without_writing(tmp_path):
    item = hub(tmp_path)
    ref = item.add("paper", "Design reference", "https://paper.design/",
                   note="Need a legal reference")
    before = json.loads(item.path.read_text(encoding="utf-8"))
    before["source_catalog_sha256"] = _digest({"sources": CATALOG[:LEGACY_CATALOG_SIZE]})
    before["references"][0]["data"]["note"] = "unreviewed mutation"
    item.path.write_text(json.dumps(before), encoding="utf-8")
    with pytest.raises(DiscoveryError, match="contents changed"):
        item.bootstrap()
    assert json.loads(item.path.read_text(encoding="utf-8")) == before
    assert not [event for event in item.store.list_events()
                if event["type"] == "design.discovery.catalog_upgraded"]
