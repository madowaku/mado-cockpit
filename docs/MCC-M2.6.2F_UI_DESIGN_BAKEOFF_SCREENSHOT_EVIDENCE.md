# MCC-M2.6.2f UI Design Bake-off / Screenshot Evidence Bridge

This milestone extends [MCC-M2.6.2e Design Intelligence](MCC-M2.6.2E_DESIGN_INTELLIGENCE_UI_SKILL_LAB.md) with **actual browser screenshots**, capture provenance, integrity verification, and contact-sheet comparison. Browser screenshots are visual evidence, not proof of correct UX or model authorship. All design-provider execution and human review remain independent.

## Capture boundary

The existing Lab creates a fixed brief and candidate-specific tasks; the new \`mado_cockpit.design_bakeoff\` bridges the externally built candidate to a local Chromium/Playwright capture.

- Browser capture is **explicitly invoked**, not triggered by catalog intake, planning, review, or CI's regular pytest.
- \`capture\` accepts only \`http://127.0.0.1:PORT/\`, \`http://localhost:PORT/\`, or \`http://[::1]:PORT/\` with explicit port at least 1024. HTTPS, remote domains, credentials, query strings, and fragments are rejected.
- Playwright blocks off-origin HTTP requests, disallows service workers and downloads, and fails capture if external requests or uncaught script errors appear. **Only serve trusted, explicitly reviewed local build output**. Browsers execute page JavaScript, even on loopback.
- A browser must already exist. \`pip install playwright\` and optional browser setup are **operator-controlled**. No npm, remote design AI, MCP, Codex or browser download occurs within the bridge.
- Screenshots use DPR 1, locale \`en-US\`, timezone UTC, reduced-motion mode, disabled screenshot animations and hidden caret. The fixed desktop viewport comes from the immutable experiment plan; mobile is 390 × 844.
- Three original PNG files are required: \`<candidate>.png\` (light), \`<candidate>-dark.png\` (dark) and \`<candidate>-mobile.png\` (mobile). A \`<candidate>.capture.json\` receipt binds each PNG's SHA-256, original source file hash, upstream candidate commit, full experiment-plan SHA-256, browser version, timestamp, URL and capture settings.
- No silent overwrites. Captures with orphan files, mismatched source, broken PNG/CRC, altered receipt or changed experiment are rejected.

An operator-supplied source file hash is a **provenance hint** and does not prove the served URL was built from that exact source, nor that a particular upstream AI was the author. The receipt explicitly records \`provenance: operator_supplied_build\` as an **assertion**; only independent signed build attestations could strengthen it.

## Start an experiment

From an initialized Cockpit, ensure the 53-source catalog is bootstrapped and the fixed-brief plan exists:

\`\`\`sh
python -m mado_cockpit.design_discovery --root . bootstrap
python -m mado_cockpit.design_intelligence_lab --root . plan \
  fixtures/design_intelligence/mcc-m2.6.2e-approval-console.json \
  --candidates superdesign better-design design-taste
\`\`\`

\`plan\` prints \`exp_<digest>\` and the work folder. Each candidate's Codex task remains data-only; generate a candidate UI separately in its own reviewed worktree. External Superdesign / Better Design services may require credentials, remote execution, approvals and payment. The Lab **does not perform** those actions. \`Design Taste\` is an instruction Skill, not a hosted visual model.

Serve a trusted local candidate build, ideally from a local test server:

\`\`\`sh
# Example only. Start the project's existing local frontend server yourself.
# It must listen on 127.0.0.1:8765 and be reviewed before opening in a browser.
python -m mado_cockpit.design_bakeoff --root . capture exp_<digest> design-taste \
  --url http://127.0.0.1:8765/ \
  --source-file path/to/approved/local-ui/index.html \
  --browser-channel chrome \
  --ready-selector '[data-bakeoff-ready]'
\`\`\`

Alternatively use \`--browser-executable /absolute/path/to/chromium\` instead of \`--browser-channel chrome\`; this uses the installed binary without a package/browser download. \`--timeout-ms\` defaults to 15000 (allowed range 1000–60000). The CLI does not launch the local web server for you.

Verify the capture:

\`\`\`sh
python -m mado_cockpit.design_bakeoff --root . verify exp_<digest> design-taste
\`\`\`

Repeat for \`superdesign\` and \`better-design\`, each using its own reviewed output. Use the same locked plan and acceptance requirements.

## Contact sheet and review

\`\`\`sh
python -m mado_cockpit.design_bakeoff --root . sheet exp_<digest> --state light
python -m mado_cockpit.design_bakeoff --root . sheet exp_<digest> --state dark
python -m mado_cockpit.design_bakeoff --root . sheet exp_<digest> --state mobile
python -m mado_cockpit.design_bakeoff --root . compare exp_<digest>
\`\`\`

The contact sheet contains only unmodified actual captured pixels separated by a 12px gutter, in plan candidate order. Its metadata states the candidate ordering, source image hashes, output hash, sheet dimensions and \`visual_contact_sheet_not_quality_assessment\`. For oversized viewports the compositor declines rather than silently rescaling original evidence. Check individual frames and the sheet visually: a screenshot by itself cannot establish interaction correctness.

For a real, independently inspected candidate, write the existing \`mado.ui-compatibility-review.v1\` JSON file as \`<candidate>.json\` into the experiment's \`evidence/\` directory. The review requires eight 0–4 scores, five explicit QA booleans, observed output, human audit label and either an observed numeric USD cost or \`null\` for unknown:

\`\`\`sh
python -m mado_cockpit.design_bakeoff --root . review exp_<digest> design-taste \
  --evaluation-file design-taste.json
python -m mado_cockpit.design_bakeoff --root . compare exp_<digest>
\`\`\`

\`review\` requires an intact local browser capture with \`operator_supplied_build\` provenance and calls the **existing** \`DesignIntelligenceLab.record\`, preserving that ledger and hash checks. \`compare\` also reports capture status per candidate. Its \`capture_complete\` means that all candidate receipts exist and are marked operator supplied, **not** that provider authorship is independently proven. Scores remain unauthenticated human assertions; \`release_approved\` is always \`false\`. No agent is auto-promoted by being the score leader.

For any production UI import, continue using Component Foundry's human-reviewed source reference, actual license grant evidence, source edit review and PNG visual QA. This does not bypass the separate Human Control Lease or permission checks.

## Reproducible real-browser CI proof

The workflow [Design Bake-off Browser Proof](../.github/workflows/design-bakeoff-browser-proof.yml) is an **explicit test-only** pipeline. It installs Python Playwright only in that CI job, uses a preinstalled Chrome/Chromium when available, serves [an original local fixture](../fixtures/design_bakeoff/approval-console-smoke.html), captures three states for each of the three candidate labels, verifies PNG bytes and builds light/dark/mobile sheets. The job publishes the screenshots and capture JSON as the \`bakeoff-real-browser-fixture-proof\` artifact.

**This is a harness test, not a provider bake-off.** Every candidate screenshot in this test is deliberately captured from the same hand-authored fixture and tagged \`fixture_smoke\`. Scoring or claiming successful external skill runs from these fixtures is prohibited by the bridge; the comparison remains incomplete, unreviewed and not release-approved.

Run manually from repository root after installing Playwright and a browser:

\`\`\`sh
python scripts/design_bakeoff_browser_smoke.py --browser-executable /usr/bin/chromium
\`\`\`

The CI artifact is the verifiable example of genuine browser rendering. No Superdesign/Better Design subscription, model billing or image generation is used.
