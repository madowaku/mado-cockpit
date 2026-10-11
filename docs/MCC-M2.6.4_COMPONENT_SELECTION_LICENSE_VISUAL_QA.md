# MCC-M2.6.4 Component Selection / License Evidence Gate / PNG Visual QA

This milestone connects the **42-source Design Discovery Hub** to a deterministic, evidence-gated Codex UI implementation workflow. The implementation lives in `mado_cockpit.component_foundry` and has **no new runtime dependencies**.

## Pipeline

```text
Design Discovery Hub: 42 sources
        |
  reviewed_reference only
        |
shortlist(query): deterministic relevance, untrusted links only
        |
nominate: immutable selected reference + intended prototype/production usage
        |
license: human-reviewed local evidence file + explicit scope flags
        |
task: Codex-friendly, data-only JSON brief, no agent execution
        |
external Codex edit / manual Playwright screenshot capture
        |
qa: real pixel-by-pixel 8-bit PNG comparison + magenta difference PNG
        |
review: human visual signoff, bound to screenshot + license hashes
```

A reference approved by Design Discovery is **not** licensed code or an approved import. The license gate is separate. An asserted `human:<id>` audit actor is **not authenticated** by this CLI; production automation must bind the audit assertion to authenticated Cockpit Human Control Lease and a real authorization channel. A human may still make an incorrect license claim. This workflow is a provenance and review aid, not a legal determination.

## Quickstart

From an initialized Cockpit, bootstrap its existing sources:

```sh
python -m mado_cockpit.design_discovery bootstrap
python -m mado_cockpit.component_foundry shortlist --query "agent button"
```

The shortlist includes only **human-reviewed** Design Discovery references in selectable component categories and never performs a network request. To supply a candidate, first use the existing Design Discovery `add` and `review` actions to bookmark/approve a specific component page. The shortlist presents links for **manual inspection**, not code to execute.

Nominate one approved reference ID:

```sh
python -m mado_cockpit.component_foundry nominate dref_<reference-id> \
  --component "ApproveButton" \
  --goal "Accessible confirmation control for agent actions" \
  --usage prototype
```

The command prints `selection_id: component_<digest>` and a local directory `.mado/cockpit/component_foundry/component_<digest>/`. Nomination is content-addressed and repeatable. A changed brief or reference creates a distinct candidate.

### License evidence is mandatory before Codex handoff

Place the **actual** saved license text, authorization/contract excerpt, or local permission evidence into:

```text
.mado/cockpit/component_foundry/component_<digest>/evidence/license.txt
```

The CLI only reads local plain-text files from that folder. It does not fetch websites and rejects path traversal, symlinks, oversized files, or mutated evidence. The license ID is a classification, **not a determination**: MIT, Apache-2.0, BSD-3-Clause, ISC, CC0-1.0, OFL-1.1, or `custom` for other reviewed grant terms.

After personally checking that the evidence covers the **specific component**, review and attest:

```sh
python -m mado_cockpit.component_foundry license component_<digest> \
  --evidence-file license.txt \
  --license-id MIT \
  --actor human:owner \
  --note "Inspected the applicable component license and dependencies" \
  --commercial --modification --redistribution
```

Only pass scope flags you have checked. For `--usage production`, both `--commercial` and `--redistribution` must be affirmed. Prototype usage may omit those. The review stores an immutable digest of the evidence file and the scope assertion; it does **not** implicitly grant rights. A different license or new evidence requires a new nomination/review workflow rather than mutating an old attestation.

Compile the task:

```sh
python -m mado_cockpit.component_foundry task component_<digest>
```

This produces `codex-task.json` with source URL and digest, desired component, goal, usage, reviewed scope, and security/QA requirements. No Codex job, npm installation or external process is started. Review the task before providing it to a Codex worker in its own isolated worktree.

### Real visual regression, no external dependencies

After the Codex worker changes the UI, capture **baseline** and **actual** screenshots with a *separate* browser harness (for example, Playwright). MCC-M2.6.4 does **not** launch a browser or pretend snapshots were captured. Place non-interlaced 8-bit PNGs in:

```text
.mado/cockpit/component_foundry/component_<digest>/screenshots/
├── baseline.png
└── actual.png
```

For reproducibility, lock viewport/DPR/theme, font loading, test data, animation clock, timezone and reduced-motion preference in your browser capture harness. Standard 8-bit RGB, RGBA and grayscale PNGs with all five PNG row-filter modes are supported; indexed, interlaced, animated and 16-bit PNGs are rejected with an explicit error. Screenshots are capped at 4096×4096 with bounds on byte size and decompression.

Compare exact pixels (zero tolerance is the default):

```sh
python -m mado_cockpit.component_foundry qa component_<digest> \
  --baseline baseline.png --actual actual.png
```

For deliberate visual tolerance, supply `--max-changed-fraction 0.01 --max-mae 2`. Results include exact changed-pixel fraction, mean absolute channel error (0–255), screenshot SHA-256, and a transparent/magenta `qa_<digest>-diff.png` overlay. Dimension mismatches and threshold failures are **machine failures**, never silent passes. Diff report IDs are content-addressed, so iterations and alternative thresholds yield separate immutable receipts.

A machine pass remains `passed_pending_human` until a person views the screenshots/diff and signs off:

```sh
python -m mado_cockpit.component_foundry review component_<digest> qa_<digest> \
  --decision approve --actor human:owner \
  --note "Checked focus ring, text clipping, contrast, reduced motion, and desktop/mobile states"
python -m mado_cockpit.component_foundry status component_<digest>
```

Failed visual QA **cannot** be approved, but can be explicitly rejected with a review note. Acceptance binds to the precise QA receipt, screenshot hashes and license evidence. Modifying any input after QA invalidates later signoff.

## Security and compatibility

- Preserves all 42 existing design resources, their review records, catalog checks and the separate M2.6.3 Motion Foundry. No existing schema is migrated by this new module.
- Only approved reference IDs from the current Design Discovery registry may be nominated. Listing a source from the 42-resource catalog does not alone grant candidate selection.
- Untrusted reference links/titles remain **data**; the pipeline executes no code from a site, copied component, README, or screenshot.
- Human license attestation is scoped to the local evidence file, reviewed rights flags and a particular selection SHA. The software cannot independently certify contract validity, source authorship or downstream library transitive dependencies.
- The standard-library PNG parser validates chunk CRC, dimensions, filters and compressed bounds. Numerical comparison is a regression signal, not accessibility certification, design taste review, or browser functional E2E.
- The module never runs shell commands, npm, Codex, Playwright, browsers, scraping or network requests. External capture/implementation remain separate with existing worktree, action gateway and human control policies.
- Evidence files are immutable at the workflow level and digest-checked. SHA-256 is **not an authenticated signature** against an attacker able to rewrite all files. The actor prefix is an audit assertion only.
- For a complete release, also require keyboard/a11y testing, mobile viewport checks, dependency SBOM and license inspection, and browser visual review of all relevant states.

## Acceptance

```sh
pytest -q tests/test_component_foundry.py
pytest -q
```

Test coverage includes shortlist filtering, immutable nomination, reference provenance, license blocks, production scope enforcement, actor controls, Codex task synthesis, PNG decoding of all five scanline filters, pixel comparisons, tolerance threshold behavior, failed QA rejection, screenshot tamper detection and review immutability.
