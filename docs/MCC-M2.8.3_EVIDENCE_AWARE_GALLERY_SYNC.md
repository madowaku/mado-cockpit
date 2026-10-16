# MCC-M2.8.3 Evidence-Aware Gallery Sync / Visual Asset Intake

MADO Project Atlas images can now move through an **operator-controlled, fail-closed pipeline**. This milestone does **not** modify a ChatGPT Site, publish a repository asset, infer a copyright license or impersonate an authenticated reviewer.

## Why it exists

M2.8.2 located four public GitHub images for Asset Foundry and App Gardenium, but locating a PNG in a public repository does not establish that its pixels were inspected, private information was removed, reuse is permitted, or a real app was tested. The M2.8.3 intake keeps these assertions separate.

```text
PUBLIC GALLERY SOURCES (M2.8.2, pinned Git commit + blob SHA)
          ↓ explicit opt-in fetch OR locally supplied source PNG
IMAGE INSPECT / QUARANTINE
  • max 3 MB, 8 million pixels, bounded PNG chunks
  • full PNG chunk CRC + structure validation
  • reject text / EXIF / unknown metadata, embedded content, APNG
  • check Git blob SHA-1 and exact size against pinned source
  • record strong SHA-256 over identical image bytes
          ↓ manual human examination (pixels, secrets, license, redaction)
MANUAL REVIEW JSON (digest-bound, operator-claimed reviewer; not signed)
          ↓ stage command
LOCAL STAGING PROPOSAL + ORIGINAL PNG (outside public portal source)
          ↓ separate human PR / product publication authorization
SITE UPDATE / PRODUCTION (NOT part of this milestone)
```

### CLI examples

Install existing dev dependencies:

```sh
pip install -e ".[dev]"
pytest -q tests/test_sites_asset_intake.py
```

Manually fetch one pinned image from a public `raw.githubusercontent.com` URL. The URL comes from `gallery.json` and cannot be freely supplied by the caller:

```sh
python -m mado_cockpit.sites_asset_intake fetch maf-review \
  --out .mado/gallery-intake/quarantine/maf-review.png
```

To inspect a supplied local copy without any network request:

```sh
python -m mado_cockpit.sites_asset_intake inspect maf-review \
  --image .mado/gallery-intake/quarantine/maf-review.png \
  > .mado/gallery-intake/maf-review-inspection.json
```

Git-based source drift can be checked against a previously exported `gallery.json`. Both files are checked against the current public-source allowlist; any new commit/blob must first be reviewed and deliberately added to the allowlist:

```sh
python -m mado_cockpit.sites_asset_intake diff \
  --previous path/to/previous-gallery.json
```

The comparison emits `new`, `removed`, `changed_source`, `unchanged_source`, and `auto_promote=false`. A `changed_source` means a real source change, not evidence of approval. This is a deterministic snapshot comparison; it does not poll GitHub for changes, enumerate private repos, or automatically add images.

## Review attestation

Save a JSON file **outside the public portal and outside Git**. `sha256` must equal the exact inspection receipt for the reviewed bytes. Example **schema only**, not a statement that anyone reviewed an actual image:

```json
{
  "schema": "mado.gallery-manual-review.v1",
  "item_id": "maf-review",
  "image_sha256": "REPLACE_WITH_ACTUAL_64_HEX_INSPECTION_DIGEST",
  "source_blob_sha": "REPLACE_WITH_PINNED_GIT_BLOB_SHA",
  "reviewer": "human:your-reviewer-id",
  "reviewed_on": "2026-10-16",
  "note": "I inspected the image contents, checked sensitive data, and verified my explicit reuse permission evidence.",
  "checks": {
    "visual_inspected": true,
    "privacy_redaction_reviewed": true,
    "rights_for_public_reuse_reviewed": true
  },
  "reuse_basis": "license",
  "rights_evidence_url": "https://github.com/madowaku/mado-asset-foundry/blob/REPLACE_WITH_PINNED_COMMIT/LICENSE",
  "public_site_release_approved": false
}
```

The URL is required to point to a file on the **same repository and pinned commit**, but this is only *syntactic evidence*: the code does not establish the file exists or that it grants redistribution rights for the image. A human must read the actual terms. A public GitHub repo is not by itself a license. No key or token belongs in this record.

If image bytes differ from the attested SHA-256, any review check is missing, evidence is unpinned, or someone tries to claim Site release approval, staging is rejected **before writing files**.

```sh
python -m mado_cockpit.sites_asset_intake stage maf-review \
  --image .mado/gallery-intake/quarantine/maf-review.png \
  --review .mado/gallery-intake/manual/maf-review.json \
  --out .mado/gallery-intake/staged/maf-review-001
```

Staging generates a `maf-review.png` plus `proposal.json` bound to the exact inspected digest. It never copies into `integrations/sites/portal/` or modifies `gallery.json`. The proposal explicitly includes `manual_attestation_not_authenticated=true`, `requires_separate_publication_review=true`, `deployment_verified=false`, and `auto_publish=false`. Human review metadata is a claim, not cryptographic authentication.

## Technical limitations and manual QA

1. PNG parser validates size, PNG structure, CRC and rejects metadata chunks with obvious leak potential. **It is not a full pixel decoder, steganography detector, content moderation filter, malware scanner or privacy-redaction engine**. Examine the actual rendered pixels before attesting.
2. The exact Git blob SHA-1 from public GitHub tree proves correspondence to the expected Git object under normal Git assumptions. Additional SHA-256 binds subsequent local content. No GitHub API attestation or artifact signature is produced.
3. The pinned source fetch is opt-in, caps response bytes and refuses HTTP redirects. It never follows an arbitrary user-provided URL. Local copies in `.mado/` are gitignored by the existing repo policy.
4. Diff is explicit and local. Existing `gallery.json` still marks `visual_inspected=false`, `reuse_approved=false`, `deployment_verified=false`. This milestone **does not set them to true**.
5. Site hosting, sharing settings, actual browser visuals, and authorization to publish are a separate, human-controlled process. Work mode is **not required** for this GitHub-first loop.

## GitHub quality gate

`.github/workflows/sites-asset-intake-qa.yml` runs unit and integration tests with **entirely synthetic PNGs**. No public PNG is downloaded during CI, no license is claimed and no Site is contacted. Existing M2.8/M2.8.1/M2.8.2 tests remain available. A passing test is a software contract result, not live visual QA.

## Next milestone idea

MCC-M2.8.4 could implement a review-only, local-image preview renderer that compares source and redacted candidate side-by-side, records perceptual diffs and creates a manually reviewed commit proposal. Avoid copying image binaries into a publicly served build until both distribution rights and image privacy are confirmed.
