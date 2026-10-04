# MCC-M1.7 OpenDots Real Conversation / Deterministic Agent Replay

MCC-M1.7 validates the MADO integration through the real OpenDots `DotAgent.run()` conversation loop without using an external model provider.

## Goal

M1.6 proved the renderer and Human Gate click path in a real Chromium session.

M1.7 proves the agent-side conversational loop:

```text
user message
  -> real OpenDots DotAgent.run()
  -> deterministic OpenAI-compatible model fixture
  -> mado_check_mission
  -> real MADO Cockpit
  -> model receives real mission tool result
  -> mado_review_human_gate frontend tool call
  -> run stops for human input

human tool result: stay_free
  -> second real DotAgent.run()
  -> deterministic model fixture
  -> mado_answer_human_gate
  -> real MADO Cockpit
  -> final assistant text
```

This is intentionally a two-run replay because frontend Human-in-the-Loop tools are client-side tools. OpenDots/TanStack pauses after the model calls the Human Gate tool. The client later returns a `role: tool` result and starts the next agent run.

## What is real

The replay uses the real upstream OpenDots:

- `DotAgent`;
- `BuiltInAgent`;
- TanStack AI adapter and agent loop;
- AG-UI tool events;
- M1.5 `madoCockpitTools`;
- M1.5 Node subprocess caller;
- M1.3 Python Tool Surface;
- real Cockpit Operator and Human Question Gate.

The OpenDots conversation thread is also real. The replay creates an in-memory OpenDots `WorkspaceStore`, binds a conversation thread to the default Dot, and runs the real Dot agent twice.

## What is deterministic

Only the model endpoint is replaced.

The replay overrides `fetch` and allows exactly:

```text
*/chat/completions
```

Any other network request fails the replay immediately.

The scripted provider does not contain a fixed Gate ID. After the first server tool executes, it parses the actual `mado_check_mission` tool result and copies the returned Human Gate metadata into the `mado_review_human_gate` call.

Therefore this sequence cannot pass if the real Cockpit tool bridge does not work.

## Run 1

The user message is conceptually:

```text
Check MADO mission <operator_id> and continue safely.
```

The deterministic model first calls:

```text
mado_check_mission
```

The server tool executes through M1.5 and returns the real Operator state.

The deterministic model then reads:

```text
data.human_gate
```

and calls the canonical frontend tool:

```text
mado_review_human_gate
```

with the real:

- operator ID;
- Gate ID;
- question;
- reason;
- materiality;
- choices;
- impacts;
- recommendation;
- safe default.

The first agent run must finish without a `TOOL_CALL_RESULT` for the Human Gate. That proves the agent did not auto-resolve the human-owned decision.

## Human result

The replay then injects the same AG-UI shape a client HITL resolution produces:

```json
{
  "role": "tool",
  "toolCallId": "human-review",
  "content": {
    "operator_id": "<real operator>",
    "gate_id": "<real gate>",
    "choice": "stay_free",
    "choose_for_me": false,
    "note": "Keep the zero-cost path."
  }
}
```

## Run 2

The second real `DotAgent.run()` receives the prior assistant Human Gate call plus the human tool result.

The deterministic model calls:

```text
mado_answer_human_gate
```

using the returned Gate ID and choice unchanged.

The real MADO tool executes and the deterministic model finishes with assistant text confirming that the mission resumed on the free path.

## Final Cockpit contract

The Python harness independently checks:

```text
status      awaiting_builder
human_gate  null
```

So the replay must agree at three layers:

1. AG-UI event sequence;
2. model-facing tool results and tool calls;
3. persisted Cockpit Operator state.

## Evidence

The replay writes:

```text
.mado/cockpit/integrations/opendots/conversation-replay/<run-id>/
├─ conversation-replay.json
├─ conversation-replay.json.stdout
└─ cockpit-final.json
```

The JSON records both agent runs, tool-call names, the real Human Gate arguments, the explicit human decision, final assistant text, and model request count.

## CI

Workflow:

```text
.github/workflows/opendots-conversation-replay.yml
```

It checks out a fresh real `CopilotKit/OpenDots@main`, applies the verified M1.5 overlay, adds only the bounded replay script, typechecks the real OpenDots tree, executes the two-run conversation, verifies Cockpit state, and uploads evidence.

## Network policy

```text
model fixture endpoint only
all other fetch requests -> fail closed
```

The MADO tool bridge itself is not HTTP. It continues to use the M1.5 local subprocess boundary:

```text
Node -> spawn(shell=false) -> Python -> Cockpit
```
