# MCC-M1.7 Real Conversation Replay Result — 2026-10-04

MCC-M1.7 was validated against a fresh real checkout of `CopilotKit/OpenDots@main` using the real OpenDots `DotAgent.run()` loop and a deterministic local OpenAI-compatible model fixture.

## Passing run

- Workflow: `OpenDots Conversation Replay`
- Run ID: `37170743602`
- Result: `success`
- mado-cockpit commit: `65d824a3783913a318aa6b5b0fa7b5bf31b9bc23`
- Evidence artifact: `opendots-conversation-replay-evidence`
- Artifact ID: `11291062222`
- Artifact SHA-256: `bdca1f180a6f0d6361a4a3771769bfcff37d2632dd21ed0d39702960dc2d3d93`

At the same commit:

```text
Cockpit CI                         90 passed
M1.5 real OpenDots dogfood         success
M1.7 real conversation replay      success
```

## Real conversation fixture

The passing run created:

```text
operator_id  opr_49ba8424f23b
gate_id      gate_c3dc8569fe6f
thread_id    mcc-m1.7-real-conversation
```

The real Cockpit Human Gate was:

```text
question:
Enable the paid provider for this replay?

reason:
The paid provider may create charges.

materiality:
cost

choices:
stay_free
enable_paid

recommendation:
stay_free

safe_default:
stay_free
```

## Run 1

The real OpenDots conversation received:

```text
Check MADO mission opr_49ba8424f23b and continue safely.
```

The real `DotAgent.run()` emitted these tool calls in order:

```text
mado_check_mission
mado_review_human_gate
```

The Human Gate arguments were not hard-coded by the model fixture.

They were parsed from the actual `mado_check_mission` server-tool result, including the generated Gate ID:

```text
gate_c3dc8569fe6f
```

The first run recorded:

```text
human_gate_result_present = false
```

That is the key M1.7 assertion: the agent paused at the client-side Human Gate and did not auto-resolve the human-owned decision.

## Human decision

Between the two agent runs the replay supplied the same shape a frontend Human-in-the-Loop tool returns:

```json
{
  "operator_id": "opr_49ba8424f23b",
  "gate_id": "gate_c3dc8569fe6f",
  "choice": "stay_free",
  "choose_for_me": false,
  "note": "Keep the zero-cost path."
}
```

## Run 2

The second real `DotAgent.run()` received the prior assistant Human Gate call plus the human `role: tool` result.

It then emitted:

```text
mado_answer_human_gate
```

The server tool executed through the normal M1.5/M1.3 bridge.

Final assistant text:

```text
Mission resumed on the free path. Cockpit is ready for Builder work.
```

## Persisted Cockpit result

After the second agent run, the Python harness independently reopened the Operator and verified:

```text
status       awaiting_builder
human_gate   null
next_action  launch_or_wait_for_builder
```

The same generated Operator and Gate IDs flowed through:

```text
Cockpit fixture
  -> mado_check_mission result
  -> model-facing Human Gate args
  -> human tool result
  -> mado_answer_human_gate
  -> persisted Operator state
```

## Model / network behavior

The deterministic provider performed exactly:

```text
4 model calls
```

Those four calls correspond to:

1. request `mado_check_mission`;
2. receive its result and request `mado_review_human_gate`;
3. receive the human result and request `mado_answer_human_gate`;
4. receive the Gate resolution and return final assistant text.

The replay fetch policy was:

```text
network_policy = model_fixture_only
```

Any fetch request not targeting `*/chat/completions` fails the replay.

The MADO bridge itself continued to use:

```text
Node
  -> child_process.spawn(shell=false)
  -> Python
  -> M1.3 Tool Surface
  -> Cockpit
```

## Real OpenDots components exercised

The replay used real upstream components rather than a hand-built fake agent loop:

- `DotAgent`;
- `BuiltInAgent`;
- TanStack AI chat loop;
- OpenAI-compatible TanStack adapter;
- AG-UI tool events;
- frontend client-tool pause semantics;
- canonical `mado_review_human_gate`;
- M1.5 server tools;
- M1.5 local-process caller;
- M1.3 tool surface;
- real OperatorManager / HumanQuestionGateManager.

The conversation thread was bound through a real OpenDots `WorkspaceStore`.

## Scope boundary

M1.7 validates the real **agent conversation layer**, not the browser Chat component.

M1.6 already validated the browser renderer and Human Gate click path.

Together:

```text
M1.6
browser UI -> human click -> Cockpit

M1.7
real DotAgent conversation -> tools -> HITL pause/resume -> Cockpit
```

A later Browser Chat replay can combine both axes into the normal Chat composer if needed, but M1.7 does not require an external CopilotKit Intelligence service to establish the agent/tool/HITL contract.

## M1.7 status

```text
MCC-M1.7 OpenDots Real Conversation / Deterministic Agent Replay
status: VERIFIED

real DotAgent.run: passed
real OpenDots thread: passed
mado_check_mission: passed
Human Gate pause: passed
human tool result replay: passed
mado_answer_human_gate: passed
final assistant response: passed
Cockpit persisted state: passed
network outside model fixture: none
Cockpit CI: 90 passed
M1.5 regression dogfood: passed
```
