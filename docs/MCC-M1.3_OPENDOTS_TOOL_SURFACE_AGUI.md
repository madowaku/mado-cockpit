# MCC-M1.3 OpenDots Tool Surface / AG-UI Bridge

MCC-M1.3 turns the narrow MCC-M1.2 runtime envelope into a Dot-friendly tool surface that matches OpenDots' current `defineTool(...) -> TanStack AI -> AG-UI` execution path.

OpenDots remains the interaction surface. MADO Cockpit remains the authority for mission state, deterministic orchestration, Human Question Gates, evidence, and QA.

## Tool surface

| Tool | Effect | Side effect |
| --- | --- | --- |
| `mado_check_mission` | Show mission state, next action, and open Human Gate | none |
| `mado_advance_mission` | Run deterministic `Operator.advance` | orchestration state only |
| `mado_answer_human_gate` | Apply an explicit human choice or declared safe default | resolves one Human Gate |
| `mado_show_evidence` | Show Builder/QA evidence and result metadata | none |
| `mado_show_qa_result` | Show handoff, latest QA result, and verdict | none |

No M1.3 tool launches a model, starts a shell, binds a capability, submits implementation evidence, publishes content, or performs arbitrary CLI execution.

## AG-UI shape

OpenDots currently builds server tools with CopilotKit `defineTool`, converts them to TanStack AI tools, and lets the existing runtime stream tool calls/results through AG-UI.

The copy-ready bridge is:

```text
integrations/opendots/mado-cockpit-tools.ts
```

It can be appended to OpenDots' `serverTools` beside page and computer tools. No AG-UI fork is required.

```text
Dot model
   |
   | mado_check_mission(...)
   v
OpenDots defineTool executor
   |
   | mado.opendots.tool-call.v1
   v
MCC-M1.3 Tool Surface
   |
   +-- M1.2 Runtime Adapter
   |      +-- operator.status
   |      +-- operator.advance
   |      +-- gate.resolve
   |
   +-- read-only projections
          +-- evidence
          +-- QA
   |
   v
mado.opendots.tool-result.v1
   |
   v
AG-UI tool result / renderer
```

## Tool call envelope

```json
{
  "schema": "mado.opendots.tool-call.v1",
  "tool_call_id": "call-123",
  "tool_name": "mado_check_mission",
  "context": {
    "dot_id": "scout",
    "space_id": "space-alpha",
    "thread_id": "thread-42"
  },
  "arguments": {
    "operator_id": "opr_123"
  }
}
```

The M1.3 surface derives a stable M1.2 request ID from `tool_call_id + tool_name + Dot + thread`. If the same AG-UI tool execution is replayed, M1.2 returns its stored receipt instead of applying `advance` or Gate resolution twice.

## Safe projection

The OpenDots result intentionally excludes internal Cockpit execution details such as:

- worker worktree paths;
- session trace paths;
- handoff snapshot paths;
- evidence file paths;
- source snapshot digests;
- arbitrary result change paths.

Evidence items expose only safe metadata such as kind, SHA-256, size, source class, and description.

## Presentation envelope

Every successful tool returns both machine data and renderer hints:

```json
{
  "schema": "mado.opendots.tool-result.v1",
  "surface_version": "MCC-M1.3",
  "tool_call_id": "call-123",
  "tool_name": "mado_check_mission",
  "ok": true,
  "data": {},
  "presentation": {
    "kind": "mission_status",
    "title": "Mission MCC-DEMO",
    "status": "awaiting_builder",
    "summary": "awaiting_builder. Next: launch_builder",
    "facts": []
  }
}
```

Current presentation kinds are:

```text
mission_status
mission_advanced
human_gate_resolved
evidence_summary
qa_result
```

An OpenDots client can use `useRenderTool` for the five `mado_*` names and render these hints as cards. Human Gate choices remain normal tool arguments, so the Dot must wait for the owner's explicit answer before invoking `mado_answer_human_gate`.

## Local tool fixture

Print the portable tool catalog:

```bash
python -m mado_cockpit.opendots_tools --catalog
```

Execute one tool call over stdin:

```bash
python -m mado_cockpit.opendots_tools --root . < tool-call.json
```

The included TypeScript bridge deliberately accepts a `MadoToolCaller` function rather than hard-coding HTTP, MCP, or credentials. The caller can later be backed by the MCC-M1.1 secure tunnel. This keeps tool semantics independent from transport.

## OpenDots integration

In OpenDots `DotAgent`, append the five tools to `serverTools`:

```ts
const serverTools = [
  ...tools,
  ...pageTools(pages),
  ...madoCockpitTools(
    {
      dotId: dot.id,
      spaceId: dot.spaceId,
      threadId: input.threadId,
    },
    callMadoCockpit,
  ),
  ...(computer.configured
    ? computerTools(computer, dot.id, check, controller.signal)
    : []),
];
```

The existing `tanstackTools(serverTools)` path then carries the calls through the same AG-UI runtime used by OpenDots' page, research, and computer tools.

## Golden fixtures

`tests/test_opendots_tools.py` verifies:

```text
five bounded tools                  -> stable catalog
mission status                      -> safe projection
AG-UI replay                        -> no duplicate advance
Human Gate explicit choice          -> M1.2 gate.resolve
ambiguous Gate choice               -> rejected
evidence metadata                   -> no internal paths
QA result/verdict                   -> safe projection
open Human Gate                     -> visible to Dot
unknown execution tool              -> rejected
```
