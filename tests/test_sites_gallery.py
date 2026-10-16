from __future__ import annotations

import copy
import json

import pytest

from mado_cockpit.sites_gallery import source_url, validate_gallery
from mado_cockpit.sites_portal import SITE_ROOT, SiteCatalogError, build_site


@pytest.fixture
def data():
    return (
        json.loads((SITE_ROOT / "gallery.json").read_text(encoding="utf-8")),
        json.loads((SITE_ROOT / "catalog.json").read_text(encoding="utf-8")),
    )


def test_reviewed_gallery_keeps_all_publication_gates_closed(data):
    gallery, catalog = data
    assert validate_gallery(gallery, catalog) is gallery
    assert len(gallery["items"]) == 4
    assert {x["project_id"] for x in gallery["items"]} == {"mado-asset-foundry", "app-gardenium"}
    assert all(not x["review"]["visual_inspected"] and not x["review"]["reuse_approved"]
               for x in gallery["items"])
    assert all("chatgpt.site" not in source_url(x["source"]) for x in gallery["items"])


@pytest.mark.parametrize("change,expected", [
    ({"project_id": "neon-brainstorm"}, "not in the public catalog"),
    ({"kind": "live_site_proof"}, "Unreviewed gallery asset kind"),
    ({"featured": "yes"}, "featured must be boolean"),
    ({"id": "../outside"}, "invalid gallery ID"),
])
def test_invalid_gallery_entry_is_rejected(data, change, expected):
    gallery, catalog = copy.deepcopy(data)
    gallery["items"][0].update(change)
    with pytest.raises(SiteCatalogError, match=expected):
        validate_gallery(gallery, catalog)


@pytest.mark.parametrize("field,bad", [
    ("repository", "madowaku/search-forest"),
    ("commit", "main"),
    ("path", "../private.png"),
    ("path", "marketing/private.png"),
    ("blob_sha", "0" * 40),
    ("size_bytes", -1),
])
def test_unreviewed_and_unpinned_sources_fail(data, field, bad):
    gallery, catalog = copy.deepcopy(data)
    gallery["items"][0]["source"][field] = bad
    with pytest.raises(SiteCatalogError):
        validate_gallery(gallery, catalog)


def test_only_one_featured_per_project(data):
    gallery, catalog = copy.deepcopy(data)
    gallery["items"][1]["featured"] = True
    with pytest.raises(SiteCatalogError, match="Only one featured"):
        validate_gallery(gallery, catalog)


def test_source_attribution_is_immutable(data):
    gallery, _ = data
    result = source_url(gallery["items"][0]["source"])
    assert result.startswith("https://raw.githubusercontent.com/madowaku/mado-asset-foundry/")
    assert "/main/" not in result
    assert result.endswith("/e2e/goldens/desktop-reviewed.png")


def test_build_receipt_explicitly_pending_gallery_visual_review(tmp_path):
    out = tmp_path / "portal"
    receipt = build_site(output=out)
    assert receipt["gallery"]["asset_count"] == 4
    assert receipt["gallery"]["visual_inspected"] is False
    assert receipt["gallery"]["reuse_approved"] is False
    assert receipt["deployment_verified"] is False
    assert (out / "gallery.json").is_file()


def test_fail_closed_gallery_changes_before_writing(tmp_path, data, monkeypatch):
    gallery, _ = data
    gallery["items"][0]["source"]["repository"] = "madowaku/search-forest"
    invalid = tmp_path / "gallery.json"
    invalid.write_text(json.dumps(gallery), encoding="utf-8")
    from mado_cockpit import sites_portal
    monkeypatch.setattr(sites_portal, "GALLERY_PATH", invalid)
    out = tmp_path / "output"
    with pytest.raises(SiteCatalogError):
        build_site(output=out)
    assert not out.exists()


def test_rejects_secret_looking_fields(data):
    gallery, catalog = copy.deepcopy(data)
    gallery["items"][0]["source"]["access_token"] = "redacted"
    with pytest.raises(SiteCatalogError, match="Sensitive"):
        validate_gallery(gallery, catalog)
