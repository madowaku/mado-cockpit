# MCC-M2.9 Human Test Flight / One-Click Feedback Gate

## Stacked base
This PR builds on #33 (MCC-M2.8.3), which builds on #32, #31 and #30. It does not overwrite the main branch or merge those PRs.

## Delivered MVP

- An entry point from the existing MADO Project Atlas and human-test links on the three pilot project cards.
- A standalone, keyboard-accessible three-minute test screen with project selector, exactly three human-observed checkpoints, emoji rating, a short optional note and a human-entered build identifier.
- Explicit local save (per browser and mission), clear and JSON export. Saving is never automatic; browser storage may not exist or may be cleared.
- An explicit GitHub **new issue draft** handoff. The browser shows a confirmation and opens GitHub with prefilled text. It does NOT create or submit the issue. Notes are transmitted to GitHub only after the tester acts.
- Test-launch handling: a URL in the verified public catalog is prefilled only when its state is `published_verified`. Otherwise the test URL must be supplied by the human in that browser session. Local localhost HTTP and HTTPS are allowed for manual testing; unverified URLs never change the site's publication state. Windows native builds are not silently launched or downloaded.
- Schema-validated `mado.human-test-flight.v1` review-only mission fixture; provenance is curated example text, not an AI-generated PR-diff mission.
- Separate, content-addressed build assets and receipt; no Site publication, permission changes or automated telemetry.

## How to use

```bash
pip install -e ".[dev]"
pytest -q tests/test_sites_portal.py tests/test_sites_gallery.py tests/test_sites_test_flight.py
node --check integrations/sites/portal/app.js
node --check integrations/sites/portal/test-flight.js
python -m mado_cockpit.sites_portal --output build/sites-portal
python -m http.server 8765 --directory build/sites-portal
```

Open `http://localhost:8765/test-flight.html?project=mado-game-service-factory`. Select a 3-minute mission, enter an explicit test URL if you have one, complete steps, choose a rating, save locally and export a JSON receipt. Use **GitHub Issue を下書き** to review before opening an issue editor. The sample list is not proof that a game executable or reachable Web build exists.

## Privacy and safety

- No embedded unreviewed apps; preview opens in a separate tab after direct click.
- Only explicit URL schemes (`https:` or `http:` loopback) with no credentials are allowed for user-supplied previews; no arbitrary script/data/file URLs.
- Feedback text and entered build reference never leave the browser unless the human triggers export or the GitHub draft handoff; no automatic upload.
- Export records a client timestamp, mission identity, 3 step states, rating, note and build reference, but deliberately excludes preview URL (could be a private local address).
- No screenshots, game-state replay, voice recording, or AI-generated missions in this MVP. These need independent consent, evidence contracts and QA gates.

## Review gates

CI checks Python manifest validation, build integrity, JavaScript syntax, and a Chromium synthetic interaction smoke that asserts feedback storage and URL rejection without using a real game preview. Browser smoke is UI evidence, not proof of deployed Game Service Factory, true human usability, Site publication or a newly filed GitHub issue.

## Next milestone

MCC-M2.9.1: approved preview URL registry / PR-diff mission generation and evidence provenance. MCC-M2.9.2: consented screenshot/video capture, issue attachment pipeline and replayable Godot gameplay state.
