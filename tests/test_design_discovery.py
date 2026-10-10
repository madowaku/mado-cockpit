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


def test_thirty_six_sources_and_no_automatic_fetch(tmp_path):
    item = hub(tmp_path)
    assert len(CATALOG) == 36
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


@pytest.mark.parametrize("source_id,expected_host", [
    ("annnimate", "annnimate.com"),
    ("uselayouts", "uselayouts.com"),
    ("arc-ui", "uiarc.dev"),
    ("kobra-systems", "kobra.systems"),
    ("bencho", "bencho.dev"),
    ("hyperiux-vault", "vault.hyperiux.com"),
    ("libraries-dev", "libraries.dev"),
    ("beui", "beui.dev"),
    ("beautifului", "beautifului.dev"),
    ("ui-maxxing", "uimaxx.ing"),
])
def test_component_sources_are_metadata_only(tmp_path, source_id, expected_host):
    item = hub(tmp_path)
    entry = next(source for source in item.sources() if source["id"] == source_id)
    assert entry["host"] == expected_host
    assert entry["mode"] == "manual_link_only"
    assert entry["rights"] == "unverified"
    candidate = item.add(source_id, "UI reference", f"https://{expected_host}/",
                         note="Stored as a research bookmark, no code download")
    assert candidate["status"] == "pending"
    assert not item.context_pack()["approved_references"]


def test_annnimate_source_points_to_user_requested_animation_index(tmp_path):
    item = hub(tmp_path)
    entry = next(source for source in item.sources() if source["id"] == "annnimate")
    assert entry["url"] == "https://annnimate.com/animations"


@pytest.mark.parametrize("legacy_size", [10, 18, 28])
def test_catalog_upgrade_from_every_known_historical_version(tmp_path, legacy_size):
    item = hub(tmp_path)
    old_source = "paper" if legacy_size == 18 else "evilbuttons"
    approved = item.add(old_source, "Historical UI reference",
                        f"https://{next(source['host'] for source in CATALOG if source['id'] == old_source)}/",
                        note="Human-reviewed before the catalog migration")
    item.review(approved["id"], decision="approve", actor="human:owner",
                note="Accepted for link research only")
    snapshot = item.references()
    ledger = item.audit.read_text(encoding="utf-8")
    data = json.loads(item.path.read_text(encoding="utf-8"))
    data["source_catalog_sha256"] = _digest({"sources": CATALOG[:legacy_size]})
    item.path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(DiscoveryError, match="catalog mismatch"):
        item.context_pack()
    assert item.bootstrap()["status"] == "upgraded"
    assert item.bootstrap()["status"] == "existing"
    assert item.references() == snapshot
    assert item.audit.read_text(encoding="utf-8") == ledger
    assert [ref["id"] for ref in item.context_pack()["approved_references"]] == [approved["id"]]
    events = [event for event in item.store.list_events()
              if event["type"] == "design.discovery.catalog_upgraded"]
    assert len(events) == 1
    assert events[0]["subject"]["from_source_count"] == legacy_size
    assert events[0]["subject"]["to_source_count"] == 36


def test_legacy_fingerprint_cannot_claim_future_sources(tmp_path):
    item = hub(tmp_path)
    item.add("beautifului", "Unknown to earlier edition", "https://beautifului.dev/",
             note="New catalog member with old fingerprint")
    data = json.loads(item.path.read_text(encoding="utf-8"))
    data["source_catalog_sha256"] = _digest({"sources": CATALOG[:18]})
    item.path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(DiscoveryError, match="predates catalog version"):
        item.bootstrap()
    assert json.loads(item.path.read_text(encoding="utf-8")) == data


def test_new_library_wrong_domain_is_blocked(tmp_path):
    item = hub(tmp_path)
    with pytest.raises(DiscoveryError, match="URL domain"):
        item.add("hyperiux-vault", "Spoof", "https://vault.hyperiux.com.attacker.test/",
                 note="Must not accept spoofed host")


@pytest.mark.parametrize("source_id,host,expected_category", [
    ("remotion", "remotion.dev", "video"),
    ("motion-dev", "motion.dev", "motion"),
    ("lottiefiles", "lottiefiles.com", "motion-assets"),
    ("rive", "rive.app", "interactive-motion"),
    ("gsap", "gsap.com", "motion"),
    ("threejs", "threejs.org", "3d"),
    ("lucide", "lucide.dev", "icons"),
    ("reactbits", "reactbits.dev", "components"),
])
def test_motion_source_bookmarks_are_metadata_only(tmp_path, source_id, host, expected_category):
    item = hub(tmp_path)
    source = next(source for source in item.sources() if source["id"] == source_id)
    assert source["host"] == host
    assert source["category"] == expected_category
    assert source["mode"] == "manual_link_only"
    assert source["rights"] == "unverified"
    ref = item.add(source_id, "Animation reference", f"https://{host}/",
                   note="Only a bookmark until licensing and explicit human review")
    assert ref["status"] == "pending"
    assert not item.context_pack()["approved_references"]


def test_video_and_animation_queries_and_policy_in_context_pack(tmp_path):
    item = hub(tmp_path)
    assert "remotion" in {ref["id"] for ref in item.sources("video")}
    assert "threejs" in {ref["id"] for ref in item.sources("webgl")}
    assert "lottiefiles" in {ref["id"] for ref in item.sources("dotlottie")}
    assert "lucide" in {ref["id"] for ref in item.sources("svg")}
    ref = item.add("remotion", "My video experiment", "https://remotion.dev/docs",
                   note="Reference for a potential product-video pipeline")
    assert item.context_pack("video")["approved_references"] == []
    item.review(ref["id"], decision="approve", actor="human:owner",
                note="Approved reference-only usage after checking provenance")
    pack = item.context_pack("video")
    assert [record["id"] for record in pack["approved_references"]] == [ref["id"]]
    assert any("code and asset reuse requires" in line for line in pack["instructions"])


def test_old_28_source_registry_with_approved_agent_ui_survives(tmp_path):
    item = hub(tmp_path)
    ref = item.add("beautifului", "AI UI", "https://beautifului.dev/",
                   note="Human approved this agent component reference")
    item.review(ref["id"], decision="approve", actor="human:owner",
                note="Agent UI research only, no copying or publishing")
    original = item.references()
    ledger = item.audit.read_bytes()
    registry = json.loads(item.path.read_text(encoding="utf-8"))
    registry["source_catalog_sha256"] = _digest({"sources": CATALOG[:28]})
    item.path.write_text(json.dumps(registry), encoding="utf-8")
    assert item.bootstrap()["status"] == "upgraded"
    assert item.references() == original
    assert item.audit.read_bytes() == ledger
    assert [entry["id"] for entry in item.context_pack()["approved_references"]] == [ref["id"]]


def test_old_28_source_fingerprint_cannot_contain_new_motion_reference(tmp_path):
    item = hub(tmp_path)
    item.add("remotion", "Impossible old motion reference", "https://remotion.dev/",
             note="New source cannot have existed in the old registry")
    registry = json.loads(item.path.read_text(encoding="utf-8"))
    registry["source_catalog_sha256"] = _digest({"sources": CATALOG[:28]})
    item.path.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(DiscoveryError, match="predates catalog version"):
        item.bootstrap()
    assert json.loads(item.path.read_text(encoding="utf-8")) == registry


def test_motion_source_domain_spoof_is_rejected(tmp_path):
    item = hub(tmp_path)
    with pytest.raises(DiscoveryError, match="URL domain"):
        item.add("remotion", "Spoof", "https://remotion.dev.evil.example/",
                 note="Do not accept domain lookalikes")
