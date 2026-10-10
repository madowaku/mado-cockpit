import json
from pathlib import Path

import pytest

from mado_cockpit.design_discovery import CATALOG, DesignDiscoveryHub, DiscoveryError, main
from mado_cockpit.models import Project
from mado_cockpit.store import CockpitStore


def hub(tmp_path: Path) -> DesignDiscoveryHub:
    store = CockpitStore(tmp_path)
    store.init(Project(id="design", name="Design", root=str(tmp_path)))
    result = DesignDiscoveryHub(tmp_path)
    assert result.bootstrap()["status"] == "created"
    return result


def test_ten_sources_and_no_automatic_fetch(tmp_path):
    item = hub(tmp_path)
    assert len(CATALOG) == 10
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
