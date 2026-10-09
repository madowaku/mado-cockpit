# MCC-M2.7 OhMyGame Intake / Cross-Engine Game Use Bridge

Status: **fixture-verified; live game engine not verified**  
Date: 2026-10-09

Source review: [WhiteTowerAI/ohmygame at 286d1ea](https://github.com/WhiteTowerAI/ohmygame/tree/286d1ea485ae631fcb226f87f6008c21c76dac40), Apache-2.0.

## Context

OhMyGame publicly defines `GameRuntimeAdapter`, `GameUseCapabilities`, and `open/inspect/act/capture/close` in [src/shared/playtest.ts](https://github.com/WhiteTowerAI/ohmygame/blob/286d1ea485ae631fcb226f87f6008c21c76dac40/src/shared/playtest.ts). Its live implementation currently uses a desktop IPC route. The upstream type also reserves Godot and Unity runtimes, but **the presence of runtime names does not mean those engines are already supported by upstream**.

MCC-M2.7 independently implements a Python contract, and **does not** copy OhMyGame implementation code, launch its Electron application, or talk to its private IPC.

## Shipped

- `GameUseController`: runtime checks, `open`, `inspect`, `act`, `capture`, `close`, and strict action/capability validation.
- `GameCapabilities`: `web`, `godot`, `unity` declarations, separate input/observation/determinism support.
- `DeterministicFixtureAdapter`: no browser or engine process, seeded deterministic state, input log, reset and step.
- `LocalJsonAdapter`: optional localhost-only HTTP JSON sidecar transport with explicit port, bounded payload size, timeout, and redirect refusal.
- `run_scenario`: snapshots, assertions, SHA-256 evidence, PNG captures, failure manifest and `finally` cleanup.
- `tests/test_game_use_bridge.py`: 9 isolated unit/integration tests, including real loopback HTTP transport to a fake game runtime.

### Sidecar wire contract

```text
HTTP POST http://127.0.0.1:<port>/game-use
request:  {"operation":"open","target":{"runtime":"web","url":"http://127.0.0.1:4173/"},"viewport":{"width":1280,"height":720}}
response: {"operation":"open","snapshot":{"runtime":"web","sessionId":"s1","viewport":{"width":1280,"height":720}}}
```

Operations: `open`, `inspect`, `act`, `capture`, `close`. The adapter requires the custom engine sidecar to implement them; **no real Web/Godot/Unity sidecar is bundled yet**.

Live `open` and `act` are denied unless the caller provides an explicit policy authorizer. Real deployment must integrate this with the existing `ActionPolicyGateway`, revalidation and human-control lease. A callback that simply approves every action is suitable only for test fixtures, not production. The local HTTP endpoint is not an authenticated public service.

## Try it with zero AI/API cost

```bash
python -m pip install -e '.[dev]'
python -m mado_cockpit.game_use_bridge fixtures/game_use/mcc-m2.7-smoke.json --fixture web
pytest -q tests/test_game_use_bridge.py
```

Evidence is written to the Git-ignored `.mado/game-use/<run-id>/` folder. Its `manifest.json` contains every snapshot and its digest; `capture_*.png` has a separate SHA-256 digest. This evidence can be handed to `EvidenceManager.submit_result` after assignment to a worker workspace. **Fixture screenshots are 1x1 test images, not proof of visual game quality**.

## Acceptance

- [x] One controller contract for Web/Godot/Unity **fixtures**
- [x] Reproducible seed, step, reset and assertion checks
- [x] PNG/evidence SHA-256, cleanup on failure
- [x] Local sidecar transport test and live default-deny
- [ ] Real Phaser game automation and screenshots
- [ ] Godot/Unity executable adapter
- [ ] Live ActionPolicyGateway dispatch and human-control lease integration
- [ ] Human visual QA

Next: **MCC-M2.8 Real Playable Sidecar / Evidence Handoff**. Use one local Phaser game for actual keyboard+render proof before attempting Godot and Unity. Avoid engine installer dependencies in the Cockpit core.
