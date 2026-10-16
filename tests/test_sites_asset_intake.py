"""MCC-M2.8.3: deterministic, fully offline synthetic PNG regression tests."""
from __future__ import annotations

import copy
import hashlib
import json
import struct
import zlib
from datetime import date
from pathlib import Path

import pytest

from mado_cockpit import sites_gallery
from mado_cockpit.sites_asset_intake import (
    APPROVAL_SCHEMA, IntakeError, diff_sources, fetch_pinned, git_blob_sha,
    get_item, inspect_bytes, prepare_staging, read_local_png, sha256,
    validate_review, verify_png,
)
from mado_cockpit.sites_portal import SITE_ROOT


def chunk(kind, payload):
    return (struct.pack(">I", len(payload)) + kind + payload +
            struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff))


def png(width=140, height=120, extra=()):
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    # Synthetic generated pixels, no real images, no actual screenshot claims.
    rows = bytearray()
    for y in range(height):
        seed = hashlib.sha512(f"fake-pixels-{y}".encode()).digest()
        rows.extend(bytes((0,)) + (seed * ((width * 4 // len(seed)) + 1))[:width * 4])
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) +
            b"".join(chunk(kind, payload) for kind, payload in extra) +
            chunk(b"IDAT", zlib.compress(bytes(rows))) + chunk(b"IEND", b""))


@pytest.fixture
def sample(monkeypatch):
    gallery = json.loads((SITE_ROOT / "gallery.json").read_text(encoding="utf-8"))
    catalog = json.loads((SITE_ROOT / "catalog.json").read_text(encoding="utf-8"))
    image = png()
    first = gallery["items"][0]
    first["source"]["blob_sha"] = git_blob_sha(image)
    first["source"]["size_bytes"] = len(image)
    entry = first["source"]
    monkeypatch.setattr(sites_gallery, "REVIEWED_SOURCES",
                        sites_gallery.REVIEWED_SOURCES | frozenset({(
                            entry["repository"], entry["commit"], entry["path"], entry["blob_sha"]
                        )}))
    item = get_item(gallery, catalog, first["id"])
    return gallery, catalog, item, image


def approved_review(item, raw):
    return {
        "schema": APPROVAL_SCHEMA,
        "item_id": item["id"],
        "image_sha256": sha256(raw),
        "source_blob_sha": item["source"]["blob_sha"],
        "reviewer": "human:gallery-reviewer",
        "reviewed_on": "2026-10-16",
        "note": "Manually inspected every pixel and reviewed redaction and redistribution rights.",
        "checks": {
            "visual_inspected": True,
            "privacy_redaction_reviewed": True,
            "rights_for_public_reuse_reviewed": True,
        },
        "reuse_basis": "license",
        "rights_evidence_url": (
            "https://github.com/" + item["source"]["repository"] + "/blob/" +
            item["source"]["commit"] + "/LICENSE"),
        "public_site_release_approved": False,
    }


def test_synthetic_png_structural_scan_and_metadata_policy():
    data = png()
    result = verify_png(data)
    assert (result["width"], result["height"], result["bytes"]) == (140, 120, len(data))
    assert result["metadata_policy"] == "safe_chunks_only"


@pytest.mark.parametrize("bad", [
    b"not png", png()[:-3], png() + b"suffix",
    png(extra=((b"tEXt", b"token=secret"),)),
    png(extra=((b"eXIf", b"private-EXIF"),)),
    png(extra=((b"iTXt", b"hidden-info"),)),
    png(extra=((b"acTL", b"animation"),)),
    png(width=5300),
])
def test_reject_malformed_oversized_or_metadata_bearing_png(bad):
    with pytest.raises(IntakeError):
        verify_png(bad)


def test_corrupted_crc_is_refused():
    raw = bytearray(png())
    raw[31] ^= 0x01
    with pytest.raises(IntakeError, match="CRC"):
        verify_png(bytes(raw))


def test_provenance_exact_git_blob_and_sha256(sample):
    gallery, catalog, item, raw = sample
    receipt = inspect_bytes(item, raw)
    assert receipt["source"]["blob_sha"] == git_blob_sha(raw)
    assert receipt["sha256"] == hashlib.sha256(raw).hexdigest()
    assert receipt["visual_content_verified"] is False
    assert receipt["privacy_review_complete"] is False
    assert receipt["rights_review_complete"] is False
    assert receipt["deployment_verified"] is False


def test_changed_source_bytes_denied_even_if_png_valid(sample):
    _, _, item, raw = sample
    with pytest.raises(IntakeError, match="Image size"):
        inspect_bytes(item, raw + b"x")
    same_length_other_png = bytearray(raw)
    same_length_other_png[-10] ^= 0x20
    with pytest.raises(IntakeError, match="Git blob"):
        inspect_bytes(item, bytes(same_length_other_png))


def test_unregistered_item_denied(sample):
    gallery, catalog, _, _ = sample
    with pytest.raises(IntakeError, match="not registered"):
        get_item(gallery, catalog, "secret-project")


def test_no_automatic_release_and_approved_local_staging(tmp_path, sample):
    gallery, catalog, item, raw = sample
    review = approved_review(item, raw)
    target = tmp_path / "prepared-gallery"
    proposal = prepare_staging(gallery, catalog, item["id"], raw, review, target)
    assert (target / (item["id"] + ".png")).read_bytes() == raw
    assert json.loads((target / "proposal.json").read_text()) == proposal
    assert proposal["manual_attestation_not_authenticated"]
    assert proposal["requires_separate_publication_review"]
    assert proposal["auto_publish"] is False
    assert proposal["deployment_verified"] is False
    with pytest.raises(IntakeError, match="non-existing"):
        prepare_staging(gallery, catalog, item["id"], raw, review, target)


@pytest.mark.parametrize("patch,pattern", [
    ({"image_sha256": "0" * 64}, "not bound"),
    ({"source_blob_sha": "0" * 40}, "source revision"),
    ({"reviewer": "bot:ci"}, "Reviewer"),
    ({"note": "ok"}, "Reviewer"),
    ({"reuse_basis": "unverified"}, "basis"),
    ({"rights_evidence_url": "https://evil.example/LICENSE"}, "Rights evidence"),
    ({"rights_evidence_url": "https://github.com/madowaku/search-forest/blob/main/LICENSE"}, "Rights evidence"),
    ({"public_site_release_approved": True}, "cannot authorize"),
    ({"reviewed_on": "not-a-date"}, "reviewed_on"),
])
def test_invalid_manual_review_is_fail_closed(sample, patch, pattern):
    _, _, item, raw = sample
    review = approved_review(item, raw)
    review.update(patch)
    with pytest.raises(IntakeError, match=pattern):
        validate_review(review, inspect_bytes(item, raw), item)


@pytest.mark.parametrize("field", [
    "visual_inspected", "privacy_redaction_reviewed", "rights_for_public_reuse_reviewed",
])
def test_every_manual_review_check_is_required(sample, field):
    _, _, item, raw = sample
    review = approved_review(item, raw)
    review["checks"][field] = False
    with pytest.raises(IntakeError, match="Every visual"):
        validate_review(review, inspect_bytes(item, raw), item)


def test_bad_review_cannot_write_any_staging_data(tmp_path, sample):
    gallery, catalog, item, raw = sample
    review = approved_review(item, raw)
    review["checks"]["privacy_redaction_reviewed"] = False
    target = tmp_path / "candidate"
    with pytest.raises(IntakeError):
        prepare_staging(gallery, catalog, item["id"], raw, review, target)
    assert not target.exists()


def test_proposal_cannot_write_to_public_portal(sample):
    gallery, catalog, item, raw = sample
    with pytest.raises(IntakeError, match="publicly served"):
        prepare_staging(gallery, catalog, item["id"], raw, approved_review(item, raw),
                        SITE_ROOT / "prepared-gallery")


def test_rejects_symlinked_local_png(tmp_path):
    original = tmp_path / "image.png"
    original.write_bytes(png())
    symlink = tmp_path / "shortcut.png"
    symlink.symlink_to(original)
    with pytest.raises(IntakeError, match="non-symlink"):
        read_local_png(symlink)


def test_deterministic_source_delta_detection(sample):
    gallery, _, _, _ = sample
    old = copy.deepcopy(gallery)
    assert diff_sources(gallery, old)["unchanged_source"] == sorted(x["id"] for x in old["items"])
    old["items"][0]["source"]["blob_sha"] = "0" * 40
    old["items"].append(old["items"].pop(1))
    old["items"].pop()
    delta = diff_sources(gallery, old)
    assert delta["changed_source"] == [gallery["items"][0]["id"]]
    assert delta["new"] == [gallery["items"][1]["id"]]
    assert delta["changed_or_removed_requires_review"] is True
    assert delta["auto_promote"] is False


def test_explicit_pinned_fetch_checks_bytes_and_no_redirect(sample, monkeypatch):
    gallery, catalog, item, raw = sample
    from mado_cockpit import sites_asset_intake as mod

    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def read(self, size):
            return raw[:size]

    class Opener:
        def open(self, request, timeout):
            assert request.full_url.startswith("https://raw.githubusercontent.com/madowaku/")
            assert timeout == 15
            return Response()

    monkeypatch.setattr(mod.urllib.request, "build_opener", lambda *_: Opener())
    assert fetch_pinned(item) == raw

    class BadResponse(Response):
        def read(self, size):
            return raw + b"x"

    monkeypatch.setattr(mod.urllib.request, "build_opener",
                        lambda *_: type("O", (), {"open": lambda *_args, **_kwargs: BadResponse()})())
    with pytest.raises(IntakeError, match="Image size"):
        fetch_pinned(item)
