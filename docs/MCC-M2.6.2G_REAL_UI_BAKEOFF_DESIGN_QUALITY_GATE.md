# MCC-M2.6.2g Real UI Bake-off / Design Quality Decision Gate

This milestone builds on the existing [Design Intelligence Lab](MCC-M2.6.2E_DESIGN_INTELLIGENCE_UI_SKILL_LAB.md) and [Browser Screenshot Evidence Bridge](MCC-M2.6.2F_UI_DESIGN_BAKEOFF_SCREENSHOT_EVIDENCE.md). It accepts **independently produced UI builds**, checks that their local bundle hashes, declared execution trace, pinned agent task, served entrypoint HTML, Chromium screenshots and human review agree, and emits an explicitly **non-deploying** human selection decision.

It does **not** run Superdesign, Better Design, Design Taste, Codex, npm, MCP or an external design provider. Tool access, cost approval and privacy/credential review belong to the operator. No actual provider winner is claimed until genuine operator-submitted run evidence and browser captures exist.

## Evidence flow

```text
MCC-M2.6.2e: pinned task + fixed UI brief
            ↓
Externally authorized provider/skill execution in separate worktree
            ↓
run declaration JSON + execution trace + static build directory
            ↓
MCC-M2.6.2g intake: hash all local build files, trace and task
            ↓
MCC-M2.6.2g capture-local:
  serves only that reviewed local build on 127.0.0.1 at a random port
            ↓
MCC-M2.6.2f Playwright screenshot receipt:
  served HTML SHA-256 + rendered light/dark/mobile PNGs + browser DOM audits
            ↓
MCC-M2.6.2e human score/QA evidence, separately reviewed
            ↓
MCC-M2.6.2g report/seal: hold, tradeoff, or recommendation
            ↓
MCC-M2.6.2g select: optional human preference, NOT release authorization
            ↓
Existing component license gate + real visual QA + authenticated Human Control Lease
            ↓
Separate production release process (not part of this milestone)
```

## One real provider-run submission

Start with an initialized Cockpit, run `design_discovery bootstrap`, and create the same fixed-brief plan for **superdesign**, **better-design** and **design-taste**. Record the returned `exp_<digest>` directory.

Each independently produced candidate requires a completed external run, reviewed generated frontend `dist/` (with an `index.html` at its root and no credentials or symlinks), its own trace text file, and a declaration JSON. Never paste credentials, account tokens or private prompts into these files.

Example **schema**, not evidence of an actual run:

```json
{
  "schema": "mado.ui-real-run.v1",
  "experiment": "exp_REPLACE_WITH_REAL_ID",
  "candidate": "design-taste",
  "task_sha256": "REPLACE_WITH_SHA256_OF_TASK_JSON",
  "upstream_commit": "c4a6bff0871eb4b15371b0e7d2751628b0ed4608",
  "execution_mode": "design_taste_skill",
  "run_id": "local-session-your-real-id",
  "operator": "human:operator",
  "command_summary": "Ran reviewed Design Taste instructions in the isolated UI worktree",
  "output_revision": "REPLACE_WITH_40_HEX_GIT_REVISION",
  "cost_usd": null,
  "duration_seconds": 140.5,
  "status": "completed"
}
```

Use the actual full 64-character SHA-256 of `tasks/design-taste.json` from this experiment, the actual git revision of the local output, and an actual measurement of duration/cost. `null` cost means *unknown*, not free.

The accepted execution mode must match its candidate:
- `superdesign`: `superdesign_cli` (operator-run CLI, potentially remote and billable)
- `better-design`: `better_design_mcp` (operator-approved MCP)
- `design-taste`: `design_taste_skill` (operator-applied local skill)

A special `manual_baseline` mode is available **only for visual harness testing**. It captures as `fixture_smoke` and is blocked from provider quality selection. Merely naming a paid provider in a declaration does **not** prove execution; this is an operator-attested manifest and output revision, not an authenticated provider record.

To hash and intake a candidate's build:

```sh
python -m mado_cockpit.design_quality_gate --root . intake \
  exp_<digest> design-taste \
  --declaration path/to/design-taste-run.json \
  --bundle path/to/reviewed/build/dist \
  --trace path/to/redacted-run-trace.txt
```

The bridge hashes each file in `dist/`, caps total files and bytes, refuses symlinks, .git, node_modules, and secret-looking files, and records its own immutable manifest. Neither the build nor the trace is executed during intake. The original local files must remain unchanged and available for verification.

To capture through a local static server **without launching a build process**:

```sh
python -m mado_cockpit.design_quality_gate --root . verify-run exp_<digest> design-taste
python -m mado_cockpit.design_quality_gate --root . capture-local exp_<digest> design-taste --browser-channel chrome
```

