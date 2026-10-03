# MCC-M1.4 OpenDots Renderer Cards / Human Gate UI

MCC-M1.4 makes the M1.3 tool surface visible and operable inside an OpenDots conversation.

It adds two distinct UI classes:

1. read/render cards for mission, evidence, QA, and completed Human Gate actions;
2. a dedicated frontend-only Human Question Gate review tool that pauses the Dot for a real user decision.

The important boundary is that **the Human Gate card does not mutate Cockpit**.

## Human Gate flow

```text
mado_check_mission
        |
        | open human_gate metadata
        v
Dot calls mado_review_human_gate
        |
        v
OpenDots useHumanInTheLoop
        |
        | user clicks / types
        v
HITL tool result
        |
        | exact operator_id + gate_id + decision
        v
Dot calls mado_answer_human_gate
        |
        v
M1.3 validates current gate_id
        |
        v
M1.2 gate.resolve
        |
        v
Cockpit resumes
```

This is intentionally two-phase. A renderer button only returns a decision to the conversation. It cannot directly call the Cockpit write path.

## Files

Copy-ready integration files:

```text
integrations/opendots/mado-human-gate.ts
integrations/opendots/mado-cockpit-renderers.tsx
integrations/opendots/mado-cockpit-renderers.css
```

The existing server bridge remains:

```text
integrations/opendots/mado-cockpit-tools.ts
```

## Renderer cards

`useMadoCockpitRenderers()` registers renderers for:

```text
mado_check_mission
mado_advance_mission
mado_answer_human_gate
mado_show_evidence
mado_show_qa_result
```

The cards consume only the M1.3 `presentation` envelope. They do not inspect Cockpit filesystem paths or raw Operator workspaces.

## Human Question Gate tool

The frontend-only tool is:

```text
mado_review_human_gate
```

Its arguments are copied from `mado_check_mission.data.human_gate` plus `operator_id`.

The card supports:

- enumerated choices with impact text;
- free-form Human Gates with a text answer;
- a visible Cockpit recommendation without auto-selection;
- a declared safe-default button only when `allow_choose_for_me` is true;
- an optional human note;
- transport failure recovery without leaving controls permanently disabled.

The result intentionally matches the writable subset of `mado_answer_human_gate`:

```json
{
  "operator_id": "opr_123",
  "gate_id": "gate_123",
  "choice": "stay_free",
  "choose_for_me": false,
  "note": "Keep the zero-cost path."
}
```

For a safe-default click:

```json
{
  "operator_id": "opr_123",
  "gate_id": "gate_123",
  "choose_for_me": true
}
```

## OpenDots wiring

### 1. Shared frontend tool

Copy `mado-human-gate.ts` into an OpenDots shared module and import `madoHumanGateReviewTool` in `DotAgent`.

When forwarding client tools into the inner agent, allow both the existing page review tool and the MADO gate review tool:

```ts
tools:
  !this.channel
    ? input.tools.filter((tool) =>
        [pageReviewTool.name, madoHumanGateReviewTool.name].includes(tool.name),
      )
    : [],
```

### 2. Dot prompt contract

Add this rule to the Dot system prompt:

```text
When mado_check_mission reports an open human_gate, never infer or manufacture the decision.
Call mado_review_human_gate with the exact gate metadata and wait for its result.
Then pass the returned operator_id, gate_id, choice or choose_for_me, and note unchanged to
mado_answer_human_gate. Do not call mado_answer_human_gate before the review tool completes.
```

### 3. Chat renderers

Inside the OpenDots `Chat` component call:

```ts
useMadoCockpitRenderers();
```

and include the renderer CSS after the base OpenDots styles.

The existing CopilotKit `useRenderTool` and `useHumanInTheLoop` transports then carry the cards without a custom AG-UI protocol fork.

## Gate identity binding

M1.4 extends `mado_answer_human_gate` with an optional `gate_id`.

When present, the server surface first reads the current Operator status and verifies that the supplied ID is still the current open Human Question Gate. A stale card cannot resolve a later Gate by accident.

The derived M1.2 request receipt now includes the underlying runtime action, so one M1.4 tool call can safely perform:

```text
operator.status -> validate gate identity
gate.resolve    -> apply exact decision
```

without request-ID collision.

## Replay and failure behavior

- repeated AG-UI server tool calls still reuse M1.2 receipts;
- a stale `gate_id` fails before `gate.resolve`;
- the HITL card never auto-selects the recommendation;
- safe default requires a human button click;
- if `respond()` is not ready or rejects, the card shows an error and re-enables controls;
- completed HITL calls render as recorded rather than showing active controls.

## Fixture

```text
fixtures/opendots/mcc-m1.4-renderer-contract.json
```

locks the expected renderer names and two-phase Human Gate contract.
