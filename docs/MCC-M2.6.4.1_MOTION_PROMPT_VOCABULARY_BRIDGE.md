# MCC-M2.6.4.1 Motion Prompt Intake / Visual Motion Vocabulary Bridge

This milestone adds an **offline, content-hash-pinned** reference vocabulary for
[Shohei Ohtaki's Motion Prompt](https://github.com/showheyohtaki/motion-prompt)
and a **data-only** handoff to the existing MCC-M2.6.3 Motion Foundry.

It does **not** replace MCC-M2.6.4 Component Selection / License / Visual QA,
which is an existing, different milestone. It does not automatically install the
third-party agent skill, execute Canvas JS, generate footage, call Codex, invoke a
browser, fetch remote scripts, install dependencies, or approve a release.

## Pipeline

~~~text
Operator fetches exact upstream api/v1/catalog.json
  -> operator records SHA-256 (local, no implicit network)
  -> validate source host, full ID/pack/category/geometry and metadata contract
  -> immutably store normalized metadata and both hashes
  -> search JA / EN -> selected #NNN + live demo links
  -> verify an existing, immutable MCC-M2.6.3 Motion Foundry project
  -> emit separate immutable data-only Codex handoff for a chosen scene
  -> manual implementation, license-scope check and temporal visual QA
~~~

The underlying source is MIT-licensed, © 2026 Shohei Ohtaki.
Preserve upstream attribution. The catalog metadata and its animation source are
different things: this bridge stores only names, descriptions, timing/spec lines and
derived gallery deep links. Any subsequent copy/port of upstream JS or kits must
receive its own rights review. A generated handoff is **not** release approval.

## Quickstart

For an initialized MADO Cockpit with the Design Discovery Hub bootstrapped:

~~~sh
# Operator-initiated upstream download. Review the exact URL and file.
curl --fail --location --silent --show-error \
  https://showheyohtaki.github.io/motion-prompt/api/v1/catalog.json \
  --output motion-prompt-catalog.json

# Linux: sha256sum motion-prompt-catalog.json
# macOS: shasum -a 256 motion-prompt-catalog.json
# Set MOTION_PROMPT_SHA256 to the actual printed 64-character digest.
python -m mado_cockpit.motion_prompt_bridge --root . intake \
  --catalog motion-prompt-catalog.json \
  --expected-sha256 "$MOTION_PROMPT_SHA256"

python -m mado_cockpit.motion_prompt_bridge --root . verify
python -m mado_cockpit.motion_prompt_bridge --root . search --query "スタガー"
python -m mado_cockpit.motion_prompt_bridge --root . search --pack camera --query dolly
python -m mado_cockpit.motion_prompt_bridge --root . get '#002'
~~~

The normal contract is the [upstream v1 static catalog](https://github.com/showheyohtaki/motion-prompt/blob/main/FORMAT.md)
with numbered elements, global pack order, dimensions and cycle lengths.
The source identity is fixed to the official GitHub repo and GitHub Pages URL.
Input must be a normal UTF-8 file, not a symlink, within a 2 MB bound.
The operator-supplied SHA-256 is compared with the file bytes before parsing.
The hash proves **which bytes were reviewed**, not that those bytes came
cryptographically from a particular Git commit. Do not infer a verified commit
signature or version from the hash alone.

You may retain the local downloaded JSON outside git for audit. The smaller
normalized snapshot is stored under .mado/cockpit/motion_prompt/catalog.json;
re-intaking identical source bytes is idempotent. Changed source bytes require
explicit new review and snapshot rotation, not silent overwrite.

## Motion Foundry handoff

First, use the existing **MCC-M2.6.3** motion workflow to produce a source-verified
project, without running Remotion:

~~~sh
python -m mado_cockpit.design_discovery --root . bootstrap
python -m mado_cockpit.motion_foundry --root . plan \
  fixtures/motion/mcc-m2.6.3-launch-brief.json
~~~

Copy the actual generated folder path and choose the zero-based target scene.
Then run:

~~~sh
python -m mado_cockpit.motion_prompt_bridge --root . handoff \
  --project .mado/cockpit/motion_foundry/motion_<digest> \
  --scene-index 0 --ids '#002' '#010' --language ja
~~~

This creates an independent JSON file at
.mado/cockpit/motion_prompt/handoffs/mp_<digest>.json. It contains only the
selected motions in user-specified order, the pin, specs, attribution and
a source-verified project identity. The existing Motion Foundry project remains
byte-for-byte unchanged, as do its source-integrity manifest and Codex task.

Do not treat the handoff as executable instructions. The only authorized next
step is **human review** followed by separate, explicit implementation in a
new change. Scene length, fps, adjacency and content remain fixed.

## Temporal Fidelity and release checks

The handoff includes sample fractions (0%, 25%, 50%, 75%, 99%) as a *QA plan*,
not screenshot evidence. To close review, a separate executor must render the
actual candidate at fixed fps, inspect entrance/exit frames and pacing against
the reference, verify the existing source manifest and render receipt, review
license scope, and collect human visual approval.

Every new handoff starts in visual_review=pending. A successful catalog intake,
deterministic digest, or green unit-test run is **not** evidence of visual fidelity.
No remote animation JS or examples are embedded or auto-run.

## Security and compatibility guarantees

- No network calls in this bridge, no new package dependencies, no external
  execution privileges or changes to existing CLI/worker modes.
- IDs are maintained as *external* three-digit numbers; internal records have
  separate source_id and content-addressed handoff IDs.
- Strict source identities, contiguous IDs, valid categories, pack-local
  numbers, matching geometry/cycle and bounded metadata are checked at intake.
- Only normalized vocabulary/spec data is stored, not original executable
  code fields or remote-provided URLs.
- Local snapshot and handoff are write-once and verified before use; no silent
  replacement of pins or target files.
- The handoff requires a verified Motion Foundry project and refuses a target
  that already has render evidence.
- Keep external content as untrusted data, including human-readable spec lines.

## Verification

~~~sh
pytest -q tests/test_motion_prompt_bridge.py
pytest -q tests/test_motion_foundry.py
pytest -q
~~~

A fully rendered video or screenshot comparison is out of scope for M2.6.4.1.
Follow-on temporal capture must provide real frame receipts and human approval;
until then all visual claims stay pending.
