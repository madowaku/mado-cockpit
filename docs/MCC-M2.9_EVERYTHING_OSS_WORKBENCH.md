# MCC-M2.9 Everything OSS Workbench / Creative Tool Intake & Compatibility Gate

## Scope
This opt-in prototype adds an independent, stdlib-only adapter under `mado_cockpit.everything_workbench`. Existing Cockpit UI, gateways, policies and tools are unchanged. No HeyPuter code is vendored. Production deployment is **not** authorized by this milestone.

## Candidates
| ID | Workflow | License observed at intake | Node guidance |
| --- | --- | --- | --- |
| photo-studio | MAF image finishing | MIT | >=22.12 |
| 3d | MGSF model/scene editing | MIT | 24 LTS |
| video-studio | MAF video finishing | AGPL-3.0-only | >=22.12 |
| whiteboard | MCC visualization | AGPL-3.0-only | >=22.12 |

These are source-review observations, not legal advice. Recheck the exact upstream commit, transitive dependencies, network calls and bundled assets before redistribution. AGPL candidates must stay separate pending legal review. Do not treat a repository root license as a blanket license.

## Usage
1. In a **disposable VM/container** with network policy enforced externally, manually clone `https://github.com/HeyPuter/everything` and pin the full commit SHA. Record that SHA alongside evidence. Never run unreviewed installers on the primary workstation.
2. Run `python -m mado_cockpit.everything_workbench catalog`.
3. Run `python -m mado_cockpit.everything_workbench inspect --checkout /path/to/everything --app photo-studio --output photo-inspect.json`.
4. Only in the disposable environment, review dependencies, then run `npm ci` inside that app's directory. Note: npm install scripts may execute third-party code. Restrict network and secrets before doing this.
5. To execute the allowlisted test/build commands, add `probe --approve-execution --checkout /path/to/everything --app photo-studio --command-index 0 --output photo-test.json`. The probe **does not install**, clone, launch a browser or collect screenshots.

The evidence JSON includes source digest, license status, command, bounded outputs and result. CLI `probe` is a local human-triggered smoke step, **not a sandbox**: isolation must be provided by an external container or VM.

## Required acceptance gates
- A: no automatic network, clone, install, or remote execution; missing files and symlinks fail closed
- B: upstream commit pinned and per-app licenses plus dependencies reviewed separately
- C: `npm test` and `npm run build` pass independently in quarantine
- D: a human reviews Playwright screenshots, console logs, file import/export and artifact handoffs
- E: Visual Evidence captures version, timestamp, screenshot paths and file hashes before any Cockpit gallery integration
- F: no merger into main or production tool tile before A through E, especially with AGPL candidates

## Deferred
Visual Evidence capture, app launch buttons, file handoff and Cockpit UI integration require real browser dogfood on the Windows host. This milestone supplies the compatibility/evidence contract only and reports those features as **not implemented**.
