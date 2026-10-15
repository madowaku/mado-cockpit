# MCC-M2.6.2e Design Intelligence / UI Skill Compatibility Lab

This milestone turns ten public UI/design repositories into a **pinned, metadata-only compatibility catalog** with separate benchmark tracks for **design skills** and **component libraries**. No external repository code is downloaded, installed, fetched, executed, imported into the browser, or connected to MCP by this module.

## Pinned sources (checked 2026-10-15)

| ID | GitHub | Role | License classification | Important boundary |
| --- | --- | --- | --- | --- |
| superdesign | [superdesigndev/superdesign-skill](https://github.com/superdesigndev/superdesign-skill) | design_skill | MIT skill | CLI/cloud design generation, potential cost, account and privacy review |
| better-design | [marvkr/better-design](https://github.com/marvkr/better-design) | design_skill | MIT repo | Connects to Better Design MCP, remote/API approval is separate |
| design-taste | [madebymustafa/design-taste](https://github.com/madebymustafa/design-taste) | design_skill | MIT | Static instruction skills, not automatically trusted commands |
| canvas-ui | [DavidHDev/canvas-ui](https://github.com/DavidHDev/canvas-ui) | component | **MIT + Commons Clause** | Redistribution as standalone components restricted; experimental HTML-in-canvas fallback |
| paper-shaders | [paper-design/shaders](https://github.com/paper-design/shaders) | component | Apache-2.0 | Preserve LICENSE and NOTICE for redistribution |
| ui-layouts | [ui-layouts/uilayouts](https://github.com/ui-layouts/uilayouts) | component | MIT | React, Tailwind, Motion and package-version compatibility |
| hyperiux | [Hyperiux-Immersion-Labs/hyperiux-components](https://github.com/Hyperiux-Immersion-Labs/hyperiux-components) | component | **Hyperiux Effects License** | CLI MIT differs from effect source license; Pro subscription and no standalone source redistribution |
| motion-primitives | [ibelick/motion-primitives](https://github.com/ibelick/motion-primitives) | component | MIT | React + Tailwind + Motion runtime setup |
| cursify | [ui-layouts/cursify](https://github.com/ui-layouts/cursify) | component | **unverified** | No root LICENSE identified at pinned commit; license evidence mandatory |
| trickle | [akaieuan/trickle-UI-kit](https://github.com/akaieuan/trickle-UI-kit) | component | MIT components; demo terms separate | CSS text motion, demo content not automatically cleared |

Each catalog item records an upstream full 40-character commit SHA verified at the time of this milestone. These are **inspection anchors**, not a claim that current upstream remains unchanged. Verify individual paths, package metadata and applicable rights before reuse. A repo root's license does not necessarily cover all downloaded dependencies, artwork, media, Pro products or embedded components.

**Design Discovery Hub** now has 53 curated entries, after nine new source IDs were added. The existing \`hyperiux-vault\` source is reused rather than duplicated. Historical catalog fingerprints 10, 18, 28, 36, 42, 43 and 44 remain eligible for strict migration; already-reviewed references retain their IDs, original content SHA-256 and audit trail. Registering a source gives it **link-only** status with unverified rights.

## Read-only preflight

\`\`\`sh
python -m mado_cockpit.design_discovery --root . bootstrap
python -m mado_cockpit.design_intelligence_lab --root . catalog
python -m mado_cockpit.design_intelligence_lab --root . catalog --role design_skill
python -m mado_cockpit.design_intelligence_lab --root . catalog --query shaders
python -m mado_cockpit.design_intelligence_lab --root . probe --package-file path/to/frontend/package.json
\`\`\`

The optional probe reads a local npm package manifest only. It does not run \`npm\`, \`npx\`, \`git\`, browsers or any external tools. It cannot certify GPU features or Node, CSS, React and browser compatibility by itself. Without a package manifest the result is explicitly \`manifest_not_provided\`.

## Fixed-brief comparison (design skills only)

\`\`\`sh
python -m mado_cockpit.design_intelligence_lab --root . plan \
  fixtures/design_intelligence/mcc-m2.6.2e-approval-console.json \
  --candidates superdesign better-design design-taste
\`\`\`

A deterministic \`.mado/cockpit/design_intelligence/exp_<digest>/\` folder contains \`plan.json\` and three JSON task handoffs. Every task uses the same brief, acceptance criteria and viewport (1280×800). It is **not an agent run**. The tasks explicitly require a separately authorized isolated worktree, review of any cost/network/credential implications, and actual screenshot capture.

The component track is independent. To evaluate source integration complexity instead, use:

\`\`\`sh
python -m mado_cockpit.design_intelligence_lab --root . plan \
  fixtures/design_intelligence/mcc-m2.6.2e-approval-console.json \
  --candidates motion-primitives trickle
\`\`\`

Mixing a component library and a design skill in one ranked experiment is rejected, so a text-prompt design tool is never treated as equivalent to a React animation component.

## Human evidence and comparison

After **external** authorized work, place a genuine screenshot named \`<candidate>.png\` into the experiment's \`evidence/\` directory. It must match the fixed viewport. Place a human reviewer-supplied \`<candidate>.json\` adjacent to it:

\`\`\`json
{
  "schema": "mado.ui-compatibility-review.v1",
  "actor": "human:reviewer",
  "note": "Verified actual rendered output against the shared brief",
  "scores": {
    "hierarchy": 3, "typography": 3, "layout": 3, "interaction": 2,
    "accessibility": 3, "responsive": 3, "performance": 2, "brand_fidelity": 3
  },
  "checks": {
    "keyboard": true, "touch": true, "reduced_motion": true,
    "theme": true, "responsive": true
  },
  "observed_output": "Describe precisely what was actually observed on screen.",
  "cost_usd": null
}
\`\`\`

Scores must be integers 0–4; missing items or out-of-range values are rejected. \`cost_usd: null\` means *unknown*, not free. The normalized weighted score uses hierarchy(2), typography(2), layout(2), interaction(2), accessibility(3), responsive(2), performance(1) and brand fidelity(3).

\`\`\`sh
python -m mado_cockpit.design_intelligence_lab --root . record exp_<digest> design-taste \
  --screenshot design-taste.png --evaluation-file design-taste.json
python -m mado_cockpit.design_intelligence_lab --root . compare exp_<digest>
\`\`\`

The score is **a human assertion** and \`human:<id>\` is an audit label, **not an authenticated identity**. The program hashes evidence and refuses to overwrite records; modifying an already-reviewed screenshot or JSON makes comparison fail. Without actual evidence, the result remains \`not_evaluated\`. Comparison is never a release gate: \`release_approved\` is always false.

## Production adoption

Reuse \`ComponentFoundry\` for **reference approval → separately verified license evidence → Codex handoff → real browser PNG visual QA → explicit human release review**. Skill-only instructions are never promoted to source-code licensing. For component source, verify applicable license **per component**, dependencies, and redistribution purpose. For Canvas UI, Hyperiux Effects and Cursify specifically, do **not** translate an upstream license label into blanket permission to redistribute a component library.

## Current evidence boundary

This milestone includes ten verified repository identities and pinned git HEAD values, full static metadata registration, CI unit tests, offline stack probing, fixed brief task compilation, review receipts and deterministic comparison. It does **not** include actual Superdesign/Better Design runs, MCP calls, end-to-end browser screenshots, pricing measurements or externally performed visual reviews. Actual comparative quality remains unknown until evidence is supplied.
