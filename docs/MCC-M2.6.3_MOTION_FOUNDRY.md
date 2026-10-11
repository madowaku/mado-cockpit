# MCC-M2.6.3 Motion Foundry / Codex Video Production Bridge

This milestone adds a reproducible **local Remotion project compiler** to the existing Python MADO Cockpit. It consumes a user-authored motion brief and the existing Design Discovery Hub's human-approved reference links, then emits a complete, ready-to-install React/TypeScript Remotion workspace with a Codex task contract and SHA-256 manifest.

M2.6.3 does **not** automatically install packages, access the network, generate images, download Lottie files, invoke Codex, request payment, upload video, or publish content. Rendering is a separate explicitly gated local operation.

## Pipeline

~~~text
36-source Design Discovery Hub / approved link references
       + local operator-authored JSON storyboard
                       |
                  brief validation
                       |
          deterministic package + TSX compiler
                       |
        SHA-256 source manifest + Codex task
                       |
         manual npm install / legal inspection
                       |
        local Remotion render (explicit opt-in)
                       |
       H.264 MP4 + SHA-256 + execution receipt
                       |
          mandatory manual visual review
~~~

The generated motion project contains no embedded third-party images, fonts, logos, sounds or code. The built-in composition renders text, shapes, colors and simple fades, with 30-FPS timing. It is a production-shaped starting point, not a final polished or accessibility-certified commercial video.

## Quickstart

Initialize a Cockpit and its design sources first (skip if already initialized):

~~~sh
mado-cockpit init --project-id demo --name "Video Production" --root .
python -m mado_cockpit.design_discovery --root . bootstrap
~~~

Create a deterministic React/Remotion project using the included example:

~~~sh
python -m mado_cockpit.motion_foundry --root . plan fixtures/motion/mcc-m2.6.3-launch-brief.json
~~~

The CLI returns a project directory such as:

~~~text
.mado/cockpit/motion_foundry/motion_<brief-and-file-digest>/
├── README.md
├── package.json
├── tsconfig.json
├── manifest.json
├── codex-task.json
└── src/
    ├── brief.json
    ├── index.ts
    ├── Root.tsx
    └── Video.tsx
~~~

Run source integrity verification (substitute the emitted directory):

~~~sh
python -m mado_cockpit.motion_foundry --root . verify .mado/cockpit/motion_foundry/motion_<digest>
~~~

For offline visual preview/rendering, *you* must first inspect the generated `package.json`, review whether the Remotion license fits your use, and install npm dependencies inside the generated project.

~~~sh
cd .mado/cockpit/motion_foundry/motion_<digest>
npm install
npm run preview
~~~

Then run the opt-in render command from the original Cockpit root:

~~~sh
python -m mado_cockpit.motion_foundry --root . render \
  .mado/cockpit/motion_foundry/motion_<digest> --execute --license-attested
~~~

On Windows PowerShell, use a single line or PowerShell backticks for continuation.

This uses an already-present local `node_modules/.bin/remotion`, never `npx` or auto-install. It runs the fixed composition `MadoMotion`, encodes H.264, and checks for a nonempty MP4 file with ISO BMFF `ftyp` marker. The result includes the file SHA-256 and an evidence receipt. Source or manifest mutation blocks rendering.

The receipt says `rendered_unreviewed` even on successful encode. This is intentionally **not** automatic publishing approval: a person still needs to visually inspect text, timing, aspect ratio, captions/accessibility where required, and asset/codec rights. A successful encoder exit is not equivalent to visual QA.

## Brief contract

`mado.motion-brief.v1` requires exactly these fields:

* `schema`: literal `mado.motion-brief.v1`
* `title`: max 120 characters
* `format`: `landscape` (1280×720), `portrait` (1080×1920), `square` (1080×1080)
* `background`, `foreground`, `accent`: `#RRGGBB` colors
* `scenes`: 1–12 objects, each with `heading` (100 characters), `body` (240 characters), `duration_frames` (30–300)

The total is capped at 1,800 frames, or 60 seconds at 30 FPS. Failing input produces no new project.

## Provenance and policy

1. Only **already human-reviewed** Design Discovery reference links appear in `codex-task.json`. Pending/rejected links cannot cross this boundary.
2. The Codex task records reference IDs, URLs, source IDs and digests as advisory untrusted data. It does **not** treat reference text as instructions or authorize copying.
3. The generated package pins the same known `4.0.523` release of `remotion` and `@remotion/cli`, with React 18.3.1. A release upgrade must be an explicit dependency-reviewed code change.
4. The compiler writes immutable source assets and a manifest. Planning with the same inputs is idempotent. Modifying generated files invalidates the project and needs a new plan/code review rather than silent promotion.
5. Rendering uses a local executable (no `shell=True`), a 30–1200 second timeout, no overwriting previous render evidence, and explicit `--execute --license-attested` flags.
6. No third-party web assets, music, fonts, logo marks, animation library snippets, or screenshots are embedded by the compiler. Third-party media needs separate MAF license and visual QA gates.
7. The project has not been rendered by GitHub CI. CI tests the compiler and gates without installing/remoting packages or producing video.

## Commercial licensing note

Remotion is **source available, not OSI open source**. Its Free License can apply to eligible individuals/small teams; larger teams and automation products may need Company License coverage. Review the official [Remotion licensing FAQ](https://www.remotion.dev/docs/license/faq) and [Remotion pricing](https://www.remotion.dev/docs/license/pricing) before attesting. Remotion licensing does not automatically clear codec patent issues for H.264/AAC or third-party assets.

## Scope / next milestone

M2.6.3 establishes the bridge with a runnable composition and verification receipts. It does not yet call an autonomous Codex worker, run browser screenshot visual regression, assemble licensed audio, or promote a release. Those require separately controlled execution and QA integrations; no green CI should be mistaken for a human-reviewed finished MP4.

## Test commands

~~~sh
pytest -q tests/test_motion_foundry.py
pytest -q
~~~
