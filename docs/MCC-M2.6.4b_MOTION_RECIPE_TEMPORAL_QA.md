# MCC-M2.6.4b Motion Recipe Registry / Temporal Fidelity QA

This is a non-breaking extension of **MCC-M2.6.3 Motion Foundry**. The suffix `b` avoids a collision with the existing `MCC-M2.6.4_COMPONENT_SELECTION_LICENSE_VISUAL_QA.md` for UI components.

## Pipeline

```text
Verified M2.6.3 Remotion plan + curated recipe reference
                        |
         immutable content-addressed selection
                        |
  external, operator-controlled PNG capture at frame indices
                        |
       offline pixel + dimension differential QA
                        |
      immutable time-indexed SHA-256 QA receipt
                        |
       optional asserted human visual review
                        |
          NOT CLEARED for publication
```

The initial registry contains **four reference-only recipes** drawn from [Studio Yebisu's motion guide](https://github.com/studio-yebisu/awesome-claude-motion-design-ja) and [Motion Reel](https://github.com/studio-yebisu/motion-reel): a Remotion title reveal, HTML Canvas card morph, HyperFrames HTML promo and Motion Canvas explainer. The catalog is intentionally smaller than the upstream list, which may grow. Only the Remotion recipe maps to the existing M2.6.3 engine. Others are *research-only* and do not pretend to have executable adapters.

## Usage

Initialize Cockpit, bootstrap Design Discovery and plan a verified motion project as described in [M2.6.3](MCC-M2.6.3_MOTION_FOUNDRY.md).

```sh
python -m mado_cockpit.motion_recipe --root . list
python -m mado_cockpit.motion_recipe --root . select \
  .mado/cockpit/motion_foundry/motion_<digest> remotion-title-reveal
```

A `recipe_<digest>` selection is written beneath `.mado/cockpit/motion_recipe/selections/`. No M2.6.3 source or manifest is changed. The operator must separately check engine licensing, dependencies and media rights. Selecting a reference grants none of those rights.

Capture PNGs externally with a pinned browser, resolution, DPR, fonts, timezone, animation clock, input data and engine version. Name frames using zero-based six-digit indices, e.g. `frame_000030.png`; keep **baseline** and **actual** captures in separate directories. The default sampling includes scene starts, +12 frames, midpoints, ends-13, and final scene frames. Custom samples can target exact cuts and transitions. For an 8-second 30fps title, the last frame is 239.

```sh
python -m mado_cockpit.motion_recipe --root . qa recipe_<digest> \
  ./captures/baseline ./captures/actual --frames 0,30,60,120,180,239
# Documented tolerance, only if intentionally allowed:
python -m mado_cockpit.motion_recipe --root . qa recipe_<digest> \
  ./captures/baseline ./captures/actual --max-changed-fraction 0.01 --max-mae 2
```

QA **does not launch browsers, download frames, or generate video**. It reuses the existing bounded, standard-library PNG parser and pixel comparison in `component_foundry`. Dimension mismatches, changed fraction, and mean absolute RGBA channel error are evaluated. Results bind sample time (frame/fps), both screenshot digests, expected project dimensions, numeric thresholds, and the project manifest SHA. Machine pass is `passed_pending_human`, fail is `failed`; a failed QA exits 1, missing/invalid evidence exits 2.

An actual human who has reviewed the snapshots may make an unauthenticated audit assertion:

```sh
python -m mado_cockpit.motion_recipe --root . review tqa_<digest> \
  --actor human:owner --note "Reviewed timing, typography and safe areas"
```

Review rechecks each image SHA-256 and rejects failed or modified receipts. `human:<id>` is **not authenticated identity**. Visual signoff records `visual_approved_not_release_cleared` and is not permission to publish.

## Claims and limits

- The QA receipt proves only **sampled PNG pixel fidelity** within a controlled capture environment, *not* semantic video correctness.
- It does **not** verify MP4 decode, actual audio synchronization, visual quality of the full sequence, font portability, accessibility, asset licensing or distribution rights.
- The registry stores links and short purpose descriptions as advisory **untrusted data**. No code, animations, music, models or fonts from the upstream project are vendored or executed.
- Receipt IDs and project/source hashes enable tamper detection inside this workflow, not authentication against an attacker able to rewrite the entire evidence store.
- This uses no additional runtime dependencies. PNG size/dimension caps and the at-most-72-frame sample bound limit resource use.
- The existing M2.6.3 source integrity, license attestation and opt-in render gates remain unchanged.

## Acceptance

```sh
pytest -q tests/test_motion_recipe.py tests/test_motion_foundry.py tests/test_component_foundry.py
pytest -q
```

**Next milestone:** an explicit isolated Playwright capture adapter, real FFprobe video-decode inspection, and measured audio event alignment. No passing sampled PNG test should silently promote those unchecked claims.