Playwright is optional and must have been installed by the operator. The supplied build JavaScript **does execute inside the local browser** while capturing, so it must be reviewed and trusted first. The static server uses a loopback-only, OS-allocated ephemeral port. The original entrypoint's SHA-256 must match the bytes served to Chromium. All build files are reverified afterward. No external provider service is started by this code.

The screenshot receipt includes three resolutions/styles and lightweight DOM smoke signals for each state: document language, main landmark, H1, at least one named focusable control, no major horizontal overflow, and reduced-motion media active. These are **necessary screening signals, not WCAG certification or automated interaction testing**. Human keyboard/touch/contrast/responsive review remains required.

## Review and decision

Use the existing `mado.ui-compatibility-review.v1` JSON with eight scores (0–4), all five explicit QA booleans, a detailed reviewer note and cost consistent with the actual run's cost declaration, then:

```sh
python -m mado_cockpit.design_bakeoff --root . review \
  exp_<digest> design-taste --evaluation-file design-taste.json
python -m mado_cockpit.design_quality_gate --root . report exp_<digest>
python -m mado_cockpit.design_quality_gate --root . seal exp_<digest>
```

The gate refuses automatic recommendation when:
- Any candidate lacks a recorded run, real browser receipt or human review.
- The run was a `manual_baseline`, any capture is `fixture_smoke`, or entrypoint HTML differs from the pinned build.
- Browser DOM smoke checks fail, or identical screenshot hashes occur under different candidate names.
- Cost is unreported, disagrees with the reviewer, or a candidate fails its human checks.
- A candidate's weighted quality score falls below **75/100**, or accessibility/brand fidelity scores are below **3/4**.

Once all three candidates have evidence, qualified candidates may be ranked for **human consideration**. A provisional recommendation requires the quality leader to beat the second qualified candidate by **at least five points** and cost no more than the second. When quality and cost conflict, the report says `human_tradeoff_required`, without forcing a winner. Candidates that failed a quality gate are shown with exclusion reasons rather than erased.

Report status taxonomy:
- `hold_missing_evidence`: incomplete intake/capture/review
- `hold_duplicate_visual_evidence`: suspicious reused screenshot
- `hold_no_eligible_candidate`: complete evidence, but no candidate meets quality gates
- `human_tradeoff_required`: multiple eligible candidates; cost/quality tradeoff unresolved
- `ready_for_human_selection`: provisional recommendation, still not an approval

Once the evidence is complete, an operator can write a **non-authorizing** preference:

```sh
python -m mado_cockpit.design_quality_gate --root . select exp_<digest> \
  --candidate design-taste --actor human:owner \
  --note "Personally inspected the three real renderings, evidence and cost tradeoffs."
```

The gate stores a content-addressed immutable quality report (versioned as evidence grows) and binds the human preference to the report hash. It never deploys code, grants production rights or asserts the `human:...` string is authenticated. A subsequent real production release still requires a separate validated human control lease and license authorization.

## Real-browser CI proof (not a comparison of those three providers)

The existing [Design Bake-off Browser Proof](../.github/workflows/design-bakeoff-browser-proof.yml) workflow now runs **two honest smoke tests**:

1. The original single-page smoke fixture, captured into three candidate slots to exercise image pipeline compatibility. All images are explicitly `fixture_smoke`.
2. **Three different original UI directions**: editorial, dense operations and calm system. They use real original HTML/CSS builds and genuine headless Chromium capture in light/dark/mobile, producing nine screenshots and three contact sheets. Each is registered as `manual_baseline` and the decision gate must return `hold_missing_evidence` with **no winner**.

The three UI directions are genuinely different screenshots but were **not generated by Superdesign, Better Design or Design Taste**. The test cannot establish provider ranking or costs. It verifies local rendering, source/screenshot integrity, distinct capture hashes, immutable reports, and the absence of a way to confuse fixtures with provider results.

The workflow uploads two separately named artifacts. The second, `bakeoff-manual-directions-decision-proof`, contains its build sources, 9 PNGs, light/dark/mobile contact sheets and the sealed hold report. This is useful for visually inspecting the process without requiring paid model runs or any external service.

## Known limits

- Execution logs, output Git commit, provider identity, human reviewer identity and cost are **locally asserted evidence**, not signed vendor attestations. SHA-256 protects the submitted local files against subsequent changes, but cannot certify who authored them.
- Only the served HTML bytes are compared to the entrypoint on disk. Linked assets are guarded by the manifest and local static server, but per-request subresource SHA checks and signed build provenance are future improvements.
- The screenshots are static observations. Real functionality, assistive-technology behavior, user comprehension and contrast require manual and/or specialized testing.
- No authenticated release API is wired into this prototype quality selector. `release_approved` stays false even after a human preference.
