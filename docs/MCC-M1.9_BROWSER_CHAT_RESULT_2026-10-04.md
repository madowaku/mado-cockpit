# MCC-M1.9 Browser Chat Result — 2026-10-04

MCC-M1.9 was validated against a fresh real checkout of `CopilotKit/OpenDots@main` using the **normal OpenDots Chat UI**, a local CopilotKit SSE runtime, Chromium, the real MADO tool bridge, and a deterministic OpenAI-compatible model shim.

## Passing run

- Workflow: `OpenDots Browser Chat`
- Run ID: `37176042604`
- Result: `success`
- mado-cockpit commit: `69c894ba734cf944b62e4dc9b773eaa17b700c90`
- Evidence artifact: `opendots-browser-chat-evidence`
- Artifact ID: `11293037094`
- Artifact SHA-256: `1e02a40a7e93f14afb220884df37bf58f4c859e5c0e6126aea504e3233ee53b9`

At the same commit:

```text
Cockpit CI                         99 passed
M1.5 real OpenDots dogfood         success
M1.9 normal Chat browser flow      success
```

## Normal Chat path exercised

The Chromium scenario opened the normal OpenDots root page and used the normal new-conversation composer.

Prompt:

```text
Check MADO mission opr_5c8fd1afe070 and continue safely.
```

The verified path was:

```text
Chromium
  -> OpenDots /
  -> Start a conversation
  -> normal Chat component
  -> /api/copilotkit
  -> local CopilotRuntime in SSE mode
  -> real DotAgent
  -> deterministic OpenAI-compatible shim
  -> mado_check_mission
  -> real MADO Cockpit
  -> normal Mission Card
  -> normal Human Gate frontend tool
  -> normal M1.4 Human Gate card
  -> explicit stay_free click
  -> resumed CopilotKit agent run
  -> mado_answer_human_gate
  -> real MADO Cockpit
  -> final assistant text
  -> independent Python state verification
```

This is the first milestone in the OpenDots series where the browser, ordinary Chat UI, agent loop, Human-in-the-Loop tool result, and Cockpit state transition were all exercised in one path.

## Deterministic model stages

The real server log recorded exactly these M1.9 shim stages:

```text
check_mission
open_human_gate
forward_human_decision
final_reply
```

The generated IDs were propagated through the live flow:

```text
operator_id  opr_5c8fd1afe070
gate_id      gate_7b89e673bfc7
```

The Gate ID was parsed from the real `mado_check_mission` result. It was not hard-coded into the deterministic shim.

## Browser result

The passing browser result was:

```json
{
  "schema": "mado.opendots.browser-chat-e2e.v1",
  "version": "MCC-M1.9",
  "ok": true,
  "operator_id": "opr_5c8fd1afe070",
  "prompt": "Check MADO mission opr_5c8fd1afe070 and continue safely.",
  "human_choice": "stay_free",
  "final_text": "Mission resumed on the free path. Cockpit is ready for Builder work.",
  "browser_errors": []
}
```

The browser intentionally clicked the explicit choice in `.mado-gate-choices`, not the separate safe-default button.

## Persisted Cockpit result

An independent Python check reopened the same Operator after the browser run:

```text
status       awaiting_builder
human_gate   null
next_action  launch_or_wait_for_builder
```

So the durable state transition was:

```text
awaiting_human
  -> explicit stay_free click
  -> mado_answer_human_gate
  -> awaiting_builder
  -> human_gate = null
```

## Visual evidence

The artifact contains:

```text
01-normal-chat-human-gate.png
02-normal-chat-resumed.png
browser-chat-result.json
cockpit-final.json
server.log
```

The first screenshot shows the ordinary OpenDots conversation with:

- the user prompt;
- MADO Mission Card;
- `awaiting_human`;
- Human decision pending;
- the Human Gate question;
- recommendation;
- explicit `stay_free` and `enable_paid` choices.

The second screenshot shows:

- the Human Gate marked Answered;
- `Decision returned to the Dot: stay_free`;
- final assistant text;
- Human decision recorded card;
- `awaiting_builder`.

## Deterministic local runtime

M1.9 does not emulate CopilotKit Intelligence as a fake remote service.

When:

```text
MADO_DETERMINISTIC_CHAT=1
```

the bounded test overlay configures:

```text
CopilotRuntime({ agents })
```

in its normal SSE mode, binds local OpenDots conversations directly into the real `WorkspaceStore`, and routes the Dot's OpenAI-compatible model endpoint back to the test-only local model shim.

The regular production path remains unchanged when the flag is absent.

## Bugs found by M1.9 dogfood

### 1. False-green CI through tee

The first browser workflow piped Playwright and Python verification through `tee` without `pipefail`.

That allowed a failing browser process to be hidden by a successful `tee` exit status.

M1.9 now uses:

```text
set -o pipefail
```

for every piped verification step and dumps the server log on failure.

This turned the apparent green run into a correctly failing diagnostic run and prevented false evidence promotion.

### 2. DotAgent still required an Intelligence key

Switching Platform to local SSE mode was not enough. The real OpenDots `DotAgent.run()` had an independent startup guard requiring:

```text
intelligenceKey
apiKey
model
```

This caused the normal Chat run to return no assistant message before the deterministic model endpoint was reached.

The M1.9 overlay now relaxes only the Intelligence-key part when:

```text
MADO_DETERMINISTIC_CHAT=1
```

The model key and model name remain mandatory.

Normal OpenDots behavior is unchanged outside the explicit test mode.

### 3. Human Gate locator ambiguity

Once the full path worked, Playwright found two controls containing `stay_free`:

- the explicit choice;
- the declared safe-default button.

The E2E was changed to click only the button inside:

```text
.mado-gate-choices
```

This both removed locator ambiguity and made the test prove the explicit-human-choice path rather than the safe-default path.

## Safety boundary

The test-only behavior is guarded by:

```text
MADO_DETERMINISTIC_CHAT=1
```

Without it:

- OpenDots retains its normal Intelligence requirements;
- conversation creation stays on its normal path;
- the deterministic model route is not selected;
- the M1.9 DotAgent readiness exception is inactive.

MADO writes still use the normal verified path:

```text
OpenDots server tool
  -> mado-cockpit-caller.ts
  -> child_process.spawn(shell=false)
  -> Python M1.3 Tool Surface
  -> M1.2 runtime / Operator
```

The Human Gate card itself still does not mutate Cockpit directly.

## M1.9 status

```text
MCC-M1.9 OpenDots Browser Chat / Deterministic Intelligence Shim
status: VERIFIED

normal OpenDots home UI: passed
normal Start a conversation flow: passed
local CopilotRuntime SSE mode: passed
real DotAgent: passed
real mado_check_mission: passed
normal Mission Card: passed
normal Human Gate card: passed
explicit stay_free click: passed
HITL resume: passed
real mado_answer_human_gate: passed
final assistant response: passed
Cockpit persisted state: passed
visual evidence: passed
Cockpit CI: 99 passed
M1.5 regression dogfood: passed
```
