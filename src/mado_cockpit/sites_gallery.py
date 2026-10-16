"""MCC-M2.8.2: deterministic, fail-closed screenshot source manifest.

A public GitHub image path is NOT proof of pixel review, licensing, a running
application or a published Site. This gate checks source attribution and
declared reviewer states; no remote image bytes are downloaded by build.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import PurePosixPath
from typing import Any

from .sites_portal import SiteCatalogError, _reject_sensitive_keys, _text

SCHEMA = "mado.sites-gallery.v1"
GALLERY_KINDS = {"browser_golden", "marketing_asset"}
# Pinned commits and Git blob IDs located from public GitHub trees, 2026-10-16.
# A different commit/path/blob requires a new, human-reviewed code change.
REVIEWED_SOURCES = frozenset({
    ("madowaku/mado-asset-foundry", "8d2558928dbf66744d12e937d6670f5ed2e4eacb", "e2e/goldens/desktop-reviewed.png", "efc0e73cae343856f29fdfeeb471991a5cf8fa43"),
    ("madowaku/mado-asset-foundry", "8d2558928dbf66744d12e937d6670f5ed2e4eacb", "e2e/goldens/desktop-gallery-pending.png", "67ed106a5039affc821b9e72673c9ead5d4e1506"),
    ("madowaku/app-gardenium", "6c3c3d5abacd141b9cc6fed8778223e8f5f11be2", "marketing/beta-launch/assets/01-home.png", "c6b0e6f8ac70298b1bdef10f0d3fc869a8061c9f"),
    ("madowaku/app-gardenium", "6c3c3d5abacd141b9cc6fed8778223e8f5f11be2", "marketing/beta-launch/assets/04-greenhouse.png", "959d3c4174e6c41171ed8bc69f88b7452a416570"),
})
ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
SHA = re.compile(r"^[0-9a-f]{40}$")


def source_url(source: dict[str, Any]) -> str:
    repo = source["repository"]
    commit = source["commit"]
    path = source["path"]
    return f"https://raw.githubusercontent.com/{repo}/{commit}/{path}"


def validate_gallery(gallery: Any, catalog: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(gallery, dict) or gallery.get("schema") != SCHEMA:
        raise SiteCatalogError("Unexpected gallery schema")
    if gallery.get("visibility") != "public_repository_sources":
        raise SiteCatalogError("Gallery must use reviewed public sources")
    if gallery.get("visual_review") != "pending" or gallery.get("deployment_verified") is not False:
        raise SiteCatalogError("Source discovery cannot certify visual review or deployment")
    try:
        date.fromisoformat(_text(gallery.get("reviewed_on"), "reviewed_on", 10))
    except ValueError as exc:
        raise SiteCatalogError("Invalid gallery review date") from exc
    _reject_sensitive_keys(gallery)
    items = gallery.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 48:
        raise SiteCatalogError("Expected between 1 and 48 gallery entries")
    allowed_projects = {p["id"] for p in catalog["projects"]}
    seen: set[str] = set()
    featured: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise SiteCatalogError("Gallery entry must be an object")
        item_id = _text(item.get("id"), "id", 64)
        if not ID.fullmatch(item_id) or item_id in seen:
            raise SiteCatalogError("Duplicate or invalid gallery ID")
        seen.add(item_id)
        project = _text(item.get("project_id"), "project_id", 70)
        if project not in allowed_projects:
            raise SiteCatalogError("Gallery project is not in the public catalog")
        for field in ("title", "description"):
            _text(item.get(field), field, 260)
        if item.get("kind") not in GALLERY_KINDS:
            raise SiteCatalogError("Unreviewed gallery asset kind")
        if type(item.get("featured")) is not bool:
            raise SiteCatalogError("featured must be boolean")
        if item["featured"]:
            if project in featured:
                raise SiteCatalogError("Only one featured image is permitted per project")
            featured.add(project)
        source = item.get("source")
        if not isinstance(source, dict):
            raise SiteCatalogError("Gallery source metadata missing")
        repo = _text(source.get("repository"), "source.repository", 90)
        commit = _text(source.get("commit"), "source.commit", 40)
        path = _text(source.get("path"), "source.path", 250)
        blob_sha = _text(source.get("blob_sha"), "source.blob_sha", 40)
        if not SHA.fullmatch(commit) or not SHA.fullmatch(blob_sha):
            raise SiteCatalogError("Source must pin complete Git commit and blob identifiers")
        parts = PurePosixPath(path)
        if (path.startswith("/") or "\\" in path or ".." in parts.parts or
                len(parts.parts) < 2 or parts.suffix.lower() != ".png"):
            raise SiteCatalogError("Gallery image must be a reviewed repository PNG path")
        if (repo, commit, path, blob_sha) not in REVIEWED_SOURCES:
            raise SiteCatalogError("Gallery source is not in the reviewed image allowlist")
        if repo != f"madowaku/{project}":
            raise SiteCatalogError("Gallery image must belong to its own project repository")
        if type(source.get("size_bytes")) is not int or not 1000 <= source["size_bytes"] <= 3_000_000:
            raise SiteCatalogError("Invalid image byte size declaration")
        review = item.get("review")
        if (not isinstance(review, dict) or review.get("source_located") is not True or
                review.get("visual_inspected") is not False or review.get("reuse_approved") is not False):
            raise SiteCatalogError("Pending visual and reuse review must be explicit")
    return gallery
