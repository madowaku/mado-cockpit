from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from mado_cockpit.sites_portal import (
    ASSETS, ROOT, SITE_ROOT, SiteCatalogError, build_site, validate_catalog,
)


@pytest.fixture
def catalog():
    return json.loads((SITE_ROOT / "catalog.json").read_text(encoding="utf-8"))


def test_first_party_public_catalog_is_valid(catalog):
    assert len(validate_catalog(catalog)["projects"]) == 12
    assert all(p["publication"]["state"] == "source_only" for p in catalog["projects"])


@pytest.mark.parametrize("repo", ["neon-brainstorm", "search-forest", "private-repo"])
def test_private_or_unreviewed_repo_never_appears(catalog, repo):
    entry = catalog["projects"][0]
    entry["id"] = repo
    entry["repository"] = f"https://github.com/madowaku/{repo}"
    with pytest.raises(SiteCatalogError, match="Unreviewed or private"):
        validate_catalog(catalog)


def test_reject_unverified_publication_claim(catalog):
    pub = catalog["projects"][0]["publication"]
    pub["state"] = "published_verified"
    pub["url"] = "https://example.org/"
    with pytest.raises(SiteCatalogError):
        validate_catalog(catalog)


def test_verified_publication_requires_review_and_public_audience(catalog):
    pub = catalog["projects"][0]["publication"]
    pub.update({
        "state": "published_verified",
        "url": "https://example.org/",
        "evidence_url": "https://github.com/madowaku/mado-cockpit/issues/1",
        "audience": "public",
        "verified_on": "2026-10-16",
    })
    validate_catalog(catalog)
    pub["audience"] = "owner_only"
    with pytest.raises(SiteCatalogError, match="public audience"):
        validate_catalog(catalog)


@pytest.mark.parametrize("url", [
    "http://example.org/", "https://localhost:8000/",
    "https://user:pass@example.org/", "javascript:alert(1)",
])
def test_reject_unsafe_publication_urls(catalog, url):
    pub = catalog["projects"][0]["publication"]
    pub.update({
        "state": "published_verified", "url": url,
        "evidence_url": "https://github.com/madowaku/mado-cockpit/issues/1",
        "audience": "public", "verified_on": "2026-10-16",
    })
    with pytest.raises(SiteCatalogError):
        validate_catalog(catalog)


def test_reject_sensitive_metadata_and_duplicate_ids(catalog):
    catalog["projects"][0]["api_key"] = "should-not-leak"
    with pytest.raises(SiteCatalogError, match="Sensitive"):
        validate_catalog(catalog)
    del catalog["projects"][0]["api_key"]
    catalog["projects"][1] = copy.deepcopy(catalog["projects"][0])
    with pytest.raises(SiteCatalogError, match="Duplicate"):
        validate_catalog(catalog)


def test_build_is_static_review_only_and_content_addressed(tmp_path, catalog):
    destination = tmp_path / "portal"
    receipt = build_site(output=destination)
    assert receipt["release_state"] == "review_only"
    assert receipt["deployment_verified"] is False
    assert receipt["sites_deployment_url"] is None
    assert receipt["project_count"] == 12
    assert receipt["verified_site_count"] == 0
    assert set(receipt["sha256"]) == set(ASSETS)
    for name in ASSETS:
        assert (destination / name).is_file()
        assert receipt["sha256"][name] == hashlib.sha256((destination / name).read_bytes()).hexdigest()
    assert json.loads((destination / "catalog.json").read_text()) == catalog
    with pytest.raises(SiteCatalogError, match="non-empty"):
        build_site(output=destination)


def test_build_fails_closed_for_bad_catalog(tmp_path, catalog):
    catalog["projects"][0]["publication"]["url"] = "https://unverified.example/"
    fake = tmp_path / "catalog.json"
    fake.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(SiteCatalogError, match="Unverified"):
        build_site(catalog_path=fake, output=tmp_path / "dist")
    assert not (tmp_path / "dist").exists()


def test_build_source_path_protected():
    with pytest.raises(SiteCatalogError, match="source directory"):
        build_site(output=SITE_ROOT)
