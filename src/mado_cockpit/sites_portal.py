"""MCC-M2.8: validated, read-only static project atlas publishing candidate.

This module NEVER creates, deploys, or modifies a ChatGPT Site.
The artifact receipt is build integrity evidence, not proof of live deployment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
SITE_ROOT = ROOT / "integrations" / "sites" / "portal"
GALLERY_PATH = SITE_ROOT / "gallery.json"
FLIGHTS_PATH = SITE_ROOT / "test-flights.json"
ASSETS = ("index.html", "styles.css", "app.js", "catalog.json", "gallery.json",
          "test-flight.html", "test-flight.css", "test-flight.js", "test-flights.json")
SCHEMA = "mado.sites-catalog.v1"
CATEGORIES = {"Control", "Assets", "Games", "Audio", "Quality", "Experiences", "Research"}
STATES = {"source_only", "preview_pending", "published_verified"}
# Checked against the linked GitHub account on 2026-10-16. This explicit
# public allowlist must be reviewed when onboarding additional repositories.
PUBLIC_REPO_ALLOWLIST = frozenset({
    "mado-cockpit",
    "mado-system-one",
    "mado-asset-foundry",
    "mado-game-service-factory",
    "mado-game-audio-loop",
    "mado-plugin-factory",
    "mado-loop",
    "mado-mobile-qa-loop",
    "app-gardenium",
    "gear-relay",
    "mado-liquid-computing",
    "madowaku-cockpit",
})
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VISUAL = re.compile(r"^[a-z][a-z0-9-]{0,30}$")
SENSITIVE = re.compile(r"(?:password|api[_-]?key|secret|private[_-]?key|access[_-]?token|credential)", re.I)


class SiteCatalogError(ValueError):
    """Validation blocked a publication candidate."""


def _text(value: Any, name: str, limit: int = 240) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise SiteCatalogError(f"{name}: expected nonempty string <= {limit} characters")
    if any(ord(c) < 32 for c in value):
        raise SiteCatalogError(f"{name}: control characters are forbidden")
    return value


def _https(url: Any, name: str, *, github: bool = False) -> str:
    s = _text(url, name, 700)
    parts = urlsplit(s)
    if (parts.scheme != "https" or not parts.hostname or parts.username
            or parts.password or parts.port or parts.fragment):
        raise SiteCatalogError(f"{name}: require clean HTTPS URL")
    if github and (parts.hostname != "github.com" or
                   not parts.path.startswith("/madowaku/")):
        raise SiteCatalogError(f"{name}: evidence must be under github.com/madowaku/")
    if not github and parts.hostname in {"localhost", "127.0.0.1"}:
        raise SiteCatalogError(f"{name}: local URLs are not deploy evidence")
    return s


def _reject_sensitive_keys(obj: Any) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if SENSITIVE.search(str(key)):
                raise SiteCatalogError(f"Sensitive-looking catalog field: {key}")
            _reject_sensitive_keys(value)
    elif isinstance(obj, list):
        for item in obj:
            _reject_sensitive_keys(item)


def validate_catalog(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise SiteCatalogError("Unexpected catalog schema")
    if data.get("visibility") != "public_only":
        raise SiteCatalogError("Catalog must remain public_only")
    try:
        date.fromisoformat(_text(data.get("snapshot_date"), "snapshot_date", 10))
    except ValueError as exc:
        raise SiteCatalogError("Invalid snapshot_date") from exc
    projects = data.get("projects")
    if not isinstance(projects, list) or not (1 <= len(projects) <= 100):
        raise SiteCatalogError("Expected between 1 and 100 projects")
    _reject_sensitive_keys(data)
    seen: set[str] = set()
    for entry in projects:
        if not isinstance(entry, dict):
            raise SiteCatalogError("Project must be an object")
        slug = _text(entry.get("id"), "id", 70)
        if not SLUG.fullmatch(slug) or slug in seen:
            raise SiteCatalogError(f"Duplicate or invalid project id: {slug}")
        if slug not in PUBLIC_REPO_ALLOWLIST:
            raise SiteCatalogError(f"Unreviewed or private repository: {slug}")
        seen.add(slug)
        for field in ("title", "description"):
            _text(entry.get(field), field)
        category = _text(entry.get("category"), "category", 30)
        if category not in CATEGORIES:
            raise SiteCatalogError(f"Unknown category: {category}")
        visual = _text(entry.get("visual"), "visual", 31)
        if not VISUAL.fullmatch(visual):
            raise SiteCatalogError("Invalid visual token")
        if type(entry.get("featured")) is not bool:
            raise SiteCatalogError("featured must be boolean")
        repository = _https(entry.get("repository"), "repository", github=True)
        if repository != f"https://github.com/madowaku/{slug}":
            raise SiteCatalogError("Repository URL does not match reviewed slug")
        pub = entry.get("publication")
        if not isinstance(pub, dict) or pub.get("state") not in STATES:
            raise SiteCatalogError("Publication state is invalid")
        state = pub["state"]
        if state == "published_verified":
            _https(pub.get("url"), "publication.url")
            _https(pub.get("evidence_url"), "publication.evidence_url", github=True)
            if pub.get("audience") != "public":
                raise SiteCatalogError("Verified public site requires public audience proof")
            try:
                date.fromisoformat(_text(pub.get("verified_on"), "publication.verified_on", 10))
            except ValueError as exc:
                raise SiteCatalogError("Invalid verified_on") from exc
        elif pub.get("url") is not None or pub.get("evidence_url") is not None:
            raise SiteCatalogError("Unverified sites may not expose a site URL or evidence")
    return data


def build_site(*, catalog_path: Path | None = None, output: Path | None = None) -> dict[str, Any]:
    catalog_path = catalog_path or SITE_ROOT / "catalog.json"
    output = output or ROOT / "build" / "sites-portal"
    catalog = validate_catalog(json.loads(catalog_path.read_text(encoding="utf-8")))
    from .sites_gallery import validate_gallery
    gallery = validate_gallery(json.loads(GALLERY_PATH.read_text(encoding="utf-8")), catalog)
    from .sites_test_flight import validate_test_flights
    flights = validate_test_flights(json.loads(FLIGHTS_PATH.read_text(encoding="utf-8")), catalog)
    output = output.resolve()
    if SITE_ROOT.resolve() == output or SITE_ROOT.resolve() in output.parents:
        raise SiteCatalogError("Refusing to build inside source directory")
    if output.exists() and any(output.iterdir()):
        raise SiteCatalogError(f"Refusing non-empty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for name in ASSETS:
        source = (catalog_path if name == "catalog.json" else GALLERY_PATH if name == "gallery.json"
                  else FLIGHTS_PATH if name == "test-flights.json" else SITE_ROOT / name)
        if not source.is_file() or source.is_symlink():
            raise SiteCatalogError(f"Missing or symlinked asset: {name}")
        raw = source.read_bytes()
        if len(raw) > 1024 * 1024:
            raise SiteCatalogError(f"Oversized static asset: {name}")
        (output / name).write_bytes(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    receipt = {
        "schema": "mado.site-build-receipt.v1",
        "candidate": "MCC-M2.8-madowaku-project-atlas",
        "source_of_truth": "madowaku/mado-cockpit",
        "release_state": "review_only",
        "sites_project_id": None,
        "sites_deployment_url": None,
        "deployment_verified": False,
        "gallery": {
            "asset_count": len(gallery["items"]),
            "visual_inspected": False,
            "reuse_approved": False,
            "source_manifest": "gallery.json",
        },
        "human_test_flight": {
            "mission_count": len(flights["missions"]),
            "review_state": "draft",
            "feedback_upload_enabled": False,
            "live_play_verified": False,
        },
        "project_count": len(catalog["projects"]),
        "verified_site_count": sum(
            p["publication"]["state"] == "published_verified" for p in catalog["projects"]
        ),
        "sha256": hashes,
    }
    (output / "build-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and prepare a non-deployed ChatGPT Sites portal candidate")
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        receipt = build_site(catalog_path=args.catalog, output=args.output)
    except (SiteCatalogError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
