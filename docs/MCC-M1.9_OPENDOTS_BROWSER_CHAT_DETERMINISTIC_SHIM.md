# MCC-M1.9 OpenDots Browser Chat / Deterministic Intelligence Shim

MCC-M1.9 combines the two verified axes from M1.6 and M1.7:

- M1.6: real Chromium + Human Gate card click;
- M1.7: real OpenDots DotAgent conversation + HITL pause/resume.

M1.9 drives the **normal OpenDots Chat composer** end to end without an external model provider or CopilotKit Intelligence service.

## Runtime shape

```text
Chromium
  -> normal OpenDots App
  -> Start a conversation
  -> normal Chat component
  -> CopilotKitProvider /api/copilotkit
  -> local CopilotRuntime (SSE mode, no Intelligence)
  -> real DotAgent
  -> local OpenAI-compatible deterministic shim
  -> MADO server tools
  -> Node subprocess caller
  -> Python M1.3 Tool Surface
  -> real Cockpit
  -> Human Gate frontend tool
  -> normal M1.4 Human Gate card
  -> explicit human click
  -> resumed CopilotKit run
  -> mado_answer_human_gate
  -> final assistant text
```

## Why this is an Intelligence shim

Normal OpenDots requires CopilotKit Intelligence for persistent conversation creation and its runtime configuration.

For M1.9 only, when:

```text
MADO_DETERMINISTIC_CHAT=1
```

the overlay changes that boundary to:

- instantiate `CopilotRuntime({ agents })` without an Intelligence client;
- use the runtime's local SSE mode;
- bind new conversation IDs directly into the real OpenDots `WorkspaceStore`;
- report setup as locally usable so the normal composer is enabled;
- keep the normal `/api/copilotkit` client/runtime contract.

No production path changes unless the explicit environment flag is present.

## Deterministic model shim

The model endpoint is the same OpenDots server:

```text
OPENAI_BASE_URL=http://127.0.0.1:4310/api/mado-chat-shim/v1
```

The shim implements only:

```text
POST /api/mado-chat-shim/v1/chat/completions
```

and emits OpenAI-compatible SSE chunks.

Its state is inferred from the real conversation messages and tool results:

```text
user prompt
  -> mado_check_mission

mission tool result
  -> mado_review_human_gate

human tool result
  -> mado_answer_human_gate

gate answer tool result
  -> final assistant text
```

The Gate ID is never hard-coded. It is copied from the real `mado_check_mission` result.

## Normal browser interaction

The Playwright script does not load an E2E-only page.

It opens:

```text
/
```

and uses the normal OpenDots controls:

```text
textbox: Start a conversation
button:  Start conversation
```

The prompt is:

```text
Check MADO mission <operator_id> and continue safely.
```

The browser then waits for the normal MADO Human Gate renderer, clicks:

```text
stay_free
```

and waits for the normal Chat transcript to contain:

```text
Mission resumed on the free path. Cockpit is ready for Builder work.
```

## Real Cockpit fixture

The harness creates a real Operator with:

```text
question:
Enable the paid provider for this browser chat?

materiality:
cost

choices:
stay_free
enable_paid
```

Expected state transition:

```text
awaiting_human
  -> browser Human Gate click
  -> awaiting_builder
  -> human_gate = null
```

The final state is independently reopened and checked from Python.

## Upstream drift

M1.9 inherits the M1.5 upstream lock and additionally pins:

```text
src/server/platform.ts
src/server/app.ts
```

in:

```text
fixtures/opendots/mcc-m1.9-upstream-lock.json
```

Drift fails closed before patching unless an intentional local experiment uses `--allow-drift`.

## Evidence

The workflow stores:

```text
01-normal-chat-human-gate.png
02-normal-chat-resumed.png
browser-chat-result.json
cockpit-final.json
server.log
```

## CI workflow

```text
.github/workflows/opendots-browser-chat.yml
```

It uses a fresh `CopilotKit/OpenDots@main`, applies the verified M1.5 overlay plus the bounded M1.9 shim, typechecks and builds the real OpenDots tree, starts production OpenDots, and executes Chromium against the normal Chat UI.

## Production boundary

The deterministic runtime and model route exist for dogfood only.

Without:

```text
MADO_DETERMINISTIC_CHAT=1
```

OpenDots retains its normal CopilotKit Intelligence and model-provider behavior.
