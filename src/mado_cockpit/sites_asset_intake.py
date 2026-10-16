"""MCC-M2.8.3: evidence-aware, operator-controlled PNG gallery intake.

No automatic publication. Sources must be pinned in the M2.8.2 gallery
allowlist; remote fetch is optional, explicit and bounded. Review statements
are operator-attested, not authenticated or a proof of license ownership.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import urllib.error
import urllib.request
import zlib
from datetime import date
from pathlib import Path
from typing import Any

from .sites_gallery import source_url, validate_gallery
from .sites_portal import SITE_ROOT, SiteCatalogError, validate_catalog

MAX_BYTES = 3_000_000
MAX_PIXELS = 8_000_000
MAX_CHUNKS = 256
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ALLOWED_ANCILLARY = {b"sRGB", b"gAMA", b"cHRM", b"pHYs", b"tRNS", b"bKGD"}
APPROVAL_SCHEMA = "mado.gallery-manual-review.v1"
INSPECTION_SCHEMA = "mado.gallery-image-inspection.v1"
PROPOSAL_SCHEMA = "mado.gallery-staging-proposal.v1"


class IntakeError(ValueError):
    """Safety or provenance gate denied the intake."""


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_png(data: bytes) -> dict[str, Any]:
    """Structural PNG check, not an image decoder, privacy audit or pixel proof."""
    if not PNG_SIGNATURE == data[:8] or len(data) > MAX_BYTES or len(data) < 60:
        raise IntakeError("Not a bounded PNG")
    pos = 8
    count = 0
    width = height = 0
    got_idat = got_end = False
    idat_done = False
    while pos < len(data):
        count += 1
        if count > MAX_CHUNKS or pos + 12 > len(data):
            raise IntakeError("PNG chunk limit or truncated header")
        length = struct.unpack_from(">I", data, pos)[0]
        kind = data[pos + 4:pos + 8]
        stop = pos + 12 + length
        if length > MAX_BYTES or stop > len(data):
            raise IntakeError("Oversized or truncated PNG chunk")
        chunk = data[pos + 8:pos + 8 + length]
        stored_crc = struct.unpack_from(">I", data, pos + 8 + length)[0]
        if zlib.crc32(kind + chunk) & 0xffffffff != stored_crc:
            raise IntakeError("PNG CRC mismatch")
        if not all((65 <= c <= 90 or 97 <= c <= 122) for c in kind):
            raise IntakeError("Invalid PNG chunk type")
        if count == 1:
            if kind != b"IHDR" or length != 13:
                raise IntakeError("PNG must start with IHDR")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", chunk)
            valid_depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8},
                            4: {8, 16}, 6: {8, 16}}
            if (not 100 <= width <= 5000 or not 100 <= height <= 5000
                    or width * height > MAX_PIXELS or depth not in valid_depths.get(color, set())
                    or compression != 0 or filtering != 0 or interlace not in (0, 1)):
                raise IntakeError("Unsupported or oversized PNG dimensions/format")
        elif kind == b"IHDR":
            raise IntakeError("Duplicate IHDR")
        elif kind == b"IDAT":
            if idat_done:
                raise IntakeError("Non-contiguous IDAT chunks")
            got_idat = True
        elif kind == b"IEND":
            if length != 0 or not got_idat or stop != len(data):
                raise IntakeError("Invalid PNG end/trailing content")
            got_end = True
        elif kind in (b"PLTE",) or kind in ALLOWED_ANCILLARY:
            if got_idat:
                idat_done = True
        else:
            raise IntakeError("Unreviewed, embedded or privacy-risk PNG metadata/chunk")
        if got_idat and kind != b"IDAT":
            idat_done = True
        pos = stop
        if got_end:
            break
    if not got_end or pos != len(data):
        raise IntakeError("Missing PNG IEND")
    return {"width": width, "height": height, "bytes": len(data), "metadata_policy": "safe_chunks_only"}


def get_item(gallery: dict[str, Any], catalog: dict[str, Any], item_id: str) -> dict[str, Any]:
    validate_gallery(gallery, catalog)
    return next((x for x in gallery["items"] if x["id"] == item_id), None) or _missing(item_id)


def _missing(item_id: str) -> Any:
    raise IntakeError(f"Image not registered in source allowlist: {item_id}")


def inspect_bytes(item: dict[str, Any], raw: bytes) -> dict[str, Any]:
    source = item["source"]
    if len(raw) != source["size_bytes"]:
        raise IntakeError("Image size differs from pinned repository tree")
    if git_blob_sha(raw) != source["blob_sha"]:
        raise IntakeError("Image bytes do not match the pinned Git blob SHA")
    properties = verify_png(raw)
    return {
        "schema": INSPECTION_SCHEMA,
        "item_id": item["id"],
        "project_id": item["project_id"],
        "source": {key: source[key] for key in ("repository", "commit", "path", "blob_sha")},
        "sha256": sha256(raw),
        "png": properties,
        "visual_content_verified": False,
        "privacy_review_complete": False,
        "rights_review_complete": False,
        "deployment_verified": False,
    }


def read_local_png(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise IntakeError("Local PNG must be a regular non-symlink file")
    if path.stat().st_size > MAX_BYTES:
        raise IntakeError("PNG exceeds bounded intake size")
    return path.read_bytes()


def diff_sources(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    """Deterministic, immutable-source comparison; never approves changes."""
    old = {item["id"]: item for item in previous["items"]}
    new = {item["id"]: item for item in current["items"]}
    added = sorted(new.keys() - old.keys())
    removed = sorted(old.keys() - new.keys())
    changed = sorted(k for k in new.keys() & old.keys() if new[k]["source"] != old[k]["source"])
    unchanged = sorted(k for k in new.keys() & old.keys() if new[k]["source"] == old[k]["source"])
    return {
        "schema": "mado.gallery-source-diff.v1",
        "new": added, "removed": removed, "changed_source": changed,
        "unchanged_source": unchanged,
        "changed_or_removed_requires_review": bool(changed or removed),
        "auto_promote": False,
    }


def validate_review(review: dict[str, Any], inspection: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(review, dict) or review.get("schema") != APPROVAL_SCHEMA:
        raise IntakeError("Expected a manual review attestation JSON")
    if review.get("item_id") != item["id"] or review.get("image_sha256") != inspection["sha256"]:
        raise IntakeError("Review is not bound to the inspected image bytes")
    if review.get("source_blob_sha") != inspection["source"]["blob_sha"]:
        raise IntakeError("Review does not match pinned source revision")
    reviewer = review.get("reviewer")
    note = review.get("note")
    if (not isinstance(reviewer, str) or not re.fullmatch(r"human:[A-Za-z0-9_-]{3,64}", reviewer)
            or not isinstance(note, str) or not 25 <= len(note) <= 1000):
        raise IntakeError("Reviewer label and substantive human review note are required")
    try:
        date.fromisoformat(review["reviewed_on"])
    except (ValueError, KeyError, TypeError) as exc:
        raise IntakeError("Valid reviewed_on ISO date required") from exc
    checks = review.get("checks")
    keys = ("visual_inspected", "privacy_redaction_reviewed", "rights_for_public_reuse_reviewed")
    if not isinstance(checks, dict) or any(checks.get(k) is not True for k in keys):
        raise IntakeError("Every visual, privacy and rights review must explicitly pass")
    basis = review.get("reuse_basis")
    if basis not in ("license", "owner_permission"):
        raise IntakeError("Explicit license or owner-permission basis required")
    evidence = review.get("rights_evidence_url")
    prefix = ("https://github.com/" + item["source"]["repository"]
              + "/blob/" + item["source"]["commit"] + "/")
    if (not isinstance(evidence, str) or not evidence.startswith(prefix)
            or len(evidence) > 700 or any(c in evidence for c in "?#@")
            or "/../" in evidence or evidence.endswith("/")):
        raise IntakeError("Rights evidence must be a pinned file in the source repository")
    if review.get("public_site_release_approved") is not False:
        raise IntakeError("Staging approval cannot authorize production publication")
    return review


def _fresh_output(output: Path) -> Path:
    dest = output.resolve()
    site_root = SITE_ROOT.resolve()
    if dest == site_root or site_root in dest.parents:
        raise IntakeError("Cannot write intake evidence into the publicly served portal source")
    if output.is_symlink() or dest.exists():
        raise IntakeError("Intake destinations must be new, non-existing paths")
    return dest


def prepare_staging(
    gallery: dict[str, Any], catalog: dict[str, Any], item_id: str,
    raw: bytes, review: dict[str, Any], output: Path,
) -> dict[str, Any]:
    item = get_item(gallery, catalog, item_id)
    inspection = inspect_bytes(item, raw)
    validate_review(review, inspection, item)
    dest = _fresh_output(output)
    dest.mkdir(parents=True, exist_ok=False)
    asset = dest / (item_id + ".png")
    asset.write_bytes(raw)
    proposal = {
        "schema": PROPOSAL_SCHEMA,
        "item_id": item_id,
        "source": inspection["source"],
        "file": asset.name,
        "image_sha256": inspection["sha256"],
        "image_metadata": inspection["png"],
        "reviewer_claim": review["reviewer"],
        "reviewed_on": review["reviewed_on"],
        "reuse_basis_claim": review["reuse_basis"],
        "rights_evidence_url": review["rights_evidence_url"],
        "manual_attestation_not_authenticated": True,
        "requires_separate_publication_review": True,
        "auto_publish": False,
        "deployment_verified": False,
    }
    (dest / "proposal.json").write_text(
        json.dumps(proposal, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return proposal


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise IntakeError("Refusing redirect from pinned GitHub asset host")


def fetch_pinned(item: dict[str, Any]) -> bytes:
    """Explicit network action; URL is built from a reviewed manifest, never user input."""
    url = source_url(item["source"])
    if not url.startswith("https://raw.githubusercontent.com/madowaku/"):
        raise IntakeError("Unapproved image host")
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": "mado-gallery-intake/0.1"})
    try:
        with opener.open(request, timeout=15) as response:
            if response.status != 200:
                raise IntakeError("Pinned image endpoint did not return 200")
            raw = response.read(MAX_BYTES + 1)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise IntakeError("Pinned image fetch failed") from exc
    inspect_bytes(item, raw)
    return raw


def load_manifests() -> tuple[dict[str, Any], dict[str, Any]]:
    catalog = validate_catalog(json.loads((SITE_ROOT / "catalog.json").read_text(encoding="utf-8")))
    gallery = validate_gallery(
        json.loads((SITE_ROOT / "gallery.json").read_text(encoding="utf-8")), catalog)
    return gallery, catalog


def cli() -> int:
    parser = argparse.ArgumentParser(description="MCC-M2.8.3 reviewed PNG intake (never deploys)")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", help="Inspect local bytes against a pinned Git blob")
    inspect.add_argument("item_id")
    inspect.add_argument("--image", type=Path, required=True)
    fetch = sub.add_parser("fetch", help="Explicitly fetch a pinned public image to quarantine")
    fetch.add_argument("item_id")
    fetch.add_argument("--out", type=Path, required=True)
    stage = sub.add_parser("stage", help="Prepare a separate reviewed staging proposal")
    stage.add_argument("item_id")
    stage.add_argument("--image", type=Path, required=True)
    stage.add_argument("--review", type=Path, required=True)
    stage.add_argument("--out", type=Path, required=True)
    plan = sub.add_parser("diff", help="Compare reviewed gallery source manifests")
    plan.add_argument("--previous", type=Path, required=True)
    args = parser.parse_args()
    try:
        gallery, catalog = load_manifests()
        if args.command == "diff":
            old = validate_gallery(json.loads(args.previous.read_text(encoding="utf-8")), catalog)
            result = diff_sources(gallery, old)
        else:
            item = get_item(gallery, catalog, args.item_id)
            if args.command == "fetch":
                dest = _fresh_output(args.out)
                raw = fetch_pinned(item)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(raw)
                result = inspect_bytes(item, raw)
            elif args.command == "inspect":
                result = inspect_bytes(item, read_local_png(args.image))
            else:
                approval = json.loads(args.review.read_text(encoding="utf-8"))
                result = prepare_staging(gallery, catalog, args.item_id, read_local_png(args.image),
                                         approval, args.out)
    except (IntakeError, SiteCatalogError, ValueError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
