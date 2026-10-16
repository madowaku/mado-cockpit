# MCC-M2.8.2 Visual Project Gallery / Screenshot Evidence Hub

## Overview

Adds an evidence-first image gallery to the **MADO / Project Atlas**. This milestone builds on:

- PR #30: MCC-M2.8 static portal, source-only public project index, release gate.
- PR #31: MCC-M2.8.1 optional read-only live browser dogfood.
- This PR: four pinned visual sources, filters, accessible zoom dialog, provenance links and safe fallback thumbnails.

These are **stacked PRs**, not independent main-branch patches. Merge #30, then #31, then retarget this PR to `main` before merge.

## Current picture inventory

| Project | Artifact | Kind | Provenance |
| --- | --- | --- | --- |
| Asset Foundry | `e2e/goldens/desktop-reviewed.png` | committed browser golden | mado-asset-foundry @ `8d25589` |
| Asset Foundry | `e2e/goldens/desktop-gallery-pending.png` | committed browser golden | mado-asset-foundry @ `8d25589` |
| App Gardenium | `marketing/beta-launch/assets/01-home.png` | marketing asset | app-gardenium @ `6c3c3d5` |
| App Gardenium | `marketing/beta-launch/assets/04-greenhouse.png` | marketing asset | app-gardenium @ `6c3c3d5` |

Source paths, pinned commit SHA, Git blob SHA and byte sizes were located in public GitHub trees on 2026-10-16. The gallery links to those exact source files and renders images via public `raw.githubusercontent.com` URLs at the pinned commit. This is a **source-provenance claim only**: no verified image-download SHA-256, pixel inspection, image content/reuse permission, live app state or public Site reachability is asserted.

The public GitHub catalog has 12 projects; only 2 have reviewed *source locations*. The other 10 deliberately show CSS artwork rather than fabricated screenshots. All publication states remain `source_only`.

## User experience

- Hero button scrolls to image gallery, then browsable visual cards.
- Source-kind filter: **All / E2E goldens / Marketing assets**.
- Click a tile for an accessible native `dialog` with larger image, description, source-type disclosure and pinned GitHub source link. Escape and Close dismiss it.
- Asset Foundry and Gardenium directory cards use the featured image with a review-pending badge.
- All other project cards retain existing abstract artwork.
- If an image host or CSP blocks loading, fallback text and GitHub source link remain. If the gallery manifest is unavailable, the project directory continues to work.
- Images are lazy loaded, sourced only from pinned and reviewed GitHub repository paths, and do not use tracking pixels or private files.

## Evidence contract and release gate

`integrations/sites/portal/gallery.json` uses `mado.sites-gallery.v1`.

- `source_located=true`: public repository tree contains the referenced PNG path and blob on a pinned commit.
- `visual_inspected=false`: the actual pixels have NOT been reviewed in a trusted browser.
- `reuse_approved=false`: public appearance and licensing/reuse approval are NOT established by repository visibility alone.
- `deployment_verified=false`: no ChatGPT Site deployment verification is implied.

`sites_gallery.validate_gallery` rejects secret-looking fields, unreviewed/private projects, unpinned source paths, duplicates, incorrect source owners, unreviewed image kinds, ambiguous promotion, and duplicate featured images. The static build includes `gallery.json` and its SHA-256 receipt, but intentionally does **not** mirror/download remote image files. Thus the build can work offline, but actual image rendering requires the browser's access to the public GitHub image host and the Sites CSP allowing it.

A production/public Sites update requires a separate **human visual and reuse-rights inspection**, plus a real-site browser check. This milestone doesn't publish or alter Sites sharing permissions.

## Local review

```bash
pip install -e ".[dev]"
pytest -q tests/test_sites_portal.py tests/test_sites_gallery.py tests/test_sites_live_qa.py
python -m mado_cockpit.sites_portal --output build/sites-portal
python -m http.server 8765 --directory build/sites-portal
```

Open `http://localhost:8765`. Test a desktop and mobile width, each filter, image fallback (offline or blocked host), modal Escape/Close, provenance links, project search, and gallery-manifest failure. Inspect actual pixel contents before approving public use. Check that marketing artwork is clearly labeled and never presented as gameplay proof.

## Next gate

MCC-M2.8.3 could add reviewed screenshot ingestion with pixel SHA-256, opt-in local/offline copies, privacy/redaction + license attestations, screenshot freshness and source-deployment parity. Do not silently upgrade `visual_inspected` or `reuse_approved` from a passing UI test.
